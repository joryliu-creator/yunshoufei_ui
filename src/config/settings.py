from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config.environments import load_test_environment


ROOT = Path(__file__).resolve().parents[2]
environment_profile = load_test_environment(ROOT)


def _as_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


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
    base_url: str
    master_customer_id: str
    project_name: str
    room_path: str
    charge_type: str
    charge_item: str
    billing_month: str
    receivable_date: str
    latest_payment_date: str
    allow_bill_creation: bool
    skip_bill_notification: bool
    cleanup_created_bill: bool
    allow_bill_deletion: bool
    void_reason: str

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
            "https://t.jslife.net/jportal/index.html",
        )
        customer_id = (
            os.getenv("CUSTOMER_ID", "").strip()
            or os.getenv("MASTER_CUSTOMER_ID", "").strip()
        )
        if not customer_id:
            customer_id = _environment_value(
                "CUSTOMER_ID", environment, "93537"
            )
        return cls(
            test_environment=environment,
            base_url=base_url.rstrip("/"),
            master_customer_id=customer_id,
            project_name=os.getenv("PROJECT_NAME", "云收费自动化MS1"),
            room_path=os.getenv(
                "ROOM_PATH", "云收费自动化MS/1/周期性收费房间001"
            ),
            charge_type=os.getenv("CHARGE_TYPE", "周期类"),
            charge_item=os.getenv("CHARGE_ITEM", "周期性收费项"),
            billing_month=os.getenv("BILLING_MONTH", "2026-07"),
            receivable_date=os.getenv("RECEIVABLE_DATE") or today,
            latest_payment_date=os.getenv("LATEST_PAYMENT_DATE") or today,
            allow_bill_creation=allow_bill_creation,
            skip_bill_notification=_as_bool("SKIP_BILL_NOTIFICATION", True),
            cleanup_created_bill=cleanup_created_bill,
            allow_bill_deletion=allow_bill_deletion,
            void_reason=os.getenv("VOID_REASON", "UI自动化Demo数据清理"),
        )


settings = Settings.from_env()
