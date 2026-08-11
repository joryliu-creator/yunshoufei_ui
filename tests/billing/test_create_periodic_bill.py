from __future__ import annotations

import json

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
    page: Page, record_property: pytest.RecordProperty
) -> None:
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
        portal.open_home(settings.base_url, settings.master_customer_id)
        portal.open_billing_center()
        billing_center.wait_until_ready()
        billing_center.select_project(data.project_name)

        dialog = billing_center.open_create_bill()
        billing_center.fill_bill(dialog, data)
        created_bill = billing_center.submit_and_skip_notification(dialog, data)
        record_property(
            "created_bill",
            json.dumps(
                {
                    "bill_number": created_bill.bill_number,
                    "charge_item": created_bill.charge_item,
                    "receivable_date": created_bill.receivable_date,
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
            billing_center.cleanup_bill(
                created_bill.bill_number,
                settings.void_reason,
                data.billing_month,
            )
