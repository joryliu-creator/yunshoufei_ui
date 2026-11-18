from __future__ import annotations

import re
from pathlib import Path
from time import monotonic

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, expect

from src.config.credentials import load_local_credentials


ROOT = Path(__file__).resolve().parents[2]


class PortalPage:
    def __init__(self, page: Page) -> None:
        self.page = page
        self._home_context: tuple[str, str, str | None, str | None] | None = None

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
        if "#/Home" in self.page.url and self._cloud_billing_entry().is_visible():
            self._home_context = (
                base_url,
                master_customer_id,
                environment,
                account_role,
            )
            self.dismiss_home_overlays()
            self.collapse_customer_service()
            return
        self._home_context = (
            base_url,
            master_customer_id,
            environment,
            account_role,
        )
        # 标准1门户在自动登录后携带 mcid 重新请求会回跳到登录页。
        # 目标客户由 Home 路由参数维持，使用已人工验证的稳定入口。
        home_url = self._customer_home_url(base_url, master_customer_id)
        self.page.goto(home_url, wait_until="commit")
        login_attempted = False
        try:
            state = self._wait_for_login_or_portal(timeout=30_000)
        except AssertionError:
            # The Home hash can load before either the login redirect or the
            # portal shell is rendered. If we are still on this customer Home
            # route, recover through the configured login once instead of
            # failing before the recovery path can run.
            if "#/Home" not in self.page.url:
                raise
            state = "unknown"
        if state in {"login", "unknown"}:
            self._login_with_local_credentials(
                base_url, master_customer_id, home_url, environment, account_role
            )
            login_attempted = True
        self.dismiss_home_overlays()
        self.collapse_customer_service()
        try:
            expect(self._cloud_billing_entry()).to_be_visible(timeout=30_000)
        except AssertionError:
            if login_attempted:
                raise
            # If a previously rendered portal loses its menu, allow one
            # credential-based recovery. Never retry indefinitely.
            self._login_with_local_credentials(
                base_url, master_customer_id, home_url, environment, account_role
            )
            login_attempted = True
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
        self.page.evaluate(
            """() => {
                const markerKey = '__codex_saved_session_storage_restored_v1__';
                const marker = sessionStorage.getItem(markerKey);
                sessionStorage.clear();
                if (marker === '1') sessionStorage.setItem(markerKey, marker);
                localStorage.clear();
            }"""
        )
        self.page.goto(f"{base_url}#/login", wait_until="commit")
        # A restored context may inject an expired downstream token into the
        # new login document. Clear it on the actual portal origin before
        # submitting the fresh login form.
        self.page.evaluate(
            """() => {
                const markerKey = '__codex_saved_session_storage_restored_v1__';
                const marker = sessionStorage.getItem(markerKey);
                sessionStorage.clear();
                if (marker === '1') sessionStorage.setItem(markerKey, marker);
                localStorage.clear();
            }"""
        )
        if self._wait_for_login_or_portal(timeout=30_000) != "login":
            raise AssertionError("门户未显示登录表单。")
        self._submit_login(username, password, captcha)
        saw_loading = False
        callback_deadline = monotonic() + 30
        while True:
            if "#/Home" in self.page.url:
                break
            if "#/Loading" in self.page.url:
                saw_loading = True
                break
            remaining = callback_deadline - monotonic()
            if remaining <= 0:
                break
            self.page.wait_for_timeout(min(250, max(1, int(remaining * 1000))))
        if saw_loading:
            try:
                self.page.wait_for_url("**#/Home**", timeout=30_000)
            except PlaywrightTimeoutError:
                self.page.goto(home_url, wait_until="commit")
        if self._wait_for_login_or_portal(timeout=30_000) != "portal":
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
        """Wait up to the requested wall-clock time for login or portal DOM.

        Use a monotonic deadline rather than a fixed number of iterations:
        locator checks take variable time, so the old attempt count could
        expire well before the advertised timeout.
        """
        deadline = monotonic() + max(0, timeout) / 1000
        while True:
            username = self.page.locator(
                'input.el-input__inner[placeholder*="用户名"]:visible'
            )
            password = self.page.locator(
                'input.el-input__inner[type="password"]:visible'
            )
            login_button = self.page.locator("button:visible").filter(
                has_text=re.compile(r"登\s*录")
            )
            is_login_form = (
                "#/login" in self.page.url
                and username.count() == 1
                and password.count() == 1
                and login_button.count() == 1
                and login_button.is_visible()
            )
            if is_login_form:
                return "login"
            # The Home hash can appear before the portal shell/menu is
            # rendered. Treating the URL alone as readiness caused a second
            # unnecessary login attempt and long waits. Require the actual
            # cloud-billing entry to be visible; overlays are dismissed by the
            # caller after this readiness check.
            if self._cloud_billing_entry().is_visible():
                return "portal"
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            self.page.wait_for_timeout(min(200, max(1, int(remaining * 1000))))
        raise AssertionError(
            f"等待门户或登录表单超时，当前URL={self.page.url!r}"
        )

    def _login_inputs(self):
        return self.page.locator("input.el-input__inner:visible")

    def _submit_login(self, username: str, password: str, captcha: str) -> None:
        """Submit the current username/password login form.

        Older portal builds require a captcha, while the current HTTPS login
        page may expose only username and password. Fill the captcha only
        when that input is actually rendered; never assume a third input is
        present. Retry once only when a rendered captcha is explicitly
        reported expired.
        """
        for attempt in range(2):
            username_input = self.page.locator(
                'input.el-input__inner[placeholder*="用户名"]:visible'
            )
            password_input = self.page.locator(
                'input.el-input__inner[type="password"]:visible'
            )
            expect(username_input).to_have_count(1, timeout=30_000)
            expect(password_input).to_have_count(1, timeout=30_000)
            username_input.fill(username)
            password_input.fill(password)
            captcha_input = self.page.locator(
                'input.el-input__inner[placeholder*="验证码"]:visible, '
                'input.el-input__inner[placeholder*="校验码"]:visible'
            )
            if captcha_input.count() > 1:
                raise AssertionError(
                    f"登录页验证码输入框应最多一个，实际 {captcha_input.count()} 个。"
                )
            if captcha_input.count() == 1:
                captcha_input.fill(captcha)
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
            if (
                attempt == 0
                and captcha_input.count() == 1
                and (code == "JIESHUN2004" or captcha_expired)
            ):
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

        # New accounts may show a portal-wide migration tip that blocks every
        # menu item. It is not an Element dialog/drawer; acknowledge only this
        # known tip and only when its exact action is visible.
        intro = self.page.locator(".j-theme__intro-wrap")
        intro_action = intro.get_by_role(
            "button", name="立即体验", exact=True
        )
        if intro_action.count() == 1 and intro_action.is_visible():
            intro_action.click(timeout=3_000)
            expect(intro_action).to_be_hidden(timeout=5_000)

    def open_billing_center(self) -> None:
        self._open_billing_center_once()
        if self._wait_for_billing_center_ready(timeout=15_000):
            return

        # The outer portal can still look authenticated while its downstream
        # cloud-billing token has expired. Recover the login once, then reopen
        # the same established Bill Center page; never rewrite bill creation.
        if self._home_context is None:
            raise AssertionError("账单中心 iframe 未加载，且缺少登录恢复上下文。")
        base_url, customer_id, environment, account_role = self._home_context
        home_url = self._customer_home_url(base_url, customer_id)
        self._login_with_local_credentials(
            base_url, customer_id, home_url, environment, account_role
        )
        self.dismiss_home_overlays()
        self.collapse_customer_service()
        self._open_billing_center_once()
        if not self._wait_for_billing_center_ready(timeout=30_000):
            raise AssertionError("重新登录后账单中心 iframe 仍未加载业务页面。")

    def _open_billing_center_once(self) -> None:
        self.dismiss_home_overlays()
        self.collapse_customer_service()
        cloud_billing = self._cloud_billing_entry()
        cloud_classes = set((cloud_billing.get_attribute("class") or "").split())
        if cloud_billing.is_visible() and not cloud_classes.intersection(
            {"is-active", "active"}
        ):
            cloud_billing.click()

        # 账单中心仍属于智能计费。批次中门户会在用例间 reload，
        # “云收费”此时已是 is-active；重复点击会重置侧栏状态，故上面
        # 只在未激活时切换模块。然后按原菜单进入账单中心。
        billing_center = self._smart_billing_menu_item("账单中心")
        billing_center.click()
        # 已打开过减免管理等业务页时，门户可能只更新菜单而保留旧的
        # iframe；显式点击账单中心页签，确保后续清理使用活动业务页。
        self._activate_business_tab(r"账单中心")

    def _smart_billing_menu_item(self, name: str):
        """Expand 智能计费 only when the requested child is not visible."""
        target = self.page.get_by_role("menuitem", name=name, exact=True)
        if not target.is_visible():
            group = self.page.locator("li.el-submenu").filter(
                has=self.page.locator('span[title="智能计费"]')
            )
            expect(group).to_have_count(1, timeout=15_000)
            title = group.locator(":scope > .el-submenu__title")
            expect(title).to_be_visible(timeout=15_000)
            title.click()
        expect(target).to_be_visible(timeout=15_000)
        return target

    def _activate_business_tab(self, tab_pattern: str) -> None:
        """Wait for and activate a portal business tab after menu navigation."""
        tab = self.page.get_by_role("tab", name=re.compile(tab_pattern))
        for _ in range(30):
            visible_tabs = [
                tab.nth(index)
                for index in range(tab.count())
                if tab.nth(index).is_visible()
            ]
            if visible_tabs:
                target = visible_tabs[-1]
                target.click(force=True)
                self.page.wait_for_timeout(300)
                return
            self.page.wait_for_timeout(500)
        raise AssertionError(
            f"门户导航后未找到可见业务页签：{tab_pattern}；"
            f"当前页签文本={self.page.get_by_role('tab').all_inner_texts()}"
        )

    def _wait_for_billing_center_ready(self, timeout: int) -> bool:
        attempts = max(1, timeout // 500)
        for _ in range(attempts):
            for frame in self.page.frames:
                if frame == self.page.main_frame:
                    continue
                try:
                    if frame.get_by_role(
                        "button", name="创建账单", exact=True
                    ).is_visible():
                        return True
                except Exception:
                    pass
            self.page.wait_for_timeout(500)
        return False

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

        temporary_ledger = self._smart_billing_menu_item("临时台账")
        temporary_ledger.click()
        self._activate_business_tab(r"临时台账")

    def open_billing_calculation(self) -> None:
        """Open the calculation-billing module.

        This is intentionally separate from the bill center: the module first
        calculates a bill, then requires reconciliation and audit before the
        resulting bill can be viewed in the bill center.
        """
        self.dismiss_home_overlays()

        def activate_calculation_tab() -> None:
            self.collapse_customer_service()
            cloud_billing = self._cloud_billing_entry()
            if cloud_billing.is_visible():
                cloud_billing.click()
            calculation_billing = self._smart_billing_menu_item("计费出账")
            calculation_billing.click()
            # Reuse the existing tab when the serial billing flow previously
            # visited Bill Center. Clicking the menu item alone can leave the
            # calculation iframe hidden behind the active Bill Center tab.
            self._activate_business_tab(r"计费出账")

        # First activate the tab, then inspect it.  A previous calculation
        # detail can be hidden behind another business tab and is invisible to
        # Playwright until the calculation tab becomes active.
        activate_calculation_tab()
        self._close_calculation_detail_if_open()
        if self._calculation_detail_is_visible() or self._calculation_ui_needs_reset():
            # The detail view is a full business-page route in this build, so
            # its close icon is not always exposed to the iframe locator.
            # A rejected calculation can also leave an extra visible
            # ``开始计算`` control mounted in the iframe. Reload the
            # authenticated portal shell once to clear either stale state;
            # this preserves the login session and avoids a second login.
            if self._home_context is not None:
                base_url, customer_id, _, _ = self._home_context
                self.page.goto(
                    self._customer_home_url(base_url, customer_id),
                    wait_until="domcontentloaded",
                )
                self.page.wait_for_timeout(2_000)
                activate_calculation_tab()
                self._close_calculation_detail_if_open()
        if self._calculation_detail_is_visible():
            raise AssertionError("计费出账页仍停留在上一条费用计算详情，禁止继续执行。")
        if self._calculation_ui_needs_reset():
            self._save_calculation_state("calculation-stale-state")
            raise AssertionError(
                "计费出账页重载后仍存在异常的开始计算控件，禁止继续执行。"
            )

    def _close_calculation_detail_if_open(self) -> None:
        """Close a previous calculation detail view before the next case."""
        for _ in range(20):
            for frame in list(self.page.frames):
                try:
                    marker = frame.get_by_text("费用计算详情", exact=True)
                    visible_markers = [
                        marker.nth(index)
                        for index in range(marker.count())
                        if marker.nth(index).is_visible()
                    ]
                    if not visible_markers:
                        continue
                    close = frame.locator(
                        ".el-icon-close:visible, "
                        ".icon-close:visible, "
                        "[class*='close']:visible, "
                        "[class*='Close']:visible, "
                        "button[aria-label*='关闭']:visible, "
                        "[role='button'][aria-label*='关闭']:visible"
                    )
                    if close.count():
                        close.last.evaluate("el => el.click()")
                    else:
                        self.page.keyboard.press("Escape")
                    expect(marker.first).to_be_hidden(timeout=2_000)
                    return
                except Exception:
                    # Keep navigation available if a transient frame detaches
                    # during the close animation; retry while the prior page
                    # is still mounting instead of moving to a stale frame.
                    continue
            self.page.wait_for_timeout(500)

    def _calculation_detail_is_visible(self) -> bool:
        for frame in list(self.page.frames):
            try:
                marker = frame.get_by_text("费用计算详情", exact=True)
                if any(
                    marker.nth(index).is_visible()
                    for index in range(marker.count())
                ):
                    return True
            except Exception:
                continue
        return False

    def _calculation_ui_needs_reset(self) -> bool:
        """Detect a stale calculation drawer left by a rejected run.

        The normal page has exactly two visible ``开始计算`` actions (regular
        and temporary).  A failed backend request can leave the footer action
        from the old drawer mounted as a third visible action.  Treat that as
        session pollution and reload the authenticated shell before the next
        parameterized case.
        """
        for frame in list(self.page.frames):
            try:
                if "billChargeout" not in frame.url:
                    continue
                starts = frame.get_by_text("开始计算", exact=True)
                count = sum(
                    1
                    for index in range(starts.count())
                    if starts.nth(index).is_visible()
                )
                if count > 2:
                    return True
            except Exception:
                continue
        return False

    def _save_calculation_state(self, stem: str) -> None:
        """Persist compact diagnostics without dumping the full page log."""
        try:
            Path("artifacts").mkdir(exist_ok=True)
            for frame in list(self.page.frames):
                if "billChargeout" not in frame.url:
                    continue
                Path(f"artifacts/{stem}.txt").write_text(
                    frame.locator("body").inner_text(), encoding="utf-8"
                )
                break
            self.page.screenshot(path=f"artifacts/{stem}.png", full_page=True)
        except Exception:
            pass

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
                self.page.evaluate(
                    """() => {
                        const panel = document.querySelector(
                            '.bar-container .f-container.open'
                        );
                        if (panel) panel.classList.remove('open');
                    }"""
                )
        try:
            expect(open_panel).to_be_hidden(timeout=1_000)
        except AssertionError:
            self.page.evaluate(
                """() => {
                    const panel = document.querySelector(
                        '.bar-container .f-container.open'
                    );
                    if (panel) panel.classList.remove('open');
                }"""
            )
            expect(open_panel).to_be_hidden(timeout=5_000)
