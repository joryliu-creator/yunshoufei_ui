from __future__ import annotations

import re
from urllib.parse import unquote

from playwright.sync_api import Frame, Page, expect


class WorkbenchBillingPage:
    """Workbench room search and bill-detail entry used for one-off bills."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.workbench: Frame | None = None
        self.detail: Frame | None = None
        self.room_path: str | None = None

    def open(self) -> Frame:
        entry = self.page.get_by_role(
            "menuitem", name="业务办理收费台", exact=True
        )
        expect(entry).to_have_count(1, timeout=15_000)
        expect(entry).to_be_visible(timeout=15_000)
        entry.click()
        self.workbench = self._wait_for_frame(
            lambda frame: "work-biz-web" in frame.url.lower()
            and frame.get_by_text("按房间", exact=True).count() > 0,
            "工作台业务页面",
        )
        expect(self.workbench.get_by_text("按房间", exact=True)).to_be_visible(
            timeout=30_000
        )
        return self.workbench

    def search_room(self, room_path: str) -> None:
        frame = self._require_workbench()
        self.room_path = room_path
        room_number = room_path.rstrip("/").split("/")[-1]
        mode = frame.get_by_text("按房间", exact=True)
        expect(mode).to_be_visible(timeout=15_000)
        mode.click()
        search = frame.locator(
            'input.search-input:visible, input[placeholder="请输入房间名称"]:visible'
        )
        expect(search).to_have_count(1, timeout=10_000)
        result = frame.get_by_text(room_path, exact=True)
        last_error: AssertionError | None = None
        for attempt in range(2):
            search.fill(room_number)
            frame.get_by_role("button", name="立即查询", exact=True).click()
            try:
                expect(result).to_be_visible(timeout=15_000)
                expect(result).to_have_count(1)
                return
            except AssertionError as exc:
                last_error = exc
                if attempt == 0:
                    search.fill("")
                    self.page.wait_for_timeout(800)
        visible_text = frame.locator("body").inner_text()
        raise AssertionError(
            f"工作台按房间查询未唯一找到 {room_path!r}；"
            f"当前结果摘要={visible_text[-1200:]!r}"
        ) from last_error

    def open_room_profile(self, room_path: str) -> Frame:
        frame = self._require_workbench()
        result = frame.get_by_text(room_path, exact=True)
        expect(result).to_have_count(1, timeout=10_000)
        expect(result).to_be_visible(timeout=10_000)
        result.click()
        self.detail = self._wait_for_frame(
            lambda candidate: "billdetail" in candidate.url.lower(),
            "房间收费对象档案",
        )
        return self.detail

    def wait_for_charge_profile(
        self, *, room_path: str, charge_item: str, charge_standard: str
    ) -> Frame:
        detail = self.wait_for_room_profile(room_path)
        expect(detail.get_by_text(charge_item, exact=True)).to_be_visible(
            timeout=30_000
        )
        body_text = detail.locator("body").inner_text()
        if charge_standard not in body_text:
            raise AssertionError(
                f"房间档案未显示预期收费标准 {charge_standard!r}；"
                f"页面摘要={body_text[-1600:]!r}"
            )
        return detail

    def wait_for_room_profile(self, room_path: str) -> Frame:
        """Wait for the archive itself without assuming a fee is room-bound.

        Public-share participants intentionally need not have a room fee
        binding.  Their bill flow must still start from this room's archive,
        then select the scheme's charge item in the bill drawer.
        """
        detail = self._require_detail()
        expect(detail.get_by_role("button", name="新增账单", exact=True)).to_be_visible(
            timeout=60_000
        )
        room_number = room_path.rstrip("/").split("/")[-1]
        if room_number not in unquote(detail.url):
            raise AssertionError(
                "房间档案路由与已点击的房间不一致；"
                f"目标房间号={room_number!r}，档案路由={detail.url!r}。"
            )
        expect(detail.get_by_text(f"客户{room_number}", exact=True)).to_be_visible(
            timeout=30_000
        )
        return detail

    def open_create_bill(self):
        detail = self._require_detail()
        add_bill = detail.get_by_role("button", name="新增账单", exact=True)
        expect(add_bill).to_be_visible(timeout=10_000)
        add_bill.click()
        drawer = detail.locator(".el-drawer[role='dialog']:visible").filter(
            has_text="新增账单"
        )
        expect(drawer).to_have_count(1, timeout=15_000)
        expect(drawer).to_be_visible(timeout=15_000)
        room_label = drawer.locator("label.el-radio").filter(has_text="房间")
        expect(room_label).to_have_count(1, timeout=10_000)
        expect(room_label).to_have_class(re.compile(r"is-checked"))
        if not self.room_path:
            raise AssertionError("创建账单前未记录已选择的房间。")
        expect(drawer.get_by_text(self.room_path, exact=True)).to_be_visible(
            timeout=10_000
        )
        return drawer

    def submit_and_wait_for_success(self, drawer) -> str:
        confirm = drawer.get_by_role("button", name="确定", exact=True)
        expect(confirm).to_have_count(1, timeout=10_000)
        expect(confirm).to_be_enabled(timeout=10_000)
        confirm.click(force=True)
        for _ in range(240):
            for frame in reversed(self.page.frames):
                try:
                    messages = frame.locator(
                        ".el-message:visible, .el-notification:visible, "
                        ".el-message-box:visible, .el-alert:visible"
                    )
                    text = " ".join(
                        value.strip()
                        for value in messages.all_inner_texts()
                        if value.strip()
                    )
                    if not text:
                        text = frame.locator("body").inner_text()[-1200:]
                    match = re.search(r"账单成功数\s*[:：]\s*(\d+)", text)
                    if match:
                        if int(match.group(1)) == 1:
                            return text
                        raise AssertionError(f"工作台新增账单返回非预期结果：{text!r}")
                except AssertionError:
                    raise
                except Exception:
                    continue
            self.page.wait_for_timeout(250)
        raise AssertionError("工作台新增账单后未观察到成功数为 1 的明确反馈。")

    def _require_workbench(self) -> Frame:
        if self.workbench is None:
            raise AssertionError("工作台业务页尚未打开。")
        return self.workbench

    def _require_detail(self) -> Frame:
        if self.detail is None:
            raise AssertionError("房间收费对象档案尚未打开。")
        return self.detail

    def _wait_for_frame(self, predicate, label: str) -> Frame:
        last_frames: list[tuple[str, str]] = []
        for _ in range(120):
            last_frames = []
            for frame in reversed(self.page.frames):
                if frame == self.page.main_frame:
                    continue
                try:
                    last_frames.append((frame.url, frame.name))
                    if predicate(frame):
                        return frame
                except Exception:
                    continue
            self.page.wait_for_timeout(250)
        raise AssertionError(f"未加载{label}；当前业务框架={last_frames!r}")
