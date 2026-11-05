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
CASES = load_instrument_cases(regression=True)


@pytest.mark.parametrize("case", CASES, ids=lambda item: item.case_id)
def test_create_gas_and_ac_public_share_scheme(
    fresh_login_page: Page, case
) -> None:
    """Create exact AT gas/AC schemes; cleanup is a separately gated test."""
    if not _enabled("ALLOW_PUBLIC_SHARE_SCHEME_CREATION"):
        pytest.skip("未开启 ALLOW_PUBLIC_SHARE_SCHEME_CREATION=true")

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
        if schemes.exists(case.name):
            schemes.assert_scheme(case)
            return
        schemes.create(case)
        schemes.assert_scheme(case)
    finally:
        schemes.close_open_drawer()
        page.close()
