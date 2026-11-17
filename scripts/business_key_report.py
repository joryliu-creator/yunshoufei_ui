"""只读核对：按账期+房间+收费项查看账单中心/临时台账的实际账单状态。

用于两类场景：

* 重跑前核实某个业务键是否已有有效账单（例如 1273 手工作废的说法需要以页面
  当前查询结果为准）；
* 重跑结束后按本次运行的业务键核对残留。

脚本不创建、不作废、不删除任何数据，只做查询与截图取证。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_MONTH = "2026-08"
DEPOSIT_ITEM = "押金类收费项"


def _param_id(nodeid: str) -> str:
    if "[" in nodeid and nodeid.endswith("]"):
        return nodeid[nodeid.rindex("[") + 1 : -1].split("-", 1)[-1]
    return nodeid


_SCENARIO_CACHE: dict[str, object] = {}


def _cached_scenario(scenario_id: str):
    """Read the workbook scenario once per scenario id (74 keys otherwise = 74 loads)."""
    if scenario_id not in _SCENARIO_CACHE:
        from src.config.excel_data import load_excel_test_data
        from src.config.settings import settings

        _SCENARIO_CACHE[scenario_id] = load_excel_test_data(
            settings.test_environment,
            settings.master_customer_id,
            scenario_id,
        ).scenario
    return _SCENARIO_CACHE[scenario_id]


def resolve_business_key(nodeid: str) -> dict[str, str]:
    """Resolve the authoritative business key for one nodeid."""
    import os as _os

    _os.environ.setdefault("TEST_ENV", "standard1")
    _os.environ.setdefault("CUSTOMER_ID", "93537")

    from src.config.excel_data import load_case_reference
    from src.config.settings import settings

    filename = nodeid.split("::", 1)[0].rsplit("/", 1)[-1]
    param = _param_id(nodeid)

    if filename == "test_create_deposit_bill.py":
        from tests.billing.test_create_deposit_bill import DEPOSIT_CASES

        case = next(item for item in DEPOSIT_CASES if item.case_id == param)
        return {
            "case_id": param,
            "billing_month": settings.billing_month,
            "room_path": f"A栋/1层/{case.room}",
            "charge_item": DEPOSIT_ITEM,
            "entrypoint": (
                "临时台账"
                if "in_temporary_ledger" in nodeid
                else "计费出账"
            ),
        }

    if filename == "test_public_share_meter_billing.py":
        from scripts.test_instrument_public_share_billing import MONTH
        from tests.billing.test_public_share_meter_billing import CASE_BY_ROOM

        case = CASE_BY_ROOM[param]
        return {
            "case_id": f"{filename}::{param}",
            "billing_month": MONTH,
            "room_path": case.room.room_path,
            "charge_item": case.charge_item,
            "entrypoint": (
                "账单中心" if "::test_bill_center_" in nodeid else "计费出账"
            ),
        }

    reference = load_case_reference(param)
    scenario = _cached_scenario(reference.scenario_id)
    month = _runtime_month(filename, reference.scenario_id, scenario)
    entrypoint = (
        "临时台账"
        if filename == "test_create_temporary_bill.py"
        else ("账单中心" if filename.startswith("test_create_") else "计费出账")
    )
    return {
        "case_id": param,
        "billing_month": month,
        "room_path": scenario.room_path,
        "charge_item": scenario.charge_item,
        "entrypoint": entrypoint,
    }


def _runtime_month(filename: str, scenario_id: str, scenario) -> str:
    """Mirror each test module's own billing-month resolution.

    The Excel ``建议测试账期`` column is not authoritative: calculation cases
    read ``CALCULATION_BILLING_MONTH`` and the temporary-calculation module is
    pinned to the regression month.
    """
    from src.config.settings import settings

    if filename == "test_calculate_periodic_bill.py":
        from src.config.excel_data import load_excel_test_data

        runtime = load_excel_test_data(
            settings.test_environment,
            settings.master_customer_id,
            scenario_id,
        ).runtime_parameters
        month = (
            os.getenv("CALCULATION_BILLING_MONTH", "").strip()
            or runtime.get("CALCULATION_BILLING_MONTH", "").strip()
        )
        if month in {"执行当月", "執行当月"} or not month:
            return DEFAULT_MONTH
        return month
    if filename == "test_calculate_temporary_bill.py":
        return DEFAULT_MONTH
    if filename == "test_create_periodic_center_bills.py":
        return settings.billing_month
    return scenario.suggested_billing_month or DEFAULT_MONTH


def _resolve_with_cache(nodeids: list[str]) -> list[dict[str, str]]:
    """Resolve nodeid -> business key, reusing a local cache across runs.

    Each resolution reads the Excel workbook, so the cache keeps the read-only
    audit affordable when the same 74 keys are checked before and after a run.
    """
    cache_path = ROOT / "artifacts" / ".business-keys-cache.json"
    cache: dict[str, dict[str, str]] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache = {}
    resolved: list[dict[str, str]] = []
    dirty = False
    for index, nodeid in enumerate(nodeids, start=1):
        if nodeid in cache:
            resolved.append(cache[nodeid])
            continue
        print(f"[keys] {index}/{len(nodeids)} 解析 {nodeid}", flush=True)
        key = resolve_business_key(nodeid)
        cache[nodeid] = key
        resolved.append(key)
        dirty = True
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if dirty:
        print(f"[keys] 已缓存到 {cache_path.as_posix()}", flush=True)
    return resolved


def _restore_session_storage(context, session_file: Path, auth_file: Path, base_url: str) -> None:
    """Replay the saved sessionStorage snapshot for the exact origin."""
    from urllib.parse import urlparse

    payload = json.loads(session_file.read_text(encoding="utf-8"))
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if not parsed.scheme or not parsed.netloc:
        raise SystemExit("BASE_URL 缺少有效协议或主机名")
    auth_state = json.loads(auth_file.read_text(encoding="utf-8"))
    origins = {
        item.get("origin")
        for item in auth_state.get("origins", [])
        if isinstance(item, dict) and item.get("origin")
    }
    if origins and origin not in origins:
        return
    script = (
        "(() => { const storage = " + json.dumps(payload, ensure_ascii=False) + ";"
        " const host = " + json.dumps(origin) + ";"
        " const marker = '__codex_saved_session_storage_restored_v1__';"
        " if (location.origin === host && sessionStorage.getItem(marker) !== '1') {"
        " for (const [k, v] of Object.entries(storage)) sessionStorage.setItem(k, v);"
        " sessionStorage.setItem(marker, '1'); } })();"
    )
    context.add_init_script(script)


def main() -> int:
    parser = argparse.ArgumentParser(description="只读核对账单业务键")
    parser.add_argument("--nodeids", type=Path, default=None)
    parser.add_argument("--test-env", default="standard1")
    parser.add_argument("--customer-id", default="93537")
    parser.add_argument("--account-role", default="default")
    parser.add_argument("--include-voided", action="store_true")
    parser.add_argument("--only-case", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--label", default="business-key-check")
    parser.add_argument("--skip-ledger", action="store_true")
    parser.add_argument("--screenshot", action="store_true")
    args = parser.parse_args()

    os.chdir(ROOT)
    from src.config.environments import load_test_environment

    load_test_environment(ROOT, args.test_env, override=True)
    os.environ["TEST_ENV"] = args.test_env
    os.environ["CUSTOMER_ID"] = args.customer_id
    os.environ["TEST_ACCOUNT_ROLE"] = args.account_role

    from playwright.sync_api import sync_playwright

    from src.config.accounts import get_account_auth_profile
    from src.config.settings import settings
    from src.pages.billing_center_page import BillingCenterPage
    from src.pages.portal_page import PortalPage
    from src.pages.temporary_ledger_page import TemporaryLedgerPage

    nodeids: list[str] = []
    if args.nodeids:
        raw = json.loads(args.nodeids.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("nodeids", [])
        nodeids = list(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))
    if args.only_case:
        wanted = set(args.only_case)
        nodeids = [
            nodeid for nodeid in nodeids
            if any(token in nodeid for token in wanted)
        ]
    keys = _resolve_with_cache(nodeids)
    # 同一业务键可能同时出现在账单中心和计费出账两个入口，只查一次。
    merged: dict[tuple[str, str, str], dict[str, object]] = {}
    for key in keys:
        identity = (key["billing_month"], key["room_path"], key["charge_item"])
        if identity in merged:
            merged[identity]["cases"].append(key["case_id"])
            merged[identity]["entrypoints"].append(key["entrypoint"])
            continue
        merged[identity] = {
            **key,
            "cases": [key["case_id"]],
            "entrypoints": [key["entrypoint"]],
        }
    keys = list(merged.values())
    if args.limit:
        keys = keys[: args.limit]
    if not keys:
        raise SystemExit("没有可核对的目标业务键。")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "artifacts"
    out_dir.mkdir(exist_ok=True)
    report_path = out_dir / f"{args.label}-{stamp}.json"
    shot_dir = out_dir / f"{args.label}-{stamp}-screenshots"
    if args.screenshot:
        shot_dir.mkdir(parents=True, exist_ok=True)

    profile = get_account_auth_profile(
        ROOT, args.account_role, settings.test_environment, settings.master_customer_id
    )
    if not profile.auth_file.exists() or not profile.session_file.exists():
        raise SystemExit("缺少已保存的登录状态，请先运行 scripts/save_auth.py。")

    records: list[dict[str, object]] = []
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
        portal = PortalPage(page)
        center = BillingCenterPage(page)
        ledger = TemporaryLedgerPage(page)
        try:
            portal.open_home(
                settings.base_url,
                settings.master_customer_id,
                environment=settings.test_environment,
                account_role=args.account_role,
            )
            for index, key in enumerate(keys, start=1):
                entry = {
                    **key,
                    "queried_at": datetime.now().isoformat(timespec="seconds"),
                    "include_voided": args.include_voided,
                }
                try:
                    portal.open_billing_center()
                    center.wait_until_ready()
                    center.select_project(settings.project_name)
                    numbers = center.get_bill_numbers_by_month_room_charge_item(
                        billing_month=key["billing_month"],
                        room_path=key["room_path"],
                        charge_item=key["charge_item"],
                        allow_empty=True,
                        include_voided=args.include_voided,
                    )
                    rows = center._find_main_table_row(
                        room_path=key["room_path"], charge_item=key["charge_item"]
                    )
                    texts = [
                        rows.nth(i).inner_text().replace("\n", " ").strip()
                        for i in range(rows.count())
                        if rows.nth(i).is_visible()
                    ]
                    entry["bill_center_numbers"] = numbers
                    entry["bill_center_rows"] = texts
                    entry["bill_center_active"] = bool(numbers)
                except Exception as error:  # keep going: one key must not stop the audit
                    entry["bill_center_error"] = f"{type(error).__name__}: {error}"[:800]

                if not args.skip_ledger and key["entrypoint"] == "临时台账":
                    try:
                        portal.open_temporary_ledger()
                        ledger.wait_until_ready()
                        ledger_numbers = ledger.get_bill_numbers_by_month_room_charge_item(
                            billing_month=key["billing_month"],
                            room_path=key["room_path"],
                            charge_item=key["charge_item"],
                        )
                        ledger._close_advanced_search_if_open()
                        entry["ledger_numbers"] = ledger_numbers
                        entry["ledger_active_numbers"] = ledger.filter_active_bill_numbers(
                            ledger_numbers
                        )
                    except Exception as error:
                        entry["ledger_error"] = f"{type(error).__name__}: {error}"[:800]

                if args.screenshot:
                    target = shot_dir / f"{index:02d}-{key['case_id'].replace('::', '_')}.png"
                    try:
                        page.screenshot(path=str(target), full_page=True)
                        entry["screenshot"] = str(target)
                    except Exception as error:
                        entry["screenshot_error"] = str(error)[:300]

                residue = bool(entry.get("bill_center_numbers")) or bool(
                    entry.get("ledger_active_numbers")
                )
                entry["residue"] = residue
                records.append(entry)
                print(
                    f"[{index}/{len(keys)}] {key['entrypoint']} {key['case_id']} "
                    f"{key['billing_month']} {key['room_path']} {key['charge_item']} -> "
                    f"账单中心={entry.get('bill_center_numbers', entry.get('bill_center_error', '-'))} "
                    f"台账={entry.get('ledger_active_numbers', '-')} "
                    f"{'残留' if residue else '无有效账单'}",
                    flush=True,
                )
        finally:
            context.close()
            browser.close()

    report_path.write_text(
        json.dumps(
            {
                "generated_at": stamp,
                "environment": settings.test_environment,
                "customer_id": settings.master_customer_id,
                "account_role": args.account_role,
                "include_voided": args.include_voided,
                "total": len(records),
                "residue_count": sum(1 for item in records if item.get("residue")),
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[report] {report_path.as_posix()}", flush=True)
    print(
        f"[report] 共 {len(records)} 个业务键，有效账单命中 "
        f"{sum(1 for item in records if item.get('residue'))} 个",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
