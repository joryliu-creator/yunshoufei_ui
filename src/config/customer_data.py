from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

try:
    from openpyxl import load_workbook
except ModuleNotFoundError:  # keep the project venv compatible with Excel loaders
    ROOT_FOR_TOOLS = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT_FOR_TOOLS / ".tools" / "python"))
    from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CUSTOMER_WORKBOOK = ROOT / "前置数据模版文件" / "企业客户导入模板.xlsx"


@dataclass(frozen=True, slots=True)
class CustomerRoomMapping:
    customer_name: str
    project_name: str
    room_path: str


def _is_room_path(value: str) -> bool:
    """Distinguish a template help-text row from a building/floor/room path."""
    parts = [part.strip() for part in value.split("/") if part.strip()]
    return len(parts) >= 3 and parts[-1].isdigit()


def load_customer_room_mapping(
    room_name: str,
    workbook_path: Path = DEFAULT_CUSTOMER_WORKBOOK,
) -> CustomerRoomMapping:
    """Load one customer/room prerequisite mapping from the import template.

    The workbook is the source of truth for customer-room associations.  A
    missing or ambiguous mapping is an input error; it is never guessed from
    a room number or from the current page order.
    """
    target = str(room_name).strip()
    if not target:
        raise ValueError("房间名称不能为空")
    if not workbook_path.exists():
        raise FileNotFoundError(f"客户导入模板不存在: {workbook_path}")

    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()

    if not rows:
        raise ValueError(f"客户导入模板为空: {workbook_path}")

    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    required = ["*客户名称", "*所属项目", "房屋"]
    missing = set(required).difference(headers)
    if missing:
        raise ValueError(f"客户导入模板缺少字段: {sorted(missing)}")
    index = {header: headers.index(header) for header in required}

    matches: list[CustomerRoomMapping] = []
    # Row 2 in the enterprise-customer import template is a field-help row,
    # not a customer record.  Ignore it and any other non-room instruction row.
    for row in rows[1:]:
        values = [
            str(row[index[key]]).strip() if row[index[key]] is not None else ""
            for key in required
        ]
        customer_name, project_name, room_path = values
        if _is_room_path(room_path) and room_path.rstrip("/").split("/")[-1] == target:
            matches.append(CustomerRoomMapping(customer_name, project_name, room_path))

    if len(matches) != 1:
        raise ValueError(
            f"房间 {target!r} 在客户导入模板中应唯一匹配，实际匹配 {len(matches)} 条"
        )
    return matches[0]


def load_all_customer_room_mappings(
    workbook_path: Path = DEFAULT_CUSTOMER_WORKBOOK,
) -> list[CustomerRoomMapping]:
    """Load all unique customer-room mappings in template order."""
    if not workbook_path.exists():
        raise FileNotFoundError(f"客户导入模板不存在: {workbook_path}")
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    if not rows:
        return []
    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    required = ["*客户名称", "*所属项目", "房屋"]
    missing = set(required).difference(headers)
    if missing:
        raise ValueError(f"客户导入模板缺少字段: {sorted(missing)}")
    index = {header: headers.index(header) for header in required}
    result: list[CustomerRoomMapping] = []
    seen_rooms: set[str] = set()
    # The second row documents each field.  Only rows with a real room path
    # are eligible for prerequisite migration.
    for row in rows[1:]:
        values = [
            str(row[index[key]]).strip() if row[index[key]] is not None else ""
            for key in required
        ]
        mapping = CustomerRoomMapping(*values)
        room_name = mapping.room_path.rstrip("/").split("/")[-1]
        if not all(values) or not _is_room_path(mapping.room_path) or room_name in seen_rooms:
            continue
        seen_rooms.add(room_name)
        result.append(mapping)
    return result
