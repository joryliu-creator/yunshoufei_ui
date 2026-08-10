from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / ".tools" / "python"))

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation


OUTPUT = Path(__file__).parent / "UI自动化回归测试用例模板_V2.xlsx"

HEADERS = [
    "用例编号*", "一级模块*", "二级模块", "功能点*", "用例名称*", "优先级*",
    "用例类型*", "是否主流程*", "前置条件*", "操作步骤*", "测试数据",
    "预期结果*", "账号/角色", "数据影响*", "风险操作*", "自动化状态*",
    "依赖条件", "标签", "维护状态*", "备注",
]

SAMPLES = [
    [
        "YSF-LOGIN-001", "登录", "密码登录", "有效账号登录", "测试账号登录成功",
        "P0", "正向", "是", "测试环境可访问；测试账号有效；验证码策略可用",
        "1. 打开登录页\n2. 切换到密码登录\n3. 输入用户名、密码和验证码\n4. 点击登录",
        "用户名=${TEST_USERNAME}\n密码=${TEST_PASSWORD}\n验证码=${CAPTCHA}",
        "1. 登录页正常显示\n2. 密码登录页签被选中\n3. 信息可正常输入\n4. 跳转首页并显示当前用户名",
        "测试账号/普通管理员", "只读", "否", "可自动化", "验证码需固定或提供测试方案",
        "smoke,login", "有效", "密码必须通过环境变量提供，不写入 Excel",
    ],
    [
        "YSF-CASHIER-001", "云收费", "智能计费/收银台", "模块切换", "进入云收费收银台",
        "P0", "正向", "是", "用户已登录且拥有云收费权限",
        "1. 点击顶部“云收费”\n2. 等待模块加载完成",
        "项目=云收费自动化MS2",
        "1. 云收费菜单处于选中状态\n2. 默认打开收银台\n3. 显示费用查询区域和当前项目",
        "测试账号/普通管理员", "只读", "否", "可自动化", "账号需具备模块权限",
        "smoke,cloud-fee", "有效", "",
    ],
    [
        "YSF-CASHIER-002", "云收费", "智能计费/收银台", "客户费用查询", "按客户名称查询费用",
        "P1", "正向", "是", "已进入收银台；存在稳定的测试客户和费用数据",
        "1. 输入客户名称\n2. 点击查询\n3. 查看查询结果",
        "客户名称=${CUSTOMER_NAME}",
        "1. 输入框显示目标客户名称\n2. 查询完成且页面无报错\n3. 结果仅包含匹配客户，金额与预置数据一致",
        "测试账号/普通管理员", "只读", "否", "待评估", "需要稳定的客户与账单数据",
        "regression,query", "有效", "请补充稳定测试客户和期望金额",
    ],
]

OPTIONS = {
    "优先级": ["P0", "P1", "P2", "P3"],
    "用例类型": ["正向", "异常", "边界", "权限", "兼容性", "性能观察"],
    "是否主流程": ["是", "否"],
    "数据影响": ["只读", "新增", "修改", "删除", "资金/账务", "外部通知"],
    "风险操作": ["否", "是-需确认", "禁止自动执行"],
    "自动化状态": ["可自动化", "待评估", "不建议自动化", "已自动化"],
    "维护状态": ["有效", "待补充", "暂停", "废弃"],
}

