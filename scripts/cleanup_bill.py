from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.settings import settings  # noqa: E402
from src.pages.billing_center_page import BillingCenterPage  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402


AUTH_FILE = ROOT / ".auth" / "user.json"
SESSION_FILE = ROOT / ".auth" / "session-storage.json"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("用法：python scripts/cleanup_bill.py <账单编号>")
    if not settings.allow_bill_deletion:
        raise SystemExit("ALLOW_BILL_DELETION 未开启，禁止删除账单。")

    bill_number_argument = sys.argv[1].strip()
    session_storage = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    storage_json = json.dumps(session_storage, ensure_ascii=False)
    restore_script = """
    (() => {
      const storage = __SESSION_STORAGE__;
      for (const [key, value] of Object.entries(storage)) {
        window.sessionStorage.setItem(key, value);
      }
    })();
    """.replace("__SESSION_STORAGE__", storage_json)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False, slow_mo=200)
        context = browser.new_context(storage_state=str(AUTH_FILE))
        context.add_init_script(script=restore_script)
        page = context.new_page()

        portal = PortalPage(page)
        billing_center = BillingCenterPage(page)
        portal.open_home(settings.base_url, settings.master_customer_id)
        portal.open_billing_center()
        billing_center.wait_until_ready()
        billing_center.select_project(settings.project_name)
        if bill_number_argument == "--only-result":
            bill_number = billing_center.get_only_result_bill_number(
                settings.billing_month, settings.room_path
            )
        else:
            bill_number = bill_number_argument
        billing_center.cleanup_bill(
            bill_number, settings.void_reason, settings.billing_month
        )

        browser.close()
    print(f"账单已作废并删除：{bill_number}")


if __name__ == "__main__":
    main()
