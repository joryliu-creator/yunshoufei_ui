from copy import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))

from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation


OUTPUT = ROOT / "UI自动化回归测试用例模板_Demo.xlsx"
SOURCE_CANDIDATES = [
    ROOT / "UI自动化回归测试用例模板_V2.xlsx",
    OUTPUT,
    ROOT / "UI自动化回归测试用例模板_Demo_已调整.xlsx",
    ROOT / "UI自动化回归测试用例模板.xlsx",
]


CASE = [
    "YSF-BILL-001",
    "云收费",
    "智能计费/账单中心",
    "创建账单",
    "为周期性收费房间创建7月账单",
    "P0",
    "正向",
    "是",
    "用户已登录且拥有账单中心新增权限；项目、房间及周期性收费项已配置；目标账期不存在重复账单",
    "1. 进入云收费/账单中心\n"
    "2. 选择项目“${PROJECT_NAME}”\n"
    "3. 点击“创建账单”\n"
    "4. 清空房间输入框并展开房间树，勾选“${ROOM_PATH}”，点击房间树弹窗的“确定”；确认后等待系统查询该房间的收费项\n"
    "5. 应收日期选择“${RECEIVABLE_DATE}”，账期选择“${BILLING_MONTH}”\n"
    "6. 收费类型选择“${CHARGE_TYPE}”，收费项选择“${CHARGE_ITEM}”\n"
    "7. 最晚缴款日选择“${LATEST_PAYMENT_DATE}”\n"
    "8. 确认系统生成的计费期间属于“${BILLING_MONTH}”\n"
    "9. 点击“确定”\n"
    "10. 在账单通知提示中点击“不需要”\n"
    "11. 如启用清理：返回账单中心，按账期筛选并通过新账单编号唯一定位该账单\n"
    "12. 勾选该账单，点击“更多/批量作废”，填写作废理由，点击“确定作废”，确认账单状态为“已作废”\n"
    "13. 再次勾选该账单，点击“更多/批量删除”，在删除确认提示中点击“确定”，确认列表中不再显示该账单编号",
    "PROJECT_NAME=云收费自动化MS1\n"
    "ROOM_PATH=云收费自动化MS/1/周期性收费房间001\n"
    "CHARGE_TYPE=周期类\n"
    "CHARGE_ITEM=周期性收费项\n"
    "BILLING_MONTH=2026-07\n"
    "RECEIVABLE_DATE=执行当天\n"
    "LATEST_PAYMENT_DATE=执行当天\n"
    "CLEANUP_CREATED_BILL=false\n"
    "ALLOW_BILL_DELETION=false\n"
    "VOID_REASON=UI自动化Demo数据清理\n"
    "ACCOUNT_ROLE=default\n"
    "TEST_ENV=standard1\n"
    "CUSTOMER_ID=93537",
    "1. 创建账单弹窗正常打开\n"
    "2. 房间树点击“确定”后触发收费项查询；房间、收费类型、收费项、账期和日期显示为目标值\n"
    "3. 点击确定后显示账单通知选择提示\n"
    "4. 点击“不需要”后弹窗关闭\n"
    "5. 账单中心出现新账单，且提供详情、作废、修改操作\n"
    "6. 计费期间必须属于目标账期；不一致时禁止提交并报告失败\n"
    "7. 启用清理时，仅按新账单编号定位的账单被批量作废，作废理由保存成功且状态变为“已作废”\n"
    "8. 批量删除确认后，列表不再显示该账单编号",
    "DEFAULT / 测试管理员",
    "新增",
    "是-需确认",
    "已自动化",
    "需要已保存登录状态；房间已配置周期性收费项；同一账期不可重复出账；删除清理需双重安全开关",
    "smoke,billing,create-bill,side-effect",
    "有效",
    "脚本默认跳过；真实巡检发现直接填写2026-07可能仍按2026-08出账，框架已增加计费期间断言",
]


