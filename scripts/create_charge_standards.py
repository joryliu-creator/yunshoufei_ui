from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.update_room_import_template import (  # noqa: E402
    CHARGE_ITEM_NAMES,
    FULL_MONTH_FORMULA,
    formula_mappings,
)
from src.config.accounts import get_account_auth_profile  # noqa: E402
from src.config.environments import load_test_environment  # noqa: E402
from src.pages.charge_standard_page import (  # noqa: E402
    ChargeStandardData,
    ChargeStandardPage,
)
from src.pages.portal_page import PortalPage  # noqa: E402
from scripts.save_auth import load_credentials  # noqa: E402
from src.config.standard_name import automation_standard_name  # noqa: E402


SUPPORTED_FORMULAS = {FULL_MONTH_FORMULA}
UI_CHARGE_TYPES = {"水表仪表类": "仪表类", "电表仪表类": "仪表类"}
RESULT_FILE = ROOT / "artifacts" / "charge-standard-create-results.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按映射表创建收费标准")
    parser.add_argument("--environment", default="standard1")
    parser.add_argument("--customer-id", default="93537")
    parser.add_argument("--account", default="default")
    parser.add_argument("--project", default="云收费UI自动化")
    parser.add_argument("--rooms", nargs="+", required=True)
    parser.add_argument(
        "--automation-names",
        action="store_true",
        help="创建自动化专项用的 AT- 收费标准；默认使用房间映射表中的业务名称。",
    )
    parser.add_argument("--headful", action="store_true")
    parser.add_argument(
        "--fresh-login",
        action="store_true",
        help="不复用旧 storage state，使用目标客户本地凭据重新登录。",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="仅按收费标准名称精确查询，不进入新增或修改数据。",
    )
    parser.add_argument("--slow-mo", type=int, default=150)
    parser.add_argument(
        "--delete-created-on-failure",
        action="store_true",
        help="仅删除本次运行已创建、且后续验证失败的收费标准。",
    )
    parser.add_argument(
        "--inspect-room",
        nargs="+",
        help="依次打开指定房间公式并输出动态字段结构，不保存。",
    )
    return parser.parse_args()


def restore_session(context, profile, base_url: str) -> None:
    storage = json.loads(profile.session_file.read_text(encoding="utf-8"))
    hostname = urlparse(base_url).hostname
    storage_json = json.dumps(storage, ensure_ascii=False)
    hostname_json = json.dumps(hostname)
    context.add_init_script(
        script="""
        (() => {
          const storage = __STORAGE__;
          const hostname = __HOSTNAME__;
          if (location.hostname === hostname) {
            for (const [key, value] of Object.entries(storage)) {
              sessionStorage.setItem(key, value);
            }
          }
        })();
        """.replace("__STORAGE__", storage_json).replace(
            "__HOSTNAME__", hostname_json
        )
    )


