from __future__ import annotations

import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import Page, expect

from src.config.excel_data import load_case_reference, load_excel_test_data
from src.config.settings import settings
from src.domain.bill_presence import BillKey, ensure_no_active_bill, skip_existing_active_bill
from src.pages.billing_calculation_page import (
    BillingCalculationPage,
    TemporaryCalculationData,
)
from src.pages.billing_center_page import BillingCenterPage
from src.pages.portal_page import PortalPage


pytestmark = [
    pytest.mark.scenario("YSF-SCENE-CALCULATION-TEMPORARY"),
    pytest.mark.side_effect,
    pytest.mark.skipif(
        not settings.allow_bill_creation,
        reason="默认禁止创建账单；确认测试数据后设置 ALLOW_BILL_CREATION=true。",
    ),
]


def _today() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def _month() -> str:
    return "2026-08"


# Entry-point-specific cases for the Billing Issuance temporary workflow.
# YSF-BILL-TEMP-* belongs exclusively to Temporary Ledger and is collected by
# test_create_temporary_bill.py.
TEMP_CALC_CASE_IDS = [
    "YSF-CALC-TEMP-1012",
    "YSF-CALC-TEMP-1013",
    "YSF-CALC-TEMP-1014",
    "YSF-CALC-TEMP-1015",
    "YSF-CALC-TEMP-1016",
    "YSF-CALC-TEMP-1017",
    "YSF-CALC-TEMP-1018",
    "YSF-CALC-TEMP-1019",
    "YSF-CALC-TEMP-1020",
    "YSF-CALC-TEMP-1059",
    "YSF-CALC-TEMP-1060",
]


def _data(case_id: str) -> tuple[TemporaryCalculationData, Decimal, str]:
    reference = load_case_reference(case_id)
    source = load_excel_test_data(
        settings.test_environment,
        settings.master_customer_id,
        reference.scenario_id,
    )
    params = {}
    for token in source.scenario.calculation_parameters.split(";"):
        if "=" in token:
            key, value = token.split("=", 1)
            params[key.strip()] = value.strip()
    today = _today()
    tomorrow = datetime.now(ZoneInfo("Asia/Shanghai")).date().fromordinal(
        datetime.now(ZoneInfo("Asia/Shanghai")).date().toordinal() + 1
    ).strftime("%Y-%m-%d")
    # This scenario is deliberately explicit: the user asked for current
    # month/today in the calculation drawer, regardless of the stale demo
    # runtime month retained for the ledger examples.
    data = TemporaryCalculationData(
        project_name=source.scenario.project_name,
        room_name=source.scenario.room_path.rsplit("/", 1)[-1],
        room_path=source.scenario.room_path,
        billing_month=_month(),
        receivable_date=_today(),
        latest_payment_date=_today(),
        charge_item=source.scenario.charge_item,
        charge_standard=source.scenario.charge_standard,
        meter_usage=params.get("METER_USAGE"),
        quantity=params.get("QUANTITY"),
        manual_amount=params.get("MANUAL_AMOUNT"),
        area_type=params.get("AREA_TYPE"),
        billing_period_start=today if params.get("DATE_RANGE") else None,
        billing_period_end=tomorrow if params.get("DATE_RANGE") else None,
        expected_amount=source.scenario.expected_receivable_amount,
    )
    return data, Decimal(source.scenario.expected_receivable_amount), reference.scenario_id


