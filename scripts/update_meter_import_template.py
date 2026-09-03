from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))

from openpyxl import load_workbook


WORKBOOK = ROOT / "仪表导入模板.xlsx"
ROOM_METER_TYPES = {
    "1032": "水表",
    "1033": "水表",
    "1034": "水表",
    "1035": "水表",
    "1037": "水表",
    "1038": "水表",
    "1040": "电表",
    "1041": "电表",
    "1042": "电表",
    "1043": "电表",
    "1045": "电表",
    "1046": "电表",
}


def main() -> None:
    if not WORKBOOK.exists():
        raise FileNotFoundError(f"未找到仪表导入模板：{WORKBOOK}")
    workbook = load_workbook(WORKBOOK)
    worksheet = workbook["Sheet1"]
    headers = {
        str(cell.value).strip(): index
        for index, cell in enumerate(worksheet[3], 1)
        if cell.value is not None
    }
    required = {"仪表名称*", "仪表编号*", "仪表类型*", "关联收费房间"}
    missing = required - set(headers)
    if missing:
        workbook.close()
        raise ValueError(f"仪表导入模板缺少字段：{sorted(missing)}")

    seen: set[str] = set()
    for row in range(4, worksheet.max_row + 1):
        room_path = str(
            worksheet.cell(row, headers["关联收费房间"]).value or ""
        ).strip()
        if not room_path:
            continue
        room_name = room_path.rsplit("/", 1)[-1]
        if room_name not in ROOM_METER_TYPES:
            workbook.close()
            raise ValueError(f"仪表模板存在映射外房间：{room_path}")
        if room_name in seen:
            workbook.close()
            raise ValueError(f"仪表模板房间重复：{room_path}")
        seen.add(room_name)
        meter_type = ROOM_METER_TYPES[room_name]
        meter_name = f"{meter_type}{room_name}"
        worksheet.cell(row, headers["仪表名称*"], meter_name)
        worksheet.cell(row, headers["仪表编号*"], meter_name)
        worksheet.cell(row, headers["仪表类型*"], meter_type)

    missing_rooms = set(ROOM_METER_TYPES) - seen
    if missing_rooms:
        workbook.close()
        raise ValueError(f"仪表模板缺少房间：{sorted(missing_rooms)}")
    workbook.save(WORKBOOK)
    workbook.close()
    print(f"updated={WORKBOOK}")
    print(f"meter_count={len(seen)}")


if __name__ == "__main__":
    main()
