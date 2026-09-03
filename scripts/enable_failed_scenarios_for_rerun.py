"""Keep failed scenarios executable while retaining failure notes on cases."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))
from openpyxl import load_workbook  # noqa: E402


def main() -> None:
    workbook = next(ROOT.glob("UI*.xlsx"))
    wb = load_workbook(workbook)
    ws = wb.worksheets[1]
    changed = 0
    for row in range(2, ws.max_row + 1):
        if str(ws.cell(row, 26).value or "").strip() == "已核验-失败":
            ws.cell(row, 26).value = "已核验"
            changed += 1
    wb.save(workbook)
    print(f"enabled={changed}")


if __name__ == "__main__":
    main()
