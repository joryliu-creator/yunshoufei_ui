from copy import copy
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".tools" / "python"))

from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from scripts.update_room_import_template import formula_mappings
from src.domain.periodic_charge import (
    PeriodicRoomBasis,
    calculate_periodic_amount,
)
from src.domain.meter_charge import MeterReadingBasis, calculate_meter_amount
from src.domain.public_share_charge import PUBLIC_SHARE_BILL_CASES
from scripts.update_room_import_template import CHARGE_ITEM_NAMES


OUTPUT = ROOT / "UI自动化回归测试用例模板_Demo.xlsx"
MAPPING_WORKBOOK = ROOT / "房间收费标准映射表.xlsx"
METER_USAGE_WORKBOOK = ROOT / "线下仪表用量导入模板.xlsx"
if not METER_USAGE_WORKBOOK.exists():
    # 前置数据模板统一归档到子目录时，仪表出账场景仍应复用同一份
    # 用户已核对的用量数据，而不是要求复制一份到项目根目录。
    METER_USAGE_WORKBOOK = (
        ROOT / "前置数据模版文件" / "线下仪表用量导入模板.xlsx"
    )
METER_BILLING_MONTH = "2026-08"
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
    "周期类收费标准出账及应收金额断言",
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
    "8. 提交前确认独立公式计算的预期应收金额为“${EXPECTED_RECEIVABLE_AMOUNT}”\n"
    "9. 确认系统生成的计费期间属于“${BILLING_MONTH}”\n"
    "10. 点击“确定”\n"
    "11. 在账单通知提示中点击“不需要”\n"
    "12. 打开高级搜索，设置收费项和账期；‘收费对象’决定账单归属主体，切换为‘收费对象-房间’后在相邻房间树选择‘${ROOM_PATH}’并确认；‘关联对象’是关联资产的附加条件，按房间清理时留空。按账期+房间+收费项唯一核对本次账单，断言原始金额、减免金额、应收金额与场景预期一致；账单编号仅记录为报告证据\n"
    "13. 如启用清理：按上述业务键唯一定位有效账单；若结果不唯一则停止并报告。勾选目标行，点击“更多/批量作废”，填写“${VOID_REASON}”并确认作废\n"
    "14. 按相同业务键重新查询并确认目标已作废，勾选目标行后点击“更多/批量删除”并确认；再次查询相同组合确认结果为0",
    "SCENARIO_ID=YSF-SCENE-PERIODIC-001",
    "1. 创建账单弹窗正常打开\n"
    "2. 房间树点击“确定”后触发收费项查询；房间、收费类型、收费项、账期和日期显示为目标值\n"
    "3. 点击确定后显示账单通知选择提示\n"
    "4. 点击“不需要”后弹窗关闭\n"
    "5. 账单中心出现新账单并取得唯一账单编号\n"
    "6. 计费期间必须属于目标账期；不一致时禁止提交并报告失败\n"
    "7. 原始金额、减免金额、应收金额与收费场景配置中的独立预期金额一致\n"
    "8. 启用清理时按账期+房间+收费项唯一定位本次账单，完成填写作废原因、批量作废和批量删除；相同组合复查为0，账单编号不作为筛选条件",
    "DEFAULT / 测试管理员",
    "新增",
    "是-需确认",
    "已自动化",
    "基础房间、房间收费设置和收费项已由测试人员导入；同一账期不可重复出账；删除清理需双重安全开关",
    "smoke,billing,create-bill,side-effect",
    "有效",
    "项目统一为云收费UI自动化；预期金额由独立周期计费模型计算，不复制系统结果",
]


WORKBENCH_CASE = [
    "YSF-WORKBENCH-BILL-1001",
    "云收费",
    "工作台/业务办理收费台",
    "房间档案新增账单",
    "1001房间通过工作台房间档案新增周期类账单并清理",
    "P0",
    "正向",
    "是",
    "Standard1 客户93537，使用 DEFAULT 测试管理员；A栋/1层/1001已关联UI周期性收费项及有效收费标准；创建前确认2026-08账期的同房间、同收费项无重复账单",
    "1. 通过顶部导航进入云收费，点击左侧‘业务办理收费台’。\n"
    "2. 选择‘按房间’，输入‘1001’，点击‘立即查询’，等待结果后点击唯一房间‘A栋/1层/1001’，等待房间收费对象档案加载。\n"
    "3. 在‘账单信息’模块点击‘新增账单’。抽屉打开后核验收费对象默认为房间且房间已自动带入‘A栋/1层/1001’；不要再次选择房间。\n"
    "4. 账期设为‘2026-08’，应收日期设为‘2026-08-31’。点击‘新增收费项’，搜索并选择‘UI周期性收费项’，点击抽屉右下角‘确定’。\n"
    "5. 等待收费明细出现，点击该行‘编辑’，将最晚缴款日设为‘2026-08-31’，点击该行‘保存’。核对收费项、收费标准和金额后，点击新增账单抽屉右下角‘确定’。\n"
    "6. 等待房间档案提示账单成功数为1。进入账单中心，按‘收费对象-房间’选择‘A栋/1层/1001’，再设置账期‘2026-08’和收费项‘UI周期性收费项’；确认三个条件都保留后搜索，唯一核对本次账单及金额。账单编号仅作证据，不作筛选条件。\n"
    "7. 清理本次账单：按同一业务键唯一定位，批量作废并填写作废原因；重新查询后批量删除；再次按相同条件查询并确认结果为0。结果不唯一时停止清理并报告。",
    "SCENARIO_ID=YSF-SCENE-PERIODIC-BILL-001",
    "1. 房间档案唯一命中A栋/1层/1001；新增账单抽屉默认带入该房间，无需再次选择。\n"
    "2. 账期为2026-08，应收日及最晚缴款日均为2026-08-31；收费项和收费标准与场景配置一致。\n"
    "3. 创建成功数为1；账单中心按账期+房间+收费项唯一命中，原始金额及应收金额与独立预期3001.20元一致。\n"
    "4. 批量作废、批量删除成功；按相同业务键复查结果为0。",
    "DEFAULT / 测试管理员",
    "新增",
    "是-需确认",
    "已自动化",
    "依赖1001房间、客户、收费项及收费标准已配置；执行前检查账单唯一性；创建和批量删除必须由本地安全开关授权",
    "regression,billing,workbench,create-bill,side-effect",
    "有效",
    "已在Standard1/客户93537实际验证；2026-08账期；自动带入房间，不在新增账单抽屉重复选择",
]