DATA_ROWS = [
    ["DATA-BILL-001", "standard1", "云收费", "PROJECT_NAME", "云收费自动化MS1", "固定业务数据", "客户 93537 的创建账单项目", "项目存在且账号可访问", "否", "无需清理", "有效", ""],
    ["DATA-BILL-002", "standard1", "云收费", "ROOM_PATH", "云收费自动化MS/1/周期性收费房间001", "固定业务数据", "创建账单房间", "房间已配置周期性收费项", "否", "账单按环境策略清理", "有效", "选择后必须点击房间树弹窗的“确定”以触发收费项查询"],
    ["DATA-BILL-003", "standard1", "云收费", "CHARGE_TYPE", "周期类", "固定业务数据", "收费类型", "类型已启用", "否", "无需清理", "有效", ""],
    ["DATA-BILL-004", "standard1", "云收费", "CHARGE_ITEM", "周期性收费项", "固定业务数据", "收费项", "收费项已绑定房间", "否", "无需清理", "有效", ""],
    ["DATA-BILL-005", "standard1", "云收费", "BILLING_MONTH", "2026-07", "用例参数", "账期", "不存在重复账单", "是", "执行前更换为可出账账期", "有效", "格式 YYYY-MM"],
    ["DATA-BILL-006", "standard1", "云收费", "RECEIVABLE_DATE", "执行当天", "动态数据", "应收日期", "系统日期正确", "是", "无需清理", "有效", "格式 YYYY-MM-DD"],
    ["DATA-BILL-007", "standard1", "云收费", "LATEST_PAYMENT_DATE", "执行当天", "动态数据", "最晚缴款日", "系统日期正确", "是", "无需清理", "有效", "格式 YYYY-MM-DD"],
    ["DATA-BILL-008", "standard1", "云收费", "CLEANUP_CREATED_BILL", "false", "安全开关", "执行后清理", "仅非生产测试环境允许", "是", "批量作废后批量删除", "有效", "与 ALLOW_BILL_DELETION 同时为 true 才执行"],
    ["DATA-BILL-009", "standard1", "云收费", "ALLOW_BILL_DELETION", "false", "安全开关", "允许永久删除", "已确认删除范围", "是", "按账期筛选并按新账单编号唯一定位", "有效", "默认关闭；严禁仅按宽泛筛选条件删除"],
    ["DATA-BILL-010", "standard1", "云收费", "VOID_REASON", "UI自动化Demo数据清理", "用例参数", "账单作废原因", "作废前账单为未收", "是", "记录到作废原因", "有效", ""],
    ["DATA-BILL-011", "standard1", "云收费", "ACCOUNT_ROLE", "default", "账号别名", "选择客户下的用例登录账号", "已保存该环境、客户和别名的登录状态", "是", "无需清理", "有效", "真实账号密码仅维护在本地环境文件"],
    ["DATA-BILL-012", "standard1", "云收费", "TEST_ENV", "standard1", "环境别名", "选择运行环境", "环境配置存在", "否", "无需清理", "有效", "标准1环境"],
    ["DATA-BILL-013", "standard1", "云收费", "CUSTOMER_ID", "93537", "客户数据", "选择客户及其项目和账号", "客户存在且账号属于该客户", "否", "无需清理", "有效", "标准1环境客户号"],
]


ACCOUNT_ROWS = [
    ["DEFAULT", "standard1", "93537", "本地默认测试账号", "测试管理员", "云收费自动化MS1", "云收费/账单中心", "创建账单、批量作废、批量删除", "未经授权的生产操作", "是", "兼容现有 Demo；真实凭据仅维护在本地环境文件"],
    ["BILLING_ADMIN", "standard1", "93537", "待本地配置", "收费管理员", "待分配", "云收费/账单中心", "出账、作废、删除", "超出授权范围的资金操作", "否", "配置项目权限、凭据和登录状态后启用"],
    ["CASHIER", "standard1", "93537", "待本地配置", "收银员", "待分配", "云收费/收银台", "缴费", "退款审批、账单删除", "否", "配置项目权限、凭据和登录状态后启用"],
    ["FINANCE_ADMIN", "standard1", "93537", "待本地配置", "财务管理员", "待分配", "云收费/实收管理", "退款、退款审核", "未经授权的账单删除", "否", "配置项目权限、凭据和登录状态后启用"],
]


