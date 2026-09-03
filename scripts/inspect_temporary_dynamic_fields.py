from __future__ import annotations

import json
import sys
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.create_charge_standards import restore_session  # noqa: E402
from src.config.accounts import get_account_auth_profile  # noqa: E402
from src.config.excel_data import load_excel_test_data  # noqa: E402
from src.config.settings import settings  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402
from src.pages.temporary_ledger_page import TemporaryBillData, TemporaryLedgerPage  # noqa: E402


SCENARIO_IDS = (
    "YSF-SCENE-TEMP-1012",
    "YSF-SCENE-TEMP-1015",
    "YSF-SCENE-TEMP-1017",
    "YSF-SCENE-TEMP-1020",
)


def visible_fields(dialog) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    for index in range(dialog.locator("input:visible, textarea:visible").count()):
        field = dialog.locator("input:visible, textarea:visible").nth(index)
        fields.append(
            {
                "tag": field.evaluate("(node) => node.tagName"),
                "placeholder": field.get_attribute("placeholder") or "",
                "value": field.input_value(),
                "readonly": field.get_attribute("readonly") or "",
                "disabled": field.get_attribute("disabled") or "",
                "outer_html": field.evaluate("(node) => node.outerHTML"),
                "container_text": field.locator(
                    "xpath=ancestor::*[self::tr or contains(@class, 'el-form-item')][1]"
                ).inner_text()
                if field.locator(
                    "xpath=ancestor::*[self::tr or contains(@class, 'el-form-item')][1]"
                ).count()
                else "",
            }
        )
    return fields


def decimal_parameter(parameters: str, name: str) -> Decimal | None:
    match = re.search(
        rf"(?:^|;){re.escape(name)}=([0-9]+(?:\.[0-9]+)?)(?:;|$)",
        parameters,
    )
    return Decimal(match.group(1)) if match else None


def temporary_bill_data(scenario) -> TemporaryBillData:
    parameters = scenario.calculation_parameters
    has_days = decimal_parameter(parameters, "BILLING_DAYS") is not None
    return TemporaryBillData(
        room_path=scenario.room_path,
        billing_month=scenario.suggested_billing_month,
        charge_item=scenario.charge_item,
        charge_standard=scenario.charge_standard,
        remark="自动化测试出临时账单",
        manual_amount=decimal_parameter(parameters, "MANUAL_AMOUNT"),
        meter_usage=decimal_parameter(parameters, "METER_USAGE"),
        quantity=decimal_parameter(parameters, "QUANTITY"),
        billing_period_start=date.today().isoformat() if has_days else None,
        billing_period_end=(date.today() + timedelta(days=1)).isoformat()
        if has_days
        else None,
    )


def main() -> None:
    profile = get_account_auth_profile(
        ROOT,
        "default",
        settings.test_environment,
        settings.master_customer_id,
    )
    if not profile.auth_file.exists() or not profile.session_file.exists():
        raise SystemExit("未找到当前环境、客户和账号的隔离登录状态。")

    result: dict[str, object] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(profile.auth_file))
        restore_session(context, profile, settings.base_url)
        page = context.new_page()
        try:
            portal = PortalPage(page)
            ledger = TemporaryLedgerPage(page)
            portal.open_home(
                settings.base_url,
                settings.master_customer_id,
                environment=settings.test_environment,
                account_role="default",
            )
            portal.open_temporary_ledger()
            ledger.wait_until_ready()
            for scenario_id in SCENARIO_IDS:
                scenario = load_excel_test_data(
                    settings.test_environment,
                    settings.master_customer_id,
                    scenario_id,
                ).scenario
                dialog = ledger.open_create_temporary_bill()
                ledger.fill_temporary_bill_before_submit(
                    dialog,
                    temporary_bill_data(scenario),
                )
                result[scenario_id] = visible_fields(dialog)
                dialog.get_by_role("button", name="关闭", exact=True).click()
        finally:
            context.close()
            browser.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
