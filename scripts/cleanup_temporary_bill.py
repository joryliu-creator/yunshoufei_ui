"""Clean one direct Temporary Ledger bill by business-key search."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.settings import settings  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402
from src.pages.temporary_ledger_page import TemporaryLedgerPage  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="按账期+房间+收费项作废并删除临时台账记录"
    )
    parser.add_argument("--billing-month", required=True)
    parser.add_argument("--room", required=True, help="完整房间路径")
    parser.add_argument("--charge-item", required=True)
    parser.add_argument("--headful", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not settings.allow_bill_deletion:
        raise SystemExit("ALLOW_BILL_DELETION 未开启，禁止删除临时台账记录")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headful)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            portal = PortalPage(page)
            portal.open_home(
                settings.base_url,
                settings.master_customer_id,
                environment=settings.test_environment,
                account_role="default",
            )
            portal.open_temporary_ledger()
            ledger = TemporaryLedgerPage(page)
            ledger.wait_until_ready()
            cleaned = ledger.cleanup_by_month_room_charge_item(
                billing_month=args.billing_month.strip(),
                room_path=args.room.strip(),
                charge_item=args.charge_item.strip(),
                void_reason=settings.void_reason,
            )
            print(f"临时台账清理完成，定位并处理 {len(set(cleaned))} 条记录")
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
