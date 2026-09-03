from __future__ import annotations

import json
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from playwright.sync_api import Page

from scripts.add_bill_demo_to_excel import TEMPORARY_CASES
from src.config.excel_data import load_case_reference, load_excel_test_data
from src.config.settings import settings
from src.pages.portal_page import PortalPage
from src.pages.temporary_ledger_page import TemporaryBillData, TemporaryLedgerPage


TEMPORARY_CASE_IDS = [case[0] for case in TEMPORARY_CASES]
ROOT = Path(__file__).resolve().parents[2]
CREATED_BILL_ARTIFACT = ROOT / "artifacts" / "temporary-created-bill.json"

pytestmark = [
    pytest.mark.side_effect,
    pytest.mark.skipif(
        not settings.allow_bill_creation,
        reason="默认禁止创建临时账单；确认测试数据后设置 ALLOW_BILL_CREATION=true。",
    ),
]


@pytest.mark.parametrize("case_id", TEMPORARY_CASE_IDS)
def test_create_temporary_bill_assert_amount_and_cleanup(
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
    if scenario.charge_type != "临时类":
        pytest.fail(f"用例 {case_id} 未引用临时类场景。")

    expected_amount = Decimal(scenario.expected_receivable_amount)
    data = _temporary_bill_data(scenario)

    portal = PortalPage(page)
    temporary = TemporaryLedgerPage(page)
    created = None
    try:
        portal.open_home(
            settings.base_url,
            settings.master_customer_id,
            environment=settings.test_environment,
            account_role=account_role,
        )
        portal.open_temporary_ledger()
        temporary.wait_until_ready()
        existing_bill_numbers = temporary.visible_bill_numbers_for_room(
            data.room_path.split("/")[-1]
        )
        dialog = temporary.open_create_temporary_bill()
        temporary.fill_temporary_bill_before_submit(dialog, data)
        created = temporary.submit_and_read_created_bill(
            dialog,
            data,
            expected_amount,
            existing_bill_numbers,
        )
        record_property(
            "created_temporary_bill",
            json.dumps(
                {
                    "case_id": case_id,
                    "scenario_id": reference.scenario_id,
                    "room_path": data.room_path,
                    "charge_item": data.charge_item,
                    "charge_standard": data.charge_standard,
                    "billing_month": data.billing_month,
                    "amount": str(created.amount),
                    "bill_number": created.bill_number,
                },
                ensure_ascii=False,
            ),
        )
        # Persist the system-generated identifier before any destructive
        # cleanup. If cleanup fails, recovery can still target this exact
        # bill instead of guessing from room or billing month.
        CREATED_BILL_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        CREATED_BILL_ARTIFACT.write_text(
            json.dumps(
                {
                    "case_id": case_id,
                    "scenario_id": reference.scenario_id,
                    "room_path": data.room_path,
                    "billing_month": data.billing_month,
                    "charge_item": data.charge_item,
                    "amount": str(created.amount),
                    "bill_number": created.bill_number,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        if created is not None and settings.cleanup_created_bill:
            if not settings.allow_bill_deletion:
                pytest.fail(
                    "已创建临时账单但禁止删除；如需自动清理，请同时设置 "
                    "ALLOW_BILL_DELETION=true。"
                )
            temporary.cleanup_by_month_room_charge_item(
                billing_month=data.billing_month,
                room_path=data.room_path,
                charge_item=data.charge_item,
                void_reason=settings.void_reason,
                expected_bill_number=created.bill_number,
                require_match=True,
            )
            artifact = json.loads(CREATED_BILL_ARTIFACT.read_text(encoding="utf-8"))
            artifact["cleanup_status"] = "completed"
            CREATED_BILL_ARTIFACT.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


def _temporary_bill_data(scenario) -> TemporaryBillData:
    parameters = scenario.calculation_parameters
    billing_days = _decimal_parameter(parameters, "BILLING_DAYS")
    start_date = end_date = None
    if billing_days is not None:
        if billing_days != Decimal("2"):
            pytest.fail(
                f"临时类天数场景目前只确认了今明两天，实际参数={billing_days}"
            )
        start_date = date.today().isoformat()
        end_date = (date.today() + timedelta(days=1)).isoformat()
    return TemporaryBillData(
        room_path=scenario.room_path,
        billing_month=scenario.suggested_billing_month,
        charge_item=scenario.charge_item,
        charge_standard=scenario.charge_standard,
        remark="自动化测试出临时账单",
        manual_amount=_decimal_parameter(parameters, "MANUAL_AMOUNT"),
        meter_usage=_decimal_parameter(parameters, "METER_USAGE"),
        quantity=_decimal_parameter(parameters, "QUANTITY"),
        billing_period_start=start_date,
        billing_period_end=end_date,
        expected_amount=Decimal(scenario.expected_receivable_amount),
    )


def _decimal_parameter(parameters: str, name: str) -> Decimal | None:
    match = re.search(
        rf"(?:^|;){re.escape(name)}=([0-9]+(?:\.[0-9]+)?)(?:;|$)",
        parameters,
    )
    return Decimal(match.group(1)) if match else None
