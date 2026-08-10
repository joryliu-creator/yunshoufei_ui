from __future__ import annotations

import json
import os
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Browser, BrowserContext, Page

from src.config.accounts import (
    AccountAuthProfile,
    get_account_auth_profile,
    normalize_account_role,
)


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--account-role",
        action="store",
        default=None,
        help="本次测试使用的账号别名，例如 billing_admin 或 cashier。",
    )


@pytest.fixture
def account_role(request: pytest.FixtureRequest) -> str:
    indirect_value = getattr(request, "param", None)
    marker = request.node.get_closest_marker("account")
    marker_value = marker.args[0] if marker and marker.args else None
    command_value = request.config.getoption("--account-role")
    environment_value = os.getenv("TEST_ACCOUNT_ROLE")
    value = indirect_value or marker_value or command_value or environment_value
    try:
        return normalize_account_role(value)
    except ValueError as exc:
        pytest.fail(str(exc), pytrace=False)


def _require_auth_profile(role: str) -> AccountAuthProfile:
    profile = get_account_auth_profile(ROOT, role)
    if not profile.auth_file.exists() or not profile.session_file.exists():
        pytest.fail(
            f"账号别名 {profile.role!r} 尚未保存完整登录状态；请先运行 "
            f"python scripts/save_auth.py --account {profile.role}。",
            pytrace=False,
        )
    return profile


def _restore_session_storage(
    context: BrowserContext, profile: AccountAuthProfile
) -> None:
    try:
        session_storage = json.loads(
            profile.session_file.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        pytest.fail(
            f"账号别名 {profile.role!r} 的 sessionStorage 文件无效：{exc}",
            pytrace=False,
        )
    if not isinstance(session_storage, dict):
        pytest.fail(
            f"账号别名 {profile.role!r} 的 sessionStorage 必须是 JSON 对象。",
            pytrace=False,
        )

    storage_json = json.dumps(session_storage, ensure_ascii=False)
    restore_script = """
        (() => {
          const storage = __SESSION_STORAGE__;
          if (window.location.hostname === 't.jslife.net') {
            for (const [key, value] of Object.entries(storage)) {
              window.sessionStorage.setItem(key, value);
            }
          }
        })();
        """.replace("__SESSION_STORAGE__", storage_json)
    context.add_init_script(script=restore_script)


def _new_account_context(
    browser: Browser,
    browser_context_args: dict[str, Any],
    role: str,
) -> BrowserContext:
    profile = _require_auth_profile(role)
    context_args = {
        **browser_context_args,
        "storage_state": str(profile.auth_file),
    }
    context_args.setdefault("viewport", {"width": 1440, "height": 900})
    context = browser.new_context(**context_args)
    _restore_session_storage(context, profile)
    return context


@pytest.fixture
def context(
    browser: Browser,
    browser_context_args: dict[str, Any],
    account_role: str,
) -> Generator[BrowserContext, None, None]:
    account_context = _new_account_context(
        browser, browser_context_args, account_role
    )
    yield account_context
    account_context.close()


@pytest.fixture
def account_context(
    browser: Browser,
    browser_context_args: dict[str, Any],
) -> Generator[Callable[[str], BrowserContext], None, None]:
    """创建任意账号的独立上下文，供同一端到端用例切换多个账号。"""
    contexts: list[BrowserContext] = []

    def factory(role: str) -> BrowserContext:
        created = _new_account_context(browser, browser_context_args, role)
        contexts.append(created)
        return created

    yield factory
    for created in reversed(contexts):
        created.close()


@pytest.fixture
def page(context: BrowserContext) -> Generator[Page, None, None]:
    created_page = context.new_page()
    yield created_page
    created_page.close()
