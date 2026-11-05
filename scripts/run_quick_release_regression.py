"""Run a safe, random 12-case pre-release billing smoke suite.

The selector checks exact billing-month + room + charge-item keys before
pytest. Per-case cleanup remains enabled; broad recovery sweeps are disabled so
unrelated historical bills are never touched by this targeted run.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
import os
import random
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MONTH = "2026-08"
DEPOSIT_CASE_IDS = (
    "YSF-BILL-DEPOSIT-1021",
    "YSF-BILL-DEPOSIT-002",
    "YSF-BILL-DEPOSIT-003",
    "YSF-BILL-DEPOSIT-004",
    "YSF-BILL-DEPOSIT-005",
    "YSF-BILL-DEPOSIT-006",
)
DEPOSIT_ROOMS = {
    "YSF-BILL-DEPOSIT-1021": "1021",
    "YSF-BILL-DEPOSIT-002": "1022",
    "YSF-BILL-DEPOSIT-003": "1023",
    "YSF-BILL-DEPOSIT-004": "1024",
    "YSF-BILL-DEPOSIT-005": "1025",
    "YSF-BILL-DEPOSIT-006": "1026",
}


@dataclass(frozen=True)
class Candidate:
    group: str
    nodeid: str
    route: str
    case_id: str
    project_name: str
    room_path: str
    charge_item: str
    billing_month: str = MONTH

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.billing_month, self.room_path, self.charge_item)


@lru_cache(maxsize=1)
def _workbook_index() -> tuple[dict[str, str], dict[str, object]]:
    """Read the workbook once, avoiding repeated full XLSX scans per case."""
    import re

    from openpyxl import load_workbook

    from src.config.excel_data import (
        DEFAULT_WORKBOOK,
        ChargeScenarioData,
        _header_map,
        _text,
    )

    workbook = load_workbook(DEFAULT_WORKBOOK, read_only=True, data_only=True)
    try:
        case_sheet = workbook["用例清单"]
        case_headers = _header_map(case_sheet)
        case_col = case_headers["用例编号"] - 1
        reference_col = case_headers["场景引用/覆盖项"] - 1
        case_scenarios: dict[str, str] = {}
        for row in case_sheet.iter_rows(min_row=2, values_only=True):
            case_id = _text(row[case_col])
            if not case_id:
                continue
            match = re.search(
                r"(?:^|\n)SCENARIO_ID\s*=\s*([^\s]+)",
                _text(row[reference_col]),
            )
            if match:
                case_scenarios[case_id] = match.group(1).strip()

        scenario_sheet = workbook["收费场景配置"]
        scenario_headers = _header_map(scenario_sheet)
        fields = (
            "场景编号", "环境", "客户号", "维护状态", "是否启用",
            "PROJECT_NAME", "ROOM_PATH", "CHARGE_TYPE", "CHARGE_ITEM",
            "收费标准", "计费公式", "计算参数", "建议测试账期", "减免配置",
            "预期原始金额", "预期减免金额", "预期应收金额",
        )
        columns = {name: scenario_headers[name] - 1 for name in fields}
        scenarios: dict[str, object] = {}
        for row in scenario_sheet.iter_rows(min_row=2, values_only=True):
            scenario_id = _text(row[columns["场景编号"]])
            if not scenario_id:
                continue
            environment = _text(row[columns["环境"]])
            customer_id = _text(row[columns["客户号"]])
            key = f"{environment}|{customer_id}|{scenario_id}"
            if key in scenarios:
                raise ValueError(f"场景编号 {scenario_id!r} 重复")
            status = _text(row[columns["维护状态"]])
            if not status.startswith("已核验") or _text(row[columns["是否启用"]]) != "是":
                continue
            values = {
                name: _text(row[columns[name]])
                for name in fields[5:9]
            }
            missing = [name for name, value in values.items() if not value]
            if missing:
                raise ValueError(
                    f"场景 {scenario_id!r} 缺少步骤变量：{', '.join(missing)}"
                )
            scenarios[key] = ChargeScenarioData(
                scenario_id=scenario_id,
                environment=environment,
                customer_id=customer_id,
                project_name=values["PROJECT_NAME"],
                room_path=values["ROOM_PATH"],
                charge_type=values["CHARGE_TYPE"],
                charge_item=values["CHARGE_ITEM"],
                charge_standard=_text(row[columns["收费标准"]]),
                formula=_text(row[columns["计费公式"]]),
                calculation_parameters=_text(row[columns["计算参数"]]),
                suggested_billing_month=_text(row[columns["建议测试账期"]]),
                discount_config=_text(row[columns["减免配置"]]),
                expected_original_amount=_text(row[columns["预期原始金额"]]),
                expected_discount_amount=_text(row[columns["预期减免金额"]]),
                expected_receivable_amount=_text(row[columns["预期应收金额"]]),
            )
        return case_scenarios, scenarios
    finally:
        workbook.close()


def _candidate(
    *, group: str, filename: str, test_name: str, case_id: str, route: str
) -> Candidate:
    from src.config.excel_data import ChargeScenarioData

    case_scenarios, scenarios = _workbook_index()
    scenario_id = case_scenarios.get(case_id)
    if not scenario_id:
        raise ValueError(f"用例 {case_id!r} 未配置场景引用")
    key = f"{os.environ['TEST_ENV']}|{os.environ['CUSTOMER_ID']}|{scenario_id}"
    scenario = scenarios.get(key)
    if not isinstance(scenario, ChargeScenarioData):
        raise ValueError(
            f"用例 {case_id!r} 引用的场景不存在、未核验、未启用，或不属于当前客户"
        )
    return Candidate(
        group=group,
        nodeid=f"tests/billing/{filename}::{test_name}[chromium-{case_id}]",
        route=route,
        case_id=case_id,
        project_name=scenario.project_name,
        room_path=scenario.room_path,
        charge_item=scenario.charge_item,
    )


def _case_ids(prefix: str) -> list[str]:
    case_scenarios, _ = _workbook_index()
    return sorted(case_id for case_id in case_scenarios if case_id.startswith(prefix))


def _build_pools() -> list[tuple[str, list[Candidate]]]:
    periodic_rooms = [
        *range(1003, 1012),
        *range(1048, 1059),
    ]
    meter_rooms = [
        1033, 1034, 1035, 1037, 1038,
        1040, 1041, 1042, 1043, 1045, 1046,
    ]
    bill_periodic_ids = set(_case_ids("YSF-BILL-PERIODIC-"))
    bill_meter_ids = set(_case_ids("YSF-BILL-METER-"))
    calc_periodic_ids = set(_case_ids("YSF-CALC-PERIODIC-"))
    calc_meter_ids = set(_case_ids("YSF-CALC-METER-"))
    calc_temp_ids = set(_case_ids("YSF-CALC-TEMP-"))
    ledger_temp_ids = set(_case_ids("YSF-BILL-TEMP-"))

    def make_pool(
        group: str,
        ids: list[str],
        filename: str,
        test_name: str,
        route: str,
        allowed_rooms: set[str] | None = None,
    ) -> list[Candidate]:
        result: list[Candidate] = []
        for case_id in ids:
            room = case_id.rsplit("-", 1)[-1]
            if allowed_rooms is not None and room not in allowed_rooms:
                continue
            result.append(
                _candidate(
                    group=group,
                    filename=filename,
                    test_name=test_name,
                    case_id=case_id,
                    route=route,
                )
            )
        return result

    def make_deposit_pool(group: str, test_name: str, route: str) -> list[Candidate]:
        return [
            Candidate(
                group=group,
                nodeid=(
                    "tests/billing/test_create_deposit_bill.py::"
                    f"{test_name}[chromium-{case_id}]"
                ),
                route=route,
                case_id=case_id,
                project_name="云收费UI自动化",
                room_path=f"A栋/1层/{DEPOSIT_ROOMS[case_id]}",
                charge_item="押金类收费项",
            )
            for case_id in DEPOSIT_CASE_IDS
        ]

    periodic_suffixes = {str(room) for room in periodic_rooms}
    meter_suffixes = {str(room) for room in meter_rooms}
    pools: list[tuple[str, list[Candidate]]] = [
        (
            "账单中心-周期类",
            make_pool(
                "账单中心-周期类", sorted(bill_periodic_ids),
                "test_create_periodic_center_bills.py",
                "test_create_periodic_bill_and_cleanup", "bill_center",
                periodic_suffixes,
            ),
        ),
        (
            "账单中心-仪表类",
            make_pool(
                "账单中心-仪表类", sorted(bill_meter_ids),
                "test_create_meter_bills.py",
                "test_create_meter_bill_and_assert_amount", "bill_center",
                meter_suffixes,
            ),
        ),
        (
            "计费出账-周期类",
            make_pool(
                "计费出账-周期类", sorted(calc_periodic_ids),
                "test_calculate_periodic_bill.py",
                "test_calculate_periodic_bill_then_approve_and_cleanup",
                "bill_center", periodic_suffixes,
            ),
        ),
        (
            "计费出账-仪表类",
            make_pool(
                "计费出账-仪表类", sorted(calc_meter_ids),
                "test_calculate_periodic_bill.py",
                "test_calculate_periodic_bill_then_approve_and_cleanup",
                "bill_center", meter_suffixes,
            ),
        ),
        (
            "计费出账-临时类",
            make_pool(
                "计费出账-临时类", sorted(calc_temp_ids),
                "test_calculate_temporary_bill.py",
                "test_calculate_temporary_bill_then_cleanup", "bill_center",
            ),
        ),
        (
            "计费出账-押金类",
            make_deposit_pool(
                "计费出账-押金类",
                "test_deposit_bill_in_calculation_then_bill_center_cleanup",
                "bill_center",
            ),
        ),
        (
            "临时台账-临时类",
            make_pool(
                "临时台账-临时类", sorted(ledger_temp_ids),
                "test_create_temporary_bill.py",
                "test_create_temporary_bill_assert_amount_and_cleanup", "ledger",
            ),
        ),
        (
            "临时台账-押金类",
            make_deposit_pool(
                "临时台账-押金类",
                "test_deposit_bill_in_temporary_ledger_then_room_cleanup", "ledger",
            ),
        ),
    ]

    # Public-share billing is a business dimension routed through existing
    # entrypoints. Select a simple periodic ratio/amount pair at Bill Center
    # and a full-month household meter pair through Billing Issuance.
    from src.domain.public_share_charge import PUBLIC_SHARE_BILL_CASES

    periodic_pairs: dict[tuple[str, str], str] = {}
    for case in PUBLIC_SHARE_BILL_CASES:
        if case.method_key not in {"RATIO", "AMOUNT"}:
            continue
        periodic_pairs[case.pair] = case.scheme_key
    periodic_share_groups: list[tuple[str, list[Candidate]]] = []
    for pair, _scheme in periodic_pairs.items():
        cases = [
            _candidate(
                group="公摊出账-周期类",
                filename="test_create_periodic_center_bills.py",
                test_name="test_create_periodic_bill_and_cleanup",
                case_id=f"YSF-BILL-PUBLIC-SHARE-PERIODIC-{room}",
                route="bill_center",
            )
            for room in pair
        ]
        periodic_share_groups.append((f"公摊周期对-{pair[0]}-{pair[1]}", cases))

    from src.config.instrument_public_share_data import load_instrument_cases

    meter_pairs: dict[tuple[str, str], list[Candidate]] = {}
    for scheme in load_instrument_cases(regression=False):
        if scheme.method != "按户分摊" or scheme.incomplete_month_rule != "按满月计费":
            continue
        pair = tuple(scheme.rooms)
        meter_pairs[pair] = [
            Candidate(
                group="公摊出账-仪表类",
                nodeid=(
                    "tests/billing/test_public_share_meter_billing.py::"
                    # This test parametrization intentionally exposes only
                    # the room suffix as its readable id; pytest-playwright
                    # adds the browser prefix around that id.
                    f"test_calculation_public_share_meter_regression[chromium-{room.rsplit('/', 1)[-1]}]"
                ),
                route="bill_center",
                case_id=f"YSF-CALC-PUBLIC-SHARE-METER-{room}",
                project_name="云收费UI自动化",
                room_path=f"A栋/1层/{room}",
                charge_item=scheme.charge_item,
            )
            for room in pair
        ]
    if not periodic_share_groups or not meter_pairs:
        raise ValueError("未能从维护数据中构造周期/仪表公摊代表房间对")

    pools.extend(
        [
            ("公摊出账-周期类", periodic_share_groups),
            ("公摊出账-仪表类", list(meter_pairs.values())),
        ]
    )
    return pools


def _restore_session_storage(
    context, session_file: Path, auth_file: Path, base_url: str
) -> None:
    from urllib.parse import urlparse

    payload = json.loads(session_file.read_text(encoding="utf-8"))
    parsed_url = urlparse(base_url)
    expected_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
    if not parsed_url.scheme or not parsed_url.netloc:
        raise ValueError("测试环境 BASE_URL 缺少有效协议或主机名")
    auth_state = json.loads(auth_file.read_text(encoding="utf-8"))
    saved_origins = {
        item.get("origin")
        for item in auth_state.get("origins", [])
        if isinstance(item, dict) and item.get("origin")
    }
    # Never inject a session snapshot captured from HTTP into an HTTPS page
    # (or from another origin). That stale cross-origin state can invalidate
    # a fresh login during later Home navigations.
    if saved_origins and expected_origin not in saved_origins:
        return
    storage_json = json.dumps(payload, ensure_ascii=False)
    origin_json = json.dumps(expected_origin)
    context.add_init_script(
        "(() => { const storage = " + storage_json + "; const host = "
        + origin_json
        + "; const marker = '__codex_saved_session_storage_restored_v1__'; "
        + "if (location.origin === host && sessionStorage.getItem(marker) !== '1') { "
        + "for (const [k,v] of Object.entries(storage)) sessionStorage.setItem(k, v); "
        + "sessionStorage.setItem(marker, '1'); } })();"
    )


def _run_preflight(pools: list[tuple[str, list[Candidate]]], role: str) -> tuple[list[Candidate], int]:
    from playwright.sync_api import sync_playwright

    from src.config.accounts import get_account_auth_profile
    from src.config.settings import settings
    from src.pages.billing_calculation_page import BillingCalculationPage
    from src.pages.billing_center_page import BillingCenterPage
    from src.pages.portal_page import PortalPage
    from src.pages.temporary_ledger_page import TemporaryLedgerPage
    from scripts.test_instrument_public_share_billing import (
        _has_pending_target_bills,
    )

    profile = get_account_auth_profile(
        ROOT, role, settings.test_environment, settings.master_customer_id
    )
    if not profile.auth_file.exists() or not profile.session_file.exists():
        raise FileNotFoundError("缺少所选环境/客户/账号的已保存登录状态")

    selected: list[Candidate] = []
    reserved_keys: set[tuple[str, str, str]] = set()
    rejected_existing = 0
    chooser = random.SystemRandom()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=str(profile.auth_file),
            viewport={"width": 1440, "height": 900},
        )
        _restore_session_storage(
            context, profile.session_file, profile.auth_file, settings.base_url
        )
        page = context.new_page()
        page.set_default_timeout(30_000)
        portal = PortalPage(page)
        center = BillingCenterPage(page)
        ledger = TemporaryLedgerPage(page)
        try:
            portal.open_home(
                settings.base_url,
                settings.master_customer_id,
                environment=settings.test_environment,
                account_role=role,
            )
            for group, candidate_or_groups in pools:
                candidates: list[Candidate] = []
                if group.startswith("公摊出账-"):
                    if group == "公摊出账-周期类":
                        pair_groups = list(candidate_or_groups)
                    else:
                        pair_groups = [
                            (f"仪表对-{pair[0].room_path.rsplit('/', 1)[-1]}-{pair[1].room_path.rsplit('/', 1)[-1]}", pair)
                            for pair in candidate_or_groups
                        ]
                    chooser.shuffle(pair_groups)
                    accepted: list[Candidate] | None = None
                    for _, pair in pair_groups:
                        if any(item.key in reserved_keys for item in pair):
                            continue
                        print(
                            f"[preflight] 检查 {group}: "
                            + ",".join(item.case_id for item in pair),
                            flush=True,
                        )
                        clean = True
                        for item in pair:
                            portal.open_billing_center()
                            center.wait_until_ready()
                            center.select_project(item.project_name)
                            matches = center.get_calculation_result_bill_numbers(
                                billing_month=item.billing_month,
                                room_path=item.room_path,
                                charge_item=item.charge_item,
                                allow_empty=True,
                            )
                            if matches:
                                rejected_existing += 1
                                print(
                                    f"[preflight] 跳过既存账单候选 {item.case_id}",
                                    flush=True,
                                )
                                clean = False
                                break
                        if clean:
                            accepted = pair
                            break
                    if accepted is None:
                        raise RuntimeError(f"{group} 没有账期+房间+收费项均无残留的房间对")
                    candidates = accepted
                else:
                    candidates = list(candidate_or_groups)
                    chooser.shuffle(candidates)
                    accepted_one: Candidate | None = None
                    for item in candidates:
                        if item.key in reserved_keys:
                            continue
                        print(
                            f"[preflight] 检查 {group}: {item.case_id}",
                            flush=True,
                        )
                        if item.route == "ledger":
                            portal.open_temporary_ledger()
                            ledger.wait_until_ready()
                            matches = ledger.get_bill_numbers_by_month_room_charge_item(
                                billing_month=item.billing_month,
                                room_path=item.room_path,
                                charge_item=item.charge_item,
                            )
                        else:
                            portal.open_billing_center()
                            center.wait_until_ready()
                            center.select_project(item.project_name)
                            matches = center.get_calculation_result_bill_numbers(
                                billing_month=item.billing_month,
                                room_path=item.room_path,
                                charge_item=item.charge_item,
                                allow_empty=True,
                            )
                        if matches:
                            rejected_existing += 1
                            print(
                                f"[preflight] 跳过既存账单候选 {item.case_id}",
                                flush=True,
                            )
                            continue
                        accepted_one = item
                        break
                    if accepted_one is None:
                        raise RuntimeError(f"{group} 没有目标业务键无残留的候选用例")
                    candidates = [accepted_one]

                selected.extend(candidates)
                reserved_keys.update(item.key for item in candidates)
                print(
                    f"[preflight] 选定 {group}: "
                    + ",".join(item.case_id for item in candidates),
                    flush=True,
                )

            # Existing calculation cards can contaminate calculations even
            # when the final bill list is empty. Do not touch historical cards.
            portal.open_billing_calculation()
            calculation = BillingCalculationPage(page)
            calculation.wait_until_ready()
            pending = _has_pending_target_bills(calculation)
            if pending:
                raise RuntimeError(
                    "计费出账页已有 2026-08 待处理卡片；为避免碰历史卡片，停止本批："
                    + " | ".join(pending[:3])
                )
        finally:
            context.close()
            browser.close()
    if len(selected) != 12:
        raise RuntimeError(f"应选中12条房间级用例，实际 {len(selected)} 条")
    return selected, rejected_existing


def main() -> int:
    parser = argparse.ArgumentParser(description="安全运行12条云收费快速回归用例")
    parser.add_argument("--test-env", default="standard1")
    parser.add_argument("--customer-id", default="93537")
    parser.add_argument("--account-role", default="default")
    args = parser.parse_args()

    os.chdir(ROOT)
    from src.config.environments import load_test_environment

    load_test_environment(ROOT, args.test_env, override=True)
    os.environ["TEST_ENV"] = args.test_env
    os.environ["CUSTOMER_ID"] = args.customer_id
    os.environ["TEST_ACCOUNT_ROLE"] = args.account_role
    os.environ["TEST_CASE_ID"] = "YSF-BILL-PERIODIC-1003"
    os.environ.pop("SCENARIO_ID", None)
    os.environ["BILLING_MONTH"] = MONTH
    os.environ["CALCULATION_BILLING_MONTH"] = MONTH
    os.environ["PUBLIC_SHARE_BILLING_MONTH"] = MONTH
    os.environ["PUBLIC_SHARE_PERIOD_DAYS"] = "32"
    os.environ["PUBLIC_SHARE_UNIT_PRICE"] = "5"
    os.environ["SCOPED_BILLING_CLEANUP_ONLY"] = "true"

    from src.config.settings import settings

    if settings.test_environment == "prod":
        raise SystemExit("禁止在 prod 环境运行带副作用的快速回归。")
    if not (settings.allow_bill_creation and settings.cleanup_created_bill and settings.allow_bill_deletion):
        raise SystemExit("创建、清理、删除三个账单安全开关必须全部开启。")
    if settings.master_customer_id != args.customer_id:
        raise SystemExit("本地环境客户号与请求客户号不一致，停止执行。")
    if settings.billing_month != MONTH:
        raise SystemExit(
            f"运行参数账期必须为 {MONTH}，当前配置为 {settings.billing_month}。"
        )

    pools = _build_pools()
    selected, rejected_existing = _run_preflight(pools, args.account_role)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    html = artifacts / f"quick-release-12-{timestamp}.html"
    junit = artifacts / f"quick-release-12-{timestamp}.xml"
    run_log = artifacts / f"quick-release-12-{timestamp}.log"
    progress = artifacts / f"quick-release-12-{timestamp}-progress.json"
    progress_log = artifacts / f"quick-release-12-{timestamp}-progress.log"
    selection_file = artifacts / f"quick-release-12-{timestamp}-selection.json"
    selection_file.write_text(
        json.dumps(
            {
                "environment": settings.test_environment,
                "customer_id": settings.master_customer_id,
                "billing_month": MONTH,
                "preflight_existing_candidates_skipped": rejected_existing,
                "selected": [asdict(item) for item in selected],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    child_env = os.environ.copy()
    child_env["TEST_PROGRESS_STATE"] = str(progress)
    child_env["TEST_PROGRESS_LOG"] = str(progress_log)
    child_env["QUICK_RELEASE_SHARED_LOGIN"] = "true"
    collect_command = [
        sys.executable,
        "-m", "pytest",
        "--collect-only", "-q",
        "--test-env", settings.test_environment,
        "--customer-id", settings.master_customer_id,
        "--account-role", args.account_role,
    ] + [target for item in selected for target in (item.nodeid,)]
    collected = subprocess.run(
        collect_command,
        cwd=ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )
    collected_nodeids = [
        line.strip()
        for line in collected.stdout.splitlines()
        if line.lstrip().startswith("tests/") and "::" in line
    ]
    if collected.returncode or len(collected_nodeids) != 12:
        raise RuntimeError(
            "12条候选用例未能完整收集；未启动任何业务写操作。"
            f" collect_exit={collected.returncode}, collected={len(collected_nodeids)}"
        )
    command = [
        sys.executable,
        "scripts/run_jenkins_regression.py",
        "--test-env", settings.test_environment,
        "--customer-id", settings.master_customer_id,
        "--account-role", args.account_role,
        "--max-minutes", "0",
        "--junitxml", str(junit),
        "--html-report", str(html),
        "--skip-post-cleanup",
    ]
    for item in selected:
        command.extend(["--test-target", item.nodeid])
    with run_log.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=child_env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    print(f"selected_cases={len(selected)}")
    print(f"preflight_existing_candidates_skipped={rejected_existing}")
    print(f"pytest_exit_code={completed.returncode}")
    print(f"html_report={html}")
    print(f"junit_report={junit}")
    print(f"run_log={run_log}")
    print(f"selection={selection_file}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
