from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Frame, FrameLocator, Locator, Page, Response, expect

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
        self.frame: Frame | FrameLocator = page.frame_locator("iframe").last

    def wait_until_ready(self) -> None:
        self._resolve_business_frame()
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

    def _resolve_business_frame(self) -> None:
        """Select the iframe that actually contains Bill Center.

        Opening the discount-management tab leaves its iframe mounted in the
        portal.  ``iframe.last`` can therefore point at reduceManage instead
        of BillingCenter when cleanup returns to the bill list.
        """
        for frame in reversed(self.page.frames):
            if frame == self.page.main_frame:
                continue
            try:
                if frame.get_by_role("button", name="创建账单", exact=True).count():
                    self.frame = frame
                    return
            except Exception:
                continue
        # 切换页签后业务 iframe 可能已挂载但按钮尚未渲染；其业务路由
        # 仍是稳定信号，避免回退到 iframe.last（可能是减免管理）。
        for frame in reversed(self.page.frames):
            if frame == self.page.main_frame or "BillingCenter" not in frame.url:
                continue
            self.frame = frame
            return

    def wait_until_table_readable(self) -> None:
        """只读恢复场景允许表格可读但初始化遮罩尚未完全消失。"""
        self._resolve_business_frame()
        expect(
            self.frame.locator(".el-table__body-wrapper")
        ).to_be_visible(timeout=60_000)

    def select_project(self, project_name: str) -> None:
        # The project selector is rendered before the initial bill query
        # finishes on the server.  It is visible but not interactable while
        # the mask intercepts pointer events.
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        # Do not search for a generic readonly input across the whole frame:
        # the advanced-search drawer has its own readonly object selectors,
        # so a persisted drawer can make that locator ambiguous on later cases.
        project_selector = self.require_single(
            self.frame.locator(".jie-project:visible"), "项目选择框"
        )
        project_input = self.require_single(
            project_selector.locator("input[readonly]"), "项目选择输入框"
        )
        current_project_label = project_selector.locator("span.textOverflow")
        current_target = current_project_label.filter(
            has_text=re.compile(rf"^{re.escape(project_name)}$")
        )
        if current_target.count() >= 1:
            return

        click_error = None
        for _ in range(3):
            try:
                expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
                    0, timeout=60_000
                )
                project_selector.click()
                click_error = None
                break
            except PlaywrightError as exc:
                click_error = exc
                self.page.wait_for_timeout(1_000)
        if click_error is not None:
            raise click_error
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
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
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
        target = self.require_single(
            panel.get_by_text(month_names[month], exact=True),
            f"账期月份选项 {month_names[month]}",
        )
        expect(target).to_be_visible(timeout=10_000)
        # The portal's floating customer-service/App-download panel can open
        # asynchronously after navigation and physically cover the picker.
        # Collapse that known outer-page overlay before clicking the exact
        # month cell; do not force-click through it.
        from src.pages.portal_page import PortalPage

        PortalPage(self.page).collapse_customer_service()
        # A floating App-download widget can still geometrically overlap the
        # picker cell while remaining outside the picker DOM. The exact visible
        # month anchor is a non-financial filter control, so dispatch its own
        # click only after strict uniqueness/visibility checks.
        target.evaluate("element => element.click()")
        expect(month_input).to_have_value(billing_month, timeout=10_000)
        # The picker closes itself after the month cell is selected; wait for
        # its transition to finish before opening the next field. Sending
        # Escape during that transition can close the whole advanced drawer.
        open_panels = self.frame.locator(".el-picker-panel:visible")
        expect(open_panels).to_have_count(0, timeout=5_000)

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
        try:
            visible_add_buttons[0].click()
        except PlaywrightError as exc:
            # On the long creation drawer a teleported popover reference can
            # overlap this exact button even though the button is visible and
            # enabled.  Use its native click only for that verified hit-test
            # interception; other click failures still propagate unchanged.
            if "intercepts pointer events" not in str(exc):
                raise
            visible_add_buttons[0].evaluate("element => element.click()")

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
        # The server can render both inputs before the available tree arrives.
        # Filtering that empty snapshot leaves only collapsed fee categories.
        available_tree = picker.locator('.room-tree .el-tree')
        expect(available_tree.locator('.el-tree-node__content').first).to_be_visible(
            timeout=30_000
        )
        search = search_inputs.first
        search.fill(charge_item)
        # The redesigned dual-pane picker filters on the input event.  Enter
        # is not a search action here and can submit/reset the left tree,
        # leaving no selectable result.
        expect(picker.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=30_000
        )
        self.page.wait_for_timeout(500)
        collapsed_icons = available_tree.locator(
            ".el-tree-node:not(.is-expanded) > .el-tree-node__content > "
            ".el-tree-node__expand-icon:not(.is-leaf):visible"
        )
        for index in range(collapsed_icons.count()):
            collapsed_icons.nth(index).click()
            self.page.wait_for_timeout(200)

        item_texts = available_tree.get_by_text(charge_item, exact=True)
        # The charge-item tree is populated asynchronously after the drawer
        # opens.  Wait for the filtered item to actually render instead of
        # sampling the list immediately (which can briefly show “暂无数据”).
        item_error = None
        for attempt in range(3):
            try:
                expect(item_texts.first).to_be_visible(timeout=5_000)
                item_error = None
                break
            except AssertionError as exc:
                item_error = exc
                if attempt == 2:
                    break
                # Replay only the filter after asynchronous tree replacement.
                search.fill('')
                search.fill(charge_item)
                for _ in range(4):
                    if not collapsed_icons.count():
                        break
                    collapsed_icons.first.click()
                    self.page.wait_for_timeout(200)
        if item_error is not None:
            raise AssertionError(
                f"收费项筛选后未展示目标 {charge_item!r}；"
                f"收费项抽屉文本={picker.inner_text()!r}"
            ) from item_error
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
        submit_responses: list[dict[str, str | int]] = []

        def capture_submit(response: Response) -> None:
            request = response.request
            if request.method != "POST":
                return
            path = urlsplit(response.url).path
            if "bill" not in path.lower():
                return
            try:
                body = response.text()[:2000]
            except Exception:
                body = "<unavailable>"
            submit_responses.append(
                {
                    "status": response.status,
                    "path": path,
                    "request": (request.post_data or "")[:3000],
                    "body": body,
                }
            )

        self.page.on("response", capture_submit)
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
            errors = [
                message for message in messages
                if not re.search(r"创建成功|账单成功数|成功，是否进行账单通知", message)
            ]
            if errors:
                self.page.remove_listener("response", capture_submit)
                raise AssertionError(
                    "提交创建账单时页面返回错误："
                    + "；".join(errors)
                    + f"；提交响应={submit_responses[-5:]}"
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
        self.page.remove_listener("response", capture_submit)
        no_notification = result_dialog.get_by_role(
            "button", name="不需要", exact=True
        )
        expect(no_notification).to_be_visible(timeout=15_000)
        no_notification.click()

        expect(result_dialog).to_be_hidden(timeout=30_000)
        expect(dialog).to_be_hidden(timeout=30_000)
        # Creation refreshes the list but may preserve a previous case's
        # advanced-search filters. Reapply the complete business key before
        # reading the new row; the separate associated-object field remains
        # intentionally unset.
        matching_numbers = self.get_bill_numbers_by_month_room_charge_item(
            billing_month=data.billing_month,
            room_path=data.room_path,
            charge_item=data.charge_item,
        )
        if len(matching_numbers) != 1:
            raise AssertionError(
                "账单创建成功后，按账期+房间+收费项应唯一命中本次账单；"
                f"实际编号={matching_numbers!r}。"
            )
        row = self._find_main_table_row(
            bill_number=matching_numbers[0],
        )
        expect(row).to_be_visible(timeout=30_000)

        row_candidates = [row.nth(index) for index in range(row.count())]
        if not row_candidates:
            raise AssertionError("创建成功后未定位到账单业务行。")
        main_row = max(
            row_candidates, key=lambda candidate: candidate.locator("td").count()
        )
        bill_row_text = main_row.inner_text()

        bill_number_candidates = {
            text.strip()
            for text in main_row.locator("td").all_inner_texts()
            if re.fullmatch(r"ZD[A-Z0-9]+", text.strip())
        }
        if bill_number_candidates != {matching_numbers[0]}:
            raise AssertionError(
                "账单业务行中的编号单元格与完整业务键查询结果不一致；"
                f"查询编号={matching_numbers[0]!r}，行内编号={sorted(bill_number_candidates)!r}。"
            )
        bill_number = matching_numbers[0]

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

    def find_unique_bill_by_month_room_charge_item(
        self, *, billing_month: str, room_path: str, charge_item: str
    ) -> Locator:
        """按账期+房间+收费项唯一定位账单行，供专项减免核对使用。"""
        self._filter_billing_month(billing_month)
        rows = self._find_main_table_row(
            room_path=room_path,
            charge_item=charge_item,
        )
        visible = [rows.nth(i) for i in range(rows.count()) if rows.nth(i).is_visible()]
        if len(visible) != 1:
            raise AssertionError(
                "账单减免核对要求账期+房间+收费项唯一命中，"
                f"实际可见行数={len(visible)}。"
            )
        return visible[0]

    def assert_row_amounts(
        self,
        row: Locator,
        *,
        expected_original: Decimal,
        expected_discount: Decimal,
        expected_receivable: Decimal,
    ) -> None:
        actual = self._read_bill_amounts(row)
        expected = {
            "original_amount": expected_original,
            "discount_amount": expected_discount,
            "receivable_amount": expected_receivable,
        }
        if actual != expected:
            raise AssertionError(
                "账单减免后的金额断言失败："
                f"期望={expected}，实际={actual}，行文本={row.inner_text()!r}"
            )

    def bill_number_from_row(self, row: Locator) -> str:
        cell = self.require_single(
            row.locator('td[class*="_column_25"]'), "账单编号单元格"
        )
        value = cell.inner_text().strip()
        if not value:
            raise AssertionError("账单行中未读取到账单编号。")
        return value

    def cleanup_bill(
        self,
        bill_number: str,
        void_reason: str,
        billing_month: str | None = None,
    ) -> None:
        row = self._find_bill_row_any(bill_number)
        if row.count() == 0 and billing_month:
            # A locator can briefly report zero while the table re-renders
            # after the preceding search; retry the current result first.
            self.page.wait_for_timeout(1_000)
            row = self._find_bill_row_any(bill_number)
        if row.count() == 0 and billing_month:
            self._filter_billing_month(billing_month)
            # The list refresh is asynchronous; do not query the virtualized
            # table while its loading mask is still mounted.
            expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
                0, timeout=60_000
            )
            self.page.wait_for_timeout(1_000)
            row = self._find_bill_row_any(bill_number)
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
            try:
                expect(self._find_bill_row_any(bill_number)).to_contain_text(
                    "已作废", timeout=30_000
                )
            except AssertionError:
                # The void request can succeed while the virtualized list
                # keeps the old row snapshot.  Re-query the exact business
                # month before deciding that voiding failed.
                if billing_month:
                    self.page.wait_for_timeout(1_000)
                    self._filter_billing_month(billing_month)
                refreshed = self._find_bill_row_any(bill_number)
                expect(refreshed).to_contain_text("已作废", timeout=30_000)

        self._select_only_result_row(bill_number)
        self._open_more_action("批量删除")

        delete_prompt = self.frame.get_by_text(
            re.compile(r"(?:删除后.*不可恢复|不可恢复.*删除|确定删除)")
        )
        try:
            expect(delete_prompt).to_be_visible(timeout=5_000)
        except AssertionError:
            # The action menu can remain mounted after a text-node click in
            # some portal builds. Click the actual menu button once, then wait
            # for the confirmation UI instead of assuming the first click
            # invoked the delete action.
            action_buttons = self.frame.get_by_role(
                "button", name="批量删除", exact=True
            )
            visible_buttons = [
                action_buttons.nth(index)
                for index in range(action_buttons.count())
                if action_buttons.nth(index).is_visible()
            ]
            if len(visible_buttons) == 1:
                # The floating customer-service widget can intercept the
                # pointer even when it is not marked `.open`; this is a
                # destructive action only after the exact business-key row
                # was selected above. Use the button's click handler directly
                # for the same reason as `_open_more_action`: the overlay may
                # intercept another forced pointer click as well.
                visible_buttons[0].evaluate("element => element.click()")
            expect(delete_prompt).to_be_visible(timeout=15_000)
        delete_panel = delete_prompt.locator("xpath=ancestor::*[.//button][1]")
        delete_confirm = delete_panel.get_by_text("确定", exact=True)
        self.require_single(delete_confirm, "批量删除确认按钮").click()
        expect(self._find_bill_row_any(bill_number)).to_have_count(
            0, timeout=30_000
        )

    def _find_bill_row_any(self, bill_number: str) -> Locator:
        """Find a bill row even when the current build splits fixed columns.

        Some Element UI builds keep the bill-number cell in a fixed wrapper;
        the normal body wrapper then has no text match although the record is
        present.  Restrict the fallback to the exact generated number.
        """
        rows = self._find_main_table_row(bill_number=bill_number)
        if rows.count() == 0:
            rows = self.frame.locator("tr:visible").filter(has_text=bill_number)
        return rows

    def _select_only_result_row(self, bill_number: str | None = None) -> None:
        if bill_number:
            rows = self._find_bill_row_any(bill_number)
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
        action_buttons = self.frame.get_by_role(
            "button", name=action, exact=True
        )
        visible_actions = [
            action_buttons.nth(index)
            for index in range(action_buttons.count())
            if action_buttons.nth(index).is_visible()
        ]
        if len(visible_actions) != 1:
            raise AssertionError(
                f"更多菜单中的 {action} 应唯一可见，实际可见 "
                f"{len(visible_actions)} 个。"
            )
        # The app-download/customer-service float can overlay the toolbar
        # area while the tooltip menu remains visible. A forced mouse click
        # then lands on that overlay and leaves the menu unchanged. Dispatch
        # the click on the exact, uniquely visible menu button itself.
        visible_actions[0].evaluate("element => element.click()")

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
        self._search_advanced_business_key(
            billing_month=billing_month,
            room_path=room_path,
            charge_item=charge_item,
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
        allow_empty: bool = False,
    ) -> list[str]:
        """Return every active matching bill number for duplicate cleanup."""
        self._search_advanced_business_key(
            billing_month=billing_month,
            room_path=room_path,
            charge_item=charge_item,
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
            if (
                billing_month not in text
                or "已作废" in text
                or (normalized and normalized not in text)
            ):
                continue
            match = re.search(r"ZD[A-Z0-9]+", text)
            if match:
                numbers.append(match.group(0))
        if not numbers:
            Path("artifacts").mkdir(exist_ok=True)
            Path("artifacts/billing-center-room-filter.txt").write_text(
                self.frame.locator("body").inner_text(), encoding="utf-8"
            )
            if allow_empty:
                return []
            raise AssertionError("账单中心未找到活动的目标账单")
        return numbers

    def get_bill_numbers_by_month_room_charge_item(
        self, *, billing_month: str, room_path: str, charge_item: str,
        allow_empty: bool = False, include_voided: bool = False,
    ) -> list[str]:
        """Resolve active Bill Center rows without relying on advanced room tree."""
        # Approval and Bill Center list refresh are eventually consistent.  A
        # single search can therefore return an empty table even though the
        # approved bill is already committed.  Re-submit the same business-key
        # query a few times before declaring the bill missing.
        last_body = ""
        for attempt in range(1, 4):
            self._search_advanced_business_key(
                billing_month=billing_month,
                room_path=room_path,
                charge_item=charge_item,
            )
            rows = self._find_main_table_row(
                room_path=room_path, charge_item=charge_item
            )
            numbers: list[str] = []
            for index in range(rows.count()):
                row = rows.nth(index)
                if not row.is_visible():
                    continue
                text = row.inner_text()
                if "已作废" in text and not include_voided:
                    continue
                match = re.search(r"ZD[A-Z0-9]+", text)
                if match:
                    numbers.append(match.group(0))
            if numbers:
                return list(dict.fromkeys(numbers))
            last_body = self.frame.locator("body").inner_text()
            if attempt < 3:
                self.page.wait_for_timeout(2_000)
        if allow_empty:
            return []
        Path("artifacts").mkdir(exist_ok=True)
        safe_room = re.sub(r"[^A-Za-z0-9_-]+", "-", room_path)
        safe_item = re.sub(r"[^A-Za-z0-9_-]+", "-", charge_item)
        artifact = Path(
            f"artifacts/billing-center-room-charge-miss-{safe_room}-"
            f"{safe_item}-{billing_month}.txt"
        )
        artifact.write_text(
            "\n".join(
                (
                    f"billing_month={billing_month}",
                    f"room_path={room_path}",
                    f"charge_item={charge_item}",
                    "query_attempts=3",
                    "--- visible page body ---",
                    last_body,
                )
            ),
            encoding="utf-8",
        )
        raise AssertionError(
            "账单中心未找到指定账期、房间和收费项的有效账单；"
            f"已完成3次查询并保存页面证据 {artifact.as_posix()}"
        )

    def cleanup_by_month_room_charge_item(
        self, *, billing_month: str, room_path: str, charge_item: str,
        void_reason: str,
    ) -> list[str]:
        """Void/delete every active bill matching the business key.

        The business key, not a bill number, is the cleanup entry point. Any
        captured numbers are used only internally after the exact query.
        """
        numbers = self.get_bill_numbers_by_month_room_charge_item(
            billing_month=billing_month, room_path=room_path, charge_item=charge_item,
            include_voided=True,
        )
        for number in reversed(dict.fromkeys(numbers)):
            self.cleanup_bill(number, void_reason, billing_month)
        remaining = self.get_bill_numbers_by_month_room_charge_item(
            billing_month=billing_month,
            room_path=room_path,
            charge_item=charge_item,
            allow_empty=True,
            include_voided=True,
        )
        if remaining:
            raise AssertionError(
                "账单中心清理后，相同账期+房间+收费项仍命中有效账单："
                + ", ".join(remaining)
            )
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

    def _select_advanced_room(
        self, drawer: Locator, room_path: str, billing_month: str
    ) -> None:
        # 云收费新列表将房间筛选合并到“收费对象”。先选择对象类型，
        # 再使用右侧房间树；不要混用下方独立的“关联对象”筛选。
        new_object_filter = drawer.get_by_text("收费对象", exact=True).count() == 1
        if new_object_filter:
            selectors = drawer.locator('input[readonly][placeholder="请选择"]:visible')
            object_selectors = [
                selectors.nth(i) for i in range(selectors.count())
                if selectors.nth(i).input_value().startswith("收费对象-")
            ]
            if len(object_selectors) != 1:
                raise AssertionError(
                    f"高级搜索收费对象类型控件应唯一，实际 {len(object_selectors)} 个。"
                )
            object_selector = object_selectors[0]
            room_filter = object_selector.locator(
                "xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' jie-dialog-label ')][1]"
            )
            if object_selector.input_value() != "收费对象-房间":
                object_select = self.require_single(
                    object_selector.locator(
                        "xpath=ancestor::*[contains(@class,'el-select')][1]"
                    ),
                    "收费对象类型下拉框",
                )
                expect(object_select).to_be_visible(timeout=10_000)
                object_select.click()
                room_option = self.frame.locator(
                    ".el-select-dropdown:visible .el-select-dropdown__item"
                ).filter(has_text=re.compile(r"^收费对象-房间$"))
                expect(room_option).to_have_count(1, timeout=10_000)
                room_option.click()
                expect(object_selector).to_have_value("收费对象-房间")
        # Some deployments default the bill-object selector to 全部; the
        # adjacent room field is not active until that selector is 房间.
        all_object = drawer.get_by_text(
            re.compile(r"账单对象\s*[-:]\s*全部"), exact=False
        )
        visible_all = [
            all_object.nth(index)
            for index in range(all_object.count())
            if all_object.nth(index).is_visible()
        ]
        if len(visible_all) > 1:
            raise AssertionError("账单对象-全部切换控件不唯一，停止房间检索。")
        if visible_all:
            visible_all[0].hover(force=True)
            visible_all[0].click(force=True)
            room_option = self.frame.locator(
                ".el-dropdown-menu:visible .el-dropdown-menu__item"
            ).filter(has_text=re.compile(r"^房间$"))
            expect(room_option).to_have_count(1, timeout=10_000)
            room_option.click(force=True)
        if not new_object_filter:
            room_label = self.require_single(
                drawer.get_by_text("房间名称", exact=True), "高级搜索房间名称标签"
            )
            room_filter = room_label.locator(
                "xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' jie-dialog-label ')][1]"
            )
        parts = [part for part in room_path.split("/") if part]
        if not parts:
            raise ValueError(f"房间路径不能为空：{room_path!r}")
        room_field = self.require_single(room_filter, "高级搜索房间筛选字段")
        room_content = self.require_single(
            room_field.locator(".jie-content"), "高级搜索房间筛选内容"
        )
        # After an advanced-search query, Element UI may retain the selected
        # room tag and hide/disable its editable input. Reuse an exact existing
        # room condition instead of failing on a missing editor or reopening
        # the tree unnecessarily.
        existing_room_tags = room_content.locator(".tags-info .el-tag:visible")
        existing_room_texts: list[str] = []
        for index in range(existing_room_tags.count()):
            tag = existing_room_tags.nth(index)
            content = tag.locator(".el-tag__content")
            text = content.inner_text() if content.count() == 1 else tag.inner_text()
            existing_room_texts.append(" ".join(text.split()))
        if len(existing_room_texts) == 1 and existing_room_texts[0] in {
            parts[-1],
            room_path,
        }:
            return
        for index in reversed(range(existing_room_tags.count())):
            tag = existing_room_tags.nth(index)
            close = tag.locator(".el-tag__close")
            if close.count() != 1:
                raise AssertionError(
                    "房间筛选保留了其他房间，但没有唯一移除按钮；"
                    f"现有标签={existing_room_texts!r}。"
                )
            close.click(force=True)
        inputs = room_content.locator(
            '.select-input input[placeholder="请选择"]:visible'
            ':not([readonly]):not([disabled])'
        )
        if inputs.count() != 1:
            raise AssertionError(
                "高级搜索房间名称右侧可编辑‘请选择’输入框应唯一，"
                f"实际 {inputs.count()} 个。"
            )
        # Advanced Search persists previously selected rooms across queries.
        # Its compact tag view shows only the first room plus a count (e.g.
        # "1006 +4").  Remove tags from this room field before selecting the
        # next exact room, without touching the month or charge-item filters.
        for _ in range(60):
            previous_tags = room_field.locator(".tags-info .el-tag")
            if previous_tags.count() == 0:
                break
            close = room_field.locator(".tags-info .el-tag__close")
            if close.count() == 0:
                raise AssertionError("房间筛选保留旧房间标签，但没有可用的移除按钮。")
            close.first.click(force=True)
        else:
            raise AssertionError("房间筛选旧标签超过60个，停止清空以免误操作。")
        expect(room_field.locator(".tags-info .el-tag")).to_have_count(0)
        # The adjacent readonly control selects the mode; this editable field
        # opens the room tree.  On this Bill Center build, typing the leaf
        # before expanding A栋 suppresses lazy-loaded descendants, so expand
        # only the known path first instead of filtering an unloaded tree.
        room_input = inputs.first
        # A previous advanced-search query can leave its leaf filter in this
        # input.  Clear that token before loading the known ancestor path.
        # The room tree is lazily loaded per bill-center project; on this
        # build the first popper open occasionally renders an empty
        # "暂无数据" tree when the lazy request loses the race with the
        # popper transition.  Dismiss and reopen the popper a few times so a
        # transient empty tree does not abort the whole case.
        tree = self.frame.locator(".el-tree:visible")
        tree_error: Exception | None = None
        for tree_attempt in range(1, 4):
            room_input.click(force=True)
            room_input.fill("")
            try:
                expect(tree).to_have_count(1, timeout=20_000)
                expect(tree.locator(".el-tree-node__content").first).to_be_visible(
                    timeout=20_000
                )
                break
            except AssertionError as exc:
                tree_error = exc
                if tree_attempt == 3:
                    labels = tree.locator(".el-tree-node__content").all_inner_texts()
                    raise AssertionError(
                        "高级搜索房间树连续 3 次打开均为空/不可见；"
                        f"可见节点数={len(labels)}，目标={room_path!r}"
                    ) from tree_error
                # Clicking the filter block itself lands outside the popper
                # and dismisses it, which re-triggers the lazy room request
                # on the next open.
                room_field.click(force=True)
                self.page.wait_for_timeout(800)
        for index, part in enumerate(parts[:-1]):
            ancestor = tree.get_by_text(part, exact=True)
            expect(ancestor).to_have_count(1, timeout=20_000)
            node = ancestor.locator(
                "xpath=ancestor::*[contains(@class,'el-tree-node')][1]"
            )
            expand = node.locator(".el-tree-node__expand-icon")
            if expand.count() == 1 and "expanded" not in (
                expand.get_attribute("class") or ""
            ):
                expand.click(force=True)
            # Element UI inserts each child level asynchronously.  Do not
            # continue to the next path segment merely because the parent
            # caret has flipped to expanded.
            child = tree.get_by_text(parts[index + 1], exact=True)
            try:
                expect(child).to_have_count(1, timeout=8_000)
            except AssertionError as exc:
                # The caret may say expanded before the lazy child request
                # has populated any nodes.  Reopen this single known branch
                # once, then fail with a compact tree snapshot if still empty.
                if child.count() == 0 and expand.count() == 1:
                    if "expanded" in (expand.get_attribute("class") or ""):
                        expand.click(force=True)
                    expand.click(force=True)
                try:
                    expect(child).to_have_count(1, timeout=20_000)
                except AssertionError as retry_exc:
                    labels = tree.locator(".el-tree-node__content").all_inner_texts()
                    raise AssertionError(
                        f"房间树展开 {part!r} 后未加载 {parts[index + 1]!r}；"
                        f"可见节点数={len(labels)}，前30个={labels[:30]!r}"
                    ) from retry_exc
        leaf = tree.get_by_text(parts[-1], exact=True)
        expect(leaf).to_have_count(1, timeout=20_000)
        node_content = self.require_single(
            leaf.locator(
                "xpath=ancestor::*[contains(@class,'el-tree-node__content')][1]"
            ),
            "高级搜索目标房间树节点",
        )
        checkbox = self.require_single(
            node_content.locator(".el-checkbox__inner:visible"),
            "高级搜索目标房间勾选框",
        )
        checkbox_state = node_content.locator(".el-checkbox__input")
        self.require_single(checkbox_state, "高级搜索目标房间勾选状态")
        # The room tags and the lazily-rendered tree can get out of sync after
        # a previous advanced-search query.  Clearing a tag alone does not
        # always reset the tree's checked leaf, so remove any other checked
        # room leaves before selecting the target.  Only numeric room leaves
        # are touched; building/floor parent checkboxes are left alone.
        for _ in range(60):
            checked_room_rows = tree.locator(
                ".el-tree-node__content:visible:has(.el-checkbox__input.is-checked)"
            )
            stale_row = None
            stale_text = ""
            for index in range(checked_room_rows.count()):
                candidate = checked_room_rows.nth(index)
                candidate_text = " ".join(candidate.inner_text().split())
                room_tokens = re.findall(r"(?<!\d)\d{3,5}(?!\d)", candidate_text)
                if room_tokens and room_tokens[-1] != parts[-1]:
                    stale_row, stale_text = candidate, candidate_text
                    break
            if stale_row is None:
                break
            checked_state = stale_row.locator(".el-checkbox__input.is-checked")
            checked_box = stale_row.locator(".el-checkbox__inner")
            if checked_state.count() != 1 or checked_box.count() != 1:
                raise AssertionError(
                    "高级搜索房间树存在旧的已勾选房间，但无法唯一取消；"
                    f"目标={room_path!r}，旧节点={stale_text!r}。"
                )
            checked_box.click(force=True)
            expect(stale_row.locator(".el-checkbox__input")).not_to_have_class(
                re.compile(r"\bis-checked\b"), timeout=5_000
            )
        else:
            raise AssertionError(
                f"高级搜索房间树旧房间选择超过60项，停止；目标={room_path!r}。"
            )

        # Make the target selection idempotent: never toggle an already
        # checked target off.
        is_checked = checkbox_state.evaluate(
            "element => element.classList.contains('is-checked')"
        )
        if not is_checked:
            checkbox.click(force=True)
        expect(checkbox_state).to_have_class(re.compile(r"\bis-checked\b"))
        panel = tree.locator("xpath=ancestor::*[.//button][1]")
        confirm = panel.get_by_text("确定", exact=True)
        confirm = self.require_single(confirm, "高级搜索房间确认按钮")
        # A fully expanded floor can contain >100 rooms and push the popover
        # footer outside the viewport.  The unique button remains valid, but
        # Playwright's pointer click cannot reach it; dispatch its native
        # button click after the exact room checkbox is selected.
        confirm.evaluate("element => element.closest('button').click()")
        selected_tags = room_field.locator(".tags-info .el-tag")
        try:
            expect(selected_tags).to_have_count(1, timeout=15_000)
        except AssertionError as exc:
            checked_nodes = tree.locator(
                ".el-tree-node.is-checked .el-tree-node__content"
            ).all_inner_texts()
            raise AssertionError(
                "房间树确认后没有唯一房间标签；"
                f"目标={room_path!r}，输入值={room_input.input_value()!r}，"
                f"房间筛选文本={room_field.inner_text()!r}，"
                f"已勾选树节点={checked_nodes[:20]!r}。"
            ) from exc
        tag_content = selected_tags.first.locator(".el-tag__content")
        selected_room = (
            tag_content.inner_text()
            if tag_content.count() == 1
            else selected_tags.first.inner_text()
        )
        selected_room = " ".join(selected_room.split())
        if selected_room not in {parts[-1], room_path}:
            Path("artifacts").mkdir(exist_ok=True)
            safe_room = re.sub(r"[^A-Za-z0-9_-]+", "-", parts[-1])
            artifact = Path(
                f"artifacts/billing-center-room-filter-{safe_room}-{billing_month}.txt"
            )
            artifact.write_text(
                "\n".join(
                    (
                        f"target={room_path}",
                        f"selected={selected_room}",
                        f"room_field={room_field.inner_text()}",
                        f"checked_nodes={tree.locator('.el-tree-node.is-checked .el-tree-node__content').all_inner_texts()!r}",
                        f"drawer={drawer.inner_text()}",
                    )
                ),
                encoding="utf-8",
            )
            raise AssertionError(
                "账单中心高级搜索确认的房间与目标房间不一致；"
                f"目标={room_path!r}，实际={selected_room!r}，证据={artifact.as_posix()}"
            )

    def _set_advanced_billing_month(
        self, drawer: Locator, billing_month: str
    ) -> Locator:
        # The drawer contains two date ranges (billing period first, creation
        # time later), and both reuse the same placeholders.  Keep the first
        # range in DOM order: on the verified layout this is the billing
        # period shown at the top of Advanced Search.
        starts = drawer.get_by_placeholder("选择开始日期")
        ends = drawer.get_by_placeholder("选择结束日期")
        if starts.count() < 1 or ends.count() < 1:
            raise AssertionError(
                "账单中心高级搜索缺少账期起止日期输入框，"
                f"开始数={starts.count()}，结束数={ends.count()}。"
            )
        def visible_field(locator: Locator, label: str) -> Locator:
            for _ in range(20):
                visible = [
                    locator.nth(index)
                    for index in range(locator.count())
                    if locator.nth(index).is_visible()
                ]
                if visible:
                    return visible[0]
                self.page.wait_for_timeout(250)
            raise AssertionError(
                f"高级搜索{label}日期控件未变为可见；"
                f"候选数={locator.count()}，抽屉可见={drawer.is_visible()}。"
            )

        start = visible_field(starts, "开始")
        end = visible_field(ends, "结束")
        # These are Element UI month-picker inputs. Filling text alone leaves
        # the internal picker model unchanged and may leave its popper open;
        # use the same verified month-cell interaction as bill creation.
        self._select_billing_month(start, billing_month)
        self._select_billing_month(end, billing_month)
        expect(start).to_have_value(billing_month)
        expect(end).to_have_value(billing_month)
        expect(
            self.frame.locator(".el-picker-panel:visible")
        ).to_have_count(0, timeout=5_000)
        expect(drawer).to_be_visible(timeout=10_000)
        return drawer

    def _select_advanced_charge_item(
        self, drawer: Locator, charge_item: str
    ) -> None:
        fields = drawer.locator(".jie-dialog-label").filter(
            has_text=re.compile(r"^收费项")
        )
        field = self.require_single(fields, "账单中心高级搜索收费项字段")
        select = self.require_single(
            field.locator(".el-select"), "账单中心高级搜索收费项多选框"
        )
        selected_tag_nodes = select.locator(".el-tag:visible")
        selected_values = [
            " ".join(
                (
                    tag.locator(".el-tag__content").inner_text()
                    if tag.locator(".el-tag__content").count() == 1
                    else tag.inner_text()
                ).split()
            )
            for tag in [
                selected_tag_nodes.nth(i)
                for i in range(selected_tag_nodes.count())
            ]
        ]
        if selected_values == [charge_item]:
            return
        # Advanced Search can preserve the prior multi-select across serial
        # queries. Adding the next fee item without removing the old tag makes
        # the query key broader/ambiguous and can yield zero or wrong rows.
        # Normalize this criterion to exactly the requested fee item.
        for index in reversed(range(selected_tag_nodes.count())):
            tag = selected_tag_nodes.nth(index)
            close = tag.locator(".el-tag__close")
            if close.count() != 1:
                raise AssertionError(
                    "高级搜索收费项保留了旧条件，但没有唯一移除按钮；"
                    f"当前收费项={selected_values!r}，目标={charge_item!r}"
                )
            close.click(force=True)
        expect(select.locator(".el-tag:visible")).to_have_count(0, timeout=10_000)
        # This is a multi-select with an inner filter input. Clicking its
        # readonly display input is intercepted by that child input, so open
        # the dropdown through the actual filter control.
        filter_input = select.locator("input.el-select__input")
        self.require_single(filter_input, "收费项多选筛选输入框").click()
        dropdown = self.frame.locator(".el-select-dropdown:visible").last
        expect(dropdown).to_be_visible(timeout=10_000)
        option = dropdown.locator(
            ".el-select-dropdown__item"
        ).filter(has_text=re.compile(rf"^{re.escape(charge_item)}$"))
        expect(option).to_have_count(1, timeout=15_000)
        option.click()
        option_class = option.get_attribute("class") or ""
        option_aria_selected = option.get_attribute("aria-selected") or ""
        option_checkbox = option.locator(".el-checkbox")
        checkbox_class = (
            option_checkbox.get_attribute("class") or ""
            if option_checkbox.count()
            else ""
        )
        selected_tags = select.locator(".el-tag__content:visible")
        tags = [text.strip() for text in selected_tags.all_inner_texts()]
        values = field.locator("input").evaluate_all(
            "els => els.map(input => input.value.trim())"
        )
        selected_in_dropdown = (
            "selected" in option_class.split()
            or "is-selected" in option_class.split()
            or option_aria_selected.lower() == "true"
            or "is-checked" in checkbox_class.split()
        )
        if not selected_in_dropdown and charge_item not in tags and charge_item not in values:
            raise AssertionError(
                "收费项选项点击后未回显目标值；"
                f"目标={charge_item!r}，标签={tags!r}，输入值={values!r}，"
                f"下拉选项class={option_class!r}，aria-selected={option_aria_selected!r}，"
                f"checkbox class={checkbox_class!r}，字段文本={field.inner_text()!r}。"
            )
        final_tags = [
            " ".join(text.split())
            for text in select.locator(".el-tag__content:visible").all_inner_texts()
            if text.strip()
        ]
        if final_tags and final_tags != [charge_item]:
            raise AssertionError(
                "高级搜索收费项未规范为唯一目标条件；"
                f"目标={charge_item!r}，实际标签={final_tags!r}"
            )
        if not final_tags and charge_item not in values and not selected_in_dropdown:
            raise AssertionError(
                "高级搜索收费项点击后没有可验证的选中状态；"
                f"目标={charge_item!r}，输入值={values!r}，"
                f"下拉选中状态={selected_in_dropdown}，字段={field.inner_text()!r}"
            )

    def _search_advanced_business_key(
        self, *, billing_month: str, room_path: str, charge_item: str | None
    ) -> None:
        visible_drawers = self.frame.locator(".el-drawer:visible").filter(
            has_text="高级搜索"
        )
        if visible_drawers.count() > 1:
            raise AssertionError(
                f"账单中心可见高级搜索抽屉应唯一，实际 {visible_drawers.count()} 个。"
            )
        # Reuse an already-open advanced-search panel.  Re-running the top
        # search while this drawer is open matches two Search buttons and can
        # leave stale room conditions active between serial parameter cases.
        drawer = (
            visible_drawers.first
            if visible_drawers.count() == 1
            else self._open_advanced_search()
        )
        # The Bill Center room tree can remain empty when opened after the
        # charge-item and month widgets have been changed. Select the room
        # first, then set the month and charge item; finally re-check that all
        # three conditions survived the component refreshes. The separate
        # “关联对象” condition is intentionally untouched.
        self._select_advanced_room(drawer, room_path, billing_month)
        drawer = self._set_advanced_billing_month(drawer, billing_month)
        if charge_item:
            self._select_advanced_charge_item(drawer, charge_item)
        self._verify_advanced_business_key(
            drawer,
            billing_month=billing_month,
            room_path=room_path,
            charge_item=charge_item,
        )
        expect(drawer).to_be_visible(timeout=10_000)
        search_button = self.require_single(
            drawer.get_by_role("button", name="搜索", exact=True),
            "账单中心高级搜索提交按钮",
        )
        expect(search_button).to_be_visible(timeout=10_000)
        expect(search_button).to_be_enabled(timeout=10_000)
        from src.pages.portal_page import PortalPage

        PortalPage(self.page).collapse_customer_service()
        try:
            search_button.click(timeout=5_000)
        except PlaywrightError as exc:
            if "intercepts pointer events" not in str(exc):
                raise
            # The search is a read-only filter action. Dispatch the click on
            # the exact, unique enabled button only when a floating portal
            # widget has been proven to intercept the pointer.
            search_button.evaluate("element => element.click()")
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )

    def _verify_advanced_business_key(
        self,
        drawer: Locator,
        *,
        billing_month: str,
        room_path: str,
        charge_item: str | None,
    ) -> None:
        """Fail closed if a cascading filter refresh drops a business key."""
        starts = drawer.get_by_placeholder("选择开始日期")
        ends = drawer.get_by_placeholder("选择结束日期")
        if not starts.count() or not ends.count():
            raise AssertionError("高级搜索账期起止控件在筛选联动后消失。")
        expect(starts.first).to_have_value(billing_month)
        expect(ends.first).to_have_value(billing_month)

        parts = [part for part in room_path.split("/") if part]
        if not parts:
            raise ValueError(f"房间路径不能为空：{room_path!r}")
        object_selectors = drawer.locator(
            'input[readonly][placeholder="请选择"]:visible'
        )
        room_filter = None
        for index in range(object_selectors.count()):
            candidate = object_selectors.nth(index)
            if candidate.input_value().startswith("收费对象-"):
                room_filter = candidate.locator(
                    "xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' jie-dialog-label ')][1]"
                )
                break
        if room_filter is None:
            room_label = self.require_single(
                drawer.get_by_text("房间名称", exact=True),
                "高级搜索房间名称标签（联动复核）",
            )
            room_filter = room_label.locator(
                "xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' jie-dialog-label ')][1]"
            )
        selected_rooms = room_filter.locator(".tags-info .el-tag:visible")
        room_values: list[str] = []
        for index in range(selected_rooms.count()):
            tag = selected_rooms.nth(index)
            content = tag.locator(".el-tag__content")
            text = content.inner_text() if content.count() == 1 else tag.inner_text()
            room_values.append(" ".join(text.split()))
        if room_values not in ([parts[-1]], [room_path]):
            raise AssertionError(
                "高级搜索筛选联动后房间条件未保留或不唯一；"
                f"目标={room_path!r}，实际={room_values!r}。"
            )

        if charge_item:
            fields = drawer.locator(".jie-dialog-label").filter(
                has_text=re.compile(r"^收费项")
            )
            field = self.require_single(fields, "高级搜索收费项字段（联动复核）")
            tags = field.locator(".el-tag__content").all_inner_texts()
            tags = [" ".join(text.split()) for text in tags if text.strip()]
            field_text = " ".join(field.inner_text().split())
            if charge_item not in field_text or (tags and tags != [charge_item]):
                raise AssertionError(
                    "高级搜索筛选联动后收费项条件未保留或不唯一；"
                    f"目标={charge_item!r}，标签={tags!r}，字段文本={field_text!r}。"
                )

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
        headers = self.frame.locator(".el-table__header-wrapper th").evaluate_all(
            """els => els.filter(el => el.getClientRects().length).map(el => ({
                text: el.innerText.trim().replace(/\s+/g, ' '),
                className: el.className
            }))"""
        )

        def header_key(label: str, parent: str | None = None) -> str:
            exact = [item for item in headers if item["text"] == label]
            if parent is not None:
                parent_ids = {
                    match.group(1)
                    for item in headers
                    if item["text"] == parent
                    for match in [re.search(r"(?:^|\s)el-table_\d+_column_(\d+)(?:\s|$)", item["className"])]
                    if match
                }
                if len(parent_ids) != 1:
                    raise AssertionError(
                        f"金额表头分组 {parent!r} 应唯一，实际列号={sorted(parent_ids)}"
                    )
                parent_id = next(iter(parent_ids))
                child_ids = {
                    match.group(1)
                    for item in exact
                    for match in [re.search(
                        rf"(?:^|\s)el-table_\d+_column_{parent_id}_column_(\d+)(?:\s|$)",
                        item["className"],
                    )]
                    if match
                }
                if len(child_ids) != 1:
                    raise AssertionError(
                        f"{parent} / {label} 金额表头应唯一，实际列号={sorted(child_ids)}"
                    )
                return f"column_{parent_id}_column_{next(iter(child_ids))}"

            column_ids = {
                match.group(1)
                for item in exact
                for match in [re.search(
                    r"(?:^|\s)el-table_\d+_column_(\d+)(?:\s|$)",
                    item["className"],
                )]
                if match
            }
            if len(column_ids) != 1:
                raise AssertionError(
                    f"{label}金额表头应唯一，实际列号={sorted(column_ids)}"
                )
            return f"column_{next(iter(column_ids))}"

        def amount_by_column(description: str, column_key: str) -> Decimal:
            candidates = row.locator("td")
            matched = []
            pattern = re.compile(
                rf"(?:^|\s)(?:el-table_\d+_)?{re.escape(column_key)}(?:\s|$)"
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
            # 表格前端重构会调整 Element UI 内部列号；从可见表头按业务标签
            # 识别本金应收、本金减免和合计欠款，避免依赖固定列号。
            "original_amount": amount_by_column(
                "本金应收", header_key("应收", "本金")
            ),
            "discount_amount": amount_by_column(
                "本金减免", header_key("减免", "本金")
            ),
            "receivable_amount": amount_by_column(
                "合计欠款", header_key("合计欠款")
            ),
        }
