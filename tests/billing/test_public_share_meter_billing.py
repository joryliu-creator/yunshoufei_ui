from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from playwright.sync_api import Page

from scripts import test_instrument_public_share_billing as focused
from src.config.excel_data import DEFAULT_WORKBOOK, load_case_reference, load_excel_test_data
from src.config.settings import settings


def _case_ids(prefix: str) -> tuple[str, ...]:
    workbook = load_workbook(DEFAULT_WORKBOOK, read_only=True, data_only=True)
    try:
        worksheet = workbook["用例清单"]
        case_ids = tuple(
            str(worksheet.cell(row, 1).value).strip()
            for row in range(2, worksheet.max_row + 1)
            if str(worksheet.cell(row, 1).value or "").strip().startswith(prefix)
        )
    finally:
        workbook.close()
    if len(case_ids) != 32 or len(set(case_ids)) != 32:
        raise ValueError(
            f"仪表公摊入口 {prefix} 应有 32 条唯一房间用例，实际 {len(case_ids)} 条。"
        )
    return case_ids


CASE_BY_ROOM = {case.room.room: case for case in focused.CASES}
if len(CASE_BY_ROOM) != 32:
    raise ValueError(f"正式水表/电表公摊应覆盖 32 间关联房间，实际 {len(CASE_BY_ROOM)} 间。")

BILL_CENTER_CASE_IDS = _case_ids("YSF-BILL-PUBLIC-SHARE-METER-")
CALCULATION_CASE_IDS = _case_ids("YSF-CALC-PUBLIC-SHARE-METER-")

pytestmark = [
    pytest.mark.side_effect,
    pytest.mark.skipif(
        not settings.allow_bill_creation,
        reason="账单创建安全开关默认关闭。",
    ),
]


def _load_case_from_excel(case_id: str, entrypoint: str):
    room = case_id.rsplit("-", 1)[-1]
    if not room.isdigit() or room not in CASE_BY_ROOM:
        raise ValueError(f"Excel 仪表公摊用例引用了未维护的房间：{case_id}")
    source_case = CASE_BY_ROOM[room]
    reference = load_case_reference(case_id)
    expected_scenario_id = f"YSF-SCENE-PUBLIC-SHARE-METER-{entrypoint}-{room}"
    if reference.scenario_id != expected_scenario_id:
        raise ValueError(
            f"{case_id} 应引用 {expected_scenario_id}，实际引用 {reference.scenario_id}。"
        )
    data = load_excel_test_data(
        settings.test_environment,
        settings.master_customer_id,
        reference.scenario_id,
    )
    scenario = data.scenario
    expected_fields = {
        "project": (scenario.project_name, settings.project_name),
        "room": (scenario.room_path, source_case.room.room_path),
        "charge type": (scenario.charge_type, "仪表类"),
        "charge item": (scenario.charge_item, source_case.charge_item),
        "charge standard": (scenario.charge_standard, source_case.charge_standard),
        "billing month": (scenario.suggested_billing_month, focused.MONTH),
    }
    mismatches = {
        name: values
        for name, values in expected_fields.items()
        if values[0] != values[1]
    }
    if mismatches:
        raise ValueError(f"Excel 仪表公摊场景与维护数据不一致：{mismatches}")

    expected_amount = Decimal(scenario.expected_receivable_amount)
    if (
        Decimal(scenario.expected_original_amount) != expected_amount
        or Decimal(scenario.expected_discount_amount or "0") != Decimal("0.00")
        or expected_amount != source_case.expected_amount
    ):
        raise ValueError(
            f"{case_id} Excel 预期金额与当前场景基准不一致："
            f"Excel={expected_amount}，基准={source_case.expected_amount}"
        )
    return replace(source_case, expected_amount=expected_amount), reference.account_role


@pytest.mark.parametrize(
    "case_id",
    BILL_CENTER_CASE_IDS,
    ids=lambda case_id: case_id.rsplit("-", 1)[-1],
)
def test_bill_center_public_share_meter_regression(
    fresh_login_page: Page,
    record_property: pytest.RecordProperty,
    account_role: str,
    case_id: str,
) -> None:
    case, role = _load_case_from_excel(case_id, "BILL")
    if role != account_role:
        raise ValueError(f"Excel 账号角色 {role!r} 与当前运行角色 {account_role!r} 不一致。")
    focused.test_bill_center_instrument_public_share(
        fresh_login_page,
        record_property,
        account_role,
        case,
    )


@pytest.mark.parametrize(
    "case_id",
    CALCULATION_CASE_IDS,
    ids=lambda case_id: case_id.rsplit("-", 1)[-1],
)
def test_calculation_public_share_meter_regression(
    fresh_login_page: Page,
    record_property: pytest.RecordProperty,
    account_role: str,
    case_id: str,
) -> None:
    case, role = _load_case_from_excel(case_id, "CALC")
    if role != account_role:
        raise ValueError(f"Excel 账号角色 {role!r} 与当前运行角色 {account_role!r} 不一致。")
    focused.test_calculation_instrument_public_share(
        fresh_login_page,
        record_property,
        account_role,
        case,
    )
