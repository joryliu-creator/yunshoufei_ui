"""Remove active Bill Center bills for rooms 1001-1060."""
from __future__ import annotations

import re
import sys
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config.settings import settings  # noqa: E402
from src.pages.billing_center_page import BillingCenterPage  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402

BILL_RE = re.compile(r"(?:LS)?ZD[A-Z0-9]+")

def main() -> None:
    if not settings.allow_bill_deletion:
        raise SystemExit("ALLOW_BILL_DELETION must be true for the room gate")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            portal = PortalPage(page)
            portal.open_home(settings.base_url, settings.master_customer_id,
                             environment=settings.test_environment, account_role="default")
            portal.open_billing_center()
            billing = BillingCenterPage(page)
            billing.wait_until_ready()
            billing.select_project(settings.project_name)
            # Cleanup/gate invocations may override the workbook runtime
            # month explicitly (for example, fixed regression month 2026-08).
            # Settings otherwise prefers the scenario workbook value.
            billing_month = os.getenv("BILLING_MONTH", "").strip() or settings.billing_month
            billing._filter_billing_month(billing_month)
            # Element UI splits wide tables into left/main/right wrappers;
            # the bill-number cell may be rendered in a different wrapper
            # from the room columns.  Scan every visible body row and dedupe
            # bill numbers instead of assuming one wrapper contains all cells.
            body_text = billing.frame.locator("body").inner_text()
            targets = BILL_RE.findall(body_text)
            row_count = 0
            """
            for i in range(rows.count()):
                row = rows.nth(i)
                text = row.inner_text()
                if re.search(r"已作废|作废", text):
                    continue
                match = BILL_RE.search(text)
                if match:
                    targets.append(match.group(0))
            """
            unique = list(dict.fromkeys(targets))
            for number in unique:
                billing.cleanup_bill(number, settings.void_reason, billing_month)
            print(f"room_gate_candidates={len(unique)}")
            print(f"room_gate_cleaned={len(unique)}")
            if not unique:
                print(f"room_gate_visible_rows={row_count}")
                print("room_gate_body_excerpt=" + body_text[:1200].replace("\n", " | "))
        finally:
            browser.close()

if __name__ == "__main__":
    main()
