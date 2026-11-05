"""Parameterized data for the four instrument public-sharing workflows."""

from __future__ import annotations

import ast

from openpyxl import load_workbook

from src.config.excel_data import DEFAULT_WORKBOOK
from src.pages.public_share_scheme_page import PublicShareSchemeCase


METER_GROUPS = (
    {
        "display": "水表",
        "instrument_type": "水表",
        "charge_item": "UI公摊水费",
        "charge_standard": "公摊水费收费标准",
        "first_room": 1207,
        "prefix": "UI",
        "short_type": "水表",
        "regression": False,
    },
    {
        "display": "电表",
        "instrument_type": "电表",
        "charge_item": "UI公摊电费",
        "charge_standard": "公摊电费收费标准",
        "first_room": 1223,
        "prefix": "UI",
        "short_type": "电表",
        "regression": False,
    },
    {
        "display": "燃气表",
        "instrument_type": "燃气表",
        "charge_item": "公摊燃气",
        "charge_standard": "公摊燃气收费标准",
        "first_room": 1239,
        "prefix": "AT-UI",
        "short_type": "燃气",
        "regression": True,
    },
    {
        "display": "空调",
        "instrument_type": "空调",
        "charge_item": "公摊空调",
        "charge_standard": "公摊空调收费标准",
        "first_room": 1255,
        "prefix": "AT-UI",
        "short_type": "空调",
        "regression": True,
    },
)

METHODS = (
    ("HOUSEHOLD", "按户分摊", "按户", None, None),
    ("AREA", "按计费面积分摊", "面积", "建筑面积", None),
    (
        "FLOOR_COEFFICIENT",
        "按住户所在楼层对应系数分摊",
        "楼层系数",
        None,
        None,
    ),
    (
        "METER_AREA_COEFFICIENT",
        "按住户计费面积对应系数分摊",
        "计费面积系数",
        "使用面积",
        None,
    ),
)

MONTH_RULES = (("FULL", "按满月计费"), ("DAILY", "按天计费"))


def instrument_cases(*, regression: bool) -> tuple[PublicShareSchemeCase, ...]:
    """Build eight cases per selected instrument type, aligned to room pairs.

    Pair order matches ``scripts/add_public_share_rooms.py``: four sharing
    methods, each with full-month then per-day rule.
    """
    cases: list[PublicShareSchemeCase] = []
    for meter in METER_GROUPS:
        if meter["regression"] is not regression:
            continue
        pair_index = 0
        for method_code, method, short_method, area, expected_area in METHODS:
            for rule_code, month_rule in MONTH_RULES:
                first = int(meter["first_room"]) + pair_index * 2
                second = first + 1
                room_pair = (str(first), str(second))
                name = (
                    f"{meter['prefix']}-{meter['short_type']}-{short_method}-"
                    f"{'满月' if rule_code == 'FULL' else '按天'}-{first}-{second}"
                )
                case_id = (
                    f"YSF-PUBLIC-SHARE-METER-{meter['display'].upper()}-"
                    f"{method_code}-{rule_code}-{first}-{second}"
                )
                floor_tiers = None
                if method_code == "FLOOR_COEFFICIENT":
                    # Recorded workflow: floor <=2 / 4 households / coeff 3;
                    # floor 3 / 4 households / coeff 5.
                    floor_tiers = (("2", "4", "3"), ("3", "4", "5"))
                elif method_code == "METER_AREA_COEFFICIENT":
                    # The documented flow leaves the second lower bound blank,
                    # but the live backend rejects it with “请设置阶梯面积”.
                    # Match its continuous, non-empty range validation.
                    floor_tiers = (("5", "3"), ("6", "5"))

                cases.append(
                    PublicShareSchemeCase(
                        case_id=case_id,
                        name=name,
                        method=method,
                        rooms=room_pair,
                        charge_type="仪表类费用",
                        charge_item=str(meter["charge_item"]),
                        charge_standard=str(meter["charge_standard"]),
                        instrument_type=str(meter["instrument_type"]),
                        instrument_name=f"{meter['display']}{first},{meter['display']}{second}",
                        incomplete_month_rule=month_rule,
                        billing_area=area,
                        expected_area_total=expected_area,
                        household_count="2",
                        floor_tiers=floor_tiers,
                    )
                )
                pair_index += 1
    return tuple(cases)