def to_data(
    mapping, project: str, *, automation_names: bool = True
) -> ChargeStandardData:
    parameters = {
        part.split("=", 1)[0]: part.split("=", 1)[1]
        for part in mapping.calculation_parameters.split(";")
        if "=" in part
    }
    formula = mapping.formula
    usage_price_tiers = ()
    usage_coefficient_tiers = ()
    if "多阶梯多单价" in formula or "累计用量计费" in formula:
        usage_price_tiers = (("", "10", "1.5"), ("10", "", "2"))
    if "多阶梯多系数" in formula:
        usage_coefficient_tiers = (("", "10", "2"), ("11", "", "3"))
    commission_percentage_tiers = ()
    commission_amount_tiers = ()
    if "抽成比例阶梯" in parameters:
        commission_percentage_tiers = (
            ("", "10000", "10"),
            ("10000", "20000", "20"),
            ("20000", "", "25"),
        )
    if "抽成金额阶梯" in parameters:
        commission_amount_tiers = (
            ("", "10000", "1000"),
            ("10000", "", "2000"),
        )
    return ChargeStandardData(
        name=(
            automation_standard_name(mapping.standard_name)
            if automation_names
            else mapping.standard_name
        ),
        charge_type=UI_CHARGE_TYPES.get(mapping.charge_type, mapping.charge_type),
        charge_item=CHARGE_ITEM_NAMES[mapping.charge_type],
        project_name=project,
        formula=formula,
        area_type=mapping.area_type,
        partial_month_rule=mapping.partial_month_rule,
        monthly_unit_price=parameters.get("月单价", ""),
        fixed_monthly_amount=parameters.get("月固定金额", ""),
        coefficient=parameters.get("系数", ""),
        # “楼层阶梯”同名参数在仪表多阶梯公式中表示用量/系数档位，
        # 不应误走周期/临时类的“新增楼层行”控件。
        floor_tiers=(
            (("1", "10", "2"), ("11", "20", "3"))
            if "楼层阶梯" in parameters and "周期阶梯计费" in formula
            else ()
        ),
        floor_fixed_tiers=(
            (("1", "10", "100"), ("11", "20", "200"))
            if "楼层固定金额阶梯" in parameters
            else ()
        ),
        area_fixed_tiers=(
            (("", "200", "10"), ("200", "", "15"))
            if "面积固定金额阶梯" in parameters
            else ()
        ),
        unit_price=parameters.get("单价", ""),
        fixed_amount=parameters.get("固定金额", ""),
        usage_price_tiers=usage_price_tiers,
        usage_coefficient_tiers=usage_coefficient_tiers,
        merge_customer_room_usage=(
            True if "累计用量计费" in formula else None
        ),
        commission_percentage=parameters.get("抽成比例", "").removesuffix("%"),
        commission_percentage_tiers=commission_percentage_tiers,
        commission_amount_tiers=commission_amount_tiers,
    )


def ensure_logged_in(
    page,
    base_url: str,
    environment: str,
    customer_id: str,
    role: str,
    *,
    force_login: bool = False,
) -> None:
    customer_home_url = (
        f"{base_url}?mcid={customer_id}&masterCustomerId={customer_id}"
        f"#/Home?masterCustomerId={customer_id}"
    )
    if force_login:
        credentials = load_credentials(environment, customer_id, role)
        if credentials is None:
            raise AssertionError("本地未配置该账号凭据，无法执行全新登录。")
        username, password, captcha = credentials
        page.goto(f"{base_url}#/login", wait_until="domcontentloaded")
        page.get_by_placeholder("用户名").fill(username)
        page.get_by_placeholder("密码").fill(password)
        page.get_by_placeholder("验证码", exact=True).fill(captcha)
        login_button = page.locator("button:visible").filter(
            has_text=re.compile(r"登\s*录")
        )
        if login_button.count() != 1:
            raise AssertionError("登录按钮未唯一匹配。")
        login_button.click()
        page.wait_for_url("**#/Home**", timeout=60_000)
        page.wait_for_timeout(3_000)
        # 登录接口可能恢复账号上一次访问的客户。登录成功后必须显式切到
        # 目标客户完整地址，避免外层 mcid 与路由 masterCustomerId 混用。
        page.goto(customer_home_url, wait_until="domcontentloaded")
        page.wait_for_timeout(3_000)
        page.get_by_role(
            "menuitem", name="云收费", exact=True
        ).wait_for(state="visible", timeout=60_000)
        return

    page.goto(customer_home_url, wait_until="domcontentloaded")
    cloud_billing = page.get_by_role("menuitem", name="云收费", exact=True)
    try:
        cloud_billing.wait_for(state="visible", timeout=10_000)
        page.wait_for_timeout(3_000)
        kicked = page.get_by_text("您的账号在其他地方登录", exact=False)
        if kicked.count() == 0 or not kicked.first.is_visible():
            return
    except Exception:
        pass

    credentials = load_credentials(environment, customer_id, role)
    if credentials is None:
        raise AssertionError("登录状态失效且本地未配置该账号凭据。")
    username, password, captcha = credentials
    page.goto(f"{base_url}#/login", wait_until="domcontentloaded")
    page.get_by_placeholder("用户名").fill(username)
    page.get_by_placeholder("密码").fill(password)
    page.get_by_placeholder("验证码", exact=True).fill(captcha)
    login_button = page.locator("button:visible").filter(
        has_text=re.compile(r"登\s*录")
    )
    if login_button.count() != 1:
        raise AssertionError("登录按钮未唯一匹配。")
    login_button.click()
    page.wait_for_url("**#/Home**", timeout=60_000)
    page.wait_for_timeout(3_000)
    cloud_billing.wait_for(state="visible", timeout=30_000)


