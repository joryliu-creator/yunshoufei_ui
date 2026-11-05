"""Apply the confirmed execution-day payment deadline to the workbook."""
from pathlib import Path
from shutil import copy2
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.tools' / 'python'))
from openpyxl import load_workbook

root = Path(__file__).resolve().parents[1]
target = root / 'UI自动化回归测试用例模板_Demo.xlsx'
book = load_workbook(target)
sheet = book['运行参数']
changed = 0
for row in sheet.iter_rows():
    for cell in row:
        if cell.value == 'LATEST_PAYMENT_DATE':
            value_cell = sheet.cell(cell.row, cell.column + 1)
            if value_cell.value != '执行当天':
                value_cell.value = '执行当天'
                changed += 1
if changed:
    backup = root / 'artifacts' / 'runtime-before-server-fix.xlsx'
    if not backup.exists():
        copy2(target, backup)
    book.save(target)
print(f'payment_deadline_rows_updated={changed}')
