from __future__ import annotations

import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from playwright.sync_api import Frame, Locator, Page, expect

from src.config.settings import settings
from src.pages.base_page import BasePage
from src.pages.portal_page import PortalPage


@dataclass(frozen=True, slots=True)
class PublicShareSchemeCase:
    """One parameterized public-sharing scheme creation case."""

    case_id: str
    name: str
    method: str
    rooms: tuple[str, str]
    amount: str = "1000"
    allocations: tuple[str, str] | None = None
    billing_area: str | None = None
    unit_price: str = "2"
    first_tier_upper: str = "5"
    first_tier_coefficient: str = "3"
    second_tier_lower: str = "6"
    second_tier_coefficient: str = "5"
    charge_type: str = "周期性费用"
    charge_item: str = "公摊周期性收费项"
    charge_standard: str = "UI公摊周期性收费标准"
    instrument_type: str | None = None
    instrument_name: str | None = None
    incomplete_month_rule: str | None = None
    expected_area_total: str | None = None
    household_count: str = "2"
    floor_tiers: tuple[tuple[str, ...], tuple[str, ...]] | None = None


class PublicShareSchemePage(BasePage):
    """云收费公摊方案列表及新增抽屉。"""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.frame: Frame | None = None

    def open(self, project_name: str) -> None:
        portal = PortalPage(self.page)
        for attempt in range(2):
            try:
                portal.dismiss_home_overlays()
                cloud = portal._cloud_billing_entry()
                if cloud.is_visible():
                    cloud.click()
                settings_menu = self.page.locator(
                    'li.el-submenu[role="menuitem"]'
                ).filter(has_text="收费设置")
                expect(settings_menu).to_be_visible(timeout=30_000)
                if settings_menu.get_attribute("aria-expanded") != "true":
                    settings_menu.click()
                entry = self.page.get_by_role(
                    "menuitem", name="公摊方案", exact=True
                )
                expect(entry).to_be_visible(timeout=30_000)
                entry.click()
                self.frame = self._wait_for_frame()
                self.close_open_drawer()
                self._wait_ready()
                self.select_project(project_name)
                return
            except AssertionError as exc:
                if attempt != 0 or "业务子页返回错误路由" not in str(exc):
                    raise
                # A mounted WYSF subpage may remain at #/err even though the
                # portal shell is healthy. Reload the authenticated Home once
                # to discard stale iframe/Vue state, then reopen the tab.
                self.frame = None
                self.page.reload(wait_until="domcontentloaded")
                portal.open_home(
                    settings.base_url,
                    settings.master_customer_id,
                    environment=settings.test_environment,
                    account_role="default",
                )

    def select_project(self, project_name: str) -> None:
        frame = self._require_frame()
        selector = frame.locator(".jie-project")
        if selector.count() == 0:
            return
        selector = self.require_single(selector, "公摊方案项目选择器")
        current = selector.locator("span.textOverflow")
        if current.count() == 1 and current.inner_text().strip() == project_name:
            return
        selector.click()
        popover_id = selector.get_attribute("aria-describedby")
        if not popover_id:
            raise AssertionError("公摊方案项目选择器缺少弹层标识")
        popover = frame.locator(f"#{popover_id}:visible")
        expect(popover).to_be_visible(timeout=15_000)
        target = popover.get_by_text(project_name, exact=True)
        expect(target).to_have_count(1, timeout=30_000)
        target.click()
        expect(current).to_have_text(project_name, timeout=15_000)

    def create(self, case: PublicShareSchemeCase) -> None:
        frame = self._require_frame()
        self._wait_ready()
        add = frame.get_by_role("button", name="新增方案", exact=True)
        expect(add).to_be_visible(timeout=30_000)
        add.click()
        drawer = self._drawer()

        name_input = drawer.get_by_placeholder("请输入方案名称", exact=True)
        expect(name_input).to_be_visible(timeout=15_000)
        self._set_value(name_input, case.name)
        if case.instrument_type:
            self._create_instrument_scheme(drawer, case)
            return

        self._select_option(drawer, "请选择收费项类型", case.charge_type)
        try:
            self._select_option(
                drawer,
                "请选择收费项",
                case.charge_item,
                dependency_charge_type=case.charge_type,
            )
        except AssertionError:
            # Standard1 occasionally returns an empty dependent-item list on
            # the first drawer instance even though the type selection is
            # visible.  Reopen the drawer once to create a new component
            # instance and retry the same business selection; do not loop
            # indefinitely or hide a real data/configuration failure.
            self.close_open_drawer()
            add.click()
            drawer = self._drawer()
            name_input = drawer.get_by_placeholder("请输入方案名称", exact=True)
            self._set_value(name_input, case.name)
            self._select_option(drawer, "请选择收费项类型", case.charge_type)
            self._select_option(
                drawer,
                "请选择收费项",
                case.charge_item,
                dependency_charge_type=case.charge_type,
            )
        self._select_option(drawer, "请选择收费标准", case.charge_standard)
        self._select_option(drawer, "请选择公摊方式", case.method)

        if case.method == "按房间设置比例分摊":
            self._fill_amount(drawer, case.amount)
        elif case.method == "按房间设置金额分摊":
            self._fill_amount(drawer, case.amount)
        elif case.method == "按住户面积及所在楼层对应系数公摊":
            self._fill_area_fields(drawer, case)
        else:
            raise ValueError(f"不支持的周期公摊方式: {case.method}")

        self._select_rooms(drawer, case.rooms)
        if case.allocations:
            inputs = drawer.locator('input[placeholder="请输入"]:visible')
            expect(inputs).to_have_count(len(case.allocations), timeout=15_000)
            for input_locator, value in zip(inputs.all(), case.allocations):
                self._set_value(input_locator, value)

        save = drawer.get_by_role("button", name=re.compile(r"保\s*存"))
        expect(save).to_have_count(1, timeout=15_000)
        expect(save).to_be_enabled(timeout=15_000)
        save.click()
        self._assert_saved(drawer, case.name)

    def _create_instrument_scheme(
        self, drawer: Locator, case: PublicShareSchemeCase
    ) -> None:
        """Create a meter-sharing scheme through the shared instrument flow.

        Meter type, instrument, charge item/standard, room pair and rules are
        scenario data; all four meter kinds use this same UI sequence.
        """
        if not case.instrument_type or not case.instrument_name:
            raise ValueError("仪表公摊用例必须设置仪表类型和公摊仪表名称")
        if not case.incomplete_month_rule:
            raise ValueError("仪表公摊用例必须设置不足月公摊规则")

        self._select_option(drawer, "请选择收费项类型", case.charge_type)
        self._select_option(drawer, "请选择仪表类型", case.instrument_type)
        self._select_option(drawer, "请选择公摊仪表", case.instrument_name)
        self._select_option(
            drawer,
            "请选择收费项",
            case.charge_item,
            dependency_charge_type=case.charge_type,
        )
        self._select_option(drawer, "请选择收费标准", case.charge_standard)
        self._select_option(drawer, "请选择公摊方式", case.method)

        if case.method == "按户分摊":
            self._assert_auto_amount(drawer, case.household_count)
        elif case.method == "按计费面积分摊":
            self._select_meter_area(drawer, case, assert_total=True)
        elif case.method == "按住户所在楼层对应系数分摊":
            self._fill_instrument_tiers(drawer, case)
        elif case.method == "按住户计费面积对应系数分摊":
            self._select_meter_area(drawer, case, assert_total=False)
            self._fill_instrument_tiers(drawer, case)
        else:
            raise ValueError(f"不支持的仪表公摊方式: {case.method}")

        self._select_meter_rule(drawer, case.incomplete_month_rule)
        self._assert_instrument_rooms(drawer, case.rooms)

        save = drawer.get_by_role("button", name=re.compile(r"保\s*存"))
        expect(save).to_have_count(1, timeout=15_000)
        expect(save).to_be_enabled(timeout=15_000)
        save.click()
        self._assert_saved(drawer, case.name)

    def _select_meter_area(
        self,
        drawer: Locator,
        case: PublicShareSchemeCase,
        *,
        assert_total: bool,
    ) -> None:
        area_name = case.billing_area or "建筑面积"
        radio = drawer.locator("label.el-radio").filter(has_text=area_name)
        expect(radio).to_have_count(1, timeout=15_000)
        radio.click()
        expect(radio.locator('input[type="radio"]')).to_be_checked(
            timeout=15_000
        )
        if assert_total:
            amount = self._meter_amount_input(drawer)
            expect(amount).to_be_visible(timeout=15_000)
            if case.expected_area_total is not None:
                expect(amount).to_have_value(
                    case.expected_area_total, timeout=15_000
                )
            else:
                self._assert_meter_area_sum(drawer, amount, area_name)

    def _assert_meter_area_sum(
        self, drawer: Locator, amount: Locator, area_name: str
    ) -> None:
        table = drawer.locator(".el-table:visible").filter(has_text="房间名称")
        expect(table).to_have_count(1, timeout=15_000)
        rows = table.locator(".el-table__body-wrapper tr:visible")
        expect(rows).to_have_count(2, timeout=15_000)
        values: list[Decimal] = []
        for row in rows.all():
            cells = row.locator("td")
            expect(cells).to_have_count(2, timeout=15_000)
            area_text = cells.nth(1).inner_text()
            match = re.search(r"\d+(?:,\d{3})*(?:\.\d+)?", area_text)
            if not match:
                raise AssertionError(
                    f"公摊房间 {area_name} 单元格没有有效面积：{area_text!r}"
                )
            try:
                values.append(Decimal(match.group().replace(",", "")))
            except InvalidOperation as exc:
                raise AssertionError(f"无法解析房间面积 {area_text!r}") from exc
        expected = sum(values, Decimal("0")).quantize(Decimal("0.01"))
        raw_actual = amount.input_value().strip().replace(",", "")
        try:
            actual = Decimal(raw_actual).quantize(Decimal("0.01"))
        except InvalidOperation as exc:
            raise AssertionError(
                f"页面未自动生成有效的{area_name}合计：{raw_actual!r}"
            ) from exc
        if expected <= 0 or actual != expected:
            raise AssertionError(
                f"公摊{area_name}合计错误：两房间面积={[str(v) for v in values]}，"
                f"应为 {expected}，页面为 {actual}"
            )

    def _assert_auto_amount(self, drawer: Locator, expected: str) -> None:
        amount = self._meter_amount_input(drawer)
        expect(amount).to_be_visible(timeout=15_000)
        expect(amount).to_have_value(expected, timeout=15_000)

    @staticmethod
    def _meter_amount_input(drawer: Locator) -> Locator:
        matches = drawer.locator(
            'input[placeholder*="公摊"][placeholder*="面积"]:visible'
        )
        if matches.count() == 1:
            return matches
        inputs = drawer.locator("input:visible")
        fields = []
        for input_locator in inputs.all():
            placeholder = input_locator.get_attribute("placeholder") or ""
            aria_label = input_locator.get_attribute("aria-label") or ""
            fields.append(
                {
                    "placeholder": placeholder.encode(
                        "ascii", "backslashreplace"
                    ).decode("ascii"),
                    "aria_label": aria_label.encode(
                        "ascii", "backslashreplace"
                    ).decode("ascii"),
                    "value": input_locator.input_value().encode(
                        "ascii", "backslashreplace"
                    ).decode("ascii"),
                }
            )
        raise AssertionError(
            "仪表公摊户数/面积输入框未唯一匹配；"
            f"matched={matches.count()}, visibleInputs={fields!r}"
        )

    def _select_meter_rule(self, drawer: Locator, rule: str) -> None:
        radio = drawer.locator("label.el-radio").filter(has_text=rule)
        expect(radio).to_have_count(1, timeout=15_000)
        radio.click()
        expect(radio.locator('input[type="radio"]')).to_be_checked(
            timeout=15_000
        )

    def _fill_instrument_tiers(
        self, drawer: Locator, case: PublicShareSchemeCase
    ) -> None:
        if case.floor_tiers is None:
            raise ValueError(f"{case.method}用例必须提供阶梯参数")
        tables = drawer.locator(".el-table:visible").filter(
            has_text=re.compile(r"楼层|面积")
        )
        candidates = []
        for index in range(tables.count()):
            table = tables.nth(index)
            text = table.inner_text()
            if "系数" in text and ("户数" in text or "面积" in text):
                candidates.append(table)
        if len(candidates) != 1:
            raise AssertionError(
                f"无法唯一定位仪表公摊系数阶梯表: candidates={len(candidates)}"
            )
        rows = candidates[0].locator(".el-table__body-wrapper tr:visible")
        expect(rows).to_have_count(2, timeout=15_000)
        for row, values in zip(rows.all(), case.floor_tiers):
            inputs = row.locator("input:visible")
            expect(inputs).to_have_count(len(values), timeout=15_000)
            for input_locator, value in zip(inputs.all(), values):
                if value:
                    self._set_value(input_locator, value)

    def _assert_instrument_rooms(
        self, drawer: Locator, rooms: tuple[str, str]
    ) -> None:
        table = drawer.locator(".el-table:visible").filter(has_text="房间名称")
        expect(table).to_have_count(1, timeout=15_000)
        rows = table.locator(".el-table__body-wrapper tr:visible")
        expect(rows).to_have_count(len(rooms), timeout=30_000)
        row_texts = rows.all_inner_texts()
        for room in rooms:
            matches = [
                text
                for text in row_texts
                if re.search(rf"(?<!\d){re.escape(room)}(?!\d)", text)
            ]
            if len(matches) != 1:
                raise AssertionError(
                    f"仪表自动带出的房间行不匹配 {room!r}；"
                    f"当前房间行={row_texts!r}"
                )

    def search(self, name: str) -> None:
        frame = self._require_frame()
        self.close_open_drawer()
        search_input = frame.locator(
            'input.el-input__key[placeholder="请输入方案名称"]:visible'
        )
        expect(search_input).to_have_count(1, timeout=15_000)
        self._set_value(search_input, name)
        search = frame.locator(".search-btn button:visible").first
        expect(search).to_be_visible(timeout=15_000)
        search.click()
        expect(frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )

    def assert_scheme(self, case: PublicShareSchemeCase) -> None:
        self.search(case.name)
        row = self._row(case.name)
        expect(row).to_have_count(1, timeout=30_000)
        expect(row).to_contain_text(case.charge_type)
        expect(row).to_contain_text(case.charge_item)
        if case.instrument_type:
            expect(row).to_contain_text(case.instrument_type)
            # The instrument list renders the method label without its leading
            # "按" in some versions; the selected control is verified before
            # save, so accept either exact or normalized list text.
            method_label = case.method.removeprefix("按")
            if method_label not in row.inner_text():
                actual = row.inner_text().encode(
                    "ascii", "backslashreplace"
                ).decode("ascii")
                expected = method_label.encode(
                    "ascii", "backslashreplace"
                ).decode("ascii")
                raise AssertionError(
                    f"仪表公摊列表未显示所选方式；expected={expected}, row={actual}"
                )
        else:
            expect(row).to_contain_text(case.method)

    def exists(self, name: str) -> bool:
        self.search(name)
        return self._row(name).count() == 1

    def delete(self, name: str) -> None:
        """Delete one explicitly-owned AT scheme and verify it is absent."""
        frame = self._require_frame()
        self.search(name)
        row = self._row(name)
        expect(row).to_have_count(1, timeout=30_000)
        operation_row = self._operation_row(row, name)
        delete = operation_row.get_by_text("删除", exact=True)
        if delete.count() == 0:
            delete = operation_row.get_by_role("button", name="删除", exact=True)
        expect(delete).to_have_count(1, timeout=15_000)
        delete.click()

        prompt = frame.get_by_text(
            re.compile(r"是否确认删除|确认是否删除|确认删除|删除后不可恢复")
        )
        expect(prompt).to_be_visible(timeout=15_000)
        panel = prompt.locator("xpath=ancestor::*[.//button][1]")
        confirm = panel.get_by_role("button", name=re.compile(r"^(确定|确认)$"))
        expect(confirm).to_be_visible(timeout=15_000)
        confirm.click()
        expect(
            frame.locator(".el-message--success:visible").filter(
                has_text=re.compile(r"删除成功|操作成功")
            )
        ).to_be_visible(timeout=30_000)
        self.search(name)
        expect(self._row(name)).to_have_count(0, timeout=30_000)

    def delete_if_exists(self, name: str) -> bool:
        """Delete only a named automation record; never broad-delete rows."""
        if not name.startswith("AT-"):
            raise ValueError("公摊方案清理只允许删除 AT- 前缀的自动化方案")
        if not self.exists(name):
            return False
        self.delete(name)
        return True

    def close_open_drawer(self) -> None:
        if self.frame is None:
            return
        drawer = self.frame.locator(".add-scheme-drawer:visible")
        if drawer.count() == 0:
            return
        close = drawer.get_by_role("button", name="关闭", exact=True)
        if close.count() == 1:
            close.evaluate("element => element.click()")
        expect(drawer).to_be_hidden(timeout=15_000)

    def _operation_row(self, data_row: Locator, name: str) -> Locator:
        frame = self._require_frame()
        expect(data_row).to_have_count(1, timeout=15_000)
        row_index = data_row.evaluate(
            "row => Array.from(row.parentElement.children).indexOf(row)"
        )
        fixed_rows = frame.locator(
            ".el-table__fixed-right .el-table__fixed-body-wrapper "
            "tr.el-table__row:visible"
        )
        if fixed_rows.count() > row_index:
            return fixed_rows.nth(row_index)
        if data_row.get_by_text("删除", exact=True).count():
            return data_row
        raise AssertionError(
            f"公摊方案 {name!r} 未找到对应固定右侧操作行："
            f"row_index={row_index}, fixed_rows={fixed_rows.count()}"
        )

    def _assert_saved(self, drawer: Locator, name: str) -> None:
        frame = self._require_frame()
        self.page.wait_for_timeout(1_500)
        errors = drawer.locator(".el-form-item__error:visible")
        if errors.count():
            raise AssertionError("公摊方案表单校验失败: " + " | ".join(errors.all_inner_texts()))
        if drawer.is_visible():
            messages = frame.locator(".el-message:visible").all_inner_texts()
            message_classes = frame.locator(".el-message:visible").evaluate_all(
                "els => els.map(el => el.className)"
            )
            failed_messages = frame.locator(
                ".el-message--error:visible, .el-message--warning:visible"
            ).all_inner_texts()
            if failed_messages:
                tables = drawer.locator(".el-table:visible")
                table_texts = tables.all_inner_texts()
                input_state = drawer.locator("input:visible").evaluate_all(
                    "els => els.map(el => ({placeholder: el.placeholder, value: el.value, type: el.type}))"
                )
                safe_diagnostic = repr(
                    {
                        "messages": [
                            str(item).encode("ascii", "backslashreplace").decode("ascii")
                            for item in failed_messages
                        ],
                        "tables": [
                            str(item).encode("ascii", "backslashreplace").decode("ascii")
                            for item in table_texts
                        ],
                        "inputs": [
                            {
                                key: str(value)
                                .encode("ascii", "backslashreplace")
                                .decode("ascii")
                                for key, value in item.items()
                            }
                            for item in input_state
                        ],
                    }
                )
                raise AssertionError(
                    "公摊方案保存时页面返回警告/错误，未判为成功："
                    + safe_diagnostic
                )
            # The current UI shows a success toast but keeps the drawer open.
            # Treat that as a successful save, close the drawer explicitly,
            # then verify the persisted row.  Keep diagnostics ASCII-safe so
            # Windows GBK output cannot mask the real assertion.
            success_toast = frame.locator(".el-message.el-message--success:visible")
            safe_messages = [str(item).encode("ascii", "backslashreplace").decode("ascii") for item in messages]
            safe_classes = [str(item).encode("ascii", "backslashreplace").decode("ascii") for item in message_classes]
            print(
                "[public-share-debug] drawer-visible messages=",
                safe_messages,
                "classes=",
                safe_classes,
                flush=True,
            )
            if success_toast.count() > 0:
                close = drawer.get_by_role("button", name="关闭", exact=True)
                if close.count() == 1:
                    close.evaluate("element => element.click()")
                expect(drawer).to_be_hidden(timeout=15_000)
                self.search(name)
                expect(self._row(name)).to_have_count(1, timeout=30_000)
                return
        expect(drawer).to_be_hidden(timeout=30_000)
        # 保存成功后页面返回方案列表；用方案名称再次查询，作为最终业务断言。
        self.search(name)
        expect(self._row(name)).to_have_count(1, timeout=30_000)
        messages = frame.locator(".el-message:visible")
        if messages.count():
            expect(messages.first).to_contain_text(re.compile(r"成功|保存"))

    def _fill_amount(self, drawer: Locator, amount: str) -> None:
        target = drawer.get_by_placeholder("请输入公摊金额", exact=True)
        expect(target).to_be_visible(timeout=15_000)
        self._set_value(target, amount)

    def _fill_area_fields(self, drawer: Locator, case: PublicShareSchemeCase) -> None:
        if not case.billing_area:
            raise ValueError("面积系数公摊必须指定 billing_area")
        area = drawer.get_by_text(case.billing_area, exact=True)
        expect(area).to_have_count(1, timeout=15_000)
        area.click()
        unit = drawer.get_by_placeholder("请输入标准面积单价", exact=True)
        expect(unit).to_be_visible(timeout=15_000)
        self._set_value(unit, case.unit_price)

        # 页面以两行阶梯表呈现“低于等于/高于等于”和“系数”输入框；
        # 上限输入框没有 placeholder，不能只按 placeholder 筛选。
        all_inputs = drawer.locator("input:visible")
        unit_index = next(
            (
                index
                for index in range(all_inputs.count())
                if all_inputs.nth(index).get_attribute("placeholder")
                == "请输入标准面积单价"
            ),
            -1,
        )
        if unit_index < 0:
            raise AssertionError("未定位到标准面积单价输入框")
        tier_group = drawer.locator("input:visible")
        if tier_group.count() < unit_index + 5:
            raise AssertionError(
                f"面积系数阶梯输入框数量不足: total={tier_group.count()}, unit_index={unit_index}"
            )
        tier_inputs = [tier_group.nth(unit_index + offset) for offset in range(1, 5)]
        self._set_value(tier_inputs[0], case.first_tier_upper)
        self._set_value(tier_inputs[1], case.first_tier_coefficient)
        # 当前后端校验阶梯必须连续且非空：第一行 <=5，第二行从 6
        # 起算。旧流程文档曾要求留空，实际页面会以“阶梯必须连续且不能为空”拒绝保存，
        # 因此这里采用与首行连续的下限，并将该兼容规则沉淀到产品知识中。
        self._set_value(tier_inputs[2], case.second_tier_lower)
        self._set_value(tier_inputs[3], case.second_tier_coefficient)

    def _select_rooms(self, drawer: Locator, rooms: tuple[str, str]) -> None:
        frame = self._require_frame()
        picker = drawer.locator(".jie-poper-input:visible")
        expect(picker).to_have_count(1, timeout=15_000)
        picker.click()
        popover_id = picker.get_attribute("aria-describedby")
        if not popover_id:
            raise AssertionError("公摊房间选择器缺少弹层标识")
        popover = frame.locator(f"#{popover_id}:visible")
        expect(popover).to_be_visible(timeout=15_000)

        # 当前项目树的稳定层级为 A栋→1层；房间叶子节点再按名称精确定位。
        building = popover.get_by_text("A栋", exact=True)
        expect(building).to_have_count(1, timeout=15_000)
        building.click()
        floor = popover.get_by_text("1层", exact=True)
        expect(floor).to_have_count(1, timeout=15_000)
        floor.click()
        for room in rooms:
            room_text = popover.get_by_text(room, exact=True)
            expect(room_text).to_have_count(1, timeout=15_000)
            content = room_text.locator(
                "xpath=ancestor::div[contains(@class, 'el-tree-node__content')][1]"
            )
            checkbox = content.locator("label.el-checkbox")
            expect(checkbox).to_have_count(1, timeout=15_000)
            # Element UI 的原生 checkbox 被隐藏，直接触发其 label 点击事件比
            # 依赖坐标稳定；Vue 仍会同步更新选中状态。
            checkbox.evaluate("element => element.click()")

        confirm = popover.get_by_role("button", name="确定", exact=True)
        expect(confirm).to_have_count(1, timeout=15_000)
        confirm.evaluate("element => element.click()")
        room_table = drawer.locator(".el-table").filter(has_text="房间名称")
        expect(room_table).to_have_count(1, timeout=15_000)
        rows = room_table.locator(".el-table__body-wrapper tr:visible")
        expect(rows).to_have_count(2, timeout=15_000)
        for room in rooms:
            expect(rows.filter(has_text=room)).to_have_count(1, timeout=15_000)

    @staticmethod
    def _set_value(locator: Locator, value: str) -> None:
        locator.fill(value)
        if locator.input_value() == value:
            return
        locator.click()
        locator.press("Control+A")
        locator.type(value)
        locator.press("Tab")
        if locator.input_value() != value:
            raise AssertionError(
                f"输入框值未生效: expected={value!r}, actual={locator.input_value()!r}"
            )

    def _select_option(
        self,
        drawer: Locator,
        placeholder: str,
        option: str,
        *,
        dependency_charge_type: str | None = None,
    ) -> None:
        frame = self._require_frame()
        field = drawer.get_by_placeholder(placeholder, exact=True)
        expect(field).to_be_visible(timeout=15_000)
        field.click()
        deadline = time.monotonic() + 30
        refreshed_dependency = False
        while time.monotonic() < deadline:
            dropdown = frame.locator(".el-select-dropdown:visible")
            if dropdown.count() == 1:
                target = dropdown.locator(".el-select-dropdown__item").filter(
                    has_text=option
                )
                if target.count() == 1:
                    target.click()
                    expect(field).to_have_value(option, timeout=15_000)
                    # 收费项/收费标准列表由上一层选择异步加载；给 Vue 变更和
                    # 后端请求一个短窗口，避免马上打开下一级时看到空列表。
                    self.page.wait_for_timeout(1_200)
                    return
            if (
                placeholder == "请选择收费项"
                and dependency_charge_type
                and not refreshed_dependency
                and time.monotonic() + 24 < deadline
            ):
                # 标准1偶发先渲染空的收费项下拉，但重新触发上一级类型变更
                # 后接口会返回同一项目的收费项列表。
                refreshed_dependency = True
                frame.locator("body").press("Escape")
                self._select_option(
                    drawer,
                    "请选择收费项类型",
                    dependency_charge_type,
                )
                field.click()
            self.page.wait_for_timeout(500)
        options = []
        dropdown = frame.locator(".el-select-dropdown:visible")
        if dropdown.count() == 1:
            options = dropdown.locator(".el-select-dropdown__item").all_inner_texts()
        raise AssertionError(
            f"下拉框 {placeholder!r} 未出现选项 {option!r}；当前选项={options!r}"
        )

    def _row(self, name: str) -> Locator:
        frame = self._require_frame()
        rows = frame.locator(
            ".el-table__body-wrapper:not(.el-table__fixed-body-wrapper) tr:visible"
        ).filter(has_text=name)
        return rows

    def _drawer(self) -> Locator:
        frame = self._require_frame()
        drawers = frame.locator(".add-scheme-drawer:visible")
        return self.require_single(drawers, "新增公摊方案抽屉")

    def _wait_ready(self) -> None:
        frame = self._require_frame()
        expect(frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        expect(
            frame.get_by_role("button", name="新增方案", exact=True)
        ).to_be_visible(timeout=30_000)

    def _wait_for_frame(self) -> Frame:
        deadline = time.monotonic() + 60
        error_seen_at: float | None = None
        while time.monotonic() < deadline:
            for frame in self.page.frames:
                if frame == self.page.main_frame:
                    continue
                try:
                    if frame.get_by_role(
                        "button", name="新增方案", exact=True
                    ).is_visible():
                        return frame
                except Exception:
                    pass
            error_frames = [
                frame
                for frame in self.page.frames
                if frame != self.page.main_frame
                and "#/err" in frame.url
                and "sharingScheme" in frame.url
            ]
            if error_frames:
                error_seen_at = error_seen_at or time.monotonic()
                if time.monotonic() - error_seen_at >= 4:
                    try:
                        error_text = error_frames[-1].locator("body").inner_text(
                            timeout=1_000
                        )[:300]
                    except Exception:
                        error_text = ""
                    safe_error = error_text.encode(
                        "ascii", "backslashreplace"
                    ).decode("ascii")
                    raise AssertionError(
                        "公摊方案业务子页返回错误路由 #/err；"
                        f"body={safe_error}"
                    )
            else:
                error_seen_at = None
            self.page.wait_for_timeout(500)
        raise AssertionError(
            "未识别到公摊方案业务 iframe；当前 frames="
            + repr([frame.url for frame in self.page.frames])
        )

    def _require_frame(self) -> Frame:
        if self.frame is None:
            raise AssertionError("公摊方案业务 iframe 尚未初始化")
        return self.frame
