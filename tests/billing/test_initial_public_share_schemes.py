from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page

from scripts.create_initial_public_share_schemes import CASES
from src.config.settings import settings
from src.pages.portal_page import PortalPage
from src.pages.public_share_scheme_page import PublicShareSchemePage


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


pytestmark = pytest.mark.side_effect


@pytest.mark.parametrize("case", CASES, ids=lambda item: item.case_id)
def test_initialize_periodic_public_share_scheme(
    fresh_login_page: Page, case
) -> None:
    """Create formal non-AT baseline schemes and intentionally retain them."""
    if not _enabled("ALLOW_INITIAL_PUBLIC_SHARE_SCHEMES"):
        pytest.skip("未开启 ALLOW_INITIAL_PUBLIC_SHARE_SCHEMES=true")

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
        else:
            schemes.create(case)
            schemes.assert_scheme(case)
    finally:
        # Formal initialization data is intentionally retained; this is not a
        # regression cleanup case and never calls delete/delete_if_exists.
        schemes.close_open_drawer()
        page.close()
