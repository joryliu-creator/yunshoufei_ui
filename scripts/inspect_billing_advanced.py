from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.settings import settings  # noqa: E402
from src.pages.billing_center_page import BillingCenterPage  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    portal = PortalPage(page)
    portal.open_home(
        settings.base_url,
        settings.master_customer_id,
        environment=settings.test_environment,
        account_role="default",
    )
    portal.open_billing_center()
    billing = BillingCenterPage(page)
    billing.wait_until_ready()
    Path("artifacts/billing-center-before-advanced.txt").write_text(
        billing.frame.locator("body").inner_text(), encoding="utf-8"
    )
    drawer = billing._open_advanced_search()
    room_input = drawer.locator('input[placeholder="请选择"]').first
    Path("artifacts/billing-room-input.html").write_text(
        room_input.evaluate("e => e.parentElement.parentElement.parentElement.outerHTML"),
        encoding="utf-8",
    )
    room_input.click()
    room_input.press_sequentially("1001", delay=120)
    room_input.press("Enter")
    page.wait_for_timeout(3000)
    Path("artifacts/billing-room-popups.txt").write_text(
        "\n--- dropdowns ---\n"
        + page.locator(".el-select-dropdown:visible").all_inner_texts().__repr__()
        + "\n--- trees ---\n"
        + page.locator(".el-tree:visible").all_inner_texts().__repr__(),
        encoding="utf-8",
    )
    Path("artifacts/billing-room-popovers.txt").write_text(
        billing.frame.locator(".el-popover:visible").all_inner_texts().__repr__(),
        encoding="utf-8",
    )
    popover = billing.frame.locator(".el-popover:visible").last
    Path("artifacts/billing-room-popover.html").write_text(
        popover.evaluate("e => e.outerHTML"), encoding="utf-8"
    )
    Path("artifacts/billing-advanced-body.txt").write_text(
        drawer.inner_text(), encoding="utf-8"
    )
    Path("artifacts/billing-advanced-inputs.json").write_text(
        str(
            drawer.locator("input:visible").evaluate_all(
                "els => els.map(e => ({placeholder:e.placeholder, value:e.value, readonly:e.readOnly, outer:e.outerHTML}))"
            )
        ),
        encoding="utf-8",
    )
    page.screenshot(path="artifacts/billing-advanced.png", full_page=True)
    browser.close()
