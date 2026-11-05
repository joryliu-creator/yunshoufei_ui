from __future__ import annotations

from pathlib import Path
import sys

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.update_room_import_template import formula_mappings  # noqa: E402
from src.config.standard_name import (  # noqa: E402
    AUTOMATION_STANDARD_PREFIX,
    automation_standard_name,
)


WORKBOOK = ROOT / "UI自动化回归测试用例模板_Demo.xlsx"
SHEET = "收费标准专项"
HEADERS = [
    "用例编号", "场景引用", "目标房间", "收费类型", "收费项", "计费公式",
    "自动化收费标准名称", "计算参数", "创建策略", "清理策略", "操作步骤",
    "预期结果", "维护状态",
]


def build_rows() -> list[list[str]]:
    rows: list[list[str]] = []
    for mapping in formula_mappings():
        if mapping.creation_policy != "创建":
            continue
        name = automation_standard_name(mapping.standard_name)
        steps = (
            "读取映射并生成AT-前缀名称；进入收费设置-收费标准管理；"
            "按收费类型/收费项/项目/公式及参数创建；保存后按完整名称精确查询；"
            "仅处理本次运行创建且以AT-开头的记录；若为启用状态先切换为未启用；"
            "再执行删除，删除后再次精确查询确认不存在"
        )
        expected = "创建成功或检测到同名AT记录后幂等跳过；精确查询可定位；清理后查询结果为空"
        rows.append([
            f"YSF-CHARGE-STANDARD-{mapping.room_name}",
            "YSF-CHARGE-STANDARD-LIFECYCLE",
            mapping.room_name,
            mapping.charge_type,
            mapping.charge_item,
            mapping.formula,
            name,
            mapping.calculation_parameters,
            mapping.creation_policy,
            "仅清理本次运行创建的AT-收费标准；开关控制删除",
            steps,
            expected,
            "新增专项回归",
        ])
    return rows


def main() -> None:
    if not WORKBOOK.exists():
        raise FileNotFoundError(WORKBOOK)
    workbook = load_workbook(WORKBOOK)
    if SHEET in workbook.sheetnames:
        del workbook[SHEET]
    sheet = workbook.create_sheet(SHEET)
    sheet.append(HEADERS)
    for row in build_rows():
        sheet.append(row)
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    widths = [28, 34, 12, 14, 24, 40, 42, 30, 12, 34, 80, 45, 16]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + index)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    workbook.save(WORKBOOK)
    print(f"updated {WORKBOOK.name}: sheet={SHEET}, rows={sheet.max_row - 1}")


if __name__ == "__main__":
    main()
