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
    if len(sys.argv) not in {2, 4, 6, 8}:
        raise SystemExit(
            "用法：python scripts/cleanup_bill.py <账单编号|--only-result> "
            "[--room <房间路径>] [--billing-month <YYYY-MM>]"
        )
    if not settings.allow_bill_deletion:
        raise SystemExit("ALLOW_BILL_DELETION 未开启，禁止删除账单。")

    bill_number_argument = sys.argv[1].strip()
    room_path_override = None
    billing_month_override = None
    charge_item_override = None
    if len(sys.argv) == 4:
        if sys.argv[2] == "--room":
            room_path_override = sys.argv[3].strip()
        elif sys.argv[2] == "--billing-month":
            billing_month_override = sys.argv[3].strip()
        else:
            raise SystemExit("参数必须是 --room 或 --billing-month")
    if len(sys.argv) == 6:
        if sys.argv[2] != "--room" or sys.argv[4] != "--billing-month":
            raise SystemExit("参数顺序应为 --room <房间路径> --billing-month <YYYY-MM>")
        room_path_override = sys.argv[3].strip()
        billing_month_override = sys.argv[5].strip()
    if len(sys.argv) == 8:
        if sys.argv[2] != "--room" or sys.argv[4] != "--billing-month" or sys.argv[6] != "--charge-item":
            raise SystemExit("参数顺序应为 --room <房间路径> --billing-month <YYYY-MM> --charge-item <收费项>")
        room_path_override = sys.argv[3].strip()
        billing_month_override = sys.argv[5].strip()
        charge_item_override = sys.argv[7].strip()
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
        billing_month = billing_month_override or settings.billing_month
        room_path = room_path_override or settings.room_path
        if bill_number_argument == "--only-result":
            if charge_item_override:
                numbers = billing_center.get_bill_numbers_by_month_room_charge_item(
                    billing_month=billing_month,
                    room_path=room_path,
                    charge_item=charge_item_override,
                )
                for number in reversed(numbers):
                    billing_center.cleanup_bill(number, settings.void_reason, billing_month)
                bill_number = numbers[-1]
            else:
                bill_number = billing_center.get_only_result_bill_number(
                    billing_month,
                    room_path,
                    require_void=False,
                )
        else:
            bill_number = bill_number_argument
        billing_center.cleanup_bill(
            bill_number, settings.void_reason, billing_month
        )

        browser.close()
    print(f"账单已作废并删除：{bill_number}")


if __name__ == "__main__":
    main()
