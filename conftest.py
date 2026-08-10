from __future__ import annotations

import json
import os
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, BrowserContext, Page
from urllib.parse import urlparse

from src.config.accounts import (
    AccountAuthProfile,
    get_account_auth_profile,
    normalize_account_role,
    normalize_customer_id,
)
from src.config.environments import (
    load_test_environment,
    normalize_test_environment,
)


ROOT = Path(__file__).resolve().parent


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--test-env",
        action="store",
        default=None,
        help="测试环境：standard1、standard2、uat 或 prod。",
    )
    parser.addoption(
        "--account-role",
        action="store",
        default=None,
        help="本次测试使用的账号别名，例如 billing_admin 或 cashier。",
    )
    parser.addoption(
        "--customer-id",
        action="store",
        default=None,
        help="本次测试使用的客户号，例如 93537。",
    )


def pytest_configure(config: pytest.Config) -> None:
    requested = config.getoption("--test-env") or os.getenv("TEST_ENV")
    try:
        load_test_environment(ROOT, requested)
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc
    requested_customer = config.getoption("--customer-id")
    if requested_customer:
        try:
            os.environ["CUSTOMER_ID"] = normalize_customer_id(
                requested_customer
            )
        except ValueError as exc:
            raise pytest.UsageError(str(exc)) from exc


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    environment = normalize_test_environment(
        config.getoption("--test-env") or os.getenv("TEST_ENV")
    )
    if environment != "prod":
        return
    production_skip = pytest.mark.skip(
        reason="生产环境禁止执行带 side_effect 标记的用例。"
    )
    for item in items:
        if item.get_closest_marker("side_effect"):
            item.add_marker(production_skip)


@pytest.fixture(scope="session")
def test_environment(request: pytest.FixtureRequest) -> str:
    return normalize_test_environment(
        request.config.getoption("--test-env") or os.getenv("TEST_ENV")
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


@pytest.fixture
def customer_id(request: pytest.FixtureRequest) -> str:
    indirect_value = getattr(request, "param", None)
    marker = request.node.get_closest_marker("customer")
    marker_value = marker.args[0] if marker and marker.args else None
    command_value = request.config.getoption("--customer-id")
    environment_value = os.getenv("CUSTOMER_ID") or os.getenv(
        "MASTER_CUSTOMER_ID"
    )
    value = indirect_value or marker_value or command_value or environment_value
    try:
        return normalize_customer_id(value)
    except ValueError as exc:
        pytest.fail(str(exc), pytrace=False)


def _require_auth_profile(
    role: str, environment: str, customer_id: str
) -> AccountAuthProfile:
    profile = get_account_auth_profile(
        ROOT, role, environment, customer_id
    )
    if not profile.auth_file.exists() or not profile.session_file.exists():
        pytest.fail(
            f"环境 {profile.environment!r}、客户 {profile.customer_id!r} "
            f"的账号别名 {profile.role!r} "
            "尚未保存完整登录状态；请先运行 python scripts/save_auth.py "
            f"--environment {profile.environment} "
            f"--customer-id {profile.customer_id} --account {profile.role}。",
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
    allowed_hostname = urlparse(os.getenv("BASE_URL", "")).hostname
    if not allowed_hostname:
        pytest.fail("当前环境 BASE_URL 无效，无法安全恢复 sessionStorage。")
    hostname_json = json.dumps(allowed_hostname)
    restore_script = """
        (() => {
          const storage = __SESSION_STORAGE__;
          const allowedHostname = __ALLOWED_HOSTNAME__;
          if (window.location.hostname === allowedHostname) {
            for (const [key, value] of Object.entries(storage)) {
              window.sessionStorage.setItem(key, value);
            }
          }
        })();
        """.replace("__SESSION_STORAGE__", storage_json).replace(
            "__ALLOWED_HOSTNAME__", hostname_json
        )
    context.add_init_script(script=restore_script)


def _new_account_context(
    browser: Browser,
    browser_context_args: dict[str, Any],
    role: str,
    environment: str,
    customer_id: str,
) -> BrowserContext:
    profile = _require_auth_profile(role, environment, customer_id)
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
    test_environment: str,
    customer_id: str,
) -> Generator[BrowserContext, None, None]:
    account_context = _new_account_context(
        browser,
        browser_context_args,
        account_role,
        test_environment,
        customer_id,
    )
    yield account_context
    account_context.close()


@pytest.fixture
def account_context(
    browser: Browser,
    browser_context_args: dict[str, Any],
    test_environment: str,
    customer_id: str,
) -> Generator[Callable[..., BrowserContext], None, None]:
    """创建任意账号的独立上下文，供同一端到端用例切换多个账号。"""
    contexts: list[BrowserContext] = []

    def factory(role: str, target_customer_id: str | None = None) -> BrowserContext:
        created = _new_account_context(
            browser,
            browser_context_args,
            role,
            test_environment,
            normalize_customer_id(target_customer_id or customer_id),
        )
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
