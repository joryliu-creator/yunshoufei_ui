from decimal import Decimal

import pytest

from src.domain.meter_charge import MeterReadingBasis, calculate_meter_amount


BASIS = MeterReadingBasis(
    period_usage=Decimal("80"),
    previous_reading=Decimal("280"),
    current_reading=Decimal("360"),
    cumulative_usage=Decimal("360"),
)


@pytest.mark.parametrize(
    ("formula", "parameters", "expected"),
    [
        ("仪表无阶梯（固定单价*用量）", "单价=2", "160.00"),
        (
            "仪表多阶梯多单价（阶梯单价*用量 ；年清用量）",
            "用量阶梯=0-10:1.5;10以上:2",
            "160.00",
        ),
        ("仪表无阶梯（固定单价*用量*系数）", "单价=3;系数=2", "480.00"),
        (
            "仪表多阶梯多系数（固定单价*用量*阶梯系数）",
            "单价=2;楼层阶梯=1-10:2;11及以上:3",
            "320.00",
        ),
        (
            "仪表累计用量计费（累计用量对应单价*用量）",
            "累计用量阶梯=0-10:1.5;10以上:2;合并客户所有房间用量=开启",
            "160.00",
        ),
        (
            "仪表多阶梯多单价（阶梯单价*用量 ；月清用量）",
            "用量阶梯=0-10:1.5;10以上:2",
            "155.00",
        ),
    ],
)
def test_meter_amounts_from_august_import(
    formula: str, parameters: str, expected: str
) -> None:
    assert calculate_meter_amount(formula, parameters, BASIS) == Decimal(expected)


def test_annual_tier_pricing_only_charges_new_usage_in_each_crossed_tier() -> None:
    basis = MeterReadingBasis(
        period_usage=Decimal("800"),
        previous_reading=Decimal("2500"),
        current_reading=Decimal("3300"),
        cumulative_usage=Decimal("3300"),
    )

    assert calculate_meter_amount(
        "仪表多阶梯多单价（阶梯单价*用量 ；年清用量）",
        "用量阶梯=0-1000:1.0;1000-3000:2.0;3000以上:3.0",
        basis,
    ) == Decimal("1900.00")


def test_monthly_tier_pricing_restarts_from_zero_each_month() -> None:
    basis = MeterReadingBasis(
        period_usage=Decimal("325"),
        previous_reading=Decimal("0"),
        current_reading=Decimal("325"),
        cumulative_usage=Decimal("325"),
    )

    assert calculate_meter_amount(
        "仪表多阶梯多单价（阶梯单价*用量 ；月清用量）",
        "用量阶梯=0-100:1.0;100-300:2.0;300以上:3.0",
        basis,
    ) == Decimal("575.00")


def test_multi_coefficient_formula_uses_room_floor_not_meter_usage() -> None:
    high_floor_basis = MeterReadingBasis(
        period_usage=Decimal("80"),
        previous_reading=Decimal("280"),
        current_reading=Decimal("360"),
        cumulative_usage=Decimal("360"),
        floor=11,
    )

    assert calculate_meter_amount(
        "仪表多阶梯多系数（固定单价*用量*阶梯系数）",
        "单价=2;楼层阶梯=1-10:2;11及以上:3",
        high_floor_basis,
    ) == Decimal("480.00")
