from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.create_charge_standards import (  # noqa: E402
    ensure_logged_in,
    restore_session,
)
from scripts.update_room_import_template import formula_mappings  # noqa: E402
from src.config.accounts import get_account_auth_profile  # noqa: E402
from src.config.environments import load_test_environment  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402
from src.pages.room_fee_setting_page import RoomFeeSettingPage  # noqa: E402


RESULT_FILE = ROOT / "artifacts" / "room-fee-area-results.json"


def persist_results(results: list[dict[str, str]]) -> None:
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="按房间映射表逐一维护房间收费面积"
    )
    parser.add_argument("--environment", default="standard1")
    parser.add_argument("--customer-id", default="93537")
    parser.add_argument("--account", default="default")
    parser.add_argument("--project", default="云收费UI自动化")
    parser.add_argument("--fee-area", default="260.00")
    parser.add_argument(
        "--room-prefix", default="A栋/1层", help="房间完整路径前缀"
    )
    parser.add_argument(
        "--rooms",
        nargs="+",
        help="只处理指定房间；省略时处理映射表中的全部房间。",
    )
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--fresh-login", action="store_true")
    parser.add_argument("--slow-mo", type=int, default=150)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="确认执行页面保存；未传入时仅检查参数并输出计划。",
    )
    parser.add_argument(
        "--inspect-only",
        action="store_true",
        help="只读输出指定房间收费详情，不修改或保存。",
    )
    return parser.parse_args()


def normalize_fee_area(value: str) -> Decimal:
    try:
        area = Decimal(value).quantize(Decimal("0.00"))
    except InvalidOperation as exc:
        raise ValueError(f"收费面积不是有效数字：{value!r}") from exc
    if area <= 0:
        raise ValueError("收费面积必须大于 0。")
    return area


def selected_rooms(requested: list[str] | None) -> list[str]:
    all_rooms = [item.room_name for item in formula_mappings()]
    if not requested:
        return all_rooms
    requested_set = set(requested)
    missing = requested_set - set(all_rooms)
    if missing:
        raise ValueError(f"映射表不存在房间：{sorted(missing)}")
    return [room for room in all_rooms if room in requested_set]


def main() -> None:
    args = parse_args()
    profile_env = load_test_environment(
        ROOT, args.environment, override=True
    )
    if profile_env.is_production:
        raise SystemExit("生产环境禁止批量修改房间收费面积。")
    fee_area = normalize_fee_area(args.fee_area)
    rooms = selected_rooms(args.rooms)
    room_prefix = args.room_prefix.strip("/")
    plan = {
        "environment": args.environment,
        "customer_id": args.customer_id,
        "project": args.project,
        "fee_area": format(fee_area, "f"),
        "room_count": len(rooms),
        "rooms": rooms,
    }
    if not args.apply and not args.inspect_only:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    base_url = os.environ["BASE_URL"]
    profile = get_account_auth_profile(
        ROOT, args.account, args.environment, args.customer_id
    )
    if not args.fresh_login and (
        not profile.auth_file.exists() or not profile.session_file.exists()
    ):
        raise SystemExit("未找到对应环境、客户和账号的本地登录状态。")

    results: list[dict[str, str]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=not args.headful, slow_mo=args.slow_mo
        )
        context = (
            browser.new_context(viewport={"width": 1440, "height": 900})
            if args.fresh_login
            else browser.new_context(
                storage_state=str(profile.auth_file),
                viewport={"width": 1440, "height": 900},
            )
        )
        if not args.fresh_login:
            restore_session(context, profile, base_url)
        page = context.new_page()
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        try:
            ensure_logged_in(
                page,
                base_url,
                args.environment,
                args.customer_id,
                args.account,
                force_login=args.fresh_login,
            )
            portal = PortalPage(page)
            portal.dismiss_home_overlays()
            portal.collapse_customer_service()
            room_setting = RoomFeeSettingPage(page)
            room_setting.open(expected_customer_id=args.customer_id)
            room_setting.select_project(args.project)

            for room in rooms:
                room_path = f"{room_prefix}/{room}" if room_prefix else room
                result = {"room": room, "room_path": room_path}
                try:
                    if args.inspect_only:
                        detail = room_setting.read_room_detail(room_path)
                        result.update(status="inspected", detail=detail)
                    else:
                        saved = room_setting.set_fee_area(room_path, fee_area)
                        result.update(status="updated", fee_area=saved)
                except Exception as exc:
                    result.update(status="failed", reason=str(exc))
                    results.append(result)
                    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(
                        path=str(
                            RESULT_FILE.parent
                            / f"room-fee-area-failed-{room}.png"
                        ),
                        full_page=True,
                    )
                    break
                results.append(result)
                persist_results(results)
                print(
                    f"progress={len(results)}/{len(rooms)} "
                    f"room={room} status={result['status']}",
                    flush=True,
                )
        except Exception as exc:
            if not results or results[-1].get("status") != "failed":
                results.append({"status": "failed", "reason": str(exc)})
            RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(
                path=str(RESULT_FILE.parent / "room-fee-area-failed.png"),
                full_page=True,
            )
        finally:
            persist_results(results)
            context.tracing.stop(
                path=str(RESULT_FILE.parent / "room-fee-area-trace.zip")
            )
            context.close()
            browser.close()

    output = json.dumps(results, ensure_ascii=False, indent=2)
    try:
        print(output)
    except UnicodeEncodeError:
        print(output.encode("gbk", errors="backslashreplace").decode("gbk"))
    if any(item["status"] == "failed" for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
