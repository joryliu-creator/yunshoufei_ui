from __future__ import annotations

import json
import os
from pathlib import Path
from dataclasses import dataclass
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from src.config.settings import settings
from src.pages.billing_calculation_page import BillingCalculationPage, TemporaryCalculationData
from src.pages.billing_center_page import BillingCenterPage
from src.pages.portal_page import PortalPage
from src.pages.temporary_ledger_page import TemporaryBillData, TemporaryLedgerPage


@dataclass(frozen=True, slots=True)
class DepositCase:
    case_id: str
    room: str
    standard: str
    expected: Decimal
    manual_amount: Decimal | None = None
    quantity: Decimal | None = None


DEPOSIT_CASES = (
    DepositCase(
        "YSF-BILL-DEPOSIT-001",
        "1021",
        "押金类-人工输入收费金额",
        Decimal("2000.00"),
        manual_amount=Decimal("2000"),
    ),
    DepositCase(
        "YSF-BILL-DEPOSIT-002",
        "1022",
        "押金类-固定金额",
        Decimal("100.00"),
    ),
    DepositCase(
        "YSF-BILL-DEPOSIT-003",
        "1023",
        "押金类-数量公式（数量*单价）",
        Decimal("100.00"),
        quantity=Decimal("10"),
    ),
    DepositCase(
        "YSF-BILL-DEPOSIT-004",
        "1024",
        "押金类-面积公式（计费面积*单价）建筑",
        Decimal("3001.20"),
    ),
    DepositCase(
        "YSF-BILL-DEPOSIT-005",
        "1025",
        "押金类-面积公式（计费面积*单价）使用",
        Decimal("2800.10"),
    ),
    DepositCase(
        "YSF-BILL-DEPOSIT-006",
        "1026",
        "押金类-面积公式（计费面积*单价）收费",
        Decimal("26000.00"),
    ),
)


pytestmark = [
    pytest.mark.scenario("YSF-SCENE-DEPOSIT-TEMPORARY"),
    pytest.mark.side_effect,
    pytest.mark.skipif(
        not settings.allow_bill_creation,
        reason="默认禁止创建押金账单；需显式开启 ALLOW_BILL_CREATION=true。",
    ),
]


def _room_path(room: str) -> str:
    return f"A栋/1层/{room}"


@pytest.mark.parametrize("case", DEPOSIT_CASES, ids=lambda item: item.case_id)
def test_deposit_bill_in_temporary_ledger_then_room_cleanup(
    fresh_login_page: Page,
    account_role: str,
    record_property: pytest.RecordProperty,
    case: DepositCase,
) -> None:
    """押金类在临时台账生成后，按临时台账作废/删除流程清理。"""
    data = TemporaryBillData(
        room_path=_room_path(case.room),
        billing_month=settings.billing_month,
        charge_item="押金类收费项",
        charge_standard=case.standard,
        remark="自动化测试押金临时账单",
        manual_amount=case.manual_amount,
        quantity=case.quantity,
        expected_amount=case.expected,
    )
    portal = PortalPage(fresh_login_page)
    ledger = TemporaryLedgerPage(fresh_login_page)
    created = None
    try:
        portal.open_home(
            settings.base_url,
            settings.master_customer_id,
            environment=settings.test_environment,
            account_role=account_role,
        )
        portal.open_temporary_ledger()
        ledger.wait_until_ready()
        before = ledger.visible_bill_numbers_for_room(case.room)
        dialog = ledger.open_create_temporary_bill()
        ledger.fill_temporary_bill_before_submit(dialog, data)
        created = ledger.submit_and_read_created_bill(
            dialog, data, case.expected, before
        )
        record_property(
            "created_deposit_bill",
            json.dumps(
                {
                    "case_id": case.case_id,
                    "room": data.room_path,
                    "standard": case.standard,
                    "amount": format(case.expected, ".2f"),
                    "bill_number": created.bill_number,
                },
                ensure_ascii=False,
            ),
        )
    finally:
        if created is not None and settings.cleanup_created_bill:
            if not settings.allow_bill_deletion:
                pytest.fail(
                    "押金账单已创建但未授权删除；请同时开启 ALLOW_BILL_DELETION。"
                )
            ledger.cleanup_by_month_room_charge_item(
                billing_month=data.billing_month,
                room_path=data.room_path,
                charge_item=data.charge_item,
                void_reason=settings.void_reason,
                expected_bill_number=created.bill_number,
                require_match=True,
            )