@pytest.mark.parametrize("case_id", TEMP_CALC_CASE_IDS)
def test_calculate_temporary_bill_then_cleanup(
    fresh_login_page: Page,
    record_property: pytest.RecordProperty,
    account_role: str,
    case_id: str,
) -> None:
    data, expected_amount, scenario_id = _data(case_id)
    portal = PortalPage(fresh_login_page)
    calculation = BillingCalculationPage(fresh_login_page)
    billing_center = BillingCenterPage(fresh_login_page)
    bill_number: str | None = None
    bill_numbers: list[str] = []
    submission_started = False

    try:
        portal.open_home(
            settings.base_url,
            settings.master_customer_id,
            environment=settings.test_environment,
            account_role=account_role,
        )
        # 运行前按账期+房间+收费项只读预检：已有有效账单则保留原数据并跳过；
        # 预检查询本身失败时也跳过（失败安全）。
        portal.open_billing_center()
        billing_center.wait_until_ready()

        def _query_bills() -> list[str]:
            billing_center.select_project(data.project_name)
            return billing_center.get_bill_numbers_by_month_room_charge_item(
                billing_month=data.billing_month,
                room_path=data.room_path,
                charge_item=data.charge_item,
                allow_empty=True,
            )

        def _reopen_billing_center() -> None:
            portal.open_billing_center()
            billing_center.wait_until_ready()

        ensure_no_active_bill(
            case_id=case_id,
            entrypoint="计费出账",
            key=BillKey(
                billing_month=data.billing_month,
                room_path=data.room_path,
                charge_item=data.charge_item,
            ),
            record_property=record_property,
            query=_query_bills,
            reset=_reopen_billing_center,
        )
        portal.open_billing_calculation()
        calculation.wait_until_ready()
        calculation.select_project(data.project_name)
        drawer = calculation.open_temporary_calculation()
        calculation.configure_temporary_calculation(drawer, data)
        # Do not touch pre-existing pending cards when a case fails before its
        # own submission.  Pending cleanup is a fallback only after this case
        # has actually entered the submit flow.
        submission_started = True
        calculation.submit_temporary_calculation(drawer)

        portal.open_billing_center()
        billing_center.wait_until_ready()
        bill_numbers = billing_center.get_bill_numbers_by_month_room_charge_item(
            billing_month=data.billing_month,
            room_path=data.room_path,
            charge_item=data.charge_item,
        )
        if len(bill_numbers) != 1:
            raise AssertionError(
                f"计费出账后按账期+房间+收费项应唯一匹配账单，实际 {len(bill_numbers)} 条"
            )
        bill_number = bill_numbers[-1]
        row = billing_center._find_main_table_row(bill_number=bill_number)
        expect(row).to_contain_text(data.charge_item)
        expect(row).to_contain_text(format(expected_amount, "f"))
        record_property(
            "created_bill",
            json.dumps(
                {
                    "case_id": case_id,
                    "scenario_id": scenario_id,
                    "bill_number": bill_number,
                    "room": data.room_path,
                    "billing_month": data.billing_month,
                    "expected_amount": format(expected_amount, "f"),
                },
                ensure_ascii=False,
            ),
        )
    finally:
        if bill_numbers and settings.cleanup_created_bill:
            if not settings.allow_bill_deletion:
                pytest.fail(
                    "已创建临时类计费出账账单但禁止删除；请设置 ALLOW_BILL_DELETION=true。"
                )
            for number in reversed(dict.fromkeys(bill_numbers)):
                # The created number is authoritative.  Re-querying by an
                # exact month here can return zero in builds whose list query
                # uses the full year range, which previously skipped cleanup.
                billing_center.cleanup_by_month_room_charge_item(
                    billing_month=data.billing_month,
                    room_path=data.room_path,
                    charge_item=data.charge_item,
                    void_reason=settings.void_reason,
                )
        if (
            sys.exc_info()[0] is not None
            and submission_started
            and settings.allow_bill_deletion
        ):
            try:
                # A failed lookup may already have navigated to Bill Center;
                # explicitly return to calculation before looking for pending
                # cards.
                portal.open_billing_calculation()
                calculation.wait_until_ready()
                calculation.cleanup_pending_records()
            except Exception as cleanup_error:
                Path("artifacts").mkdir(exist_ok=True)
                Path("artifacts/calculation-temporary-pending-cleanup-error.txt").write_text(
                    repr(cleanup_error), encoding="utf-8"
                )
