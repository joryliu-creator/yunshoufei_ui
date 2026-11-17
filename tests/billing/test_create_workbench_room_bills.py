from __future__ import annotations

import json
import os
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from playwright.sync_api import Page, expect

from scripts.update_room_import_template import formula_mappings
from src.config.excel_data import DEFAULT_WORKBOOK, _load_scenario
from src.config.settings import settings
from src.domain.meter_charge import MeterReadingBasis, calculate_meter_amount
from src.domain.periodic_charge import PeriodicRoomBasis, calculate_periodic_amount
from src.domain.public_share_charge import PUBLIC_SHARE_BY_ROOM
from src.pages.billing_center_page import BillData, BillingCenterPage
from src.pages.portal_page import PortalPage
from src.pages.workbench_billing_page import WorkbenchBillingPage


BILLING_MONTH = "2026-08"
RECEIVABLE_DATE = "2026-08-31"
LATEST_PAYMENT_DATE = "2026-08-31"
PROFILE_ONLY = os.getenv("WORKBENCH_PROFILE_ONLY", "").strip().lower() in {
    "1", "true", "yes", "on"
}
ROOM_MAPPINGS = {item.room_name: item for item in formula_mappings()}


def _candidate_scenarios() -> dict[str, object]:
    """Use only the verified Standard1/93537 room scenarios for requested types."""
    # _load_scenario performs keyed row lookups repeatedly; load the small
    # scenario worksheet in memory so collection remains fast and deterministic.
    workbook = load_workbook(DEFAULT_WORKBOOK, read_only=False, data_only=True)
    try:
        sheet = workbook["收费场景配置"]
        headers = {
            str(sheet.cell(1, column).value).splitlines()[0].rstrip("*").strip(): column
            for column in range(1, sheet.max_column + 1)
            if sheet.cell(1, column).value
        }
        required = (
            "场景编号", "环境", "客户号", "房间路径", "收费类型", "维护状态", "是否启用"
        )
        missing = [name for name in required if name not in headers]
        if missing:
            raise ValueError(f"回归工作簿场景表缺少列：{missing}")

        prefixes = (
            "YSF-SCENE-PERIODIC-BILL-",
            "YSF-SCENE-METER-BILL-",
            "YSF-SCENE-PUBLIC-SHARE-PERIODIC-BILL-",
            "YSF-SCENE-PUBLIC-SHARE-METER-BILL-",
        )
        selected: list[tuple[int, int, str]] = []
        category_order = {
            prefixes[0]: 0,
            prefixes[1]: 1,
            prefixes[2]: 2,
            prefixes[3]: 3,
        }
        for row in range(2, sheet.max_row + 1):
            value = lambda name: str(sheet.cell(row, headers[name]).value or "").strip()
            scenario_id = value("场景编号")
            if not scenario_id.startswith(prefixes):
                continue
            if scenario_id == "YSF-SCENE-PERIODIC-BILL-001":
                # 1001 was already successfully created, verified, and cleaned
                # through the Workbench in the preceding task.
                continue
            if (
                value("环境") != settings.test_environment
                or value("客户号") != settings.master_customer_id
                or value("是否启用") != "是"
                or not value("维护状态").startswith("已核验")
            ):
                continue
            room = value("房间路径").rsplit("/", 1)[-1]
            prefix = next(item for item in prefixes if scenario_id.startswith(item))
            selected.append((category_order[prefix], int(room), scenario_id))
        selected.sort()
        ids = tuple(item[2] for item in selected)
        if len(ids) != 75 or len(set(ids)) != len(ids):
            raise ValueError(
                "当前已核验场景应映射75个待处理房间（21周期、12仪表、42公摊）；"
                f"实际场景数={len(ids)}，去重后={len(set(ids))}。"
            )
        return {
            scenario_id: _load_scenario(
                workbook,
                settings.test_environment,
                settings.master_customer_id,
                scenario_id,
            )
            for scenario_id in ids
        }
    finally:
        workbook.close()


SCENARIOS = _candidate_scenarios()
SCENARIO_IDS = tuple(SCENARIOS)


pytestmark = [
    pytest.mark.side_effect,
    pytest.mark.skipif(
        not settings.allow_bill_creation,
        reason="默认禁止创建账单；确认目标数据后设置 ALLOW_BILL_CREATION=true。",
    ),
]


