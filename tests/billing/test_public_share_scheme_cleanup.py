from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page

from src.config.settings import settings
from src.pages.portal_page import PortalPage
from src.pages.public_share_scheme_page import PublicShareSchemePage


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


# These are the exact AT-prefixed records created during the current periodic
# public-sharing verification. No non-AT initialization scheme is ever eligible
# for cleanup.
CREATED_SCHEME_NAMES = (
    "AT-UI周期类-按房间设置比例分摊-1201-1202",
    "AT-UI周期类-按房间设置金额分摊-1203-1204",
    "AT-UI周期类-面积系数公摊-建筑面积-1205-1206",
    "AT-UI周期类-面积系数公摊-使用面积-1271-1272",
    "AT-UI周期类-面积系数公摊-收费面积-1273-1274",
)

pytestmark = pytest.mark.side_effect


@pytest.mark.parametrize("name", CREATED_SCHEME_NAMES, ids=CREATED_SCHEME_NAMES)
def test_cleanup_created_periodic_public_share_scheme(
    fresh_login_page: Page, name: str
) -> None:
    if not _enabled("CLEANUP_PUBLIC_SHARE_SCHEMES"):
        pytest.skip("未开启 CLEANUP_PUBLIC_SHARE_SCHEMES=true")
    if not _enabled("ALLOW_PUBLIC_SHARE_SCHEME_DELETION"):
        pytest.skip("未开启 ALLOW_PUBLIC_SHARE_SCHEME_DELETION=true")

    page = fresh_login_page.context.new_page()
    schemes = PublicShareSchemePage(page)
    try:
        portal = PortalPage(page)
        portal.open_home(
            settings.base_url,
            settings.master_customer_id,
            environment=settings.test_environment,
            account_role="default",
        )
        schemes.open(settings.project_name)
        schemes.delete_if_exists(name)
    finally:
        schemes.close_open_drawer()
        page.close()