CALCULATION_CASE = [
    "YSF-CALC-PERIODIC-1001",
    "云收费",
    "智能计费/计费出账",
    "常规类出账",
    "1001房间周期类常规计费出账、审核及账单清理",
    "P0",
    "正向",
    "是",
    "用户已登录且拥有计费出账、账单中心作废和删除权限；1001房间已绑定周期类收费项及收费标准；目标账期不存在重复账单",
    "1. 进入智能计费-计费出账，选择项目“${PROJECT_NAME}”\n"
    "2. 在常规类出账点击“开始计算”，计费对象保持按房间\n"
    "3. 点击“请选择房间”，在房间抽屉搜索并勾选“${ROOM_PATH}”的叶子节点，确认右侧已选房间展示后点击“确认”\n"
    "4. 计费账期开始和结束月份均选择“${CALCULATION_BILLING_MONTH}”；计费方式保持自然月\n"
    "5. 点击“请选择计费费项”，在收费项抽屉搜索、选择“${CHARGE_ITEM}”并点击“确认”\n"
    "6. 点击“已确认计算条件，下一步”\n"
    "7. 应收日期设置为账期月第0个月第“${CALCULATION_RULE_DAY}”日；最晚缴款日期设置为应收日期到期后第0个月第“${CALCULATION_RULE_DAY}”日，确认均为账期当月1日\n"
    "8. 点击“开始计算”，等待待处理账单的金额完成，断言金额为“${EXPECTED_RECEIVABLE_AMOUNT}”\n"
    "9. 点击“核对账单”并提交审核；点击“审核账单”-“通过”，审核说明填写“${CALCULATION_AUDIT_COMMENT}”，点击“确定”\n"
    "10. 点击“查看账单”，跳转账单中心后打开高级搜索，按顺序设置收费项“${CHARGE_ITEM}”、账期“${CALCULATION_BILLING_MONTH}”，将“收费对象”切换为“收费对象-房间”并在相邻房间树选择“${ROOM_PATH}”；“关联对象”是关联资产的附加条件，按房间清理时留空。按账期+房间+收费项筛选唯一未作废账单并核对金额；账单编号仅作证据，不作筛选条件\n"
    "11. 清理：勾选唯一目标行，点击“更多/批量作废”并填写“${VOID_REASON}”确认；按相同业务键重新查询并勾选已作废目标，点击“更多/批量删除”确认；相同组合复查为0",
    "SCENARIO_ID=YSF-SCENE-PERIODIC-001",
    "1. 1001与周期类收费项、账期选择正确，计算条件确认按钮可用\n"
    "2. 应收日期、最晚缴款日均为账期当月1日\n"
    "3. 待处理账单金额、账单中心应收金额均为场景独立计算值\n"
    "4. 状态依次完成已计算、已核对、已审核、已出账\n"
    "5. 仅账期+房间+收费项唯一定位的本次账单被批量作废、批量删除；账单编号不作筛选条件，按相同组合复查结果为0",
    "DEFAULT / 测试管理员",
    "新增",
    "是，需确认",
    "已自动化",
    "计费出账与账单中心创建是并行模块；本用例只在审核通过后进入账单中心核对及清理",
    "regression,calculation-billing,periodic,reconcile,audit,void,delete,side-effect",
    "有效",
    "计费账期取执行当月；1001预期金额取收费场景配置的独立周期计算结果",
]


TEMPORARY_CASES = [[
    "YSF-BILL-TEMP-1016",
    "云收费",
    "智能计费/临时台账",
    "创建并清理临时账单",
    "1016房间固定金额临时类账单创建、金额断言及清理",
    "P0",
    "正向",
    "是",
    "用户已登录且拥有临时台账新增、作废和删除权限；A栋/1层/1016已绑定UI临时类收费项及UI临时类-固定金额收费标准",
    "1. 进入智能计费-临时台账页面\n"
    "2. 点击右上角“发起临时缴费”，弹出创建临时账单组件\n"
    "3. 收费对象选择“房间”\n"
    "4. 点击“请选择房间”，在房间树选择“${ROOM_PATH}”，点击房间树“确定”\n"
    "5. 选择年月“${BILLING_MONTH}”\n"
    "6. 选择收费项目“${CHARGE_ITEM}”\n"
    "7. 选择收费标准“${CHARGE_STANDARD}”\n"
    "8. 固定金额标准不填写收费金额；动态参数类填写参数后点击其他位置失焦，等待收款金额计算完成；备注填写“自动化测试出临时账单”\n"
    "9. 是否推送保持“否”，账单接收人不选择\n"
    "10. 提交前断言收款金额为“${EXPECTED_RECEIVABLE_AMOUNT}”\n"
    "11. 点击最终“确定”，确认页面提示推送成功并取得本次账单唯一编号\n"
    "12. 清理：打开高级搜索，依次选择收费项、将起止账期均设为${BILLING_MONTH}\n"
    "13. 将账单对象切换为房间，在右侧可编辑输入框输入房间号，展开完整路径并勾选目标房间后确定\n"
    "14. 点击搜索，按账期+房间+收费项唯一核对结果；账单编号仅记录为证据\n"
    "15. 在匹配行点击“作废”，填写作废说明并确认；再点击“删除”并二次确认\n"
    "16. 重新按相同组合搜索，断言结果为0",
    "SCENARIO_ID=YSF-SCENE-TEMP-1016",
    "1. 创建临时账单组件正常打开\n"
    "2. 房间树确认后收费项目可选且收费标准为目标值\n"
    "3. 提交前预期金额为100.00\n"
    "4. 创建成功后取得唯一账单编号并提示推送成功\n"
    "5. 按账期+房间+收费项执行作废和删除\n"
    "6. 删除确认后相同组合查询结果为0",
    "DEFAULT / 测试管理员",
    "新增",
    "是-需确认",
    "已自动化",
    "基础房间、收费项和收费标准由前置数据流程维护；临时台账清理不同于账单中心批量清理",
    "regression,billing,temporary,create,void,delete,side-effect",
    "有效",
    "固定金额100.00；真实创建和清理受本地安全开关控制",
]]


TEMPORARY_SCENARIO_ROWS = [[
    "YSF-SCENE-TEMP-1016",
    "临时类-1016-固定金额",
    "standard1", "93537", "云收费UI自动化",
    "A栋/1层/1016", "", "", "",
    "临时类", "UI临时类收费项", "UI临时类-固定金额", "",
    "2023-01-01", "2028-12-31", "固定金额", "FIXED_AMOUNT=100",
    "2026-08", "无减免", "100.00", "0.00", "100.00",
    "四舍五入保留2位",
    "客户、房间、收费项和收费标准已配置；目标临时账单由本用例创建",
    "否", "已核验", "是", "云收费测试", "2026-08-18",
    "固定金额收费标准不填写人工收费金额；创建后必须在临时台账按收费项→账期→房间顺序筛选并作废删除",
]]


