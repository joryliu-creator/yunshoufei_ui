from __future__ import annotations

"""维护周期类公摊方案专项用例；只更新项目本地回归工作簿。"""

import os
import sys
from copy import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))
sys.path.insert(0, str(ROOT))

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from src.config.instrument_public_share_data import INITIAL_CASES, REGRESSION_CASES


WORKBOOK = ROOT / "UI自动化回归测试用例模板_Demo.xlsx"

CASES = [
    {
        "id": "YSF-PUBLIC-SHARE-PERIODIC-RATIO-1201-1202",
        "name": "AT-UI周期类-按房间设置比例分摊-1201-1202",
        "method": "按房间设置比例分摊",
        "area": "",
        "rooms": "1201、1202",
        "parameters": "公摊金额=1000；分摊比例=40/60",
        "expect": "保存成功；列表可按方案名称查到周期性费用、公摊周期性收费项及比例分摊方式",
    },
    {
        "id": "YSF-PUBLIC-SHARE-PERIODIC-AMOUNT-1203-1204",
        "name": "AT-UI周期类-按房间设置金额分摊-1203-1204",
        "method": "按房间设置金额分摊",
        "area": "",
        "rooms": "1203、1204",
        "parameters": "公摊金额=1000；分摊金额=300/700",
        "expect": "保存成功；列表可按方案名称查到周期性费用、公摊周期性收费项及金额分摊方式",
    },
    {
        "id": "YSF-PUBLIC-SHARE-PERIODIC-BUILDING-1205-1206",
        "name": "AT-UI周期类-面积系数公摊-建筑面积-1205-1206",
        "method": "按住户面积及所在楼层对应系数公摊",
        "area": "建筑面积",
        "rooms": "1205、1206",
        "parameters": "标准面积单价=2；低于/等于5系数=3；高于/等于系数=5",
        "expect": "保存成功；列表可按方案名称查到周期性费用、公摊周期性收费项及面积系数方式",
    },
    {
        "id": "YSF-PUBLIC-SHARE-PERIODIC-USABLE-1271-1272",
        "name": "AT-UI周期类-面积系数公摊-使用面积-1271-1272",
        "method": "按住户面积及所在楼层对应系数公摊",
        "area": "使用面积",
        "rooms": "1271、1272",
        "parameters": "标准面积单价=2；低于/等于5系数=3；高于/等于系数=5",
        "expect": "保存成功；列表可按方案名称查到使用面积及面积系数方式",
    },
    {
        "id": "YSF-PUBLIC-SHARE-PERIODIC-CHARGE-1273-1274",
        "name": "AT-UI周期类-面积系数公摊-收费面积-1273-1274",
        "method": "按住户面积及所在楼层对应系数公摊",
        "area": "收费面积",
        "rooms": "1273、1274",
        "parameters": "标准面积单价=2；低于/等于5系数=3；高于/等于系数=5",
        "expect": "保存成功；列表可按方案名称查到收费面积及面积系数方式",
    },
]

for case in (*INITIAL_CASES, *REGRESSION_CASES):
    is_regression = case.name.startswith("AT-")
    CASES.append(
        {
            "id": case.case_id,
            "scheme_name": case.name,
            "name": case.name,
            "scheme_type": f"仪表类公摊-{case.instrument_type}",
            "method": case.method,
            "area": case.billing_area or "",
            "charge_type": case.charge_type,
            "charge_item": case.charge_item,
            "charge_standard": case.charge_standard,
            "meter": case.instrument_name,
            "month_rule": case.incomplete_month_rule,
            "instrument_type": case.instrument_type,
            "instrument_name": case.instrument_name,
            "area_total": case.expected_area_total or "",
            "floor_tiers": repr(case.floor_tiers) if case.floor_tiers else "",
            "rooms": "、".join(case.rooms),
            "parameters": (
                f"仪表={case.instrument_name}；仪表类型={case.instrument_type}；"
                f"不足月规则={case.incomplete_month_rule}；"
                f"计费面积={case.billing_area or '不适用'}；"
                f"公摊系数阶梯={case.floor_tiers or '不适用'}"
            ),
            "expect": (
                "保存后按方案名称精确查询；核对仪表类型、收费项/标准、公摊方式、"
                "不足月规则及自动带出的两间关联房间。"
            ),
            "cleanup": (
                "本次 AT- 创建后由独立清理用例按精确名称删除；" 
                "仅删除燃气/空调 AT 方案，不生成账单。"
                if is_regression
                else "水表/电表正式初始化方案不带 AT 前缀，成功后长期保留，不清理。"
            ),
            "steps": (
                "1. 登录 standard1，进入云收费→收费设置→公摊方案；\n"
                "2. 点击新增方案，填写方案名称；\n"
                f"3. 选择收费项类型={case.charge_type}、仪表类型={case.instrument_type}；\n"
                f"4. 选择公摊仪表={case.instrument_name}；\n"
                f"5. 选择收费项={case.charge_item}、收费标准={case.charge_standard}；\n"
                f"6. 选择公摊方式={case.method}；"
                f"计费面积={case.billing_area or '不适用'}；不足月规则={case.incomplete_month_rule}；\n"
                "7. 核对系统自动带出的两间关联房间及动态参数，点击保存；\n"
                "8. 按方案名称精确查询并核对保存结果。"
            ),
        }
    )


