from __future__ import annotations

from copy import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))

from openpyxl import load_workbook
from openpyxl.worksheet.table import Table


ROOMS = [
    ("1101", "按折扣", "普通账单减免，参数待确认"),
    ("1102", "按固定金额", "普通账单减免，参数待确认"),
    ("1103", "自定义金额", "普通账单减免，参数待确认"),
    ("1104", "违约金全免", "需先通过定时任务产生违约金"),
    ("1105", "违约金折扣", "需先通过定时任务产生违约金，折扣参数待确认"),
    ("1106", "抹零减免", "抹零规则及触发条件待确认"),
]


def locate_workbooks() -> tuple[Path, Path, Path]:
    root_candidates = [
        p for p in ROOT.glob("*.xlsx")
        if not p.name.startswith("~$")
        and load_workbook(p, read_only=True).worksheets[0].max_column == 11
    ]
    room_candidates = [
        p for p in ROOT.glob("*/*.xlsx")
        if not p.name.startswith("~$")
        and load_workbook(p, read_only=True).worksheets[0].max_column == 19
    ]
    charge_item_candidates = [
        p for p in ROOT.glob("*/*.xlsx")
        if not p.name.startswith("~$")
        and load_workbook(p, read_only=True).worksheets[0].max_column == 6
    ]
    if len(root_candidates) != 1 or len(room_candidates) != 1 or len(charge_item_candidates) != 1:
        raise RuntimeError("无法唯一定位映射表、房间导入模板或收费项导入模板")
    return root_candidates[0], room_candidates[0], charge_item_candidates[0]


def copy_row_style(ws, source_row: int, target_row: int) -> None:
    ws.row_dimensions[target_row].height = ws.row_dimensions[source_row].height
    for col in range(1, ws.max_column + 1):
        source = ws.cell(source_row, col)
        target = ws.cell(target_row, col)
        if source.has_style:
            target._style = copy(source._style)
        if source.number_format:
            target.number_format = source.number_format
        if source.alignment:
            target.alignment = copy(source.alignment)
        if source.protection:
            target.protection = copy(source.protection)


def update_table_ref(ws, new_end_row: int) -> None:
    for table in ws.tables.values():
        start = table.ref.split(":")[0]
        table.ref = f"{start}:{ws.cell(new_end_row, ws.max_column).coordinate}"


def main() -> None:
    mapping_path, room_path, charge_item_path = locate_workbooks()

    mapping_wb = load_workbook(mapping_path)
    mapping_ws = mapping_wb.active
    existing_rooms = {str(mapping_ws.cell(r, 2).value).strip() for r in range(2, mapping_ws.max_row + 1)}
    next_row = mapping_ws.max_row + 1
    next_serial = max(
        [int(mapping_ws.cell(r, 1).value) for r in range(2, mapping_ws.max_row + 1) if str(mapping_ws.cell(r, 1).value).isdigit()],
        default=0,
    ) + 1
    for room, scheme, note in ROOMS:
        if room in existing_rooms:
            continue
        values = [
            next_serial,
            room,
            "周期类",
            "UI周期性收费项",
            "自定义金额",
            None,
            None,
            "周期类-自定义金额",
            None,
            "使用已有/待确认",
            f"减免方案：{scheme}；{note}",
        ]
        copy_row_style(mapping_ws, mapping_ws.max_row, next_row)
        for col, value in enumerate(values, 1):
            mapping_ws.cell(next_row, col).value = value
        next_row += 1
        next_serial += 1
    update_table_ref(mapping_ws, next_row - 1)
    mapping_wb.save(mapping_path)

    room_wb = load_workbook(room_path)
    room_ws = room_wb.active
    existing_room_numbers = {str(room_ws.cell(r, 3).value).strip() for r in range(2, room_ws.max_row + 1)}
    room_next_row = room_ws.max_row + 1
    for room, _, _ in ROOMS:
        if room in existing_room_numbers:
            continue
        source_row = room_ws.max_row
        copy_row_style(room_ws, source_row, room_next_row)
        for col in range(1, room_ws.max_column + 1):
            room_ws.cell(room_next_row, col).value = room_ws.cell(source_row, col).value
        room_ws.cell(room_next_row, 3).value = room
        room_next_row += 1
    update_table_ref(room_ws, room_next_row - 1)
    room_wb.save(room_path)

    charge_wb = load_workbook(charge_item_path)
    charge_ws = charge_wb.active
    existing_charge_rooms = {
        str(charge_ws.cell(r, 1).value).strip()
        for r in range(2, charge_ws.max_row + 1)
        if charge_ws.cell(r, 1).value
    }
    charge_next_row = charge_ws.max_row + 1
    for room, _, _ in ROOMS:
        room_path_value = f"A栋/1层/{room}"
        if room_path_value in existing_charge_rooms:
            continue
        source_row = charge_ws.max_row
        copy_row_style(charge_ws, source_row, charge_next_row)
        for col in range(1, charge_ws.max_column + 1):
            charge_ws.cell(charge_next_row, col).value = charge_ws.cell(source_row, col).value
        values = [
            room_path_value,
            "UI周期性收费项",
            "周期类-自定义金额",
            None,
            "2023-01-01",
            "2028-12-31",
        ]
        for col, value in enumerate(values, 1):
            charge_ws.cell(charge_next_row, col).value = value
        charge_next_row += 1
    update_table_ref(charge_ws, charge_next_row - 1)
    charge_wb.save(charge_item_path)
    print(f"updated mapping={mapping_path}")
    print(f"updated rooms={room_path}")
    print(f"updated charge_items={charge_item_path}")


if __name__ == "__main__":
    main()