INITIAL_CASES = instrument_cases(regression=False)
REGRESSION_CASES = instrument_cases(regression=True)


if len(INITIAL_CASES) != 16 or len(REGRESSION_CASES) != 16:
    raise RuntimeError("仪表公摊场景参数数量错误；预期每类仪表 8 个场景")


def load_instrument_cases(*, regression: bool) -> tuple[PublicShareSchemeCase, ...]:
    """Read the executable instrument cases from the maintained Excel sheet."""
    if not DEFAULT_WORKBOOK.exists():
        raise FileNotFoundError(f"回归用例工作簿不存在：{DEFAULT_WORKBOOK}")
    workbook = load_workbook(DEFAULT_WORKBOOK, read_only=True, data_only=True)
    try:
        if "公摊方案专项" not in workbook.sheetnames:
            raise ValueError("Excel 缺少“公摊方案专项”工作表")
        worksheet = workbook["公摊方案专项"]
        headers = {
            str(worksheet.cell(1, column).value or "").strip(): column
            for column in range(1, worksheet.max_column + 1)
        }
        required = (
            "用例编号",
            "方案名称",
            "公摊方式",
            "公摊房间",
            "关联收费项类型",
            "关联收费项",
            "关联收费标准",
            "仪表类型",
            "公摊仪表",
            "不足月规则",
            "计费面积",
            "预期公摊户数/面积",
            "系数阶梯参数",
        )
        missing = [name for name in required if name not in headers]
        if missing:
            raise ValueError(f"Excel 公摊方案专项缺少列：{missing}")

        def value(row: int, name: str) -> str:
            return str(worksheet.cell(row, headers[name]).value or "").strip()

        cases: list[PublicShareSchemeCase] = []
        for row in range(2, worksheet.max_row + 1):
            case_id = value(row, "用例编号")
            if not case_id.startswith("YSF-PUBLIC-SHARE-METER-"):
                continue
            name = value(row, "方案名称")
            is_regression = name.startswith("AT-")
            if is_regression is not regression:
                continue
            rooms = tuple(
                part.strip()
                for part in value(row, "公摊房间").replace(",", "、").split("、")
                if part.strip()
            )
            if len(rooms) != 2:
                raise ValueError(f"用例 {case_id} 的公摊房间必须恰好为两间：{rooms}")
            tiers_value = value(row, "系数阶梯参数")
            tiers = ast.literal_eval(tiers_value) if tiers_value else None
            cases.append(
                PublicShareSchemeCase(
                    case_id=case_id,
                    name=name,
                    method=value(row, "公摊方式"),
                    rooms=(rooms[0], rooms[1]),
                    charge_type=value(row, "关联收费项类型"),
                    charge_item=value(row, "关联收费项"),
                    charge_standard=value(row, "关联收费标准"),
                    instrument_type=value(row, "仪表类型"),
                    instrument_name=value(row, "公摊仪表"),
                    incomplete_month_rule=value(row, "不足月规则"),
                    billing_area=value(row, "计费面积") or None,
                    expected_area_total=value(row, "预期公摊户数/面积") or None,
                    household_count="2",
                    floor_tiers=tiers,
                )
            )
        if len(cases) != 16:
            raise ValueError(
                f"Excel 中仪表公摊{'回归' if regression else '初始化'}用例应为 16 条，"
                f"实际 {len(cases)} 条"
            )
        return tuple(cases)
    finally:
        workbook.close()
