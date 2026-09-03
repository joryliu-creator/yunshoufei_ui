"""Synchronize the room/entrypoint overview into the mapping workbook."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))

from openpyxl import load_workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402


REGRESSION_WORKBOOK = ROOT / "UI自动化回归测试用例模板_Demo.xlsx"
MAPPING_WORKBOOK = ROOT / "房间收费标准映射表.xlsx"
TARGET_SHEET = "房间场景分类"
SCENARIO_PATTERN = re.compile(
    r"^YSF-SCENE-(PERIODIC|METER|TEMP|DEPOSIT)-(BILL|CALC|LEDGER)-(.+)$"
)
TYPE_LABELS = {
    "PERIODIC": "周期类",
    "METER": "仪表类",
    "TEMP": "临时类",
    "DEPOSIT": "押金类",
}
ENTRYPOINT_LABELS = {
    "BILL": "账单中心",
    "CALC": "计费出账",
    "LEDGER": "临时台账",
}
ENTRYPOINT_ORDER = {"账单中心": 0, "计费出账": 1, "临时台账": 2}
TYPE_ORDER = {"周期类": 0, "仪表类": 1, "临时类": 2, "押金类": 3}


def main() -> None:
    regression = load_workbook(REGRESSION_WORKBOOK, read_only=True, data_only=True)
    try:
        scenarios = regression["收费场景配置"]
        grouped: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        for row in scenarios.iter_rows(min_row=2, values_only=True):
            scenario_id = str(row[0] or "").strip()
            match = SCENARIO_PATTERN.fullmatch(scenario_id)
            if not match:
                continue
            category, entrypoint, _ = match.groups()
            room_path = str(row[5] or "").strip()
            room = room_path.rsplit("/", 1)[-1]
            if not room:
                continue
            grouped[(TYPE_LABELS[category], room)].append(
                (ENTRYPOINT_LABELS[entrypoint], scenario_id)
            )
    finally:
        regression.close()

    workbook = load_workbook(MAPPING_WORKBOOK)
    if TARGET_SHEET in workbook.sheetnames:
        del workbook[TARGET_SHEET]
    sheet = workbook.create_sheet(TARGET_SHEET)
    headers = ["房间号", "收费类型", "涉及入口", "场景数量", "场景编号", "说明"]
    sheet.append(headers)

    def room_number(value: str) -> tuple[int, str]:
        return (int(value), value) if value.isdigit() else (10**9, value)

    for (charge_type, room), entries in sorted(
        grouped.items(), key=lambda item: (TYPE_ORDER[item[0][0]], room_number(item[0][1]))
    ):
        unique_entries = sorted(set(entries), key=lambda item: ENTRYPOINT_ORDER[item[0]])
        sheet.append(
            [
                int(room) if room.isdigit() else room,
                charge_type,
                "、".join(entry for entry, _ in unique_entries),
                len(unique_entries),
                "、".join(scenario_id for _, scenario_id in unique_entries),
                "不同入口分别维护独立场景与清理流程",
            ]
        )

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:F{sheet.max_row}"
    for column, width in enumerate((10, 12, 24, 10, 72, 34), 1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.row_dimensions[1].height = 24
    workbook.save(MAPPING_WORKBOOK)
    print(f"updated={MAPPING_WORKBOOK}")
    print(f"rooms={len(grouped)}")


if __name__ == "__main__":
    main()
