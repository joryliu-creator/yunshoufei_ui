from __future__ import annotations

from decimal import Decimal
import json
import re
import os
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from scripts.update_room_import_template import formula_mappings
from src.config.excel_data import load_case_reference, load_excel_test_data
from src.config.settings import settings
from src.domain.bill_presence import BillKey, ensure_no_active_bill
from src.domain.periodic_charge import PeriodicRoomBasis, calculate_periodic_amount
from src.pages.billing_center_page import BillData, BillingCenterPage
from src.pages.portal_page import PortalPage
from src.pages.workbench_billing_page import WorkbenchBillingPage


CASE_ID = "YSF-WORKBENCH-BILL-1001"
ROOM_PATH = "A栋/1层/1001"
BILLING_MONTH = "2026-08"
RECEIVABLE_DATE = "2026-08-31"
LATEST_PAYMENT_DATE = "2026-08-31"
ROOM_MAPPINGS = {item.room_name: item for item in formula_mappings()}

pytestmark = [
    pytest.mark.side_effect,
    pytest.mark.skipif(
        not settings.allow_bill_creation,
        reason="默认禁止创建账单；确认测试数据后设置 ALLOW_BILL_CREATION=true。",
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
    parameters = _parameters(scenario.calculation_parameters)
    room_number = scenario.room_path.rstrip("/").split("/")[-1]
    mapping = ROOM_MAPPINGS[room_number]
    basis = PeriodicRoomBasis(
        building_area=Decimal(parameters.get("BUILDING_AREA", "300.12")),
        usable_area=Decimal(parameters.get("USABLE_AREA", "280.01")),
        fee_area=Decimal(parameters.get("FEE_AREA", "260.00")),
        floor=int(parameters.get("FLOOR", "1")),
        months=Decimal(parameters.get("MONTHS", "1")),
    )
    return calculate_periodic_amount(
        scenario.formula,
        mapping.area_type,
        scenario.calculation_parameters,
        basis,
    )


def test_create_bill_from_workbench_room_profile(
    fresh_login_page: Page,
    account_role: str,
    record_property: pytest.RecordProperty,
) -> None:
    """Use the workbench room profile to create, verify, and clean one bill."""
    if settings.test_environment != "standard1" or settings.master_customer_id != "93537":
        pytest.fail(
            "工作台新增账单专项仅允许使用 Standard1 / 客户 93537；"
            "尚未验证的账号和客户上下文禁止写入。"
        )
    if account_role != "default":
        pytest.fail(
            f"工作台新增账单专项要求 default 登录配置，当前账号别名={account_role!r}。"
        )
    if not settings.cleanup_created_bill or not settings.allow_bill_deletion:
        pytest.fail(
            "本场景要求创建后立即清理；请同时确认 CLEANUP_CREATED_BILL=true "
            "和 ALLOW_BILL_DELETION=true，再运行。"
        )

    reference = load_case_reference(CASE_ID)
    scenario = load_excel_test_data(
        settings.test_environment,
        settings.master_customer_id,
        reference.scenario_id,
    ).scenario
    if (
        scenario.room_path != ROOM_PATH
        or scenario.charge_type != "周期类"
        or scenario.charge_item != "UI周期性收费项"
    ):
        pytest.fail(
            "1001 场景配置与工作台专项要求不一致；"
            f"room={scenario.room_path!r}, type={scenario.charge_type!r}, "
            f"item={scenario.charge_item!r}。"
        )

    expected_original = _expected_amount(scenario)
    expected_discount = Decimal(scenario.expected_discount_amount)
    expected_receivable = Decimal(scenario.expected_receivable_amount)
    if expected_original - expected_discount != expected_receivable:
        pytest.fail(
            "1001 周期收费场景的独立计算金额与 Excel 应收基线不一致；"
            f"独立金额={expected_original}，减免={expected_discount}，"
            f"Excel应收={expected_receivable}。"
        )
    data = BillData(
        project_name=scenario.project_name,
        room_path=ROOM_PATH,
        charge_type=scenario.charge_type,
        charge_item=scenario.charge_item,
        billing_month=BILLING_MONTH,
        receivable_date=RECEIVABLE_DATE,
        latest_payment_date=LATEST_PAYMENT_DATE,
    )

    page = fresh_login_page
    portal = PortalPage(page)
    center = BillingCenterPage(page)
    workbench = WorkbenchBillingPage(page)
    submission_attempted = False
    created_number: str | None = None

    portal.open_home(
        settings.base_url,
        settings.master_customer_id,
        environment=settings.test_environment,
        account_role=account_role,
    )
    portal.open_billing_center()
    center.wait_until_ready()
    center.select_project(data.project_name)

    def query_target(*, include_voided: bool = False, allow_empty: bool = False) -> list[str]:
        try:
            return center.get_bill_numbers_by_month_room_charge_item(
                billing_month=data.billing_month,
                room_path=data.room_path,
                charge_item=data.charge_item,
                include_voided=include_voided,
                allow_empty=allow_empty,
            )
        except Exception as exc:
            artifact_dir = Path("artifacts")
            artifact_dir.mkdir(exist_ok=True)
            screenshot = artifact_dir / "workbench-bill-precheck-failure.png"
            try:
                page.screenshot(path=str(screenshot), full_page=True, timeout=15_000)
            except Exception:
                screenshot = Path()
            record_property(
                "workbench_precheck_error",
                f"{type(exc).__name__}: {exc}; screenshot={screenshot.as_posix()}",
            )
            print(f"[workbench-precheck] {type(exc).__name__}: {exc}", flush=True)
            raise

    def reopen_center() -> None:
        portal.open_billing_center()
        center.wait_until_ready()
        center.select_project(data.project_name)

    ensure_no_active_bill(
        case_id="YSF-WORKBENCH-BILL-1001",
        entrypoint="工作台房间档案",
        key=BillKey(BILLING_MONTH, ROOM_PATH, data.charge_item),
        record_property=record_property,
        query=lambda: query_target(allow_empty=True),
        reset=reopen_center,
    )
    if os.getenv("WORKBENCH_PREFLIGHT_ONLY", "").strip().lower() in {
        "1", "true", "yes", "on"
    }:
        pytest.skip("工作台新增账单只读预检模式；未进入创建步骤。")

    try:
        workbench.open()
        workbench.search_room(ROOM_PATH)
        detail = workbench.open_room_profile(ROOM_PATH)
        workbench.wait_for_charge_profile(
            room_path=ROOM_PATH,
            charge_item=data.charge_item,
            charge_standard=scenario.charge_standard,
        )
        dialog = workbench.open_create_bill()

        # Reuse the verified Bill Center form interactions: only the entry
        # point differs; month, charge-item, and latest-payment-date controls
        # are the same Element UI widgets in this portal build.
        center.frame = detail
        receivable_dates = dialog.get_by_placeholder("选择日期")
        expect(receivable_dates).to_have_count(1, timeout=10_000)
        receivable_dates.first.fill(RECEIVABLE_DATE)
        receivable_dates.first.press("Enter")
        page.keyboard.press("Escape")
        expect(receivable_dates.first).to_have_value(RECEIVABLE_DATE)

        month_input = dialog.get_by_placeholder("选择年月")
        expect(month_input).to_have_count(1, timeout=10_000)
        center._select_billing_month(month_input, BILLING_MONTH)
        center._add_charge_item(dialog, data.charge_item)
        center._edit_charge_detail(
            dialog,
            charge_item=data.charge_item,
            latest_payment_date=LATEST_PAYMENT_DATE,
        )

        # Mark the write attempt before clicking. If the server commits but
        # the browser loses its response, finally still performs a guarded
        # business-key cleanup rather than leaving an untracked bill behind.
        submission_attempted = True
        success_message = workbench.submit_and_wait_for_success(dialog)
        record_property("workbench_create_feedback", success_message)

        portal.open_billing_center()
        center.wait_until_ready()
        center.select_project(data.project_name)
        numbers = query_target()
        if len(numbers) != 1:
            raise AssertionError(
                "工作台新增后按账期+房间+收费项应唯一命中；"
                f"实际匹配数={len(numbers)}。"
            )
        created_number = numbers[0]
        rows = center._find_main_table_row(
            room_path=ROOM_PATH, charge_item=data.charge_item
        )
        matching_rows = [
            rows.nth(index)
            for index in range(rows.count())
            if rows.nth(index).is_visible()
            and BILLING_MONTH in rows.nth(index).inner_text()
            and "已作废" not in rows.nth(index).inner_text()
        ]
        if len(matching_rows) != 1:
            raise AssertionError(
                "账单中心校验时业务键应唯一匹配一行；"
                f"可见匹配数={len(matching_rows)}。"
            )
        row = matching_rows[0]
        expect(row).to_contain_text(RECEIVABLE_DATE)
        expect(row).to_contain_text(data.charge_item)
        center.assert_row_amounts(
            row,
            expected_original=expected_original,
            expected_discount=expected_discount,
            expected_receivable=expected_receivable,
        )
        record_property(
            "workbench_created_bill",
            json.dumps(
                {
                    "entrypoint": "业务办理收费台-房间档案",
                    "customer_id": settings.master_customer_id,
                    "room": ROOM_PATH,
                    "billing_month": BILLING_MONTH,
                    "charge_item": data.charge_item,
                    "receivable_date": RECEIVABLE_DATE,
                    "latest_payment_date": LATEST_PAYMENT_DATE,
                    "bill_number": created_number,
                    "expected_original": str(expected_original),
                    "expected_receivable": str(expected_receivable),
                },
                ensure_ascii=False,
            ),
        )
    finally:
        if submission_attempted:
            # Bill Center bills must be voided then batch-deleted. Never
            # delete ambiguous business-key matches; preserve them for review.
            reopen_center()
            all_matches = query_target(include_voided=True, allow_empty=True)
            if len(all_matches) > 1:
                raise AssertionError(
                    "工作台创建后的清理业务键命中多条账单，已停止删除以保护数据；"
                    f"匹配数={len(all_matches)}。"
                )
            if all_matches:
                center.cleanup_by_month_room_charge_item(
                    billing_month=data.billing_month,
                    room_path=data.room_path,
                    charge_item=data.charge_item,
                    void_reason=settings.void_reason,
                )
            remaining = query_target(include_voided=True, allow_empty=True)
            if remaining:
                raise AssertionError(
                    "工作台新增账单清理后仍有同业务键账单："
                    f"{remaining!r}。"
                )
            record_property("workbench_cleanup", "已按账期+房间+收费项作废并批量删除，复查为 0 条")
