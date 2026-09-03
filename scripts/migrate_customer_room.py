from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.customer_data import (  # noqa: E402
    load_all_customer_room_mappings,
    load_customer_room_mapping,
)
from src.config.settings import settings  # noqa: E402
from src.pages.customer_management_page import CustomerManagementPage  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="迁入云收费客户关联房间")
    parser.add_argument("--room", default="1002", help="单个房间号，默认 1002")
    parser.add_argument("--project", default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "artifacts" / "customer_room_migration_report.json",
        help="JSON result report path",
    )
    args = parser.parse_args()
    mappings = load_all_customer_room_mappings() if args.all else [load_customer_room_mapping(args.room)]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.set_default_timeout(30_000)
        portal = PortalPage(page)
        customer_page = CustomerManagementPage(page)
        portal.open_home(
            settings.base_url,
            settings.master_customer_id,
            environment=settings.test_environment,
            account_role="default",
        )
        customer_page.open()
        results: list[dict[str, str]] = []
        try:
            for mapping in mappings:
                project = args.project or mapping.project_name
                status = customer_page.migrate_room_for_customer(
                    mapping.customer_name, mapping.room_path, project
                )
                result = {
                    "room": mapping.room_path.rstrip("/").split("/")[-1],
                    "customer": mapping.customer_name,
                    "status": status,
                }
                results.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
        finally:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        context.close()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