@pytest.mark.parametrize("case", DEPOSIT_CASES, ids=lambda item: item.case_id)
def test_deposit_bill_in_calculation_then_bill_center_cleanup(
    fresh_login_page: Page,
    account_role: str,
    record_property: pytest.RecordProperty,
    case: DepositCase,
) -> None:
    """押金类经计费出账临时入口生成后，按账单中心流程清理。"""
    data = TemporaryCalculationData(
        project_name="云收费UI自动化",
        room_name=case.room,
        room_path=_room_path(case.room),
        billing_month=settings.billing_month,
        receivable_date=_today(),
        latest_payment_date=_today(),
        charge_item="押金类收费项",
        charge_standard=case.standard,
        manual_amount=format(case.manual_amount, "f") if case.manual_amount else None,
        quantity=format(case.quantity, "f") if case.quantity else None,
        expected_amount=format(case.expected, "f"),
    )
    portal = PortalPage(fresh_login_page)
    calculation = BillingCalculationPage(fresh_login_page)
    center = BillingCenterPage(fresh_login_page)
    bill_numbers: list[str] = []
    submitted = False
    try:
        portal.open_home(
            settings.base_url,
            settings.master_customer_id,
            environment=settings.test_environment,
            account_role=account_role,
        )
        portal.open_billing_calculation()
        calculation.wait_until_ready()
        calculation.select_project(data.project_name)
        drawer = calculation.open_temporary_calculation()
        calculation.configure_temporary_calculation(drawer, data)
        submitted = True
        calculation.submit_temporary_calculation(drawer)

        portal.open_billing_center()
        center.wait_until_ready()
        bill_numbers = center.get_bill_numbers_by_month_room_charge_item(
            billing_month=data.billing_month,
            room_path=data.room_path,
            charge_item=data.charge_item,
        )
        if len(bill_numbers) != 1:
            raise AssertionError(
                f"计费出账后按账期+房间+收费项应唯一匹配账单，实际 {len(bill_numbers)} 条"
            )
        bill_number = bill_numbers[-1]
        row = center._find_main_table_row(bill_number=bill_number)
        expect(row).to_contain_text(data.charge_item)
        expect(row).to_contain_text(format(case.expected, "f"))
        record_property("created_deposit_bill_number", bill_number)
    finally:
        if bill_numbers and settings.cleanup_created_bill:
            if not settings.allow_bill_deletion:
                pytest.fail(
                    "押金账单已创建但未授权删除；请同时开启 ALLOW_BILL_DELETION。"
                )
            # The bill was already resolved and validated by the exact
            # month + room + charge-item key above. Reopening Advanced
            # Search and selecting the room a second time adds a fragile
            # UI dependency and can leave the verified bill behind. Clean
            # every active match through the same authoritative key; each
            # cleanup_bill call asserts that its concrete row disappears.
            portal.open_billing_center()
            center.wait_until_ready()
            center.cleanup_by_month_room_charge_item(
                billing_month=data.billing_month,
                room_path=data.room_path,
                charge_item=data.charge_item,
                void_reason=settings.void_reason,
            )
        if submitted and not bill_numbers and settings.allow_bill_deletion:
            # The calculation page has its own pending-card fallback. This is
            # intentionally not used before the final submit click.
            try:
                portal.open_billing_calculation()
                calculation.wait_until_ready()
                calculation.cleanup_pending_records()
            except Exception as cleanup_error:
                # Never mask the original submission/assertion failure with a
                # broad cleanup locator failure; retain evidence for recovery.
                Path("artifacts").mkdir(exist_ok=True)
                Path("artifacts/deposit-calculation-pending-cleanup-error.txt").write_text(
                    repr(cleanup_error), encoding="utf-8"
                )


def _today() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def _current_month() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return "2026-08"
