from __future__ import annotations

from dataclasses import dataclass
import re
import time

from playwright.sync_api import FrameLocator, Locator, Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.pages.base_page import BasePage


@dataclass(frozen=True, slots=True)
class ChargeStandardData:
    name: str
    charge_type: str
    charge_item: str
    project_name: str
    formula: str
    area_type: str = ""
    partial_month_rule: str = ""
    monthly_unit_price: str = ""
    fixed_monthly_amount: str = ""
    coefficient: str = ""
    floor_tiers: tuple[tuple[str, str, str], ...] = ()
    floor_fixed_tiers: tuple[tuple[str, str, str], ...] = ()
    area_fixed_tiers: tuple[tuple[str, str, str], ...] = ()
    unit_price: str = ""
    fixed_amount: str = ""
    usage_price_tiers: tuple[tuple[str, str, str], ...] = ()
    usage_coefficient_tiers: tuple[tuple[str, str, str], ...] = ()
    merge_customer_room_usage: bool | None = None
    commission_percentage: str = ""
    commission_percentage_tiers: tuple[tuple[str, str, str], ...] = ()
    commission_amount_tiers: tuple[tuple[str, str, str], ...] = ()


class ChargeStandardPage(BasePage):
    PARTIAL_MONTH_UI_LABELS = {
        "按天": "按天计费",
        "按满月": "按满月计费",
    }

    def __init__(self, page: Page) -> None:
        self.page = page
        self.frame: FrameLocator = page.frame_locator(
            'iframe[src*="chargeStandard"]'
        )

    def open(self, expected_customer_id: str | None = None) -> None:
        existing_button = self.frame.get_by_role(
            "button", name="鏂板鏀惰垂鏍囧噯", exact=True
        )
        if existing_button.count() == 1 and existing_button.is_visible():
            if expected_customer_id:
                iframe_src = self.page.locator(
                    'iframe[src*="chargeStandard"]'
                ).get_attribute("src") or ""
                if f"customerId={expected_customer_id}" not in iframe_src:
                    raise AssertionError(
                        f"charge standard iframe customer context mismatch: {iframe_src}"
                    )
            return
        self.page.get_by_role("menuitem", name="云收费", exact=True).click()
        charge_settings = self.page.locator(
            'li.el-submenu[role="menuitem"]'
        ).filter(has_text="收费设置")
        expect(charge_settings).to_be_visible(timeout=30_000)
        if charge_settings.get_attribute("aria-expanded") != "true":
            charge_settings.click()
        standard_menu = self.page.get_by_role(
            "menuitem", name="收费标准管理", exact=True
        )
        expect(standard_menu).to_be_visible(timeout=15_000)
        standard_menu.click()
        create_button = self.frame.get_by_role(
            "button", name="新增收费标准", exact=True
        )
        try:
            expect(create_button).to_be_visible(timeout=30_000)
        except (AssertionError, PlaywrightTimeoutError):
            # 门户偶发恢复出一个已选中但内容为空的历史业务标签。
            # 关闭异步公告和这个空标签，再从左侧菜单重新打开。
            self._dismiss_portal_overlays()
            active_tab = self.page.locator(
                ".el-tabs__item.is-active"
            ).filter(has_text="收费标准管理")
            if active_tab.count() == 1:
                close_tab = active_tab.locator(".el-icon-close")
                if close_tab.count() == 1:
                    close_tab.click()
                    self.page.wait_for_timeout(500)
            charge_settings = self.page.locator(
                'li.el-submenu[role="menuitem"]'
            ).filter(has_text="收费设置")
            expect(charge_settings).to_be_visible(timeout=30_000)
            if charge_settings.get_attribute("aria-expanded") != "true":
                charge_settings.click()
            standard_menu = self.page.get_by_role(
                "menuitem", name="收费标准管理", exact=True
            )
            expect(standard_menu).to_be_visible(timeout=30_000)
            standard_menu.click()
            try:
                expect(create_button).to_be_visible(timeout=120_000)
            except (AssertionError, PlaywrightTimeoutError) as exc:
                frames = self.page.locator("iframe").evaluate_all(
                    "els => els.map(el => ({src: el.src, id: el.id}))"
                )
                raise AssertionError(
                    f"收费标准 iframe 重开后仍未就绪；iframe={frames}"
                ) from exc
        if expected_customer_id:
            iframe_src = self.page.locator(
                'iframe[src*="chargeStandard"]'
            ).get_attribute("src") or ""
            if f"customerId={expected_customer_id}" not in iframe_src:
                raise AssertionError(
                    "收费标准 iframe 客户上下文不匹配；"
                    f"期望 customerId={expected_customer_id}，实际 src={iframe_src}"
                )

    def _dismiss_portal_overlays(self) -> None:
        """只关闭门户公告/通知遮挡层，不触碰业务 iframe 内弹窗。"""
        for _ in range(10):
            close_buttons = self.page.locator(
                ".el-dialog__wrapper:visible .el-dialog__headerbtn, "
                ".el-drawer__wrapper:visible .el-drawer__close-btn"
            )
            if close_buttons.count() == 0:
                return
            close_buttons.last.click()
            self.page.wait_for_timeout(300)

    def exists(self, name: str) -> bool:
        self.cancel_open_create_dialog()
        search = self.require_single(
            self.frame.locator(
                'input[placeholder="请输入收费标准名称"]:visible'
            ),
            "收费标准名称查询框",
        )
        search_button = self.frame.locator("button").filter(
            has_text="搜索", has_not_text="高级搜索"
        )
        search_button = self.require_single(search_button, "普通搜索按钮")
        for _ in range(2):
            self._wait_for_no_messages(timeout=15_000)
            search.fill(name)
            try:
                search_button.click(timeout=5_000)
            except PlaywrightTimeoutError:
                self._wait_for_no_messages(timeout=15_000)
                search_button.click(timeout=10_000)
            self.page.wait_for_timeout(3_000)
            expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
                0, timeout=60_000
            )
            exact_cell = self.frame.locator("td").filter(has_text=name)
            for index in range(exact_cell.count()):
                if exact_cell.nth(index).inner_text().strip() == name:
                    return True
            self.page.wait_for_timeout(1_000)
        return False

    def _wait_for_no_messages(self, *, timeout: int) -> None:
        """Avoid a transient Element UI toast intercepting the search button."""
        messages = self.frame.locator(".el-message:visible, .el-notification:visible")
        try:
            expect(messages).to_have_count(0, timeout=min(timeout, 3_000))
        except (AssertionError, PlaywrightTimeoutError):
            self.page.keyboard.press("Escape")

    def create(self, data: ChargeStandardData) -> None:
        self.frame.get_by_role(
            "button", name="新增收费标准", exact=True
        ).click()
        dialog = self.require_single(
            self.frame.get_by_role("dialog"), "新增收费标准弹窗"
        )
        expect(dialog).to_be_visible(timeout=15_000)

        self.page.wait_for_timeout(1_500)
        self._select(dialog.get_by_placeholder("请选择收费类型"), data.charge_type)
        # The charge-item field is rebuilt after the project selection. Do
        # not keep a pre-refresh locator and inspect it with an immediate
        # count while Vue has temporarily detached the input.
        self._select_project(dialog, data.project_name)
        charge_item = dialog.get_by_placeholder("请选择收费项")
        expect(charge_item).to_have_count(1, timeout=20_000)
        expect(charge_item).to_be_visible(timeout=15_000)
        expect(charge_item).to_be_enabled(timeout=15_000)
        if data.charge_type == "抽成类":
            self._select_charge_item(charge_item, data.charge_item)
        else:
            self._select_charge_item(charge_item, data.charge_item)
        dialog.get_by_placeholder("请输入收费标准名称").fill(data.name)
        self._select(dialog.get_by_placeholder("请选择计费公式"), data.formula)

        if data.partial_month_rule:
            self._choose_text(
                dialog,
                self.PARTIAL_MONTH_UI_LABELS.get(
                    data.partial_month_rule, data.partial_month_rule
                ),
            )
        if data.area_type:
            self._choose_text(dialog, data.area_type)
        if data.monthly_unit_price:
            self._fill_labeled_number(
                dialog, "月单价", data.monthly_unit_price
            )
        if data.fixed_monthly_amount:
            self._fill_labeled_number(
                dialog, "月固定金额", data.fixed_monthly_amount
            )
        if data.coefficient:
            self._fill_labeled_number(dialog, "系数", data.coefficient)
        if data.floor_tiers:
            self._fill_floor_tiers(dialog, data.floor_tiers)
        if data.floor_fixed_tiers:
            self._fill_floor_fixed_amount_tiers(
                dialog, data.floor_fixed_tiers
            )
        if data.area_fixed_tiers:
            self._fill_area_fixed_amount_tiers(dialog, data.area_fixed_tiers)
        if data.unit_price:
            self._fill_exact_placeholder(dialog, "请输入单价", data.unit_price)
        if data.fixed_amount:
            self._fill_exact_placeholder(
                dialog, "请输入固定金额", data.fixed_amount
            )
        if data.usage_price_tiers:
            self._fill_two_usage_tiers(
                dialog, data.usage_price_tiers, value_placeholder="请输入单价"
            )
        if data.usage_coefficient_tiers:
            self._fill_two_usage_tiers(
                dialog, data.usage_coefficient_tiers, value_placeholder="请输入"
            )
        if data.merge_customer_room_usage is not None:
            self._set_merge_usage_switch(
                dialog, data.merge_customer_room_usage
            )
        if data.commission_percentage:
            self._fill_exact_placeholder(
                dialog, "请输入抽成比例", data.commission_percentage
            )
        if data.commission_percentage_tiers:
            self._fill_commission_tiers(
                dialog,
                data.commission_percentage_tiers,
                value_placeholder="请输入",
            )
        if data.commission_amount_tiers:
            self._fill_commission_tiers(
                dialog,
                data.commission_amount_tiers,
                value_placeholder="请输入金额",
            )

        self._assert_form(dialog, data)
        dialog.get_by_role("button", name="保 存", exact=True).click()
        try:
            expect(dialog).to_be_hidden(timeout=90_000)
        except AssertionError:
            # 后端偶发已经落库但弹窗不关闭。此时禁止再次提交；关闭弹窗，
            # 由调用方按收费标准名称精确回查作为最终结论。
            cancel = dialog.get_by_role("button", name="取 消", exact=True)
            expect(cancel).to_have_count(1)
            cancel.click()
            expect(dialog).to_be_hidden(timeout=15_000)

    def inspect_dynamic_fields(self, data: ChargeStandardData) -> dict:
        """填写公共字段并选择公式，返回动态字段结构，不保存。"""
        self.frame.get_by_role(
            "button", name="新增收费标准", exact=True
        ).click()
        dialog = self.require_single(
            self.frame.get_by_role("dialog"), "新增收费标准弹窗"
        )
        expect(dialog).to_be_visible(timeout=15_000)
        self.page.wait_for_timeout(1_500)
        self._select(dialog.get_by_placeholder("请选择收费类型"), data.charge_type)
        charge_item = dialog.get_by_placeholder("请选择收费项")
        expect(charge_item).to_be_enabled(timeout=15_000)
        if data.charge_type == "抽成类":
            self._select_project(dialog, data.project_name)
            self.page.wait_for_timeout(5_000)
            self._select_charge_item(charge_item, data.charge_item)
        else:
            self.page.wait_for_timeout(3_000)
            self._select_charge_item(charge_item, data.charge_item)
            self._select_project(dialog, data.project_name)
        dialog.get_by_placeholder("请输入收费标准名称").fill(data.name)
        self._select(dialog.get_by_placeholder("请选择计费公式"), data.formula)
        if data.partial_month_rule:
            self._choose_text(
                dialog,
                self.PARTIAL_MONTH_UI_LABELS.get(
                    data.partial_month_rule, data.partial_month_rule
                ),
            )
        if data.floor_tiers or "多阶梯" in data.formula or "累计用量" in data.formula:
            add_tier = dialog.get_by_role("button", name="新增", exact=True)
            if add_tier.count() == 1:
                add_tier.click()
        structure = dialog.evaluate(
            """el => ({
              text: el.innerText,
              inputs: [...el.querySelectorAll('input')].map(x => ({
                placeholder: x.placeholder,
                type: x.type,
                value: x.value,
                readonly: x.readOnly,
                outer: x.outerHTML.slice(0, 500)
              })),
              buttons: [...el.querySelectorAll('button')].map(x => x.innerText.trim()),
              tables: [...el.querySelectorAll('table')].map(x => x.innerText)
            })"""
        )
        dialog.get_by_role("button", name="取 消", exact=True).click()
        expect(dialog).to_be_hidden(timeout=15_000)
        return structure

    def delete_exact(self, name: str) -> None:
        """只删除精确名称且查询结果唯一的收费标准。"""
        self.cancel_open_create_dialog()
        if not self.exists(name):
            return
        row = self.frame.locator("tr").filter(has_text=name)
        exact_rows = []
        for index in range(row.count()):
            candidate = row.nth(index)
            cells = candidate.locator("td")
            if any(
                cells.nth(cell_index).inner_text().strip() == name
                for cell_index in range(cells.count())
            ):
                exact_rows.append(candidate)
        if len(exact_rows) != 1:
            raise AssertionError(
                f"收费标准 {name!r} 应唯一匹配一行，实际 {len(exact_rows)} 行。"
            )
        data_row = exact_rows[0]
        status_switch = data_row.locator(".el-switch:visible")
        status_switch = self.require_single(
            status_switch, "收费标准启用状态开关"
        )
        if "is-checked" in (status_switch.get_attribute("class") or ""):
            status_switch.click()
            expect(status_switch).not_to_have_class(
                re.compile(r".*\bis-checked\b.*"), timeout=30_000
            )
            expect(data_row).to_contain_text(
                re.compile(r"未启用|停用"), timeout=30_000
            )
            expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
                0, timeout=60_000
            )
        row_index = data_row.evaluate(
            "row => Array.from(row.parentElement.children).indexOf(row)"
        )
        fixed_rows = self.frame.locator(
            ".el-table__fixed-right .el-table__fixed-body-wrapper "
            "tr.el-table__row:visible"
        )
        operation_row = (
            fixed_rows.nth(row_index)
            if fixed_rows.count() > row_index
            else data_row
        )
        delete_button = operation_row.get_by_role(
            "button", name="删除", exact=True
        )
        if delete_button.count() == 0:
            delete_button = operation_row.get_by_text("删除", exact=True)
        expect(delete_button).to_have_count(1)
        delete_button.click()
        prompt_pattern = re.compile(r"是否确认删除|确认.*删除|删除后.*不可恢复")
        prompt = self.frame.get_by_text(prompt_pattern)
        try:
            expect(prompt).to_be_visible(timeout=15_000)
        except (AssertionError, PlaywrightTimeoutError):
            prompt = self.page.get_by_text(prompt_pattern)
            expect(prompt).to_be_visible(timeout=15_000)
        panel = prompt.locator("xpath=ancestor::*[.//button][1]")
        confirm = panel.get_by_role("button", name=re.compile(r"^确\s*定$"))
        confirm = self.require_single(confirm, "收费标准删除确认按钮")
        confirm.click()
        expect(panel).to_be_hidden(timeout=15_000)
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        self.page.wait_for_timeout(3_000)
        if self.exists(name):
            frame_messages = self.frame.locator(
                ".el-message:visible, .el-notification:visible, "
                ".el-message-box:visible"
            ).all_inner_texts()
            page_messages = self.page.locator(
                ".el-message:visible, .el-notification:visible, "
                ".el-message-box:visible"
            ).all_inner_texts()
            raise AssertionError(
                f"收费标准删除后仍可查询：{name}；"
                f"iframe提示={frame_messages}；门户提示={page_messages}"
            )

    def _select(
        self, input_locator: Locator, option: str, *, max_wait_ms: int = 30_000
    ) -> None:
        input_locator = self.require_single(input_locator, f"{option}选择框")
        options: list[str] = []
        input_locator.click()
        deadline = time.monotonic() + max_wait_ms / 1000
        while time.monotonic() < deadline:
            dropdowns = self.frame.locator(".el-select-dropdown:visible")
            matching_dropdowns: list[Locator] = []
            observed: list[str] = []
            for index in range(dropdowns.count()):
                dropdown = dropdowns.nth(index)
                observed.extend(dropdown.locator("li:visible").all_inner_texts())
                if dropdown.get_by_text(option, exact=True).count() == 1:
                    matching_dropdowns.append(dropdown)
            options = observed
            if matching_dropdowns:
                target = matching_dropdowns[-1].get_by_text(option, exact=True)
                try:
                    target.scroll_into_view_if_needed(timeout=2_000)
                    target.click(timeout=5_000)
                    expect(input_locator).to_have_value(option, timeout=5_000)
                    return
                except (AssertionError, PlaywrightTimeoutError):
                    self.page.keyboard.press("Escape")
                    input_locator.click()
                    self.page.wait_for_timeout(500)
                    continue
            self.page.wait_for_timeout(500)
        self.page.keyboard.press("Escape")
        raise AssertionError(
            f"下拉框未找到选项 {option!r}；最后可见选项：{options}"
        )

    def _select_charge_item(
        self, input_locator: Locator, option: str
    ) -> None:
        """收费项接口会异步刷新选择值，空值时有限重选。"""
        last_error: Exception | None = None
        for _ in range(3):
            try:
                # Project changes can briefly unmount/rebuild this select.
                # Wait for the exact field to return before require_single()
                # performs its intentionally immediate uniqueness check.
                expect(input_locator).to_have_count(1, timeout=15_000)
                expect(input_locator).to_be_visible(timeout=15_000)
                expect(input_locator).to_be_enabled(timeout=15_000)
                self._select(input_locator, option, max_wait_ms=30_000)
                expect(input_locator).to_have_value(option, timeout=5_000)
                self.page.wait_for_timeout(500)
                expect(input_locator).to_have_value(option, timeout=5_000)
                return
            except (AssertionError, PlaywrightTimeoutError) as exc:
                last_error = exc
            visible_dropdown = self.frame.locator(
                ".el-select-dropdown:visible"
            )
            if visible_dropdown.count():
                self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(1_500)
        raise AssertionError(
            f"收费项 {option!r} 未能稳定选择；最后一次错误：{last_error}"
        ) from last_error

    def _wait_for_formula_options(self, dialog: Locator) -> None:
        """收费项会异步加载公式；等到下拉中出现真实选项再继续。"""
        formula_input = self.require_single(
            dialog.get_by_placeholder("请选择计费公式"), "计费公式选择框"
        )
        self._wait_for_select_options(formula_input, "计费公式")

    def _wait_for_select_options(
        self, input_locator: Locator, label: str
    ) -> None:
        """等待 Element UI 异步下拉出现至少一个真实选项。"""
        input_locator = self.require_single(input_locator, f"{label}选择框")
        dropdown = self.frame.locator(".el-select-dropdown:visible")
        for _ in range(12):
            input_locator.click()
            expect(dropdown).to_have_count(1, timeout=10_000)
            if dropdown.locator("li:visible").count() > 0:
                self.page.keyboard.press("Escape")
                expect(dropdown).to_have_count(0, timeout=5_000)
                return
            self.page.keyboard.press("Escape")
            expect(dropdown).to_have_count(0, timeout=5_000)
            self.page.wait_for_timeout(1_500)
        input_locator.click()
        expect(dropdown).to_have_count(1, timeout=10_000)
        state = dropdown.inner_text().strip()
        self.page.keyboard.press("Escape")
        raise AssertionError(f"{label}异步加载超时；下拉状态：{state!r}")

    def cancel_open_create_dialog(self) -> None:
        dialog = self.frame.get_by_role("dialog")
        if dialog.count() != 1 or not dialog.is_visible():
            return
        cancel = dialog.get_by_role("button", name="取 消", exact=True)
        if cancel.count() == 1:
            cancel.click()
            expect(dialog).to_be_hidden(timeout=15_000)

    def _select_project(self, dialog: Locator, project_name: str) -> None:
        project_input = self.require_single(
            dialog.get_by_placeholder("请选择适用项目"), "适用项目选择框"
        )
        project_selector = project_input.locator(
            "xpath=ancestor::div[contains(@class, 'el-select')][1]"
        )
        project_selector = self.require_single(
            project_selector, "适用项目外层选择组件"
        )
        project_selector.click()
        popper = self.frame.locator(
            ".el-cascader__dropdown:visible, .el-select-dropdown:visible"
        )
        expect(popper).to_have_count(1, timeout=15_000)
        target = popper.get_by_text(project_name, exact=True)
        expect(target).to_have_count(1, timeout=15_000)
        target.click()
        self.page.keyboard.press("Escape")
        expect(popper).to_have_count(0, timeout=15_000)
        expect(dialog.get_by_text(project_name, exact=True)).to_be_visible(
            timeout=15_000
        )

    def _choose_text(self, dialog: Locator, text: str) -> None:
        target = dialog.get_by_text(text, exact=True)
        expect(target).to_have_count(1, timeout=15_000)
        target.click()

    def _fill_labeled_number(
        self, dialog: Locator, label: str, value: str
    ) -> None:
        placeholders = {
            "月单价": "请输入月单价",
            "月固定金额": "请输入月固定单价",
            "系数": "请输入系数",
        }
        input_box = dialog.get_by_placeholder(placeholders[label], exact=True)
        expect(input_box).to_have_count(1)
        input_box.fill(value)
        expect(input_box).to_have_value(value)

    def _fill_exact_placeholder(
        self, dialog: Locator, placeholder: str, value: str
    ) -> None:
        input_box = dialog.locator(
            f'input[placeholder="{placeholder}"]:visible'
        )
        expect(input_box).to_have_count(1)
        input_box.fill(value)
        expect(input_box).to_have_value(value)

    def _fill_two_usage_tiers(
        self,
        dialog: Locator,
        tiers: tuple[tuple[str, str, str], ...],
        *,
        value_placeholder: str,
    ) -> None:
        if len(tiers) != 2:
            raise AssertionError("当前仪表阶梯自动化仅支持低档和高档两档。")
        boundaries = dialog.locator(
            'input[type="number"][placeholder=""]:visible'
        )
        values = dialog.locator(
            f'input[type="number"][placeholder="{value_placeholder}"]:visible'
        )
        expect(boundaries).to_have_count(2, timeout=30_000)
        expect(values).to_have_count(2, timeout=30_000)
        low_upper, low_value, high_lower, high_value = (
            tiers[0][1], tiers[0][2], tiers[1][0], tiers[1][2]
        )
        boundaries.nth(0).fill(low_upper)
        boundaries.nth(1).fill(high_lower)
        values.nth(0).fill(low_value)
        values.nth(1).fill(high_value)
        expect(boundaries.nth(0)).to_have_value(low_upper)
        expect(boundaries.nth(1)).to_have_value(high_lower)
        expect(values.nth(0)).to_have_value(low_value)
        expect(values.nth(1)).to_have_value(high_value)

    def _set_merge_usage_switch(self, dialog: Locator, enabled: bool) -> None:
        switch = dialog.locator('input[type="checkbox"].el-switch__input')
        expect(switch).to_have_count(1)
        if switch.is_checked() != enabled:
            visible_switch = switch.locator("xpath=ancestor::div[contains(@class, 'el-switch')][1]")
            visible_switch.click()
        expect(switch).to_be_checked() if enabled else expect(switch).not_to_be_checked()

    def _fill_floor_tiers(
        self,
        dialog: Locator,
        tiers: tuple[tuple[str, str, str], ...],
    ) -> None:
        add_tier = dialog.get_by_role("button", name="新增", exact=True)
        expect(add_tier).to_have_count(1)
        for _ in tiers:
            add_tier.click()
            self.page.wait_for_timeout(500)

        minimums = dialog.locator('input[placeholder="最小值"]:visible')
        maximums = dialog.locator('input[placeholder="最大值"]:visible')
        prices = dialog.locator(
            'input[placeholder="请输入对应月单价"]:visible'
        )
        expect(minimums).to_have_count(len(tiers), timeout=30_000)
        expect(maximums).to_have_count(len(tiers), timeout=30_000)
        expect(prices).to_have_count(len(tiers), timeout=30_000)
        for index, (minimum, maximum, price) in enumerate(tiers):
            minimums.nth(index).fill(minimum)
            maximums.nth(index).fill(maximum)
            prices.nth(index).fill(price)
            expect(minimums.nth(index)).to_have_value(minimum)
            expect(maximums.nth(index)).to_have_value(maximum)
            expect(prices.nth(index)).to_have_value(price)

    def _fill_area_fixed_amount_tiers(
        self,
        dialog: Locator,
        tiers: tuple[tuple[str, str, str], ...],
    ) -> None:
        """填写面积固定金额的内置低档/高档两行。"""
        if len(tiers) != 2:
            raise AssertionError("面积固定金额当前仅支持低档和高档两档。")
        body = dialog.locator(".el-table__body-wrapper").filter(
            has_text="不大于"
        )
        expect(body).to_have_count(1, timeout=30_000)
        boundaries = body.locator('input[type="number"][placeholder=""]')
        amounts = body.locator(
            'input[type="number"][placeholder="请输入单价"]'
        )
        expect(boundaries).to_have_count(2, timeout=30_000)
        expect(amounts).to_have_count(2, timeout=30_000)
        low_upper, low_amount, high_lower, high_amount = (
            tiers[0][1], tiers[0][2], tiers[1][0], tiers[1][2]
        )
        for locator, value in (
            (boundaries.nth(0), low_upper),
            (amounts.nth(0), low_amount),
            (boundaries.nth(1), high_lower),
            (amounts.nth(1), high_amount),
        ):
            locator.fill(value)
            expect(locator).to_have_value(value)

    def _fill_floor_fixed_amount_tiers(
        self,
        dialog: Locator,
        tiers: tuple[tuple[str, str, str], ...],
    ) -> None:
        """新增并填写楼层阶梯固定金额。"""
        if len(tiers) != 2:
            raise AssertionError("楼层固定金额当前仅支持两档。")
        add_tier = dialog.get_by_role("button", name="新增", exact=True)
        expect(add_tier).to_have_count(1)
        for _ in tiers:
            add_tier.click()
            self.page.wait_for_timeout(500)

        minimums = dialog.locator('input[placeholder="最小值"]:visible')
        maximums = dialog.locator('input[placeholder="最大值"]:visible')
        amounts = dialog.locator(
            'input[placeholder="请输入对应月单价"]:visible'
        )
        expect(minimums).to_have_count(len(tiers), timeout=30_000)
        expect(maximums).to_have_count(len(tiers), timeout=30_000)
        expect(amounts).to_have_count(len(tiers), timeout=30_000)
        for index, (minimum, maximum, amount) in enumerate(tiers):
            minimums.nth(index).fill(minimum)
            maximums.nth(index).fill(maximum)
            amounts.nth(index).fill(amount)

    def _fill_commission_tiers(
        self,
        dialog: Locator,
        tiers: tuple[tuple[str, str, str], ...],
        *,
        value_placeholder: str,
    ) -> None:
        """填写抽成比例或固定抽成金额的内置阶梯。"""
        if len(tiers) not in {2, 3}:
            raise AssertionError("抽成阶梯自动化仅支持页面内置的两档或三档。")
        body = dialog.locator(".el-table__body-wrapper").filter(
            has_text="低于/等于"
        )
        expect(body).to_have_count(1, timeout=30_000)
        boundaries = body.locator(
            'input[type="number"][placeholder=""]:visible'
        )
        values = body.locator(
            f'input[placeholder="{value_placeholder}"]:visible'
        )
        expect(boundaries).to_have_count(2 * (len(tiers) - 1), timeout=30_000)
        expect(values).to_have_count(len(tiers), timeout=30_000)

        boundary_values: list[str] = []
        for index, (minimum, maximum, value) in enumerate(tiers):
            if index == 0:
                boundary_values.append(maximum)
            elif index == len(tiers) - 1:
                boundary_values.append(minimum)
            else:
                boundary_values.extend((minimum, maximum))
            values.nth(index).fill(value)
            expect(values.nth(index)).to_have_value(value)
        for locator, value in zip(boundaries.all(), boundary_values, strict=True):
            locator.fill(value)
            expect(locator).to_have_value(value)

    def _assert_form(
        self, dialog: Locator, data: ChargeStandardData
    ) -> None:
        expect(dialog.get_by_placeholder("请输入收费标准名称")).to_have_value(
            data.name
        )
        expect(dialog.get_by_placeholder("请选择收费类型")).to_have_value(
            data.charge_type
        )
        expect(dialog.get_by_placeholder("请选择收费项")).to_have_value(
            data.charge_item
        )
        expect(dialog.get_by_placeholder("请选择计费公式")).to_have_value(
            data.formula
        )
        expect(dialog.get_by_text(data.project_name, exact=True)).to_be_visible()
        if data.area_type:
            area = dialog.get_by_text(data.area_type, exact=True)
            expect(area).to_have_count(1)
        if data.partial_month_rule:
            rule = self.PARTIAL_MONTH_UI_LABELS.get(
                data.partial_month_rule, data.partial_month_rule
            )
            expect(dialog.get_by_text(rule, exact=True)).to_have_count(1)
