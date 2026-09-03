from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import FrameLocator, Locator, Page, Response, expect

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
    original_amount: Decimal | None
    discount_amount: Decimal | None
    receivable_amount: Decimal | None
    bill_row_text: str
    amount_read_error: str = ""


class BillingCenterPage(BasePage):
    def __init__(self, page: Page) -> None:
        self.page = page
        # 新门户路由可能使用 BillingCenter、billCenter 等不同大小写命名；
        # 每次打开业务菜单都会将当前活动 iframe 追加在最后，以“创建账单”
        # 按钮作为最终业务页校验，避免依赖不稳定的 URL 大小写。
        self.frame: FrameLocator = page.frame_locator("iframe").last

    def wait_until_ready(self) -> None:
        create_button = self.frame.get_by_role(
            "button", name="创建账单", exact=True
        )
        try:
            expect(create_button).to_be_visible(timeout=15_000)
        except AssertionError as exc:
            frames = [
                {"url": frame.url, "name": frame.name}
                for frame in self.page.frames
            ]
            raise AssertionError(
                "账单中心 iframe 未加载出“创建账单”按钮；"
                f"当前框架={frames}"
            ) from exc
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=30_000
        )

    def wait_until_table_readable(self) -> None:
        """只读恢复场景允许表格可读但初始化遮罩尚未完全消失。"""
        expect(
            self.frame.locator(".el-table__body-wrapper")
        ).to_be_visible(timeout=60_000)

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
        dialog = self.frame.locator(
            ".el-drawer[role='dialog']:visible"
        ).filter(has_text="创建账单")
        expect(dialog).to_have_count(1, timeout=15_000)
        expect(dialog).to_be_visible(timeout=15_000)
        return dialog

    def fill_bill(self, dialog: Locator, data: BillData) -> None:
        self._select_room(dialog, data.room_path)

        date_inputs = dialog.get_by_placeholder("选择日期")
        # 新版创建抽屉在新增收费项之前只展示应收日期；最晚缴款日
        # 在收费明细“编辑”后填写。保留 >= 1 的断言，避免把新版
        # 页面误判为旧版双日期表单。
        if date_inputs.count() < 1:
            raise AssertionError("创建账单抽屉未找到应收日期输入框。")
        date_inputs.nth(0).fill(data.receivable_date)
        date_inputs.nth(0).press("Enter")
        self.page.keyboard.press("Escape")
        expect(date_inputs.nth(0)).to_have_value(data.receivable_date)

        month_input = self.require_single(
            dialog.get_by_placeholder("选择年月"), "账期选择框"
        )
        self._select_billing_month(month_input, data.billing_month)
        self._add_charge_item(dialog, data.charge_item)
        self._edit_charge_detail(
            dialog,
            charge_item=data.charge_item,
            latest_payment_date=data.latest_payment_date,
        )

    def _select_billing_month(self, month_input: Locator, billing_month: str) -> None:
        """Select the billing month through the Element UI month picker.

        Filling the input directly can leave the picker model on the current
        month (especially after the calendar rolls over), so always open the
        component and click the target year/month cell.
        """
        year, month = billing_month.split("-", 1)
        month_names = {
            "01": "一月", "02": "二月", "03": "三月", "04": "四月",
            "05": "五月", "06": "六月", "07": "七月", "08": "八月",
            "09": "九月", "10": "十月", "11": "十一月", "12": "十二月",
        }
        month_input.click()
        panel = self.frame.locator(".el-picker-panel:visible").last
        expect(panel).to_be_visible(timeout=10_000)
        # The panel opens on the currently selected year in supported builds.
        # If it is a different year, open the year selector and choose ours.
        if panel.get_by_text(f"{year} 年", exact=True).count() == 0:
            header_year = panel.locator(".el-date-picker__header-label").filter(
                has_text=re.compile(r"年")
            ).first
            if header_year.count() == 1:
                header_year.click()
                year_cell = panel.get_by_text(year, exact=True)
                expect(year_cell).to_be_visible(timeout=5_000)
                year_cell.click()
        target = panel.get_by_text(month_names[month], exact=True)
        expect(target).to_be_visible(timeout=10_000)
        target.click()
        expect(month_input).to_have_value(billing_month, timeout=10_000)

    def _add_charge_item(self, dialog: Locator, charge_item: str) -> None:
        """Use the new charge-item drawer instead of the legacy inline select."""
        add_buttons = dialog.get_by_text("新增收费项", exact=True)
        visible_add_buttons = [
            add_buttons.nth(index)
            for index in range(add_buttons.count())
            if add_buttons.nth(index).is_visible()
        ]
        if len(visible_add_buttons) != 1:
            raise AssertionError(
                "创建账单明细区域“新增收费项”应唯一可见，实际 "
                f"{len(visible_add_buttons)} 个。"
            )
        visible_add_buttons[0].click()

        picker_candidates = self.frame.locator(
            ".el-drawer[role='dialog']:visible"
        )
        pickers = []
        for index in range(picker_candidates.count()):
            candidate = picker_candidates.nth(index)
            text = candidate.inner_text().strip()
            if re.search(r"选择.*收费项", text):
                pickers.append(candidate)
        if len(pickers) != 1:
            raise AssertionError(
                "新增收费项后应唯一出现选择收费项抽屉，实际 "
                f"{len(pickers)} 个；可见抽屉={picker_candidates.count()}。"
            )
        picker = pickers[0]
        expect(picker).to_be_visible(timeout=30_000)

        search_inputs = picker.locator(
            'input.el-input__inner:visible:not([readonly]):not([disabled])'
        )
        if search_inputs.count() != 1:
            candidates = picker.locator(
                'input[placeholder*="收费项"]:visible:not([readonly]):not([disabled]), '
                'input[placeholder*="名称"]:visible:not([readonly]):not([disabled])'
            )
            if candidates.count() == 1:
                search_inputs = candidates
        # In the current picker the first visible input filters available
        # charge items and the second filters the already-selected list.
        # Keep the left (first) input when both are present.
        if search_inputs.count() == 0:
            raise AssertionError(
                "选择收费项抽屉内的收费项搜索框应唯一，实际 "
                f"{search_inputs.count()} 个。"
            )
        # Give the UI one render turn after the successful response before
        # typing; this avoids filtering an empty pre-render snapshot.
        self.page.wait_for_timeout(500)
        # Expand fee-type groups so a filtered item is rendered consistently
        # across Element UI versions that do not auto-expand on search.
        collapsed_icons = picker.locator(
            ".el-tree-node:not(.is-expanded) > .el-tree-node__content > "
            ".el-tree-node__expand-icon:not(.is-leaf):visible"
        )
        for index in range(collapsed_icons.count()):
            collapsed_icons.nth(index).click()
            self.page.wait_for_timeout(200)
        search = search_inputs.first
        search.fill(charge_item)
        # The redesigned dual-pane picker filters on the input event.  Enter
        # is not a search action here and can submit/reset the left tree,
        # leaving no selectable result.
        expect(picker.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=30_000
        )
        self.page.wait_for_timeout(500)
        collapsed_icons = picker.locator(
            ".el-tree-node:not(.is-expanded) > .el-tree-node__content > "
            ".el-tree-node__expand-icon:not(.is-leaf):visible"
        )
        for index in range(collapsed_icons.count()):
            collapsed_icons.nth(index).click()
            self.page.wait_for_timeout(200)

        item_texts = picker.get_by_text(charge_item, exact=True)
        # The charge-item tree is populated asynchronously after the drawer
        # opens.  Wait for the filtered item to actually render instead of
        # sampling the list immediately (which can briefly show “暂无数据”).
        try:
            expect(item_texts.first).to_be_visible(timeout=20_000)
        except AssertionError as exc:
            raise AssertionError(
                f"收费项筛选后未展示目标 {charge_item!r}；"
                f"收费项抽屉文本={picker.inner_text()!r}"
            ) from exc
        visible_items = [
            item_texts.nth(index)
            for index in range(item_texts.count())
            if item_texts.nth(index).is_visible()
        ]
        if len(visible_items) != 1:
            raise AssertionError(
                "选择收费项抽屉内目标收费项应唯一可见，实际 "
                f"{len(visible_items)} 个。"
            )
        item = visible_items[0]
        # The Element UI tree is replaced after filtering. Clicking its label
        # wrapper can report success without changing the model, especially
        # when a transparent tree layer is still settling. Re-acquire the row,
        # click the concrete checkbox control, and require the item to appear
        # in the selected (right) pane before confirming the drawer.
        last_error: PlaywrightError | None = None
        selected = False
        for _ in range(3):
            try:
                current_items = picker.get_by_text(charge_item, exact=True)
                visible_count = sum(
                    1
                    for index in range(current_items.count())
                    if current_items.nth(index).is_visible()
                )
                if visible_count >= 2:
                    selected = True
                    break
                current_item = current_items.first
                expect(current_item).to_be_visible(timeout=10_000)
                checkbox = self._item_checkbox(current_item)
                inner = checkbox.locator(".el-checkbox__inner")
                if inner.count() == 1:
                    inner.click(force=True)
                else:
                    checkbox.click(force=True)
                self.page.wait_for_timeout(800)
            except PlaywrightError as exc:
                last_error = exc
                self.page.wait_for_timeout(500)
        if not selected:
            current_items = picker.get_by_text(charge_item, exact=True)
            visible_count = sum(
                1
                for index in range(current_items.count())
                if current_items.nth(index).is_visible()
            )
            selected = visible_count >= 2
        if not selected:
            raise AssertionError(
                f"目标收费项 {charge_item!r} 未进入右侧已选列表"
            ) from last_error

        confirm = picker.get_by_role("button", name="确定", exact=True)
        visible_confirms = [
            confirm.nth(index)
            for index in range(confirm.count())
            if confirm.nth(index).is_visible()
        ]
        if len(visible_confirms) != 1:
            raise AssertionError(
                "选择收费项抽屉右下角“确定”应唯一可见，实际 "
                f"{len(visible_confirms)} 个。"
            )
        visible_confirms[0].click()
        expect(picker).to_be_hidden(timeout=30_000)
        expect(dialog).to_contain_text(charge_item, timeout=30_000)

    def _item_checkbox(self, item: Locator) -> Locator:
        """Find the checkbox belonging to a visible charge-item row."""
        containers = [
            item.locator("xpath=ancestor::tr[1]"),
            item.locator(
                "xpath=ancestor::*[contains(@class, 'el-tree-node__content')][1]"
            ),
            item.locator(
                "xpath=ancestor::*[.//label[contains(@class, 'el-checkbox')] or "
                ".//span[contains(@class, 'el-checkbox')]][1]"
            ),
        ]
        for container in containers:
            if container.count() != 1 or not container.is_visible():
                continue
            # Element UI deployments differ slightly: some render the
            # checkbox as a label wrapper, others expose only the input
            # wrapper.  Prefer the wrapper so its `is-checked` class can be
            # asserted consistently, then fall back to the inner control.
            for selector in (
                "label.el-checkbox:visible",
                "span.el-checkbox:visible",
                ".el-checkbox__input:visible",
                ".el-checkbox__inner:visible",
                "input[type='checkbox']:visible",
            ):
                checkboxes = container.locator(selector)
                if checkboxes.count() == 1:
                    return checkboxes
        raise AssertionError("收费项结果行未找到唯一可操作的勾选框。")

    def _edit_charge_detail(
        self,
        dialog: Locator,
        *,
        charge_item: str,
        latest_payment_date: str,
    ) -> None:
        """Edit the added detail row and keep both billing-period ranges intact."""
        rows = dialog.locator("tr").filter(has_text=charge_item)
        if rows.count() == 0:
            rows = dialog.locator(".el-table__row").filter(has_text=charge_item)
        if rows.count() != 1:
            raise AssertionError(
                "新增收费项后应唯一匹配一条明细行，实际 "
                f"{rows.count()} 行。"
            )
        row = rows.first
        edit = row.get_by_text("编辑", exact=True)
        visible_edits = [
            edit.nth(index)
            for index in range(edit.count())
            if edit.nth(index).is_visible()
        ]
        if len(visible_edits) != 1:
            raise AssertionError(
                "新增收费项明细行的“编辑”应唯一可见，实际 "
                f"{len(visible_edits)} 个。"
            )
        visible_edits[0].click()

        editable_dates = row.locator(
            'input[placeholder="选择日期"]:visible:not([readonly]):not([disabled])'
        )
        if editable_dates.count() != 1:
            raise AssertionError(
                "编辑收费明细后最晚缴款日输入框应唯一，实际 "
                f"{editable_dates.count()} 个；计费期间和用户端展示期间不得修改。"
            )
        latest = editable_dates.first
        latest.fill(latest_payment_date)
        latest.press("Enter")
        self.page.keyboard.press("Escape")
        expect(latest).to_have_value(latest_payment_date)

        save = row.get_by_text("保存", exact=True)
        visible_saves = [
            save.nth(index)
            for index in range(save.count())
            if save.nth(index).is_visible()
        ]
        if len(visible_saves) != 1:
            raise AssertionError(
                "新增收费项明细行的“保存”应唯一可见，实际 "
                f"{len(visible_saves)} 个。"
            )
        visible_saves[0].click()
        expect(row.get_by_text("保存", exact=True)).to_have_count(0, timeout=15_000)
        expect(row.get_by_text("编辑", exact=True)).to_be_visible(timeout=15_000)
        expect(row).to_contain_text(latest_payment_date, timeout=15_000)

    def submit_and_skip_notification(
        self, dialog: Locator, data: BillData
    ) -> CreatedBill:
        confirm = self.require_single(
            dialog.get_by_role("button", name="确定", exact=True),
            "创建账单最终确定按钮",
        )
        expect(confirm).to_be_enabled(timeout=15_000)
        confirm.click(force=True)

        result_dialog = self.frame.get_by_role(
            "dialog", name="账单创建结果"
        )
        feedback = self.frame.locator(
            ".el-message:visible, .el-message-box:visible, .el-notification:visible, "
            ".el-form-item__error:visible"
        )
        for _ in range(240):
            if result_dialog.count() and result_dialog.is_visible():
                break
            messages = [text.strip() for text in feedback.all_inner_texts() if text.strip()]
            if messages:
                raise AssertionError(
                    "提交创建账单时页面返回错误：" + "；".join(messages)
                )
            self.page.wait_for_timeout(250)
        else:
            feedback = self.frame.locator(
                ".el-message:visible, .el-message-box:visible, .el-notification:visible, "
                ".el-form-item__error:visible"
            )
            details = feedback.all_inner_texts()
            drawer_text = dialog.inner_text() if dialog.is_visible() else "创建账单抽屉已关闭"
            raise AssertionError(
                "提交创建账单后未出现‘账单创建结果’弹窗；"
                f"页面反馈={details or '无可见反馈'}；抽屉内容={drawer_text!r}"
            )
        no_notification = result_dialog.get_by_role(
            "button", name="不需要", exact=True
        )
        expect(no_notification).to_be_visible(timeout=15_000)
        no_notification.click()

        expect(result_dialog).to_be_hidden(timeout=30_000)
        expect(dialog).to_be_hidden(timeout=30_000)
        row = self._find_main_table_row(
            room_path=data.room_path,
            charge_item=data.charge_item,
            receivable_date=data.receivable_date,
        )
        expect(row).to_be_visible(timeout=30_000)

        row_candidates = [row.nth(index) for index in range(row.count())]
        if not row_candidates:
            raise AssertionError("创建成功后未定位到账单业务行。")
        main_row = max(
            row_candidates, key=lambda candidate: candidate.locator("td").count()
        )
        bill_row_text = main_row.inner_text()

        bill_number_cell = self.require_single(
            main_row.locator('td[class*="_column_25"]'), "账单编号单元格"
        )
        bill_number = bill_number_cell.inner_text().strip()
        if not bill_number:
            raise AssertionError("创建成功后未读取到账单编号。")

        amount_error = ""
        try:
            amounts = self._read_bill_amounts(main_row)
        except AssertionError as exc:
            amounts = {
                "original_amount": None,
                "discount_amount": None,
                "receivable_amount": None,
            }
            amount_error = str(exc)

        return CreatedBill(
            bill_number=bill_number,
            charge_item=data.charge_item,
            receivable_date=data.receivable_date,
            original_amount=amounts["original_amount"],
            discount_amount=amounts["discount_amount"],
            receivable_amount=amounts["receivable_amount"],
            bill_row_text=bill_row_text,
            amount_read_error=amount_error,
        )

    def assert_bill_amounts(
        self,
        created_bill: CreatedBill,
        *,
        expected_original: Decimal,
        expected_discount: Decimal,
        expected_receivable: Decimal,
    ) -> None:
        if created_bill.amount_read_error:
            raise AssertionError(
                "账单已创建但金额读取失败："
                f"{created_bill.amount_read_error}；"
                f"账单编号={created_bill.bill_number}。"
            )
        actual = (
            created_bill.original_amount,
            created_bill.discount_amount,
            created_bill.receivable_amount,
        )
        expected = (
            expected_original,
            expected_discount,
            expected_receivable,
        )
        if actual != expected:
            raise AssertionError(
                "账单金额断言失败："
                f"原始金额/减免金额/应收金额期望={expected}，实际={actual}，"
                f"账单编号={created_bill.bill_number}。"
            )

    def cleanup_bill(
        self,
        bill_number: str,
        void_reason: str,
        billing_month: str | None = None,
    ) -> None:
        row = self._find_main_table_row(bill_number=bill_number)
        if row.count() == 0 and billing_month:
            # A locator can briefly report zero while the table re-renders
            # after the preceding search; retry the current result first.
            self.page.wait_for_timeout(1_000)
            row = self._find_main_table_row(bill_number=bill_number)
        if row.count() == 0 and billing_month:
            self._filter_billing_month(billing_month)
            # The list refresh is asynchronous; do not query the virtualized
            # table while its loading mask is still mounted.
            expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
                0, timeout=60_000
            )
            self.page.wait_for_timeout(1_000)
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
            self._select_only_result_row(bill_number)
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
            expect(self._find_main_table_row(bill_number=bill_number)).to_contain_text(
                "已作废", timeout=30_000
            )

        self._select_only_result_row(bill_number)
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

    def _select_only_result_row(self, bill_number: str | None = None) -> None:
        if bill_number:
            rows = self._find_main_table_row(bill_number=bill_number)
            row_checkboxes = rows.locator("label.el-checkbox:visible")
        else:
            row_checkboxes = self.frame.locator("tbody label.el-checkbox:visible")
        if row_checkboxes.count() == 0 and bill_number:
            # Some table builds render the visible hit target as the span
            # inside the label (or expose only the native checkbox input) in
            # the fixed selection column. Keep the bill-number row scope and
            # support those equivalent DOM variants.
            rows = self._find_main_table_row(bill_number=bill_number)
            row_checkboxes = rows.locator(
                ".el-checkbox__input:visible, input[type='checkbox']:visible"
            )
            if row_checkboxes.count() == 0:
                # Element UI's fixed selection column is rendered as a
                # separate table.  Scope the checkbox to the fixed row that
                # contains this bill number before considering any fallback;
                # otherwise every visible result-row checkbox is collected.
                fixed_rows = self.frame.locator(
                    ".el-table__fixed-body-wrapper tr.el-table__row"
                ).filter(has_text=bill_number)
                fixed_row_checkboxes = fixed_rows.locator(
                    "label.el-checkbox:visible, .el-checkbox__input:visible, "
                    "input[type='checkbox']:visible"
                )
                if fixed_row_checkboxes.count() > 0:
                    row_checkboxes = fixed_row_checkboxes
            if row_checkboxes.count() == 0:
                # Element UI renders the fixed selection column as a separate
                # table, so its checkbox is not a descendant of the matching
                # content row.  Only accept the fallback when the filtered
                # result is exactly one visible data row and exactly one
                # visible row checkbox exists; this keeps cleanup scoped.
                all_row_checkboxes = self.frame.locator(
                    ".el-table__fixed-body-wrapper .el-checkbox__input:visible, "
                    ".el-table__fixed-body-wrapper label.el-checkbox:visible"
                )
                if all_row_checkboxes.count() == 0:
                    all_row_checkboxes = self.frame.locator(
                        "tbody label.el-checkbox:visible, "
                        "tbody .el-checkbox__input:visible"
                    )
                if rows.count() != 1 or all_row_checkboxes.count() not in {1, 2}:
                    fixed_html = self.frame.locator(
                        ".el-table__fixed-body-wrapper, .el-table__fixed"
                    ).all_inner_texts()
                    raise AssertionError(
                        f"账单行存在但未找到唯一可选复选框："
                        f"行数={rows.count()}，候选数={all_row_checkboxes.count()}，"
                        f"固定列文本={fixed_html}；行文本={rows.inner_text()}"
                    )
                row_checkboxes = all_row_checkboxes
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
        self,
        billing_month: str,
        room_path: str,
        *,
        require_void: bool = True,
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
        if require_void and "已作废" not in row_text:
            raise AssertionError("唯一结果尚未作废，禁止直接删除。")
        match = re.search(r"ZD[A-Z0-9]+", row_text)
        if not match:
            raise AssertionError("唯一结果中未读取到账单编号。")
        return match.group(0)

    def get_calculation_result_bill_number(
        self,
        *,
        billing_month: str,
        room_path: str,
        charge_item: str,
        expected_amount: str | None = None,
    ) -> str:
        """Find a calculation-billing result through the verified room filter.

        Calculation billing has no creation-result bill number on its own
        screen.  Its post-audit cleanup therefore starts in Bill Center by
        filtering the exact room and month, then validates the uniquely
        matching active bill before reading its generated number.
        """
        self._filter_billing_month(billing_month)
        search = self._open_advanced_search()
        self._select_advanced_room(search, room_path)
        search_button = self.require_single(
            search.get_by_role("button", name="搜索", exact=True),
            "账单中心高级搜索提交按钮",
        )
        search_button.click()
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )

        rows = self._find_main_table_row(
            room_path=room_path,
            charge_item=charge_item,
        )
        try:
            expect(rows).to_have_count(1, timeout=30_000)
        except AssertionError:
            from pathlib import Path

            Path("artifacts/billing-center-room-filter.txt").write_text(
                self.frame.locator("body").inner_text(), encoding="utf-8"
            )
            raise
        row = rows.first
        row_text = row.inner_text()
        if "已作废" in row_text:
            raise AssertionError("房间筛选结果为已作废账单，禁止作为本次清理目标。")
        expect(row).to_contain_text(billing_month)
        expect(row).to_contain_text(expected_amount)
        match = re.search(r"ZD[A-Z0-9]+", row_text)
        if not match:
            raise AssertionError(f"房间筛选结果未读取到账单编号：{row_text!r}")
        return match.group(0)

    def get_calculation_result_bill_numbers(
        self,
        *,
        billing_month: str,
        room_path: str,
        charge_item: str | None = None,
        bill_type: str | None = None,
        expected_amount: str | None = None,
    ) -> list[str]:
        """Return every active matching bill number for duplicate cleanup."""
        self._filter_billing_month(billing_month)
        search = self._open_advanced_search()
        self._select_advanced_room(search, room_path)
        self.require_single(
            search.get_by_role("button", name="搜索", exact=True),
            "账单中心高级搜索提交按钮",
        ).click()
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        rows = self._find_main_table_row(
            room_path=room_path,
            charge_item=charge_item,
        )
        if bill_type:
            rows = rows.filter(has_text=bill_type)
        normalized = expected_amount.replace(",", "") if expected_amount else None
        numbers: list[str] = []
        for index in range(rows.count()):
            row = rows.nth(index)
            if not row.is_visible():
                continue
            text = row.inner_text()
            if "已作废" in text or (normalized and normalized not in text):
                continue
            match = re.search(r"ZD[A-Z0-9]+", text)
            if match:
                numbers.append(match.group(0))
        if not numbers:
            Path("artifacts").mkdir(exist_ok=True)
            Path("artifacts/billing-center-room-filter.txt").write_text(
                self.frame.locator("body").inner_text(), encoding="utf-8"
            )
            raise AssertionError("账单中心未找到活动的目标账单")
        return numbers

    def get_bill_numbers_by_month_room_charge_item(
        self, *, billing_month: str, room_path: str, charge_item: str
    ) -> list[str]:
        """Resolve active Bill Center rows without relying on advanced room tree."""
        self._filter_billing_month(billing_month)
        rows = self._find_main_table_row(room_path=room_path, charge_item=charge_item)
        numbers: list[str] = []
        for index in range(rows.count()):
            row = rows.nth(index)
            if not row.is_visible():
                continue
            text = row.inner_text()
            if "已作废" in text:
                continue
            match = re.search(r"ZD[A-Z0-9]+", text)
            if match:
                numbers.append(match.group(0))
        if not numbers:
            raise AssertionError("账单中心未找到指定账期、房间和收费项的有效账单")
        return numbers

    def cleanup_by_month_room_charge_item(
        self, *, billing_month: str, room_path: str, charge_item: str,
        void_reason: str,
    ) -> list[str]:
        """Void/delete every active bill matching the business key.

        The business key, not a bill number, is the cleanup entry point. Any
        captured numbers are used only internally after the exact query.
        """
        numbers = self.get_bill_numbers_by_month_room_charge_item(
            billing_month=billing_month, room_path=room_path, charge_item=charge_item
        )
        for number in reversed(dict.fromkeys(numbers)):
            self.cleanup_bill(number, void_reason, billing_month)
        return numbers

    def get_active_temporary_bill_numbers(self, *, billing_month: str) -> list[str]:
        """List active bills whose *bill type* is 临时类 for a billing month.

        Both temporary-charge and deposit-charge items are represented by this
        bill type, so cleanup must not depend on the charge-item label.
        """
        # Bill Center's list query uses a year range; querying only the exact
        # month can return zero even when that month's rows are visible in the
        # normal Jan-Dec list.  Keep the target month for later cleanup, but
        # search the full calendar year.
        year = billing_month.split("-", 1)[0]
        start_month = self.require_single(
            self.frame.get_by_placeholder("开始年月"), "开始账期"
        )
        end_month = self.require_single(
            self.frame.get_by_placeholder("结束年月"), "结束账期"
        )
        start_month.fill(f"{year}-01")
        start_month.press("Enter")
        end_month.fill(f"{year}-12")
        end_month.press("Enter")
        self.page.keyboard.press("Escape")
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=120_000
        )
        search_button = self.frame.locator("button:visible").filter(
            has_text=re.compile(r"^\s*搜索\s*$")
        )
        self.require_single(search_button, "账单搜索按钮").click()
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        rows = self.frame.locator(
            ".el-table__body-wrapper tr.el-table__row:visible"
        )
        if rows.count() == 0:
            Path("artifacts").mkdir(exist_ok=True)
            Path("artifacts/billing-center-temporary-cleanup.txt").write_text(
                self.frame.locator("body").inner_text(), encoding="utf-8"
            )
        numbers: list[str] = []
        for index in range(rows.count()):
            text = rows.nth(index).inner_text()
            if "临时类" not in text or "已作废" in text:
                continue
            match = re.search(r"ZD[A-Z0-9]+", text)
            if match:
                numbers.append(match.group(0))
        return list(dict.fromkeys(numbers))

    def _open_advanced_search(self) -> Locator:
        button = self.require_single(
            self.frame.get_by_role("button", name="高级搜索", exact=False),
            "账单中心高级搜索按钮",
        )
        button.click()
        drawer = self.frame.locator(".el-drawer:visible").filter(
            has_text="高级搜索"
        )
        expect(drawer).to_have_count(1, timeout=15_000)
        return drawer

    def _set_advanced_month(self, drawer: Locator, billing_month: str) -> None:
        # Element UI supplies two date inputs inside the drawer.  Restrict by
        # value/placeholder instead of matching the main page's date range.
        inputs = drawer.locator(
            'input.el-input__inner:visible[placeholder*="年"]'
        )
        if inputs.count() == 0:
            inputs = drawer.locator('input:visible[placeholder*="月"]')
        if inputs.count() != 2:
            raise AssertionError(
                f"高级搜索账期应有两个输入框，实际 {inputs.count()} 个。"
            )
        for index in (0, 1):
            inputs.nth(index).fill(billing_month)
            inputs.nth(index).press("Enter")
        self.page.keyboard.press("Escape")
        expect(inputs.nth(0)).to_have_value(billing_month)
        expect(inputs.nth(1)).to_have_value(billing_month)

    def _select_advanced_room(self, drawer: Locator, room_path: str) -> None:
        room_label = self.require_single(
            drawer.get_by_text("房间名称", exact=True), "高级搜索房间名称标签"
        )
        row = room_label.locator("xpath=ancestor::*[.//input][1]")
        inputs = row.locator('input[readonly]:visible, input[placeholder="请选择"]:visible')
        if inputs.count() == 0:
            # Some builds render the room selector as a plain visible input
            # without readonly/placeholder attributes.
            inputs = row.locator("input:visible")
        if inputs.count() != 1:
            raise AssertionError(
                f"房间名称右侧请选择输入框应唯一，实际 {inputs.count()} 个。"
            )
        # 房间树支持直接在“请选择”输入框按房间名称过滤。先等树根真实
        # 出现，再输入末级房间号并等待过滤结果，避免异步重绘吞字或逐层
        # 展开整棵房间树。
        inputs.first.click(force=True)
        # Advanced-search room picker is rendered inside the drawer on some
        # builds and portaled to the iframe root on others.
        tree = drawer.locator(".el-tree:visible, [role='tree']:visible")
        if tree.count() == 0:
            tree = self.frame.locator(".el-tree:visible, [role='tree']:visible")
        if tree.count() == 0:
            tree = self.page.locator(".el-tree:visible, [role='tree']:visible")
        search_input = inputs.first
        try:
            search_input.fill("")
        except Exception:
            # Element-UI may expose the selector as readonly while still
            # accepting keyboard filtering after focus.
            search_input.click()
            search_input.press("Control+A")
            search_input.press("Backspace")
        search_input.press_sequentially(room_path.rsplit("/", 1)[-1], delay=120)
        inputs.first.press("Enter")
        # Some deployments mount the tree only after the search text is
        # entered; wait for that asynchronous mount instead of failing on an
        # initially empty locator.
        expect(tree).to_have_count(1, timeout=30_000)
        leaf_name = room_path.rsplit("/", 1)[-1]
        leaf = tree.get_by_text(leaf_name, exact=True)
        expect(leaf).to_be_visible(timeout=30_000)
        row = leaf.locator(
            "xpath=ancestor::*[contains(@class, 'el-tree-node__content')][1]"
        )
        checkbox = row.locator(".el-checkbox__inner")
        self.require_single(checkbox, "高级搜索目标房间勾选框").click()
        panel = tree.locator("xpath=ancestor::*[.//button][1]")
        confirm = panel.get_by_text("确定", exact=True)
        self.require_single(confirm, "高级搜索房间确认按钮").click()
        expect(drawer).to_contain_text(leaf_name, timeout=15_000)

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
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=120_000
        )
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
        parts = [part for part in room_path.split("/") if part]
        if not parts:
            raise ValueError("ROOM_PATH 不能为空。")

        room_tree = self.frame.locator(".el-tree:visible")
        room_name = parts[-1]
        tree_load_error: AssertionError | None = None
        api_responses: list[Response] = []

        def record_api_response(response: Response) -> None:
            if response.request.resource_type not in {"xhr", "fetch"}:
                return
            api_responses.append(response)

        self.page.on("response", record_api_response)
        try:
            for attempt in range(1, 4):
                room_input.fill("")
                room_input.click()
                try:
                    expect(room_tree).to_have_count(1, timeout=10_000)
                    # 房间树是异步加载的。必须等根节点真实出现后，才在
                    # 左侧搜索框输入房间号；否则重绘会吞掉过早输入的文本。
                    expect(
                        room_tree.get_by_text(parts[0], exact=True)
                    ).to_be_visible(timeout=30_000)
                    # Some deployments render a two-pane picker, where the
                    # first visible “请输入” field filters available rooms;
                    # others render a compact tree whose original trigger
                    # input is itself the search field.  Both variants must
                    # type only after the tree root is ready.
                    search_inputs = self.frame.locator(
                        'input[placeholder*="请输入"]:visible:not([readonly]):not([disabled])'
                    )
                    # In the two-pane variant the right input filters only
                    # selected rooms, so the first is the correct left input.
                    # The compact variant has no extra input and falls back
                    # to the opened room trigger.
                    room_search = search_inputs.first if search_inputs.count() else room_input
                    room_search.fill("")
                    room_search.press_sequentially(room_name, delay=120)
                    room_search.press("Enter")
                    expect(
                        room_tree.get_by_text(room_name, exact=True)
                    ).to_have_count(1, timeout=30_000)
                    tree_load_error = None
                    break
                except AssertionError as exc:
                    tree_load_error = exc
                    self.page.keyboard.press("Escape")
                    self.page.wait_for_timeout(2_000)
        finally:
            self.page.remove_listener("response", record_api_response)
        if tree_load_error is not None:
            recent_responses = ", ".join(
                f"{response.status} {urlsplit(response.url).path}"
                for response in api_responses[-12:]
            ) or "无XHR/fetch响应"
            tree_response_summary = ""
            tree_responses = [
                response
                for response in api_responses
                if urlsplit(response.url).path.endswith("/getBuildRoomNew")
            ]
            if tree_responses:
                try:
                    payload = tree_responses[-1].json()
                    if isinstance(payload, dict):
                        data = payload.get("data")
                        data_shape = (
                            f"{type(data).__name__}[{len(data)}]"
                            if hasattr(data, "__len__")
                            else type(data).__name__
                        )
                        tree_response_summary = (
                            "；房间接口业务响应="
                            f"respCode={payload.get('respCode')!r}, "
                            f"respMsg={payload.get('respMsg')!r}, "
                            f"success={payload.get('success')!r}, "
                            f"data={data_shape}"
                        )
                except Exception as exc:  # 诊断信息不能覆盖原始失败
                    tree_response_summary = f"；房间接口响应解析失败={type(exc).__name__}"
            tree_text = room_tree.inner_text().strip() if room_tree.count() else ""
            raise AssertionError(
                f"房间选择条件连续3次未就绪（根节点或房间搜索框）{parts[0]!r}，禁止继续出账；"
                f"树文本={tree_text!r}；近期接口={recent_responses}"
                f"{tree_response_summary}。"
            ) from tree_load_error

        leaf = room_tree.get_by_text(room_name, exact=True)
        expect(leaf).to_have_count(1, timeout=30_000)
        leaf = self.require_single(leaf, f"房间树叶子节点 {room_name}")
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
        expect(dialog.get_by_text(room_name, exact=True)).to_be_visible(
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
        expect(input_locator).to_have_value(option, timeout=15_000)
        expect(dropdown).to_be_hidden(timeout=15_000)

    def _find_main_table_row(
        self,
        *,
        bill_number: str | None = None,
        room_path: str | None = None,
        charge_item: str | None = None,
        receivable_date: str | None = None,
    ) -> Locator:
        rows = self.frame.locator(
            ".el-table__body-wrapper tr.el-table__row"
        )
        if bill_number:
            rows = rows.filter(has_text=bill_number)
        if room_path:
            rows = rows.filter(has_text=room_path)
        if charge_item:
            rows = rows.filter(has_text=charge_item)
        if receivable_date:
            rows = rows.filter(has_text=receivable_date)
        return rows

    def _read_bill_amounts(self, row: Locator) -> dict[str, Decimal]:
        def amount_by_column(description: str, column_key: str) -> Decimal:
            candidates = row.locator("td")
            matched = []
            pattern = re.compile(
                rf"\b(?:el-table_\d+_)?{re.escape(column_key)}\b"
            )
            for index in range(candidates.count()):
                candidate = candidates.nth(index)
                if pattern.search(candidate.get_attribute("class") or ""):
                    matched.append(candidate)
            if len(matched) != 1:
                classes = candidates.evaluate_all(
                    "els => els.map(el => el.className)"
                )
                raise AssertionError(
                    f"{description}金额单元格应唯一匹配，实际 {len(matched)} 个；"
                    f"当前行业列={classes}"
                )
            cell = matched[0]
            raw = cell.inner_text().replace(",", "").replace("￥", "").strip()
            try:
                return Decimal(raw).quantize(Decimal("0.00"))
            except InvalidOperation as exc:
                raise AssertionError(
                    f"{description}金额不是有效数字：{raw!r}"
                ) from exc

        return {
            # 页面真实复合列：本金分组 column_13 下的应收/减免，
            # column_12 为包含本金与违约金的合计欠款（当前应缴）。
            "original_amount": amount_by_column(
                "本金应收", "column_13_column_14"
            ),
            "discount_amount": amount_by_column(
                "本金减免", "column_13_column_15"
            ),
            "receivable_amount": amount_by_column(
                "合计欠款", "column_12"
            ),
        }