def temporary_case_row(
    case_id, scenario_id, room_name, standard_name, title, expected_amount,
    manual_amount="", calculation_step=""
):
    amount_step = (
        f"8. 在收费金额输入框填写“{manual_amount}”\n"
        if manual_amount
        else "8. 收费金额由收费标准自动计算；填写动态参数或日期后点击其他位置失焦，等待收款金额显示完成\n"
    )
    return [
        case_id, "云收费", "智能计费/临时台账", "创建并清理临时账单", title,
        "P0", "正向", "是",
        f"用户已登录且拥有临时台账新增、作废和删除权限；A栋/1层/{room_name}已绑定UI临时类收费项及{standard_name}收费标准",
        (
            "1. 进入智能计费-临时台账页面\n"
            "2. 点击右上角“发起临时缴费”\n"
            "3. 收费对象选择“房间”，在房间树选择“${ROOM_PATH}”并点击“确定”\n"
            "4. 选择年月“${BILLING_MONTH}”，选择收费项目“${CHARGE_ITEM}”及收费标准“${CHARGE_STANDARD}”\n"
            + amount_step
            + (f"9. {calculation_step}\n" if calculation_step else "")
            + "10. 备注填写“自动化测试出临时账单”，推送保持“否”，接收人不选择\n"
            "11. 提交前断言收款金额为“${EXPECTED_RECEIVABLE_AMOUNT}”，点击底部“确定”，确认推送成功并记录本次唯一账单编号\n"
            "12. 高级搜索先选择收费项，再将起止账期均设为${BILLING_MONTH}\n"
            "13. 账单对象切换为房间，在右侧可编辑输入框输入房间号，展开完整路径、勾选目标房间并确定后搜索\n"
            "14. 按账期+房间+收费项核对结果，逐条作废并删除；重新搜索断言结果为0"
        ),
        f"SCENARIO_ID={scenario_id}",
        f"1. 创建前预期收费金额为{expected_amount}\n2. 创建成功后已取得唯一账单编号作为证据\n3. 按账期+房间+收费项完成作废删除，重新查询结果为0",
        "DEFAULT / 测试管理员", "新增", "是-需确认", "已自动化",
        "前置房间、收费项和收费标准已配置；清理使用账期+房间+收费项组合条件",
        "regression,billing,temporary,create,void,delete,side-effect", "有效",
        f"预期应收金额={expected_amount}",
    ]


def temporary_scenario_row(
    scenario_id, room_name, standard_name, formula, parameters, expected_amount, manual_amount=""
):
    if manual_amount and "MANUAL_AMOUNT=" not in parameters:
        parameters = f"{parameters};MANUAL_AMOUNT={manual_amount}"
    return [
        scenario_id, f"临时类-{room_name}-{formula}", "standard1", "93537", "云收费UI自动化",
        f"A栋/1层/{room_name}", "", "", "", "临时类", "UI临时类收费项", standard_name, "",
        "2023-01-01", "2028-12-31", formula, parameters, "2026-08", "无减免",
        expected_amount, "0.00", expected_amount, "四舍五入保留2位",
        "客户、房间、收费项和收费标准已配置；目标临时账单由本用例创建",
        "否", "已核验", "是", "云收费测试", "2026-08-18",
        "清理按收费项→账期→房间顺序设置高级搜索；账单编号只作为报告证据",
    ]


TEMPORARY_CASES.extend([
    temporary_case_row(
        "YSF-BILL-TEMP-1013", "YSF-SCENE-TEMP-1013", "1013",
        "UI临时类-面积多阶梯固定金额（不同建筑面积，不同固定金额）",
        "1013房间面积阶梯固定金额临时账单创建、金额断言及清理", "15.00",
    ),
    temporary_case_row(
        "YSF-BILL-TEMP-1014", "YSF-SCENE-TEMP-1014", "1014",
        "UI临时类-楼层多阶梯固定金额（不同楼层，不同固定金额）",
        "1014房间楼层阶梯固定金额临时账单创建、金额断言及清理", "100.00",
    ),
    temporary_case_row(
        "YSF-BILL-TEMP-1015", "YSF-SCENE-TEMP-1015", "1015",
        "UI临时类-人工输入收费金额",
        "1015房间人工输入金额临时账单创建、金额断言及清理", "200.00", "200",
    ),
])

TEMPORARY_SCENARIO_ROWS.extend([
    temporary_scenario_row(
        "YSF-SCENE-TEMP-1013", "1013",
        "UI临时类-面积多阶梯固定金额（不同建筑面积，不同固定金额）",
        "面积多阶梯固定金额（不同面积，不同固定金额）",
        "计费面积=建筑面积;面积固定金额阶梯=0-200:10;200以上:15", "15.00",
    ),
    temporary_scenario_row(
        "YSF-SCENE-TEMP-1014", "1014",
        "UI临时类-楼层多阶梯固定金额（不同楼层，不同固定金额）",
        "楼层多阶梯固定金额（不同楼层，不同固定金额）",
        "楼层固定金额阶梯=1-10:100;11-20:200", "100.00",
    ),
    temporary_scenario_row(
        "YSF-SCENE-TEMP-1015", "1015", "UI临时类-人工输入收费金额",
        "人工输入收费金额", "MANUAL_AMOUNT=200", "200.00", "200",
    ),
])

TEMPORARY_CASES.extend([
    temporary_case_row(
        "YSF-BILL-TEMP-1012", "YSF-SCENE-TEMP-1012", "1012",
        "UI临时类-仪表无阶梯（固定单价*用量*系数）",
        "1012房间仪表系数公式临时账单创建、金额断言及清理", "120.00",
        calculation_step="仪表用量取已导入的20，按单价3、系数2计算预期金额",
    ),
    temporary_case_row(
        "YSF-BILL-TEMP-1017", "YSF-SCENE-TEMP-1017", "1017",
        "UI临时类-天数公式（天单价*建筑面积*天数）",
        "1017房间建筑面积天数公式临时账单创建、金额断言及清理", "120048.00",
        calculation_step="计费期间选择今天至明天两天，按建筑面积300.12、天单价200计算预期金额",
    ),
    temporary_case_row(
        "YSF-BILL-TEMP-1018", "YSF-SCENE-TEMP-1018", "1018",
        "UI临时类-天数公式（天单价*使用面积*天数）",
        "1018房间使用面积天数公式临时账单创建、金额断言及清理", "112004.00",
        calculation_step="计费期间选择今天至明天两天，按使用面积280.01、天单价200计算预期金额",
    ),
    temporary_case_row(
        "YSF-BILL-TEMP-1019", "YSF-SCENE-TEMP-1019", "1019",
        "UI临时类-天数公式（天单价*收费面积*天数）",
        "1019房间收费面积天数公式临时账单创建、金额断言及清理", "104000.00",
        calculation_step="计费期间选择今天至明天两天，按收费面积260.00、天单价200计算预期金额",
    ),
    temporary_case_row(
        "YSF-BILL-TEMP-1020", "YSF-SCENE-TEMP-1020", "1020",
        "UI临时类-数量公式（数量*单价）",
        "1020房间数量公式临时账单创建、金额断言及清理", "200.00",
        calculation_step="数量填写10，按单价20计算预期金额",
    ),
    temporary_case_row(
        "YSF-BILL-TEMP-1059", "YSF-SCENE-TEMP-1059", "1059",
        "UI临时类-面积多阶梯固定金额（不同使用面积，不同固定金额）",
        "1059房间使用面积阶梯固定金额临时账单创建、金额断言及清理", "15.00",
    ),
    temporary_case_row(
        "YSF-BILL-TEMP-1060", "YSF-SCENE-TEMP-1060", "1060",
        "UI临时类-面积多阶梯固定金额（不同收费面积，不同固定金额）",
        "1060房间收费面积阶梯固定金额临时账单创建、金额断言及清理", "15.00",
    ),
])

