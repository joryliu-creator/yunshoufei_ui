from __future__ import annotations

import re

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, expect


class PortalPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    def open_home(self, base_url: str, master_customer_id: str) -> None:
        self.page.goto(
            f"{base_url}#/Home?masterCustomerId={master_customer_id}",
            wait_until="domcontentloaded",
        )
        self.dismiss_home_overlays()
        self.collapse_customer_service()
        expect(
            self.page.get_by_role("menuitem", name="云收费", exact=True)
        ).to_be_visible(timeout=30_000)

    def dismiss_home_overlays(self) -> None:
        # 登录后可能同时出现“通知提醒”弹窗和“全部公告”侧边抽屉。
        # 只关闭当前可见遮挡层，不处理业务页面中的普通弹窗。
        self.page.wait_for_timeout(1_000)
        dialog_close_buttons = self.page.locator(
            ".el-dialog__wrapper:visible .el-dialog__headerbtn"
        )
        for _ in range(10):
            if dialog_close_buttons.count() == 0:
                break
            dialog_close_buttons.last.click()
            self.page.wait_for_timeout(500)

        drawer_close_buttons = self.page.locator(
            ".el-drawer__wrapper:visible .el-drawer__close-btn"
        )
        while drawer_close_buttons.count() > 0:
            drawer_close_buttons.first.click()
            self.page.wait_for_timeout(300)

    def open_billing_center(self) -> None:
        self.dismiss_home_overlays()
        self.collapse_customer_service()
        cloud_billing = self.page.get_by_role(
            "menuitem", name="云收费", exact=True
        )
        if cloud_billing.is_visible():
            cloud_billing.click()

        billing_center = self.page.get_by_role(
            "menuitem", name="账单中心", exact=True
        )
        expect(billing_center).to_be_visible(timeout=15_000)
        billing_center.click()

    def collapse_customer_service(self) -> None:
        open_panel = self.page.locator(".bar-container .f-container.open")
        if open_panel.count() == 0 or not open_panel.first.is_visible():
            return

        candidates = self.page.locator(".bar-container").get_by_text(
            re.compile(r"在\s*线\s*客\s*服")
        )
        visible_candidates = []
        for index in range(candidates.count()):
            candidate = candidates.nth(index)
            box = candidate.bounding_box() if candidate.is_visible() else None
            if box:
                visible_candidates.append((box["width"], candidate))

        if not visible_candidates:
            raise AssertionError("在线客服已展开，但未找到可见收起控件。")
        collapse_button = min(visible_candidates, key=lambda item: item[0])[1]
        try:
            collapse_button.click(timeout=2_000)
        except PlaywrightTimeoutError:
            # 通知弹窗可能在首次清理后异步出现并遮挡客服按钮。
            self.dismiss_home_overlays()
            if open_panel.count() == 0 or not open_panel.first.is_visible():
                return
            try:
                collapse_button.click(timeout=2_000)
            except PlaywrightTimeoutError:
                open_panel.first.evaluate("el => el.classList.remove('open')")
        try:
            expect(open_panel).to_be_hidden(timeout=1_000)
        except AssertionError:
            open_panel.first.evaluate("el => el.classList.remove('open')")
            expect(open_panel).to_be_hidden(timeout=5_000)
