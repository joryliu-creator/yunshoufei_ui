from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page

from src.config.settings import settings
from src.pages.portal_page import PortalPage
from src.pages.public_share_scheme_page import (
    PublicShareSchemeCase,
    PublicShareSchemePage,
)


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


CASES = (
    PublicShareSchemeCase(
        case_id="YSF-PUBLIC-SHARE-PERIODIC-RATIO-1201-1202",
        name="AT-UI周期类-按房间设置比例分摊-1201-1202",
        method="按房间设置比例分摊",
        rooms=("1201", "1202"),
        allocations=("40", "60"),
    ),
    PublicShareSchemeCase(
        case_id="YSF-PUBLIC-SHARE-PERIODIC-AMOUNT-1203-1204",
        name="AT-UI周期类-按房间设置金额分摊-1203-1204",
        method="按房间设置金额分摊",
        rooms=("1203", "1204"),
        allocations=("300", "700"),
    ),
    PublicShareSchemeCase(
        case_id="YSF-PUBLIC-SHARE-PERIODIC-BUILDING-1205-1206",
        name="AT-UI周期类-面积系数公摊-建筑面积-1205-1206",
        method="按住户面积及所在楼层对应系数公摊",
        rooms=("1205", "1206"),
        billing_area="建筑面积",
    ),
    PublicShareSchemeCase(
        case_id="YSF-PUBLIC-SHARE-PERIODIC-USABLE-1271-1272",
        name="AT-UI周期类-面积系数公摊-使用面积-1271-1272",
        method="按住户面积及所在楼层对应系数公摊",
        rooms=("1271", "1272"),
        billing_area="使用面积",
    ),
    PublicShareSchemeCase(
        case_id="YSF-PUBLIC-SHARE-PERIODIC-CHARGE-1273-1274",
        name="AT-UI周期类-面积系数公摊-收费面积-1273-1274",
        method="按住户面积及所在楼层对应系数公摊",
        rooms=("1273", "1274"),
        billing_area="收费面积",
    ),
)

pytestmark = pytest.mark.side_effect


@pytest.mark.parametrize("case", CASES, ids=lambda item: item.case_id)
def test_create_periodic_public_share_scheme(
    fresh_login_page: Page, case: PublicShareSchemeCase
) -> None:
    if not _enabled("ALLOW_PUBLIC_SHARE_SCHEME_CREATION"):
        pytest.skip("未开启 ALLOW_PUBLIC_SHARE_SCHEME_CREATION=true")

    # Keep one authenticated browser context for the batch, but use a fresh
    # page per parameterized scenario.  This avoids reusing the previous
    # public-sharing iframe/component state without creating another login.
    page = fresh_login_page.context.new_page()
    portal = PortalPage(page)
    schemes = PublicShareSchemePage(page)
    try:
        portal.open_home(
            settings.base_url,
            settings.master_customer_id,
            environment=settings.test_environment,
            account_role="default",
        )
        schemes.open(settings.project_name)
        # 方案名称是唯一业务键；已有同名方案只做结构核验，不重复提交。
        if schemes.exists(case.name):
            schemes.assert_scheme(case)
            return

        schemes.create(case)
        schemes.assert_scheme(case)
    finally:
        # 即使异步下拉或表单校验失败，也关闭抽屉，避免污染后续参数化场景。
        schemes.close_open_drawer()
        page.close()