TEMPORARY_SCENARIO_ROWS.extend([
    temporary_scenario_row(
        "YSF-SCENE-TEMP-1012", "1012",
        "UI临时类-仪表无阶梯（固定单价*用量*系数）",
        "仪表无阶梯（固定单价*用量*系数）",
        "METER_USAGE=20;UNIT_PRICE=3;COEFFICIENT=2", "120.00",
    ),
    temporary_scenario_row(
        "YSF-SCENE-TEMP-1017", "1017",
        "UI临时类-天数公式（天单价*建筑面积*天数）",
        "天数公式（天单价*计费面积*天数）",
        "AREA_TYPE=建筑面积;AREA=300.12;DAY_UNIT_PRICE=200;BILLING_DAYS=2;DATE_RANGE=今天至明天",
        "120048.00",
    ),
    temporary_scenario_row(
        "YSF-SCENE-TEMP-1018", "1018",
        "UI临时类-天数公式（天单价*使用面积*天数）",
        "天数公式（天单价*计费面积*天数）",
        "AREA_TYPE=使用面积;AREA=280.01;DAY_UNIT_PRICE=200;BILLING_DAYS=2;DATE_RANGE=今天至明天",
        "112004.00",
    ),
    temporary_scenario_row(
        "YSF-SCENE-TEMP-1019", "1019",
        "UI临时类-天数公式（天单价*收费面积*天数）",
        "天数公式（天单价*计费面积*天数）",
        "AREA_TYPE=收费面积;AREA=260.00;DAY_UNIT_PRICE=200;BILLING_DAYS=2;DATE_RANGE=今天至明天",
        "104000.00",
    ),
    temporary_scenario_row(
        "YSF-SCENE-TEMP-1020", "1020",
        "UI临时类-数量公式（数量*单价）",
        "数量公式（数量*单价）",
        "QUANTITY=10;UNIT_PRICE=20", "200.00",
    ),
    temporary_scenario_row(
        "YSF-SCENE-TEMP-1059", "1059",
        "UI临时类-面积多阶梯固定金额（不同使用面积，不同固定金额）",
        "面积多阶梯固定金额（不同面积，不同固定金额）",
        "计费面积=使用面积;面积固定金额阶梯=0-200:10;200以上:15", "15.00",
    ),
    temporary_scenario_row(
        "YSF-SCENE-TEMP-1060", "1060",
        "UI临时类-面积多阶梯固定金额（不同收费面积，不同固定金额）",
        "面积多阶梯固定金额（不同面积，不同固定金额）",
        "计费面积=收费面积;面积固定金额阶梯=0-200:10;200以上:15", "15.00",
    ),
])


def meter_case_rows(meter_scenarios):
    rows = []
    for scenario in meter_scenarios:
        room_name = scenario[5].rsplit("/", 1)[-1]
        rows.append([
            f"YSF-BILL-METER-{room_name}",
            "云收费",
            "智能计费/账单中心",
            "创建账单",
            f"仪表类-{room_name}-2026-08出账及金额断言",
            "P0",
            "正向",
            "是",
            "用户已登录且拥有账单中心新增权限；房间收费设置、仪表读数、收费项和收费标准已完成导入；目标账期不存在重复账单",
            "1. 进入云收费/账单中心\n"
            "2. 选择项目“${PROJECT_NAME}”\n"
            "3. 点击“创建账单”\n"
            "4. 清空房间输入框并展开房间树，勾选“${ROOM_PATH}”，点击房间树弹窗的“确定”；确认后等待系统查询该房间的收费项\n"
            "5. 应收日期选择“${RECEIVABLE_DATE}”，账期选择“${BILLING_MONTH}”\n"
            "6. 收费类型选择“${CHARGE_TYPE}”，收费项选择“${CHARGE_ITEM}”\n"
            "7. 最晚缴款日选择“${LATEST_PAYMENT_DATE}”\n"
            "8. 根据收费标准、8月本期用量和累计读数独立计算预期应收金额\n"
            "9. 确认系统生成的计费期间属于“${BILLING_MONTH}”\n"
            "10. 点击创建账单抽屉右下角“确定”，在“账单创建结果”提示中选择“不需要”（不进行账单通知）\n"
            "11. 打开高级搜索，按顺序设置收费项“${CHARGE_ITEM}”、账期“${BILLING_MONTH}”，将“收费对象”切换为“收费对象-房间”并在相邻房间树选择“${ROOM_PATH}”后确认；“关联对象”是关联资产的附加条件，按房间清理时留空。按账期+房间+收费项筛选并唯一核对本次账单；账单编号仅记录为报告证据，断言原始金额、减免金额、应收金额与场景预期一致\n"
            "12. 如启用清理：按上述组合筛选唯一有效账单，勾选后点击“更多/批量作废”，填写“${VOID_REASON}”并确认；再勾选已作废账单，点击“更多/批量删除”并确认；重复组合筛选确认无匹配记录",
            f"SCENARIO_ID={scenario[0]}",
            "1. 创建账单弹窗正常打开\n"
            "2. 房间树确认后，仪表类收费项和账期显示为目标值\n"
            "3. 计费期间属于 2026-08\n"
            "4. 新账单取得唯一账单编号\n"
            "5. 原始金额、减免金额、应收金额与独立计算预期一致\n"
            "6. 启用清理时按账期+房间+收费项唯一定位，不以账单编号作为筛选条件；完成填写作废原因、批量作废、批量删除，并确认相同组合查询结果为0",
            "DEFAULT / 测试管理员",
            "新增",
            "是-需确认",
            "已自动化",
            "仪表用量已导入并人工核对；本期用量、上期/本期读数来源于线下仪表用量导入模板",
            "regression,billing,meter,create-bill,side-effect",
            "有效",
            f"2026-08仪表出账；场景参数中保留仪表编号与用量读数依据",
        ])
    return rows


