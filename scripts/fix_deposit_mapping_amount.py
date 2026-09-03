"""Correct confirmed deposit parameters for rooms 1022 and 1023."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))
from openpyxl import load_workbook  # noqa: E402

WORKBOOK = ROOT / "房间收费标准映射表.xlsx"

wb = load_workbook(WORKBOOK)
ws = wb.active
headers = {ws.cell(1, col).value: col for col in range(1, ws.max_column + 1)}
for row in range(2, ws.max_row + 1):
    room = str(ws.cell(row, headers["房间名称"]).value).strip()
    if room == "1022":
        ws.cell(row, headers["计价参数"], "固定金额=100")
        ws.cell(row, headers["备注"], "按实际收费标准核对：固定金额为100元")
    elif room == "1023":
        ws.cell(row, headers["计价参数"], "单价=10")
        ws.cell(row, headers["备注"], "按实际收费标准核对：单价为10元")
    elif room == "1026":
        ws.cell(row, headers["计价参数"], "单价=100")
        ws.cell(row, headers["备注"], "按实际收费标准核对：收费面积260.00，单价为100元")
wb.save(WORKBOOK)
print(f"updated={WORKBOOK}")