def main() -> None:
    args = parse_args()
    load_test_environment(ROOT, args.environment, override=True)
    import os

    base_url = os.environ["BASE_URL"]
    master_customer_id = os.environ["MASTER_CUSTOMER_ID"]
    profile = get_account_auth_profile(
        ROOT, args.account, args.environment, args.customer_id
    )
    if not profile.auth_file.exists() or not profile.session_file.exists():
        raise SystemExit("未找到对应环境、客户和账号的本地登录状态。")

    requested = set(args.rooms)
    selected = [x for x in formula_mappings() if x.room_name in requested]
    missing = requested - {x.room_name for x in selected}
    if missing:
        raise SystemExit(f"映射表不存在房间：{sorted(missing)}")

    results: list[dict[str, str]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=not args.headful, slow_mo=args.slow_mo
        )
        context = (
            browser.new_context()
            if args.fresh_login
            else browser.new_context(storage_state=str(profile.auth_file))
        )
        if not args.fresh_login:
            restore_session(context, profile, base_url)
        page = context.new_page()
        ensure_logged_in(
            page,
            base_url,
            args.environment,
            args.customer_id,
            args.account,
            force_login=args.fresh_login,
        )
        PortalPage(page).dismiss_home_overlays()
        PortalPage(page).collapse_customer_service()
        standards = ChargeStandardPage(page)
        standards.open(expected_customer_id=args.customer_id)

        created_names: list[str] = []
        if args.inspect_room:
            inspections = {}
            for room in args.inspect_room:
                mapping = next(
                    (x for x in selected if x.room_name == room), None
                )
                if mapping is None:
                    raise SystemExit(
                        "--inspect-room 必须同时包含在 --rooms 中。"
                    )
                inspections[room] = standards.inspect_dynamic_fields(
                    to_data(
                        mapping,
                        args.project,
                        automation_names=args.automation_names,
                    )
                )
                print(json.dumps(
                    {room: inspections[room]},
                    ensure_ascii=False,
                    indent=2,
                ).encode("gbk", errors="backslashreplace").decode("gbk"), flush=True)
            print(json.dumps(
                inspections,
                ensure_ascii=False,
                indent=2,
            ).encode("gbk", errors="backslashreplace").decode("gbk"))
            context.close()
            browser.close()
            return

        for mapping in selected:
            result = {"room": mapping.room_name, "name": mapping.standard_name}
            try:
                if mapping.creation_policy != "创建":
                    result["status"] = "skipped-by-policy"
                    result["reason"] = mapping.creation_policy
                    results.append(result)
                    continue
                data = to_data(
                    mapping,
                    args.project,
                    automation_names=args.automation_names,
                )
                exists = standards.exists(data.name)
                if args.verify_only:
                    result["status"] = "exists" if exists else "missing"
                elif exists:
                    result["status"] = "skipped-existing"
                else:
                    standards.create(data)
                    created_names.append(data.name)
                    if not standards.exists(data.name):
                        raise AssertionError("保存后未查询到精确名称")
                    result["status"] = "created"
            except Exception as exc:
                result["status"] = "failed"
                result["reason"] = str(exc)
                results.append(result)
                if args.delete_created_on_failure:
                    standards.cancel_open_create_dialog()
                    for created_name in reversed(created_names):
                        standards.delete_exact(created_name)
                break
            results.append(result)

        RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
        RESULT_FILE.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        context.close()
        browser.close()

    output = json.dumps(results, ensure_ascii=False, indent=2)
    try:
        print(output)
    except UnicodeEncodeError:
        print(output.encode("gbk", errors="backslashreplace").decode("gbk"))
    if any(item["status"] == "failed" for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