RUNTIME_PARAMETER_HEADERS = [
    "参数编号*", "环境*", "客户号", "参数名*", "默认值", "参数类型*",
    "用途*", "是否可覆盖*", "维护状态*", "备注",
]


RUNTIME_PARAMETER_ROWS = [
    ["PARAM-001", "standard1", "93537", "TEST_ENV", "standard1", "运行选择", "选择执行环境", "是", "有效", "命令行 --test-env 可覆盖"],
    ["PARAM-002", "standard1", "93537", "CUSTOMER_ID", "93537", "运行选择", "选择客户及其账号和场景", "是", "有效", "命令行 --customer-id 可覆盖"],
    ["PARAM-003", "standard1", "93537", "BILLING_MONTH", "2026-07", "业务运行参数", "目标出账账期", "是", "有效", "格式 YYYY-MM；执行前确认不存在重复账单"],
    ["PARAM-004", "standard1", "93537", "RECEIVABLE_DATE", "执行当天", "日期参数", "应收日期", "是", "有效", "执行当天由代码动态转换为 YYYY-MM-DD"],
    ["PARAM-005", "standard1", "93537", "LATEST_PAYMENT_DATE", "执行当天", "日期参数", "最晚缴款日", "是", "有效", "执行当天由代码动态转换为 YYYY-MM-DD"],
    ["PARAM-006", "standard1", "93537", "SKIP_BILL_NOTIFICATION", "true", "流程开关", "账单创建后选择不需要通知", "是", "有效", "与当前 Demo 流程一致"],
    ["PARAM-007", "standard1", "93537", "VOID_REASON", "UI自动化Demo数据清理", "清理参数", "账单作废原因", "是", "有效", "仅在本地安全开关授权清理后使用"],
    ["PARAM-008", "standard1", "93537", "CALCULATION_BILLING_MONTH", "执行当月", "业务运行参数", "计费出账常规类的开始和结束账期", "是", "有效", "执行时解析为 YYYY-MM；当前 Demo 为 2026-08"],
    ["PARAM-009", "standard1", "93537", "CALCULATION_RULE_DAY", "1", "业务运行参数", "应收日期与最晚缴款日期的日选项", "是", "有效", "应收日期为账期月第0个月第1日；最晚缴款日为应收日后第0个月第1日"],
    ["PARAM-010", "standard1", "93537", "CALCULATION_AUDIT_COMMENT", "Auto自动化计费出账审核", "业务运行参数", "计费出账审核说明", "是", "有效", "审核通过时填写"],
]


OBSOLETE_RUNTIME_PARAMETERS = {
    "SCENARIO_ID",
    "ACCOUNT_ROLE",
    "ALLOW_BILL_CREATION",
    "CLEANUP_CREATED_BILL",
    "ALLOW_BILL_DELETION",
}


ACCOUNT_ROWS = [
    ["DEFAULT", "standard1", "93537", "本地默认测试账号", "测试管理员", "云收费UI自动化", "云收费/业务办理收费台、账单中心", "档案查看、新增账单、批量作废、批量删除", "未经授权的生产操作", "是", "真实凭据仅维护在本地环境文件"],
    ["BILLING_ADMIN", "standard1", "93537", "待本地配置", "收费管理员", "待分配", "云收费/账单中心", "出账、作废、删除", "超出授权范围的资金操作", "否", "配置项目权限、凭据和登录状态后启用"],
    ["CASHIER", "standard1", "93537", "待本地配置", "收银员", "待分配", "云收费/收银台", "缴费", "退款审批、账单删除", "否", "配置项目权限、凭据和登录状态后启用"],
    ["FINANCE_ADMIN", "standard1", "93537", "待本地配置", "财务管理员", "待分配", "云收费/实收管理", "退款、退款审核", "未经授权的账单删除", "否", "配置项目权限、凭据和登录状态后启用"],
]


SCENARIO_HEADERS = [
    ("场景编号*", "稳定且唯一，例如 PERIODIC_AREA_001；测试用例通过此编号引用场景。"),
    ("场景名称*", "说明该房间主要验证的收费规则。"),
    ("环境*", "standard1、standard2、uat 或 prod。"),
    ("客户号*", "该场景所属客户号。"),
    ("项目名称*\n${PROJECT_NAME}", "账号必须拥有该项目权限。"),
    ("房间路径*\n${ROOM_PATH}", "建议一个互不兼容的收费标准使用一个专用房间。"),
    ("房间业务ID", "如可从接口获取，请同时维护稳定业务 ID。"),
    ("客户名称", "房间收费设置中绑定的客户。"),
    ("账单接收人", "来源于人员基础的账单接收人。"),
    ("收费类型*\n${CHARGE_TYPE}", "周期类、仪表类、押金类、临时类或其他。"),
    ("收费项*\n${CHARGE_ITEM}", "云收费中配置并绑定到房间的收费项。"),
    ("收费标准*", "本场景要验证的具体收费标准。"),
    ("收费标准编码", "如有稳定编码，建议维护以避免同名。"),
    ("生效开始*", "收费标准对目标账期必须已经生效，格式 YYYY-MM-DD。"),
    ("生效结束", "长期有效可留空，格式 YYYY-MM-DD。"),
    ("计费公式*", "使用业务可读公式，例如 面积×单价。"),
    ("计算参数*", "每行一个 KEY=VALUE，例如 AREA=80 和 UNIT_PRICE=2.5。"),
    ("建议测试账期", "仅作为场景建议值；实际执行账期由运行参数 BILLING_MONTH 决定。"),
    ("减免配置", "填写无减免、固定金额减免、比例减免等规则及参数。"),
    ("预期原始金额*", "人工确认或独立计算得出的金额，不要复制系统实际结果。"),
    ("预期减免金额", "无减免时填写 0。"),
    ("预期应收金额*\n${EXPECTED_RECEIVABLE_AMOUNT}", "用于账单金额断言。"),
    ("舍入规则", "例如 四舍五入保留2位。"),
    ("前置条件", "记录客户、接收人、收费项、标准和依赖数据的状态。"),
    ("是否共享房间*", "存在并发或账单冲突时必须为“否”。"),
    ("维护状态*", "模板、待补充、已核验或已停用。"),
    ("是否启用*", "只有“是”才允许自动化读取执行。"),
    ("数据负责人", "负责维护该场景基准数据的人员或团队。"),
    ("最近检查日期", "最近人工或自动健康检查日期，格式 YYYY-MM-DD。"),
    ("备注", "补充特殊规则、依赖数据和清理要求。"),
]


PERIODIC_BASIS = PeriodicRoomBasis(
    building_area=Decimal("300.12"),
    usable_area=Decimal("280.01"),
    fee_area=Decimal("260.00"),
    floor=1,
)


