from __future__ import annotations

import json
import os

import pytest
from playwright.sync_api import Page

from scripts.create_charge_standards import to_data
from scripts.update_room_import_template import formula_mappings
from src.config.settings import settings
from src.config.standard_name import AUTOMATION_STANDARD_PREFIX
from src.pages.charge_standard_page import ChargeStandardPage
from src.pages.portal_page import PortalPage


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


pytestmark = pytest.mark.side_effect


def _selected_mappings():
    # 抽成类收费标准暂不纳入专项回归；其业务前置和接口刷新规则与
    # 周期/仪表/临时/押金类不同，待单独录制流程后再启用。
    mappings = [
        item
        for item in formula_mappings()
        if item.creation_policy == "创建" and item.charge_type != "抽成类"
    ]
    case_limit = os.getenv("CHARGE_STANDARD_CASE_LIMIT", "").strip()
    offset = int(os.getenv("CHARGE_STANDARD_CASE_OFFSET", "0") or "0")
    if offset < 0:
        raise ValueError("CHARGE_STANDARD_CASE_OFFSET 必须大于等于 0")
    if case_limit:
        limit = int(case_limit)
        if limit < 1:
            raise ValueError("CHARGE_STANDARD_CASE_LIMIT 必须大于等于 1")
        return mappings[offset : offset + limit]
    return mappings[offset:]


def _mapping_id(mapping) -> str:
    return f"room-{mapping.room_name}"


@pytest.mark.parametrize(
    "mapping", _selected_mappings(), ids=_mapping_id
)
def test_charge_standard_create_verify_and_cleanup(
    fresh_login_page: Page,
    record_property: pytest.RecordProperty,
    account_role: str,
    mapping,
) -> None:
    if not _enabled("ALLOW_CHARGE_STANDARD_CREATION"):
        pytest.skip(
            "收费标准真实创建默认关闭；设置 ALLOW_CHARGE_STANDARD_CREATION=true 后执行。"
        )
    assert mapping.creation_policy == "创建"
    page = fresh_login_page
    portal = PortalPage(page)
    portal.open_home(
        settings.base_url,
        settings.master_customer_id,
        environment=settings.test_environment,
        account_role=account_role,
    )
    standards = ChargeStandardPage(page)
    # A failed parameter can leave the shared session with an open dialog;
    # clear only that transient UI state before opening the next case.
    standards.cancel_open_create_dialog()
    standards.open(expected_customer_id=settings.master_customer_id)
    created: list[str] = []
    results: list[dict[str, str]] = []
    try:
        data = to_data(mapping, settings.project_name)
        assert data.name.startswith(AUTOMATION_STANDARD_PREFIX)
        if standards.exists(data.name):
            results.append({"room": mapping.room_name, "name": data.name, "status": "exists"})
        else:
            standards.create(data)
            # Register immediately after submit so a post-save verification
            # failure still triggers the exact-name cleanup path.
            created.append(data.name)
            if not standards.exists(data.name):
                raise AssertionError(f"保存后未精确查询到收费标准：{data.name}")
            results.append({"room": mapping.room_name, "name": data.name, "status": "created"})
    finally:
        if created and _enabled("CLEANUP_CREATED_CHARGE_STANDARDS"):
            if not _enabled("ALLOW_CHARGE_STANDARD_DELETION"):
                pytest.fail(
                    "专项创建了收费标准但未开启 ALLOW_CHARGE_STANDARD_DELETION=true，禁止宣称清理完成。"
                )
            for name in reversed(created):
                standards.delete_exact(name)
                if standards.exists(name):
                    raise AssertionError(f"收费标准删除后仍可查询：{name}")
    record_property("charge_standard_lifecycle", json.dumps(results, ensure_ascii=False))
