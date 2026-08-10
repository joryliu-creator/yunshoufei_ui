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
    customer_account_env_prefix,
    get_account_auth_profile,
    normalize_account_role,
    normalize_customer_id,
)
from src.config.environments import (  # noqa: E402
    load_test_environment,
    normalize_test_environment,
)


BASE_DATA_FILE = ROOT / "自动化测试基础数据.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="保存指定测试账号的登录状态。")
    parser.add_argument(
        "--account",
        "--account-role",
        dest="account_role",
        default=None,
        help="账号别名，例如 billing_admin 或 cashier。",
    )
    parser.add_argument(
        "--environment",
        "--test-env",
        dest="test_environment",
        default=None,
        help="测试环境：standard1、standard2、uat 或 prod。",
    )
    parser.add_argument(
        "--customer-id",
        default=None,
        help="客户号，例如 93537。",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="登录后保持浏览器打开 5 分钟。",
    )
    return parser.parse_args()


def load_credentials(
    environment: str, customer_id: str, role: str
) -> tuple[str, str, str] | None:
    scoped_prefix = customer_account_env_prefix(customer_id, role)
    username = os.getenv(f"{scoped_prefix}_USERNAME", "").strip()
    password = os.getenv(f"{scoped_prefix}_PASSWORD", "").strip()
    captcha = os.getenv(f"{scoped_prefix}_CAPTCHA", "").strip()

    is_legacy_standard1 = environment == "standard1" and customer_id == "93537"
    if is_legacy_standard1:
        legacy_prefix = account_env_prefix(role)
        username = username or os.getenv(
            f"{legacy_prefix}_USERNAME", ""
        ).strip()
        password = password or os.getenv(
            f"{legacy_prefix}_PASSWORD", ""
        ).strip()
        captcha = captcha or os.getenv(
            f"{legacy_prefix}_CAPTCHA", ""
        ).strip()

        if role == "default":
            username = username or os.getenv("TEST_USERNAME", "").strip()
            password = password or os.getenv("TEST_PASSWORD", "").strip()
            captcha = captcha or os.getenv("CAPTCHA", "").strip()
    captcha = captcha or "0000"

    if username and password:
        return username, password, captcha

    if is_legacy_standard1 and role == "default" and BASE_DATA_FILE.exists():
        content = BASE_DATA_FILE.read_text(encoding="utf-8")
        match = re.search(
            r"测试账号\s*[:：]\s*(\S+)\s+密码\s*[:：]\s*(\S+)", content
        )
        if match:
            return match.group(1), match.group(2), captcha

    return None


def main() -> None:
    args = parse_args()
    environment = normalize_test_environment(
        args.test_environment or os.getenv("TEST_ENV")
    )
    load_test_environment(ROOT, environment)
    role = normalize_account_role(
        args.account_role or os.getenv("TEST_ACCOUNT_ROLE")
    )
    customer_id = normalize_customer_id(
        args.customer_id
        or os.getenv("CUSTOMER_ID")
        or os.getenv("MASTER_CUSTOMER_ID")
    )
    from src.config.settings import settings  # noqa: PLC0415

    profile = get_account_auth_profile(
        ROOT,
        role,
        environment,
        customer_id,
        allow_legacy_default=False,
    )
    profile.auth_file.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{settings.base_url}#/login", wait_until="domcontentloaded")

        credentials = load_credentials(environment, customer_id, role)
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
            print(
                f"已使用本地配置提交环境 {environment!r}、客户 "
                f"{customer_id!r}、账号别名 {role!r} 的登录。"
            )
        else:
            print(
                f"未找到环境 {environment!r}、客户 {customer_id!r}、"
                f"账号别名 {role!r} 的本地凭据，请在浏览器中完成登录；"
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
    print(
        f"环境 {environment!r}、客户 {customer_id!r}、账号别名 "
        f"{role!r} 的登录状态已保存到：{profile.auth_file.parent}"
    )


if __name__ == "__main__":
    main()
