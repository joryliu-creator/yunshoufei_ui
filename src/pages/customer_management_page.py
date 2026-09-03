from __future__ import annotations

import re
import time

from playwright.sync_api import Frame, Locator, Page, expect

from src.pages.base_page import BasePage


class CustomerManagementPage(BasePage):
    """客户管理 A 的企业客户房间迁入流程。"""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.frame: Frame | None = None

    def open(self) -> None:
        """Open 客户管理1 -> 客户管理A and wait for its business iframe."""
        self._close_portal_overlays()
        top = self.page.get_by_role("menuitem", name="客户管理1", exact=True)
        expect(top).to_be_visible(timeout=30_000)
        top.dispatch_event("click")
        self.frame = self._wait_for_customer_frame()
        expect(self.frame.get_by_text("企业客户", exact=True)).to_be_visible(
            timeout=60_000
        )

    def migrate_room_for_customer(
        self,
        customer_name: str,
        room_path: str,
        project_name: str,
    ) -> str:
        frame = self._require_frame()
        self._select_project(project_name)
        self._search_customer(customer_name)

        customer_cells = frame.get_by_role("button", name=customer_name, exact=True)
        if customer_cells.count() == 0:
            customer_cells = frame.get_by_text(customer_name, exact=True)
        visible_customer_cells = [
            customer_cells.nth(index)
            for index in range(customer_cells.count())
            if customer_cells.nth(index).is_visible()
        ]
        if len(visible_customer_cells) != 1:
            raise AssertionError(
                f"客户 {customer_name!r} 应唯一匹配，实际 {len(visible_customer_cells)} 条"
            )
        if room_path not in frame.locator("body").inner_text():
            raise AssertionError(
                f"客户搜索结果未展示预期房间 {room_path!r}，停止迁入"
            )

        # Fixed-column tables render operation cells outside the customer
        # cell's DOM row.  The exact customer search above guarantees that a
        # single visible 编辑 button is the matching operation.
        edit = frame.get_by_role("button", name="编辑", exact=True)
        expect(edit).to_have_count(1, timeout=15_000)
        edit.click(no_wait_after=True)

        drawer_title = frame.get_by_text("编辑客户信息", exact=True)
        expect(drawer_title).to_be_visible(timeout=30_000)
        tabs = frame.locator(".el-tabs__item:visible").filter(
            has_text="入驻楼栋房间"
        )
        expect(tabs).to_have_count(1, timeout=15_000)
        tabs.click()
        self.page.wait_for_timeout(1_000)

        expect(frame.get_by_text(room_path, exact=True).first).to_be_visible(
            timeout=30_000
        )
        migrate = frame.get_by_role("button", name="迁入", exact=True)
        move_out = frame.get_by_role("button", name="迁出", exact=True)
        if migrate.count() == 0 and move_out.count() == 1:
            result = "already_in"
        elif migrate.count() == 1 and move_out.count() == 0:
            migrate.click(no_wait_after=True)
            expect(frame.locator(".el-message:visible")).to_contain_text(
                "操作成功", timeout=60_000
            )
            expect(frame.get_by_text("已入住", exact=True).first).to_be_visible(
                timeout=30_000
            )
            result = "migrated"
        else:
            raise AssertionError(
                f"房间 {room_path!r} 的迁入状态无法唯一判断：迁入={migrate.count()}，迁出={move_out.count()}"
            )

        close = frame.get_by_role("button", name="关闭", exact=True)
        if close.count() == 0:
            close = frame.get_by_text("关闭", exact=True)
        expect(close).to_have_count(1, timeout=15_000)
        close.click(no_wait_after=True)
        expect(drawer_title).to_be_hidden(timeout=30_000)
        return result

    def _select_project(self, project_name: str) -> None:
        frame = self._require_frame()
        selector = frame.locator("span.m-floatOrg.project:visible")
        expect(selector).to_have_count(1, timeout=15_000)
        current = selector.inner_text().strip()
        if project_name in current:
            return
        selector.locator(".el-popover__reference").click()
        popover = frame.locator(".m-floatOrgPopper:visible")
        expect(popover).to_be_visible(timeout=15_000)
        search = popover.get_by_placeholder("请输入项目名称", exact=True)
        search.fill(project_name)
        self.page.wait_for_timeout(1_000)
        target = popover.get_by_text(project_name, exact=True)
        expect(target).to_have_count(1, timeout=30_000)
        target.click()
        expect(selector).to_contain_text(project_name, timeout=15_000)

    def _search_customer(self, customer_name: str) -> None:
        frame = self._require_frame()
        inputs = frame.locator("input[placeholder='请输入']:visible")
        expect(inputs).to_have_count(1, timeout=15_000)
        inputs.fill(customer_name)
        search = frame.locator("button:visible").filter(has_text=re.compile(r"^查询$"))
        expect(search).to_have_count(1, timeout=10_000)
        search.click(no_wait_after=True)
        expect(frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        result = frame.get_by_role("button", name=customer_name, exact=True)
        if result.count() == 0:
            result = frame.get_by_text(customer_name, exact=True)
        expect(result.first).to_be_visible(timeout=30_000)

    def _wait_for_customer_frame(self) -> Frame:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            for frame in self.page.frames:
                if frame == self.page.main_frame:
                    continue
                if "/customer-web/" in frame.url:
                    return frame
                try:
                    if frame.get_by_text("企业客户", exact=True).count() and frame.get_by_text(
                        "客户名称", exact=True
                    ).count():
                        return frame
                except Exception:
                    continue
            self.page.wait_for_timeout(500)
        raise AssertionError(
            f"未识别到客户管理 A iframe；当前 frames={[frame.url for frame in self.page.frames]}"
        )

    def _close_portal_overlays(self) -> None:
        self.page.wait_for_timeout(500)
        # Announcement dialogs can expose two header buttons, one belonging
        # to the side panel.  Dispatching the DOM click is reliable even when
        # Element UI reports the button as visible before its overlay settles.
        self.page.locator(
            ".el-dialog__wrapper:visible .el-dialog__headerbtn"
        ).evaluate_all("els => els.forEach(el => el.click())")
        self.page.wait_for_timeout(500)

    def _require_frame(self) -> Frame:
        if self.frame is None:
            raise AssertionError("尚未打开客户管理 A 页面")
        return self.frame
