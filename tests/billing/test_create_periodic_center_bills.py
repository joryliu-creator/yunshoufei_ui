from __future__ import annotations

import json
from decimal import Decimal

import pytest
from playwright.sync_api import Page

from scripts.update_room_import_template import formula_mappings
from src.config.excel_data import load_case_reference, load_excel_test_data
from src.config.settings import settings
from src.domain.periodic_charge import PeriodicRoomBasis, calculate_periodic_amount
from src.domain.public_share_charge import PUBLIC_SHARE_BY_ROOM
from src.pages.billing_center_page import BillData, BillingCenterPage
from src.pages.portal_page import PortalPage


# The workbook has one maintained Bill Center case for every periodic room.
# Room 1001 uses the formal matrix case YSF-BILL-PERIODIC-001; the legacy
# The obsolete YSF-BILL-001 Demo is not part of the maintained matrix.
PERIODIC_BILL_CASE_IDS = [
    "YSF-BILL-PERIODIC-001",
    *(f"YSF-BILL-PERIODIC-{room}" for room in range(1002, 1012)),
    *(f"YSF-BILL-PERIODIC-{room}" for room in range(1048, 1059)),
    *(
        f"YSF-BILL-PUBLIC-SHARE-PERIODIC-{case.room}"
        for case in PUBLIC_SHARE_BY_ROOM.values()
    ),
]

ROOM_MAPPINGS = {item.room_name: item for item in formula_mappings()}

pytestmark = [
    pytest.mark.side_effect,
    pytest.mark.skipif(
        not settings.allow_bill_creation,
        reason="Bill creation is disabled; set ALLOW_BILL_CREATION=true after confirming test data.",
    ),
]


def _parameters(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.replace(";", "\n").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _expected_amount(scenario) -> Decimal:
    """Recalculate the expected amount from the scenario's independent basis."""
    params = _parameters(scenario.calculation_parameters)
    room = scenario.room_path.rsplit("/", 1)[-1]
    if room in PUBLIC_SHARE_BY_ROOM:
        return PUBLIC_SHARE_BY_ROOM[room].expected_amount
    mapping = ROOM_MAPPINGS[room]
    basis = PeriodicRoomBasis(
        building_area=Decimal(params.get("BUILDING_AREA", "300.12")),
        usable_area=Decimal(params.get("USABLE_AREA", "280.01")),
        fee_area=Decimal(params.get("FEE_AREA", "260.00")),
        floor=int(params.get("FLOOR", "1")),
        months=Decimal(params.get("MONTHS", "1")),
    )
    return calculate_periodic_amount(
        scenario.formula,
        mapping.area_type,
        scenario.calculation_parameters,
        basis,
    )


@pytest.mark.parametrize("case_id", PERIODIC_BILL_CASE_IDS)
def test_create_periodic_bill_and_cleanup(
    fresh_login_page: Page,
    record_property: pytest.RecordProperty,
    account_role: str,
    case_id: str,
) -> None:
    page = fresh_login_page
    reference = load_case_reference(case_id)
    source = load_excel_test_data(
        settings.test_environment,
        settings.master_customer_id,
        reference.scenario_id,
    )
    scenario = source.scenario
    expected = _expected_amount(scenario)
    expected_from_sheet = Decimal(scenario.expected_receivable_amount)
    assert expected == expected_from_sheet, (
        f"{case_id}: 独立公式金额 {expected} 与 Excel 预期 {expected_from_sheet} 不一致"
    )

    data = BillData(
        project_name=scenario.project_name,
        room_path=scenario.room_path,
        charge_type=scenario.charge_type,
        charge_item=scenario.charge_item,
        billing_month=settings.billing_month,
        receivable_date=settings.receivable_date,
        latest_payment_date=settings.latest_payment_date,
    )
    portal = PortalPage(page)
    billing_center = BillingCenterPage(page)
    created_bill = None
    try:
        portal.open_home(
            settings.base_url,
            settings.master_customer_id,
            environment=settings.test_environment,
            account_role=account_role,
        )
        portal.open_billing_center()
        billing_center.wait_until_ready()
        billing_center.select_project(data.project_name)
        dialog = billing_center.open_create_bill()
        billing_center.fill_bill(dialog, data)
        created_bill = billing_center.submit_and_skip_notification(dialog, data)
        assert data.billing_month in created_bill.bill_row_text
        billing_center.assert_bill_amounts(
            created_bill,
            expected_original=expected,
            expected_discount=Decimal(scenario.expected_discount_amount),
            expected_receivable=expected,
        )
        record_property(
            "created_bill",
            json.dumps(
                {
                    "case_id": case_id,
                    "scenario_id": scenario.scenario_id,
                    "room": scenario.room_path,
                    "expected_amount": format(expected, "f"),
                    "bill_number": created_bill.bill_number,
                },
                ensure_ascii=False,
            ),
        )
    finally:
        if created_bill is not None and settings.cleanup_created_bill:
            if not settings.allow_bill_deletion:
                pytest.fail(
                    "Bill created but deletion is disabled; set ALLOW_BILL_DELETION=true."
                )
            billing_center.cleanup_by_month_room_charge_item(
                billing_month=data.billing_month,
                room_path=data.room_path,
                charge_item=data.charge_item,
                void_reason=settings.void_reason,
            )