SCENARIO_HEADERS = [
    ("场景编号*", "稳定且唯一，例如 PERIODIC_AREA_001；测试用例通过此编号引用场景。"),
    ("场景名称*", "说明该房间主要验证的收费规则。"),
    ("环境*", "standard1、standard2、uat 或 prod。"),
    ("客户号*", "该场景所属客户号。"),
    ("项目名称*", "账号必须拥有该项目权限。"),
    ("房间路径*", "建议一个互不兼容的收费标准使用一个专用房间。"),
    ("房间业务ID", "如可从接口获取，请同时维护稳定业务 ID。"),
    ("客户名称", "房间收费设置中绑定的客户。"),
    ("账单接收人", "来源于人员基础的账单接收人。"),
    ("收费类型*", "周期类、仪表类、押金类、临时类或其他。"),
    ("收费项*", "云收费中配置并绑定到房间的收费项。"),
    ("收费标准*", "本场景要验证的具体收费标准。"),
    ("收费标准编码", "如有稳定编码，建议维护以避免同名。"),
    ("生效开始*", "收费标准对目标账期必须已经生效，格式 YYYY-MM-DD。"),
    ("生效结束", "长期有效可留空，格式 YYYY-MM-DD。"),
    ("计费公式*", "使用业务可读公式，例如 面积×单价。"),
    ("计算参数*", "每行一个 KEY=VALUE，例如 AREA=80 和 UNIT_PRICE=2.5。"),
    ("测试账期*", "用于该场景回归的可出账账期，格式 YYYY-MM。"),
    ("减免配置", "填写无减免、固定金额减免、比例减免等规则及参数。"),
    ("预期原始金额*", "人工确认或独立计算得出的金额，不要复制系统实际结果。"),
    ("预期减免金额", "无减免时填写 0。"),
    ("预期应收金额*", "用于账单金额断言。"),
    ("舍入规则", "例如 四舍五入保留2位。"),
    ("前置条件", "记录客户、接收人、收费项、标准和依赖数据的状态。"),
    ("是否共享房间*", "存在并发或账单冲突时必须为“否”。"),
    ("维护状态*", "模板、待补充、已核验或已停用。"),
    ("是否启用*", "只有“是”才允许自动化读取执行。"),
    ("数据负责人", "负责维护该场景基准数据的人员或团队。"),
    ("最近检查日期", "最近人工或自动健康检查日期，格式 YYYY-MM-DD。"),
    ("备注", "补充特殊规则、依赖数据和清理要求。"),
]


