"""Safely remove pending calculation-billing cards (non-production only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.accounts import get_account_auth_profile  # noqa: E402
from src.config.settings import settings  # noqa: E402
from src.pages.billing_calculation_page import BillingCalculationPage  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402


def main() -> None:
    if settings.test_environment == "prod":
        raise SystemExit("生产环境禁止清理计费出账待处理数据。")
    if not settings.allow_bill_deletion:
        raise SystemExit("ALLOW_BILL_DELETION 未开启，禁止删除计费出账待处理数据。")

    profile = get_account_auth_profile(
        ROOT, "default", settings.test_environment, settings.master_customer_id
    )
    if False:
        raise SystemExit(f"缺少登录状态文件：{profile.auth_file}")

    # Fall back to normal credential login when persisted browser state is stale.
    session_storage = None
    if profile.session_file.exists():
        try:
            session_storage = json.loads(profile.session_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            session_storage = None
    hostname = settings.base_url.split("//", 1)[-1].split("/", 1)[0]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        # Do not reuse stale cookies/session data during cleanup.  The portal
        # login recovery in PortalPage is the authoritative path.
        context = browser.new_context()
        page = context.new_page()
        try:
            portal = PortalPage(page)
            try:
                portal.open_home(
                    settings.base_url,
                    settings.master_customer_id,
                    environment=settings.test_environment,
                    account_role="default",
                )
            except AssertionError:
                # Standard1 can return a transient JIESHUN0997 after a
                # successful login callback.  Re-request the explicit
                # customer Home route once, as confirmed by the user.
                page.goto(
                    f"{settings.base_url}#/Home?masterCustomerId="
                    f"{settings.master_customer_id}",
                    wait_until="domcontentloaded",
                )
                page.wait_for_timeout(5_000)
            portal.open_billing_calculation()
            calculation = BillingCalculationPage(page)
            calculation.wait_until_ready()
            # The calculation page can finish its shell load before the
            # pending-card query returns.  Do not interpret the transient
            # empty state as the final result; wait for the card actions or
            # for the loading indicator to settle.
            page.wait_for_timeout(10_000)
            for _ in range(30):
                visible_text = calculation.shell_frame.locator("body").inner_text()
                if any(
                    marker in visible_text
                    for marker in ("核对账单", "审核账单", "删除", "暂无数据")
                ):
                    break
                page.wait_for_timeout(1_000)
            removed = calculation.cleanup_pending_records()
            if not any(removed.values()):
                artifacts = ROOT / "artifacts"
                artifacts.mkdir(exist_ok=True)
                page.screenshot(
                    path=str(artifacts / "calculation-pending-cleanup-empty.png"),
                    full_page=True,
                )
                (artifacts / "calculation-pending-cleanup-empty.txt").write_text(
                    calculation.shell_frame.locator("body").inner_text(),
                    encoding="utf-8",
                )
            print(f"计费出账待处理清理完成：{removed}")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
