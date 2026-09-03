"""Build offline meter-usage import records from the completed water-meter demo.

The source workbook supplies the authoritative meter numbers.  The offline
template's completed ``水表1032`` records supply the monthly usage/reading
pattern and cell formatting.  Re-running this script is safe: it replaces
only the records generated for the other mapped meters.
"""

from __future__ import annotations

from copy import copy
from datetime import datetime
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))

from openpyxl import load_workbook


METER_IMPORT_WORKBOOK = ROOT / "仪表导入模板.xlsx"
USAGE_WORKBOOK = ROOT / "线下仪表用量导入模板.xlsx"
HEADER_ROW = 3
DATA_START_ROW = 4
DEMO_METER_NO = "水表1032"
REQUIRED_MONTHS = tuple(f"2026-{month:02d}" for month in range(1, 9))


def headers_of(worksheet, header_row: int) -> dict[str, int]:
    return {
        str(cell.value).strip(): column
        for column, cell in enumerate(worksheet[header_row], 1)
        if cell.value is not None
    }


def meter_numbers_from_import_template() -> list[str]:
    workbook = load_workbook(METER_IMPORT_WORKBOOK, read_only=True, data_only=True)
    worksheet = workbook.active
    headers = headers_of(worksheet, HEADER_ROW)
    meter_no_column = headers.get("仪表编号*")
    if not meter_no_column:
        workbook.close()
        raise ValueError("仪表导入模板缺少“仪表编号*”列")

    meter_numbers: list[str] = []
    for row in range(DATA_START_ROW, worksheet.max_row + 1):
        meter_no = str(worksheet.cell(row, meter_no_column).value or "").strip()
        if meter_no:
            meter_numbers.append(meter_no)
    workbook.close()

    if len(meter_numbers) != len(set(meter_numbers)):
        raise ValueError("仪表导入模板存在重复的仪表编号")
    if DEMO_METER_NO not in meter_numbers:
        raise ValueError(f"仪表导入模板未包含示例仪表：{DEMO_METER_NO}")
    return meter_numbers


def copy_row_style(source_row, target_row) -> None:
    for source_cell, target_cell in zip(source_row, target_row):
        if source_cell.has_style:
            target_cell._style = copy(source_cell._style)
        if source_cell.number_format:
            target_cell.number_format = source_cell.number_format
        if source_cell.alignment:
            target_cell.alignment = copy(source_cell.alignment)
        if source_cell.protection:
            target_cell.protection = copy(source_cell.protection)
        if source_cell.fill:
            target_cell.fill = copy(source_cell.fill)
        if source_cell.font:
            target_cell.font = copy(source_cell.font)
        if source_cell.border:
            target_cell.border = copy(source_cell.border)


def main() -> None:
    if not METER_IMPORT_WORKBOOK.exists():
        raise FileNotFoundError(f"未找到仪表导入模板：{METER_IMPORT_WORKBOOK}")
    if not USAGE_WORKBOOK.exists():
        raise FileNotFoundError(f"未找到线下仪表用量导入模板：{USAGE_WORKBOOK}")

    meter_numbers = meter_numbers_from_import_template()
    target_meter_numbers = [number for number in meter_numbers if number != DEMO_METER_NO]

    workbook = load_workbook(USAGE_WORKBOOK)
    worksheet = workbook.active
    headers = headers_of(worksheet, HEADER_ROW)
    required_headers = {"仪表编号*", "本期用量*", "本期抄表日期*", "本期读数*", "抄表所属月份*"}
    missing_headers = required_headers - set(headers)
    if missing_headers:
        workbook.close()
        raise ValueError(f"线下仪表用量导入模板缺少列：{sorted(missing_headers)}")

    meter_no_column = headers["仪表编号*"]
    date_column = headers["本期抄表日期*"]
    month_column = headers["抄表所属月份*"]
    demo_rows = [
        row
        for row in range(DATA_START_ROW, worksheet.max_row + 1)
        if str(worksheet.cell(row, meter_no_column).value or "").strip() == DEMO_METER_NO
    ]
    if len(demo_rows) != len(REQUIRED_MONTHS):
        workbook.close()
        raise ValueError(
            f"示例仪表 {DEMO_METER_NO} 应有 {len(REQUIRED_MONTHS)} 条记录，实际为 {len(demo_rows)} 条"
        )

    demo_months = tuple(str(worksheet.cell(row, month_column).value or "").strip() for row in demo_rows)
    if demo_months != REQUIRED_MONTHS:
        workbook.close()
        raise ValueError(f"示例仪表的抄表所属月份应为 {REQUIRED_MONTHS}，实际为 {demo_months}")

    # The completed demo is the data pattern.  Its July date was entered as
    # 2026-06-04; normalize all demo dates to the month they belong to.
    for row, month in zip(demo_rows, REQUIRED_MONTHS):
        datetime.strptime(month, "%Y-%m")
        worksheet.cell(row, date_column).value = f"{month}-04"

    # Remove records created by an earlier execution without touching records
    # for any other meter that a user may have added independently.
    for row in range(worksheet.max_row, DATA_START_ROW - 1, -1):
        meter_no = str(worksheet.cell(row, meter_no_column).value or "").strip()
        if meter_no in target_meter_numbers:
            worksheet.delete_rows(row, 1)

    demo_rows = [
        row
        for row in range(DATA_START_ROW, worksheet.max_row + 1)
        if str(worksheet.cell(row, meter_no_column).value or "").strip() == DEMO_METER_NO
    ]
    next_row = worksheet.max_row + 1
    for meter_no in target_meter_numbers:
        for demo_row in demo_rows:
            source_cells = list(worksheet[demo_row])
            target_cells = [worksheet.cell(next_row, column) for column in range(1, worksheet.max_column + 1)]
            copy_row_style(source_cells, target_cells)
            for source_cell, target_cell in zip(source_cells, target_cells):
                target_cell.value = source_cell.value
            worksheet.cell(next_row, meter_no_column).value = meter_no
            worksheet.row_dimensions[next_row].height = worksheet.row_dimensions[demo_row].height
            next_row += 1

    workbook.save(USAGE_WORKBOOK)
    workbook.close()

    expected_total = len(meter_numbers) * len(REQUIRED_MONTHS)
    print(f"updated={USAGE_WORKBOOK}")
    print(f"meter_count={len(meter_numbers)}")
    print(f"generated_records={len(target_meter_numbers) * len(REQUIRED_MONTHS)}")
    print(f"total_records={expected_total}")


if __name__ == "__main__":
    main()
