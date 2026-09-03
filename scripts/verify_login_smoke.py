"""Real portal login smoke check without creating business data."""
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.environments import load_test_environment  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.pages.portal_page import PortalPage  # noqa: E402


def main() -> None:
    load_test_environment(ROOT, "standard1", override=False)
    settings = Settings.from_env()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            PortalPage(page).open_home(
                settings.base_url,
                settings.master_customer_id,
                environment=settings.test_environment,
                account_role="default",
            )
            page.screenshot(path=str(ROOT / "artifacts" / "login-smoke-success.png"))
            print("LOGIN_SMOKE=PASS")
            print(f"PORTAL_URL={page.url}")
        except Exception:
            page.screenshot(path=str(ROOT / "artifacts" / "login-smoke-failure.png"))
            print("LOGIN_SMOKE=FAIL")
            raise
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
