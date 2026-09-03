from decimal import Decimal

import pytest

from src.domain.periodic_charge import (
    PeriodicRoomBasis,
    calculate_periodic_amount,
)


BASIS = PeriodicRoomBasis(
    building_area=Decimal("300.12"),
    usable_area=Decimal("280.01"),
    fee_area=Decimal("260.00"),
    floor=1,
)


@pytest.mark.parametrize(
    ("formula", "area", "parameters", "expected"),
    [
        ("周期常用公式（月单价*计费面积*月数）", "建筑面积", "月单价=10", "3001.20"),
        ("周期常用公式（月单价*计费面积*月数）", "使用面积", "月单价=10", "2800.10"),
        ("周期常用公式（月单价*计费面积*月数）", "收费面积", "月单价=10", "2600.00"),
        ("周期固定金额（月固定金额*月数）", "", "月固定金额=10", "10.00"),
        ("周期阶梯计费（对应月单价*计费面积*月数）", "建筑面积", "楼层阶梯=1-10:2;11-20:3", "600.24"),
        ("周期阶梯计费（对应月单价*计费面积*月数）", "使用面积", "楼层阶梯=1-10:2;11-20:3", "560.02"),
        ("周期阶梯计费（对应月单价*计费面积*月数）", "收费面积", "楼层阶梯=1-10:2;11-20:3", "520.00"),
        ("周期系数公式（月单价*计费面积*月数*系数）", "建筑面积", "月单价=3;系数=2", "1800.72"),
        ("周期系数公式（月单价*计费面积*月数*系数）", "使用面积", "月单价=3;系数=2", "1680.06"),
        ("周期系数公式（月单价*计费面积*月数*系数）", "收费面积", "月单价=3;系数=2", "1560.00"),
        ("周期系数公式（月固定金额*月数*系数）", "", "月固定金额=3;系数=2", "6.00"),
    ],
)
def test_periodic_full_month_amounts(
    formula: str, area: str, parameters: str, expected: str
) -> None:
    assert calculate_periodic_amount(formula, area, parameters, BASIS) == Decimal(expected)