def periodic_scenario_rows():
    rows = []
    periodic = [x for x in formula_mappings() if x.charge_type == "周期类"]
    for mapping in periodic:
        amount = calculate_periodic_amount(
            mapping.formula,
            mapping.area_type,
            mapping.calculation_parameters,
            PERIODIC_BASIS,
        )
        scenario_id = (
            "YSF-SCENE-PERIODIC-001"
            if mapping.room_name == "1001"
            else f"YSF-SCENE-PERIODIC-{mapping.room_name}"
        )
        verified = True
        parameters = "\n".join(
            [
                "BUILDING_AREA=300.12",
                "USABLE_AREA=280.01",
                "FEE_AREA=260.00",
                "FLOOR=1",
                "MONTHS=1",
                mapping.calculation_parameters,
            ]
        )
        rows.append([
            scenario_id,
            f"周期类-{mapping.room_name}-{mapping.partial_month_rule}",
            "standard1", "93537", "云收费UI自动化",
            f"A栋/1层/{mapping.room_name}", "", "", "",
            "周期类", "UI周期性收费项", mapping.standard_name, "",
            "2023-01-01", "2028-12-31", mapping.formula, parameters,
            "2026-07", "无减免", format(amount, "f"), "0.00",
            format(amount, "f"), "四舍五入保留2位",
            "房间、收费标准、客户与账单接收人已配置；目标账期不存在重复账单",
            "否", "已核验" if verified else "待补充",
            "是" if verified else "否", "云收费测试", "2026-08-14",
            (
                "2026-08-14研发修复后回归通过；预期金额由独立公式计算"
                if mapping.room_name in {"1011", "1058"}
                else f"不足月规则={mapping.partial_month_rule}；预期金额由独立公式计算"
            ),
        ])
    return rows


def _header_map(worksheet):
    return {
        str(cell.value).strip(): column
        for column, cell in enumerate(worksheet[1], 1)
        if cell.value is not None
    }


def meter_scenario_rows():
    if not MAPPING_WORKBOOK.exists() or not METER_USAGE_WORKBOOK.exists():
        missing = [
            str(path) for path in (MAPPING_WORKBOOK, METER_USAGE_WORKBOOK)
            if not path.exists()
        ]
        raise FileNotFoundError(f"缺少仪表出账场景来源文件：{missing}")

    mapping_book = load_workbook(MAPPING_WORKBOOK, read_only=True, data_only=True)
    mapping_sheet = mapping_book.active
    mapping_headers = _header_map(mapping_sheet)
    usage_book = load_workbook(METER_USAGE_WORKBOOK, read_only=True, data_only=True)
    usage_sheet = usage_book.active
    usage_headers = {
        str(cell.value).strip(): column
        for column, cell in enumerate(usage_sheet[3], 1)
        if cell.value is not None
    }
    required_mapping = {"房间名称", "收费类型", "计费公式", "建议收费标准名称", "计价参数", "创建策略"}
    required_usage = {"仪表编号*", "本期用量*", "本期读数*", "抄表所属月份*"}
    if missing := required_mapping - set(mapping_headers):
        raise ValueError(f"房间收费标准映射表缺少列：{sorted(missing)}")
    if missing := required_usage - set(usage_headers):
        raise ValueError(f"线下仪表用量导入模板缺少列：{sorted(missing)}")

    readings = {}
    for row in range(4, usage_sheet.max_row + 1):
        meter_no = str(usage_sheet.cell(row, usage_headers["仪表编号*"]).value or "").strip()
        month = str(usage_sheet.cell(row, usage_headers["抄表所属月份*"]).value or "").strip()
        if meter_no and month:
            readings[(meter_no, month)] = (
                Decimal(str(usage_sheet.cell(row, usage_headers["本期用量*"]).value)),
                Decimal(str(usage_sheet.cell(row, usage_headers["本期读数*"]).value)),
            )

    rows = []
    for row in range(2, mapping_sheet.max_row + 1):
        charge_type = str(mapping_sheet.cell(row, mapping_headers["收费类型"]).value or "").strip()
        if charge_type not in {"水表仪表类", "电表仪表类"}:
            continue
        if str(mapping_sheet.cell(row, mapping_headers["创建策略"]).value or "").strip() != "创建":
            continue
        room_name = str(mapping_sheet.cell(row, mapping_headers["房间名称"]).value or "").strip()
        meter_prefix = "水表" if charge_type == "水表仪表类" else "电表"
        meter_no = f"{meter_prefix}{room_name}"
        try:
            period_usage, current_reading = readings[(meter_no, METER_BILLING_MONTH)]
            _, previous_reading = readings[(meter_no, "2026-07")]
        except KeyError as exc:
            raise ValueError(f"仪表 {meter_no} 缺少 2026-07 或 2026-08 抄表数据") from exc
        formula = str(mapping_sheet.cell(row, mapping_headers["计费公式"]).value or "").strip()
        standard_name = str(
            mapping_sheet.cell(row, mapping_headers["建议收费标准名称"]).value or ""
        ).strip()
        if standard_name.startswith("AT-"):
            raise ValueError(
                f"仪表出账场景 {room_name} 必须引用房间绑定的正式收费标准名；"
                f"映射表中的名称不应使用收费标准专项 AT- 前缀：{standard_name!r}"
            )
        pricing_parameters = str(mapping_sheet.cell(row, mapping_headers["计价参数"]).value or "").strip()
        basis = MeterReadingBasis(
            period_usage=period_usage,
            previous_reading=previous_reading,
            current_reading=current_reading,
            cumulative_usage=current_reading,
        )
        amount = calculate_meter_amount(formula, pricing_parameters, basis)
        scenario_parameters = "\n".join([
            f"METER_NO={meter_no}",
            f"PREVIOUS_READING={previous_reading}",
            f"CURRENT_READING={current_reading}",
            f"PERIOD_USAGE={period_usage}",
            f"CUMULATIVE_USAGE={current_reading}",
            "FLOOR=1",
            pricing_parameters,
        ])
        rows.append([
            f"YSF-SCENE-METER-{room_name}",
            f"{charge_type}-{room_name}-2026-08出账",
            "standard1", "93537", "云收费UI自动化",
            f"A栋/1层/{room_name}", "", "", "",
            "仪表类", CHARGE_ITEM_NAMES[charge_type], standard_name, "",
            "2023-01-01", "2028-12-31", formula, scenario_parameters,
            METER_BILLING_MONTH, "无减免", format(amount, "f"), "0.00",
            format(amount, "f"), "四舍五入保留2位",
            "房间、客户、账单接收人、仪表、收费项、收费标准和2026-08抄表用量已配置；目标账期不存在重复账单",
            "否", "已核验", "是", "云收费测试", "2026-08-17",
            "预期金额由收费标准参数及线下仪表用量导入模板独立计算，不复制账单实际结果",
        ])
    mapping_book.close()
    usage_book.close()
    if len(rows) != 12:
        raise ValueError(f"应生成12条仪表出账场景，实际生成 {len(rows)} 条")
    return rows


