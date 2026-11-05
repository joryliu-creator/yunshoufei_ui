from __future__ import annotations

import os
from dataclasses import dataclass

import pytest
from playwright.sync_api import Page

from src.config.settings import settings
from src.pages.discount_scheme_page import DiscountSchemePage
from src.pages.portal_page import PortalPage


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class DiscountCase:
    room: str
    rule: str
    value: str | None = None

    @property
    def name(self) -> str:
        # 页面方案名称长度有限；短前缀仍保留规则标识。
        prefix = os.getenv("DISCOUNT_SCHEME_PREFIX", "AT")
        if _bool("DISCOUNT_SCHEME_INCLUDE_ROOM", True):
            return f"{prefix}-{self.rule}-{self.room}"
        return f"{prefix}-{self.rule}"


CASES = (
    DiscountCase("1101", "按折扣", "5"),
    DiscountCase("1102", "按固定金额", "5"),
    DiscountCase("1103", "自定义金额"),
    DiscountCase("1104", "违约金全免"),
    DiscountCase("1105", "违约金折扣", "5"),
    DiscountCase("1106", "抹零减免"),
)

pytestmark = pytest.mark.side_effect


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.rule}-{c.room}")
def test_create_discount_scheme_and_cleanup(page: Page, case: DiscountCase) -> None:
    if not _bool("ALLOW_DISCOUNT_SCHEME_CREATION"):
        pytest.skip("未开启 ALLOW_DISCOUNT_SCHEME_CREATION=true")
    portal = PortalPage(page)
    schemes = DiscountSchemePage(page)
    portal.open_home(
        settings.base_url,
        settings.master_customer_id,
        environment=settings.test_environment,
        account_role="default",
    )
    schemes.open(settings.project_name)
    created = False
    try:
        # 处理上次中断可能遗留的同名方案，保证重复运行幂等。
        if _bool("ALLOW_DISCOUNT_SCHEME_DELETION"):
            schemes.delete_if_exists(case.name)
        schemes.create(name=case.name, rule=case.rule, value=case.value)
        created = True
    finally:
        if created and _bool("CLEANUP_DISCOUNT_SCHEMES"):
            if not _bool("ALLOW_DISCOUNT_SCHEME_DELETION"):
                pytest.fail("减免方案已创建但未开启 ALLOW_DISCOUNT_SCHEME_DELETION=true")
            schemes.delete(case.name)
