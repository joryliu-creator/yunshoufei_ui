"""Append dedicated public-sharing rooms to the room import template.

The rooms intentionally have no charge-item binding.  They are only used as
the two participants of each public-sharing scheme and are grouped in the
备注 column so the initialization data remains auditable.
"""

from __future__ import annotations

from copy import copy
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "前置数据模版文件" / "房间导入模版.xlsx"
START_ROOM = 1201

# 任何依赖计费面积的公摊方式，都必须使用一对面积不同的房间，才能
# 区分建筑面积/使用面积/收费面积的计算结果。收费面积由房间收费配置
# 另行维护；本模板负责把建筑面积和使用面积设置成可区分的基础数据。
AREA_DISTINCT_PAIRS = (
    # 周期类：建筑面积、使用面积、收费面积
    ("1205", "1206"),
    ("1271", "1272"),
    ("1273", "1274"),
    # 仪表类：按计费面积分摊、按住户计费面积对应系数分摊；
    # 每种仪表类型分别覆盖按满月/按天两组房间。
    ("1211", "1212"), ("1213", "1214"),
    ("1219", "1220"), ("1221", "1222"),
    ("1227", "1228"), ("1229", "1230"),
    ("1235", "1236"), ("1237", "1238"),
    ("1243", "1244"), ("1245", "1246"),
    ("1251", "1252"), ("1253", "1254"),
    ("1259", "1260"), ("1261", "1262"),
    ("1267", "1268"), ("1269", "1270"),
)

AREA_VALUES = {
    "first": (300.12, 280.01),
    "second": (360.36, 315.15),
}


def _area_values_for_room(room: str) -> tuple[float, float] | None:
    for first, second in AREA_DISTINCT_PAIRS:
        if room == first:
            return AREA_VALUES["first"]
        if room == second:
            return AREA_VALUES["second"]
    return None


def _plan() -> list[tuple[str, str]]:
    groups: list[tuple[str, str, int]] = []

    periodic = (
        "周期性公摊",
        [
            "按房间设置比例分摊",
            "按房间设置金额分摊",
            "按住户面积及所在楼层对应系数公摊",
        ],
    )
    for formula in periodic[1]:
        groups.append((periodic[0], formula, 2))

    meter_types = ("水表", "电表", "燃气表", "空调")
    meter_methods = (
        "按户分摊",
        "按计费面积分摊",
        "按住户所在楼层对应系数分摊",
        "按住户计费面积对应系数分摊",
    )
    for meter_type in meter_types:
        for method in meter_methods:
            groups.append((f"仪表类-{meter_type}", method, 4))

    rows: list[tuple[str, str]] = []
    room = START_ROOM
    for category, method, count in groups:
        if count == 2:
            modes = ("按满月计费",)
        else:
            modes = ("按满月计费", "按天计费")
        for mode in modes:
            pair = f"{room}/{room + 1}"
            for _ in range(2):
                remark = (
                    f"公摊方案验证；公摊类型：{category}；"
                    f"公摊方式/公式：{method}；计费模式：{mode}；"
                    f"方案绑定房间组：{pair}；参与公摊房间；不绑定收费项"
                )
                if method == "按住户面积及所在楼层对应系数公摊":
                    remark = remark.replace(
                        "计费模式：按满月计费；",
                        "计费模式：按满月计费；计费面积：建筑面积；",
                    )
                rows.append((str(room), remark))
                room += 1

    # 该周期类公摊方式还需要覆盖“使用面积”和“收费面积”两种计费面积。
    # 1205/1206 已作为“建筑面积”验证房间保留，因此新增两组房间。
    for area in ("使用面积", "收费面积"):
        pair = f"{room}/{room + 1}"
        for _ in range(2):
            remark = (
                "公摊方案验证；公摊类型：周期性公摊；"
                "公摊方式/公式：按住户面积及所在楼层对应系数公摊；"
                "计费模式：按满月计费；"
                f"计费面积：{area}；方案绑定房间组：{pair}；"
                "参与公摊房间；不绑定收费项"
            )
            rows.append((str(room), remark))
            room += 1
    result: list[tuple[str, str]] = []
    for room, remark in rows:
        area_values = _area_values_for_room(room)
        if area_values is not None:
            building, usable = area_values
            remark = (
                f"{remark}；建筑面积={building:.2f}；使用面积={usable:.2f}"
            )
        result.append((room, remark))
    return result


