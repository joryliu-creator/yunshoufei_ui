"""Update the active standard1 billing month in the regression workbook."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))
from openpyxl import load_workbook  # noqa: E402


def main() -> None:
    workbook = next(ROOT.glob("UI*.xlsx"))
    wb = load_workbook(workbook)
    ws = wb["运行参数"]
    updated = False
    for row in range(2, ws.max_row + 1):
        if ws.cell(row, 4).value == "BILLING_MONTH":
            ws.cell(row, 5).value = "2026-08"
            updated = True
        if ws.cell(row, 4).value == "CALCULATION_BILLING_MONTH":
            ws.cell(row, 5).value = "2026-08"
        if ws.cell(row, 4).value in {"RECEIVABLE_DATE", "LATEST_PAYMENT_DATE"}:
            ws.cell(row, 5).value = "2026-08-01"
    if not updated:
        raise RuntimeError("运行参数中未找到 BILLING_MONTH")
    wb.save(workbook)
    print(f"updated={workbook}")


if __name__ == "__main__":
    main()
