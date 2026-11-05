from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))
sys.path.insert(0, str(ROOT))

from openpyxl import load_workbook

from scripts.update_room_import_template import CHARGE_ITEM_NAMES
from src.config.standard_name import automation_standard_name


TEMPLATE = ROOT / "收费项导入模板.xlsx"
MAPPING_WORKBOOK = ROOT / "房间收费标准映射表.xlsx"
METER_IMPORT_WORKBOOK = ROOT / "前置数据模版文件" / "仪表导入模板.xlsx"
METER_TYPES = {"水表仪表类", "电表仪表类"}
SUPPORTED_IMPORT_TYPES = {"周期类", *METER_TYPES}
EXPECTED_METER_TYPES = {
    "水表仪表类": "水表",
    "电表仪表类": "电表",
}
# 这些标准是此前已存在于普通“押金类收费项”下的基准数据，
# 导入房间关联时必须引用其真实所属收费项，不能按收费类型统一推导。
IMPORT_CHARGE_ITEM_OVERRIDES = {
    "1021": "押金类收费项",
    "1022": "押金类收费项",
    "1023": "押金类收费项",
}
REQUIRED_MAPPING_HEADERS = {
    "房间名称",
    "收费类型",
    "建议收费标准名称",
    "创建策略",
}


@dataclass(frozen=True, slots=True)
class ChargeItemImportRow:
    room_path: str
    charge_item: str
    charge_standard: str
    meter_name: str
    start_date: object
    end_date: object
    charge_type: str


@dataclass(frozen=True, slots=True)
class MeterRecord:
    room_path: str
    meter_name: str
    meter_type: str


def _copy_cell_style(source, target) -> None:
    if source.has_style:
        target._style = copy(source._style)
    target.number_format = source.number_format
    target.protection = copy(source.protection)
    target.alignment = copy(source.alignment)


def _load_active_mappings() -> list[dict[str, object]]:
    workbook = load_workbook(MAPPING_WORKBOOK, data_only=True)
    worksheet = workbook["房间收费标准映射"]
    headers = {
        str(cell.value).strip(): index
        for index, cell in enumerate(worksheet[1])
        if cell.value is not None
    }
    missing = REQUIRED_MAPPING_HEADERS - set(headers)
    if missing:
        workbook.close()
        raise ValueError(f"房间收费标准映射表缺少字段：{sorted(missing)}")

    mappings: list[dict[str, object]] = []
    for values in worksheet.iter_rows(min_row=2, values_only=True):
        row = {name: values[index] for name, index in headers.items()}
        if (
            str(row["创建策略"] or "").strip() == "创建"
            and str(row["收费类型"] or "").strip() in SUPPORTED_IMPORT_TYPES
        ):
            mappings.append(row)
    workbook.close()
    return mappings


def load_meter_records() -> list[MeterRecord]:
    if not METER_IMPORT_WORKBOOK.exists():
        raise FileNotFoundError(f"未找到仪表导入模板：{METER_IMPORT_WORKBOOK}")
    workbook = load_workbook(METER_IMPORT_WORKBOOK, data_only=True)
    worksheet = workbook["Sheet1"]
    header_row = 3
    headers = {
        str(cell.value).strip(): index
        for index, cell in enumerate(worksheet[header_row])
        if cell.value is not None
    }
    required = {"仪表名称*", "仪表类型*", "关联收费房间"}
    missing = required - set(headers)
    if missing:
        workbook.close()
        raise ValueError(f"仪表导入模板缺少字段：{sorted(missing)}")

    records: list[MeterRecord] = []
    for values in worksheet.iter_rows(min_row=header_row + 1, values_only=True):
        meter_name = str(values[headers["仪表名称*"]] or "").strip()
        meter_type = str(values[headers["仪表类型*"]] or "").strip()
        room_paths = str(values[headers["关联收费房间"]] or "").strip()
        if not meter_name and not meter_type and not room_paths:
            continue
        if not meter_name or not meter_type or not room_paths:
            workbook.close()
            raise ValueError("仪表导入模板存在缺少名称、类型或关联收费房间的记录。")
        for room_path in (part.strip() for part in room_paths.split(",")):
            if room_path:
                records.append(MeterRecord(room_path, meter_name, meter_type))
    workbook.close()
    return records


def meter_name_for(
    room_path: str,
    charge_type: str,
    meter_records: list[MeterRecord],
) -> tuple[str, str]:
    if charge_type not in METER_TYPES:
        return "", ""
    same_room = [record for record in meter_records if record.room_path == room_path]
    expected_type = EXPECTED_METER_TYPES[charge_type]
    matching = [record for record in same_room if record.meter_type == expected_type]
    if len(matching) == 1:
        return matching[0].meter_name, ""
    if len(matching) > 1:
        return "", f"房间 {room_path} 存在多个 {expected_type} 仪表"
    actual_types = sorted({record.meter_type for record in same_room})
    if actual_types:
        return "", (
            f"房间 {room_path} 需要 {expected_type}，仪表模板实际为 "
            f"{','.join(actual_types)}"
        )
    return "", f"房间 {room_path} 未找到 {expected_type} 仪表"


