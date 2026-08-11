from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config.environments import load_test_environment
from src.config.excel_data import (
    DEFAULT_WORKBOOK,
    load_case_reference,
    load_excel_test_data,
)


ROOT = Path(__file__).resolve().parents[2]
environment_profile = load_test_environment(ROOT)


def _as_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _text_as_bool(value: str | None, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on", "是"}


def _today() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def _environment_value(
    name: str, environment: str, standard1_default: str
) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    if environment == "standard1":
        return standard1_default
    raise RuntimeError(
        f"环境 {environment!r} 尚未配置 {name}；请先创建并填写 "
        f".env.{environment}。"
    )


@dataclass(frozen=True, slots=True)
class Settings:
    test_environment: str
    case_id: str
    scenario_id: str
    base_url: str
    master_customer_id: str
    project_name: str
    room_path: str
    charge_type: str
    charge_item: str
    charge_standard: str
    billing_month: str
    receivable_date: str
    latest_payment_date: str
    allow_bill_creation: bool
    skip_bill_notification: bool
    cleanup_created_bill: bool
    allow_bill_deletion: bool
    void_reason: str
    calculation_parameters: str
    discount_config: str
    expected_original_amount: str
    expected_discount_amount: str
    expected_receivable_amount: str

    @classmethod
    def from_env(cls) -> "Settings":
        today = _today()
        environment = environment_profile.name
        allow_bill_creation = _as_bool("ALLOW_BILL_CREATION")
        cleanup_created_bill = _as_bool("CLEANUP_CREATED_BILL")
        allow_bill_deletion = _as_bool("ALLOW_BILL_DELETION")
        if environment == "prod" and any(
            (allow_bill_creation, cleanup_created_bill, allow_bill_deletion)
        ):
            raise RuntimeError(
                "生产环境禁止开启创建账单、自动清理或永久删除开关。"
            )
        base_url = _environment_value(
            "BASE_URL",
            environment,
            "http://t.jslife.net/jportal/index.html",
        )
        customer_id = (
            os.getenv("CUSTOMER_ID", "").strip()
            or os.getenv("MASTER_CUSTOMER_ID", "").strip()
        )
        if not customer_id:
            customer_id = _environment_value(
                "CUSTOMER_ID", environment, "93537"
            )
        workbook_path = Path(
            os.getenv("TEST_DATA_WORKBOOK", str(DEFAULT_WORKBOOK))
        )
        case_id = os.getenv("TEST_CASE_ID", "YSF-BILL-001").strip()
        case_reference = load_case_reference(case_id, workbook_path)
        scenario_id = (
            os.getenv("SCENARIO_ID", "").strip()
            or case_reference.scenario_id
        )
        excel_data = load_excel_test_data(
            environment,
            customer_id,
            scenario_id,
            workbook_path,
        )
        runtime = excel_data.runtime_parameters

        def runtime_value(name: str, default: str = "") -> str:
            value = runtime.get(name, "").strip()
            return value or default

        def runtime_date(name: str) -> str:
            value = runtime_value(name, "执行当天")
            return today if value in {"执行当天", "当天"} else value

        billing_month = runtime_value(
            "BILLING_MONTH", excel_data.scenario.suggested_billing_month
        )
        if not billing_month:
            raise RuntimeError(
                f"场景 {scenario_id!r} 和运行参数均未配置 BILLING_MONTH。"
            )
        return cls(
            test_environment=environment,
            case_id=case_id,
            scenario_id=scenario_id,
            base_url=base_url.rstrip("/"),
            master_customer_id=customer_id,
            project_name=excel_data.scenario.project_name,
            room_path=excel_data.scenario.room_path,
            charge_type=excel_data.scenario.charge_type,
            charge_item=excel_data.scenario.charge_item,
            charge_standard=excel_data.scenario.charge_standard,
            billing_month=billing_month,
            receivable_date=runtime_date("RECEIVABLE_DATE"),
            latest_payment_date=runtime_date("LATEST_PAYMENT_DATE"),
            allow_bill_creation=allow_bill_creation,
            skip_bill_notification=_text_as_bool(
                runtime.get("SKIP_BILL_NOTIFICATION"), True
            ),
            cleanup_created_bill=cleanup_created_bill,
            allow_bill_deletion=allow_bill_deletion,
            void_reason=runtime_value(
                "VOID_REASON", "UI自动化Demo数据清理"
            ),
            calculation_parameters=(
                excel_data.scenario.calculation_parameters
            ),
            discount_config=excel_data.scenario.discount_config,
            expected_original_amount=(
                excel_data.scenario.expected_original_amount
            ),
            expected_discount_amount=(
                excel_data.scenario.expected_discount_amount
            ),
            expected_receivable_amount=(
                excel_data.scenario.expected_receivable_amount
            ),
        )


settings = Settings.from_env()
