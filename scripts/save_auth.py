from __future__ import annotations

import argparse
import os
import re
import sys
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.accounts import (  # noqa: E402
    account_env_prefix,
    get_account_auth_profile,
    normalize_account_role,
)
from src.config.settings import settings  # noqa: E402


BASE_DATA_FILE = ROOT / "自动化测试基础数据.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="保存指定测试账号的登录状态。")
    parser.add_argument(
        "--account",
        "--account-role",
        dest="account_role",
        default=os.getenv("TEST_ACCOUNT_ROLE", "default"),
        help="账号别名，例如 billing_admin 或 cashier。",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="登录后保持浏览器打开 5 分钟。",
    )
    return parser.parse_args()


def load_credentials(role: str) -> tuple[str, str, str] | None:
    prefix = account_env_prefix(role)
    username = os.getenv(f"{prefix}_USERNAME", "").strip()
    password = os.getenv(f"{prefix}_PASSWORD", "").strip()
    captcha = os.getenv(f"{prefix}_CAPTCHA", "").strip()

    if role == "default":
        username = username or os.getenv("TEST_USERNAME", "").strip()
        password = password or os.getenv("TEST_PASSWORD", "").strip()
        captcha = captcha or os.getenv("CAPTCHA", "").strip()
    captcha = captcha or "0000"

    if username and password:
        return username, password, captcha

    if role == "default" and BASE_DATA_FILE.exists():
        content = BASE_DATA_FILE.read_text(encoding="utf-8")
        match = re.search(
            r"测试账号\s*[:：]\s*(\S+)\s+密码\s*[:：]\s*(\S+)", content
        )
        if match:
            return match.group(1), match.group(2), captcha

    return None


def main() -> None:
    args = parse_args()
    role = normalize_account_role(args.account_role)
    profile = get_account_auth_profile(
        ROOT, role, allow_legacy_default=False
    )
    profile.auth_file.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{settings.base_url}#/login", wait_until="domcontentloaded")

        credentials = load_credentials(role)
        if credentials is not None:
            username, password, captcha = credentials
            page.get_by_placeholder("用户名").fill(username)
            page.get_by_placeholder("密码").fill(password)
            page.get_by_placeholder("验证码", exact=True).fill(captcha)
            login_button = page.locator("button:visible").filter(
                has_text=re.compile(r"登\s*录")
            )
            expect(login_button).to_have_count(1)
            login_button.click()
            print(f"已使用本地配置提交账号别名 {role!r} 的登录。")
        else:
            print(
                f"未找到账号别名 {role!r} 的本地凭据，请在浏览器中完成登录；"
                "登录成功后脚本会保存状态。"
            )

        page.wait_for_url("**#/Home**", timeout=300_000)
        context.storage_state(path=str(profile.auth_file))
        session_storage = page.evaluate(
            "() => Object.fromEntries(Object.entries(sessionStorage))"
        )
        profile.session_file.write_text(
            json.dumps(session_storage, ensure_ascii=False), encoding="utf-8"
        )
        if args.inspect:
            print("检查模式：登录后窗口将保持打开 5 分钟。")
            page.wait_for_timeout(300_000)
        browser.close()
    print(f"账号别名 {role!r} 的登录状态已保存到：{profile.auth_file.parent}")


if __name__ == "__main__":
    main()
