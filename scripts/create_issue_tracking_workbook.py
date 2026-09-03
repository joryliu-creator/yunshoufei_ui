from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo


OUTPUT = Path(__file__).resolve().parents[1] / "云收费UI自动化发现问题以及修改情况.xlsx"


def build_workbook() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "问题记录"

    headers = ["序号", "模块/场景", "问题描述", "确认结论", "当前状态"]
    rows = [
        [
            1,
            "计费出账｜水表仪表类",
            "仪表多阶梯多单价（阶梯单价×用量；月清用量）计算时会乘以收费面积",
            "确实是问题",
            "已修复",
        ],
        [
            2,
            "计费出账、账单中心｜电表仪表类",
            "仪表累计用量计费（累计用量对应单价×用量）计算异常",
            "确认是问题",
            "待修复",
        ],
        [
            3,
            "2.1 版本账单中心｜仪表类出账",
            "仪表类账单出账失败",
            "确认是问题",
            "待修复",
        ],
    ]

    sheet.merge_cells("A1:E1")
    sheet["A1"] = "云收费UI自动化发现问题以及修改情况"
    sheet["A1"].font = Font(name="Microsoft YaHei", size=16, bold=True, color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid", fgColor="1F4E78")
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 30

    sheet.merge_cells("A2:E2")
    sheet["A2"] = "用于记录云收费 UI 自动化回归中发现的问题、确认结论及修复进度"
    sheet["A2"].font = Font(name="Microsoft YaHei", size=10, italic=True, color="666666")
    sheet["A2"].alignment = Alignment(horizontal="left", vertical="center")

    for column, value in enumerate(headers, 1):
        cell = sheet.cell(row=4, column=column, value=value)
        cell.font = Font(name="Microsoft YaHei", bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="5B9BD5")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row_index, data_row in enumerate(rows, 5):
        for column_index, cell_value in enumerate(data_row, 1):
            cell = sheet.cell(row=row_index, column=column_index, value=cell_value)
            cell.font = Font(name="Microsoft YaHei", size=10)
            cell.alignment = Alignment(
                horizontal="center" if column_index in {1, 2, 4, 5} else "left",
                vertical="center",
                wrap_text=True,
            )
        sheet.row_dimensions[row_index].height = 42
        status = sheet.cell(row=row_index, column=5)
        if status.value == "已修复":
            status.fill = PatternFill("solid", fgColor="E2F0D9")
            status.font = Font(name="Microsoft YaHei", bold=True, color="548235")
        else:
            status.fill = PatternFill("solid", fgColor="FFF2CC")
            status.font = Font(name="Microsoft YaHei", bold=True, color="BF9000")

    thin_gray = Side(style="thin", color="D9E2F3")
    for row in sheet.iter_rows(min_row=4, max_row=7, min_col=1, max_col=5):
        for cell in row:
            cell.border = Border(left=thin_gray, right=thin_gray, top=thin_gray, bottom=thin_gray)

    widths = {1: 8, 2: 30, 3: 68, 4: 16, 5: 16}
    for column, width in widths.items():
        sheet.column_dimensions[get_column_letter(column)].width = width

    table = Table(displayName="IssueTracking", ref="A4:E7")
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showFirstColumn=False, showLastColumn=False,
        showRowStripes=True, showColumnStripes=False,
    )
    sheet.add_table(table)
    sheet.freeze_panes = "A5"
    sheet.auto_filter.ref = "A4:E7"
    sheet.sheet_view.showGridLines = False
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    workbook.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    build_workbook()
