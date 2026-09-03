from __future__ import annotations

import re
import time
from decimal import Decimal

from playwright.sync_api import Frame, Locator, Page, expect

from src.pages.base_page import BasePage


class RoomFeeSettingPage(BasePage):
    """房间收费设置页面：按房间维护收费面积。"""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.frame: Frame | None = None

    def open(self, expected_customer_id: str | None = None) -> None:
        cloud_billing = self.page.get_by_role(
            "menuitem", name="云收费", exact=True
        )
        if cloud_billing.is_visible():
            cloud_billing.click()

        charge_settings = self.page.get_by_role(
            "menuitem", name="收费设置", exact=False
        )
        expect(charge_settings).to_be_visible(timeout=30_000)
        if charge_settings.get_attribute("aria-expanded") != "true":
            charge_settings.click()

        room_setting = self.page.get_by_role(
            "menuitem", name="房间收费设置", exact=True
        )
        expect(room_setting).to_be_visible(timeout=15_000)
        room_setting.click()

        self.frame = self._wait_for_business_frame()
        self.frame.wait_for_load_state("domcontentloaded")
        if expected_customer_id and "customerId=" in self.frame.url:
            if f"customerId={expected_customer_id}" not in self.frame.url:
                raise AssertionError(
                    "房间收费设置 iframe 客户上下文不匹配；"
                    f"期望 customerId={expected_customer_id}，实际 {self.frame.url}"
                )
        expect(self.frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        self.page.wait_for_timeout(2_000)
        expect(self._search_button(timeout=60_000)).to_be_visible()

    def select_project(self, project_name: str) -> None:
        frame = self._require_frame()
        selectors = frame.locator(".jie-project")
        if selectors.count() == 0:
            # 部分版本继承门户当前项目，不显示项目选择器。
            return
        selector = self.require_single(selectors, "项目选择组件")
        current = selector.locator("span.textOverflow")
        if current.count() == 1 and current.inner_text().strip() == project_name:
            return

        selector.click()
        popover_id = selector.get_attribute("aria-describedby")
        if not popover_id:
            raise AssertionError("项目选择组件缺少关联弹窗标识。")
        popover = frame.locator(f"#{popover_id}:visible")
        expect(popover).to_be_visible(timeout=15_000)
        target = popover.get_by_text(project_name, exact=True)
        expect(target).to_have_count(1, timeout=30_000)
        target.click()
        if current.count() == 1:
            expect(current).to_have_text(project_name, timeout=15_000)

    def set_fee_area(
        self, room_path: str, fee_area: Decimal | str
    ) -> str:
        frame = self._require_frame()
        normalized = Decimal(str(fee_area)).quantize(Decimal("0.00"))
        self._select_room(room_path)
        self._search_button().click()
        expect(frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )

        main_rows = frame.locator(
            ".el-table__body-wrapper tr.el-table__row:visible"
        )
        expect(main_rows).to_have_count(1, timeout=30_000)
        row_text = main_rows.first.inner_text()
        room_name = room_path.rstrip("/").split("/")[-1]
        if room_name not in row_text:
            raise AssertionError(
                f"唯一查询结果不属于房间 {room_name!r}：{row_text!r}"
            )

        details = frame.get_by_text("收费详情", exact=True)
        visible_details = self._visible(details)
        if len(visible_details) != 1:
            raise AssertionError(
                "唯一查询结果的“收费详情”应唯一可见，实际可见 "
                f"{len(visible_details)} 个。"
            )
        visible_details[0].click()

        edit_button = frame.get_by_role(
            "button", name="编辑收费标准", exact=True
        )
        expect(edit_button).to_be_visible(timeout=60_000)
        expect(frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        edit_button.click()

        input_value = format(normalized.normalize(), "f")
        actual_value = ""
        actual_area: Decimal | None = None
        for _ in range(3):
            fee_area_input = self._fee_area_input()
            expect(fee_area_input).to_be_visible(timeout=30_000)
            fee_area_input.fill("")
            fee_area_input.fill(input_value)
            fee_area_input.press("Tab")
            self.page.wait_for_timeout(500)
            actual_value = fee_area_input.input_value().strip()
            try:
                actual_area = Decimal(actual_value).quantize(Decimal("0.00"))
            except Exception:
                actual_area = None
            if actual_area == normalized:
                break
        if actual_area != normalized:
            raise AssertionError(
                f"收费面积输入后页面值无效或不一致：{actual_value!r}"
            )

        save_buttons = frame.get_by_role("button", name="保存", exact=True)
        visible_saves = self._visible(save_buttons)
        if len(visible_saves) != 1:
            raise AssertionError(
                f"编辑页“保存”应唯一可见，实际可见 {len(visible_saves)} 个。"
            )
        visible_saves[0].click()

        success = frame.get_by_text("设置成功", exact=False)
        expect(success).to_be_visible(timeout=60_000)
        expect(self._search_button()).to_be_visible(timeout=60_000)
        expect(frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        return format(normalized, "f")

    def read_room_detail(self, room_path: str) -> str:
        """只读返回指定房间当前收费详情文本。"""
        frame = self._require_frame()
        self._select_room(room_path)
        self._search_button().click()
        expect(frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        rows = frame.locator(
            ".el-table__body-wrapper tr.el-table__row:visible"
        )
        expect(rows).to_have_count(1, timeout=30_000)
        room_name = room_path.rstrip("/").split("/")[-1]
        if room_name not in rows.first.inner_text():
            raise AssertionError("唯一结果不是目标房间，停止读取详情。")
        details = self._visible(frame.get_by_text("收费详情", exact=True))
        if len(details) != 1:
            raise AssertionError("目标房间收费详情入口未唯一匹配。")
        details[0].click()
        title = frame.get_by_text("房间收费标准详情", exact=True)
        expect(title).to_be_visible(timeout=60_000)
        panel = title.locator(
            "xpath=ancestor::*[.//button[normalize-space()='编辑收费标准']][1]"
        )
        expect(panel).to_be_visible(timeout=30_000)
        expect(frame.locator(".el-loading-mask:visible")).to_have_count(
            0, timeout=60_000
        )
        return panel.inner_text().strip()

    def describe(self) -> dict[str, object]:
        frame = self._require_frame()
        return {
            "frame_url": frame.url,
            "visible_inputs": frame.locator("input:visible").evaluate_all(
                "els => els.map(e => ({placeholder: e.placeholder, value: e.value, readonly: e.readOnly}))"
            ),
            "visible_buttons": [
                text.strip()
                for text in frame.locator("button:visible").all_inner_texts()
                if text.strip()
            ],
        }

    def _wait_for_business_frame(self) -> Frame:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            for frame in self.page.frames:
                if frame == self.page.main_frame:
                    continue
                try:
                    if "/roomChargeSetting" in frame.url:
                        return frame
                    if frame.get_by_role(
                        "button", name="搜索", exact=True
                    ).count() and (
                        frame.get_by_placeholder("请选择房间").count()
                        or frame.get_by_text("房间名称", exact=True).count()
                    ):
                        return frame
                except Exception:
                    continue
            self.page.wait_for_timeout(500)
        frames = [frame.url for frame in self.page.frames]
        raise AssertionError(f"未识别到房间收费设置 iframe；当前 frames={frames}")

    def _select_room(self, room_path: str) -> None:
        frame = self._require_frame()
        room_input = frame.get_by_placeholder("请选择房间")
        if room_input.count() == 0:
            candidates = frame.locator("input[placeholder='请选择']:visible")
            matched: list[Locator] = []
            for index in range(candidates.count()):
                candidate = candidates.nth(index)
                context_text = candidate.evaluate(
                    """el => {
                      let node = el;
                      for (let i = 0; i < 5 && node; i++, node = node.parentElement) {
                        const text = (node.innerText || '').replace(/\\s+/g, ' ').trim();
                        if (text.includes('房间名称')) return text;
                      }
                      return '';
                    }"""
                )
                if "房间名称" in context_text:
                    matched.append(candidate)
            if len(matched) != 1:
                descriptors = candidates.evaluate_all(
                    """els => els.map(el => ({
                      outerHTML: el.outerHTML,
                      parentText: (el.parentElement?.parentElement?.innerText || '').replace(/\\s+/g, ' ').trim(),
                      x: el.getBoundingClientRect().x,
                      y: el.getBoundingClientRect().y
                    }))"""
                )
                raise AssertionError(
                    "未唯一识别到“房间名称”右侧的请选择输入框；"
                    f"候选结构={descriptors}"
                )
            room_input = matched[0]
        room_input = self.require_single(room_input, "房间名称输入框")
        # 详情保存返回列表后，筛选框会保留上一房间的标签；必须先删除，
        # 否则下一次选择会累加并产生多条查询结果。
        clear_tags = frame.locator(
            ".el-tag:visible .el-tag__close, "
            ".el-tag:visible .el-icon-close"
        )
        while clear_tags.count() > 0:
            clear_tags.first.click()
            self.page.wait_for_timeout(200)
        # 组件将多选项折叠为“+N”时，逐个关闭不可见标签可能无效；
        # 此时使用组件自身的 clear 事件，不直接修改业务数据。
        remaining_tags = frame.locator(".el-tag:visible")
        if remaining_tags.count() > 0:
            room_input.evaluate(
                """el => {
                  const input = el;
                  input.focus();
                  input.value = '';
                  input.dispatchEvent(new Event('input', {bubbles: true}));
                  input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Backspace', bubbles: true}));
                }"""
            )
            self.page.keyboard.press("Backspace")
            self.page.wait_for_timeout(300)
        room_input.fill("")
        room_input.click()
        room_tree = frame.locator(".el-tree:visible")
        expect(room_tree).to_have_count(1, timeout=15_000)
        parts = [part for part in room_path.split("/") if part]
        if not parts:
            raise ValueError("房间路径不能为空。")

        for part in parts[:-1]:
            node_text = room_tree.get_by_text(part, exact=True)
            expect(node_text).to_have_count(1, timeout=30_000)
            node = node_text.locator(
                "xpath=ancestor::*[contains(@class, 'el-tree-node')][1]"
            )
            icon = node.locator(".el-tree-node__expand-icon")
            if icon.count() == 1 and icon.is_visible():
                if "expanded" not in (icon.get_attribute("class") or ""):
                    icon.click()

        leaf = room_tree.get_by_text(parts[-1], exact=True)
        expect(leaf).to_have_count(1, timeout=30_000)
        leaf_content = leaf.locator(
            "xpath=ancestor::*[contains(@class, 'el-tree-node__content')][1]"
        )
        checkbox = leaf_content.locator(".el-checkbox")
        if checkbox.count() == 1:
            checkbox.click()
            expect(checkbox).to_have_class(re.compile(r"\bis-checked\b"))
        else:
            leaf.click()

        panel = room_tree.locator("xpath=ancestor::*[.//button][1]")
        confirm = panel.get_by_text(re.compile(r"^确\s*[认定]$"))
        expect(confirm).to_have_count(1, timeout=10_000)
        confirm.click()
        expect(room_tree).to_be_hidden(timeout=15_000)

    def _fee_area_input(self) -> Locator:
        frame = self._require_frame()
        detail_title = frame.get_by_text("房间收费标准详情", exact=True)
        if detail_title.count() == 1 and detail_title.is_visible():
            detail_panel = detail_title.locator(
                "xpath=ancestor::*[.//button[normalize-space()='保存']][1]"
            )
            number_inputs = self._visible(
                detail_panel.locator("input[type='number']")
            )
            if len(number_inputs) == 1:
                return number_inputs[0]
            editable = self._visible(
                detail_panel.locator(
                    "input:not([readonly]):not([disabled])"
                )
            )
            if len(editable) == 1:
                return editable[0]
        by_placeholder = frame.get_by_placeholder(
            re.compile("收费面积"), exact=False
        )
        visible = self._visible(by_placeholder)
        if len(visible) == 1:
            return visible[0]

        labels = frame.get_by_text("收费面积", exact=True)
        for label in self._visible(labels):
            form_item = label.locator(
                "xpath=ancestor::*[contains(@class, 'el-form-item')][1]"
            )
            inputs = self._visible(form_item.locator("input"))
            if len(inputs) == 1:
                return inputs[0]
            following = label.locator("xpath=following::input[1]")
            if following.count() == 1 and following.is_visible():
                return following
        raise AssertionError("未唯一识别到收费面积输入框。")

    def _search_button(self, timeout: int = 10_000) -> Locator:
        frame = self._require_frame()
        buttons = frame.locator("button:visible").filter(
            has_text=re.compile(r"^\s*搜索\s*$")
        )
        expect(buttons).to_have_count(1, timeout=timeout)
        if buttons.count() != 1:
            raise AssertionError(
                f"房间收费设置“搜索”应唯一可见，实际 {buttons.count()} 个。"
            )
        return buttons

    def _require_frame(self) -> Frame:
        if self.frame is None:
            raise AssertionError("尚未打开房间收费设置页面。")
        return self.frame

    @staticmethod
    def _visible(locator: Locator) -> list[Locator]:
        return [
            locator.nth(index)
            for index in range(locator.count())
            if locator.nth(index).is_visible()
        ]
