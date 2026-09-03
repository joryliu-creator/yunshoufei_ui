"""Complete the applicable entry-point matrix in the regression workbook."""
from __future__ import annotations

from copy import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))
from openpyxl import load_workbook  # noqa: E402

WORKBOOK = ROOT / "UI自动化回归测试用例模板_Demo.xlsx"


def copy_style(ws, source: int, target: int, columns: int) -> None:
    ws.row_dimensions[target].height = ws.row_dimensions[source].height
    for col in range(1, columns + 1):
        ws.cell(target, col)._style = copy(ws.cell(source, col)._style)
        ws.cell(target, col).number_format = ws.cell(source, col).number_format
        ws.cell(target, col).alignment = copy(ws.cell(source, col).alignment)


def row_for(ws, key: str) -> int:
    for row in range(2, ws.max_row + 1):
        if ws.cell(row, 1).value == key:
            return row
    for row in range(2, ws.max_row + 1):
        if ws.cell(row, 1).value in (None, ""):
            return row
    return ws.max_row + 1


def main() -> None:
    wb = load_workbook(WORKBOOK)
    scenarios = wb["收费场景配置"]
    cases = wb["用例清单"]
    scenario_rows = {
        str(scenarios.cell(r, 1).value): r
        for r in range(2, scenarios.max_row + 1)
        if scenarios.cell(r, 1).value
    }
    case_ids = {
        str(cases.cell(r, 1).value): r
        for r in range(2, cases.max_row + 1)
        if cases.cell(r, 1).value
    }
    donor_scenario = max(2, max(scenario_rows.values()))
    donor_case = max(2, max(case_ids.values()))
    created_scenarios = 0
    created_cases = 0

    # Existing periodic scenarios are CALC-specific. Add BILL-specific cases
    # for every periodic room, including the existing 1001 demo as an explicit
    # entry-point ID.
    for base_id, base_row in list(scenario_rows.items()):
        if not base_id.startswith("YSF-SCENE-PERIODIC-CALC-"):
            continue
        room = base_id.rsplit("-", 1)[-1]
        bill_scenario_id = f"YSF-SCENE-PERIODIC-BILL-{room}"
        target = scenario_rows.get(bill_scenario_id)
        if target is None:
            target = scenarios.max_row + 1
            copy_style(scenarios, base_row, target, 30)
            scenario_rows[bill_scenario_id] = target
            created_scenarios += 1
        for col in range(3, 31):
            scenarios.cell(target, col, scenarios.cell(base_row, col).value)
        scenarios.cell(target, 1, bill_scenario_id)
        scenarios.cell(target, 2, f"{scenarios.cell(base_row, 2).value}-账单中心")
        scenario = [scenarios.cell(target, col).value for col in range(1, 31)]
        expected = str(scenario[21] or scenario[19] or "")
        standard = str(scenario[11] or "")
        item = str(scenario[10] or "")
        room_path = str(scenario[5] or "")
        case_id = f"YSF-BILL-PERIODIC-{room}"
        cr = case_ids.get(case_id)
        if cr is None:
            cr = cases.max_row + 1
            copy_style(cases, donor_case, cr, 20)
            case_ids[case_id] = cr
            created_cases += 1
        steps = (
            "1. 进入智能计费-账单中心，选择项目‘云收费UI自动化’\n"
            "2. 点击‘创建账单’，选择房间‘{room_path}’并确认\n"
            "3. 选择应收日期、账期‘${{BILLING_MONTH}}’、收费类型‘周期类’\n"
            "4. 选择收费项‘{item}’及收费标准‘{standard}’，核对计费期间后确认\n"
            "5. 在账单通知提示中选择‘不需要’\n"
            "6. 按账期和房间筛选唯一账单，断言应收金额为‘{expected}’\n"
            "7. 点击更多/批量作废，填写‘自动化测试账单清理’并确认作废\n"
            "8. 点击更多/批量删除并确认，校验列表无本次账单"
        ).format(room_path=room_path, item=item, standard=standard, expected=expected)
        case = [
            case_id, "云收费", "智能计费/账单中心", "创建并清理周期类账单",
            f"{room}房间周期类账单中心出账、金额断言及清理", "P0", "正向", "是",
            f"已登录；{room_path}已绑定周期类收费项及收费标准；目标账期无重复账单",
            steps, f"SCENARIO_ID={bill_scenario_id}",
            f"账单金额为 {expected}；作废删除后账单中心无本次账单",
            "DEFAULT / 测试管理员", "新增后清理", "作废、删除", "已实现",
            "账期、房间和收费标准来自场景配置", "regression,billing,periodic", "有效", "入口独立场景",
        ]
        for col, value in enumerate(case, 1):
            cases.cell(cr, col, value)
        cases.row_dimensions[cr].height = 210

    # Existing temporary scenarios are LEDGER-specific. Add CALC-specific
    # cases for the calculation page's temporary-entry workflow.
    for base_id, base_row in list(scenario_rows.items()):
        if not base_id.startswith("YSF-SCENE-TEMP-LEDGER-"):
            continue
        room = base_id.rsplit("-", 1)[-1]
        calc_scenario_id = f"YSF-SCENE-TEMP-CALC-{room}"
        target = scenario_rows.get(calc_scenario_id)
        if target is None:
            target = scenarios.max_row + 1
            copy_style(scenarios, base_row, target, 30)
            scenario_rows[calc_scenario_id] = target
            created_scenarios += 1
        for col in range(3, 31):
            scenarios.cell(target, col, scenarios.cell(base_row, col).value)
        scenarios.cell(target, 1, calc_scenario_id)
        scenarios.cell(target, 2, f"{scenarios.cell(base_row, 2).value}-计费出账临时类")
        scenario = [scenarios.cell(target, col).value for col in range(1, 31)]
        expected = str(scenario[21] or scenario[19] or "")
        standard = str(scenario[11] or "")
        item = str(scenario[10] or "")
        room_path = str(scenario[5] or "")
        case_id = f"YSF-CALC-TEMP-{room}"
        cr = case_ids.get(case_id)
        if cr is None:
            cr = cases.max_row + 1
            copy_style(cases, donor_case, cr, 20)
            case_ids[case_id] = cr
            created_cases += 1
        steps = (
            "1. 进入智能计费-计费出账，点击临时类出账下‘开始计算’\n"
            "2. 按房间选择‘{room_path}’，等待房间树加载后确认\n"
            "3. 选择当前月、当天应收日期和最晚缴款日期\n"
            "4. 等待收费项加载，选择‘{item}’及收费标准‘{standard}’\n"
            "5. 按场景参数填写金额/用量/数量，等待计算金额完成\n"
            "6. 点击确认，在线下收款提示中点击取消，断言创建成功\n"
            "7. 进入账单中心按房间筛选，断言金额为‘{expected}’\n"
            "8. 在账单中心作废并删除本次账单，校验列表无本次账单"
        ).format(room_path=room_path, item=item, standard=standard, expected=expected)
        case = [
            case_id, "云收费", "智能计费/计费出账", "临时类入口创建并清理临时账单",
            f"{room}房间临时类计费出账、金额断言及账单清理", "P0", "正向", "是",
            f"已登录；{room_path}已绑定临时类收费项及收费标准；目标账期无重复账单",
            steps, f"SCENARIO_ID={calc_scenario_id}",
            f"临时类账单金额为 {expected}；账单中心作废删除后无本次账单",
            "DEFAULT / 测试管理员", "新增后清理", "作废、删除", "已实现",
            "临时类入口与临时台账入口步骤不同", "regression,billing,temporary", "有效", "入口独立场景",
        ]
        for col, value in enumerate(case, 1):
            cases.cell(cr, col, value)
        cases.row_dimensions[cr].height = 210

    wb.save(WORKBOOK)
    print(f"updated={WORKBOOK}")
    print(f"created_scenarios={created_scenarios} created_cases={created_cases}")


if __name__ == "__main__":
    main()