SCENARIO_ROWS = [
    [
        "YSF-SCENE-PERIODIC-001", "当前Demo-周期类出账", "standard1", "93537",
        "云收费自动化MS1", "云收费自动化MS/1/周期性收费房间001", "", "", "",
        "周期类", "周期性收费项", "待补充实际收费标准", "", "", "",
        "按收费标准配置", "请填写实际计算参数", "2026-07", "无减免", "", "0", "",
        "系统配置", "房间已绑定客户、接收人、收费项、收费标准且目标账期有效",
        "否", "待补充", "否", "", "",
        "补充收费标准、生效时间、计算参数和预期金额，人工核验后再启用",
    ],
    [
        "TEMPLATE-PERIODIC-FIXED", "复制后修改-周期固定金额", "", "", "", "", "", "", "",
        "周期类", "", "", "", "", "", "固定金额", "FIXED_AMOUNT=", "", "无减免", "", "0", "",
        "四舍五入保留2位", "", "否", "模板", "否", "", "", "模板行，请复制并更换场景编号",
    ],
    [
        "TEMPLATE-PERIODIC-AREA", "复制后修改-周期面积计费", "", "", "", "", "", "", "",
        "周期类", "", "", "", "", "", "面积×单价", "AREA=\nUNIT_PRICE=", "", "无减免", "", "0", "",
        "四舍五入保留2位", "房间面积已维护", "否", "模板", "否", "", "", "模板行，请复制并更换场景编号",
    ],
    [
        "TEMPLATE-METER", "复制后修改-仪表计费", "", "", "", "", "", "", "",
        "仪表类", "", "", "", "", "", "(本次读数-上次读数)×单价",
        "PREVIOUS_READING=\nCURRENT_READING=\nUNIT_PRICE=", "", "无减免", "", "0", "",
        "四舍五入保留2位", "仪表已绑定且读数数据已准备", "否", "模板", "否", "", "",
        "模板行，请复制并更换场景编号",
    ],
    [
        "TEMPLATE-DEPOSIT", "复制后修改-押金计费", "", "", "", "", "", "", "",
        "押金类", "", "", "", "", "", "固定金额或数量×单价", "QUANTITY=\nUNIT_PRICE=", "", "无减免", "", "0", "",
        "四舍五入保留2位", "", "否", "模板", "否", "", "", "模板行，请复制并更换场景编号",
    ],
    [
        "TEMPLATE-TEMPORARY", "复制后修改-临时计费", "", "", "", "", "", "", "",
        "临时类", "", "", "", "", "", "数量×单价", "QUANTITY=\nUNIT_PRICE=", "", "无减免", "", "0", "",
        "四舍五入保留2位", "", "否", "模板", "否", "", "", "模板行，请复制并更换场景编号",
    ],
]


def first_empty_row(ws, key_column=1, start=2):
    for row in range(start, ws.max_row + 1):
        if ws.cell(row, key_column).value in (None, ""):
            return row
    return ws.max_row + 1


def find_or_empty_row(ws, key, key_column=1, start=2):
    for row in range(start, ws.max_row + 1):
        if ws.cell(row, key_column).value == key:
            return row
    return first_empty_row(ws, key_column=key_column, start=start)


def resolve_source():
    for candidate in SOURCE_CANDIDATES:
        if candidate.exists():
            return candidate
    names = "、".join(path.name for path in SOURCE_CANDIDATES)
    raise FileNotFoundError(f"未找到可用 Excel 底稿：{names}")


def ensure_account_role_schema(ws):
    if ws.cell(1, 3).value != "客户号*":
        ws.insert_cols(3)
        ws.cell(1, 3)._style = copy(ws.cell(1, 2)._style)
    if ws.cell(1, 6).value != "可访问项目*":
        ws.insert_cols(6)
        ws.cell(1, 6)._style = copy(ws.cell(1, 5)._style)
    headers = [
        "账号变量名*",
        "环境*",
        "客户号*",
        "账号标识",
        "角色名称*",
        "可访问项目*",
        "可访问模块*",
        "允许操作*",
        "禁止操作*",
        "是否启用*",
        "备注",
    ]
    for column, value in enumerate(headers, 1):
        ws.cell(1, column, value)


def remove_legacy_account_rows(ws):
    """移除旧模板中直接维护真实账号变量的示例行。"""
    for row in range(ws.max_row, 1, -1):
        if ws.cell(row, 1).value == "TEST_USERNAME":
            ws.delete_rows(row, 1)


def find_account_row(ws, account_alias, environment, customer_id):
    legacy_match = None
    for row in range(2, ws.max_row + 1):
        if ws.cell(row, 1).value != account_alias:
            continue
        if (
            ws.cell(row, 2).value == environment
            and str(ws.cell(row, 3).value or "") == str(customer_id)
        ):
            return row
        if legacy_match is None:
            legacy_match = row
    return legacy_match or first_empty_row(ws)


def copy_row_style(ws, source_row, target_row, max_col):
    ws.row_dimensions[target_row].height = ws.row_dimensions[source_row].height
    for col in range(1, max_col + 1):
        source = ws.cell(source_row, col)
        target = ws.cell(target_row, col)
        if source.has_style:
            target._style = copy(source._style)
        if source.number_format:
            target.number_format = source.number_format
        if source.alignment:
            target.alignment = copy(source.alignment)
        if source.border:
            target.border = copy(source.border)


