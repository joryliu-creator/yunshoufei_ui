from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config.excel_data import DEFAULT_WORKBOOK, _header_map, _text

try:
    from openpyxl import load_workbook
except ModuleNotFoundError:  # pragma: no cover - bundled runtime fallback
    import sys

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / ".tools" / "python"))
    from openpyxl import load_workbook


@dataclass(frozen=True, slots=True)
class BillDiscountCase:
    case_id: str
    scenario_id: str
    room_path: str
    discount_scheme: str
    remark: str
    expected_original_amount: str
    expected_discount_amount: str
    expected_receivable_amount: str
    discount_amount_input: str
    cleanup_strategy: str
    enabled: str
    maintenance_status: str


def load_bill_discount_case(
    case_id: str = "YSF-BILL-DISCOUNT-1101",
    workbook_path: Path | None = None,
) -> BillDiscountCase:
    path = workbook_path or DEFAULT_WORKBOOK
    if not path.exists():
        raise FileNotFoundError(f"测试数据 Excel 不存在：{path}")
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if "账单减免专项" not in workbook.sheetnames:
            raise ValueError("Excel 缺少“账单减免专项”工作表。")
        worksheet = workbook["账单减免专项"]
        headers = _header_map(worksheet)
        id_column = headers.get("用例编号")
        if id_column is None:
            raise ValueError("账单减免专项缺少“用例编号”列。")
        matches = [
            row
            for row in range(2, worksheet.max_row + 1)
            if _text(worksheet.cell(row, id_column).value) == case_id
        ]
        if len(matches) != 1:
            raise ValueError(
                f"账单减免用例 {case_id!r} 应唯一存在，实际匹配 {len(matches)} 行。"
            )
        row = matches[0]

        def value(name: str) -> str:
            column = headers.get(name)
            if column is None:
                raise ValueError(f"账单减免专项缺少“{name}”列。")
            return _text(worksheet.cell(row, column).value)

        case = BillDiscountCase(
            case_id=value("用例编号"),
            scenario_id=value("场景引用"),
            room_path=value("目标房间"),
            discount_scheme=value("减免方案"),
            remark=value("减免说明"),
            expected_original_amount=value("预期原始金额"),
            expected_discount_amount=value("预期减免金额"),
            expected_receivable_amount=value("预期应收金额"),
            discount_amount_input=(value("设置减免金额") if headers.get("设置减免金额") else ""),
            cleanup_strategy=value("清理策略"),
            enabled=value("是否启用"),
            maintenance_status=value("维护状态"),
        )
        if case.enabled != "是" or not case.maintenance_status.startswith("已核验"):
            raise ValueError(
                f"账单减免用例 {case_id!r} 尚未同时满足“已核验且启用”。"
            )
        if not case.scenario_id.startswith("SCENARIO_ID="):
            raise ValueError("账单减免专项的“场景引用”必须使用 SCENARIO_ID= 前缀。")
        return case
    finally:
        workbook.close()
