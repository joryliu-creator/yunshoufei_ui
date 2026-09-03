"""Fill the 1032 Bill Center meter form without submitting it."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.excel_data import load_excel_test_data  # noqa: E402
from src.config.settings import settings  # noqa: E402
from src.pages.billing_center_page import BillData, BillingCenterPage  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402


def main() -> None:
    scenario = load_excel_test_data(
        settings.test_environment,
        settings.master_customer_id,
        "YSF-SCENE-METER-BILL-1032",
    ).scenario
    data = BillData(
        project_name=scenario.project_name,
        room_path=scenario.room_path,
        charge_type=scenario.charge_type,
        charge_item=scenario.charge_item,
        billing_month=scenario.suggested_billing_month,
        receivable_date=settings.receivable_date,
        latest_payment_date=settings.latest_payment_date,
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            portal = PortalPage(page)
            billing = BillingCenterPage(page)
            portal.open_home(
                settings.base_url,
                settings.master_customer_id,
                environment=settings.test_environment,
                account_role="default",
            )
            portal.open_billing_center()
            billing.wait_until_ready()
            billing.select_project(data.project_name)
            dialog = billing.open_create_bill()
            billing.fill_bill(dialog, data)
            row = dialog.locator("tr").filter(has_text=data.charge_item).first
            row.get_by_text("编辑", exact=True).click()
            page.wait_for_timeout(500)
            fields = row.locator("input").evaluate_all(
                "els => els.map(e => ({placeholder:e.placeholder, value:e.value, "
                "readonly:e.readOnly, disabled:e.disabled, type:e.type, outer:e.outerHTML}))"
            )
            buttons = dialog.locator("button:visible").evaluate_all(
                "els => els.map(e => ({text:e.innerText, disabled:e.disabled, "
                "className:e.className}))"
            )
            print(
                json.dumps(
                    {
                        "row_text": row.inner_text(),
                        "row_html": row.evaluate("e => e.outerHTML"),
                        "fields": fields,
                        "buttons": buttons,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            page.screenshot(
                path=str(ROOT / "artifacts" / "bill-center-meter-form.png"),
                full_page=False,
            )
        finally:
            browser.close()


if __name__ == "__main__":
    main()