METER_SCENARIO_ROWS = meter_scenario_rows()
METER_CASES = meter_case_rows(METER_SCENARIO_ROWS)


def public_share_scenario_rows() -> list[list[str]]:
    """Build ten room-level August scenarios from formal public-share schemes."""
    donor = list(periodic_scenario_rows()[0])
    rows: list[list[str]] = []
    for case in PUBLIC_SHARE_BILL_CASES:
        row = list(donor)
        row[0] = f"YSF-SCENE-PUBLIC-SHARE-PERIODIC-CALC-{case.room}"
        row[1] = f"PUBLIC-SHARE-{case.scheme_key}-{case.room}-2026-08"
        row[5] = f"A栋/1层/{case.room}"
        row[10] = "公摊周期性收费项"
        row[11] = "UI公摊周期性收费标准"
        row[15] = "PUBLIC_SHARE_ALLOCATION"
        row[16] = case.calculation_parameters
        row[17] = "2026-08"
        row[19] = format(case.expected_amount, "f")
        row[21] = format(case.expected_amount, "f")
        row[23] = (
            f"formal scheme {case.scheme_key} must exist; pair={','.join(case.pair)}; "
            "room has no independent fee-item mapping"
        )
        row[29] = (
            f"periodic public-share validation; method={case.method_key}; "
            f"pair={','.join(case.pair)}; expected room allocation={case.expected_amount:f}"
        )
        rows.append(row)
    return rows


PUBLIC_SHARE_SCENARIO_ROWS = public_share_scenario_rows()
SCENARIO_ROWS = (
    periodic_scenario_rows()
    + PUBLIC_SHARE_SCENARIO_ROWS
    + METER_SCENARIO_ROWS
    + TEMPORARY_SCENARIO_ROWS
    + [
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
)


def calculation_case_rows() -> list[list[str]]:
    """为所有已核验的周期类和仪表类场景生成计费出账用例。"""
    rows = [CALCULATION_CASE]
    # Keep the legacy 1001 calculation case aligned with the maintained
    # CALC-specific scenario created by the entrypoint matrix.
    rows[0] = list(rows[0])
    rows[0][10] = "SCENARIO_ID=YSF-SCENE-PERIODIC-CALC-001"
    for scenario in SCENARIO_ROWS:
        scenario_id = str(scenario[0] or "")
        charge_type = str(scenario[9] or "")
        if not scenario_id.startswith("YSF-SCENE-") or charge_type not in {"周期类", "仪表类"}:
            continue
        if scenario_id == "YSF-SCENE-PERIODIC-001":
            continue
        room_path = str(scenario[5] or "")
        room_name = room_path.rsplit("/", 1)[-1]
        kind = "PERIODIC" if charge_type == "周期类" else "METER"
        if scenario_id.startswith("YSF-SCENE-PUBLIC-SHARE-PERIODIC-"):
            kind = "PUBLIC-SHARE-PERIODIC"
        case = list(CALCULATION_CASE)
        case[0] = f"YSF-CALC-{kind.upper()}-{room_name}"
        case[4] = f"{room_name}房间{charge_type}常规计费出账、审核及账单清理"
        case[8] = (
            f"用户已登录并拥有计费出账、账单中心作废和删除权限；{room_path}已绑定"
            f"收费项及收费标准；目标账期不存在重复账单"
        )
        case[9] = (
            "1. 进入智能计费-计费出账，点击常规类出账下的‘开始计算’\n"
            "2. 按房间选择‘${ROOM_PATH}’，等待房间树加载后勾选叶子节点并点击‘确定’\n"
            "3. 开始月份和结束月份均选择‘${CALCULATION_BILLING_MONTH}’，计费方式保持自然月\n"
            "4. 等待收费项树加载后搜索并选择‘${CHARGE_ITEM}’，点击‘已确认计算条件，下一步’\n"
            "5. 应收日期和最晚缴款日期均选择账期当月第‘${CALCULATION_RULE_DAY}’日，点击‘开始计算’\n"
            "6. 等待待处理账单金额完成，断言预期金额为‘${EXPECTED_RECEIVABLE_AMOUNT}’\n"
            "7. 点击‘核对账单’提交审核，再点击‘审核账单’-‘通过’，审核说明填写‘${CALCULATION_AUDIT_COMMENT}’\n"
            "8. 审核通过后进入账单中心，打开高级搜索，按顺序选择收费项、账期，再将“收费对象”设为“收费对象-房间”并选择目标房间；“关联对象”是关联资产的附加条件，按房间清理时留空。按账期+房间+收费项筛选唯一未作废账单，核对金额；账单编号只作报告证据，不作筛选条件\n"
            "9. 勾选目标行，点击“更多/批量作废”并填写“${VOID_REASON}”确认；按相同业务键重新查询并勾选该作废账单，点击“更多/批量删除”确认；相同业务键复查为0"
        )
        case[10] = f"SCENARIO_ID={scenario_id}"
        case[11] = (
            "1. 房间、收费项和账期显示为目标值\n"
            "2. 计费金额与场景独立计算的预期应收金额一致\n"
            "3. 核对、审核通过后账单中心存在唯一对应账单\n"
            "4. 作废删除后账单中心不再显示本次账单"
        )
        case[17] = "DEFAULT / 测试管理员"
        case[18] = "新增"
        case[19] = "是，需确认"
        rows.append(case)
    return rows


CALCULATION_CASES = calculation_case_rows()


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


def ensure_runtime_parameter_sheet(workbook):
    if "运行参数" in workbook.sheetnames:
        ws = workbook["运行参数"]
    elif "测试数据" in workbook.sheetnames:
        ws = workbook["测试数据"]
        ws.title = "运行参数"
    else:
        ws = workbook.create_sheet("运行参数")

    migrating = ws.cell(1, 1).value != RUNTIME_PARAMETER_HEADERS[0]
    legacy_values = {}
    if migrating:
        for row in range(2, ws.max_row + 1):
            parameter_name = ws.cell(row, 4).value
            if parameter_name:
                legacy_values[parameter_name] = ws.cell(row, 5).value
        ws.delete_rows(1, ws.max_row)
        ws.data_validations.dataValidation = []

    header_fill = PatternFill("solid", fgColor="375623")
    for column, header in enumerate(RUNTIME_PARAMETER_HEADERS, 1):
        cell = ws.cell(1, column, header)
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )
    if ws.max_column > len(RUNTIME_PARAMETER_HEADERS):
        ws.delete_cols(
            len(RUNTIME_PARAMETER_HEADERS) + 1,
            ws.max_column - len(RUNTIME_PARAMETER_HEADERS),
        )

    existing_parameters = {
        ws.cell(row, 4).value: row
        for row in range(2, ws.max_row + 1)
        if ws.cell(row, 4).value
    }
    for row in range(ws.max_row, 1, -1):
        if ws.cell(row, 4).value in OBSOLETE_RUNTIME_PARAMETERS:
            ws.delete_rows(row, 1)
    existing_parameters = {
        ws.cell(row, 4).value: row
        for row in range(2, ws.max_row + 1)
        if ws.cell(row, 4).value
    }
    for item in RUNTIME_PARAMETER_ROWS:
        parameter_name = item[3]
        if parameter_name in existing_parameters:
            continue
        row = first_empty_row(ws)
        values = list(item)
        if parameter_name in legacy_values:
            values[4] = legacy_values[parameter_name]
        for column, value in enumerate(values, 1):
            ws.cell(row, column, value)

    safety_fill = PatternFill("solid", fgColor="FCE4D6")
    selection_fill = PatternFill("solid", fgColor="DDEBF7")
    for row in range(2, ws.max_row + 1):
        parameter_type = ws.cell(row, 6).value
        fill = safety_fill if parameter_type == "安全开关" else None
        if parameter_type in {"运行选择", "场景引用", "账号选择"}:
            fill = selection_fill
        for column in range(1, len(RUNTIME_PARAMETER_HEADERS) + 1):
            cell = ws.cell(row, column)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if fill:
                cell.fill = fill
        ws.row_dimensions[row].height = 42

    widths = [15, 13, 14, 28, 25, 18, 34, 16, 16, 48]
    for column, width in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(1, column).column_letter].width = width
    ws.row_dimensions[1].height = 36
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:J{max(ws.max_row, 2)}"
    ws.sheet_properties.tabColor = "70AD47"

    if migrating:
        validations = [
            ("B2:B1000", '"standard1,standard2,uat,prod"'),
            ("H2:H1000", '"是,否"'),
            ("I2:I1000", '"有效,待补充,已停用"'),
        ]
        for cell_range, options in validations:
            validation = DataValidation(
                type="list", formula1=options, allow_blank=True
            )
            ws.add_data_validation(validation)
            validation.add(cell_range)
    return ws


