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
    get_account_auth_profile,
    normalize_account_role,
    normalize_customer_id,
)
from src.config.credentials import load_local_credentials  # noqa: E402
from src.config.environments import (  # noqa: E402
    load_test_environment,
    normalize_test_environment,
)


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
    parser.add_argument(
        "--manual",
        action="store_true",
        help="不自动填写本地凭据，等待人工在浏览器中登录。",
    )
    return parser.parse_args()


def load_credentials(
    environment: str, customer_id: str, role: str
) -> tuple[str, str, str] | None:
    return load_local_credentials(ROOT, environment, customer_id, role)


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

        credentials = None if args.manual else load_credentials(
            environment, customer_id, role
        )
        if credentials is not None:
            username, password, captcha = credentials
            # The portal sometimes renders the login form after navigation;
            # its placeholder/ARIA text is not stable across deployments.
            # The three visible Element UI inputs keep a stable order:
            # username, password, captcha.
            login_inputs = page.locator("input.el-input__inner:visible")
            expect(login_inputs.nth(2)).to_be_visible(timeout=30_000)
            login_inputs.nth(0).fill(username)
            login_inputs.nth(1).fill(password)
            login_inputs.nth(2).fill(captcha)
            login_button = page.get_by_role(
                "button", name=re.compile(r"登\s*录")
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
