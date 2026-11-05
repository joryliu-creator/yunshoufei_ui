"""Safely clear this instrument-public-share run from Bill Center.

Targets are resolved by billing month + room + charge item.  A captured bill
number is only accepted as provenance evidence for the exact current-run row;
unknown or ambiguous rows abort the cleanup before any destructive action.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.settings import settings  # noqa: E402
from src.pages.billing_center_page import BillingCenterPage  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402

MONTH = "2026-08"
RESULTS = ROOT / "artifacts" / "instrument-public-share-bill-center.jsonl"
ROOMS = {
    **{str(room): "UI公摊水费" for room in range(1207, 1223)},
    **{str(room): "UI公摊电费" for room in range(1223, 1239)},
}


def _current_run_numbers() -> dict[tuple[str, str, str], set[str]]:
    if not RESULTS.exists():
        raise SystemExit(f"缺少本轮账单证据文件：{RESULTS}")
    known: dict[tuple[str, str, str], set[str]] = {}
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("phase") != "billing_center" or row.get("billing_month") != MONTH:
            continue
        if row.get("instrument_type") not in {"水表", "电表"}:
            continue
        number = str(row.get("bill_number") or "").strip()
        room_path = str(row.get("room") or "").strip()
        item = str(row.get("charge_item") or "").strip()
        if not number or not room_path or not item:
            continue
        key = (MONTH, room_path, item)
        known.setdefault(key, set()).add(number)
    return known


def main() -> None:
    if settings.test_environment == "prod":
        raise SystemExit("生产环境禁止执行账单清理。")
    if not settings.cleanup_created_bill or not settings.allow_bill_deletion:
        raise SystemExit(
            "CLEANUP_CREATED_BILL 与 ALLOW_BILL_DELETION 必须同时开启。"
        )
    if settings.test_environment != "standard1" or settings.master_customer_id != "93537":
        raise SystemExit("环境/客户与本轮账单证据不一致，停止清理。")

    known = _current_run_numbers()
    keys = [
        (MONTH, f"A栋/1层/{room}", item)
        for room, item in ROOMS.items()
    ]
    active: list[tuple[str, str, str, str]] = []
    blockers: list[tuple[tuple[str, str, str], list[str], list[str]]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        try:
            portal = PortalPage(page)
            portal.open_home(
                settings.base_url,
                settings.master_customer_id,
                environment=settings.test_environment,
                account_role="default",
            )
            portal.open_billing_center()
            billing = BillingCenterPage(page)
            billing.wait_until_ready()
            billing.select_project(settings.project_name)

            # Preflight every room key. Unknown and duplicate rows block the
            # whole batch so no partial cleanup can hide an ambiguity.
            for key in keys:
                month, room_path, item = key
                matches = billing.get_bill_numbers_by_month_room_charge_item(
                    billing_month=month,
                    room_path=room_path,
                    charge_item=item,
                    allow_empty=True,
                )
                expected = known.get(key, set())
                if not matches:
                    continue
                if len(matches) != 1 or set(matches) != expected:
                    blockers.append((key, matches, sorted(expected)))
                    continue
                active.append((month, room_path, item, matches[0]))

            if blockers:
                details = "\n".join(
                    f"{key}: active={matches}, run_evidence={expected}"
                    for key, matches, expected in blockers
                )
                raise SystemExit(
                    "发现非本轮或多条匹配账单；未执行任何删除，请先核实：\n"
                    + details
                )

            cleaned: list[tuple[str, str, str]] = []
            for month, room_path, item, number in active:
                row = billing._find_main_table_row(
                    room_path=room_path,
                    charge_item=item,
                    bill_number=number,
                )
                if row.count() != 1:
                    raise AssertionError(
                        f"业务键已命中，但完整账单行无法唯一确认：{room_path}, {item}"
                    )
                billing.cleanup_bill(number, settings.void_reason, month)
                remaining = billing.get_bill_numbers_by_month_room_charge_item(
                    billing_month=month,
                    room_path=room_path,
                    charge_item=item,
                    allow_empty=True,
                )
                if remaining:
                    raise AssertionError(
                        f"清理后仍有活动账单：{room_path}, {item}, {remaining}"
                    )
                cleaned.append((room_path, item, number))

            # Final gate: every public-share room must have no active August
            # water/electric bill before Calculation Billing starts.
            residuals = []
            for month, room_path, item in keys:
                remaining = billing.get_bill_numbers_by_month_room_charge_item(
                    billing_month=month,
                    room_path=room_path,
                    charge_item=item,
                    allow_empty=True,
                )
                if remaining:
                    residuals.append((room_path, item, remaining))
            if residuals:
                raise AssertionError(f"账单中心清理门禁未通过：{residuals}")

            print(f"preflight_rooms={len(keys)}")
            print(f"active_run_bills={len(active)}")
            print(f"cleaned_now={len(cleaned)}")
            print(f"verified_zero_residuals={len(keys)}")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
