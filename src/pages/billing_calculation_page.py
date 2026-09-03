from __future__ import annotations

import json
import re
from dataclasses import dataclass

from playwright.sync_api import Frame, FrameLocator, Locator, Page, expect

from src.pages.base_page import BasePage


@dataclass(frozen=True, slots=True)
class CalculationData:
    project_name: str
    room_name: str
    charge_item: str
    billing_month: str
    receivable_day: str
    latest_payment_day: str
    audit_comment: str
    charge_type: str = ""


@dataclass(frozen=True, slots=True)
class TemporaryCalculationData:
    """临时类计费出账抽屉的场景数据。"""

    project_name: str
    room_name: str
    room_path: str
    billing_month: str
    receivable_date: str
    latest_payment_date: str
    charge_item: str
    charge_standard: str
    meter_usage: str | None = None
    quantity: str | None = None
    manual_amount: str | None = None
    expected_amount: str = ""
    area_type: str | None = None
    billing_period_start: str | None = None
    billing_period_end: str | None = None


class BillingCalculationPage(BasePage):
    """常规类计费出账页面。

    该页面的状态流转为：配置计算条件 -> 计算 -> 核对 -> 提交审核 ->
    审核通过。它不复用账单中心的“创建账单”抽屉。
    """

    def __init__(self, page: Page) -> None:
        self.page = page
        # The portal keeps previously opened business iframes alive. Do not
        # assume the calculation page is the final one: an unrelated iframe
        # can be appended after it by a portal widget.
        self.frame: FrameLocator = page.frame_locator("iframe").first
        self.shell_frame: FrameLocator = page.frame_locator("iframe").first

    def wait_until_ready(self) -> None:
        selected_frame: FrameLocator | None = None
        selected_shell: FrameLocator | None = None
        # This nested application is materially slower than the portal shell
        # in Standard1.  Wait for its actual business entry rather than
        # treating a rendered outer iframe as ready.
        # Fail fast on a genuinely unavailable business iframe; the caller's
        # per-test cleanup/finally path still handles any partial submission.
        for _ in range(90):
            iframe_elements = self.page.locator("iframe")
            for index in range(iframe_elements.count()):
                outer_frame = self.page.frame_locator("iframe").nth(index)
                candidates = [outer_frame]
                nested_iframes = outer_frame.locator("iframe")
                for nested_index in range(nested_iframes.count()):
                    candidates.append(outer_frame.frame_locator("iframe").nth(nested_index))
                for candidate in candidates:
                    regular_start = candidate.get_by_text(
                        "开始计算", exact=True
                    ).first
                    if regular_start.is_visible():
                        selected_frame = candidate
                        selected_shell = outer_frame
                        break
                if selected_frame is not None:
                    break
            if selected_frame is not None:
                break
            self.page.wait_for_timeout(500)
        if selected_frame is None:
            raise AssertionError(
                "计费出账 iframe 未加载‘开始计算’按钮；"
                f"当前顶层 iframe 数量={self.page.locator('iframe').count()}"
            )
        self.frame = selected_frame
        self.shell_frame = selected_shell or selected_frame
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=30_000
        )

    def select_project(self, project_name: str) -> None:
        """Select the top project selector only when it is not already active."""
        project_labels = self.shell_frame.get_by_text(project_name, exact=True)
        if any(
            project_labels.nth(index).is_visible()
            for index in range(project_labels.count())
        ):
            return
        selectors = self.shell_frame.locator(".jie-project:visible")
        if selectors.count() == 0:
            # 页面已按当前项目加载时，部分版本不会暴露可编辑项目选择器。
            expect(self.shell_frame.get_by_text(project_name, exact=True)).to_be_visible(
                timeout=15_000
            )
            return
        selector = self.require_single(selectors, "计费出账项目选择器")
        current = selector.get_by_text(project_name, exact=True)
        if (current.count() and current.first.is_visible()) or (
            project_name in selector.inner_text()
        ):
            return
        selector.click()
        popover_id = selector.get_attribute("aria-describedby")
        panels: list[Locator] = []
        if popover_id:
            for scope in (self.frame, self.shell_frame):
                candidate = scope.locator(f"#{popover_id}:visible")
                if candidate.count() == 1:
                    panels.append(candidate)
        if not panels:
            for scope in (self.frame, self.shell_frame):
                candidates = scope.locator(".el-popover:visible")
                panels.extend(
                    candidates.nth(index)
                    for index in range(candidates.count())
                    if candidates.nth(index).get_by_text(
                        project_name, exact=True
                    ).count()
                )
        dropdown = self.require_single(
            panels[0] if len(panels) == 1 else self.shell_frame.locator(".el-popover:visible"),
            "计费出账项目下拉面板",
        )
        option = dropdown.get_by_text(project_name, exact=True)
        visible: list[Locator] = []
        # Project options are loaded asynchronously after the popover shell;
        # retry the exact label for a bounded period rather than clicking an
        # empty shell or substituting another project.
        for _ in range(60):
            visible = [
                option.nth(index)
                for index in range(option.count())
                if option.nth(index).is_visible()
            ]
            if not visible:
                # The popover may be teleported outside the aria-describedby
                # node while its opening animation is running.
                for scope in (self.frame, self.shell_frame):
                    fallback = scope.get_by_text(project_name, exact=True)
                    visible.extend(
                        fallback.nth(index)
                        for index in range(fallback.count())
                        if fallback.nth(index).is_visible()
                    )
            if visible:
                break
            self.page.wait_for_timeout(500)
        if not visible:
            raise AssertionError(
                f"项目 {project_name!r} 应唯一可选，实际可见 {len(visible)} 个。"
            )
        viewport = self.page.viewport_size or {"width": 0, "height": 0}
        in_view = []
        for candidate in visible:
            box = candidate.bounding_box()
            if box and 0 <= box["x"] < viewport["width"] and 0 <= box["y"] < viewport["height"]:
                in_view.append(candidate)
        target = in_view[0] if in_view else visible[-1]
        # Native DOM click avoids Playwright's cross-frame viewport check when
        # Element UI renders the popup in a portal layer outside the iframe's
        # scroll box.
        target.evaluate("el => el.click()")

    def open_regular_calculation(self) -> Locator:
        starts = self.frame.get_by_text("开始计算", exact=True)
        visible = [
            starts.nth(index)
            for index in range(starts.count())
            if starts.nth(index).is_visible()
        ]
        if len(visible) != 2:
            raise AssertionError(
                "首页应同时显示常规类和临时类两个“开始计算”按钮，"
                f"实际可见 {len(visible)} 个。"
            )
        visible[0].click(force=True)
        drawer = self.frame.locator(".el-drawer:visible").filter(
            has_text="常规类出账-费用计算"
        )
        expect(drawer).to_have_count(1, timeout=15_000)
        return drawer

    def open_temporary_calculation(self) -> Locator:
        """Open the right-hand 临时类出账 card, never the regular card."""
        starts = self.frame.get_by_text("开始计算", exact=True)
        visible = [
            starts.nth(index)
            for index in range(starts.count())
            if starts.nth(index).is_visible()
        ]
        if len(visible) != 2:
            raise AssertionError(
                "首页应同时显示常规类和临时类两个“开始计算”按钮，"
                f"实际可见 {len(visible)} 个。"
            )
        visible[1].click(force=True)
        drawer = self.frame.locator(".el-drawer:visible").filter(
            has_text="临时类出账-费用计算"
        )
        expect(drawer).to_have_count(1, timeout=30_000)
        expect(drawer.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        return drawer

    def configure_temporary_calculation(
        self, drawer: Locator, data: TemporaryCalculationData
    ) -> None:
        """Fill temporary calculation conditions and wait for async amount."""
        self._select_room(drawer, data.room_name)

        month = self.require_single(
            drawer.get_by_placeholder("选择年月"), "临时类应收账期"
        )
        self._fill_date_input(month, data.billing_month)
        date_inputs = drawer.get_by_placeholder("选择日期")
        if date_inputs.count() != 2:
            raise AssertionError(
                f"临时类应收日期和最晚缴款日期应各有一个输入框，实际 {date_inputs.count()} 个。"
            )
        self._fill_date_input(date_inputs.nth(0), data.receivable_date)
        self._fill_date_input(date_inputs.nth(1), data.latest_payment_date)

        item_input = self.require_single(
            drawer.locator('input[placeholder="请选择收费项目"]:visible'),
            "临时类收费项目",
        )
        self._select_visible_dropdown_option(item_input, data.charge_item)

        standard_input = self.require_single(
            drawer.locator(
                'input[readonly][placeholder="请选择"]:visible:not([disabled])'
            ),
            "临时类收费标准",
        )
        expect(standard_input).to_be_enabled(timeout=30_000)
        self._select_visible_dropdown_option(standard_input, data.charge_standard)
        if data.area_type:
            self._select_temporary_area(drawer, data.area_type)
        if data.billing_period_start and data.billing_period_end:
            self._fill_temporary_period(
                drawer, data.billing_period_start, data.billing_period_end
            )
        self._fill_temporary_dynamic_value(drawer, data)
        self._assert_temporary_amount(drawer, data.expected_amount)

    def submit_temporary_calculation(self, drawer: Locator) -> None:
        """Confirm, decline offline collection, and assert creation success."""
        confirm = self.require_single(
            drawer.get_by_role("button", name="确定", exact=True),
            "临时类出账确认按钮",
        )
        expect(confirm).to_be_enabled(timeout=30_000)
        confirm.click()
        prompt = None
        prompt_scope = None
        # Temporary-billing submission is asynchronous on Standard1. The
        # confirm button can show a spinner while the offline-collection prompt
        # is still being returned by the service.
        for _ in range(120):
            for scope in [self.frame, self.shell_frame, *self.page.frames]:
                candidates = scope.get_by_text(
                    re.compile(r"是否需要进行线下收款[?？]"), exact=False
                )
                visible = [
                    candidates.nth(index)
                    for index in range(candidates.count())
                    if candidates.nth(index).is_visible()
                ]
                if visible:
                    prompt = visible[-1]
                    prompt_scope = scope
                    break
            if prompt is not None:
                break
            self.page.wait_for_timeout(1_000)
        if prompt is None or prompt_scope is None:
            from pathlib import Path

            Path("artifacts").mkdir(exist_ok=True)
            texts = []
            for index, frame in enumerate(self.page.frames):
                try:
                    texts.append(f"FRAME {index} URL={frame.url}\n{frame.locator('body').inner_text()}")
                except Exception:
                    continue
            Path("artifacts/calculation-temporary-submit-state.txt").write_text(
                "\n\n".join(texts), encoding="utf-8"
            )
            self.page.screenshot(path="artifacts/calculation-temporary-submit-state.png", full_page=True)
            raise AssertionError("未找到线下收款确认提示")
        prompt_box = prompt.locator("xpath=ancestor::*[.//button][1]")
        cancel = prompt_box.get_by_role("button", name="取消", exact=True)
        if cancel.count() == 0:
            cancel = prompt_box.get_by_text("取消", exact=True)
        self.require_single(cancel, "线下收款提示取消按钮").click()
        for scope in [self.frame, self.shell_frame, *self.page.frames]:
            messages = scope.locator(".el-message:visible")
            if messages.count() > 0:
                expect(messages.first).to_contain_text(
                    re.compile(r"创建成功|成功"), timeout=30_000
                )
                break
        expect(drawer).to_be_hidden(timeout=30_000)

    def _fill_date_input(self, locator: Locator, value: str) -> None:
        expect(locator).to_be_visible(timeout=30_000)
        locator.fill(value)
        locator.press("Enter")
        locator.press("Tab")
        self.page.keyboard.press("Escape")
        expect(locator).to_have_value(value, timeout=15_000)

    def _select_visible_dropdown_option(self, input_locator: Locator, option: str) -> None:
        input_locator.click()
        target: Locator | None = None
        scopes = [self.frame, self.shell_frame, *self.page.frames]
        for _ in range(120):
            for scope in scopes:
                panels = scope.locator(
                    ".el-select-dropdown:visible, .el-popover:visible, [role='tooltip']:visible"
                )
                for index in range(panels.count() - 1, -1, -1):
                    candidate = panels.nth(index)
                    option_locator = candidate.get_by_text(option, exact=True)
                    visible = [
                        option_locator.nth(item)
                        for item in range(option_locator.count())
                        if option_locator.nth(item).is_visible()
                    ]
                    if visible:
                        target = visible[-1]
                        break
                if target is not None:
                    break
            if target is not None:
                break
            self.page.wait_for_timeout(500)
        if target is None:
            raise AssertionError(f"收费项/收费标准下拉未加载出唯一选项 {option!r}。")
        target.evaluate("el => el.click()")
        expect(input_locator).to_have_value(option, timeout=30_000)
        # Deposit fee items can finish loading the fee-form row after the
        # selected value is already visible in the input. Give that dependent
        # request a short bounded settle window before filling parameters or
        # submitting; this is intentionally not a blind long sleep.
        self.page.wait_for_timeout(1_000)

    def _fill_temporary_dynamic_value(
        self, drawer: Locator, data: TemporaryCalculationData
    ) -> None:
        values = [
            value
            for value in (data.meter_usage, data.quantity, data.manual_amount)
            if value is not None
        ]
        if len(values) > 1:
            raise ValueError("临时类计费一次只能配置一种动态参数")
        if not values:
            return
        preferred = (
            "请输入用量" if data.meter_usage is not None
            else "请输入数量" if data.quantity is not None
            else "请输入收费金额"
        )
        candidates = [
            drawer.locator(f'input[placeholder="{preferred}"]:visible').first
        ]
        if candidates[0].count() == 0:
            editable = drawer.locator(
                'input.el-input__inner[placeholder]:visible:not([readonly])'
            )
            candidates = [
                editable.nth(index)
                for index in range(editable.count())
                if editable.nth(index).get_attribute("placeholder") in {
                    preferred,
                    "请输入",
                }
            ]
        added_blank_row = False
        if len(candidates) == 1 and candidates[0].get_attribute("disabled") is not None:
            # Manual-input standards enable the amount field only after the
            # fee-detail row's 新增 action commits the selected standard.
            adds = drawer.get_by_text("新增", exact=True)
            visible_adds = [
                adds.nth(index)
                for index in range(adds.count())
                if adds.nth(index).is_visible()
            ]
            if visible_adds:
                visible_adds[-1].click()
                added_blank_row = True
                self.page.wait_for_timeout(800)
                refreshed = drawer.locator(
                    'input.el-input__inner[placeholder]:visible:not([readonly])'
                )
                candidates = [
                    refreshed.nth(index)
                    for index in range(refreshed.count())
                    if refreshed.nth(index).get_attribute("placeholder") in {
                        preferred,
                        "请输入",
                    }
                    and refreshed.nth(index).get_attribute("disabled") is None
                ]
        if len(candidates) != 1:
            # Keep real input attributes when a formula-specific control
            # differs between builds; do not guess a selector.
            from pathlib import Path

            Path("artifacts").mkdir(exist_ok=True)
            inputs = drawer.locator("input:visible")
            details = inputs.evaluate_all(
                "els => els.map(el => ({placeholder: el.getAttribute('placeholder'), "
                "value: el.value, readonly: el.readOnly, disabled: el.disabled, "
                "className: el.className, parentText: el.parentElement?.parentElement?.innerText, "
                "outerHTML: el.outerHTML}))"
            )
            Path("artifacts/calculation-temporary-dynamic-inputs.json").write_text(
                json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            Path("artifacts/calculation-temporary-drawer-text.txt").write_text(
                drawer.inner_text(), encoding="utf-8"
            )
            raise AssertionError(
                f"临时类收费标准动态参数输入框应唯一，实际 {len(candidates)} 个。"
            )
        dynamic = candidates[0]
        if dynamic.get_attribute("disabled") is not None:
            # The manual-amount variant can render the amount input with a
            # stale disabled attribute until its first value event.  Update
            # only the formula amount control and dispatch normal input/change
            # events so the page recalculates the amount.
            dynamic.evaluate(
                "(el, value) => {"
                "el.removeAttribute('disabled');"
                "const setter = Object.getOwnPropertyDescriptor("
                "HTMLInputElement.prototype, 'value').set;"
                "setter.call(el, value);"
                "el.dispatchEvent(new Event('input', {bubbles: true}));"
                "el.dispatchEvent(new Event('change', {bubbles: true}));"
                "el.blur();"
                "}",
                values[0],
            )
        else:
            dynamic.fill(values[0])
        dynamic.press("Tab")
        if added_blank_row:
            # 新增 commits the manual row but also appends an empty row. Remove
            # only that trailing blank row before submitting the bill.
            deletes = drawer.get_by_text("删除", exact=True)
            visible_deletes = [
                deletes.nth(index)
                for index in range(deletes.count())
                if deletes.nth(index).is_visible()
            ]
            if visible_deletes:
                visible_deletes[-1].click()
                self.page.wait_for_timeout(500)

    def _fill_temporary_period(
        self, drawer: Locator, start: str, end: str
    ) -> None:
        inputs = drawer.locator("input.el-range-input:visible")
        if inputs.count() != 2:
            raise AssertionError(
                f"天数公式计费期间应有开始/结束两个输入框，实际 {inputs.count()} 个。"
            )
        inputs.nth(0).fill(start)
        inputs.nth(0).press("Enter")
        inputs.nth(1).fill(end)
        inputs.nth(1).press("Enter")
        inputs.nth(1).press("Tab")
        self.page.keyboard.press("Escape")
        expect(inputs.nth(0)).to_have_value(start, timeout=30_000)
        expect(inputs.nth(1)).to_have_value(end, timeout=30_000)

    def _select_temporary_area(self, drawer: Locator, area_type: str) -> None:
        label = drawer.get_by_text("计费面积", exact=True)
        if label.count() != 1:
            # In Standard1 the selected standard name already encodes the area
            # (建筑面积/使用面积/收费面积); the calculation drawer has no
            # separate area selector. Only interact when the field is actually
            # rendered by a variant.
            return
        row = label.locator("xpath=ancestor::*[.//input][1]")
        inputs = row.locator('input[readonly]:visible, input[placeholder="请选择"]:visible')
        if inputs.count() != 1:
            raise AssertionError(
                f"计费面积选择框应唯一，实际 {inputs.count()} 个。"
            )
        self._select_visible_dropdown_option(inputs.first, area_type)

    def _assert_temporary_amount(self, drawer: Locator, expected: str) -> None:
        if not expected:
            return
        # Formula results can coexist with an empty disabled input belonging
        # to a newly added blank row.  Match any settled control (or the total
        # text) instead of assuming the first disabled input is the result.
        normalized_amount = expected.rstrip("0").rstrip(".")
        pattern = re.compile(rf"^{re.escape(normalized_amount)}(?:\.0+)?$")
        for _ in range(120):
            amount = drawer.locator('input[placeholder="请输入"]:visible')
            for index in range(amount.count()):
                value = amount.nth(index).input_value().strip()
                if pattern.fullmatch(value):
                    return
            if re.search(
                rf"(?:出账金额|收费金额)\s*{re.escape(normalized_amount)}(?:\.0+)?",
                drawer.inner_text(),
            ):
                return
            self.page.wait_for_timeout(500)
        from pathlib import Path

        Path("artifacts").mkdir(exist_ok=True)
        Path("artifacts/calculation-temporary-amount-state.txt").write_text(
            drawer.inner_text(), encoding="utf-8"
        )
        self.page.screenshot(path="artifacts/calculation-temporary-amount-state.png", full_page=True)
        raise AssertionError(f"临时类出账金额未稳定为 {expected}")

    def configure_regular_calculation(
        self, drawer: Locator, data: CalculationData
    ) -> None:
        self._select_room(drawer, data.room_name)
        # The current regular-calculation drawer exposes month-range controls
        # for periodic and meter charge items alike.  The backend build that
        # required YYYY-MM-DD for meters was rolled back; entering full dates
        # here is normalized by the UI to YYYY-MM and must not be asserted as
        # a day range.
        self._select_month_range(drawer, data.billing_month)
        self._select_charge_item(drawer, data.charge_item)
        next_button = drawer.get_by_role(
            "button", name="已确认计算条件，下一步", exact=True
        )
        expect(next_button).to_be_enabled(timeout=30_000)

    def open_rule_details(self, drawer: Locator) -> Locator:
        drawer.get_by_role(
            "button", name="已确认计算条件，下一步", exact=True
        ).click()
        details = self.frame.locator(".el-drawer:visible").filter(
            has_text="计费规则明细"
        )
        expect(details).to_have_count(1, timeout=15_000)
        return details

    def configure_rule_dates(
        self, details: Locator, data: CalculationData
    ) -> None:
        self._set_rule_day(details, "应收日期", data.receivable_day)
        self._set_rule_day(details, "最晚缴款日期为", data.latest_payment_day)
        monthly_detail = details.get_by_text(data.billing_month.replace("-", "年") + "月")
        expect(monthly_detail).to_be_visible(timeout=15_000)
        expect(details).to_contain_text(f"{data.billing_month}-01")

    def start_calculation(self, details: Locator) -> None:
        buttons = self.frame.get_by_role("button", name="开始计算", exact=True)
        visible = [
            buttons.nth(index)
            for index in range(buttons.count())
            if buttons.nth(index).is_visible()
        ]
        if len(visible) != 1:
            # Some builds render the fixed footer outside the drawer subtree.
            text_buttons = self.frame.get_by_text("开始计算", exact=True)
            visible = [
                text_buttons.nth(index)
                for index in range(text_buttons.count())
                if text_buttons.nth(index).is_visible()
            ]
        if not visible:
            raise AssertionError("规则明细提交区未找到可见开始计算按钮。")
        # The page keeps the two home-card buttons mounted underneath the
        # drawer. The fixed footer action is the lowest visible matching
        # control; choose it by geometry rather than relying on DOM order.
        positioned = [(item, item.bounding_box()) for item in visible]
        positioned = [(item, box) for item, box in positioned if box is not None]
        target = max(positioned, key=lambda pair: pair[1]["y"])[0] if positioned else visible[-1]
        target.click(force=True)
        expect(self.frame.locator(".el-message:visible")).to_contain_text(
            "账单创建计算中", timeout=30_000
        )
        expect(details).to_be_hidden(timeout=30_000)

    def reconcile_and_approve(self, data: CalculationData) -> None:
        card = self._wait_for_pending_bill(data.billing_month)
        expect(card).to_contain_text("待核对", timeout=180_000)
        reconcile = card.get_by_text("核对账单", exact=True)
        if reconcile.count() != 1:
            reconcile = card.get_by_role("button", name="核对账单", exact=True)
        self.require_single(reconcile, "待核对账单操作").click(force=True)
        details = self._open_calculation_detail("待核对")
        submit = details.locator(".bottom-wrap .btn2")
        if submit.count() == 0:
            submit = details.get_by_role("button", name="提交审核", exact=True)
        self.require_single(submit, "提交审核操作").evaluate("el => el.click()")
        try:
            expect(self.frame.locator(".el-message:visible")).to_contain_text(
                "提交审核成功", timeout=10_000
            )
        except AssertionError:
            # The toast is short-lived on Standard1; closing the detail drawer
            # is the durable success signal and is followed by status polling.
            expect(details).to_be_hidden(timeout=30_000)

        audit_card = self._wait_for_pending_bill(data.billing_month, "审核账单")
        expect(audit_card).to_contain_text("待审核", timeout=30_000)
        audit = audit_card.get_by_text("审核账单", exact=True)
        if audit.count() != 1:
            audit = audit_card.get_by_role("button", name="审核账单", exact=True)
        self.require_single(audit, "待审核账单操作").click(force=True)
        audit_detail = self._open_calculation_detail("待审核")
        approve = audit_detail.locator(".bottom-wrap .btn2")
        if approve.count() == 0:
            approve = audit_detail.get_by_role("button", name="通过", exact=True)
        if approve.count() == 0:
            approve = audit_detail.get_by_text("通过", exact=True)
        self.require_single(approve, "审核通过操作").evaluate("el => el.click()")

        audit_containers = self.frame.locator(
            ".el-drawer:visible, .el-dialog:visible"
        ).filter(has_text="审核说明")
        if audit_containers.count() == 0:
            audit_containers = self.shell_frame.locator(
                ".el-drawer:visible, .el-dialog:visible"
            ).filter(has_text="审核说明")
        expect(audit_containers.first).to_be_visible(timeout=15_000)
        # Standard1 can render an outer drawer and a nested dialog with the
        # same label. Pick the smallest visible matching container so the
        # textbox and confirm button belong to the actual form.
        candidates = [
            audit_containers.nth(index)
            for index in range(audit_containers.count())
            if audit_containers.nth(index).is_visible()
        ]
        audit_drawer = (
            min(candidates, key=lambda item: item.locator("*").count())
            if len(candidates) > 1
            else candidates[0]
        )
        comment = self.require_single(
            audit_drawer.get_by_role("textbox"), "审核说明输入框"
        )
        comment.fill(data.audit_comment)
        expect(comment).to_have_value(data.audit_comment)
        confirm = audit_drawer.get_by_role("button", name="确定", exact=True)
        if confirm.count() == 0:
            confirm = audit_drawer.get_by_text("确定", exact=True)
        self.require_single(confirm, "审核确认操作").evaluate("el => el.click()")
        expect(self.frame.locator(".el-message:visible")).to_contain_text(
            re.compile(r"审核.*成功"), timeout=30_000
        )

    def cleanup_pending_records(
        self, reject_reason: str = "auto自动驳回"
    ) -> dict[str, int]:
        """清理本次失败可能留下的计费出账待处理卡片。

        只处理计费出账页的待处理数据，不进入账单中心。待审核卡片必须
        ``驳回 -> 填写理由 -> 确认 -> 删除``；待核对卡片可以直接从详情
        底部删除。该方法用于测试失败时的 finally 兜底，且不会在生产环境
        被调用（调用方负责检查删除开关）。
        """
        removed = {"待审核驳回删除": 0, "待核对删除": 0, "已驳回删除": 0}

        def visible(scope, locator):
            return [
                locator.nth(index)
                for index in range(locator.count())
                if locator.nth(index).is_visible()
            ]

        def scopes():
            return self._calculation_scopes()

        def last_drawer(scope):
            drawers = visible(scope, scope.locator(".el-drawer:visible"))
            if not drawers:
                raise AssertionError("清理待处理账单时未找到详情抽屉")
            return drawers[-1]

        def confirm(scope):
            buttons = visible(scope, scope.get_by_text("确定", exact=True))
            if len(buttons) != 1:
                raise AssertionError(
                    f"清理待处理账单确认按钮应唯一，实际可见 {len(buttons)} 个"
                )
            buttons[0].evaluate("el => el.click()")

        # 待审核：驳回后详情页才允许删除。
        while True:
            target = None
            target_scope = None
            for scope in scopes():
                actions = visible(scope, scope.get_by_text("审核账单", exact=True))
                if actions:
                    target, target_scope = actions[0], scope
                    break
            if target is None or target_scope is None:
                break
            target.evaluate("el => el.click()")
            self.page.wait_for_timeout(800)
            drawer = last_drawer(target_scope)
            reject = visible(drawer, drawer.locator(".bottom-wrap .btn1"))
            if len(reject) != 1:
                raise AssertionError("待审核详情未找到唯一驳回按钮")
            reject[0].evaluate("el => el.click()")
            self.page.wait_for_timeout(500)
            fields = visible(
                target_scope,
                target_scope.locator(
                    'input[placeholder="请输入"]:visible, '
                    'textarea[placeholder="请输入"]:visible'
                ),
            )
            if len(fields) != 1:
                raise AssertionError("驳回理由输入框应唯一")
            fields[0].fill(reject_reason)
            confirm(target_scope)
            self.page.wait_for_timeout(1_000)
            drawer = last_drawer(target_scope)
            delete = visible(drawer, drawer.locator(".bottom-wrap .btn1"))
            if len(delete) != 1:
                raise AssertionError("驳回后详情未找到唯一删除按钮")
            delete[0].evaluate("el => el.click()")
            confirm(target_scope)
            self.page.wait_for_timeout(1_000)
            removed["待审核驳回删除"] += 1

        # 待核对：详情底部的第一个操作是删除，直接删除即可。
        while True:
            target = None
            target_scope = None
            for scope in scopes():
                actions = visible(scope, scope.get_by_text("核对账单", exact=True))
                if actions:
                    target, target_scope = actions[0], scope
                    break
            if target is None or target_scope is None:
                break
            target.evaluate("el => el.click()")
            self.page.wait_for_timeout(800)
            drawer = last_drawer(target_scope)
            delete = visible(drawer, drawer.locator(".bottom-wrap .btn1"))
            if len(delete) != 1:
                raise AssertionError("待核对详情未找到唯一删除按钮")
            delete[0].evaluate("el => el.click()")
            confirm(target_scope)
            self.page.wait_for_timeout(1_000)
            removed["待核对删除"] += 1

        # 已驳回卡片：列表中直接提供删除操作。
        while True:
            target = None
            target_scope = None
            for scope in scopes():
                actions = visible(scope, scope.get_by_text("删除", exact=True))
                if actions:
                    target, target_scope = actions[0], scope
                    break
            if target is None or target_scope is None:
                break
            target.evaluate("el => el.click()")
            self.page.wait_for_timeout(500)
            confirm(target_scope)
            self.page.wait_for_timeout(1_000)
            removed["已驳回删除"] += 1

        return removed

    def assert_pending_amount(self, billing_month: str, expected_amount: str) -> None:
        card = self._wait_for_pending_bill(billing_month)
        normalized = expected_amount.replace(",", "")
        expect(card).to_contain_text(
            re.compile(rf"{re.escape(normalized)}(?:\.0+)?"), timeout=180_000
        )

    def open_bill_center_result(self) -> None:
        # 审核确认后的“已出账”状态由后台异步刷新。不能假设审核弹窗
        # 关闭后详情抽屉仍立即可用，按实际的“查看账单”操作等待即可。
        for _ in range(90):
            for scope in self._calculation_scopes():
                actions = scope.get_by_role("button", name="查看账单", exact=True)
                visible = [
                    actions.nth(index)
                    for index in range(actions.count())
                    if actions.nth(index).is_visible()
                ]
                if not visible:
                    # 当前版本将页脚动作渲染成带样式的 div，不能只依赖
                    # ARIA button 语义。
                    actions = scope.get_by_text("查看账单", exact=True)
                    visible = [
                        actions.nth(index)
                        for index in range(actions.count())
                        if actions.nth(index).is_visible()
                    ]
                if len(visible) == 1:
                    visible[0].click(force=True)
                    return
            self.page.wait_for_timeout(1_000)
        raise AssertionError("审核通过后未出现唯一可见的“查看账单”按钮。")

    def _select_room(self, drawer: Locator, room_name: str) -> None:
        room_triggers = drawer.get_by_text("请选择房间", exact=True)
        if room_triggers.count() != 1:
            room_triggers = drawer.locator("[placeholder='请选择房间']:visible")
        room_trigger = self.require_single(room_triggers, "请选择房间组件")
        room_trigger.click()
        # The calculation module has two tree implementations. Most builds
        # expose a searchable drawer; Standard1's temporary drawer teleports
        # a compact tree to the base-management frame without a search box.
        picker = None
        for scope in [self.frame, self.shell_frame, *self.page.frames]:
            candidates = scope.locator(".el-drawer:visible")
            for index in range(candidates.count() - 1, -1, -1):
                candidate = candidates.nth(index)
                if (
                    candidate.locator("input").count() >= 1
                    and candidate.get_by_text("选择房间", exact=False).count() > 0
                ):
                    picker = candidate
                    break
            if picker is not None:
                break
        if picker is not None and picker.get_by_placeholder("请输入").count() > 0:
            search = picker.get_by_placeholder("请输入").first
            expect(search).to_be_visible(timeout=15_000)
            # The room tree request is lazy-loaded.  Wait for the root node
            # before typing so a fast keystroke is not lost by the redraw.
            root = picker.get_by_text("A栋", exact=True)
            try:
                expect(root).to_be_visible(timeout=20_000)
            except AssertionError:
                # A filtered/virtualized tree may omit the root label; the
                # search input can still trigger the lazy query safely.
                self.page.wait_for_timeout(2_000)
            self.page.wait_for_timeout(1_500)
            try:
                search.fill("")
            except Exception:
                search.click()
                search.press("Control+A")
                search.press("Backspace")
            search.press_sequentially(room_name, delay=120)
            self.page.wait_for_timeout(2_000)
            search.press("Enter")
            room = picker.get_by_text(room_name, exact=True)
            try:
                expect(room).to_be_visible(timeout=30_000)
            except AssertionError:
                # Some Element UI builds teleport the filtered tree rows out
                # of the drawer.  Re-anchor to the one visible tree row in
                # the active frame instead of declaring the room absent.
                visible_rooms = []
                for scope in (self.frame, self.shell_frame, *self.page.frames):
                    candidates = scope.locator(
                        ".el-tree:visible .el-tree-node__content"
                    ).filter(has_text=room_name)
                    visible_rooms.extend(
                        candidates.nth(index)
                        for index in range(candidates.count())
                        if candidates.nth(index).is_visible()
                    )
                if len(visible_rooms) != 1:
                    raise
                room = visible_rooms[0].get_by_text(room_name, exact=True)
            tree_row = room.locator(
                "xpath=ancestor::*[contains(@class, 'el-tree-node__content')][1]"
            )
            checkbox = tree_row.locator(".el-checkbox__inner")
            if checkbox.count() == 0:
                checkbox = tree_row.locator("input[type='checkbox']")
            self.require_single(checkbox, "目标房间勾选框").click()
            self.page.wait_for_timeout(500)
            self._confirm_selection(picker)
        else:
            confirmed = False
            for attempt in range(3):
                if attempt:
                    room_trigger.click()
                    self.page.wait_for_timeout(500)
                try:
                    self._select_room_from_compact_tree(room_name)
                    expect(drawer).to_contain_text(room_name, timeout=5_000)
                    confirmed = True
                    break
                except AssertionError:
                    # A stale tooltip from another portal frame can consume
                    # the first selection. Reopen the same tree and retry;
                    # never substitute a different room or continue silently.
                    continue
            if not confirmed:
                raise AssertionError(f"确认房间 {room_name} 后主抽屉未显示房间标签。")
            return
        expect(drawer).to_contain_text(room_name, timeout=15_000)

    def _select_room_from_compact_tree(self, room_name: str) -> None:
        """Select a room in the Standard1 teleported compact tree."""
        parts = ["A栋", "1层", room_name]
        scope: Locator | None = None
        for _ in range(60):
            for candidate in self.page.frames:
                tooltips = candidate.get_by_role("tooltip")
                for index in range(tooltips.count()):
                    tooltip = tooltips.nth(index)
                    if not tooltip.is_visible():
                        continue
                    root = tooltip.get_by_text(parts[0], exact=True)
                    if (
                        root.count()
                        and root.first.is_visible()
                        and tooltip.get_by_role("tree").count() == 1
                        and tooltip.get_by_text("确定", exact=True).count() > 0
                    ):
                        # Multiple portal frames can expose a stale tree
                        # tooltip. Keep the last matching tree, which is the
                        # active billing selection popup.
                        scope = tooltip
            if scope is not None:
                break
            self.page.wait_for_timeout(500)
        if scope is None:
            raise AssertionError("房间树未加载出 A栋 根节点。")
        for index, part in enumerate(parts[:-1]):
            node_text = scope.get_by_text(part, exact=True)
            expect(node_text).to_be_visible(timeout=30_000)
            node = node_text.locator(
                "xpath=ancestor::*[contains(@class, 'el-tree-node')][1]"
            )
            expand = node.locator(".el-tree-node__expand-icon")
            next_part = parts[index + 1]
            next_node = scope.get_by_text(next_part, exact=True)
            if expand.count() == 1 and not (
                next_node.count() and next_node.first.is_visible()
            ):
                # The tree is teleported and may replace its node during the
                # async load; dispatch the native click on the current node
                # instead of waiting for Playwright's viewport stability.
                expand.evaluate("el => el.click()")
            expect(next_node).to_be_visible(timeout=60_000)
        leaf = scope.get_by_text(room_name, exact=True)
        expect(leaf).to_be_visible(timeout=60_000)
        row = leaf.locator(
            "xpath=ancestor::*[contains(@class, 'el-tree-node__content')][1]"
        )
        checkbox = row.locator(".el-checkbox__inner")
        if checkbox.count() == 0:
            checkbox = row.locator("label.el-checkbox")
        if checkbox.count() == 0:
            checkbox = row.locator("input[type='checkbox']")
        if checkbox.count() == 0:
            # Some versions wrap the leaf label in a node-content sibling;
            # re-anchor at the enclosing tree node before declaring the
            # selection control missing.
            node = leaf.locator(
                "xpath=ancestor::*[contains(@class, 'el-tree-node')][1]"
            )
            checkbox = node.locator("label.el-checkbox, .el-checkbox__inner")
        if checkbox.count() == 1:
            checkbox.click(force=True)
        else:
            # A compact tree build uses the leaf itself as the selectable
            # target. Click it only as an explicit DOM variant fallback; the
            # subsequent confirm/tag assertion remains mandatory.
            leaf.click(force=True)
        confirms = scope.get_by_text("确定", exact=True)
        visible_confirms = [
            confirms.nth(index)
            for index in range(confirms.count())
            if confirms.nth(index).is_visible()
        ]
        if not visible_confirms:
            raise AssertionError("房间树已选择但未找到确认按钮。")
        self.page.wait_for_timeout(500)
        visible_confirms[-1].evaluate("el => el.click()")
        self.page.wait_for_timeout(1_000)

    def _select_month_range(self, drawer: Locator, billing_month: str) -> None:
        inputs = drawer.locator("input.el-range-input:visible")
        if inputs.count() != 2:
            inputs = drawer.locator("input[placeholder*='月份']:visible")
        if inputs.count() != 2:
            raise AssertionError(
                f"计费账期应有两个开始/结束月份输入框，实际 {inputs.count()} 个。"
            )
        for index in (0, 1):
            inputs.nth(index).fill(billing_month)
            inputs.nth(index).press("Enter")
        self.page.keyboard.press("Escape")
        expect(inputs.nth(0)).to_have_value(billing_month)
        expect(inputs.nth(1)).to_have_value(billing_month)

    def _select_charge_item(self, drawer: Locator, charge_item: str) -> None:
        triggers = drawer.get_by_text("请选择计费费项", exact=True)
        if triggers.count() != 1:
            triggers = drawer.locator("[placeholder='请选择计费费项']:visible")
        input_box = self.require_single(triggers, "请选择计费费项组件")
        input_box.click()
        picker = self._selection_drawer("收费项")
        search = picker.get_by_placeholder("请输入").first
        expect(search).to_be_visible(timeout=15_000)
        # The search box is rendered before the fee-item tree data arrives.
        # Wait for an actual visible tree row, otherwise the first query can
        # race the asynchronous room/fee dependency request and return none.
        tree_rows = picker.locator(".el-tree-node__content:visible")
        expect(tree_rows.first).to_be_visible(timeout=60_000)
        self.page.wait_for_timeout(1_000)
        # The fee-item tree is populated asynchronously on Standard1.  A
        # direct fill followed immediately by lookup can race the filter
        # request, so type at UI speed, submit the filter, then wait for the
        # exact visible tree node.
        search.fill("")
        search.press_sequentially(charge_item, delay=120)
        search.press("Enter")
        self.page.wait_for_timeout(1_000)
        exact_item = picker.get_by_text(charge_item, exact=True)
        tree_item = picker.locator(".el-tree-node__content").filter(
            has_text=charge_item
        )
        # Depending on the Element UI build, the label is either a direct text
        # node or wrapped by a span inside the tree row.  Prefer the direct
        # label when present, otherwise use the uniquely matching tree row.
        item = exact_item
        if exact_item.count() == 0:
            item = tree_item
        expect(item).to_be_visible(timeout=60_000)
        item_row = item.locator(
            "xpath=ancestor::*[contains(@class, 'el-tree-node__content')][1]"
        )
        checkbox = item_row.locator(".el-checkbox__inner")
        if checkbox.count() == 0:
            checkbox = item_row.locator("input[type='checkbox']")
        self.require_single(checkbox, "目标收费项勾选框").click()
        self._confirm_selection(picker)
        expect(drawer).to_contain_text(charge_item, timeout=15_000)

    def _selection_drawer(self, expected_text: str) -> Locator:
        scopes = [self.frame, self.shell_frame, *self.page.frames]
        seen: set[str] = set()
        for scope in scopes:
            scope_key = getattr(scope, "url", repr(scope))
            if scope_key in seen:
                continue
            seen.add(scope_key)
            candidates = scope.locator(".el-drawer:visible")
            for index in range(candidates.count() - 1, -1, -1):
                candidate = candidates.nth(index)
                if candidate.locator("input").count() >= 1:
                    title = "选择房间" if expected_text == "房间" else "选择收费项"
                    if candidate.get_by_text(title, exact=False).count() > 0:
                        return candidate
        raise AssertionError(f"未找到包含搜索输入框的{expected_text}选择抽屉。")

    def _confirm_selection(self, picker: Locator) -> None:
        confirm = picker.get_by_role("button", name="确认", exact=True)
        target = picker
        if confirm.count() == 0:
            candidates = self.shell_frame.locator(".el-drawer:visible")
            for index in range(candidates.count() - 1, -1, -1):
                candidate = candidates.nth(index)
                possible = candidate.get_by_role("button", name="确认", exact=True)
                if possible.count() == 0:
                    possible = candidate.get_by_text("确定", exact=True)
                if possible.count() == 1:
                    confirm = possible
                    target = candidate
                    break
        self.require_single(confirm, "选择抽屉确认按钮").click()
        expect(target).to_be_hidden(timeout=15_000)

    def _set_rule_day(self, details: Locator, label: str, day: str) -> None:
        label_node = details.get_by_text(label, exact=True)
        expect(label_node).to_be_visible(timeout=15_000)
        row = label_node.locator("xpath=ancestor::*[.//input][1]")
        selectors = row.locator("input[readonly]:visible")
        if selectors.count() != 1:
            raise AssertionError(
                f"{label}规则行应有一个日选择框，实际 {selectors.count()} 个。"
            )
        selectors.first.click()
        visible = []
        for scope in (self.frame, self.shell_frame):
            option = scope.get_by_text(day, exact=True)
            visible.extend(
                option.nth(index)
                for index in range(option.count())
                if option.nth(index).is_visible()
            )
        if not visible:
            raise AssertionError(
                f"{label}的日选项 {day!r} 应唯一可见，实际 {len(visible)} 个。"
            )
        # Element UI's popup can briefly be covered by the drawer overlay while
        # it is being repositioned; force the click only after visibility was
        # established and the option list was deduplicated above.
        viewport = self.page.viewport_size or {"width": 0, "height": 0}
        in_view = []
        for candidate in visible:
            box = candidate.bounding_box()
            if box and 0 <= box["x"] < viewport["width"] and 0 <= box["y"] < viewport["height"]:
                in_view.append(candidate)
        # Let the Element UI select component commit its own change event.
        # This avoids clicking a cloned portal node that looks visible but is
        # not the active option list.
        selectors.first.press("ArrowDown")
        selectors.first.press("Enter")
        expect(selectors.first).to_have_value(day)

    def _wait_for_pending_bill(
        self, billing_month: str, action_text: str = "核对账单"
    ) -> Locator:
        scopes = self._calculation_scopes()
        for scope in scopes:
            tab = scope.get_by_text("待处理账单", exact=True)
            visible = [
                tab.nth(index)
                for index in range(tab.count())
                if tab.nth(index).is_visible()
            ]
            if visible:
                visible[-1].click(force=True)
                break
        pattern = re.compile(rf"账单\s*{re.escape(billing_month)}")
        deadline_ms = 180_000
        elapsed_ms = 0
        while elapsed_ms < deadline_ms:
            for scope in scopes:
                cards = scope.locator("*:visible").filter(has_text=pattern)
                # The action is a styled div in this module rather than a
                # semantic button. Use the exact card action text and choose
                # the smallest matching container, not DOM order.
                candidates = [
                    cards.nth(index)
                    for index in range(cards.count())
                    if cards.nth(index).get_by_text(action_text, exact=True).count() > 0
                ]
                if candidates:
                    return min(candidates, key=lambda item: item.locator("*").count())
            self.page.wait_for_timeout(1_000)
            elapsed_ms += 1_000
        from pathlib import Path
        Path("artifacts").mkdir(exist_ok=True)
        Path("artifacts/calculation-pending-timeout.txt").write_text(
            self.shell_frame.locator("body").inner_text(), encoding="utf-8"
        )
        raise AssertionError(f"待处理账单中等待 {billing_month} 账单卡片超时。")

    def _open_calculation_detail(self, expected_status: str) -> Locator:
        for scope in self._calculation_scopes():
            drawers = scope.locator(".el-drawer:visible")
            for index in range(drawers.count() - 1, -1, -1):
                drawer = drawers.nth(index)
                if drawer.get_by_text(expected_status, exact=True).count() > 0:
                    return drawer
                if expected_status in {"待核对", "待审核", "已出账"}:
                    # The detail drawer in some Standard1 builds omits the
                    # status pill, while retaining its business action/footer.
                    if (
                        drawer.get_by_text("审核说明", exact=True).count()
                        or drawer.get_by_text("通过", exact=True).count()
                        or drawer.get_by_text("查看账单", exact=True).count()
                        or drawer.locator(".bottom-wrap .btn2:visible").count() == 1
                    ):
                        return drawer
        raise AssertionError(f"未找到状态为 {expected_status} 的费用计算详情抽屉。")

    def _calculation_scopes(self) -> list[Frame | FrameLocator]:
        """Return active calculation frames without relying on iframe order."""
        scopes: list[Frame | FrameLocator] = [self.frame, self.shell_frame]
        scopes.extend(
            frame for frame in self.page.frames if "billChargeout" in frame.url
        )
        unique: list[Frame | FrameLocator] = []
        identities: set[int] = set()
        for scope in scopes:
            identity = id(scope)
            if identity not in identities:
                unique.append(scope)
                identities.add(identity)
        return unique
