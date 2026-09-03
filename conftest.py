from __future__ import annotations

import json
import os
import subprocess
import sys
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
from src.config.excel_data import DEFAULT_WORKBOOK, load_case_reference


ROOT = Path(__file__).resolve().parent
_GROUP_CLEANUP_ERRORS: list[str] = []
_BETWEEN_GROUP_CLEANUP_SCRIPTS = (
    "scripts/cleanup_calculation_pending.py",
    "scripts/cleanup_calculation_temporary_bills.py",
    "scripts/cleanup_bill_center_room_gate.py",
)
_FINAL_CLEANUP_SCRIPTS = (
    *_BETWEEN_GROUP_CLEANUP_SCRIPTS,
    "scripts/cleanup_temporary_ledger_bills.py",
)


def _truthy_environment(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _entrypoint_group(item: pytest.Item) -> int:
    name = Path(str(item.fspath)).name
    if name in {
        "test_create_periodic_center_bills.py",
        "test_create_meter_bills.py",
    }:
        return 0  # Bill Center
    if name in {
        "test_calculate_periodic_bill.py",
        "test_calculate_temporary_bill.py",
    }:
        return 1  # Billing Issuance
    if name == "test_create_deposit_bill.py":
        if "in_calculation_then_bill_center_cleanup" in item.name:
            return 1
        return 2  # Temporary Ledger
    if name == "test_create_temporary_bill.py":
        return 2  # Temporary Ledger
    return 99


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Keep the legacy single-room Demo out of maintained batch runs."""
    if (
        collection_path.name == "test_create_periodic_bill.py"
        and not _truthy_environment("RUN_LEGACY_DEMO")
    ):
        return True
    return None


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
    parser.addoption(
        "--case-id",
        action="store",
        default=None,
        help="Excel 用例编号，例如 YSF-BILL-PERIODIC-001。",
    )
    parser.addoption(
        "--scenario-id",
        action="store",
        default=None,
        help="临时覆盖用例引用的收费场景编号。",
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
    case_id = config.getoption("--case-id") or os.getenv(
        "TEST_CASE_ID", "YSF-BILL-PERIODIC-001"
    )
    os.environ["TEST_CASE_ID"] = case_id
    workbook_path = Path(
        os.getenv("TEST_DATA_WORKBOOK", str(DEFAULT_WORKBOOK))
    )
    try:
        case_reference = load_case_reference(case_id, workbook_path)
    except (FileNotFoundError, ValueError) as exc:
        raise pytest.UsageError(str(exc)) from exc
    requested_scenario = config.getoption("--scenario-id")
    if requested_scenario:
        os.environ["SCENARIO_ID"] = requested_scenario.strip()
    else:
        os.environ["SCENARIO_ID"] = case_reference.scenario_id
    if not config.getoption("--account-role"):
        os.environ["TEST_ACCOUNT_ROLE"] = case_reference.account_role


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    original_order = {id(item): index for index, item in enumerate(items)}
    items.sort(
        key=lambda item: (_entrypoint_group(item), original_order[id(item)])
    )
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


def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> None:
    """Clean between entrypoint groups while keeping one pytest login session."""
    if nextitem is None:
        return
    current = _entrypoint_group(item)
    following = _entrypoint_group(nextitem)
    if current == 99 or following == 99 or current == following:
        return
    for script in _BETWEEN_GROUP_CLEANUP_SCRIPTS:
        result = subprocess.run([sys.executable, script], cwd=ROOT, env=os.environ.copy())
        if result.returncode:
            _GROUP_CLEANUP_ERRORS.append(f"{script} ({result.returncode})")
            print(f"[group-cleanup] failed: {script} ({result.returncode})")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if (
        not session.config.getoption("collectonly")
        and any(_entrypoint_group(item) != 99 for item in session.items)
        and _truthy_environment("CLEANUP_CREATED_BILL")
        and _truthy_environment("ALLOW_BILL_DELETION")
    ):
        for script in _FINAL_CLEANUP_SCRIPTS:
            result = subprocess.run(
                [sys.executable, script], cwd=ROOT, env=os.environ.copy()
            )
            if result.returncode:
                _GROUP_CLEANUP_ERRORS.append(f"{script} ({result.returncode})")
                print(f"[final-cleanup] failed: {script} ({result.returncode})")
    if _GROUP_CLEANUP_ERRORS and exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


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


@pytest.fixture(scope="session")
def fresh_login_page(
    browser: Browser,
    browser_context_args: dict[str, Any],
    request: pytest.FixtureRequest,
) -> Generator[Page, None, None]:
    """Batch-shared authenticated page for serial billing scenarios.

    Start from the saved account profile, then reuse the same context for the
    whole batch.  ``PortalPage.open_home`` still performs the normal local
    credential recovery if that profile has expired.  This avoids creating a
    second server-side login session merely because a test uses this fixture.
    """
    environment = normalize_test_environment(
        request.config.getoption("--test-env") or os.getenv("TEST_ENV")
    )
    customer_id = normalize_customer_id(
        request.config.getoption("--customer-id")
        or os.getenv("CUSTOMER_ID")
        or os.getenv("MASTER_CUSTOMER_ID")
    )
    role = normalize_account_role(
        request.config.getoption("--account-role")
        or os.getenv("TEST_ACCOUNT_ROLE")
        or "default"
    )
    context = _new_account_context(
        browser, browser_context_args, role, environment, customer_id
    )
    context.set_default_timeout(30_000)
    created_page = context.new_page()
    yield created_page
    context.close()
