from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlparse

from playwright.sync_api import FrameLocator, Locator, Page, Response, expect

from src.pages.base_page import BasePage


@dataclass(frozen=True, slots=True)
class TemporaryBillData:
    room_path: str
    billing_month: str
    charge_item: str
    charge_standard: str
    remark: str
    manual_amount: Decimal | None = None
    meter_usage: Decimal | None = None
    quantity: Decimal | None = None
    billing_period_start: str | None = None
    billing_period_end: str | None = None
    expected_amount: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CreatedTemporaryBill:
    bill_number: str
    row_text: str
    amount: Decimal


class TemporaryLedgerPage(BasePage):
    """Temporary-ledger UI.

    The workflow is intentionally not shared with BillingCenterPage.  In
    particular, its clean-up must use advanced search followed by the row's
    single-item void and delete actions.
    """

    def __init__(self, page: Page) -> None:
        self.page = page
        self.frame: FrameLocator = page.frame_locator(
            'iframe[src*="busH5Url"][src*="temporaryBill"]'
        )
        self.last_submission_confirmed = False

    def wait_until_ready(self) -> None:
        launch = self.frame.get_by_role(
            "button", name="发起临时缴费", exact=True
        )
        expect(launch).to_be_visible(timeout=30_000)
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )

    def open_advanced_search(self) -> Locator:
        button = self.require_single(
            self.frame.get_by_role("button", name="高级搜索", exact=False),
            "临时台账高级搜索按钮",
        )
        button.click()
        return self._advanced_search_panel()

    def _advanced_search_panel(self) -> Locator:
        """Return the current visible advanced-search drawer.

        The page replaces the drawer subtree after some selector changes and
        the replacement can temporarily lose its ARIA accessible name.  The
        visible Element UI container plus its stable title remains available.
        """
        panels = self.frame.locator(
            ".el-drawer:visible, .el-dialog:visible"
        ).filter(has_text="高级搜索")
        expect(panels).to_have_count(1, timeout=15_000)
        return panels.first

    def _close_advanced_search_if_open(self) -> None:
        panels = self.frame.locator(
            ".el-drawer:visible, .el-dialog:visible"
        ).filter(has_text="高级搜索")
        if panels.count() != 1:
            return
        panel = panels.first
        close_buttons = panel.locator(
            ".el-drawer__close-btn:visible, .el-dialog__headerbtn:visible"
        )
        if close_buttons.count() == 1:
            close_buttons.click(force=True)
        else:
            self.page.keyboard.press("Escape")
        expect(panel).to_be_hidden(timeout=10_000)
        expect(self.frame.locator(".el-tree:visible")).to_have_count(
            0, timeout=10_000
        )

    def open_create_temporary_bill(self) -> Locator:
        launch = self.require_single(
            self.frame.get_by_role(
                "button", name="发起临时缴费", exact=True
            ),
            "发起临时缴费按钮",
        )
        launch.click()
        dialog = self.frame.locator(
            ".el-dialog:visible, .el-drawer:visible"
        ).filter(has_text="创建临时账单")
        expect(dialog).to_have_count(1, timeout=15_000)
        return dialog

    def fill_temporary_bill_before_submit(
        self, dialog: Locator, data: TemporaryBillData
    ) -> None:
        """Fill the user-confirmed temporary-bill fields, without submitting.

        Fixed-amount standards intentionally leave the amount field untouched.
        Manual-input cases will use a separate, explicitly parameterized method
        once their amount input rule is recorded.
        """
        room_radio = self.require_single(
            dialog.get_by_role("radio", name="房间", exact=True),
            "收费对象房间单选项",
        )
        room_radio.check()
        self._select_room_from_tree(dialog, data.room_path)

        billing_month = self.require_single(
            dialog.get_by_placeholder("选择年月"), "临时账单账期"
        )
        billing_month.fill(data.billing_month)
        billing_month.press("Enter")
        self.page.keyboard.press("Escape")
        expect(billing_month).to_have_value(data.billing_month)

        charge_item = self.require_single(
            dialog.locator('input[placeholder="请选择收费项目"]:visible'),
            "临时收费项目",
        )
        self._select_dropdown_option(charge_item, data.charge_item)

        standard = self.require_single(
            dialog.locator(
                'input[readonly][placeholder="请选择"]:not([disabled]):visible'
            ),
            "临时收费标准",
        )
        expect(standard).to_be_enabled(timeout=15_000)
        self._select_dropdown_option(standard, data.charge_standard)

        self._fill_calculation_parameters(dialog, data)

        remark = self.require_single(
            dialog.get_by_placeholder("请输入账单备注"), "临时账单备注"
        )
        remark.fill(data.remark)
        expect(remark).to_have_value(data.remark)

        no_push = self.require_single(
            dialog.get_by_role("radio", name="否", exact=True),
            "不推送单选项",
        )
        expect(no_push).to_be_checked()

    def _fill_calculation_parameters(
        self, dialog: Locator, data: TemporaryBillData
    ) -> None:
        """Fill only calculation fields explicitly supplied by the scenario.

        Inspection confirmed that the three amount-like temporary-bill
        formulas render one enabled Element UI input after the standard is
        selected, while day formulas render a two-input date range.
        """
        value_fields = [
            value
            for value in (data.manual_amount, data.meter_usage, data.quantity)
            if value is not None
        ]
        if len(value_fields) > 1:
            raise ValueError("临时账单一次只能填写一种动态金额、仪表用量或数量参数")
        if value_fields:
            candidates = dialog.locator(
                'input.el-input__inner[placeholder]:visible'
                ':not([readonly]):not([disabled])'
                ':not([placeholder="选择年月"])'
            )
            if candidates.count() != 1:
                details = []
                for index in range(candidates.count()):
                    item = candidates.nth(index)
                    details.append({
                        "value": item.input_value(),
                        "placeholder": item.get_attribute("placeholder"),
                        "outer_html": item.evaluate("el => el.outerHTML"),
                        "parent_text": item.locator("xpath=.. ").inner_text(),
                    })
                raise AssertionError(
                    "临时账单收费标准对应的动态参数输入框应唯一匹配一个元素，"
                    f"实际匹配到 {candidates.count()} 个：{details!r}"
                )
            dynamic_input = candidates
            if data.manual_amount is not None:
                # Manual-input standards bind this textbox directly to the
                # receivable amount; there is no calculation API to wait for.
                dynamic_input.fill(self._format_decimal(data.manual_amount))
                dynamic_input.press("Tab")
            else:
                # Meter-usage and quantity standards calculate the receivable
                # amount asynchronously. A visible value alone is insufficient:
                # the create API can otherwise win the race.
                with self.page.expect_response(
                    lambda response: (
                        response.request.method == "POST"
                        and urlparse(response.url).path.endswith(
                            "/temporaryBill/queryTempFeeStandardTotalFeeAmount"
                        )
                    ),
                    timeout=30_000,
                ) as calculation_response:
                    dynamic_input.fill(self._format_decimal(value_fields[0]))
                    dynamic_input.press("Tab")
                if not calculation_response.value.ok:
                    raise AssertionError(
                        "临时账单金额计算接口未成功返回："
                        f"HTTP {calculation_response.value.status}"
                    )
            expect(dynamic_input).to_have_value(
                self._format_decimal(value_fields[0])
            )
            if data.manual_amount is None:
                calculated_amount = self.require_single(
                    dialog.locator(
                        'input.el-input__inner[disabled]:visible:not([readonly])'
                    ),
                    "临时账单异步计算后的收款金额",
                )
                expect(calculated_amount).not_to_have_value("", timeout=15_000)
                if data.expected_amount is not None:
                    expect(calculated_amount).to_have_value(
                        self._format_decimal(data.expected_amount), timeout=15_000
                    )

        if (data.billing_period_start is None) != (data.billing_period_end is None):
            raise ValueError("临时账单计费日期必须同时提供开始和结束日期")
        if data.billing_period_start and data.billing_period_end:
            date_inputs = dialog.locator("input.el-range-input:visible")
            expect(date_inputs).to_have_count(2, timeout=15_000)
            date_inputs.nth(0).fill(data.billing_period_start)
            date_inputs.nth(0).press("Enter")
            # Day formulas also calculate asynchronously.  Commit the end
            # date by blurring it, then wait for the bill amount instead of
            # letting the final submit race the calculation.
            with self.page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and urlparse(response.url).path.endswith(
                        "/temporaryBill/queryTempFeeStandardTotalFeeAmount"
                    )
                ),
                timeout=30_000,
            ) as calculation_response:
                date_inputs.nth(1).fill(data.billing_period_end)
                date_inputs.nth(1).press("Enter")
                date_inputs.nth(1).press("Tab")
            self.page.keyboard.press("Escape")
            expect(date_inputs.nth(0)).to_have_value(data.billing_period_start)
            expect(date_inputs.nth(1)).to_have_value(data.billing_period_end)
            if not calculation_response.value.ok:
                raise AssertionError(
                    "临时账单天数公式金额计算接口未成功返回："
                    f"HTTP {calculation_response.value.status}"
                )
            calculated_amount = self.require_single(
                dialog.locator(
                    'input.el-input__inner[disabled]:visible:not([readonly])'
                ),
                "临时账单天数公式计算后的收款金额",
            )
            if data.expected_amount is not None:
                expect(calculated_amount).to_have_value(
                    self._format_decimal(data.expected_amount), timeout=15_000
                )

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        return format(value.normalize(), "f")

    def require_ready_to_submit(self, dialog: Locator) -> Locator:
        """Return the final submit button after non-mutating preflight checks."""
        submit = dialog.get_by_role("button", name="确定", exact=True)
        expect(submit).to_have_count(1, timeout=30_000)
        return self.require_single(
            submit,
            "临时账单最终确定按钮",
        )

    def submit_and_read_created_bill(
        self,
        dialog: Locator,
        data: TemporaryBillData,
        expected_amount: Decimal,
        existing_bill_numbers: set[str] | None = None,
    ) -> CreatedTemporaryBill:
        """Submit one temporary bill and capture its unique row identifier.

        The caller controls the creation safety flag.  This method deliberately
        does not clean anything: cleanup must use the captured number and the
        temporary-ledger-specific void/delete workflow below.
        """
        post_responses: list[str] = []
        submission_response: Response | None = None
        self.last_submission_confirmed = False

        def record_post_response(response) -> None:
            nonlocal submission_response
            if response.request.method != "POST":
                return
            path = urlparse(response.url).path
            post_responses.append(f"{response.status}:{path}")
            if path.endswith("/temporaryBill/pushTemporaryBillCharge"):
                submission_response = response

        self.page.on("response", record_post_response)
        self.require_ready_to_submit(dialog).click()
        try:
            expect(dialog).to_be_hidden(timeout=30_000)
        except AssertionError as exc:
            validation_errors = dialog.locator(
                ".el-form-item__error:visible, .is-error:visible"
            ).all_inner_texts()
            response_summary: dict[str, object] | str = "未捕获到提交响应"
            if submission_response is not None:
                try:
                    payload = submission_response.json()
                    response_summary = {
                        key: payload.get(key)
                        for key in ("respCode", "respMsg", "success", "code", "message")
                        if key in payload
                    }
                except Exception as response_error:  # pragma: no cover - diagnostic fallback
                    response_summary = f"响应无法解析为JSON: {type(response_error).__name__}"
            raise AssertionError(
                "临时账单提交后创建弹窗未关闭；"
                f"可见表单校验信息={validation_errors!r}；"
                f"提交接口业务结果={response_summary!r}；"
                f"提交期间POST响应={post_responses[-10:]!r}"
            ) from exc
        finally:
            self.page.remove_listener("response", record_post_response)
        feedback = self.frame.locator(
            ".el-message:visible, .el-notification:visible, .el-message-box:visible"
        )
        expect(feedback).to_contain_text(re.compile(r"推送成功|成功"), timeout=30_000)
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        self.last_submission_confirmed = True

        # The create dialog can close successfully while the default table
        # remains stale. Refresh via the exact business-key query instead of
        # assuming the room row is already rendered in the old view.
        current_bill_numbers = self.get_bill_numbers_by_month_room_charge_item(
            billing_month=data.billing_month,
            room_path=data.room_path,
            charge_item=data.charge_item,
        )
        before = existing_bill_numbers or set()
        candidates = [number for number in current_bill_numbers if number not in before]
        if len(candidates) != 1:
            raise AssertionError(
                "创建后无法仅通过提交前后的唯一账单编号差集确定新记录；"
                f"提交前数量={len(before)}，提交后数量={len(current_bill_numbers)}，"
                f"候选数量={len(candidates)}。"
            )
        bill_number = candidates[0]
        row = self._find_bill_row(bill_number)
        expect(row).to_have_count(1, timeout=15_000)
        row_text = row.inner_text()
        if f"{expected_amount:.2f}" not in row_text:
            raise AssertionError(
                f"临时账单金额未包含预期 {expected_amount:.2f}；实际行={row_text!r}"
            )
        return CreatedTemporaryBill(bill_number, row_text, expected_amount)

    def visible_bill_numbers_for_room(self, room_name: str) -> set[str]:
        """Read current visible IDs for creation-result comparison only.

        This is not a cleanup locator. Cleanup searches by billing month, room,
        and charge item; IDs are retained only as creation evidence.
        """
        rows = self.frame.locator(
            ".el-table__body-wrapper tr.el-table__row:visible"
        ).filter(has_text=room_name)
        numbers: set[str] = set()
        for index in range(rows.count()):
            numbers.add(self._extract_bill_number(rows.nth(index).inner_text()))
        return numbers

    def cleanup_created_bill(
        self,
        created: CreatedTemporaryBill,
        void_reason: str,
        *,
        billing_month: str,
        room_path: str,
        charge_item: str,
    ) -> None:
        """Compatibility wrapper; cleanup is always keyed by business fields."""
        self.cleanup_by_month_room_charge_item(
            billing_month=billing_month,
            room_path=room_path,
            charge_item=charge_item,
            void_reason=void_reason,
            expected_bill_number=created.bill_number,
            require_match=True,
        )

    def get_bill_numbers_by_month_room_charge_item(
        self, *, billing_month: str, room_path: str, charge_item: str
    ) -> list[str]:
        """Read ledger matches by the confirmed business key without mutation."""
        panels = self.frame.locator(".el-drawer:visible, .el-dialog:visible").filter(
            has_text="高级搜索"
        )
        if panels.count() == 1:
            search = panels.first
        else:
            search = self.open_advanced_search()

        # Follow the current UI order and compatibility rules: charge item,
        # both billing-month bounds, then bill-object room selection.
        charge_inputs = search.locator('input[placeholder*="收费项"]')
        if charge_inputs.count() == 0:
            charge_inputs = search.locator('input[placeholder="请选择"]')
        visible_charge_inputs = [
            charge_inputs.nth(i)
            for i in range(charge_inputs.count())
            if charge_inputs.nth(i).is_visible()
        ]
        if not visible_charge_inputs:
            raise AssertionError("临时台账高级搜索收费项控件未可见")
        charge_input = visible_charge_inputs[-1]
        if charge_input.get_attribute("readonly") is not None:
            select_wrapper = charge_input.locator(
                "xpath=ancestor::*[contains(@class,'el-select')][1]"
            )
            if select_wrapper.count() == 1 and select_wrapper.is_visible():
                select_wrapper.click(force=True)
            else:
                charge_input.click(force=True)
            option = self.frame.locator(
                ".el-select-dropdown:visible .el-select-dropdown__item"
            ).filter(has_text=re.compile(rf"^{re.escape(charge_item)}$"))
            expect(option).to_have_count(1, timeout=20_000)
            option.scroll_into_view_if_needed(timeout=10_000)
            option.click(force=True)
        else:
            charge_input.fill(charge_item)
            charge_input.press("Enter")

        month_inputs = search.locator('input[placeholder*="年月"]:visible')
        expect(month_inputs).to_have_count(2)
        for index in (0, 1):
            month_inputs.nth(index).fill(billing_month)
            month_inputs.nth(index).press("Enter")
        expect(month_inputs.nth(0)).to_have_value(billing_month)
        expect(month_inputs.nth(1)).to_have_value(billing_month)
        self.select_advanced_room_filter(search, room_path)

        search = self._advanced_search_panel()
        submit = self.require_single(
            search.get_by_role("button", name="搜索", exact=True),
            "临时台账高级搜索提交按钮",
        )
        submit.click(force=True)
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        rows = self.frame.locator(
            ".el-table__body-wrapper tr.el-table__row:visible"
        )
        numbers: list[str] = []
        for index in range(rows.count()):
            try:
                numbers.append(self._extract_bill_number(rows.nth(index).inner_text()))
            except AssertionError:
                # Fixed-column fragments may not contain the bill number.
                continue
        return list(dict.fromkeys(numbers))

    def cleanup_by_month_room_charge_item(
        self, *, billing_month: str, room_path: str, charge_item: str,
        void_reason: str, expected_bill_number: str | None = None,
        require_match: bool = False,
    ) -> list[str]:
        """Clean temporary-ledger bills using month + room + charge item.

        The bill number is extracted only after the business-key query and is
        never used as the search/filter input.
        """
        # A previous query can leave a drawer mounted with controls that have
        # since been hidden/replaced. Reopen it cleanly before destructive
        # operations so the exact-key filters target the current controls.
        self._close_advanced_search_if_open()
        search = self.open_advanced_search()
        # Newer builds close the drawer when Reset is clicked. Normalize the
        # persistent state by overwriting each business-key field below.
        # Select the charge item before opening the room tree.  The redesigned
        # page re-renders the charge selector when the room popover closes;
        # doing this first avoids that transition entirely.
        charge_inputs = search.locator('input[placeholder*="收费项"]')
        if charge_inputs.count() == 0:
            charge_inputs = search.locator('input[placeholder="请选择"]')
        if charge_inputs.count():
            visible_charge_inputs = [
                charge_inputs.nth(i)
                for i in range(charge_inputs.count())
                if charge_inputs.nth(i).is_visible()
            ]
            if not visible_charge_inputs:
                self.page.wait_for_timeout(1_000)
                visible_charge_inputs = [
                    charge_inputs.nth(i)
                    for i in range(charge_inputs.count())
                    if charge_inputs.nth(i).is_visible()
                ]
            if not visible_charge_inputs:
                raise AssertionError(
                    f"临时台账高级搜索收费项控件未可见；候选数={charge_inputs.count()}"
                )
            charge_input = visible_charge_inputs[-1]
            expect(charge_input).to_be_attached(timeout=15_000)
            # Allow the room popover animation to finish; click is forced
            # after scrolling because the control may be briefly covered.
            if charge_input.get_attribute("readonly") is not None:
                select_wrapper = charge_input.locator(
                    "xpath=ancestor::*[contains(@class,'el-select')][1]"
                )
                if select_wrapper.count() == 1 and select_wrapper.is_visible():
                    select_wrapper.click(force=True)
                else:
                    charge_input.click(force=True)
                popups = self.frame.locator(
                    ".el-select-dropdown:visible, .el-popper:visible"
                )
                expect(popups).not_to_have_count(0, timeout=15_000)
                # This selector is a plain Element UI option list in the
                # current build.  Typing into any incidental input mounted in
                # the popper closes it, so resolve the exact option directly
                # from the rendered list.
                # Depending on the Element UI build the option list can be
                # rendered in a sibling popper. Resolve the exact text from
                # every visible select dropdown.
                option_candidates = self.frame.locator(
                    ".el-select-dropdown:visible .el-select-dropdown__item"
                ).filter(has_text=re.compile(rf"^{re.escape(charge_item)}$"))
                # The dropdown may first render a transient empty panel and
                # then replace it with the asynchronously loaded option list.
                expect(option_candidates).to_have_count(1, timeout=20_000)
                option = option_candidates.first
                option.scroll_into_view_if_needed(timeout=10_000)
                option.click(force=True)
            else:
                charge_input.fill(charge_item)
                charge_input.press("Enter")
        month_inputs = search.locator('input[placeholder*="年月"]:visible')
        if month_inputs.count() != 2:
            raise AssertionError(
                f"Temporary Ledger advanced search requires two month inputs; "
                f"actual={month_inputs.count()}"
            )
        for index in (0, 1):
            month_inputs.nth(index).fill(billing_month)
            month_inputs.nth(index).press("Enter")
        expect(month_inputs.nth(0)).to_have_value(billing_month)
        expect(month_inputs.nth(1)).to_have_value(billing_month)
        self.select_advanced_room_filter(search, room_path)
        # The room selector has already been confirmed and closed.  Do not
        # press Escape here: in the current build that closes the Advanced
        # Search drawer itself, leaving no Search button to submit.
        self.page.wait_for_timeout(300)
        search = self._advanced_search_panel()
        submit = self.require_single(
            search.get_by_role("button", name="搜索", exact=True),
            "临时台账高级搜索提交按钮",
        )
        expect(submit).to_be_attached(timeout=15_000)
        submit.click(force=True)
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(0, timeout=60_000)
        # Advanced Search already scopes the result by month + room + charge
        # item. Element UI renders fixed columns and the main table as
        # separate DOM rows, so requiring one DOM row to contain both the room
        # and charge-item text incorrectly returns zero for valid results.
        # Read bill numbers from every visible result-table fragment instead.
        rows = self.frame.locator(
            ".el-table__body-wrapper tr.el-table__row:visible"
        )
        numbers: list[str] = []
        for index in range(rows.count()):
            try:
                number = self._extract_bill_number(rows.nth(index).inner_text())
            except AssertionError:
                # Fixed-column fragments do not contain the bill number.
                continue
            numbers.append(number)
        numbers = list(dict.fromkeys(numbers))
        if expected_bill_number and expected_bill_number not in numbers:
            raise AssertionError(
                "临时台账按账期+房间+收费项查询后未找到本次创建账单："
                f"expected={expected_bill_number}, actual={numbers}"
            )
        if require_match and not numbers:
            raise AssertionError(
                "临时台账已创建账单，但按账期+房间+收费项清理查询结果为0："
                f"month={billing_month}, room={room_path}, item={charge_item}"
            )
        for number in reversed(numbers):
            action_row = self._find_operation_row(number)
            operation = action_row.get_by_text("作废", exact=True)
            visible_voids = [
                operation.nth(index)
                for index in range(operation.count())
                if operation.nth(index).is_visible()
            ]
            if len(visible_voids) != 1:
                raise AssertionError(
                    f"临时台账账单 {number} 的作废操作应唯一可见，"
                    f"实际 {len(visible_voids)} 个"
                )
            visible_voids[0].click()
            void_dialog = self.frame.get_by_role("dialog").filter(has_text="作废")
            expect(void_dialog).to_be_visible(timeout=15_000)
            self.require_single(void_dialog.get_by_role("textbox"), "作废说明").fill(void_reason)
            void_confirm = void_dialog.get_by_role(
                "button", name=re.compile(r"^(?:确定|确认)(?:作废)?$")
            )
            visible_confirms = [
                void_confirm.nth(index)
                for index in range(void_confirm.count())
                if void_confirm.nth(index).is_visible()
            ]
            if len(visible_confirms) != 1:
                raise AssertionError(
                    "临时台账作废确认按钮应唯一可见，实际 "
                    f"{len(visible_confirms)} 个；按钮={void_dialog.locator('button').all_inner_texts()}"
                )
            visible_confirms[0].click()
            expect(self.frame.locator(".el-message:visible")).to_contain_text(re.compile("作废成功"), timeout=30_000)
            expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
                0, timeout=30_000
            )

            action_row = self._find_operation_row(number)
            delete = action_row.get_by_text("删除", exact=True)
            expect(delete).to_have_count(1, timeout=15_000)
            visible_deletes = [
                delete.nth(index)
                for index in range(delete.count())
                if delete.nth(index).is_visible()
            ]
            if len(visible_deletes) != 1:
                raise AssertionError(
                    f"临时台账账单 {number} 的删除操作应唯一可见，"
                    f"实际 {len(visible_deletes)} 个"
                )
            visible_deletes[0].click()
            prompt = self.frame.get_by_text(re.compile(r"删除后.*不可恢复|确认.*删除"))
            expect(prompt).to_be_visible(timeout=15_000)
            panel = prompt.locator("xpath=ancestor::*[.//button][1]")
            self.require_single(panel.get_by_text("确定", exact=True), "确认删除").click()
            expect(self._find_bill_row(number)).to_have_count(0, timeout=30_000)
        for number in numbers:
            expect(self._find_bill_row(number)).to_have_count(0, timeout=30_000)
        return numbers

    def _find_bill_row(self, bill_number: str) -> Locator:
        return self.frame.locator(
            ".el-table__body-wrapper tr.el-table__row:visible"
        ).filter(has_text=bill_number)

    def _find_operation_row(self, bill_number: str) -> Locator:
        """Map a bill-number row to Element UI's fixed-right action row."""
        bill_row = self._find_bill_row(bill_number)
        expect(bill_row).to_have_count(1, timeout=15_000)
        row_index = bill_row.evaluate(
            "row => Array.from(row.parentElement.children).indexOf(row)"
        )
        fixed_rows = self.frame.locator(
            ".el-table__fixed-right .el-table__fixed-body-wrapper "
            "tr.el-table__row:visible"
        )
        if fixed_rows.count() > row_index:
            return fixed_rows.nth(row_index)
        # Compatibility fallback for builds that keep actions in the main row.
        if bill_row.get_by_text(re.compile(r"^(作废|删除)$")).count():
            return bill_row
        raise AssertionError(
            f"临时台账账单 {bill_number} 未找到对应固定右侧操作行；"
            f"row_index={row_index}, fixed_rows={fixed_rows.count()}"
        )

    @staticmethod
    def _extract_bill_number(row_text: str) -> str:
        candidates = re.findall(r"(?<![\w-])[A-Z]{2,}[A-Z0-9-]{5,}(?![\w-])", row_text)
        if len(candidates) != 1:
            raise AssertionError(
                f"新建临时账单行中的唯一账单编号无法确定：{candidates!r}；行={row_text!r}"
            )
        return candidates[0]

    def inspect_advanced_room_filter(self, dialog: Locator) -> None:
        """Assert the verified, non-mutating advanced-search contract.

        The actual search and cleanup are added only after a bill number has
        been recorded from the creation result.
        """
        self.require_single(
            dialog.get_by_text(
                re.compile(r"^账单对象\s*:\s*全部$"), exact=True
            ),
            "账单对象“全部”切换控件",
        )
        self.require_single(
            dialog.get_by_placeholder("请选择"), "房间筛选输入框"
        )
        self.require_single(
            dialog.get_by_role("button", name="搜索", exact=True),
            "高级搜索提交按钮",
        )

    def select_advanced_room_filter(self, dialog: Locator, room_path: str) -> None:
        """Select 房间 in the redesigned advanced-search bill-object filter."""
        # Do not press Escape here.  In the current build the month inputs do
        # not necessarily leave a picker open, so a global Escape closes the
        # Advanced Search drawer itself.  Interact with the bill-object
        # control inside the still-visible drawer instead.
        if dialog.count() != 1 or not dialog.is_visible():
            dialog = self._advanced_search_panel()
        month_panels = self.frame.locator(".el-picker-panel:visible")
        if month_panels.count():
            self.page.keyboard.press("Escape")
            expect(month_panels).to_have_count(0, timeout=10_000)
            dialog = self._advanced_search_panel()
        object_control = dialog.get_by_text(
            re.compile(r"账单对象\s*[-:]\s*全部"), exact=False
        )
        visible_controls = [
            object_control.nth(i)
            for i in range(object_control.count())
            if object_control.nth(i).is_visible()
        ]
        if len(visible_controls) == 1:
            visible_controls[0].hover(force=True)
            visible_controls[0].click(force=True)
            option = self.frame.locator(
                ".el-dropdown-menu:visible .el-dropdown-menu__item"
            ).filter(has_text=re.compile(r"^房间$"))
            expect(option).to_have_count(1, timeout=10_000)
            option.click(force=True)
        elif len(visible_controls) == 0:
            # Advanced Search keeps the previous bill-object mode between
            # consecutive recovery targets. After the first query the control
            # already shows 房间, so there is no “账单对象-全部” text to switch.
            room_mode = dialog.get_by_role(
                "button", name=re.compile(r"^房间(?:\s|$)")
            )
            visible_room_modes = [
                room_mode.nth(i)
                for i in range(room_mode.count())
                if room_mode.nth(i).is_visible()
            ]
            if not visible_room_modes:
                raise AssertionError(
                    "账单对象筛选控件既不是全部也不是房间；"
                    f"弹窗文本={dialog.inner_text()!r}"
                )
        else:
            raise AssertionError(f"账单对象筛选控件应唯一可见，实际 {len(visible_controls)} 个")

        room_leaf = room_path.rstrip("/").split("/")[-1]
        # The redesigned component renders two adjacent controls after the
        # bill object is changed to 房间: a readonly mode select whose value is
        # “房间选择”, followed by the actual editable room search input.  The
        # old generic `placeholder=请选择` locator selected the readonly mode
        # control and therefore never opened the room tree.
        room_inputs = dialog.locator(
            'input[placeholder="请选择"]:visible:not([readonly]):not([disabled])'
        )
        expect(room_inputs).to_have_count(1, timeout=15_000)
        room_input = room_inputs.first
        room_input.click(force=True)
        room_input.fill(room_leaf)
        tree = self.frame.locator(".el-tree:visible")
        expect(tree).to_be_visible(timeout=20_000)
        # In the redesigned cascader the field itself is readonly; the
        # editable filter input, when present, is mounted inside the tree
        # popover.  Prefer that input and fall back to the loaded tree when a
        # build does not expose a filter textbox.
        self.page.wait_for_timeout(500)
        # The search input opens the selector and carries the room token, but
        # this component does not eagerly load descendant nodes.  Expand the
        # known path while waiting for each async level before selecting the
        # exact leaf.
        path_parts = [part for part in room_path.split("/") if part]
        for part in path_parts[:-1]:
            ancestor = tree.get_by_text(part, exact=True)
            if ancestor.count() == 0:
                ancestor = tree.locator(".el-tree-node__content").filter(
                    has_text=re.compile(rf"^{re.escape(part)}$")
                )
            expect(ancestor).to_have_count(1, timeout=20_000)
            node = ancestor.first.locator(
                "xpath=ancestor::*[contains(@class,'el-tree-node')][1]"
            )
            expand = node.locator(".el-tree-node__expand-icon")
            if expand.count() == 1 and "expanded" not in (
                expand.get_attribute("class") or ""
            ):
                expand.click(force=True)
                self.page.wait_for_timeout(500)
        target = tree.get_by_text(room_leaf, exact=True)
        if target.count() == 0:
            # Some builds wrap the room number with an icon/label span, so an
            # exact text locator does not resolve even though the node is
            # rendered.  Fall back to the tree-node content while retaining
            # the exact leaf number as the filter token.
            target = tree.locator(".el-tree-node__content").filter(
                has_text=re.compile(rf"(?<!\d){re.escape(room_leaf)}(?!\d)")
            )
        try:
            expect(target).to_be_visible(timeout=20_000)
        except AssertionError as exc:
            raise AssertionError(
                f"房间树未展示目标房间 {room_leaf}；树文本={tree.inner_text()!r}"
            ) from exc
        checkboxes = target.locator(
            "xpath=ancestor::*[contains(@class,'el-tree-node__content')][1]"
        ).locator(".el-checkbox__inner:visible, input[type='checkbox']:visible")
        if checkboxes.count() == 1:
            checkboxes.click(force=True)
        else:
            target.click(force=True)
        # The room popover in the redesigned advanced search has its own
        # confirm button.  Confirm it before opening the charge selector;
        # Escape alone leaves the tree popper mounted and it can be mistaken
        # for the charge-item dropdown.
        room_popup = tree.locator("xpath=ancestor::*[.//button][1]")
        room_confirm = room_popup.get_by_text(re.compile(r"^确定$"), exact=True)
        if room_confirm.count() and room_confirm.last.is_visible():
            room_confirm.last.click(force=True)
        elif tree.is_visible():
            # Compatibility fallback for builds without a confirm button.
            self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(300)
        if tree.is_visible():
            # Some versions keep the tree popover mounted after confirming;
            # Escape is safe only while that popover is still visible.
            self.page.keyboard.press("Escape")
        expect(self.frame.locator(".el-tree:visible")).to_have_count(
            0, timeout=10_000
        )
        self.page.wait_for_timeout(500)

        # Do not click an arbitrary point in the drawer here.  On newer
        # Element UI builds that point can belong to the overlay and trigger a
        # full advanced-search redraw, temporarily hiding the next selector.

    def _select_room_from_tree(self, container: Locator, room_path: str) -> None:
        """Select a leaf room and confirm the visible Element UI tree popup."""
        parts = [part for part in room_path.split("/") if part]
        if not parts:
            raise ValueError("ROOM_PATH 不能为空")

        room_input = self.require_single(
            container.get_by_placeholder("请选择房间"), "房间选择输入框"
        )
        room_input.click()
        room_tree = self.frame.locator(".el-tree:visible")
        expect(room_tree).to_have_count(1, timeout=30_000)

        for part in parts[:-1]:
            node_locator = room_tree.get_by_text(part, exact=True)
            # A visible tree container can precede its asynchronous node data.
            # Wait for the user-confirmed path node instead of treating the
            # container render as a loaded room tree.
            if node_locator.count() == 0:
                node_locator = room_tree.locator(
                    ".el-tree-node__content"
                ).filter(has_text=re.compile(re.escape(part)))
            try:
                expect(node_locator).to_have_count(1, timeout=30_000)
            except AssertionError as exc:
                raise AssertionError(
                    f"房间树节点 {part} 未加载；树文本={room_tree.inner_text()!r}"
                ) from exc
            node_text = self.require_single(node_locator, f"房间树节点 {part}")
            node = node_text.locator(
                "xpath=ancestor::*[contains(@class, 'el-tree-node')][1]"
            )
            expand = node.locator(".el-tree-node__expand-icon")
            if expand.count() == 1 and "expanded" not in (
                expand.get_attribute("class") or ""
            ):
                expand.click()

        leaf_locator = room_tree.get_by_text(parts[-1], exact=True)
        expect(leaf_locator).to_have_count(1, timeout=30_000)
        leaf = self.require_single(leaf_locator, f"房间树叶子节点 {parts[-1]}")
        leaf_content = leaf.locator(
            "xpath=ancestor::*[contains(@class, 'el-tree-node__content')][1]"
        )
        checkbox = leaf_content.locator(".el-checkbox")
        if checkbox.count() == 1:
            checkbox.click()
            expect(checkbox).to_have_class(re.compile(r"\bis-checked\b"))
        else:
            leaf.click()

        popup = room_tree.locator("xpath=ancestor::*[.//button][1]")
        confirm = popup.get_by_text(re.compile(r"^确\s*[认定]$"))
        self.require_single(confirm, "房间树确认按钮").click()

    def _select_dropdown_option(self, input_locator: Locator, option: str) -> None:
        input_locator.click()
        dropdown = self.frame.locator(".el-select-dropdown:visible")
        expect(dropdown).to_have_count(1, timeout=15_000)
        target_locator = dropdown.get_by_text(option, exact=True)
        # The dropdown shell appears before its remote options finish loading.
        # Wait for the requested option; do not infer or substitute a value.
        expect(target_locator).to_have_count(1, timeout=30_000)
        target = self.require_single(target_locator, f"下拉选项 {option}")
        target.click()
        expect(input_locator).to_have_value(option, timeout=15_000)
        expect(dropdown).to_be_hidden(timeout=15_000)
