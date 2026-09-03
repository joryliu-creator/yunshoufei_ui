"""Clean direct Temporary Ledger bills by business keys.

Direct Temporary Ledger creation is a separate storage path from Bill Center.
This recovery sweep reads the enabled ledger scenarios from the regression
workbook and searches Temporary Ledger by billing month + room + charge item;
bill numbers are never supplied as filters.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".tools" / "python"))

from openpyxl import load_workbook  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from src.config.excel_data import DEFAULT_WORKBOOK  # noqa: E402
from src.config.settings import settings  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402
from src.pages.temporary_ledger_page import TemporaryLedgerPage  # noqa: E402


def _targets() -> list[tuple[str, str, str]]:
    # SCENARIO_ID is the ordinary test-data selector and remains set to the
    # batch's default case during a full run. Reusing it here previously made
    # the recovery sweep select zero ledger targets. Only an explicit cleanup
    # override may narrow this script.
    selected_scenario = os.getenv("CLEANUP_SCENARIO_ID", "").strip()
    workbook = load_workbook(DEFAULT_WORKBOOK, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[1]  # 收费场景配置
        result: set[tuple[str, str, str]] = set()
        for row in range(2, sheet.max_row + 1):
            scenario_id = str(sheet.cell(row, 1).value or "").strip()
            environment = str(sheet.cell(row, 3).value or "").strip()
            customer_id = str(sheet.cell(row, 4).value or "").strip()
            charge_type = str(sheet.cell(row, 10).value or "").strip()
            if environment != settings.test_environment or customer_id != str(settings.master_customer_id):
                continue
            if "-LEDGER-" not in scenario_id or charge_type not in {"临时类", "押金类"}:
                continue
            if selected_scenario and scenario_id != selected_scenario:
                continue
            room = str(sheet.cell(row, 6).value or "").strip()
            item = str(sheet.cell(row, 11).value or "").strip()
            if room and item:
                result.add((settings.billing_month, room, item))
        return sorted(result)
    finally:
        workbook.close()


def main() -> int:
    if not settings.allow_bill_deletion:
        raise SystemExit("ALLOW_BILL_DELETION 未开启，禁止清理临时台账账单")
    targets = _targets()
    if not targets:
        print("temporary-ledger targets=0")
        return 0
    cleaned: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            portal = PortalPage(page)
            portal.open_home(
                settings.base_url,
                settings.master_customer_id,
                environment=settings.test_environment,
                account_role="default",
            )
            portal.open_temporary_ledger()
            ledger = TemporaryLedgerPage(page)
            ledger.wait_until_ready()
            for month, room, item in targets:
                cleaned.extend(
                    ledger.cleanup_by_month_room_charge_item(
                        billing_month=month,
                        room_path=room,
                        charge_item=item,
                        void_reason=settings.void_reason,
                    )
                )
            print(f"temporary-ledger targets={len(targets)} cleaned={len(set(cleaned))}")
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
