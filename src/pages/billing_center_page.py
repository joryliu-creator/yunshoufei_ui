from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.sync_api import FrameLocator, Locator, Page, expect

from src.pages.base_page import BasePage


@dataclass(frozen=True, slots=True)
class BillData:
    project_name: str
    room_path: str
    charge_type: str
    charge_item: str
    billing_month: str
    receivable_date: str
    latest_payment_date: str


@dataclass(frozen=True, slots=True)
class CreatedBill:
    bill_number: str
    charge_item: str
    receivable_date: str


class BillingCenterPage(BasePage):
    def __init__(self, page: Page) -> None:
        self.page = page
        self.frame: FrameLocator = page.frame_locator(
            'iframe[src*="BillingCenter"]'
        )

    def wait_until_ready(self) -> None:
        expect(
            self.frame.get_by_role("button", name="创建账单", exact=True)
        ).to_be_visible(timeout=30_000)
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )

    def select_project(self, project_name: str) -> None:
        project_input = self.frame.locator(
            "input[readonly]:not([placeholder])"
        )
        expect(project_input).to_have_count(1, timeout=30_000)
        project_input = self.require_single(project_input, "项目选择框")
        project_selector = project_input.locator(
            "xpath=ancestor::div[contains(@class, 'jie-project')][1]"
        )
        expect(project_selector).to_have_count(1)
        current_project_label = project_selector.locator("span.textOverflow")
        current_target = current_project_label.filter(
            has_text=re.compile(rf"^{re.escape(project_name)}$")
        )
        if current_target.count() >= 1:
            return

        project_selector.click()
        popover_id = project_selector.get_attribute("aria-describedby")
        if not popover_id:
            raise AssertionError("项目选择框缺少关联的项目树弹窗标识。")
        project_popover = self.frame.locator(f"#{popover_id}:visible")
        expect(project_popover).to_be_visible(timeout=15_000)
        visible_project = project_popover.get_by_text(project_name, exact=True)
        expect(visible_project).to_have_count(1, timeout=15_000)
        visible_project.click()
        expect(current_project_label).to_have_text(project_name, timeout=15_000)

    def open_create_bill(self) -> Locator:
        self.frame.get_by_role("button", name="创建账单", exact=True).click()
        dialog = self.frame.get_by_role("dialog")
        expect(dialog).to_be_visible(timeout=15_000)
        return dialog

    def fill_bill(self, dialog: Locator, data: BillData) -> None:
        self._select_room(dialog, data.room_path)

        date_inputs = dialog.get_by_placeholder("选择日期")
        expect(date_inputs).to_have_count(2)
        date_inputs.nth(0).fill(data.receivable_date)
        self.page.keyboard.press("Escape")

        month_input = self.require_single(
            dialog.get_by_placeholder("选择年月"), "账期选择框"
        )
        month_input.fill(data.billing_month)
        month_input.press("Enter")
        self.page.keyboard.press("Escape")

        select_inputs = dialog.locator('input[readonly][placeholder="请选择"]')
        expect(select_inputs).to_have_count(1)
        self._select_dropdown_option(select_inputs.nth(0), data.charge_type)
        expect(select_inputs).to_have_count(2, timeout=10_000)
        self._select_dropdown_option(select_inputs.nth(1), data.charge_item)

        date_inputs.nth(1).fill(data.latest_payment_date)

        expect(month_input).to_have_value(data.billing_month)
        expect(select_inputs.nth(0)).to_have_value(data.charge_type)
        expect(select_inputs.nth(1)).to_have_value(data.charge_item)

        # 页面曾出现“账期框显示 7 月，但实际生成 8 月账单”的问题。
        # 提交前检查实际收费周期，避免创建错误数据。
        period_inputs = dialog.locator('input[placeholder="开始时间"]')
        expect(period_inputs).to_have_count(2)
        expect(period_inputs.nth(0)).to_have_value(
            re.compile(rf"^{re.escape(data.billing_month)}")
        )

    def submit_and_skip_notification(
        self, dialog: Locator, data: BillData
    ) -> CreatedBill:
        dialog.get_by_role("button", name="确定", exact=True).click()

        no_notification = self.frame.get_by_role(
            "button", name="不需要", exact=True
        )
        expect(no_notification).to_be_visible(timeout=15_000)
        no_notification.click()

        expect(dialog).to_be_hidden(timeout=30_000)
        row = self._find_main_table_row(
            charge_item=data.charge_item,
            receivable_date=data.receivable_date,
        )
        expect(row).to_be_visible(timeout=30_000)

        bill_number_cell = self.require_single(
            row.locator('td[class*="_column_25"]'), "账单编号单元格"
        )
        bill_number = bill_number_cell.inner_text().strip()
        if not bill_number:
            raise AssertionError("创建成功后未读取到账单编号。")

        return CreatedBill(
            bill_number=bill_number,
            charge_item=data.charge_item,
            receivable_date=data.receivable_date,
        )

    def cleanup_bill(
        self,
        bill_number: str,
        void_reason: str,
        billing_month: str | None = None,
    ) -> None:
        row = self._find_main_table_row(bill_number=bill_number)
        if row.count() == 0 and billing_month:
            self._filter_billing_month(billing_month)
            row = self._find_main_table_row(bill_number=bill_number)
            expect(row).to_have_count(1, timeout=30_000)

        if row.count() == 0:
            visible_inputs = self.frame.locator("input:visible").evaluate_all(
                "els => els.map(e => ({placeholder: e.placeholder, value: e.value, readonly: e.readOnly}))"
            )
            visible_buttons = [
                text.strip()
                for text in self.frame.locator("button:visible").all_inner_texts()
                if text.strip()
            ]
            raise AssertionError(
                f"当前筛选结果中找不到账单 {bill_number}；"
                f"可见输入框：{visible_inputs}；可见按钮：{visible_buttons}"
            )
        expect(row).to_be_visible(timeout=30_000)

        if "已作废" not in row.inner_text():
            self._select_only_result_row()
            self._open_more_action("批量作废")

            void_dialog = self.frame.get_by_role("dialog").filter(
                has_text="作废"
            )
            expect(void_dialog).to_be_visible(timeout=15_000)
            reason_input = self.require_single(
                void_dialog.get_by_role("textbox"), "作废理由输入框"
            )
            reason_input.fill(void_reason)
            expect(reason_input).to_have_value(void_reason)
            void_confirm = void_dialog.get_by_text("确定作废", exact=True)
            visible_void_confirms = [
                void_confirm.nth(index)
                for index in range(void_confirm.count())
                if void_confirm.nth(index).is_visible()
            ]
            if len(visible_void_confirms) != 1:
                raise AssertionError(
                    "批量作废弹窗内“确定作废”应唯一可见，实际可见 "
                    f"{len(visible_void_confirms)} 个；弹窗按钮："
                    f"{void_dialog.locator('button').all_inner_texts()}"
                )
            visible_void_confirms[0].click()
            expect(row).to_contain_text("已作废", timeout=30_000)

        self._select_only_result_row()
        self._open_more_action("批量删除")

        delete_prompt = self.frame.get_by_text(
            re.compile(r"删除后.*不可恢复.*确定.*删除")
        )
        expect(delete_prompt).to_be_visible(timeout=15_000)
        delete_panel = delete_prompt.locator("xpath=ancestor::*[.//button][1]")
        delete_confirm = delete_panel.get_by_text("确定", exact=True)
        self.require_single(delete_confirm, "批量删除确认按钮").click()
        expect(self._find_main_table_row(bill_number=bill_number)).to_have_count(
            0, timeout=30_000
        )

    def _select_only_result_row(self) -> None:
        row_checkboxes = self.frame.locator(
            "tbody label.el-checkbox:visible"
        )
        expect(row_checkboxes.first).to_be_visible(timeout=10_000)
        checkbox = row_checkboxes.first
        classes = checkbox.get_attribute("class") or ""
        if "is-checked" not in classes:
            checkbox.click()
        expect(checkbox).to_have_class(re.compile(r"\bis-checked\b"))

    def _open_more_action(self, action: str) -> None:
        open_customer_service = self.page.locator(
            ".bar-container .f-container.open"
        )
        if open_customer_service.count() > 0:
            candidates = self.page.locator(".bar-container").get_by_text(
                re.compile(r"在\s*线\s*客\s*服")
            )
            visible_candidates = []
            for index in range(candidates.count()):
                candidate = candidates.nth(index)
                box = candidate.bounding_box() if candidate.is_visible() else None
                if box:
                    visible_candidates.append((box["width"], candidate))
            if visible_candidates:
                min(visible_candidates, key=lambda item: item[0])[1].click()
                try:
                    expect(open_customer_service).to_be_hidden(timeout=1_000)
                except AssertionError:
                    open_customer_service.first.evaluate(
                        "el => el.classList.remove('open')"
                    )
                    expect(open_customer_service).to_be_hidden(timeout=5_000)

        more_button = self.frame.locator("button:visible").filter(
            has_text=re.compile(r"^\s*更多\s*")
        )
        self.require_single(more_button, "更多按钮").click()
        action_locator = self.frame.get_by_text(action, exact=True)
        visible_actions = [
            action_locator.nth(index)
            for index in range(action_locator.count())
            if action_locator.nth(index).is_visible()
        ]
        if len(visible_actions) != 1:
            raise AssertionError(
                f"更多菜单中的 {action} 应唯一可见，实际可见 "
                f"{len(visible_actions)} 个。"
            )
        visible_actions[0].click(force=True)

    def get_only_result_bill_number(
        self, billing_month: str, room_path: str
    ) -> str:
        self._filter_billing_month(billing_month)
        rows = self.frame.locator(
            ".el-table__body-wrapper tr.el-table__row"
        )
        expect(rows).to_have_count(1, timeout=30_000)
        row_text = rows.first.inner_text()
        expect(self.frame.get_by_placeholder("开始年月")).to_have_value(
            billing_month
        )
        expect(self.frame.get_by_placeholder("结束年月")).to_have_value(
            billing_month
        )
        room_matches = self.frame.get_by_text(room_path, exact=True)
        visible_rooms = [
            room_matches.nth(index)
            for index in range(room_matches.count())
            if room_matches.nth(index).is_visible()
        ]
        if len(visible_rooms) != 1:
            raise AssertionError(
                "唯一结果的目标房间应唯一可见，实际可见 "
                f"{len(visible_rooms)} 个，禁止继续清理。"
            )
        if "已作废" not in row_text:
            raise AssertionError("唯一结果尚未作废，禁止直接删除。")
        match = re.search(r"ZD[A-Z0-9]+", row_text)
        if not match:
            raise AssertionError("唯一结果中未读取到账单编号。")
        return match.group(0)

    def _filter_billing_month(self, billing_month: str) -> None:
        start_month = self.require_single(
            self.frame.get_by_placeholder("开始年月"), "开始账期"
        )
        end_month = self.require_single(
            self.frame.get_by_placeholder("结束年月"), "结束账期"
        )
        start_month.fill(billing_month)
        start_month.press("Enter")
        end_month.fill(billing_month)
        end_month.press("Enter")
        self.page.keyboard.press("Escape")
        expect(start_month).to_have_value(billing_month)
        expect(end_month).to_have_value(billing_month)
        search_button = self.frame.locator("button:visible").filter(
            has_text=re.compile(r"^\s*搜索\s*$")
        )
        self.require_single(search_button, "账单搜索按钮").click()
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        expect(start_month).to_have_value(billing_month)
        expect(end_month).to_have_value(billing_month)

    def _select_room(self, dialog: Locator, room_path: str) -> None:
        room_input = self.require_single(
            dialog.get_by_placeholder("请选择房间"), "房间选择框"
        )
        room_input.fill("")
        room_input.click()
        room_tree = self.frame.locator(".el-tree:visible")
        expect(room_tree).to_have_count(1, timeout=10_000)

        parts = [part for part in room_path.split("/") if part]
        if not parts:
            raise ValueError("ROOM_PATH 不能为空。")

        for part in parts[:-1]:
            node_text = room_tree.get_by_text(part, exact=True)
            expect(node_text).to_have_count(1, timeout=30_000)
            node_text = self.require_single(node_text, f"房间树节点 {part}")
            node = node_text.locator("xpath=ancestor::*[contains(@class, 'el-tree-node')][1]")
            expand_icon = node.locator(".el-tree-node__expand-icon")
            if expand_icon.count() == 1 and expand_icon.is_visible():
                classes = expand_icon.get_attribute("class") or ""
                if "expanded" not in classes:
                    expand_icon.click()

        leaf = room_tree.get_by_text(parts[-1], exact=True)
        expect(leaf).to_have_count(1, timeout=30_000)
        leaf = self.require_single(leaf, f"房间树叶子节点 {parts[-1]}")
        leaf_content = leaf.locator(
            "xpath=ancestor::*[contains(@class, 'el-tree-node__content')][1]"
        )
        leaf_checkbox = leaf_content.locator(".el-checkbox")
        if leaf_checkbox.count() == 1:
            leaf_checkbox.click()
            expect(leaf_checkbox).to_have_class(re.compile(r"\bis-checked\b"))
        else:
            leaf.click()

        room_panel = room_tree.locator("xpath=ancestor::*[.//button][1]")
        room_confirm = room_panel.get_by_text(
            re.compile(r"^确\s*[认定]$")
        )
        expect(room_confirm).to_have_count(1, timeout=10_000)
        room_confirm.click()
        expect(dialog.get_by_text(parts[-1], exact=True)).to_be_visible(
            timeout=10_000
        )

    def _select_dropdown_option(self, input_locator: Locator, option: str) -> None:
        input_locator.click()
        dropdown = self.frame.locator(".el-select-dropdown:visible").last
        expect(dropdown).to_be_visible(timeout=10_000)
        option_locator = dropdown.get_by_text(option, exact=True)
        try:
            expect(option_locator).to_have_count(1, timeout=10_000)
        except AssertionError as exc:
            available_options = [
                text.strip()
                for text in dropdown.locator(
                    ".el-select-dropdown__item:not(.is-disabled)"
                ).all_inner_texts()
                if text.strip()
            ]
            raise AssertionError(
                f"下拉选项 {option} 应唯一匹配一个元素，实际匹配到 "
                f"{option_locator.count()} 个；当前可选项：{available_options}；"
                f"下拉层文本：{dropdown.inner_text().strip()!r}；"
                f"下拉层结构：{dropdown.evaluate('el => el.outerHTML.slice(0, 3000)')}"
            ) from exc
        option_locator.click()

    def _find_main_table_row(
        self,
        *,
        bill_number: str | None = None,
        charge_item: str | None = None,
        receivable_date: str | None = None,
    ) -> Locator:
        rows = self.frame.locator(
            ".el-table__body-wrapper tr.el-table__row"
        )
        if bill_number:
            rows = rows.filter(has_text=bill_number)
        if charge_item:
            rows = rows.filter(has_text=charge_item)
        if receivable_date:
            rows = rows.filter(has_text=receivable_date)
        return rows
