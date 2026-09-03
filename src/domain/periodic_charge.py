from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


MONEY = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class PeriodicRoomBasis:
    building_area: Decimal
    usable_area: Decimal
    fee_area: Decimal
    floor: int
    months: Decimal = Decimal("1")

    def area(self, area_type: str) -> Decimal:
        mapping = {
            "建筑面积": self.building_area,
            "使用面积": self.usable_area,
            "收费面积": self.fee_area,
        }
        if area_type not in mapping:
            raise ValueError(f"不支持的计费面积类型：{area_type!r}")
        return mapping[area_type]


def calculate_periodic_amount(
    formula: str,
    area_type: str,
    calculation_parameters: str,
    basis: PeriodicRoomBasis,
) -> Decimal:
    params = _parse_parameters(calculation_parameters)
    months = basis.months

    if formula == "周期常用公式（月单价*计费面积*月数）":
        amount = _decimal(params, "月单价") * basis.area(area_type) * months
    elif formula == "周期固定金额（月固定金额*月数）":
        amount = _decimal(params, "月固定金额") * months
    elif formula == "周期阶梯计费（对应月单价*计费面积*月数）":
        unit_price = _floor_tier_price(params["楼层阶梯"], basis.floor)
        amount = unit_price * basis.area(area_type) * months
    elif formula == "周期系数公式（月单价*计费面积*月数*系数）":
        amount = (
            _decimal(params, "月单价")
            * basis.area(area_type)
            * months
            * _decimal(params, "系数")
        )
    elif formula == "周期系数公式（月固定金额*月数*系数）":
        amount = (
            _decimal(params, "月固定金额")
            * months
            * _decimal(params, "系数")
        )
    else:
        raise ValueError(f"尚未实现周期计费公式：{formula!r}")
    return amount.quantize(MONEY, rounding=ROUND_HALF_UP)


def _parse_parameters(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    # Excel calculation parameters are commonly entered one key per line,
    # while older rows use semicolons.  Treat both separators identically.
    for part in text.replace("\r\n", "\n").replace("\n", ";").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _decimal(params: dict[str, str], name: str) -> Decimal:
    if name not in params or not params[name]:
        raise ValueError(f"计算参数缺少 {name!r}。")
    return Decimal(params[name])


def _floor_tier_price(text: str, floor: int) -> Decimal:
    for tier in text.split(";"):
        range_text, price_text = tier.split(":", 1)
        start_text, end_text = range_text.split("-", 1)
        if int(start_text) <= floor <= int(end_text):
            return Decimal(price_text)
    raise ValueError(f"楼层 {floor} 未匹配任何阶梯：{text!r}")
