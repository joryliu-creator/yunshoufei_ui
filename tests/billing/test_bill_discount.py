from __future__ import annotations

import json
import os
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from src.config.discount_data import load_bill_discount_case
from src.config.excel_data import load_excel_test_data
from src.config.settings import settings
from src.pages.bill_discount_page import BillDiscountPage
from src.pages.billing_center_page import BillData, BillingCenterPage
from src.pages.portal_page import PortalPage


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


pytestmark = [
    pytest.mark.side_effect,
    pytest.mark.skipif(
        not _enabled("ALLOW_BILL_DISCOUNT"),
        reason="账单减免真实操作默认关闭；设置 ALLOW_BILL_DISCOUNT=true 后执行。",
    ),
]


@pytest.mark.parametrize(
    "case_id",
    [
        "YSF-BILL-DISCOUNT-1101",
        "YSF-BILL-DISCOUNT-1102",
        "YSF-BILL-DISCOUNT-1103",
    ],
    ids=["room-1101", "room-1102", "room-1103"],
)


def test_bill_discount_apply_audit_assert_and_cleanup(
    page: Page,
    record_property: pytest.RecordProperty,
    account_role: str,
    case_id: str,
) -> None:
    case = load_bill_discount_case(case_id)
    if not settings.allow_bill_creation:
        pytest.skip("账单减免流程需要 ALLOW_BILL_CREATION=true")
    scenario_id = case.scenario_id.split("=", 1)[1]
    source = load_excel_test_data(
        settings.test_environment,
        settings.master_customer_id,
        scenario_id,
    )
    scenario = source.scenario
    billing_month = settings.billing_month
    created_bill = None
    bill_number = ""
    flow_completed = False
    portal = PortalPage(page)
    bill_center = BillingCenterPage(page)
    try:
        # 1-12：先创建目标房间账单并申请减免；每条用例独立清理。
        portal.open_home(
            settings.base_url,
            settings.master_customer_id,
            environment=settings.test_environment,
            account_role=account_role,
        )
        portal.open_billing_center()
        bill_center.wait_until_ready()
        bill_center.select_project(scenario.project_name)
        bill_data = BillData(
            project_name=scenario.project_name,
            room_path=scenario.room_path,
            charge_type=scenario.charge_type,
            charge_item=scenario.charge_item,
            billing_month=billing_month,
            receivable_date=settings.receivable_date,
            latest_payment_date=settings.latest_payment_date,
        )
        expected_original = Decimal(case.expected_original_amount)
        expected_discount = Decimal(case.expected_discount_amount)
        expected_receivable = Decimal(case.expected_receivable_amount)
        reused_row = None
        if _enabled("REUSE_EXISTING_DISCOUNT_BILL"):
            try:
                reused_row = bill_center.find_unique_bill_by_month_room_charge_item(
                    billing_month=billing_month,
                    room_path=scenario.room_path,
                    charge_item=scenario.charge_item,
                )
            except AssertionError as exc:
                if "实际可见行数=0" not in str(exc):
                    raise
        if reused_row is not None:
            bill_center.assert_row_amounts(
                reused_row,
                expected_original=expected_original,
                expected_discount=Decimal("0.00"),
                expected_receivable=expected_original,
            )
            bill_number = bill_center.bill_number_from_row(reused_row)
        else:
            dialog = bill_center.open_create_bill()
            bill_center.fill_bill(dialog, bill_data)
            try:
                created_bill = bill_center.submit_and_skip_notification(dialog, bill_data)
                bill_number = created_bill.bill_number
                bill_center.assert_bill_amounts(
                    created_bill,
                    expected_original=expected_original,
                    expected_discount=Decimal("0.00"),
                    expected_receivable=expected_original,
                )
            except AssertionError as exc:
                # A prior interrupted run can leave a valid bill hidden until
                # the list refreshes; adopt it only for the explicit reuse
                # mode, then continue through the normal discount and cleanup.
                if not (_enabled("REUSE_EXISTING_DISCOUNT_BILL") and "UN_DECLARE" in str(exc)):
                    raise
                close = dialog.locator(".el-drawer__close-btn:visible, button[aria-label*='关闭']:visible")
                if close.count() == 0:
                    close = dialog.get_by_text("关闭", exact=True)
                if close.count() == 1:
                    close.click(force=True)
                else:
                    page.keyboard.press("Escape")
                expect(dialog).to_be_hidden(timeout=10_000)
                reused_row = bill_center.find_unique_bill_by_month_room_charge_item(
                    billing_month=billing_month,
                    room_path=scenario.room_path,
                    charge_item=scenario.charge_item,
                )
                bill_center.assert_row_amounts(
                    reused_row,
                    expected_original=expected_original,
                    expected_discount=Decimal("0.00"),
                    expected_receivable=expected_original,
                )
                bill_number = bill_center.bill_number_from_row(reused_row)

        discount = BillDiscountPage(page)
        discount.open(scenario.project_name)
        discount.create_application(
            room_number=case.room_path.rsplit("/", 1)[-1],
            discount_scheme=case.discount_scheme,
            remark=case.remark,
            discount_amount=case.discount_amount_input,
        )
        discount.search_room(case.room_path.rsplit("/", 1)[-1])
        discount.audit_room(
            case.room_path.rsplit("/", 1)[-1],
            case.remark,
        )

        # 13-20：回到账单中心按账期+房间+收费项核对本金减免和应收金额。
        portal.open_billing_center()
        bill_center.wait_until_ready()
        bill_center.select_project(scenario.project_name)
        row = bill_center.find_unique_bill_by_month_room_charge_item(
            billing_month=billing_month,
            room_path=scenario.room_path,
            charge_item=scenario.charge_item,
        )
        bill_center.assert_row_amounts(
            row,
            expected_original=expected_original,
            expected_discount=expected_discount,
            expected_receivable=expected_receivable,
        )
        flow_completed = True
        record_property(
            "bill_discount",
            json.dumps(
                {
                    "case_id": case.case_id,
                    "scenario_id": scenario_id,
                    "room": scenario.room_path,
                    "scheme": case.discount_scheme,
                    "billing_month": billing_month,
                    "expected_discount": str(expected_discount),
                    "bill_number": bill_number,
                },
                ensure_ascii=False,
            ),
        )
    finally:
        keep_for_debug = (
            _enabled("DEFER_DISCOUNT_BILL_CLEANUP_ON_FAILURE")
            and not flow_completed
        )
        if bill_number and _enabled("CLEANUP_CREATED_BILL") and not keep_for_debug:
            if not _enabled("ALLOW_BILL_DELETION"):
                pytest.fail(
                    "账单减免账单已创建但未开启 ALLOW_BILL_DELETION=true，禁止宣称清理完成。"
                )
            # 申请/审核会把业务 iframe 切换到减免管理；清理必须重新进入
            # 账单中心并按业务组合定位，不能复用已失效的旧 frame。
            portal.open_billing_center()
            bill_center.wait_until_ready()
            bill_center.select_project(scenario.project_name)
            bill_center.cleanup_by_month_room_charge_item(
                billing_month=billing_month,
                room_path=scenario.room_path,
                charge_item=scenario.charge_item,
                void_reason=settings.void_reason,
            )