def build_import_rows(
    room_prefix: str,
    start_date: object,
    end_date: object,
    meter_records: list[MeterRecord] | None = None,
) -> tuple[list[ChargeItemImportRow], list[str]]:
    meter_records = meter_records if meter_records is not None else load_meter_records()
    rows: list[ChargeItemImportRow] = []
    meter_issues: list[str] = []
    for mapping in _load_active_mappings():
        charge_type = str(mapping["收费类型"] or "").strip()
        if charge_type not in CHARGE_ITEM_NAMES:
            raise ValueError(f"未配置收费类型 {charge_type!r} 对应的收费项名称。")
        room_name = str(mapping["房间名称"] or "").strip()
        standard_name = automation_standard_name(
            str(mapping["建议收费标准名称"] or "").strip()
        )
        if not room_name or not standard_name:
            raise ValueError("创建策略为“创建”的映射缺少房间或收费标准名称。")
        room_path = f"{room_prefix}/{room_name}"
        meter_name, meter_issue = meter_name_for(
            room_path, charge_type, meter_records
        )
        if meter_issue:
            meter_issues.append(meter_issue)
        rows.append(
            ChargeItemImportRow(
                room_path=room_path,
                charge_item=IMPORT_CHARGE_ITEM_OVERRIDES.get(
                    room_name, CHARGE_ITEM_NAMES[charge_type]
                ),
                charge_standard=standard_name,
                # 仪表名称必须与目标房间中已经维护的同类型仪表完全一致。
                # 现有资产没有这项数据，禁止按房间号或收费项名称猜测。
                meter_name=meter_name,
                start_date=start_date,
                end_date=end_date,
                charge_type=charge_type,
            )
        )
    return rows, meter_issues


def main() -> None:
    if not TEMPLATE.exists():
        raise FileNotFoundError(f"未找到收费项导入模板：{TEMPLATE}")
    if not MAPPING_WORKBOOK.exists():
        raise FileNotFoundError(f"未找到房间收费标准映射表：{MAPPING_WORKBOOK}")

    workbook = load_workbook(TEMPLATE)
    worksheet = workbook["Sheet1"]
    expected_headers = (
        "*房间名称",
        "*收费项",
        "*收费标准",
        "仪表",
        "*计费开始时间",
        "*计费结束时间",
    )
    actual_headers = tuple(
        str(worksheet.cell(1, column).value or "").splitlines()[0].strip()
        for column in range(1, 7)
    )
    if actual_headers != expected_headers:
        workbook.close()
        raise ValueError(
            "收费项导入模板表头与预期不一致；"
            f"期望={expected_headers}，实际={actual_headers}"
        )
    sample_path = str(worksheet.cell(2, 1).value or "").strip()
    if "/" not in sample_path:
        workbook.close()
        raise ValueError("模板示例房间路径无效，无法提取区/楼栋/单元/楼层前缀。")
    room_prefix = sample_path.rsplit("/", 1)[0]
    start_date = worksheet.cell(2, 5).value
    end_date = worksheet.cell(2, 6).value
    if not start_date or not end_date:
        workbook.close()
        raise ValueError("模板示例行缺少计费开始或结束时间。")

    rows, meter_issues = build_import_rows(room_prefix, start_date, end_date)
    template_row = 2
    for offset, item in enumerate(rows):
        target_row = template_row + offset
        for column in range(1, 7):
            _copy_cell_style(
                worksheet.cell(template_row, column),
                worksheet.cell(target_row, column),
            )
        values = (
            item.room_path,
            item.charge_item,
            item.charge_standard,
            item.meter_name,
            item.start_date,
            item.end_date,
        )
        for column, value in enumerate(values, 1):
            worksheet.cell(target_row, column, value)
        # 仪表列与模板示例行保持完全相同的原始格式，不增加颜色或批注。
        worksheet.cell(target_row, 4).comment = None
        worksheet.row_dimensions[target_row].height = (
            worksheet.row_dimensions[template_row].height
        )

    first_unused_row = template_row + len(rows)
    if worksheet.max_row >= first_unused_row:
        worksheet.delete_rows(
            first_unused_row, worksheet.max_row - first_unused_row + 1
        )

    workbook.save(TEMPLATE)
    workbook.close()
    meter_count = sum(item.charge_type in METER_TYPES for item in rows)
    meter_filled = sum(bool(item.meter_name) for item in rows)
    print(f"updated={TEMPLATE}")
    print(f"row_count={len(rows)}")
    print(f"ready_count={len(rows) - len(meter_issues)}")
    print(f"meter_name_required={meter_count}")
    print(f"meter_name_filled={meter_filled}")
    if meter_issues:
        print("meter_issues:")
        for issue in meter_issues:
            print(f"- {issue}")


if __name__ == "__main__":
    main()