def _parameters(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.replace(";", "\n").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _scenario(scenario_id: str):
    return SCENARIOS[scenario_id]


def _expected_amount(scenario) -> tuple[Decimal, str]:
    """Return a domain calculation or a maintained, previously verified baseline."""
    room = scenario.room_path.rsplit("/", 1)[-1]
    params = _parameters(scenario.calculation_parameters)
    if scenario.scenario_id.startswith("YSF-SCENE-PUBLIC-SHARE-PERIODIC-BILL-"):
        share_case = PUBLIC_SHARE_BY_ROOM.get(room)
        if share_case is None:
            raise ValueError(f"周期公摊房间 {room} 缺少已维护的金额基线")
        return share_case.expected_amount, "公摊周期域模型确认基线"

    if scenario.scenario_id.startswith("YSF-SCENE-PUBLIC-SHARE-METER-BILL-"):
        # The maintained Excel values for these eight area-coefficient rooms
        # were explicitly approved from the actual Bill Center amounts; the
        # other meter-share scenarios are backed by the validated allocation
        # calculation. Keep that accepted room-level baseline as the oracle.
        return Decimal(scenario.expected_original_amount), "已确认的公摊房间金额基线(Excel)"

    if scenario.charge_type == "周期类":
        mapping = ROOM_MAPPINGS.get(room)
        if mapping is None:
            raise ValueError(f"周期房间 {room} 缺少收费面积映射")
        basis = PeriodicRoomBasis(
            building_area=Decimal(params.get("BUILDING_AREA", "300.12")),
            usable_area=Decimal(params.get("USABLE_AREA", "280.01")),
            fee_area=Decimal(params.get("FEE_AREA", "260.00")),
            floor=int(params.get("FLOOR", "1")),
            months=Decimal(params.get("MONTHS", "1")),
        )
        return (
            calculate_periodic_amount(
                scenario.formula,
                mapping.area_type,
                scenario.calculation_parameters,
                basis,
            ),
            "周期收费域模型独立计算",
        )

    if scenario.charge_type == "仪表类":
        basis = MeterReadingBasis(
            period_usage=Decimal(params["PERIOD_USAGE"]),
            previous_reading=Decimal(params["PREVIOUS_READING"]),
            current_reading=Decimal(params["CURRENT_READING"]),
            cumulative_usage=Decimal(params["CUMULATIVE_USAGE"]),
            floor=int(params["FLOOR"]),
        )
        return (
            calculate_meter_amount(
                scenario.formula, scenario.calculation_parameters, basis
            ),
            "仪表收费域模型独立计算",
        )

    raise ValueError(f"工作台专项不支持收费类型 {scenario.charge_type!r}")


@pytest.mark.parametrize(
    "scenario_id",
    SCENARIO_IDS,
    ids=[scenario_id.rsplit("-", 1)[-1] for scenario_id in SCENARIO_IDS],
)
def test_create_workbench_room_bill_verify_and_cleanup(
    fresh_login_page: Page,
    account_role: str,
    record_property: pytest.RecordProperty,
    scenario_id: str,
) -> None:
    page = fresh_login_page
    portal = PortalPage(page)
    portal.open_home(
        settings.base_url,
        settings.master_customer_id,
        environment=settings.test_environment,
        account_role=account_role,
    )
    if settings.test_environment != "standard1" or settings.master_customer_id != "93537":
        pytest.fail(
            "工作台批量出账只允许 Standard1 / 客户93537；其他上下文禁止写入。"
        )
    if account_role != "default":
        pytest.fail(f"工作台批量出账要求 default 登录配置，当前为 {account_role!r}。")
    if not settings.cleanup_created_bill or not settings.allow_bill_deletion:
        pytest.fail(
            "工作台批次必须逐笔清理；需要 CLEANUP_CREATED_BILL=true 和 "
            "ALLOW_BILL_DELETION=true。"
        )

    scenario = _scenario(scenario_id)
    if scenario.charge_type not in {"周期类", "仪表类"}:
        pytest.fail(f"场景 {scenario_id} 的收费类型不在本批次范围内。")
    if scenario_id.startswith("YSF-SCENE-PUBLIC-SHARE-METER-BILL-"):
        # A read-only probe of room 1207 showed that this archive's bill drawer
        # does not default the room (unlike ordinary rooms and periodic-share
        # rooms). The established Workbench rule is to trust the auto-filled
        # room and not reselect it; do not create a bill with a blank/ambiguous
        # charge object until the UI behavior is confirmed.
        record_property(
            "workbench_preflight_blocker",
            f"{scenario.room_path}: 公摊仪表房间的新增账单抽屉未自动带入房间；"
            "按既定规则未手动重选，未创建。",
        )
        print(
            f"[workbench-batch] SKIP room={scenario.room_path} "
            "reason=public-meter drawer did not auto-fill room",
            flush=True,
        )
        pytest.skip("仪表公摊房间抽屉未自动带入房间，按既定约束保护性跳过。")
    expected_original, expected_source = _expected_amount(scenario)
    expected_discount = Decimal(scenario.expected_discount_amount or "0")
    expected_receivable = Decimal(scenario.expected_receivable_amount)
    if expected_original != Decimal(scenario.expected_original_amount):
        pytest.fail(
            f"{scenario_id} 独立计算与Excel原始金额不一致："
            f"{expected_original} vs {scenario.expected_original_amount}。"
        )
    if expected_original - expected_discount != expected_receivable:
        pytest.fail(f"{scenario_id} Excel原价/减免/应收金额关系不成立。")

    data = BillData(
        project_name=scenario.project_name,
        room_path=scenario.room_path,
        charge_type=scenario.charge_type,
        charge_item=scenario.charge_item,
        billing_month=BILLING_MONTH,
        receivable_date=RECEIVABLE_DATE,
        latest_payment_date=LATEST_PAYMENT_DATE,
    )
    center = BillingCenterPage(page)
    workbench = WorkbenchBillingPage(page)
    submission_attempted = False
    room_number = scenario.room_path.rsplit("/", 1)[-1]

    print(
        f"[workbench-batch] BEGIN {scenario.charge_type} room={room_number} "
        f"item={scenario.charge_item} expected={expected_receivable}",
        flush=True,
    )
    portal.open_billing_center()
    center.wait_until_ready()
    center.select_project(data.project_name)

    def query_target(*, include_voided: bool, allow_empty: bool = True) -> list[str]:
        return center.get_bill_numbers_by_month_room_charge_item(
            billing_month=BILLING_MONTH,
            room_path=data.room_path,
            charge_item=data.charge_item,
            include_voided=include_voided,
            allow_empty=allow_empty,
        )

    def reopen_center() -> None:
        portal.open_billing_center()
        center.wait_until_ready()
        center.select_project(data.project_name)

    existing = query_target(include_voided=True)
    if existing:
        record_property(
            "workbench_preflight_existing",
            json.dumps(
                {
                    "scenario_id": scenario_id,
                    "business_key": [BILLING_MONTH, data.room_path, data.charge_item],
                    "matched_bill_numbers": existing,
                    "action": "跳过，未修改既有数据",
                },
                ensure_ascii=False,
            ),
        )
        print(
            f"[workbench-batch] SKIP existing business-key matches="
            f"{len(existing)} room={room_number}; pre-existing bills untouched",
            flush=True,
        )
        pytest.skip("目标业务键已有账单，保护既有数据，本次不创建或清理。")

    try:
        workbench.open()
        workbench.search_room(data.room_path)
        detail = workbench.open_room_profile(data.room_path)
        public_share = scenario_id.startswith("YSF-SCENE-PUBLIC-SHARE-")
        if public_share:
            # Public-share participants are not required to have a separate
            # room fee binding; the bill drawer must offer the configured
            # scheme fee item directly.
            workbench.wait_for_room_profile(data.room_path)
        else:
            workbench.wait_for_charge_profile(
                room_path=data.room_path,
                charge_item=data.charge_item,
                charge_standard=scenario.charge_standard,
            )
        dialog = workbench.open_create_bill()
        center.frame = detail
        center._add_charge_item(dialog, data.charge_item)
        if PROFILE_ONLY:
            draft_text = dialog.inner_text()
            if data.charge_item not in draft_text:
                raise AssertionError(
                    f"工作台新增账单抽屉未能添加公摊收费项 {data.charge_item!r}。"
                )
            record_property(
                "workbench_profile_preflight",
                f"{data.room_path} 档案已加载；抽屉自动带入房间且可添加 "
                f"{data.charge_item}；草稿={draft_text[-1200:]!r}；未提交。",
            )
            dialog.get_by_role("button", name="取消", exact=True).click()
            pytest.skip("只读档案预检通过，未创建账单。")

        # The archive form already has the selected room. Assert its value and
        # reuse the verified Bill Center widgets without reselecting a room.
        receivable_date = dialog.get_by_placeholder("选择日期")
        expect(receivable_date).to_have_count(1, timeout=10_000)
        receivable_date.first.fill(RECEIVABLE_DATE)
        receivable_date.first.press("Enter")
        page.keyboard.press("Escape")
        expect(receivable_date.first).to_have_value(RECEIVABLE_DATE)

        month_input = dialog.get_by_placeholder("选择年月")
        expect(month_input).to_have_count(1, timeout=10_000)
        center._select_billing_month(month_input, BILLING_MONTH)
        center._edit_charge_detail(
            dialog,
            charge_item=data.charge_item,
            latest_payment_date=LATEST_PAYMENT_DATE,
        )

        submission_attempted = True
        feedback = workbench.submit_and_wait_for_success(dialog)
        record_property("workbench_create_feedback", feedback)

        reopen_center()
        active = query_target(include_voided=False)
        if len(active) != 1:
            raise AssertionError(
                "工作台新增后按账期+房间+收费项应唯一命中一条有效账单；"
                f"实际={len(active)}。"
            )
        rows = center._find_main_table_row(
            room_path=data.room_path, charge_item=data.charge_item
        )
        matching_rows = [
            rows.nth(index)
            for index in range(rows.count())
            if rows.nth(index).is_visible()
            and BILLING_MONTH in rows.nth(index).inner_text()
            and "已作废" not in rows.nth(index).inner_text()
        ]
        if len(matching_rows) != 1:
            raise AssertionError(
                f"账单中心校验时可见业务键匹配行应为1，实际={len(matching_rows)}。"
            )
        row = matching_rows[0]
        expect(row).to_contain_text(RECEIVABLE_DATE)
        expect(row).to_contain_text(data.charge_item)
        center.assert_row_amounts(
            row,
            expected_original=expected_original,
            expected_discount=expected_discount,
            expected_receivable=expected_receivable,
        )
        record_property(
            "workbench_created_bill",
            json.dumps(
                {
                    "scenario_id": scenario_id,
                    "entrypoint": "工作台-房间档案-新增账单",
                    "room": data.room_path,
                    "charge_type": scenario.charge_type,
                    "charge_item": data.charge_item,
                    "charge_standard": scenario.charge_standard,
                    "billing_month": BILLING_MONTH,
                    "receivable_date": RECEIVABLE_DATE,
                    "latest_payment_date": LATEST_PAYMENT_DATE,
                    "bill_number": active[0],
                    "expected_amount": str(expected_receivable),
                    "expected_source": expected_source,
                },
                ensure_ascii=False,
            ),
        )
    finally:
        if submission_attempted:
            reopen_center()
            matches = query_target(include_voided=True)
            if len(matches) != 1:
                raise AssertionError(
                    "本次新建账单清理前业务键未唯一命中，停止删除保护历史数据；"
                    f"匹配数={len(matches)}。"
                )
            center.cleanup_by_month_room_charge_item(
                billing_month=BILLING_MONTH,
                room_path=data.room_path,
                charge_item=data.charge_item,
                void_reason=settings.void_reason,
            )
            remaining = query_target(include_voided=True)
            if remaining:
                raise AssertionError(
                    f"工作台账单已执行作废+批量删除，但复查仍命中：{remaining!r}。"
                )
            record_property(
                "workbench_cleanup",
                "本次账单已作废并批量删除，按账期+房间+收费项复查为0条",
            )
        print(
            f"[workbench-batch] END {scenario.charge_type} room={room_number} "
            f"submitted={submission_attempted}",
            flush=True,
        )
