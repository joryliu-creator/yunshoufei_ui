from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, expect

from src.config.credentials import load_local_credentials


ROOT = Path(__file__).resolve().parents[2]


class PortalPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    @staticmethod
    def _customer_home_url(base_url: str, master_customer_id: str) -> str:
        """Build the customer-scoped portal URL used by Standard1.

        Standard1 restores the customer context from the outer ``mcid`` query
        parameter.  Navigating only to ``#/Home?masterCustomerId=...`` can
        leave a blank shell after a fresh login even though the login API
        returned success.
        """
        return (
            f"{base_url}?mcid={master_customer_id}"
            f"&masterCustomerId={master_customer_id}"
            f"#/Home?masterCustomerId={master_customer_id}"
        )

    def _open_home_legacy(
        self,
        base_url: str,
        master_customer_id: str,
        *,
        environment: str | None = None,
        account_role: str | None = None,
    ) -> None:
        home_url = self._customer_home_url(base_url, master_customer_id)
        self.page.goto(
            home_url,
            wait_until="domcontentloaded",
        )
        # The portal may render the login form asynchronously after a
        # redirect. A synchronous element count can observe zero inputs and
        # incorrectly continue as if the home page were authenticated.
        login_username = self.page.get_by_role(
            "textbox", name="用户名", exact=True
        )
        try:
            expect(login_username).to_be_visible(timeout=30_000)
            login_required = True
        except AssertionError:
            login_required = False
        if login_required:
            if not environment or not account_role:
                raise AssertionError("登录态失效，但未提供环境或账号别名以执行本地登录。")
            credentials = load_local_credentials(
                ROOT, environment, master_customer_id, account_role
            )
            if credentials is None:
                raise AssertionError(
                    "登录态失效且本地未配置当前环境、客户和账号别名的凭据。"
                )
            username, password, captcha = credentials
            # Playwright context 可能带有服务端已判失效的旧 cookie；
            # 新旧会话共存时门户会在客户路由跳转后退回登录页。
            self.page.context.clear_cookies()
            self.page.evaluate(
                "() => { sessionStorage.clear(); localStorage.clear(); }"
            )
            # 与已验证的独立登录流程保持一致：先进入纯登录路由，再登录，
            # 避免携带客户参数的登录页在提交后丢失客户上下文。
            self.page.goto(f"{base_url}#/login", wait_until="commit")
            self.page.get_by_role(
                "textbox", name="用户名", exact=True
            ).fill(username)
            self.page.get_by_role(
                "textbox", name="密码", exact=True
            ).fill(password)
            self.page.get_by_role(
                "textbox", name="验证码", exact=True
            ).fill(captcha)
            login_button = self.page.locator("button:visible").filter(
                has_text=re.compile(r"登\s*录")
            )
            expect(login_button).to_have_count(1)
            login_button.click()
            self.page.wait_for_url("**#/Home**", timeout=30_000)
            # 登录接口与客户上下文恢复异步完成；过早跳转会被门户重定向回登录页。
            self.page.wait_for_timeout(3_000)
        self.dismiss_home_overlays()
        self.collapse_customer_service()
        expect(self._cloud_billing_entry()).to_be_visible(timeout=30_000)

    def open_home(
        self,
        base_url: str,
        master_customer_id: str,
        *,
        environment: str | None = None,
        account_role: str | None = None,
    ) -> None:
        """Open a customer portal and recover an expired local login state."""
        # 标准1门户在自动登录后携带 mcid 重新请求会回跳到登录页。
        # 目标客户由 Home 路由参数维持，使用已人工验证的稳定入口。
        home_url = self._customer_home_url(base_url, master_customer_id)
        self.page.goto(home_url, wait_until="commit")
        if self._wait_for_login_or_portal() == "login":
            self._login_with_local_credentials(
                base_url, master_customer_id, home_url, environment, account_role
            )
        self.dismiss_home_overlays()
        self.collapse_customer_service()
        try:
            expect(self._cloud_billing_entry()).to_be_visible(timeout=30_000)
        except AssertionError:
            # The portal can show an expired-local-user prompt after the first
            # successful callback and route back to login. Refill once in the
            # same browser context, then stop instead of looping indefinitely.
            # A stale session can keep the URL at Home while rendering only a
            # blank shell, so URL-based detection alone is insufficient here.
            # Force the single normal-login recovery whenever the portal menu
            # is still hidden.
            self._login_with_local_credentials(
                base_url, master_customer_id, home_url, environment, account_role
            )
            self.dismiss_home_overlays()
            self.collapse_customer_service()
            try:
                expect(self._cloud_billing_entry()).to_be_visible(timeout=30_000)
            except AssertionError:
                # Standard1 may report a transient "账号在其他地方登录"
                # after the login callback even though the session is usable.
                # Re-request the explicit customer Home route once, instead
                # of treating that notice as a definitive login failure.
                self.page.goto(home_url, wait_until="commit")
                self.page.wait_for_timeout(5_000)
                self.dismiss_home_overlays()
                self.collapse_customer_service()
                expect(self._cloud_billing_entry()).to_be_visible(timeout=30_000)

    def _login_with_local_credentials(
        self,
        base_url: str,
        master_customer_id: str,
        home_url: str,
        environment: str | None,
        account_role: str | None,
    ) -> None:
        if not environment or not account_role:
            raise AssertionError("登录态失效，未提供环境或账号别名。")
        credentials = load_local_credentials(
            ROOT, environment, master_customer_id, account_role
        )
        if credentials is None:
            raise AssertionError("未找到当前环境和账号的本地登录凭据。")
        username, password, captcha = credentials
        self.page.context.clear_cookies()
        self.page.evaluate("() => { sessionStorage.clear(); localStorage.clear(); }")
        self.page.goto(f"{base_url}#/login", wait_until="commit")
        if self._wait_for_login_or_portal() != "login":
            raise AssertionError("门户未显示登录表单。")
        self._submit_login(username, password, captcha)
        saw_loading = False
        for _ in range(30):
            if "#/Home" in self.page.url:
                break
            if "#/Loading" in self.page.url:
                saw_loading = True
                break
            self.page.wait_for_timeout(500)
        if saw_loading:
            try:
                self.page.wait_for_url("**#/Home**", timeout=15_000)
            except PlaywrightTimeoutError:
                self.page.goto(home_url, wait_until="commit")
        if self._wait_for_login_or_portal(timeout=15_000) != "portal":
            errors = self._visible_login_errors()
            detail = f"；页面提示：{'；'.join(errors)}" if errors else ""
            raise AssertionError(f"登录提交后未进入门户{detail}")
        # The login callback reaches Home asynchronously. Do not force a
        # reload here: Standard1 can invalidate the freshly issued callback
        # token during an immediate refresh and route back to login even
        # though the login API returned success. Continue on the verified Home
        # route and only navigate explicitly if the callback stopped at
        # Loading.
        if "#/Home" not in self.page.url:
            self.page.goto(home_url, wait_until="commit")
        if self._wait_for_login_or_portal(timeout=30_000) != "portal":
            raise AssertionError("登录后的门户未恢复首页。")

    def _wait_for_login_or_portal(self, timeout: int = 15_000) -> str:
        """Wait for a rendered portal menu or a rendered login form."""
        attempts = max(1, timeout // 500)
        for _ in range(attempts):
            is_login_form = (
                "#/login" in self.page.url and self._login_inputs().count() >= 3
            )
            if is_login_form:
                return "login"
            # The Home hash can appear before the portal shell/menu is
            # rendered. Treating the URL alone as readiness caused a second
            # unnecessary login attempt and long waits. Require the actual
            # cloud-billing entry to be visible; overlays are dismissed by the
            # caller after this readiness check.
            try:
                if self._cloud_billing_entry().is_visible():
                    return "portal"
            except Exception:
                pass
            self.page.wait_for_timeout(250)
        raise AssertionError(
            f"等待门户或登录表单超时，当前URL={self.page.url!r}"
        )

    def _login_inputs(self):
        return self.page.locator("input.el-input__inner:visible")

    def _submit_login(self, username: str, password: str, captcha: str) -> None:
        """Submit a portal login after its asynchronous captcha session settles.

        The standard portal may refresh the captcha session just after the
        form is rendered. Retry exactly once only when the server explicitly
        reports the documented captcha-expired response.
        """
        for attempt in range(2):
            inputs = self._login_inputs()
            expect(inputs.nth(2)).to_be_visible(timeout=30_000)
            inputs.nth(0).fill(username)
            inputs.nth(1).fill(password)
            inputs.nth(2).fill(captcha)
            login_button = self.page.get_by_role(
                "button", name=re.compile(r"登\s*录")
            )
            expect(login_button).to_have_count(1)
            with self.page.expect_response(
                lambda response: "/jportal-login/login" in response.url
            ) as login_response:
                login_button.click()
            try:
                payload = login_response.value.json()
            except Exception as exc:
                raise AssertionError("登录接口未返回可识别结果。") from exc
            if isinstance(payload, dict) and payload.get("success") is True:
                return
            code = str(payload.get("respCode", "")) if isinstance(payload, dict) else ""
            message = str(payload.get("respMsg", "")) if isinstance(payload, dict) else ""
            # The Standard1 gateway has returned the documented captcha
            # expiry both as JIESHUN2004 and as a localized message.  Treat
            # either form as the same transient login condition and refresh
            # once; never loop on a persistent credential failure.
            captcha_expired = (
                "验证码" in message
                and ("过期" in message or "无效" in message)
            )
            if attempt == 0 and (code == "JIESHUN2004" or captcha_expired):
                self.page.reload(wait_until="domcontentloaded")
                if self._wait_for_login_or_portal(timeout=30_000) != "login":
                    raise AssertionError("验证码刷新后未回到登录表单。")
                continue
            detail = f"（{message}）" if message else ""
            raise AssertionError(f"登录接口返回失败{detail}")
        raise AssertionError("验证码重试后仍未完成登录。")

    def _cloud_billing_entry(self):
        """Find the cloud-billing top navigation across portal render variants."""
        role_entry = self.page.get_by_role("menuitem", name="云收费", exact=True)
        if role_entry.count() == 1:
            return role_entry
        # The portal's top navigation may be rendered as plain text instead
        # of an ARIA menuitem. It is the stable visible portal-ready signal.
        text_entry = self.page.get_by_text("云收费", exact=True)
        return text_entry.first

    def _visible_login_errors(self) -> list[str]:
        """Return visible login errors without inspecting input values."""
        messages = self.page.locator(
            ".el-message:visible, .el-form-item__error:visible"
        ).all_inner_texts()
        return [message.strip() for message in messages if message.strip()]

    def dismiss_home_overlays(self) -> None:
        # 登录后可能同时出现“通知提醒”弹窗和“全部公告”侧边抽屉。
        # 只关闭当前可见遮挡层，不处理业务页面中的普通弹窗。
        self.page.wait_for_timeout(1_000)
        for _ in range(10):
            dialog_close_buttons = self.page.locator(
                ".el-dialog__wrapper:visible .el-dialog__headerbtn"
            )
            count = dialog_close_buttons.count()
            if count == 0:
                break
            # The announcement dialog can expose a header button before its
            # overlay has completed its transition.  A DOM click is safe here
            # and avoids leaving the portal menu blocked by the notice.
            try:
                dialog_close_buttons.evaluate_all("els => els.forEach(el => el.click())")
            except Exception:
                # The transition can detach the node between count() and the
                # click. Re-query on the next bounded iteration instead of
                # waiting 30 seconds on a stale locator.
                pass
            self.page.wait_for_timeout(500)

        for _ in range(10):
            drawer_close_buttons = self.page.locator(
                ".el-drawer__wrapper:visible .el-drawer__close-btn"
            )
            if drawer_close_buttons.count() == 0:
                break
            try:
                drawer_close_buttons.evaluate_all("els => els.forEach(el => el.click())")
            except Exception:
                pass
            self.page.wait_for_timeout(300)

    def open_billing_center(self) -> None:
        self.dismiss_home_overlays()
        self.collapse_customer_service()
        cloud_billing = self._cloud_billing_entry()
        if cloud_billing.is_visible():
            cloud_billing.click()

        billing_center = self.page.get_by_role(
            "menuitem", name="账单中心", exact=True
        )
        expect(billing_center).to_be_visible(timeout=15_000)
        billing_center.click()

    def open_temporary_ledger(self) -> None:
        """Open the cloud-billing temporary-ledger page.

        This is deliberately separate from ``open_billing_center``: temporary
        bills have a different creation form and a different cleanup workflow.
        """
        self.dismiss_home_overlays()
        self.collapse_customer_service()
        cloud_billing = self._cloud_billing_entry()
        if cloud_billing.is_visible():
            cloud_billing.click()

        temporary_ledger = self.page.get_by_role(
            "menuitem", name="临时台账", exact=True
        )
        expect(temporary_ledger).to_be_visible(timeout=15_000)
        temporary_ledger.click()

    def open_billing_calculation(self) -> None:
        """Open the calculation-billing module.

        This is intentionally separate from the bill center: the module first
        calculates a bill, then requires reconciliation and audit before the
        resulting bill can be viewed in the bill center.
        """
        self.dismiss_home_overlays()
        self.collapse_customer_service()
        cloud_billing = self._cloud_billing_entry()
        if cloud_billing.is_visible():
            cloud_billing.click()

        calculation_billing = self.page.get_by_role(
            "menuitem", name="计费出账", exact=True
        )
        expect(calculation_billing).to_be_visible(timeout=15_000)
        calculation_billing.click()

    def collapse_customer_service(self) -> None:
        open_panel = self.page.locator(".bar-container .f-container.open")
        if open_panel.count() == 0 or not open_panel.first.is_visible():
            return

        candidates = self.page.locator(".bar-container").get_by_text(
            re.compile(r"在\s*线\s*客\s*服")
        )
        visible_candidates = []
        for index in range(candidates.count()):
            candidate = candidates.nth(index)
            box = candidate.bounding_box() if candidate.is_visible() else None
            if box:
                visible_candidates.append((box["width"], candidate))

        if not visible_candidates:
            raise AssertionError("在线客服已展开，但未找到可见收起控件。")
        collapse_button = min(visible_candidates, key=lambda item: item[0])[1]
        try:
            collapse_button.click(timeout=2_000)
        except PlaywrightTimeoutError:
            # 通知弹窗可能在首次清理后异步出现并遮挡客服按钮。
            self.dismiss_home_overlays()
            if open_panel.count() == 0 or not open_panel.first.is_visible():
                return
            try:
                collapse_button.click(timeout=2_000)
            except PlaywrightTimeoutError:
                open_panel.first.evaluate("el => el.classList.remove('open')")
        try:
            expect(open_panel).to_be_hidden(timeout=1_000)
        except AssertionError:
            open_panel.first.evaluate("el => el.classList.remove('open')")
            expect(open_panel).to_be_hidden(timeout=5_000)
