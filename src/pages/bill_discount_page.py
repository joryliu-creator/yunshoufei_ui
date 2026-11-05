from __future__ import annotations

import re
import time

from playwright.sync_api import Frame, Locator, Page, expect

from src.pages.base_page import BasePage
from src.pages.portal_page import PortalPage


class BillDiscountPage(BasePage):
    """账单减免申请、审核和房间筛选流程。"""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.frame: Frame | None = None

    def open(self, project_name: str) -> None:
        portal = PortalPage(self.page)
        portal.dismiss_home_overlays()
        tabs = self.page.get_by_role("tab", name=re.compile(r"减免管理-新"))
        visible_tabs = [tabs.nth(i) for i in range(tabs.count()) if tabs.nth(i).is_visible()]
        if len(visible_tabs) == 1:
            visible_tabs[0].click()
        else:
            cloud = self.page.get_by_role("menuitem", name="云收费", exact=True)
            if cloud.is_visible():
                cloud.click()
            settings = self.page.get_by_role("menuitem", name="收费设置", exact=False)
            expect(settings).to_be_visible(timeout=30_000)
            if settings.get_attribute("aria-expanded") != "true":
                settings.click()
            entry = self.page.get_by_role(
                "menuitem", name=re.compile(r"减免管理")
            )
            expect(entry).to_be_visible(timeout=30_000)
            entry.click()
        self.frame = self._wait_for_frame()
        self._wait_ready()
        self._select_project(project_name)

    def create_application(
        self,
        *,
        room_number: str,
        discount_scheme: str,
        remark: str,
        discount_amount: str = "",
    ) -> None:
        frame = self._require_frame()
        add = frame.get_by_role("button", name=re.compile(r"新增减免"))
        if add.count() == 0:
            add = frame.get_by_text("新增减免", exact=True)
        self.require_single(add, "新增减免按钮").click()
        drawer = self._visible_container(r"新增减免")

        self._select_room(drawer, room_number)
        search = drawer.get_by_role("button", name=re.compile(r"搜索"))
        if search.count() == 0:
            search = drawer.locator("button:visible").filter(has_text=re.compile(r"搜索"))
        self.require_single(search, "减免账单搜索按钮").click()
        self._wait_loading()
        self._select_bill_row(drawer, room_number)

        self._click_step(drawer, "下一步")
        self._select_discount_scheme(drawer, discount_scheme)
        if discount_amount.strip():
            self._fill_discount_amount(drawer, discount_amount)
        self._fill_labeled_field(drawer, "减免说明", remark)
        self._click_step(drawer, "下一步")
        expect(drawer).to_contain_text(re.compile(r"确认减免账单"), timeout=15_000)
        self._click_step(drawer, "发起审核")
        expect(drawer).to_be_hidden(timeout=30_000)
        expect(frame.locator(".el-message:visible")).to_contain_text(
            re.compile(r"申请减免成功|成功"), timeout=30_000
        )

    def search_room(self, room_number: str) -> Locator:
        frame = self._require_frame()
        advanced = frame.get_by_role("button", name=re.compile(r"高级搜索"))
        self.require_single(advanced, "减免管理高级搜索按钮").click()
        drawer = self._visible_container(r"高级搜索")
        self._select_advanced_room(drawer, room_number)
        search = drawer.get_by_role("button", name=re.compile(r"搜索"))
        self.require_single(search, "减免管理高级搜索提交按钮").click()
        self._wait_loading()
        if drawer.is_visible():
            close = drawer.locator(
                ".el-drawer__close-btn, button[aria-label*='关闭']"
            )
            if close.count() == 1 and close.is_visible():
                close.click()
                expect(drawer).to_be_hidden(timeout=15_000)
        return frame.locator(".el-table__body-wrapper tr.el-table__row:visible")

    def audit_room(self, room_number: str, remark: str) -> None:
        frame = self._require_frame()
        rows = frame.locator(".el-table__body-wrapper tr.el-table__row:visible").filter(
            has_text=room_number
        )
        expect(rows).to_have_count(1, timeout=30_000)
        row = rows.first
        row_index = row.evaluate(
            "row => Array.from(row.parentElement.children).indexOf(row)"
        )
        operation_rows = frame.locator(
            ".el-table__fixed-right .el-table__fixed-body-wrapper tr.el-table__row:visible"
        )
        operation = operation_rows.nth(row_index) if operation_rows.count() > row_index else row
        audit = operation.get_by_text("审核", exact=True)
        if audit.count() == 0:
            audit = operation.get_by_role("button", name="审核", exact=True)
        self.require_single(audit, "减免申请审核按钮").click()
        dialog = self._visible_container(r"审核")
        self._fill_labeled_field(dialog, "审核说明", remark)
        confirm = dialog.get_by_role("button", name="确认", exact=True)
        if confirm.count() == 0:
            confirm = dialog.locator("button:visible").filter(
                has_text=re.compile(r"^(?:审核)?通过$|^确定$")
            )
        if confirm.count() != 1:
            raise AssertionError(
                "减免审核确认按钮应唯一，"
                f"实际={confirm.count()}；弹窗按钮={dialog.locator('button:visible').all_inner_texts()}"
            )
        confirm.click()
        expect(dialog).to_be_hidden(timeout=30_000)
        expect(frame.locator(".el-message:visible")).to_contain_text(
            re.compile(r"审批通过|审核通过|成功"), timeout=30_000
        )

    def _select_project(self, project_name: str) -> None:
        frame = self._require_frame()
        selectors = frame.locator(".jie-project:visible")
        if selectors.count() == 0:
            selectors = frame.locator(".jie-project")
        if selectors.count() == 0:
            return
        # 新版页面可能同时保留两个可见项目选择器（主表和抽屉副本）。
        # 先按目标项目文本收敛；若两份均显示同一当前项目，使用第一份
        # 读取状态即可，禁止按随机 DOM 顺序点击不同项目。
        matching = selectors.filter(has_text=re.compile(re.escape(project_name)))
        if matching.count() == 1:
            selector = matching.first
        elif matching.count() > 1:
            selector = matching.first
        else:
            selector = self.require_single(selectors, "减免管理项目选择器")
        current = selector.locator("span.textOverflow")
        if current.count() == 1 and current.inner_text().strip() == project_name:
            return
        selector.click()
        popup_id = selector.get_attribute("aria-describedby")
        if not popup_id:
            raise AssertionError("减免管理项目选择器缺少弹层标识")
        popup = frame.locator(f"#{popup_id}:visible")
        expect(popup).to_be_visible(timeout=15_000)
        target = popup.get_by_text(project_name, exact=True)
        self.require_single(target, "减免管理目标项目").click()
        expect(current).to_have_text(project_name, timeout=15_000)

    def _select_room(self, container: Locator, room_number: str) -> None:
        labels = container.get_by_text("房间名称", exact=True)
        triggers: list[Locator] = []
        for label_index in range(labels.count()):
            field = labels.nth(label_index).locator(
                "xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' jie-content ')][1]"
            )
            candidate = field.locator('input[placeholder="请选择"]:visible')
            if candidate.count() == 1:
                triggers.append(candidate)
        if len(triggers) != 1:
            contexts = [
                labels.nth(i).evaluate(
                    "(node) => (node.parentElement && node.parentElement.outerHTML || node.outerHTML).slice(0, 1800)"
                )
                for i in range(labels.count())
                if labels.nth(i).is_visible()
            ]
            raise AssertionError(
                "房间名称 jie-content 内的“请选择”输入框应唯一，"
                f"实际={len(triggers)}；标签上下文={contexts!r}"
            )
        trigger = triggers[0]
        frame = self._require_frame()
        tree = frame.locator(".el-tree:visible, [role='tree']:visible")
        # The room selector is occasionally mounted a little after the drawer;
        # retry the same trigger instead of failing on a transient empty tree.
        for attempt in range(3):
            trigger.click(force=True)
            try:
                expect(tree).to_have_count(1, timeout=8_000)
                break
            except AssertionError:
                if attempt == 2:
                    exc = AssertionError("房间树未展开")
                    self.page.screenshot(
                        path="artifacts/discount-room-not-open.png",
                        full_page=True,
                    )
                    raise AssertionError(
                        "房间名称选择控件点击后未弹出房间树；"
                        f"控件={trigger.evaluate('(node) => node.outerHTML')!r}"
                    ) from exc
                self.page.wait_for_timeout(1_000)
        search_inputs = frame.locator(
            'input[placeholder*="请输入"]:visible:not([readonly]):not([disabled])'
        )
        if search_inputs.count():
            room_search = search_inputs.first
        else:
            room_search = trigger
        self._fill_filter(room_search, room_number)
        leaf = tree.get_by_text(room_number, exact=True)
        expect(leaf).to_be_visible(timeout=30_000)
        content = leaf.locator(
            "xpath=ancestor::*[contains(@class,'el-tree-node__content')][1]"
        )
        checkbox = content.locator(".el-checkbox__inner")
        if checkbox.count() == 1:
            checkbox.click()
        else:
            leaf.click()
        panel = tree.locator("xpath=ancestor::*[.//button][1]")
        confirm = panel.get_by_text("确定", exact=True)
        self.require_single(confirm, "房间树确定按钮").click()
        expect(container).to_contain_text(room_number, timeout=15_000)

    def _select_advanced_room(self, drawer: Locator, room_number: str) -> None:
        # Discount Management filters directly by room.  The bill-object
        # hover menu is specific to Temporary Ledger and does not exist here.
        label = self.require_single(
            drawer.get_by_text("房间名称", exact=True), "高级搜索房间名称标签"
        )
        field = label.locator(
            "xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' jie-dialog-label ')][1]"
        )
        trigger = self.require_single(
            field.locator(".jie-poper-input:visible"), "高级搜索房间选择器"
        )
        trigger_input = trigger.locator("input:visible:not([disabled])")
        (trigger_input if trigger_input.count() == 1 else trigger).click(force=True)
        tree = self._require_frame().locator(".el-tree:visible, [role='tree']:visible")
        try:
            expect(tree).to_have_count(1, timeout=5_000)
        except AssertionError as exc:
            self.page.screenshot(
                path="artifacts/discount-advanced-room-not-open.png",
                full_page=True,
            )
            raise AssertionError(
                "高级搜索房间控件点击后未展开；"
                f"触发器={trigger.evaluate('(node) => node.outerHTML')!r}"
            ) from exc
        search = trigger.locator("input:visible:not([readonly]):not([disabled])")
        if search.count() == 0:
            search = field.locator(
                'input[placeholder*="请输入"]:visible:not([readonly]):not([disabled])'
            )
        self.require_single(search, "高级搜索房间输入框")
        self._fill_filter(search, room_number)
        leaf = tree.get_by_text(room_number, exact=True)
        expect(leaf).to_have_count(1, timeout=30_000)
        content = leaf.locator(
            "xpath=ancestor::*[contains(@class,'el-tree-node__content')][1]"
        )
        checkbox = content.locator(".el-checkbox__inner")
        if checkbox.count() == 1:
            checkbox.click()
        else:
            leaf.click()
        popover = tree.locator(
            "xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' el-popover ')][1]"
        )
        confirm = popover.get_by_text("确定", exact=True)
        self.require_single(confirm, "高级搜索房间确定按钮").click()
        expect(field).to_contain_text(room_number, timeout=15_000)

    def _select_bill_row(self, drawer: Locator, room_number: str) -> None:
        rows = drawer.locator(".el-table__body-wrapper tr.el-table__row:visible").filter(
            has_text=room_number
        )
        if rows.count() == 0:
            rows = drawer.locator("tr:visible").filter(has_text=room_number)
        self.require_single(rows, "待减免账单业务行")
        row = rows.first
        checkbox = row.locator("label.el-checkbox:visible")
        if checkbox.count() == 0:
            checkbox = row.locator(".el-checkbox__input:visible")
        if checkbox.count() == 0:
            checkbox = drawer.locator(
                ".el-table__fixed-body-wrapper label.el-checkbox:visible"
            )
        self.require_single(checkbox, "待减免账单选择框").click()

    def _select_discount_scheme(self, drawer: Locator, scheme: str) -> None:
        label = drawer.get_by_text("减免方案", exact=True)
        self.require_single(label, "减免方案字段标签")
        # The second step renders several inputs in the same grid row.  Bind
        # the selector to the form item that owns the exact label instead of
        # walking to the first generic ancestor containing any input.
        form_item = label.locator(
            "xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' el-form-item ')][1]"
        )
        selectors = form_item.locator(".el-select:visible")
        if selectors.count() == 0:
            # This drawer is built with a description grid rather than an
            # el-form-item in some releases.  At this step the only visible
            # select is the discount-scheme selector; hidden readonly inputs
            # from earlier steps must not be clicked.
            selectors = drawer.locator(".el-select:visible")
        self.require_single(selectors, "减免方案选择框").click()
        # Element UI portals the dropdown to the body of the discount
        # business document, which is still inside the business iframe.
        dropdown = self._require_frame().locator(".el-select-dropdown:visible").last
        expect(dropdown).to_be_visible(timeout=15_000)
        option = dropdown.get_by_text(scheme, exact=True)
        self.require_single(option, "账单减免目标方案").click()

    def _click_step(self, container: Locator, name: str) -> None:
        button = container.get_by_role("button", name=name, exact=True)
        if button.count() == 0:
            button = container.get_by_text(name, exact=True)
        self.require_single(button, f"减免流程{name}按钮").click()
        self.page.wait_for_timeout(500)

    def _fill_labeled_field(self, container: Locator, label: str, value: str) -> None:
        direct = container.locator(
            f'input:visible[placeholder*="{label}"], textarea:visible[placeholder*="{label}"]'
        )
        if direct.count() == 1:
            direct.fill(value)
            return
        label_node = container.get_by_text(re.compile(rf"^\s*{re.escape(label)}\s*$"))
        self.require_single(label_node, f"{label}字段标签")
        form_item = label_node.locator(
            "xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' el-form-item ')][1]"
        )
        target = form_item.locator("input:visible, textarea:visible")
        if target.count() == 0:
            target = label_node.locator("xpath=following::input[1]")
        self.require_single(target, f"{label}输入框").fill(value)

    def _fill_discount_amount(self, container: Locator, value: str) -> None:
        """Fill the amount input rendered to the right of the 减免金额 label."""
        def commit(target: Locator) -> None:
            target.click()
            target.fill("")
            target.press_sequentially(value, delay=100)
            target.press("Tab")
            expect(target).to_have_value(
                re.compile(rf"^{re.escape(value)}(?:\.0+)?$"), timeout=10_000
            )

        labels = container.get_by_text(re.compile(r"^\s*减免金额\s*[:：]?$"))
        if labels.count() == 0:
            labels = container.get_by_text(re.compile(r"减免金额"))
        candidates = []
        for index in range(labels.count()):
            label = labels.nth(index)
            field = label.locator(
                "xpath=ancestor::*[self::tr or "
                "contains(concat(' ',normalize-space(@class),' '),' el-form-item ') or "
                "contains(concat(' ',normalize-space(@class),' '),' el-descriptions-item ')][1]"
            )
            editable = field.locator(
                'input:visible:not([readonly]):not([disabled])'
            )
            if editable.count() == 1:
                candidates.append(editable)
        if len(candidates) == 1:
            commit(candidates[0])
            return
        # Current custom-amount build initializes the amount control to 0.00.
        # This value-based fallback excludes the scheme selector and remark.
        zero_inputs = container.locator(
            'input:visible:not([readonly]):not([disabled])'
        )
        zero_candidates = [
            zero_inputs.nth(index)
            for index in range(zero_inputs.count())
            if zero_inputs.nth(index).input_value().strip() in {"0", "0.0", "0.00"}
        ]
        if len(zero_candidates) != 1:
            raise AssertionError(
                "减免金额右侧输入框应唯一，"
                f"标签数={labels.count()}，零值输入框数={len(zero_candidates)}。"
            )
        commit(zero_candidates[0])

    def _visible_container(self, title_pattern: str) -> Locator:
        frame = self._require_frame()
        candidates = frame.locator(".el-drawer:visible, .el-dialog:visible")
        matches = [
            candidates.nth(i)
            for i in range(candidates.count())
            if re.search(title_pattern, candidates.nth(i).inner_text())
        ]
        if len(matches) != 1:
            raise AssertionError(f"{title_pattern}容器应唯一可见，实际 {len(matches)} 个")
        return matches[0]

    def _visible_tree(self, container: Locator) -> Locator:
        tree = container.locator(".el-tree:visible, [role='tree']:visible")
        if tree.count() == 0:
            tree = self._require_frame().locator(".el-tree:visible, [role='tree']:visible")
        if tree.count() == 0:
            # Element UI tree popovers are portaled to the document body in
            # this page build, outside both the drawer and its iframe.
            tree = self.page.locator(".el-tree:visible, [role='tree']:visible")
        if tree.count() == 0:
            # A few portal builds mount the popover in a sibling business
            # iframe.  Search only visible trees across the already-mounted
            # frames; never expand an unrelated hidden tree.
            for frame in self.page.frames:
                candidate = frame.locator(".el-tree:visible, [role='tree']:visible")
                if candidate.count() == 1:
                    tree = candidate
                    break
        self.require_single(tree, "房间树").wait_for(state="visible", timeout=30_000)
        return tree

    @staticmethod
    def _fill_filter(locator: Locator, value: str) -> None:
        try:
            locator.fill("")
        except Exception:
            locator.click()
            locator.press("Control+A")
            locator.press("Backspace")
        locator.press_sequentially(value, delay=100)
        locator.press("Enter")

    def _wait_ready(self) -> None:
        frame = self._require_frame()
        self._wait_loading()
        button = frame.get_by_role("button", name=re.compile(r"新增减免"))
        if button.count() == 0:
            button = frame.get_by_text("新增减免", exact=True)
        expect(button).to_be_visible(timeout=30_000)

    def _wait_loading(self) -> None:
        frame = self._require_frame()
        expect(frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )

    def _require_frame(self) -> Frame:
        if self.frame is None:
            raise AssertionError("账单减免业务 iframe 尚未初始化")
        return self.frame

    def _wait_for_frame(self) -> Frame:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            for frame in self.page.frames:
                if frame == self.page.main_frame:
                    continue
                try:
                    if frame.get_by_text("新增减免", exact=True).count() or frame.get_by_role(
                        "button", name=re.compile(r"新增减免")
                    ).count():
                        return frame
                except Exception:
                    pass
            self.page.wait_for_timeout(500)
        raise AssertionError(
            f"未识别到账单减免业务 iframe；当前框架={[f.url for f in self.page.frames]}"
        )
