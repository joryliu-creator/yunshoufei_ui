from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.create_charge_standards import restore_session  # noqa: E402
from src.config.accounts import get_account_auth_profile  # noqa: E402
from src.config.settings import settings  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402
from src.pages.temporary_ledger_page import TemporaryLedgerPage  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="只读列出指定房间的临时台账唯一账单号"
    )
    parser.add_argument("--room-name", required=True)
    parser.add_argument(
        "--inspect-advanced-search",
        action="store_true",
        help="只读输出高级搜索内可见输入框与标签，用于定位筛选字段。",
    )
    parser.add_argument(
        "--inspect-room-selector",
        action="store_true",
        help="只读切换账单对象为房间，并输出新版房间选择组件 DOM。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    room_name = args.room_name.strip()
    profile = get_account_auth_profile(
        ROOT,
        "default",
        settings.test_environment,
        settings.master_customer_id,
    )
    if not profile.auth_file.exists() or not profile.session_file.exists():
        raise SystemExit("未找到当前环境、客户和账号的隔离登录状态。")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(profile.auth_file))
        restore_session(context, profile, settings.base_url)
        page = context.new_page()
        try:
            portal = PortalPage(page)
            ledger = TemporaryLedgerPage(page)
            portal.open_home(
                settings.base_url,
                settings.master_customer_id,
                environment=settings.test_environment,
                account_role="default",
            )
            portal.open_temporary_ledger()
            ledger.wait_until_ready()
            if args.inspect_room_selector:
                search = ledger.open_advanced_search()
                object_control = search.get_by_text(
                    re.compile(r"账单对象\s*[-:]\s*全部"), exact=False
                )
                visible_controls = [
                    object_control.nth(index)
                    for index in range(object_control.count())
                    if object_control.nth(index).is_visible()
                ]
                if len(visible_controls) != 1:
                    raise AssertionError(
                        f"账单对象筛选控件应唯一可见，实际 {len(visible_controls)} 个"
                    )
                visible_controls[0].hover(force=True)
                page.wait_for_timeout(800)
                visible_controls[0].click(force=True)
                page.wait_for_timeout(800)
                room_option = ledger.frame.get_by_text("房间", exact=True)
                visible_room_options = [
                    room_option.nth(index)
                    for index in range(room_option.count())
                    if room_option.nth(index).is_visible()
                ]
                if len(visible_room_options) != 1:
                    poppers = ledger.frame.locator(
                        ".el-popper:visible, .el-dropdown-menu:visible"
                    )
                    print(
                        json.dumps(
                            {
                                "room_option_total": room_option.count(),
                                "room_option_visible": len(visible_room_options),
                                "dialog_text": search.inner_text(),
                                "visible_poppers": [
                                    poppers.nth(index).inner_text()
                                    for index in range(poppers.count())
                                ],
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                    page.screenshot(
                        path=str(
                            ROOT / "artifacts" / "temporary-room-object-debug.png"
                        ),
                        full_page=False,
                    )
                    return
                visible_room_options[0].click(force=True)
                page.wait_for_timeout(500)

                fields = []
                inputs = search.locator("input:visible")
                for index in range(inputs.count()):
                    field = inputs.nth(index)
                    fields.append(
                        {
                            "index": index,
                            "placeholder": field.get_attribute("placeholder"),
                            "readonly": field.get_attribute("readonly"),
                            "value": field.input_value(),
                            "outer_html": field.evaluate("(node) => node.outerHTML"),
                            "parent_html": field.evaluate(
                                "(node) => node.parentElement.outerHTML"
                            ),
                            "form_item_text": field.evaluate(
                                "(node) => { const item = node.closest('.el-form-item'); "
                                "return item ? item.innerText : ''; }"
                            ),
                        }
                    )
                print(json.dumps(fields, ensure_ascii=False, indent=2))

                room_candidates = search.locator(
                    'input[placeholder="请选择"]:visible'
                )
                for index in range(room_candidates.count()):
                    candidate = room_candidates.nth(index)
                    candidate.click(force=True)
                    page.wait_for_timeout(700)
                    poppers = ledger.frame.locator(
                        ".el-popper:visible, .el-cascader__dropdown:visible, "
                        ".el-select-dropdown:visible"
                    )
                    snapshot = []
                    for popup_index in range(poppers.count()):
                        popup = poppers.nth(popup_index)
                        snapshot.append(
                            {
                                "class": popup.get_attribute("class"),
                                "text": popup.inner_text(),
                                "tree_count": popup.locator(".el-tree").count(),
                                "editable_inputs": popup.locator(
                                    "input:visible:not([readonly]):not([disabled])"
                                ).count(),
                            }
                        )
                    print(
                        json.dumps(
                            {"clicked_candidate": index, "poppers": snapshot},
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                    page.keyboard.press("Escape")
                page.screenshot(
                    path=str(ROOT / "artifacts" / "temporary-room-selector-dom.png"),
                    full_page=False,
                )
                return
            if args.inspect_advanced_search:
                search = ledger.open_advanced_search()
                fields = []
                for index in range(search.locator("input:visible").count()):
                    field = search.locator("input:visible").nth(index)
                    fields.append(
                        {
                            "placeholder": field.get_attribute("placeholder"),
                            "value": field.input_value(),
                            "outer_html": field.evaluate("(node) => node.outerHTML"),
                            "parent_text": field.locator("xpath=..").inner_text(),
                        }
                    )
                print(json.dumps(fields, ensure_ascii=False, indent=2))
                return
            rows = ledger.frame.locator(
                ".el-table__body-wrapper tr.el-table__row:visible"
            ).filter(has_text=room_name)
            result: list[dict[str, str]] = []
            for index in range(rows.count()):
                text = rows.nth(index).inner_text()
                identifiers = re.findall(
                    r"(?<![\w-])[A-Z]{2,}[A-Z0-9-]{5,}(?![\w-])", text
                )
                if len(identifiers) == 1:
                    result.append({"bill_number": identifiers[0], "row": text})
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
