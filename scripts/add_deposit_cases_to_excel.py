"""Add the confirmed deposit billing cases to the regression workbook.

The operation is idempotent: rerunning it updates the same case/scenario IDs
and never creates duplicate rows.
"""
from __future__ import annotations

from copy import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))
from openpyxl import load_workbook  # noqa: E402

WORKBOOK = ROOT / "UI自动化回归测试用例模板_Demo.xlsx"

CASES = [
    ("1021", "押金类-人工输入收费金额", "无", "2000.00", "人工金额=2000"),
    ("1022", "押金类-固定金额", "无", "100.00", "固定金额=100"),
    ("1023", "押金类-数量公式（数量*单价）", "数量=10；单价=10", "100.00", "数量=10；单价=10"),
    ("1024", "押金类-面积公式（计费面积*单价）建筑", "建筑面积=300.12；单价=10", "3001.20", "计费面积=建筑面积；单价=10"),
    ("1025", "押金类-面积公式（计费面积*单价）使用", "使用面积=280.01；单价=10", "2800.10", "计费面积=使用面积；单价=10"),
    ("1026", "押金类-面积公式（计费面积*单价）收费", "收费面积=260.00；单价=100", "26000.00", "计费面积=收费面积；单价=100"),
]


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
    cases = wb["用例清单"]
    scenarios = wb["收费场景配置"]
    # Use the last populated row as a style donor; the workbook contains
    # intentionally formatted blank rows after the existing cases.
    case_donor = max(2, max(r for r in range(2, cases.max_row + 1) if cases.cell(r, 1).value))
    scenario_donor = max(2, max(r for r in range(2, scenarios.max_row + 1) if scenarios.cell(r, 1).value))

    # Remove the earlier shared-scenario rows; each entry point is now its own
    # independently executable regression scenario.
    legacy_ids = {f"YSF-SCENE-DEPOSIT-{room}" for room, *_ in CASES}
    for row in range(scenarios.max_row, 1, -1):
        if scenarios.cell(row, 1).value in legacy_ids:
            scenarios.delete_rows(row, 1)

    for room, standard, params, expected, parameter_note in CASES:
        room_path = f"A栋/1层/{room}"
        for workflow, module, cleanup in (
            ("LEDGER", "智能计费/临时台账", "临时台账高级搜索按房间筛选，作废并删除本次账单"),
            ("CALC", "智能计费/计费出账", "进入账单中心按房间筛选，作废并删除本次账单"),
        ):
            scenario_id = f"YSF-SCENE-DEPOSIT-{workflow}-{room}"
            sr = row_for(scenarios, scenario_id)
            copy_style(scenarios, scenario_donor, sr, 30)
            scenario_name = f"押金类-{workflow}-{room}-{standard}"
            scenario = [
                scenario_id, scenario_name, "standard1", "93537",
                "云收费UI自动化", room_path, "", "", "", "押金类", "押金类收费项",
                standard, "", "2023-01-01", "2028-12-31", standard.split("-", 1)[-1],
                params, "执行当月", "无减免", expected, "0.00", expected,
                "四舍五入保留2位", "客户、房间、收费项和收费标准已配置；目标账期无重复押金账单",
                "否", "已核验", "是", "云收费测试", "", parameter_note,
            ]
            for col, value in enumerate(scenario, 1):
                scenarios.cell(sr, col, value)
            scenarios.row_dimensions[sr].height = 90

            case_id = f"YSF-DEPOSIT-{workflow}-{room}"
            cr = row_for(cases, case_id)
            copy_style(cases, case_donor, cr, 20)
            if workflow == "LEDGER":
                steps = (
                    "1. 进入智能计费-临时台账，点击‘发起临时缴费’\n"
                    "2. 收费对象选择房间，选择‘A栋/1层/{room}’并点击确认\n"
                    "3. 选择当前账期、当天应收日期和最晚缴款日期\n"
                    "4. 选择收费项‘押金类收费项’及收费标准‘{standard}’\n"
                    "5. 按参数填写金额/数量（面积类使用房间已配置面积），提交并取消线下收款提示\n"
                    "6. 校验账单金额为‘{expected}’\n"
                    "7. 高级搜索按房间定位本次账单，点击作废，填写‘自动化测试押金账单清理’并确认\n"
                    "8. 点击删除并确认，校验列表不再显示本次账单"
                ).format(room=room, standard=standard, expected=expected)
            else:
                steps = (
                    "1. 进入智能计费-计费出账，点击临时类出账下‘开始计算’\n"
                    "2. 选择房间‘{room}’，选择当前月、当天应收日期和最晚缴款日期\n"
                    "3. 选择收费项‘押金类收费项’及收费标准‘{standard}’\n"
                    "4. 按参数填写金额/数量（面积类使用房间已配置面积），提交并取消线下收款提示\n"
                    "5. 在账单中心按房间定位生成账单，校验金额为‘{expected}’\n"
                    "6. 作废并删除本次账单，校验账单中心不再显示"
                ).format(room=room_path, standard=standard, expected=expected)
            case = [
                case_id, "云收费", module, "押金类账单生成与清理",
                f"{room}房间押金类账单生成、金额断言及清理", "P0", "正向", "是",
                f"已登录并拥有对应权限；{room_path}已绑定押金类收费项及收费标准；目标账期无重复账单",
                steps, f"SCENARIO_ID={scenario_id}",
                f"账单创建成功且金额为 {expected}；{cleanup} 后列表无本次账单",
                "DEFAULT / 测试管理员", "新增后清理", "作废、删除", "已实现",
                parameter_note, "regression,billing,deposit,cleanup", "有效", "押金账单不执行缴费或退款",
            ]
            for col, value in enumerate(case, 1):
                cases.cell(cr, col, value)
            cases.row_dimensions[cr].height = 210

    wb.save(WORKBOOK)
    print(f"updated={WORKBOOK}")
    print(f"deposit_scenarios={len(CASES) * 2} deposit_cases={len(CASES) * 2}")


if __name__ == "__main__":
    main()
