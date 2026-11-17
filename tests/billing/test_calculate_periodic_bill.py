from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import Page, expect

from scripts.add_bill_demo_to_excel import CALCULATION_CASES
from src.config.excel_data import load_case_reference, load_excel_test_data
from src.config.settings import settings
from src.domain.bill_presence import BillKey, ensure_no_active_bill, skip_existing_active_bill
from src.pages.billing_calculation_page import BillingCalculationPage, CalculationData
from src.pages.billing_center_page import BillingCenterPage
from src.pages.portal_page import PortalPage


CALCULATION_CASE_IDS = [case[0] for case in CALCULATION_CASES]

pytestmark = [
    pytest.mark.scenario("YSF-SCENE-CALCULATION-BILLING"),
    pytest.mark.side_effect,
    pytest.mark.skipif(
        not settings.allow_bill_creation,
        reason="默认禁止创建账单；确认测试数据后设置 ALLOW_BILL_CREATION=true。",
    ),
]


def _current_month() -> str:
    return "2026-08"


def _calculation_data(case_id: str) -> tuple[CalculationData, Decimal, str]:
    reference = load_case_reference(case_id)
    source = load_excel_test_data(
        settings.test_environment,
        settings.master_customer_id,
        reference.scenario_id,
    )
    runtime = source.runtime_parameters
    # Allow the run command to override stale workbook dates.  The current
    # meter regression is explicitly executed for 2026-08.
    billing_month = (
        os.getenv("CALCULATION_BILLING_MONTH", "").strip()
        or runtime["CALCULATION_BILLING_MONTH"]
    )
    if billing_month in {"执行当月", "执行當月"}:
        billing_month = _current_month()
    day = runtime["CALCULATION_RULE_DAY"]
    return (
        CalculationData(
            project_name=source.scenario.project_name,
            room_name=source.scenario.room_path.rsplit("/", 1)[-1],
            charge_item=source.scenario.charge_item,
            charge_type=source.scenario.charge_type,
            billing_month=billing_month,
            receivable_day=day,
            latest_payment_day=day,
            audit_comment=runtime["CALCULATION_AUDIT_COMMENT"],
        ),
        Decimal(source.scenario.expected_receivable_amount),
        reference.scenario_id,
    )


@pytest.mark.parametrize("case_id", CALCULATION_CASE_IDS)
def test_calculate_periodic_bill_then_approve_and_cleanup(
    fresh_login_page: Page,
    record_property: pytest.RecordProperty,
    account_role: str,
    case_id: str,
) -> None:
    data, expected_amount, scenario_id = _calculation_data(case_id)
    room_path = load_excel_test_data(
        settings.test_environment,
        settings.master_customer_id,
        scenario_id,
    ).scenario.room_path
    portal = PortalPage(fresh_login_page)
    calculation = BillingCalculationPage(fresh_login_page)
    billing_center = BillingCenterPage(fresh_login_page)
    created_bill_number: str | None = None
    calculation_started = False
    test_error: BaseException | None = None

    try:
        portal.open_home(
            settings.base_url,
            settings.master_customer_id,
            environment=settings.test_environment,
            account_role=account_role,
        )
        # 运行前按账期+房间+收费项只读预检：已有有效账单则保留原数据并跳过，
        # 避免对同一业务键重复计费出账；预检查询本身失败时也跳过（失败安全）。
        portal.open_billing_center()
        billing_center.wait_until_ready()

        def _query_bills() -> list[str]:
            billing_center.select_project(data.project_name)
            return billing_center.get_bill_numbers_by_month_room_charge_item(
                billing_month=data.billing_month,
                room_path=room_path,
                charge_item=data.charge_item,
                allow_empty=True,
            )

        def _reopen_billing_center() -> None:
            portal.open_billing_center()
            billing_center.wait_until_ready()

        ensure_no_active_bill(
            case_id=case_id,
            entrypoint="计费出账",
            key=BillKey(
                billing_month=data.billing_month,
                room_path=room_path,
                charge_item=data.charge_item,
            ),
            record_property=record_property,
            query=_query_bills,
            reset=_reopen_billing_center,
        )
        portal.open_billing_calculation()
        calculation.wait_until_ready()
        calculation.assert_no_pending_bill(data.billing_month)
        condition_drawer = calculation.open_regular_calculation()
        calculation.configure_regular_calculation(condition_drawer, data)
        rule_drawer = calculation.open_rule_details(condition_drawer)
        calculation.configure_rule_dates(rule_drawer, data)
        # The backend can accept the calculation even if the UI times out
        # waiting for its response. Arm cleanup immediately before submission.
        calculation_started = True
        calculation.start_calculation(rule_drawer)
        calculation.assert_pending_amount(
            data.billing_month,
            format(expected_amount, "f"),
            charge_item=data.charge_item,
            room_name=data.room_name,
        )
        calculation.reconcile_and_approve(data, format(expected_amount, "f"))

        # 审核通过后直接进入账单中心，按账期 + 房间筛选本次唯一账单。
        portal.open_billing_center()
        billing_center.wait_until_ready()
        resolved_numbers = billing_center.get_bill_numbers_by_month_room_charge_item(
            billing_month=data.billing_month,
            room_path=room_path,
            charge_item=data.charge_item,
        )
        if len(resolved_numbers) != 1:
            raise AssertionError(
                f"计费出账后按账期+房间+收费项应唯一匹配账单，实际 {len(resolved_numbers)} 条"
            )
        created_bill_number = resolved_numbers[0]
        row = billing_center._find_main_table_row(bill_number=created_bill_number)
        expect(row).to_contain_text(data.charge_item)
        expect(row).to_contain_text(format(expected_amount, "f"))
        record_property(
            "created_bill",
            json.dumps(
                {
                    "case_id": case_id,
                    "scenario_id": scenario_id,
                    "bill_number": created_bill_number,
                    "room": room_path,
                    "billing_month": data.billing_month,
                    "expected_amount": format(expected_amount, "f"),
                    "audit_comment": data.audit_comment,
                },
                ensure_ascii=False,
            ),
        )
    except BaseException as exc:
        test_error = exc
        raise
    finally:
        # 失败时清理计费出账页待处理卡片；已出账账单在账单中心按业务键清理。
        if (
            calculation_started
            and settings.allow_bill_deletion
            and settings.test_environment != "prod"
        ):
            try:
                record_property(
                    "pending_cleanup",
                    json.dumps(
                        calculation.cleanup_pending_records(),
                        ensure_ascii=False,
                    ),
                )
            except Exception as cleanup_error:
                artifact_dir = Path("artifacts")
                artifact_dir.mkdir(exist_ok=True)
                cleanup_artifact = artifact_dir / (
                    f"calculation-pending-cleanup-error-{case_id}.txt"
                )
                cleanup_artifact.write_text(
                    repr(cleanup_error), encoding="utf-8"
                )
                if test_error is None:
                    raise AssertionError(
                        "计费出账用例本身通过，但待处理卡片清理失败；"
                        f"已保存 {cleanup_artifact.as_posix()}。"
                    ) from cleanup_error
        if created_bill_number is not None and settings.cleanup_created_bill:
            if not settings.allow_bill_deletion:
                pytest.fail(
                    "已创建计费出账账单但禁止删除；如需自动清理，请同时设置 "
                    "ALLOW_BILL_DELETION=true。"
                )
            billing_center.cleanup_by_month_room_charge_item(
                billing_month=data.billing_month,
                room_path=room_path,
                charge_item=data.charge_item,
                void_reason=settings.void_reason,
            )
