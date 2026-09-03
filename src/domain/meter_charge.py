from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


MONEY = Decimal("0.01")
PARAMETER_PATTERN = re.compile(
    r"(?:^|;)(单价|系数|用量阶梯|楼层阶梯|累计用量阶梯|合并客户所有房间用量)=(.*?)(?=;(?:单价|系数|用量阶梯|楼层阶梯|累计用量阶梯|合并客户所有房间用量)=|$)"
)


@dataclass(frozen=True, slots=True)
class MeterReadingBasis:
    """One billing period's meter readings and usage.

    ``period_usage`` is the imported monthly usage. ``cumulative_usage`` is
    the current reading and is used only by formulas whose tier is explicitly
    annual or cumulative.
    """

    period_usage: Decimal
    previous_reading: Decimal
    current_reading: Decimal
    cumulative_usage: Decimal
    floor: int = 1


def calculate_meter_amount(
    formula: str,
    calculation_parameters: str,
    basis: MeterReadingBasis,
) -> Decimal:
    params = _parse_parameters(calculation_parameters)
    usage = basis.period_usage

    if formula == "仪表无阶梯（固定单价*用量）":
        amount = _decimal(params, "单价") * usage
    elif formula == "仪表多阶梯多单价（阶梯单价*用量 ；年清用量）":
        amount = _progressive_tier_amount(
            params, "用量阶梯", basis.previous_reading, basis.current_reading
        )
    elif formula == "仪表无阶梯（固定单价*用量*系数）":
        amount = _decimal(params, "单价") * usage * _decimal(params, "系数")
    elif formula == "仪表多阶梯多系数（固定单价*用量*阶梯系数）":
        amount = _decimal(params, "单价") * usage * _tier_value(
            params, "楼层阶梯", Decimal(basis.floor)
        )
    elif formula == "仪表累计用量计费（累计用量对应单价*用量）":
        amount = _tier_value(params, "累计用量阶梯", basis.cumulative_usage) * usage
    elif formula == "仪表多阶梯多单价（阶梯单价*用量 ；月清用量）":
        amount = _progressive_tier_amount(
            params, "用量阶梯", Decimal("0"), usage
        )
    else:
        raise ValueError(f"尚未实现仪表计费公式：{formula!r}")
    return amount.quantize(MONEY, rounding=ROUND_HALF_UP)


def _parse_parameters(text: str) -> dict[str, str]:
    return {
        name: value.strip()
        for name, value in PARAMETER_PATTERN.findall(text.replace("\n", ";"))
    }


def _decimal(params: dict[str, str], name: str) -> Decimal:
    value = params.get(name, "").strip()
    if not value:
        raise ValueError(f"计算参数缺少 {name!r}。")
    return Decimal(value)


def _tier_value(params: dict[str, str], name: str, usage: Decimal) -> Decimal:
    text = params.get(name, "").strip()
    if not text:
        raise ValueError(f"计算参数缺少 {name!r}。")
    for item in text.split(";"):
        if ":" not in item:
            continue
        range_text, value_text = (part.strip() for part in item.split(":", 1))
        if _matches_tier(range_text, usage):
            return Decimal(value_text)
    raise ValueError(f"用量 {usage} 未匹配 {name}：{text!r}")


def _progressive_tier_amount(
    params: dict[str, str], name: str, start_usage: Decimal, end_usage: Decimal
) -> Decimal:
    """Calculate only the newly added usage across all intersecting tiers."""
    if end_usage < start_usage:
        raise ValueError(f"累计用量不能倒退：{start_usage} -> {end_usage}")
    text = params.get(name, "").strip()
    if not text:
        raise ValueError(f"计算参数缺少 {name!r}。")

    amount = Decimal("0")
    covered = Decimal("0")
    for item in text.split(";"):
        if ":" not in item:
            continue
        range_text, price_text = (part.strip() for part in item.split(":", 1))
        tier_start, tier_end = _tier_interval(range_text)
        overlap_start = max(start_usage, tier_start)
        overlap_end = end_usage if tier_end is None else min(end_usage, tier_end)
        if overlap_end > overlap_start:
            tier_usage = overlap_end - overlap_start
            amount += tier_usage * Decimal(price_text)
            covered += tier_usage
    if covered != end_usage - start_usage:
        raise ValueError(
            f"新增用量 {start_usage}->{end_usage} 未被 {name} 完整覆盖：{text!r}"
        )
    return amount


def _tier_interval(range_text: str) -> tuple[Decimal, Decimal | None]:
    if "-" in range_text:
        start, end = (Decimal(part.strip()) for part in range_text.split("-", 1))
        return start, end
    if range_text.endswith("及以上"):
        threshold = Decimal(range_text.removesuffix("及以上").strip())
        return threshold, None
    if range_text.endswith("以上"):
        threshold = Decimal(range_text.removesuffix("以上").strip())
        return threshold, None
    raise ValueError(f"不支持的仪表阶梯边界：{range_text!r}")


def _matches_tier(range_text: str, usage: Decimal) -> bool:
    if "-" in range_text:
        start, end = (Decimal(part.strip()) for part in range_text.split("-", 1))
        return start <= usage <= end
    if range_text.endswith("及以上"):
        lower = Decimal(range_text.removesuffix("及以上").strip())
        return usage >= lower
    if range_text.endswith("以上"):
        lower = Decimal(range_text.removesuffix("以上").strip())
        return usage > lower
    raise ValueError(f"不支持的仪表阶梯边界：{range_text!r}")