FIELD_NOTES = [
    ("用例编号*", "唯一且稳定，建议：系统-模块-三位序号", "YSF-CASHIER-001", "是"),
    ("一级模块*", "顶部模块或业务域", "云收费", "是"),
    ("二级模块", "左侧菜单路径，用 / 表示层级", "智能计费/收银台", "建议"),
    ("功能点*", "本用例验证的最小功能", "客户费用查询", "是"),
    ("用例名称*", "一句话说明场景和目标", "按客户名称查询费用", "是"),
    ("优先级*", "P0 冒烟；P1 核心回归；P2 一般；P3 低频", "P1", "是"),
    ("用例类型*", "正向、异常、边界、权限等", "正向", "是"),
    ("是否主流程*", "用于先筛选第一批自动化用例", "是", "是"),
    ("前置条件*", "账号权限、页面状态、预置数据等", "已登录且存在测试账单", "是"),
    ("操作步骤*", "按 1、2、3 分行，保持原子化；不写模糊动作", "1. 输入客户名称\n2. 点击查询", "是"),
    ("测试数据", "使用变量或业务标识；不要填写密码、Token 等秘密", "客户=${CUSTOMER_NAME}", "建议"),
    ("预期结果*", "与操作步骤对应，描述可观察、可断言的结果", "列表只显示匹配客户", "是"),
    ("账号/角色", "只写账号用途、标识或角色，不写密码", "普通管理员", "建议"),
    ("数据影响*", "标识是否产生或改变业务数据", "只读", "是"),
    ("风险操作*", "资金、退款、删除、短信等必须明确标记", "禁止自动执行", "是"),
    ("自动化状态*", "用于区分候选、待评估和已实现", "待评估", "是"),
    ("依赖条件", "验证码、第三方系统、定时任务或前序数据", "验证码固定为 0000", "建议"),
    ("标签", "逗号分隔，便于筛选执行", "smoke,query", "可选"),
    ("维护状态*", "用例当前是否有效", "有效", "是"),
    ("备注", "记录待确认内容或补充说明", "待补充期望金额", "可选"),
]


