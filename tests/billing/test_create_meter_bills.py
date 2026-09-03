from __future__ import annotations

import json
from decimal import Decimal

import pytest
from playwright.sync_api import Page

from scripts.add_bill_demo_to_excel import METER_CASES
from src.config.excel_data import load_case_reference, load_excel_test_data
from src.config.settings import settings
from src.domain.meter_charge import MeterReadingBasis, calculate_meter_amount
from src.pages.billing_center_page import BillData, BillingCenterPage
from src.pages.portal_page import PortalPage


METER_CASE_IDS = [case[0] for case in METER_CASES]

pytestmark = [
    pytest.mark.side_effect,
    pytest.mark.skipif(
        not settings.allow_bill_creation,
        reason="默认禁止创建账单；确认测试数据后设置 ALLOW_BILL_CREATION=true。",
    ),
]


def _parameters(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


@pytest.mark.parametrize("case_id", METER_CASE_IDS)
def test_create_meter_bill_and_assert_amount(
    page: Page,
    record_property: pytest.RecordProperty,
    account_role: str,
    case_id: str,
) -> None:
    reference = load_case_reference(case_id)
    excel_data = load_excel_test_data(
        settings.test_environment,
        settings.master_customer_id,
        reference.scenario_id,
    )
    scenario = excel_data.scenario
    if scenario.charge_type != "仪表类":
        pytest.fail(f"用例 {case_id} 未引用仪表类场景。")
    if scenario.suggested_billing_month != "2026-08":
        pytest.fail(f"用例 {case_id} 的账期不是 2026-08。")

    parameters = _parameters(scenario.calculation_parameters)
    basis = MeterReadingBasis(
        period_usage=Decimal(parameters["PERIOD_USAGE"]),
        previous_reading=Decimal(parameters["PREVIOUS_READING"]),
        current_reading=Decimal(parameters["CURRENT_READING"]),
        cumulative_usage=Decimal(parameters["CUMULATIVE_USAGE"]),
        floor=int(parameters["FLOOR"]),
    )
    independently_calculated_amount = calculate_meter_amount(
        scenario.formula, scenario.calculation_parameters, basis
    )
    expected_original = Decimal(scenario.expected_original_amount)
    expected_discount = Decimal(scenario.expected_discount_amount)
    expected_receivable = Decimal(scenario.expected_receivable_amount)
    assert independently_calculated_amount == expected_original
    assert expected_original - expected_discount == expected_receivable

    data = BillData(
        project_name=scenario.project_name,
        room_path=scenario.room_path,
        charge_type=scenario.charge_type,
        charge_item=scenario.charge_item,
        billing_month=scenario.suggested_billing_month,
        receivable_date=settings.receivable_date,
        latest_payment_date=settings.latest_payment_date,
    )
    portal = PortalPage(page)
    billing_center = BillingCenterPage(page)
    created_bill = None

    try:
        portal.open_home(
            settings.base_url,
            settings.master_customer_id,
            environment=settings.test_environment,
            account_role=account_role,
        )
        portal.open_billing_center()
        billing_center.wait_until_ready()
        billing_center.select_project(data.project_name)
        dialog = billing_center.open_create_bill()
        billing_center.fill_bill(dialog, data)
        created_bill = billing_center.submit_and_skip_notification(dialog, data)
        assert data.billing_month in created_bill.bill_row_text
        billing_center.assert_bill_amounts(
            created_bill,
            expected_original=expected_original,
            expected_discount=expected_discount,
            expected_receivable=expected_receivable,
        )
        record_property(
            "created_bill",
            json.dumps(
                {
                    "case_id": case_id,
                    "scenario_id": scenario.scenario_id,
                    "room_path": scenario.room_path,
                    "meter_no": parameters["METER_NO"],
                    "billing_month": data.billing_month,
                    "expected_amount": str(independently_calculated_amount),
                    "bill_number": created_bill.bill_number,
                },
                ensure_ascii=False,
            ),
        )
    finally:
        if created_bill is not None and settings.cleanup_created_bill:
            if not settings.allow_bill_deletion:
                pytest.fail(
                    "已创建账单但禁止删除；如需自动清理，请同时设置 "
                    "ALLOW_BILL_DELETION=true。"
                )
            billing_center.cleanup_by_month_room_charge_item(
                billing_month=data.billing_month,
                room_path=data.room_path,
                charge_item=data.charge_item,
                void_reason=settings.void_reason,
            )
