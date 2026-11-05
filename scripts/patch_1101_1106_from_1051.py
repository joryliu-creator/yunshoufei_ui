"""直接修正 1101-1106 的临时类映射和收费项导入模板。

以 1051 的整行业务配置为基准，只保留目标行自己的序号/房间号；
不重建工作簿、不改变其他房间和工作表。
"""
from __future__ import annotations

from copy import copy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".tools" / "python"))
from openpyxl import load_workbook  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
TARGET_ROOMS = {str(i) for i in range(1101, 1107)}
BASE_ROOM = "1051"


def room_from_mapping_row(row: tuple[object, ...]) -> str:
    return str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""


def find_mapping_workbook() -> Path:
    for path in ROOT.glob("*.xlsx"):
        if path.name.startswith("~$"):
            continue
        try:
            workbook = load_workbook(path, read_only=True, data_only=False)
        except Exception:
            continue
        for sheet in workbook.worksheets:
            values = [sheet.cell(1, col).value for col in range(1, min(sheet.max_column, 12) + 1)]
            if "房间名称" in values and "计费公式" in values:
                return path
    raise FileNotFoundError("未找到房间收费标准映射表")


def find_charge_item_template() -> Path:
    for path in (ROOT / "前置数据模版文件").rglob("*.xlsx"):
        try:
            workbook = load_workbook(path, read_only=True, data_only=False)
        except Exception:
            continue
        for sheet in workbook.worksheets:
            if sheet.max_row >= 30 and sheet.max_column == 6:
                values = [sheet.cell(1, col).value for col in range(1, 7)]
                if any("收费项" in str(value) for value in values):
                    return path
    raise FileNotFoundError("未找到收费项导入模板")


def find_room_row(sheet, room: str) -> int:
    for row in range(2, sheet.max_row + 1):
        if room_from_mapping_row(tuple(sheet.cell(row, col).value for col in range(1, 3))) == room:
            return row
    raise KeyError(f"映射表未找到房间 {room}")


def patch_mapping(path: Path) -> dict[str, object]:
    workbook = load_workbook(path, data_only=False)
    sheet = workbook.worksheets[0]
    base_row = find_room_row(sheet, BASE_ROOM)
    target_rows = {room: find_room_row(sheet, room) for room in TARGET_ROOMS}
    # A=序号、B=房间名称保留目标行；其余业务列完整复制 1051。
    for room, row in target_rows.items():
        sheet.cell(row, 2).value = room
        for col in range(3, sheet.max_column + 1):
            source = sheet.cell(base_row, col)
            target = sheet.cell(row, col)
            target.value = source.value
            if source.has_style:
                target._style = copy(source._style)
            if source.number_format:
                target.number_format = source.number_format
            if source.alignment:
                target.alignment = copy(source.alignment)
            if source.protection:
                target.protection = copy(source.protection)
    workbook.save(path)
    return {"file": str(path), "base_room": BASE_ROOM, "rooms": sorted(TARGET_ROOMS)}


def patch_charge_item_template(path: Path) -> dict[str, object]:
    workbook = load_workbook(path, data_only=False)
    sheet = workbook.worksheets[0]
    rows: dict[str, int] = {}
    for row in range(2, sheet.max_row + 1):
        value = str(sheet.cell(row, 1).value or "")
        for room in TARGET_ROOMS | {BASE_ROOM}:
            if value.rstrip("/").endswith(f"/{room}"):
                rows[room] = row
    missing = (TARGET_ROOMS | {BASE_ROOM}) - rows.keys()
    if missing:
        raise KeyError(f"收费项导入模板缺少房间: {sorted(missing)}")
    base_row = rows[BASE_ROOM]
    for room in TARGET_ROOMS:
        row = rows[room]
        # A 列房间路径保留目标房间，其余收费项/收费标准/日期/仪表列复制 1051。
        original_path = str(sheet.cell(row, 1).value or "")
        prefix = original_path.rsplit("/", 1)[0]
        for col in range(2, sheet.max_column + 1):
            source = sheet.cell(base_row, col)
            target = sheet.cell(row, col)
            target.value = source.value
            if source.has_style:
                target._style = copy(source._style)
            target.number_format = source.number_format
            target.alignment = copy(source.alignment)
            target.protection = copy(source.protection)
        sheet.cell(row, 1).value = f"{prefix}/{room}"
    workbook.save(path)
    return {"file": str(path), "base_room": BASE_ROOM, "rooms": sorted(TARGET_ROOMS)}


def main() -> None:
    mapping = find_mapping_workbook()
    charge_item = find_charge_item_template()
    print(patch_mapping(mapping))
    print(patch_charge_item_template(charge_item))


if __name__ == "__main__":
    main()
