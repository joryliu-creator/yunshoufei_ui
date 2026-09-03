from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page

from src.config.customer_data import load_customer_room_mapping
from src.config.settings import settings
from src.pages.customer_management_page import CustomerManagementPage
from src.pages.portal_page import PortalPage


pytestmark = pytest.mark.side_effect


def test_migrate_customer_room_1002(
    page: Page, record_property: pytest.RecordProperty, account_role: str
) -> None:
    mapping = load_customer_room_mapping("1002")
    portal = PortalPage(page)
    customer_page = CustomerManagementPage(page)
    portal.open_home(
        settings.base_url,
        settings.master_customer_id,
        environment=settings.test_environment,
        account_role=account_role,
    )
    customer_page.open()
    status = customer_page.migrate_room_for_customer(
        mapping.customer_name, mapping.room_path, mapping.project_name
    )
    assert status in {"migrated", "already_in"}
    record_property(
        "customer_room_migration",
        json.dumps(
            {
                "room": "1002",
                "customer": mapping.customer_name,
                "room_path": mapping.room_path,
                "status": status,
            },
            ensure_ascii=False,
        ),
    )