def ensure_charge_scenario_sheet(workbook):
    sheet_name = "收费场景配置"
    created = sheet_name not in workbook.sheetnames
    ws = workbook.create_sheet(sheet_name) if created else workbook[sheet_name]

    header_font = Font(color="FFFFFF", bold=True)
    group_fills = {
        range(1, 5): PatternFill("solid", fgColor="1F4E78"),
        range(5, 16): PatternFill("solid", fgColor="0F6B78"),
        range(16, 24): PatternFill("solid", fgColor="C55A11"),
        range(24, 31): PatternFill("solid", fgColor="548235"),
    }
    for column, (header, help_text) in enumerate(SCENARIO_HEADERS, 1):
        cell = ws.cell(1, column, header)
        cell.fill = next(
            fill for columns, fill in group_fills.items() if column in columns
        )
        cell.font = header_font
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )
        cell.comment = Comment(help_text, "Codex")

    existing_rows = {
        ws.cell(row, 1).value: row
        for row in range(2, ws.max_row + 1)
        if ws.cell(row, 1).value
    }
    for item in SCENARIO_ROWS:
        row = existing_rows.get(item[0]) or first_empty_row(ws)
        for column, value in enumerate(item, 1):
            cell = ws.cell(row, column, value)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        ws.row_dimensions[row].height = 72

    # 只迁移 Demo 中由脚本生成的旧占位值；用户后续填写的收费标准、
    # 金额和备注必须保留，不能因再次生成工作簿而被覆盖。
    demo_defaults = SCENARIO_ROWS[0]
    for row in range(2, ws.max_row + 1):
        if ws.cell(row, 1).value != "YSF-SCENE-PERIODIC-001":
            continue
        if ws.cell(row, 12).value in {None, "", "待补充实际收费标准"}:
            ws.cell(row, 12, demo_defaults[11])
        if ws.cell(row, 26).value in {None, "", "待补充"}:
            ws.cell(row, 26, demo_defaults[25])
        if ws.cell(row, 27).value in {None, "", "否"}:
            ws.cell(row, 27, demo_defaults[26])
        old_note = str(ws.cell(row, 30).value or "")
        if not old_note or old_note.startswith("补充收费标准"):
            ws.cell(row, 30, demo_defaults[29])
        break

    template_fill = PatternFill("solid", fgColor="E7E6E6")
    pending_fill = PatternFill("solid", fgColor="FFF2CC")
    for row in range(2, ws.max_row + 1):
        status = ws.cell(row, 26).value
        fill = template_fill if status == "模板" else None
        if status == "待补充":
            fill = pending_fill
        for column in range(1, len(SCENARIO_HEADERS) + 1):
            cell = ws.cell(row, column)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if fill:
                cell.fill = fill
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
    ws.freeze_panes = "G2"
    ws.auto_filter.ref = f"A1:AD{max(ws.max_row, 2)}"
    ws.column_dimensions["G"].hidden = True
    ws.column_dimensions["M"].hidden = True
    ws.sheet_properties.tabColor = "5B9BD5"

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
    cases.cell(1, 11, "场景引用/覆盖项")
    case_rows = []
    # CASE is the retired pre-matrix Demo.  Do not reinsert it when rebuilding
    # the workbook; the formal 1001 Bill Center case is maintained as
    # YSF-BILL-PERIODIC-001 by the entrypoint matrix scripts.
    for case in [*CALCULATION_CASES, WORKBENCH_CASE, *METER_CASES, *TEMPORARY_CASES]:
        case_row = find_or_empty_row(cases, case[0])
        copy_row_style(cases, max(2, case_row - 1), case_row, 20)
        for column, value in enumerate(case, 1):
            cases.cell(case_row, column, value)
        cases.row_dimensions[case_row].height = 210
        case_rows.append(case_row)
    cases.auto_filter.ref = f"A1:T{cases.max_row}"

    runtime_parameters = ensure_runtime_parameter_sheet(workbook)

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

    preferred_order = [
        "用例清单", "收费场景配置", "运行参数", "账号角色",
        "填写指南", "字段说明", "下拉选项",
    ]
    order = {name: index for index, name in enumerate(preferred_order)}
    workbook._sheets.sort(
        key=lambda sheet: order.get(sheet.title, len(preferred_order))
    )
    if "下拉选项" in workbook.sheetnames:
        workbook["下拉选项"].sheet_state = "hidden"

    workbook.save(OUTPUT)
    print(f"source={source}")
    print(f"created={OUTPUT}")
    print(f"case_rows={case_rows}")
    print(f"runtime_parameter_rows={runtime_parameters.max_row - 1}")
    print(f"account_rows={len(ACCOUNT_ROWS)}")
    print(f"scenario_rows={scenarios.max_row - 1}")


if __name__ == "__main__":
    main()
