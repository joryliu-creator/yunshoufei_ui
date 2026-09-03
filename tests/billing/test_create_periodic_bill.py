from __future__ import annotations

import json
from decimal import Decimal

import pytest
from playwright.sync_api import Page

from src.config.settings import settings
from src.pages.billing_center_page import BillData, BillingCenterPage
from src.pages.portal_page import PortalPage


pytestmark = [
    pytest.mark.scenario("YSF-SCENE-PERIODIC-001"),
    pytest.mark.side_effect,
    pytest.mark.skipif(
        not settings.allow_bill_creation,
        reason="默认禁止创建账单；确认测试数据后设置 ALLOW_BILL_CREATION=true。",
    ),
]


def test_create_periodic_bill_and_cleanup(
    page: Page, record_property: pytest.RecordProperty, account_role: str
) -> None:
    if settings.charge_type != "周期类":
        pytest.skip("当前用例编号不是周期类出账场景。")
    if not settings.skip_bill_notification:
        pytest.fail("当前 Demo 仅支持提交后选择“不需要”发送通知。")

    data = BillData(
        project_name=settings.project_name,
        room_path=settings.room_path,
        charge_type=settings.charge_type,
        charge_item=settings.charge_item,
        billing_month=settings.billing_month,
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
            expected_original=Decimal(settings.expected_original_amount),
            expected_discount=Decimal(settings.expected_discount_amount),
            expected_receivable=Decimal(settings.expected_receivable_amount),
        )
        record_property(
            "created_bill",
            json.dumps(
                {
                    "bill_number": created_bill.bill_number,
                    "charge_item": created_bill.charge_item,
                    "receivable_date": created_bill.receivable_date,
                    "original_amount": str(created_bill.original_amount),
                    "discount_amount": str(created_bill.discount_amount),
                    "receivable_amount": str(created_bill.receivable_amount),
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
