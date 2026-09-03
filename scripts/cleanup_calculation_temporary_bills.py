"""Clean active temporary bills created through calculation or ledger entry.

Cleanup is intentionally performed in Bill Center by room and charge item;
the two entry points share the same bill records there.
"""
from __future__ import annotations

import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config.settings import settings  # noqa: E402
from src.pages.billing_center_page import BillingCenterPage  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402



def main() -> None:
    if not settings.allow_bill_deletion:
        raise SystemExit("ALLOW_BILL_DELETION 未开启，禁止清理账单。")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        portal = PortalPage(page)
        try:
            portal.open_home(settings.base_url, settings.master_customer_id, environment=settings.test_environment, account_role="default")
            portal.open_billing_center()
            billing = BillingCenterPage(page)
            billing.wait_until_ready()
            billing.select_project(settings.project_name)
            cleaned: list[str] = []
            numbers = billing.get_active_temporary_bill_numbers(
                billing_month=settings.billing_month
            )
            print(f"active temporary bills={len(numbers)}")
            for number in numbers:
                billing.cleanup_bill(
                    number, settings.void_reason, settings.billing_month
                )
                cleaned.append(number)
            print(f"total_cleaned={len(cleaned)}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
