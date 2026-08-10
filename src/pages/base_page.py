from __future__ import annotations

from playwright.sync_api import Locator


class BasePage:
    @staticmethod
    def require_single(locator: Locator, description: str) -> Locator:
        count = locator.count()
        if count != 1:
            raise AssertionError(
                f"{description} 应唯一匹配一个元素，实际匹配到 {count} 个。"
            )
        return locator
