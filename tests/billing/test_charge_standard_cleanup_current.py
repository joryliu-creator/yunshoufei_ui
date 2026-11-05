from playwright.sync_api import Page

from scripts.create_charge_standards import to_data
from scripts.update_room_import_template import formula_mappings
from src.config.settings import settings
from src.pages.charge_standard_page import ChargeStandardPage
from src.pages.portal_page import PortalPage


def test_cleanup_current_charge_standard(page: Page, account_role: str) -> None:
    mapping = next(item for item in formula_mappings() if item.creation_policy == "创建")
    name = to_data(mapping, settings.project_name).name
    PortalPage(page).open_home(settings.base_url, settings.master_customer_id,
                               environment=settings.test_environment,
                               account_role=account_role)
    standards = ChargeStandardPage(page)
    standards.open(expected_customer_id=settings.master_customer_id)
    standards.delete_exact(name)
    assert not standards.exists(name)