def style_header(ws, row=1):
    fill = PatternFill("solid", fgColor="1F4E78")
    for cell in ws[row]:
        cell.fill = fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def build_workbook():
    wb = Workbook()
    ws = wb.active
    ws.title = "用例清单"
    ws.append(HEADERS)
    for sample in SAMPLES:
        ws.append(sample)
    for _ in range(497):
        ws.append([None] * len(HEADERS))

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:T{ws.max_row}"
    ws.row_dimensions[1].height = 32
    widths = [18, 14, 22, 18, 28, 10, 12, 12, 32, 48, 32, 48, 20, 13, 16, 16, 30, 18, 13, 30]
    thin = Side(style="thin", color="D9E2F3")
    for index, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(index)].width = width
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(HEADERS)):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = Border(bottom=thin)
    for row_no in range(2, 5):
        ws.row_dimensions[row_no].height = 90
    style_header(ws)

    red_fill = PatternFill("solid", fgColor="FCE4D6")
    ws.conditional_formatting.add(
        f"A2:T{ws.max_row}",
        FormulaRule(formula=["$O2=\"禁止自动执行\""], fill=red_fill),
    )

    notes = wb.create_sheet("字段说明")
    notes.append(["字段", "填写说明", "示例", "必填程度"])
    for item in FIELD_NOTES:
        notes.append(item)
    notes.freeze_panes = "A2"
    notes.auto_filter.ref = f"A1:D{notes.max_row}"
    notes.column_dimensions["A"].width = 22
    notes.column_dimensions["B"].width = 64
    notes.column_dimensions["C"].width = 42
    notes.column_dimensions["D"].width = 12
    for row in notes.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    style_header(notes)

    guide = wb.create_sheet("填写指南")
    guide_rows = [
        ["主题", "建议"],
        ["拆分方式", "约 190 条用例建议保留在同一张“用例清单”，通过一级模块、二级模块和标签筛选；不要为每个模块创建结构不同的 Sheet。"],
        ["步骤与预期", "步骤和预期都用编号分行；每个预期必须能从页面、URL、提示、列表或数据状态中直接验证。"],
        ["测试数据", "优先使用 ${变量名}，真实值统一维护在自动化配置中；禁止在 Excel 保存密码、Token、生产隐私数据。"],
        ["风险控制", "删除、真实收费/退款、短信邮件、导出敏感数据等标记为“禁止自动执行”或“是-需确认”。"],
        ["优先顺序", "先整理 P0 主流程，再整理 P1；首批建议选择 10～20 条稳定、数据可控且无高风险副作用的用例。"],
        ["可自动化标准", "步骤确定、元素可定位、数据可准备、预期可断言、执行可重复，且不会造成不可恢复的业务影响。"],
        ["提交给 Codex", "填写后将文件放在当前项目目录并告诉我文件名。我会检查完整性、自动化可行性、重复步骤和风险项。"],
    ]
    for row in guide_rows:
        guide.append(row)
    guide.column_dimensions["A"].width = 20
    guide.column_dimensions["B"].width = 100
    for row in guide.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    style_header(guide)

    test_data = wb.create_sheet("测试数据")
    test_data.append([
        "数据编号*", "环境*", "一级模块*", "变量名*", "变量值*", "数据类型*",
        "用途*", "前置状态", "是否可修改*", "清理方式", "维护状态*", "备注",
    ])
    test_data.append([
        "DATA-001", "test", "云收费", "CUSTOMER_NAME_01", "自动化测试客户", "固定业务数据",
        "客户费用查询", "存在有效账单", "否", "无需清理", "待补充", "请替换为测试环境真实值",
    ])
    test_data.append([
        "DATA-002", "test", "云收费", "ROOM_NAME_01", "A栋/101", "固定业务数据",
        "房间费用查询", "房间已绑定测试客户", "否", "无需清理", "待补充", "请替换为测试环境真实值",
    ])
    test_data.append([
        "DATA-003", "test", "云收费", "EXPECTED_AMOUNT_01", "100.00", "预期值",
        "金额断言", "账单金额稳定", "否", "无需清理", "待补充", "单位：元",
    ])
    for _ in range(197):
        test_data.append([None] * 12)
    test_data.freeze_panes = "A2"
    test_data.auto_filter.ref = f"A1:L{test_data.max_row}"
    for index, width in enumerate([16, 12, 16, 26, 30, 18, 28, 30, 16, 24, 16, 36], 1):
        test_data.column_dimensions[get_column_letter(index)].width = width
    for row in test_data.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for row_no in range(2, 5):
        test_data.row_dimensions[row_no].height = 48
    style_header(test_data)

    accounts = wb.create_sheet("账号角色")
    accounts.append([
        "账号变量名*", "环境*", "账号标识", "角色名称*", "可访问模块*", "允许操作*",
        "禁止操作*", "是否启用*", "备注",
    ])
    accounts.append([
        "TEST_USERNAME", "test", "zhengtao1", "测试管理员", "基础,云收费",
        "查询,新增（限测试数据）", "删除,真实收费,退款,外部通知", "是",
        "密码只放在 .env 的 TEST_PASSWORD 中",
    ])
    for _ in range(48):
        accounts.append([None] * 9)
    accounts.freeze_panes = "A2"
    accounts.auto_filter.ref = f"A1:I{accounts.max_row}"
    for index, width in enumerate([24, 12, 20, 20, 28, 36, 40, 14, 44], 1):
        accounts.column_dimensions[get_column_letter(index)].width = width
    for row in accounts.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    accounts.row_dimensions[2].height = 60
    style_header(accounts)

    options = wb.create_sheet("下拉选项")
    for col, (name, values) in enumerate(OPTIONS.items(), 1):
        options.cell(1, col, name)
        for row, value in enumerate(values, 2):
            options.cell(row, col, value)
        options.column_dimensions[get_column_letter(col)].width = 20
    style_header(options)
    options.sheet_state = "hidden"

    header_to_col = {name.rstrip("*"): index for index, name in enumerate(HEADERS, 1)}
    for option_name, values in OPTIONS.items():
        option_col = list(OPTIONS).index(option_name) + 1
        formula = f"'下拉选项'!${get_column_letter(option_col)}$2:${get_column_letter(option_col)}${len(values)+1}"
        dv = DataValidation(type="list", formula1=formula, allow_blank=True)
        dv.error = "请选择下拉列表中的值"
        dv.errorTitle = "无效选项"
        dv.prompt = f"请选择{option_name}"
        dv.promptTitle = option_name
        ws.add_data_validation(dv)
        target_col = get_column_letter(header_to_col[option_name])
        dv.add(f"{target_col}2:{target_col}{ws.max_row}")

    wb.save(OUTPUT)


if __name__ == "__main__":
    build_workbook()
    check = load_workbook(OUTPUT, read_only=False, data_only=False)
    print(f"created={OUTPUT}")
    print(f"sheets={check.sheetnames}")
    print(f"rows={check['用例清单'].max_row}, columns={check['用例清单'].max_column}")
