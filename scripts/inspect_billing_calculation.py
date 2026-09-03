"""Read-only preflight for the regular billing-calculation screen.

It opens the calculation-condition drawer and records visible control labels.
It never clicks “下一步” or “开始计算”, so it cannot create a bill.
"""

from __future__ import annotations

import json
import argparse
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from src.config.accounts import get_account_auth_profile
from src.config.settings import settings
from src.pages.billing_calculation_page import BillingCalculationPage
from src.pages.portal_page import PortalPage


OUTPUT = ROOT / "artifacts" / "billing-calculation-preflight.json"
FAILURE_SCREENSHOT = ROOT / "artifacts" / "billing-calculation-preflight-failure.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="只读预检计费出账页面，不会创建账单。"
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="展示浏览器窗口，仅用于定位门户登录或页面加载问题。",
    )
    parser.add_argument(
        "--fresh-session",
        action="store_true",
        help="不恢复 .auth 中的旧登录态，仅验证一次全新自动登录。",
    )
    parser.add_argument(
        "--chrome-channel",
        action="store_true",
        help="使用本机 Chrome 通道，而非 Playwright 自带 Chromium。",
    )
    parser.add_argument(
        "--hold-seconds",
        type=int,
        default=0,
        help="在预检失败时保留浏览器窗口的秒数，仅用于人工观察。",
    )
    parser.add_argument(
        "--login-only",
        action="store_true",
        help="登录成功后不进入任何业务模块。",
    )
    parser.add_argument(
        "--calculation-page-only",
        action="store_true",
        help="仅打开计费出账首屏并保留浏览器，不点击开始计算。",
    )
    parser.add_argument(
        "--regular-drawer-only",
        action="store_true",
        help="仅打开常规类出账条件抽屉并保留浏览器，不填写或开始计算。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    profile = get_account_auth_profile(
        ROOT,
        "default",
        settings.test_environment,
        settings.master_customer_id,
    )
    if not args.fresh_session and not profile.auth_file.exists():
        raise FileNotFoundError(f"缺少登录状态文件：{profile.auth_file}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=not args.headed,
            channel="chrome" if args.chrome_channel else None,
        )
        if args.fresh_session:
            context = browser.new_context()
        else:
            context = browser.new_context(storage_state=str(profile.auth_file))
            session_storage = json.loads(
                profile.session_file.read_text(encoding="utf-8")
            )
            if not isinstance(session_storage, dict):
                raise ValueError("保存的 sessionStorage 必须是 JSON 对象。")
            hostname = settings.base_url.split("//", 1)[-1].split("/", 1)[0]
            context.add_init_script(
                """
                (() => {
                  const storage = __STORAGE__;
                  if (window.location.hostname === __HOSTNAME__) {
                    for (const [key, value] of Object.entries(storage)) {
                      window.sessionStorage.setItem(key, value);
                    }
                  }
                })();
                """
                .replace("__STORAGE__", json.dumps(session_storage, ensure_ascii=False))
                .replace("__HOSTNAME__", json.dumps(hostname))
            )
        page = context.new_page()
        login_responses: list[dict[str, object]] = []
        login_api_results: list[dict[str, object]] = []

        def record_login_response(response) -> None:
            path = urlsplit(response.url).path.lower()
            if any(token in path for token in ("login", "menu", "user", "portal")):
                login_responses.append({"path": path, "status": response.status})
            if any(
                endpoint in path
                for endpoint in (
                    "/jportal-login/login",
                    "/getaccountnfobytoken",
                    "/queryaccountmenuandpermission",
                )
            ):
                result: dict[str, object] = {"path": path, "status": response.status}
                try:
                    payload = response.json()
                    if isinstance(payload, dict):
                        for key in (
                            "success",
                            "respCode",
                            "respMsg",
                            "code",
                            "msg",
                            "message",
                        ):
                            if key in payload:
                                result[key] = payload[key]
                except Exception:
                    result["body"] = "unavailable"
                login_api_results.append(result)

        page.on("response", record_login_response)
        portal = PortalPage(page)
        calculation = BillingCalculationPage(page)
        try:
            try:
                portal.open_home(
                    settings.base_url,
                    settings.master_customer_id,
                    environment=settings.test_environment,
                    account_role="default",
                )
                if args.login_only:
                    print("portal login passed")
                    if args.hold_seconds > 0:
                        page.wait_for_timeout(args.hold_seconds * 1_000)
                    return
            except Exception as exc:
                OUTPUT.parent.mkdir(exist_ok=True)
                page.screenshot(path=str(FAILURE_SCREENSHOT), full_page=True)
                OUTPUT.write_text(
                    json.dumps(
                        {
                            "error": str(exc),
                            "screenshot": str(FAILURE_SCREENSHOT),
                            "url": page.url,
                            "title": page.title(),
                            "visible_inputs": page.locator("input:visible").evaluate_all(
                                "items => items.map(item => ({placeholder: item.placeholder, "
                                "readonly: item.readOnly, type: item.type}))"
                            ),
                            "visible_errors": page.locator(
                                ".el-message:visible, .el-form-item__error:visible"
                            ).all_inner_texts(),
                            "login_responses": login_responses,
                            "login_api_results": login_api_results,
                            "cloud_billing_text_count": page.get_by_text(
                                "云收费", exact=True
                            ).count(),
                            "cloud_billing_visible_count": page.get_by_text(
                                "云收费", exact=True
                            ).evaluate_all(
                                "items => items.filter(item => !!(item.offsetWidth || item.offsetHeight || item.getClientRects().length)).length"
                            ),
                            "body_contains_cloud_billing": "云收费"
                            in page.locator("body").inner_text(),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                if args.hold_seconds > 0:
                    page.wait_for_timeout(args.hold_seconds * 1_000)
                raise
            portal.open_billing_calculation()
            if args.calculation_page_only:
                print("calculation page opened")
                if args.hold_seconds > 0:
                    page.wait_for_timeout(args.hold_seconds * 1_000)
                return
            calculation.wait_until_ready()
            if args.regular_drawer_only:
                calculation.open_regular_calculation()
                print("regular calculation drawer opened")
                if args.hold_seconds > 0:
                    page.wait_for_timeout(args.hold_seconds * 1_000)
                return
            condition = calculation.open_regular_calculation()
            payload = {
                "url": page.url,
                "visible_buttons": condition.locator("button:visible").all_inner_texts(),
                "visible_inputs": condition.locator("input:visible").evaluate_all(
                    "items => items.map(item => ({placeholder: item.placeholder, "
                    "readonly: item.readOnly, type: item.type}))"
                ),
                "visible_text": condition.inner_text(),
            }
            OUTPUT.parent.mkdir(exist_ok=True)
            OUTPUT.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"preflight={OUTPUT}")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
