from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page

from src.config.instrument_public_share_data import load_instrument_cases
from src.config.settings import settings
from src.pages.portal_page import PortalPage
from src.pages.public_share_scheme_page import PublicShareSchemePage


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


pytestmark = pytest.mark.side_effect
AT_SCHEME_NAMES = tuple(
    case.name for case in load_instrument_cases(regression=True)
)


@pytest.mark.parametrize("name", AT_SCHEME_NAMES, ids=AT_SCHEME_NAMES)
def test_cleanup_exact_at_gas_and_ac_public_share_scheme(
    fresh_login_page: Page, name: str
) -> None:
    if not _enabled("CLEANUP_PUBLIC_SHARE_SCHEMES"):
        pytest.skip("未开启 CLEANUP_PUBLIC_SHARE_SCHEMES=true")
    if not _enabled("ALLOW_PUBLIC_SHARE_SCHEME_DELETION"):
        pytest.skip("未开启 ALLOW_PUBLIC_SHARE_SCHEME_DELETION=true")

    page = fresh_login_page.context.new_page()
    schemes = PublicShareSchemePage(page)
    try:
        PortalPage(page).open_home(
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
