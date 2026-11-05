from __future__ import annotations

from openpyxl import load_workbook

from scripts.add_public_share_rooms import AREA_DISTINCT_PAIRS, _plan


WORKBOOK = "前置数据模版文件/房间导入模版.xlsx"


def _columns(sheet):
    headers = {str(cell.value): cell.column for cell in sheet[1]}
    room = next(value for key, value in headers.items() if "房间号" in key)
    building = next(value for key, value in headers.items() if "建筑面积" in key)
    usable = next(value for key, value in headers.items() if "使用面积" in key)
    remark = headers["备注"]
    return room, building, usable, remark


def test_public_share_room_plan_covers_all_area_distinct_pairs() -> None:
    planned = {room for room, _ in _plan()}
    assert len(_plan()) == 74
    assert len(AREA_DISTINCT_PAIRS) == 19
    assert all(room in planned for pair in AREA_DISTINCT_PAIRS for room in pair)


def test_public_share_area_pairs_have_distinct_building_and_usable_areas() -> None:
    sheet = load_workbook(WORKBOOK, data_only=True).active
    room_column, building_column, usable_column, remark_column = _columns(sheet)
    rows = {
        str(sheet.cell(row, room_column).value).strip(): row
        for row in range(2, sheet.max_row + 1)
        if sheet.cell(row, room_column).value not in (None, "")
    }

    for first, second in AREA_DISTINCT_PAIRS:
        assert first in rows and second in rows
        first_values = (
            sheet.cell(rows[first], building_column).value,
            sheet.cell(rows[first], usable_column).value,
        )
        second_values = (
            sheet.cell(rows[second], building_column).value,
            sheet.cell(rows[second], usable_column).value,
        )
        assert first_values[0] != first_values[1]
        assert second_values[0] != second_values[1]
        assert first_values != second_values
        assert "建筑面积=" in str(sheet.cell(rows[first], remark_column).value)
        assert "使用面积=" in str(sheet.cell(rows[second], remark_column).value)
