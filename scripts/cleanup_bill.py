from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.settings import settings  # noqa: E402
from src.config.accounts import get_account_auth_profile  # noqa: E402
from src.pages.billing_center_page import BillingCenterPage  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402
from scripts.create_charge_standards import restore_session  # noqa: E402


def main() -> None:
    if len(sys.argv) != 7:
        raise SystemExit(
            "用法：python scripts/cleanup_bill.py --billing-month <YYYY-MM> "
            "--room <房间路径> --charge-item <收费项>"
        )
    if not settings.allow_bill_deletion:
        raise SystemExit("ALLOW_BILL_DELETION 未开启，禁止删除账单。")
    if sys.argv[1] != "--billing-month" or sys.argv[3] != "--room" or sys.argv[5] != "--charge-item":
        raise SystemExit(
            "参数顺序应为 --billing-month <YYYY-MM> --room <房间路径> --charge-item <收费项>"
        )
    billing_month = sys.argv[2].strip()
    room_path = sys.argv[4].strip()
    charge_item = sys.argv[6].strip()
    role = "default"
    profile = get_account_auth_profile(
        ROOT,
        role,
        settings.test_environment,
        settings.master_customer_id,
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        # Cleanup must not depend on an expired storage snapshot.  Start with
        # a fresh context so PortalPage can use the current local credentials
        # and recover the Standard1 callback deterministically.
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        portal = PortalPage(page)
        # Use the shared login recovery path.  The legacy helper only waited
        # for a username placeholder and could race the Standard1 login form,
        # leaving a generated bill uncleaned even though the account was valid.
        portal.open_home(
            settings.base_url,
            settings.master_customer_id,
            environment=settings.test_environment,
            account_role=role,
        )
        billing_center = BillingCenterPage(page)
        portal.open_billing_center()
        try:
            billing_center.wait_until_ready()
        except AssertionError:
            # 账单中心偶发初始化遮罩长期不消失；刷新并重开一次，
            # 不使用 force 穿透遮罩执行资金数据操作。
            page.reload(wait_until="domcontentloaded")
            portal.open_home(settings.base_url, settings.master_customer_id)
            portal.open_billing_center()
            billing_center.wait_until_table_readable()
        billing_center.select_project(settings.project_name)
        numbers = billing_center.get_bill_numbers_by_month_room_charge_item(
            billing_month=billing_month,
            room_path=room_path,
            charge_item=charge_item,
            include_voided=True,
            allow_empty=True,
        )
        for bill_number in reversed(numbers):
            billing_center.cleanup_bill(
                bill_number, settings.void_reason, billing_month
            )
        remaining = billing_center.get_bill_numbers_by_month_room_charge_item(
            billing_month=billing_month,
            room_path=room_path,
            charge_item=charge_item,
            allow_empty=True,
            include_voided=True,
        )
        if remaining:
            raise AssertionError(
                "清理后相同业务键仍匹配到账单：" + ", ".join(remaining)
            )

        browser.close()
        if numbers:
            print("账单已按业务键作废并删除：" + ", ".join(numbers))
        else:
            print("未发现匹配账单；业务键已确认无残留。")


if __name__ == "__main__":
    main()
