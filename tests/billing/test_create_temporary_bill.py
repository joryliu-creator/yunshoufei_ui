from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from playwright.sync_api import Page

from scripts.add_bill_demo_to_excel import TEMPORARY_CASES
from src.config.excel_data import load_case_reference, load_excel_test_data
from src.config.settings import settings
from src.domain.bill_presence import BillKey, ensure_no_active_bill, skip_existing_active_bill
from src.pages.portal_page import PortalPage
from src.pages.temporary_ledger_page import TemporaryBillData, TemporaryLedgerPage


TEMPORARY_CASE_IDS = [case[0] for case in TEMPORARY_CASES]
ROOT = Path(__file__).resolve().parents[2]
CREATED_BILL_ARTIFACT = Path(os.getenv("PLATFORM_RUN_ARTIFACTS_DIR", str(ROOT / "artifacts"))) / "temporary-created-bill.json"

pytestmark = [
    pytest.mark.side_effect,
    pytest.mark.skipif(
        not settings.allow_bill_creation,
        reason="默认禁止创建临时账单；确认测试数据后设置 ALLOW_BILL_CREATION=true。",
    ),
]


@pytest.mark.parametrize("case_id", TEMPORARY_CASE_IDS)
def test_create_temporary_bill_assert_amount_and_cleanup(
    fresh_login_page: Page,
    record_property: pytest.RecordProperty,
    account_role: str,
    case_id: str,
) -> None:
    page = fresh_login_page
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

        # 运行前按账期+房间+收费项只读预检：已有有效账单则保留原数据并跳过；
        # 预检查询本身失败时也跳过（失败安全）。
        def _query_bills() -> list[str]:
            active = temporary.filter_active_bill_numbers(
                temporary.get_bill_numbers_by_month_room_charge_item(
                    billing_month=data.billing_month,
                    room_path=data.room_path,
                    charge_item=data.charge_item,
                )
            )
            temporary._close_advanced_search_if_open()
            return active

        def _reopen_ledger() -> None:
            portal.open_temporary_ledger()
            temporary.wait_until_ready()

        ensure_no_active_bill(
            case_id=case_id,
            entrypoint="临时台账",
            key=BillKey(
                billing_month=data.billing_month,
                room_path=data.room_path,
                charge_item=data.charge_item,
            ),
            record_property=record_property,
            query=_query_bills,
            reset=_reopen_ledger,
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
        elif (
            temporary.last_submission_confirmed
            and not existing_bill_numbers
            and settings.cleanup_created_bill
        ):
            # A successful submit can still fail later while the page captures
            # the refreshed row. In that case, clean only this target that was
            # empty before the submit, using month + room + charge item.
            if not settings.allow_bill_deletion:
                pytest.fail(
                    "临时账单已提交但未捕获编号，且禁止按业务键清理；"
                    "请先核对该房间账期和收费项。"
                )
            cleaned = temporary.cleanup_by_month_room_charge_item(
                billing_month=data.billing_month,
                room_path=data.room_path,
                charge_item=data.charge_item,
                void_reason=settings.void_reason,
                require_match=False,
            )
            record_property(
                "cleanup_without_captured_bill_number",
                json.dumps(
                    {
                        "billing_month": data.billing_month,
                        "room_path": data.room_path,
                        "charge_item": data.charge_item,
                        "cleaned_count": len(cleaned),
                    },
                    ensure_ascii=False,
                ),
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