def ensure_charge_scenario_sheet(workbook):
    sheet_name = "收费场景配置"
    created = sheet_name not in workbook.sheetnames
    ws = workbook.create_sheet(sheet_name) if created else workbook[sheet_name]

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    for column, (header, help_text) in enumerate(SCENARIO_HEADERS, 1):
        cell = ws.cell(1, column, header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )
        cell.comment = Comment(help_text, "Codex")

    existing_ids = {
        ws.cell(row, 1).value
        for row in range(2, ws.max_row + 1)
        if ws.cell(row, 1).value
    }
    for item in SCENARIO_ROWS:
        if item[0] in existing_ids:
            continue
        row = first_empty_row(ws)
        for column, value in enumerate(item, 1):
            cell = ws.cell(row, column, value)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        ws.row_dimensions[row].height = 72

    widths = {
        "A": 27, "B": 25, "C": 13, "D": 14, "E": 23, "F": 38,
        "G": 17, "H": 20, "I": 20, "J": 13, "K": 22, "L": 25,
        "M": 18, "N": 14, "O": 14, "P": 28, "Q": 34, "R": 13,
        "S": 28, "T": 17, "U": 17, "V": 17, "W": 20, "X": 42,
        "Y": 17, "Z": 15, "AA": 15, "AB": 18, "AC": 18, "AD": 42,
    }
    for column, width in widths.items():
        ws.column_dimensions[column].width = width
    ws.row_dimensions[1].height = 42
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:AD{max(ws.max_row, 2)}"

    if created:
        validations = [
            ("C2:C1000", '"standard1,standard2,uat,prod"'),
            ("J2:J1000", '"周期类,仪表类,押金类,临时类,其他"'),
            ("Y2:Y1000", '"否,是"'),
            ("Z2:Z1000", '"模板,待补充,已核验,已停用"'),
            ("AA2:AA1000", '"否,是"'),
        ]
        for cell_range, options in validations:
            validation = DataValidation(
                type="list", formula1=options, allow_blank=True
            )
            validation.error = "请选择下拉列表中的有效值。"
            validation.errorTitle = "无效值"
            ws.add_data_validation(validation)
            validation.add(cell_range)
    return ws


def main():
    source = resolve_source()
    workbook = load_workbook(source)

    cases = workbook["用例清单"]
    case_row = find_or_empty_row(cases, CASE[0])
    copy_row_style(cases, max(2, case_row - 1), case_row, 20)
    for column, value in enumerate(CASE, 1):
        cases.cell(case_row, column, value)
    cases.row_dimensions[case_row].height = 210

    test_data = workbook["测试数据"]
    for item in DATA_ROWS:
        data_row = find_or_empty_row(test_data, item[0])
        copy_row_style(test_data, max(2, data_row - 1), data_row, 12)
        for column, value in enumerate(item, 1):
            test_data.cell(data_row, column, value)
        test_data.row_dimensions[data_row].height = 54

    accounts = workbook["账号角色"]
    ensure_account_role_schema(accounts)
    remove_legacy_account_rows(accounts)
    for item in ACCOUNT_ROWS:
        account_row = find_account_row(accounts, item[0], item[1], item[2])
        copy_row_style(accounts, max(2, account_row - 1), account_row, 11)
        for column, value in enumerate(item, 1):
            accounts.cell(account_row, column, value)
        accounts.row_dimensions[account_row].height = 42

    scenarios = ensure_charge_scenario_sheet(workbook)

    workbook.save(OUTPUT)
    print(f"source={source}")
    print(f"created={OUTPUT}")
    print(f"case_row={case_row}, case_id={cases.cell(case_row, 1).value}")
    print(f"test_data_rows={len(DATA_ROWS)}")
    print(f"account_rows={len(ACCOUNT_ROWS)}")
    print(f"scenario_rows={scenarios.max_row - 1}")


if __name__ == "__main__":
    main()
