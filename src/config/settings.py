from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


load_dotenv()


def _as_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _today() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


@dataclass(frozen=True, slots=True)
class Settings:
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
        return cls(
            base_url=os.getenv(
                "BASE_URL", "https://t.jslife.net/jportal/index.html"
            ).rstrip("/"),
            master_customer_id=os.getenv("MASTER_CUSTOMER_ID", "93537"),
            project_name=os.getenv("PROJECT_NAME", "云收费自动化MS1"),
            room_path=os.getenv(
                "ROOM_PATH", "云收费自动化MS/1/周期性收费房间001"
            ),
            charge_type=os.getenv("CHARGE_TYPE", "周期类"),
            charge_item=os.getenv("CHARGE_ITEM", "周期性收费项"),
            billing_month=os.getenv("BILLING_MONTH", "2026-07"),
            receivable_date=os.getenv("RECEIVABLE_DATE") or today,
            latest_payment_date=os.getenv("LATEST_PAYMENT_DATE") or today,
            allow_bill_creation=_as_bool("ALLOW_BILL_CREATION"),
            skip_bill_notification=_as_bool("SKIP_BILL_NOTIFICATION", True),
            cleanup_created_bill=_as_bool("CLEANUP_CREATED_BILL"),
            allow_bill_deletion=_as_bool("ALLOW_BILL_DELETION"),
            void_reason=os.getenv("VOID_REASON", "UI自动化Demo数据清理"),
        )


settings = Settings.from_env()
