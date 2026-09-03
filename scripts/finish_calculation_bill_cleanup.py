"""Finish cleanup for one already-approved calculation-billing result.

This recovery helper performs no calculation or bill creation.  It only opens
the existing “查看账单” result, finds the active Bill Center row through the
room/month filter, and delegates void/delete to BillingCenterPage.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.excel_data import load_excel_test_data  # noqa: E402
from src.config.settings import settings  # noqa: E402
from src.pages.billing_calculation_page import BillingCalculationPage  # noqa: E402
from src.pages.billing_center_page import BillingCenterPage  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402


def main() -> None:
    if not settings.allow_bill_deletion:
        raise SystemExit("ALLOW_BILL_DELETION 未开启，禁止作废和删除账单。")
    source = load_excel_test_data(
        settings.test_environment,
        settings.master_customer_id,
        settings.scenario_id,
    )
    expected_amount = format(
        Decimal(source.scenario.expected_receivable_amount), "f"
    )
    billing_month = source.runtime_parameters["CALCULATION_BILLING_MONTH"]
    if billing_month == "执行当月":
        billing_month = settings.billing_month

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            portal = PortalPage(page)
            portal.open_home(
                settings.base_url,
                settings.master_customer_id,
                environment=settings.test_environment,
                account_role="default",
            )
            # 审核通过后计费出账 iframe 可能被门户回收；清理入口本来就
            # 必须是账单中心，因此直接打开账单中心继续唯一筛选。
            portal.open_billing_center()

            billing_center = BillingCenterPage(page)
            billing_center.wait_until_ready()
            bill_number = billing_center.get_calculation_result_bill_number(
                billing_month=billing_month,
                room_path=source.scenario.room_path,
                charge_item=source.scenario.charge_item,
                expected_amount=expected_amount,
            )
            row = billing_center._find_main_table_row(bill_number=bill_number)
            expect(row).to_contain_text(source.scenario.charge_item)
            expect(row).to_contain_text(expected_amount)
            billing_center.cleanup_bill(
                bill_number, settings.void_reason, billing_month
            )
            print(f"已作废并删除计费出账账单：{bill_number}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
