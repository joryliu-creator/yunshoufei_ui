from __future__ import annotations

import re
import time
from typing import Any

from playwright.sync_api import Frame, Locator, Page, expect

from src.pages.base_page import BasePage
from src.pages.portal_page import PortalPage


class DiscountSchemePage(BasePage):
    """减免方案列表、新增和按名称删除流程。"""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.frame: Frame | None = None

    def open(self, project_name: str) -> None:
        # 门户通知弹窗可能在 open_home 首次清理后延迟出现。
        PortalPage(self.page).dismiss_home_overlays()
        cloud = self.page.get_by_role("menuitem", name="云收费", exact=True)
        if cloud.is_visible():
            cloud.click()
        settings = self.page.get_by_role("menuitem", name="收费设置", exact=False)
        expect(settings).to_be_visible(timeout=30_000)
        if settings.get_attribute("aria-expanded") != "true":
            settings.click()
        entry = self.page.get_by_role("menuitem", name=re.compile(r"减免方案"))
        expect(entry).to_be_visible(timeout=30_000)
        entry.click()
        self.frame = self._wait_for_frame()
        self._wait_ready()
        self.select_project(project_name)

    def select_project(self, project_name: str) -> None:
        frame = self._require_frame()
        selectors = frame.locator(".jie-project")
        if selectors.count() == 0:
            return
        selector = self.require_single(selectors, "减免方案项目选择器")
        current = selector.locator("span.textOverflow")
        if current.count() == 1 and current.inner_text().strip() == project_name:
            return
        selector.click()
        popover_id = selector.get_attribute("aria-describedby")
        if not popover_id:
            raise AssertionError("减免方案项目选择器缺少弹层标识")
        popover = frame.locator(f"#{popover_id}:visible")
        expect(popover).to_be_visible(timeout=15_000)
        target = popover.get_by_text(project_name, exact=True)
        expect(target).to_have_count(1, timeout=30_000)
        target.click()
        if current.count() == 1:
            expect(current).to_have_text(project_name, timeout=15_000)

    def create(
        self,
        *,
        name: str,
        rule: str,
        value: str | None = None,
        approval_amount: str = "1",
        remark: str = "autotest",
    ) -> None:
        frame = self._require_frame()
        self._wait_ready()
        add = frame.get_by_role("button", name="新增", exact=True)
        expect(add).to_be_visible(timeout=30_000)
        add.click()
        dialog = self._visible_dialog()
        name_input = dialog.get_by_placeholder("请输入减免方案名称")
        if name_input.count() != 1:
            name_input = dialog.locator("input").first
        expect(name_input).to_be_visible(timeout=15_000)
        name_input.fill(name)

        rule_radio = dialog.get_by_text(rule, exact=True)
        expect(rule_radio).to_have_count(1, timeout=15_000)
        rule_radio.click()

        if rule in {"按折扣", "按固定金额", "违约金折扣"}:
            if value is None:
                raise ValueError(f"规则 {rule} 必须提供减免值")
            # 页面当前文案：按折扣/按固定金额分别显示“减免折扣”/“固定金额”，
            # 违约金折扣直接使用规则名作为字段标签。
            label = {
                "按折扣": "减免折扣",
                "按固定金额": "固定金额",
                "违约金折扣": "违约金折扣",
            }[rule]
            placeholders = {
                "按折扣": "请输入减免折扣",
                "按固定金额": "请输入固定金额",
                "违约金折扣": "请输入违约金折扣",
            }
            value_input = dialog.get_by_placeholder(placeholders[rule])
            if value_input.count() == 0:
                value_input = self._input_after_label(dialog, label)
            expect(value_input).to_be_visible(timeout=10_000)
            value_input.fill(value)

        # 六种规则均需要填写“超额审批”（页面会在未填写时停留在弹窗内）。
        approval_input = dialog.locator('input[placeholder*="超额审批"]:visible')
        if approval_input.count() != 1:
            approval_input = self._input_after_label(dialog, "超额审批")
        expect(approval_input).to_be_visible(timeout=10_000)
        approval_input.fill(approval_amount)
        if approval_input.input_value() != approval_amount:
            approval_input.click()
            approval_input.press("Control+A")
            approval_input.type(approval_amount)
            approval_input.press("Tab")
        # 保留轻量诊断，便于不同版本表单受控组件定位问题。
        if approval_input.input_value() != approval_amount:
            raise AssertionError(f"超额审批输入未生效: actual={approval_input.input_value()!r}")

        remark_input = dialog.locator("textarea")
        if remark_input.count() == 1:
            remark_input.fill(remark)
        if name_input.input_value() != name:
            raise AssertionError(
                f"减免方案名称被其他字段覆盖: expected={name!r}, actual={name_input.input_value()!r}"
            )
        confirm = dialog.get_by_role("button", name="确定", exact=True)
        expect(confirm).to_be_visible(timeout=15_000)
        if not confirm.is_enabled():
            raise AssertionError("减免方案确认按钮处于禁用状态，表单仍有必填项未满足")
        submit_responses: list[dict[str, Any]] = []

        def capture_submit(response: Any) -> None:
            request = response.request
            if request.method not in {"POST", "PUT", "PATCH"}:
                return
            try:
                body = response.text()
            except Exception:
                body = "<unavailable>"
            submit_responses.append(
                {"status": response.status, "url": response.url, "body": body[:1200]}
            )

        self.page.on("response", capture_submit)
        try:
            confirm.click()
            self.page.wait_for_timeout(2500)
        finally:
            self.page.remove_listener("response", capture_submit)
        if dialog.is_visible():
            # 表单校验失败时直接暴露校验文案，避免无意义等待成功提示。
            errors = dialog.locator(".el-form-item__error:visible")
            if errors.count():
                raise AssertionError("减免方案表单校验失败: " + " | ".join(errors.all_inner_texts()))
            raise AssertionError(f"减免方案提交后弹窗未关闭；提交响应={submit_responses[-5:]}")
        expect(dialog).to_be_hidden(timeout=30_000)
        self.search(name)
        expect(self._row(name)).to_be_visible(timeout=30_000)

    def search(self, name: str) -> None:
        frame = self._require_frame()
        inputs = frame.locator("input:visible")
        candidates = []
        for i in range(inputs.count()):
            item = inputs.nth(i)
            placeholder = item.get_attribute("placeholder") or ""
            if "减免方案" in placeholder or "方案名称" in placeholder:
                candidates.append(item)
        target = candidates[0] if candidates else inputs.first
        expect(target).to_be_visible(timeout=15_000)
        target.fill(name)
        # 按钮带图标时 accessible name 会包含图标文本，不能使用 exact=True。
        search = frame.get_by_role("button", name=re.compile(r"搜索"))
        expect(search).to_be_visible(timeout=15_000)
        search.click()
        expect(frame.locator(".el-loading-mask:visible")).to_have_count(0, timeout=60_000)

    def delete(self, name: str) -> None:
        frame = self._require_frame()
        self.search(name)
        row = self._row(name)
        expect(row).to_be_visible(timeout=30_000)
        operation_row = self._operation_row(row, name)
        delete = operation_row.get_by_text("删除", exact=True)
        if delete.count() == 0:
            delete = operation_row.get_by_role("button", name="删除", exact=True)
        expect(delete).to_have_count(1, timeout=15_000)
        delete.click()
        prompt = frame.get_by_text(re.compile(r"是否确认删除|确认.*删除|删除后.*不可恢复"))
        expect(prompt).to_be_visible(timeout=15_000)
        panel = prompt.locator("xpath=ancestor::*[.//button][1]")
        confirm = panel.get_by_role("button", name="确定", exact=True)
        expect(confirm).to_be_visible(timeout=15_000)
        confirm.click()
        expect(frame.get_by_text(re.compile(r"删除成功|操作成功"))).to_be_visible(timeout=30_000)
        self.search(name)
        expect(self._row(name)).to_have_count(0, timeout=30_000)

    def delete_if_exists(self, name: str) -> bool:
        """清理上次中断留下的同名自动化数据，避免重复创建阻塞验证。"""
        self.search(name)
        if self._row(name).count() == 0:
            return False
        self.delete(name)
        return True

    def _row(self, name: str) -> Locator:
        frame = self._require_frame()
        rows = frame.locator(".el-table__body-wrapper tr:visible").filter(has_text=name)
        if rows.count() == 0:
            rows = frame.locator("tr:visible").filter(has_text=name)
        return rows

    def _operation_row(self, data_row: Locator, name: str) -> Locator:
        """Map the main data row to Element UI's fixed-right operation row."""
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
            f"减免方案 {name!r} 未找到对应固定右侧操作行；"
            f"row_index={row_index}, fixed_rows={fixed_rows.count()}"
        )

    def _visible_dialog(self) -> Locator:
        frame = self._require_frame()
        dialogs = frame.locator(".el-dialog:visible, .el-drawer:visible")
        return self.require_single(dialogs, "新增减免方案弹窗")

    @staticmethod
    def _input_after_label(container: Locator, label: str) -> Locator:
        label_node = container.get_by_text(label, exact=False)
        expect(label_node).to_have_count(1, timeout=10_000)
        row = label_node.locator("xpath=ancestor::tr[1]")
        inputs = row.locator("input:visible") if row.count() else container.locator("input:visible")
        if inputs.count() == 0:
            form_item = label_node.locator(
                "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' el-form-item ')][1]"
            )
            inputs = form_item.locator("input:visible")
        if inputs.count() != 1:
            raise AssertionError(f"字段 {label!r} 对应可见输入框数量异常: {inputs.count()}")
        return inputs

    def _wait_ready(self) -> None:
        frame = self._require_frame()
        expect(frame.locator(".el-loading-mask:visible")).to_have_count(0, timeout=60_000)
        expect(frame.get_by_role("button", name="新增", exact=True)).to_be_visible(timeout=30_000)

    def _require_frame(self) -> Frame:
        if self.frame is None:
            raise AssertionError("减免方案业务 iframe 尚未初始化")
        return self.frame

    def _wait_for_frame(self) -> Frame:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            for frame in self.page.frames:
                if frame == self.page.main_frame:
                    continue
                try:
                    if frame.get_by_role("button", name="新增", exact=True).count() and frame.locator("input:visible").count():
                        return frame
                except Exception:
                    pass
            self.page.wait_for_timeout(500)
        raise AssertionError(f"未识别到减免方案业务 iframe；当前 frames={[f.url for f in self.page.frames]}")