def _copy_row(ws, source_row: int, target_row: int) -> None:
    if ws.row_dimensions[source_row].height is not None:
        ws.row_dimensions[target_row].height = ws.row_dimensions[source_row].height
    for column in range(1, ws.max_column + 1):
        source = ws.cell(source_row, column)
        target = ws.cell(target_row, column)
        target.value = source.value
        if source.has_style:
            target._style = copy(source._style)
        if source.number_format:
            target.number_format = source.number_format
        if source.font:
            target.font = copy(source.font)
        if source.fill:
            target.fill = copy(source.fill)
        if source.border:
            target.border = copy(source.border)
        if source.alignment:
            target.alignment = copy(source.alignment)
        if source.protection:
                target.protection = copy(source.protection)


def _area_columns(ws) -> tuple[int, int]:
    building = next(
        (cell.column for cell in ws[1] if "建筑面积" in str(cell.value or "")),
        None,
    )
    usable = next(
        (cell.column for cell in ws[1] if "使用面积" in str(cell.value or "")),
        None,
    )
    if building is None or usable is None:
        raise ValueError("房间导入模板缺少建筑面积或使用面积列，已停止写入")
    return building, usable


def _apply_area_distinction(ws, room_column: int) -> int:
    building_column, usable_column = _area_columns(ws)
    rows_by_room = {
        str(ws.cell(row, room_column).value).strip(): row
        for row in range(2, ws.max_row + 1)
        if ws.cell(row, room_column).value not in (None, "")
    }
    changed = 0
    missing: list[str] = []
    for first, second in AREA_DISTINCT_PAIRS:
        if first not in rows_by_room or second not in rows_by_room:
            missing.extend(room for room in (first, second) if room not in rows_by_room)
            continue
        first_row = rows_by_room[first]
        second_row = rows_by_room[second]
        first_building, first_usable = AREA_VALUES["first"]
        second_building, second_usable = AREA_VALUES["second"]
        for row, building, usable in (
            (first_row, first_building, first_usable),
            (second_row, second_building, second_usable),
        ):
            if (
                ws.cell(row, building_column).value != building
                or ws.cell(row, usable_column).value != usable
            ):
                ws.cell(row, building_column).value = building
                ws.cell(row, usable_column).value = usable
                changed += 1
    if missing:
        raise ValueError(f"计费面积公摊专用房间缺失，未写入面积：{sorted(set(missing))}")
    return changed


def main() -> None:
    if not WORKBOOK.exists():
        raise FileNotFoundError(WORKBOOK)
    wb = load_workbook(WORKBOOK)
    ws = wb.active
    headers = {str(cell.value).strip(): cell.column for cell in ws[1]}
    room_column = headers.get("*房间号\n若有地下层，可填写“-1层”")
    remark_column = headers.get("备注")
    if room_column is None or remark_column is None:
        raise ValueError("房间导入模板缺少房间号或备注列，已停止写入")

    plan = _plan()
    planned_rooms = {room for room, _ in plan}
    source_row = 2
    existing_rooms = {
        str(ws.cell(row, room_column).value).strip()
        for row in range(2, ws.max_row + 1)
        if ws.cell(row, room_column).value not in (None, "")
    }
    overlap = sorted(planned_rooms & existing_rooms)
    if overlap:
        # 允许修复本脚本此前只复制样式、未复制值造成的半成品行；
        # 任何不带本脚本公摊备注的同号历史房间仍然拒绝覆盖。
        existing_rows = {
            str(ws.cell(row, room_column).value).strip(): row
            for row in range(2, ws.max_row + 1)
        }
        unsafe = [
            room
            for room in overlap
            if "公摊方案验证" not in str(
                ws.cell(existing_rows[room], remark_column).value or ""
            )
        ]
        if unsafe:
            raise ValueError(f"目标房间已存在，拒绝覆盖：{unsafe or overlap}")
        next_row = ws.max_row + 1
        repaired = 0
        added = 0
        for room, remark in plan:
            if room in existing_rows:
                row = existing_rows[room]
                repaired += 1
            else:
                row = next_row
                next_row += 1
                added += 1
            _copy_row(ws, source_row, row)
            ws.cell(row, room_column).value = room
            ws.cell(row, remark_column).value = remark
        changed = _apply_area_distinction(ws, room_column)
        wb.save(WORKBOOK)
        print(
            f"修复公摊验证房间 {repaired} 个并新增 {added} 个："
            f"{plan[0][0]}-{plan[-1][0]}；面积差异更新 {changed} 个"
        )
        return

    for index, (room, remark) in enumerate(plan, start=ws.max_row + 1):
        _copy_row(ws, source_row, index)
        ws.cell(index, room_column).value = room
        ws.cell(index, remark_column).value = remark

    changed = _apply_area_distinction(ws, room_column)

    wb.save(WORKBOOK)
    print(f"追加公摊验证房间 {len(plan)} 个：{plan[0][0]}-{plan[-1][0]}")
    print(f"收费项绑定：空；备注已写入公摊类型、方式、计费模式和房间组；面积差异更新 {changed} 个")


if __name__ == "__main__":
    main()
