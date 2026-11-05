"""Restore room-import template structure from the downloaded original.

The current workbook may contain curated room data, so this script uses the
original workbook as the structural and formatting base and migrates all
current data rows.
"""

from __future__ import annotations

from copy import copy
from pathlib import Path
from shutil import copy2

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "前置数据模版文件" / "房间导入模版.xlsx"
ORIGINAL = ROOT / "前置数据模版文件" / "房间导入模版-原始模版.xlsx"


def _copy_cell_style(source, target) -> None:
    if source.has_style:
        target._style = copy(source._style)
    if source.number_format:
        target.number_format = source.number_format
    target.font = copy(source.font)
    target.fill = copy(source.fill)
    target.border = copy(source.border)
    target.alignment = copy(source.alignment)
    target.protection = copy(source.protection)


def main() -> None:
    if not CURRENT.exists():
        raise FileNotFoundError(CURRENT)
    if not ORIGINAL.exists():
        raise FileNotFoundError(ORIGINAL)

    current_ws = load_workbook(CURRENT, data_only=False).active

    original_ws = load_workbook(ORIGINAL, data_only=False).active
    if current_ws.max_column != original_ws.max_column:
        raise ValueError(
            f"列数不一致，当前={current_ws.max_column}，原始={original_ws.max_column}"
        )

    current_headers = [
        current_ws.cell(1, column).value
        for column in range(1, current_ws.max_column + 1)
    ]
    original_headers = [
        original_ws.cell(1, column).value
        for column in range(1, original_ws.max_column + 1)
    ]
    if current_headers[:16] != original_headers[:16] or current_headers[17:] != original_headers[17:]:
        raise ValueError("当前模板与原始模板的关键列顺序不一致，已停止迁移")

    rows = [
        [current_ws.cell(row, column).value for column in range(1, current_ws.max_column + 1)]
        for row in range(2, current_ws.max_row + 1)
    ]
    if not rows:
        raise ValueError("当前模板没有可迁移的房间数据")

    # Make the working file an explicit copy of the downloaded original.
    # The original workbook is never opened for writing.
    copy2(ORIGINAL, CURRENT)
    migrated_wb = load_workbook(CURRENT, data_only=False)
    target_ws = migrated_wb[migrated_wb.sheetnames[0]]

    # Use the original example row as the style baseline for all data rows.
    style_row = 2
    for row_index, values in enumerate(rows, start=2):
        if row_index > target_ws.max_row:
            target_ws.row_dimensions[row_index].height = target_ws.row_dimensions[style_row].height
        for column, value in enumerate(values, start=1):
            target = target_ws.cell(row_index, column)
            source = target_ws.cell(style_row, column)
            target.value = value
            _copy_cell_style(source, target)

    # Remove any rows left over from the original base beyond migrated data.
    if target_ws.max_row > len(rows) + 1:
        target_ws.delete_rows(len(rows) + 2, target_ws.max_row - len(rows) - 1)

    migrated_wb.save(CURRENT)
    print(f"已按原始模板恢复结构并迁移 {len(rows)} 条房间数据")
    print(f"房间范围：{rows[0][2]}-{rows[-1][2]}；Sheet：{migrated_wb.sheetnames}")


if __name__ == "__main__":
    main()