HEADERS = [
    "用例编号",
    "方案名称",
    "场景引用",
    "环境",
    "客户号",
    "项目名称",
    "公摊类型",
    "公摊方式",
    "计费面积",
    "关联收费项类型",
    "关联收费项",
    "关联收费标准",
    "公摊房间",
    "仪表类型",
    "公摊仪表",
    "不足月规则",
    "预期公摊户数/面积",
    "系数阶梯参数",
    "创建参数",
    "危险操作开关",
    "操作步骤",
    "预期结果",
    "清理策略",
    "维护状态",
]


def _style_header(ws) -> None:
    fill = PatternFill("solid", fgColor="1F4E78")
    for cell in ws[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    widths = [34, 52, 42, 12, 12, 22, 18, 34, 14, 18, 24, 28, 18, 16, 40, 18, 22, 44, 34, 100, 70, 42, 14, 14]
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(1, index).column_letter].width = width


def _copy_row_style(ws, source_row: int, target_row: int) -> None:
    ws.row_dimensions[target_row].height = ws.row_dimensions[source_row].height
    for column in range(1, ws.max_column + 1):
        source = ws.cell(source_row, column)
        target = ws.cell(target_row, column)
        if source.has_style:
            target._style = copy(source._style)
        target.number_format = source.number_format
        target.alignment = copy(source.alignment)


def update() -> None:
    workbook = load_workbook(WORKBOOK)
    title = "公摊方案专项"
    if title in workbook.sheetnames:
        worksheet = workbook[title]
        worksheet.delete_rows(1, worksheet.max_row)
    else:
        worksheet = workbook.create_sheet(title)
    worksheet.append(HEADERS)
    maintenance_state = os.getenv("PUBLIC_SHARE_SCHEME_STATUS", "待实际核验")
    for case in CASES:
        steps = case.get("steps") or (
            "1. 登录 standard1，进入云收费→收费设置→公摊方案；\n"
            "2. 点击新增方案，填写方案名称；\n"
            "3. 选择收费项类型=周期性费用、收费项=公摊周期性收费项、"
            "收费标准=UI公摊周期性收费标准；\n"
            f"4. 选择公摊方式={case['method']}；"
            f"计费面积={case['area'] or '不适用'}；\n"
            f"5. 在房间树 A栋→1层 勾选 {case['rooms']}，点击组件内确定；\n"
            f"6. 填写 {case['parameters']}；\n"
            "7. 点击保存，按方案名称搜索并核对列表字段。"
        )
        worksheet.append(
            [
                case["id"],
                case.get("scheme_name", case.get("name", "")),
                f"SCENARIO_ID={case['id']}",
                "standard1",
                "93537",
                "云收费UI自动化",
                case.get("scheme_type", "周期性公摊"),
                case["method"],
                case["area"],
                case.get("charge_type", "周期性费用"),
                case.get("charge_item", "公摊周期性收费项"),
                case.get("charge_standard", "UI公摊周期性收费标准"),
                case["rooms"],
                case.get("instrument_type", ""),
                case.get("meter", ""),
                case.get("month_rule", ""),
                case.get("area_total", ""),
                case.get("floor_tiers", ""),
                case["parameters"],
                "ALLOW_PUBLIC_SHARE_SCHEME_CREATION=true；默认关闭",
                steps,
                case["expect"],
                case.get(
                    "cleanup",
                    "仅由独立清理用例删除本次创建的 AT- 方案；非 AT 初始化方案不删除",
                ),
                maintenance_state,
            ]
        )
    _style_header(worksheet)
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    workbook.save(WORKBOOK)
    print(f"updated {title}: {len(CASES)} cases")


if __name__ == "__main__":
    update()
