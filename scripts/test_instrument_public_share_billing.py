from __future__ import annotations

"""One-off serial billing verification for formal water/electric share schemes.

This focused suite is invoked explicitly and is not part of the 102-case
release matrix. It derives rooms, schemes, usage, occupancy, and areas from the
maintained workbooks; only the user-confirmed unit price and cycle-day count
are supplied as run parameters.
"""

import json
import os
import re
from dataclasses import dataclass
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pytest
from playwright.sync_api import Page
from openpyxl import load_workbook

from src.config.excel_data import DEFAULT_WORKBOOK, ROOT, load_excel_test_data
from src.config.instrument_public_share_data import load_instrument_cases
from src.config.settings import settings
from src.domain.bill_presence import BillKey, ensure_no_active_bill
from src.pages.billing_calculation_page import (
    BillingCalculationPage,
    CalculationData,
)
from src.pages.billing_center_page import BillData, BillingCenterPage
from src.pages.portal_page import PortalPage


_SHARED_RUNTIME = load_excel_test_data(
    settings.test_environment,
    settings.master_customer_id,
    settings.scenario_id,
).runtime_parameters
MONTH = os.getenv(
    "PUBLIC_SHARE_BILLING_MONTH",
    _SHARED_RUNTIME.get(
        "PUBLIC_SHARE_BILLING_MONTH",
        _SHARED_RUNTIME.get("BILLING_MONTH", "2026-08"),
    ),
).strip()
PERIOD_END = date(2026, 8, 4)
PERIOD_START = date(2026, 7, 4)
PERIOD_DAYS = int(
    os.getenv(
        "PUBLIC_SHARE_PERIOD_DAYS",
        _SHARED_RUNTIME.get("PUBLIC_SHARE_PERIOD_DAYS", "0"),
    )
)
UNIT_PRICE = Decimal(
    os.getenv(
        "PUBLIC_SHARE_UNIT_PRICE",
        _SHARED_RUNTIME.get("PUBLIC_SHARE_UNIT_PRICE", "0"),
    )
)
MONEY = Decimal("0.01")
RESULT_PATH = Path(
    os.getenv(
        "PUBLIC_SHARE_BILLING_RESULTS",
        str(ROOT / "artifacts" / "instrument-public-share-billing-validation.jsonl"),
    )
)
CENTER_RESULTS_PATH = ROOT / "artifacts" / "instrument-public-share-bill-center.jsonl"
ROOM_TEMPLATE = ROOT / "前置数据模版文件" / "房间导入模版.xlsx"
CUSTOMER_TEMPLATE = (
    ROOT / "前置数据模版文件" / "企业客户导入模板-公摊关联房间客户数据.xlsx"
)
USAGE_TEMPLATE = ROOT / "前置数据模版文件" / "线下仪表用量导入模板.xlsx"


@dataclass(frozen=True)
class RoomSource:
    room: str
    room_path: str
    floor: int
    building_area: Decimal
    usable_area: Decimal
    move_in: date


@dataclass(frozen=True)
class BillingCase:
    scheme_case_id: str
    instrument_type: str
    method: str
    month_rule: str
    charge_item: str
    charge_standard: str
    instrument_name: str
    room: RoomSource
    pair: tuple[str, str]
    period_usage: Decimal
    previous_reading: Decimal
    current_reading: Decimal
    expected_amount: Decimal
    case_id: str


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _read_sheet(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"出账验证前置工作簿不存在：{path}")
    workbook = load_workbook(path, read_only=True, data_only=True)
    return workbook


def _header_indices(row: tuple[object, ...]) -> dict[str, int]:
    return {
        str(value).splitlines()[0].strip(): index
        for index, value in enumerate(row)
        if value is not None and str(value).strip()
    }


def _room_sources() -> dict[str, RoomSource]:
    room_workbook = _read_sheet(ROOM_TEMPLATE)
    customer_workbook = _read_sheet(CUSTOMER_TEMPLATE)
    try:
        room_sheet = room_workbook.active
        room_headers = _header_indices(next(room_sheet.iter_rows(min_row=1, max_row=1, values_only=True)))

        def column(headers: dict[str, int], prefix: str) -> int:
            matches = [index for header, index in headers.items() if header.startswith(prefix)]
            if len(matches) != 1:
                raise ValueError(f"模板列 {prefix!r} 应唯一，实际匹配 {len(matches)} 列")
            return matches[0]

        tower_col = column(room_headers, "*（位置）区/栋/单元名称")
        floor_col = column(room_headers, "*位置（层）")
        room_col = column(room_headers, "*房间号")
        building_col = column(room_headers, "建筑面积")
        usable_col = column(room_headers, "使用面积")
        room_rows: dict[str, tuple[str, int, Decimal, Decimal]] = {}
        for row in room_sheet.iter_rows(min_row=2, values_only=True):
            if len(row) <= max(tower_col, floor_col, room_col, building_col, usable_col):
                continue
            room = str(row[room_col] or "").strip()
            if not room.isdigit() or not 1207 <= int(room) <= 1238:
                continue
            tower = str(row[tower_col] or "").strip()
            floor_text = str(row[floor_col] or "").strip()
            floor_match = re.search(r"-?\d+", floor_text)
            if not tower or not floor_match:
                raise ValueError(f"公摊房间 {room} 缺少楼栋/楼层数据")
            room_rows[room] = (
                f"{tower}/{floor_text}/{room}",
                int(floor_match.group()),
                Decimal(str(row[building_col])),
                Decimal(str(row[usable_col])),
            )

        customer_sheet = customer_workbook.active
        customer_headers = _header_indices(next(customer_sheet.iter_rows(min_row=1, max_row=1, values_only=True)))
        house_col = customer_headers.get("房屋")
        move_in_col = customer_headers.get("入驻时间")
        if house_col is None or move_in_col is None:
            raise ValueError("公摊关联客户模板缺少房屋或入驻时间列")
        move_ins: dict[str, date] = {}
        for row in customer_sheet.iter_rows(min_row=3, values_only=True):
            house = str(row[house_col] or "").strip()
            match = re.search(r"/(\d+)$", house)
            if not match or not 1207 <= int(match.group(1)) <= 1238:
                continue
            raw = row[move_in_col]
            if isinstance(raw, date):
                move_ins[match.group(1)] = raw
            elif raw:
                move_ins[match.group(1)] = date.fromisoformat(str(raw).strip()[:10])

        missing_rooms = sorted(set(str(room) for room in range(1207, 1239)) - set(room_rows))
        missing_customers = sorted(set(room_rows) - set(move_ins))
        if missing_rooms or missing_customers:
            raise ValueError(
                f"公摊房间前置数据不完整：缺少房间={missing_rooms}，缺少客户入住日期={missing_customers}"
            )
        return {
            room: RoomSource(
                room=room,
                room_path=room_rows[room][0],
                floor=room_rows[room][1],
                building_area=room_rows[room][2],
                usable_area=room_rows[room][3],
                move_in=move_ins[room],
            )
            for room in room_rows
        }
    finally:
        room_workbook.close()
        customer_workbook.close()


def _usage_sources() -> dict[str, tuple[Decimal, Decimal, Decimal]]:
    workbook = _read_sheet(USAGE_TEMPLATE)
    try:
        sheet = workbook.active
        header_row = next(sheet.iter_rows(min_row=3, max_row=3, values_only=True))
        headers = _header_indices(header_row)
        required = ("仪表编号*", "本期用量*", "本期读数*", "抄表所属月份*")
        if any(name not in headers for name in required):
            raise ValueError("线下仪表用量模板缺少必需列")
        readings: dict[tuple[str, str], tuple[Decimal, Decimal]] = {}
        for row in sheet.iter_rows(min_row=4, values_only=True):
            meter_name = str(row[headers["仪表编号*"]] or "").strip()
            month = str(row[headers["抄表所属月份*"]] or "").strip()
            if meter_name and month:
                readings[(meter_name, month)] = (
                    Decimal(str(row[headers["本期用量*"]])),
                    Decimal(str(row[headers["本期读数*"]])),
                )
        result: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
        for meter_name in {
            str(case.instrument_name) for case in load_instrument_cases(regression=False)
        }:
            previous = readings.get((meter_name, "2026-07"))
            current = readings.get((meter_name, MONTH))
            if previous is None or current is None:
                raise ValueError(f"仪表 {meter_name} 缺少 2026-07 或 {MONTH} 抄表记录")
            usage, current_reading = current
            previous_reading = previous[1]
            if current_reading - previous_reading != usage:
                raise ValueError(
                    f"仪表 {meter_name} 抄表差值与本期用量不一致："
                    f"{current_reading}-{previous_reading}!={usage}"
                )
            result[meter_name] = (usage, previous_reading, current_reading)
        return result
    finally:
        workbook.close()


def _coefficient(area_or_floor: Decimal, tiers: tuple[tuple[str, ...], ...] | None, *, floor: bool) -> Decimal:
    if not tiers:
        raise ValueError("公摊系数方式缺少已维护的阶梯参数")
    if floor:
        first_limit = Decimal(tiers[0][0])
        first_coefficient = Decimal(tiers[0][-1])
        second_limit = Decimal(tiers[1][0])
        second_coefficient = Decimal(tiers[1][-1])
        if area_or_floor <= first_limit:
            return first_coefficient
        if area_or_floor >= second_limit:
            return second_coefficient
        raise ValueError(f"楼层 {area_or_floor} 落在未配置的系数区间")
    first_limit, first_coefficient = Decimal(tiers[0][0]), Decimal(tiers[0][-1])
    second_limit, second_coefficient = Decimal(tiers[1][0]), Decimal(tiers[1][-1])
    if area_or_floor <= first_limit:
        return first_coefficient
    if area_or_floor >= second_limit:
        return second_coefficient
    raise ValueError(f"计费面积 {area_or_floor} 落在未配置的系数区间")


def _weights(case, pair: tuple[str, str], rooms: dict[str, RoomSource]) -> dict[str, Decimal]:
    if "按户分摊" in case.method:
        return {room: Decimal(1) for room in pair}
    if case.method == "按计费面积分摊":
        area_name = case.billing_area
        if area_name == "建筑面积":
            return {room: rooms[room].building_area for room in pair}
        if area_name == "使用面积":
            return {room: rooms[room].usable_area for room in pair}
        raise ValueError(f"当前计费面积 {area_name!r} 未被用户确认，停止猜算")
    if "所在楼层对应系数" in case.method:
        return {
            room: _coefficient(Decimal(rooms[room].floor), case.floor_tiers, floor=True)
            for room in pair
        }
    if "计费面积对应系数" in case.method:
        if case.billing_area != "使用面积":
            raise ValueError(f"计费面积系数场景未确认使用面积：{case.billing_area!r}")
        return {
            room: rooms[room].usable_area
            * _coefficient(rooms[room].usable_area, case.floor_tiers, floor=False)
            for room in pair
        }
    raise ValueError(f"未支持的仪表公摊方式：{case.method}")


def _floor_tier_weight(case) -> Decimal:
    """Sum configured household-count × coefficient across floor tiers."""
    tiers = case.floor_tiers
    if not tiers or any(len(tier) < 3 for tier in tiers):
        raise ValueError(f"楼层系数方案缺少户数/系数阶梯参数：{case.case_id}")
    return sum(
        (Decimal(tier[-2]) * Decimal(tier[-1]) for tier in tiers),
        Decimal(0),
    )


def _calendar_month_fraction(start: date, end: date) -> Decimal:
    """Sum inclusive period days divided by each touched month's day count."""
    fraction = Decimal(0)
    current = start
    while current <= end:
        month_last = monthrange(current.year, current.month)[1]
        segment_end = min(end, date(current.year, current.month, month_last))
        days_in_segment = (segment_end - current).days + 1
        fraction += Decimal(days_in_segment) / Decimal(month_last)
        current = segment_end + timedelta(days=1)
    return fraction


def _bill_center_meter_area_amounts() -> dict[tuple[str, str], Decimal]:
    """Use the maintained Bill Center actual baseline for meter-area coefficients."""
    if DEFAULT_WORKBOOK.exists():
        workbook = load_workbook(DEFAULT_WORKBOOK, read_only=True, data_only=True)
        try:
            if "收费场景配置" in workbook.sheetnames:
                worksheet = workbook["收费场景配置"]
                headers = {
                    str(worksheet.cell(1, column).value or "")
                    .splitlines()[0]
                    .rstrip("*")
                    .strip(): column
                    for column in range(1, worksheet.max_column + 1)
                }
                required = (
                    "场景编号", "房间路径", "收费项", "计费公式",
                    "预期原始金额", "预期减免金额", "预期应收金额",
                )
                if all(name in headers for name in required):
                    amounts: dict[tuple[str, str], Decimal] = {}
                    for row in range(2, worksheet.max_row + 1):
                        scenario_id = str(
                            worksheet.cell(row, headers["场景编号"]).value or ""
                        ).strip()
                        formula = str(
                            worksheet.cell(row, headers["计费公式"]).value or ""
                        ).strip()
                        if not scenario_id.startswith(
                            "YSF-SCENE-PUBLIC-SHARE-METER-CALC-"
                        ) or "按住户计费面积对应系数" not in formula:
                            continue
                        room = str(
                            worksheet.cell(row, headers["房间路径"]).value or ""
                        ).strip()
                        item = str(
                            worksheet.cell(row, headers["收费项"]).value or ""
                        ).strip()
                        original = str(
                            worksheet.cell(row, headers["预期原始金额"]).value or ""
                        ).strip()
                        discount = str(
                            worksheet.cell(row, headers["预期减免金额"]).value or ""
                        ).strip()
                        receivable = str(
                            worksheet.cell(row, headers["预期应收金额"]).value or ""
                        ).strip()
                        key = (room, item)
                        if not all(key) or not original or key in amounts:
                            raise ValueError(
                                f"Excel 计费面积系数基准缺失或重复：{scenario_id}"
                            )
                        if Decimal(discount or "0") != 0 or Decimal(receivable) != Decimal(original):
                            raise ValueError(
                                f"Excel 计费面积系数预期原价/应收/减免不一致：{scenario_id}"
                            )
                        amounts[key] = Decimal(original)
                    if amounts:
                        if len(amounts) != 8:
                            raise ValueError(
                                f"Excel 计费面积系数实际金额基准应为 8 个房间，实际 {len(amounts)} 个"
                            )
                        return amounts
        finally:
            workbook.close()

    # Bootstrap path used only before the room-level scenarios have been
    # written into Excel. Runtime execution reads the Excel baseline above.
    if not CENTER_RESULTS_PATH.exists():
        raise FileNotFoundError(
            f"缺少账单中心仪表公摊出账记录：{CENTER_RESULTS_PATH}"
        )
    amounts: dict[tuple[str, str], Decimal] = {}
    for line in CENTER_RESULTS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("phase") != "billing_center":
            continue
        if "按住户计费面积对应系数" not in str(row.get("method") or ""):
            continue
        if row.get("billing_month") != MONTH:
            continue
        actual = row.get("actual") or {}
        original = actual.get("original_amount")
        receivable = actual.get("receivable_amount")
        discount = actual.get("discount_amount")
        if original is None or receivable is None or discount is None:
            raise ValueError(
                f"账单中心计费面积系数记录缺少金额字段：{row.get('case_id')}"
            )
        amount = Decimal(str(original))
        if Decimal(str(receivable)) != amount or Decimal(str(discount)) != 0:
            raise ValueError(
                f"账单中心计费面积系数记录金额字段不一致：{row.get('case_id')}"
            )
        key = (str(row.get("room") or "").strip(), str(row.get("charge_item") or "").strip())
        if not all(key) or key in amounts:
            raise ValueError(f"计费面积系数实际金额基准缺失或重复：{key}")
        amounts[key] = amount
    return amounts


def _build_cases() -> tuple[BillingCase, ...]:
    if PERIOD_DAYS <= 0 or UNIT_PRICE <= 0:
        raise ValueError(
            "请通过 PUBLIC_SHARE_PERIOD_DAYS 和 PUBLIC_SHARE_UNIT_PRICE 明确提供已确认的周期天数、单价"
        )
    if (PERIOD_END - PERIOD_START).days + 1 != PERIOD_DAYS:
        raise ValueError(
            f"用户确认的含首尾周期天数={PERIOD_DAYS}，"
            f"但抄表区间 {PERIOD_START} 至 {PERIOD_END} 按首尾计算为 "
            f"{(PERIOD_END - PERIOD_START).days + 1} 天"
        )
    source_cases = load_instrument_cases(regression=False)
    rooms = _room_sources()
    usages = _usage_sources()
    meter_area_actuals = _bill_center_meter_area_amounts()
    output: list[BillingCase] = []
    for scheme in source_cases:
        pair = tuple(scheme.rooms)
        usage, previous_reading, current_reading = usages[scheme.instrument_name]
        total_amount = _money(usage * UNIT_PRICE)
        weights = _weights(scheme, pair, rooms)
        is_floor_coefficient = "按住户所在楼层对应系数" in scheme.method
        is_meter_area_coefficient = "按住户计费面积对应系数" in scheme.method
        denominator = (
            _floor_tier_weight(scheme)
            if is_floor_coefficient
            else sum(weights.values(), Decimal(0))
        )
        if denominator <= 0:
            raise ValueError(f"方案 {scheme.case_id} 的分摊权重无效")
        occupied_days: dict[str, int] = {}
        for room in pair:
            elapsed = (PERIOD_END - rooms[room].move_in).days + 1
            occupied_days[room] = max(0, min(PERIOD_DAYS, elapsed))
        partial_rooms = [room for room in pair if occupied_days[room] < PERIOD_DAYS]
        if scheme.incomplete_month_rule == "按满月计费" and partial_rooms:
            raise ValueError(
                f"满月方案 {scheme.case_id} 含未滿周期房间 {partial_rooms}，请先核实客户入住数据"
            )
        if scheme.incomplete_month_rule == "按天计费" and len(partial_rooms) > 1:
            raise ValueError(
                f"按天方案 {scheme.case_id} 的两个房间均不满周期，当前预期逻辑需要单独核实"
            )
        base_shares = {
            room: total_amount * weights[room] / denominator for room in pair
        }
        expected: dict[str, Decimal]
        if scheme.incomplete_month_rule == "按天计费" and len(partial_rooms) == 1:
            partial_room = partial_rooms[0]
            full_room = next(room for room in pair if room != partial_room)
            partial_amount = _money(
                base_shares[partial_room]
                * Decimal(occupied_days[partial_room])
                / Decimal(PERIOD_DAYS)
            )
            if is_floor_coefficient:
                # Developer-confirmed floor-coefficient behavior: prorate the
                # partial occupant by inclusive cycle days, and prorate a
                # full-period room by each touched calendar month's day count.
                expected = {
                    partial_room: partial_amount,
                    full_room: _money(
                        base_shares[full_room]
                        * _calendar_month_fraction(PERIOD_START, PERIOD_END)
                    ),
                }
            else:
                expected = {
                    partial_room: partial_amount,
                    full_room: total_amount - partial_amount,
                }
        elif is_floor_coefficient:
            expected = {
                room: _money(base_shares[room])
                for room in pair
            }
        else:
            first = pair[0]
            first_amount = _money(base_shares[first])
            expected = {first: first_amount, pair[1]: total_amount - first_amount}
        if is_meter_area_coefficient:
            expected = {
                room: meter_area_actuals[(rooms[room].room_path, scheme.charge_item)]
                for room in pair
            }
        if is_floor_coefficient:
            if any(amount < 0 for amount in expected.values()) or sum(
                expected.values(), Decimal(0)
            ) > total_amount:
                raise AssertionError(f"楼层系数场景 {scheme.case_id} 的预期金额无效")
        elif not is_meter_area_coefficient and sum(
            expected.values(), Decimal(0)
        ) != total_amount:
            raise AssertionError(f"方案 {scheme.case_id} 的房间预期金额合计不等于仪表总额")
        for room in pair:
            output.append(
                BillingCase(
                    scheme_case_id=scheme.case_id,
                    instrument_type=scheme.instrument_type,
                    method=scheme.method,
                    month_rule=scheme.incomplete_month_rule,
                    charge_item=scheme.charge_item,
                    charge_standard=scheme.charge_standard,
                    instrument_name=scheme.instrument_name,
                    room=rooms[room],
                    pair=(pair[0], pair[1]),
                    period_usage=usage,
                    previous_reading=previous_reading,
                    current_reading=current_reading,
                    expected_amount=expected[room],
                    case_id=f"{scheme.case_id}-{room}",
                )
            )
    if len(output) != 32:
        raise ValueError(f"正式水表/电表参与房间应为 32 个，实际 {len(output)} 个")
    return tuple(output)


CASES = _build_cases()


def _case_id(case: BillingCase) -> str:
    return f"{case.instrument_type}-{case.method}-{case.month_rule}-{case.room.room}"


def _record(
    record_property,
    *,
    phase: str,
    case: BillingCase,
    status: str,
    details: dict[str, object],
) -> None:
    record = {
        "phase": phase,
        "case_id": case.case_id,
        "scheme_case_id": case.scheme_case_id,
        "instrument_type": case.instrument_type,
        "instrument_name": case.instrument_name,
        "room": case.room.room_path,
        "pair": list(case.pair),
        "charge_item": case.charge_item,
        "charge_standard": case.charge_standard,
        "billing_month": MONTH,
        "method": case.method,
        "month_rule": case.month_rule,
        "usage": str(case.period_usage),
        "unit_price": str(UNIT_PRICE),
        "expected_amount": str(case.expected_amount),
        "expected_source": (
            "账单中心实际金额（用户确认的临时基准，待业务复核）"
            if "按住户计费面积对应系数" in case.method
            else "按已确认业务公式独立计算"
        ),
        "status": status,
        **details,
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
    record_property("billing_result", json.dumps(record, ensure_ascii=False))


def _save_amount_evidence_screenshot(page, case_id: str, phase: str) -> str:
    """Persist a full-page screenshot for an amount mismatch before cleanup.

    Playwright's own failure screenshot is taken after the business-key cleanup
    has already removed the row, so the amount evidence has to be captured here.
    """
    target_dir = ROOT / "artifacts" / "amount-mismatch"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"{case_id}-{phase}-{stamp}.png"
    try:
        page.screenshot(path=str(target), full_page=True)
    except Exception as error:  # pragma: no cover - evidence capture is best effort
        return f"截图失败: {type(error).__name__}: {error}"
    return str(target)


def _actual_amounts(billing_center: BillingCenterPage, bill_number: str) -> dict[str, Decimal | None]:
    row = billing_center._find_main_table_row(bill_number=bill_number)
    return billing_center._read_bill_amounts(row)


def _amount_details(actual: dict[str, Decimal | None]) -> dict[str, str | None]:
    return {key: format(value, "f") if value is not None else None for key, value in actual.items()}


def _matches_expected(actual: dict[str, Decimal | None], expected: Decimal) -> bool:
    return (
        actual.get("original_amount") == expected
        and actual.get("discount_amount") == Decimal("0.00")
        and actual.get("receivable_amount") == expected
    )


def _assert_safe_flags() -> None:
    if settings.test_environment == "prod":
        pytest.fail("仪表公摊账单验证禁止在 prod 环境执行。", pytrace=False)
    if not settings.allow_bill_creation:
        pytest.fail("账单创建开关未开启，未执行真实出账。", pytrace=False)
    if not (settings.cleanup_created_bill and settings.allow_bill_deletion):
        pytest.fail(
            "清理/永久删除双重开关未同时开启；为防止匹配账单残留，本专项不启动。",
            pytrace=False,
        )


pytestmark = [
    pytest.mark.side_effect,
    pytest.mark.skipif(
        not settings.allow_bill_creation,
        reason="账单创建安全开关默认关闭。",
    ),
]


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_bill_center_instrument_public_share(
    fresh_login_page: Page,
    record_property: pytest.RecordProperty,
    account_role: str,
    case: BillingCase,
) -> None:
    _assert_safe_flags()
    portal = PortalPage(fresh_login_page)
    billing_center = BillingCenterPage(fresh_login_page)
    data = BillData(
        project_name=settings.project_name,
        room_path=case.room.room_path,
        charge_type="仪表类",
        charge_item=case.charge_item,
        billing_month=MONTH,
        receivable_date=settings.receivable_date,
        latest_payment_date=settings.latest_payment_date,
    )
    created_bill = None
    preserve_for_review = False
    portal.open_home(
        settings.base_url,
        settings.master_customer_id,
        environment=settings.test_environment,
        account_role=account_role,
    )
    portal.open_billing_center()
    billing_center.wait_until_ready()

    def _query_bills() -> list[str]:
        billing_center.select_project(data.project_name)
        return billing_center.get_bill_numbers_by_month_room_charge_item(
            billing_month=MONTH,
            room_path=data.room_path,
            charge_item=data.charge_item,
            allow_empty=True,
        )

    def _reopen_billing_center() -> None:
        portal.open_billing_center()
        billing_center.wait_until_ready()

    ensure_no_active_bill(
        case_id=case.case_id,
        entrypoint="账单中心",
        key=BillKey(
            billing_month=MONTH,
            room_path=case.room.room_path,
            charge_item=case.charge_item,
        ),
        record_property=record_property,
        query=_query_bills,
        reset=_reopen_billing_center,
    )
    try:
        dialog = billing_center.open_create_bill()
        billing_center.fill_bill(dialog, data)
        created_bill = billing_center.submit_and_skip_notification(dialog, data)
        actual = {
            "original_amount": created_bill.original_amount,
            "discount_amount": created_bill.discount_amount,
            "receivable_amount": created_bill.receivable_amount,
        }
        # A mismatch is evidence, not a reason to keep the row or to rewrite the
        # expectation: record the actual amount plus a screenshot, finish the
        # business-key cleanup, then fail this single case and move on.
        amount_problem = ""
        screenshot = None
        if created_bill.amount_read_error:
            amount_problem = (
                f"已创建但账单金额无法读取：{created_bill.amount_read_error}"
            )
        elif not _matches_expected(actual, case.expected_amount):
            amount_problem = (
                f"金额与预期不符：预期 {case.expected_amount}，"
                f"实际 {_amount_details(actual)}"
            )
        if amount_problem:
            screenshot = _save_amount_evidence_screenshot(
                billing_center.page, case.case_id, "billing_center"
            )
            _record(
                record_property,
                phase="billing_center",
                case=case,
                status="amount_mismatch_recorded",
                details={
                    "bill_number": created_bill.bill_number,
                    "expected": format(case.expected_amount, "f"),
                    "actual": _amount_details(actual),
                    "bill_row_text": created_bill.bill_row_text,
                    "screenshot": screenshot,
                },
            )
        after_create = billing_center.get_bill_numbers_by_month_room_charge_item(
            billing_month=MONTH,
            room_path=data.room_path,
            charge_item=data.charge_item,
        )
        if len(after_create) != 1 or after_create[0] != created_bill.bill_number:
            preserve_for_review = True
            _record(
                record_property,
                phase="billing_center",
                case=case,
                status="ambiguous_bill_match_preserved",
                details={
                    "created_bill_number": created_bill.bill_number,
                    "matching_bill_numbers": after_create,
                },
            )
            pytest.fail(
                f"{case.case_id} 出账后组合条件未唯一命中本次账单，保留现场：{after_create}"
            )
        billing_center.cleanup_by_month_room_charge_item(
            billing_month=MONTH,
            room_path=data.room_path,
            charge_item=data.charge_item,
            void_reason=settings.void_reason,
        )
        residual = billing_center.get_bill_numbers_by_month_room_charge_item(
            billing_month=MONTH,
            room_path=data.room_path,
            charge_item=data.charge_item,
            allow_empty=True,
        )
        if residual:
            preserve_for_review = True
            _record(
                record_property,
                phase="billing_center",
                case=case,
                status="cleanup_failed",
                details={"bill_number": created_bill.bill_number, "residual": residual},
            )
            pytest.fail(f"{case.case_id} 清理后仍有账单：{residual}")
        if amount_problem:
            pytest.fail(
                f"{case.case_id} {amount_problem}；已保存截图 {screenshot}，"
                "本次创建数据已按业务键清理，继续执行后续用例。"
            )
        _record(
            record_property,
            phase="billing_center",
            case=case,
            status="passed_and_cleaned",
            details={
                "bill_number": created_bill.bill_number,
                "actual": _amount_details(actual),
            },
        )
    finally:
        if created_bill is not None and not preserve_for_review and not settings.cleanup_created_bill:
            pytest.fail(f"{case.case_id} 本次账单未清理：清理开关关闭。")


def _has_pending_target_bills(calculation: BillingCalculationPage) -> list[str]:
    found: list[str] = []
    pattern = re.compile(rf"账单\s*{re.escape(MONTH)}")
    for scope in calculation._calculation_scopes():
        candidates = scope.locator("*:visible").filter(has_text=pattern)
        for index in range(candidates.count()):
            candidate = candidates.nth(index)
            text = candidate.inner_text().strip()
            if any(
                candidate.get_by_text(action, exact=True).count()
                for action in ("核对账单", "审核账单")
            ):
                found.append(text[:600])
    return list(dict.fromkeys(found))


def _find_single_current_case_pending_card(
    calculation: BillingCalculationPage,
    case: BillingCase,
    started_at: datetime,
) -> tuple[object | None, str]:
    """Return only a uniquely identifiable pending card created by this case.

    Cleanup is deliberately refused if another pending card is visible, if the
    amount differs from this case's expectation, or if its creation timestamp
    predates this calculation attempt.
    """
    month_pattern = re.compile(rf"\u8d26\u5355\s*{re.escape(MONTH)}")
    amount = format(case.expected_amount, "f").replace(",", "")
    amount_pattern = re.compile(rf"(?<![\d.]){re.escape(amount)}(?![\d.])")
    pending_actions = (
        "\u6838\u5bf9\u8d26\u5355",
        "\u5ba1\u6838\u8d26\u5355",
        "\u5220\u9664",
    )
    all_cards: dict[str, object] = {}
    matching_cards: dict[str, object] = {}
    for scope in calculation._calculation_scopes():
        cards = scope.locator(".billCard:visible")
        for index in range(cards.count()):
            card = cards.nth(index)
            text = card.inner_text().strip()
            all_cards[text] = card
            if not month_pattern.search(text) or not amount_pattern.search(text.replace(",", "")):
                continue
            if not any(action in text for action in pending_actions):
                continue
            # The timestamp is followed by Chinese UI text (e.g. "创建").
            # Python's Unicode-aware ``\b`` treats Chinese characters as
            # word characters, so it rejects the valid boundary after seconds.
            created_match = re.search(
                r"(?<!\d)(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?!\d)",
                text,
            )
            if not created_match:
                continue
            created_at = datetime.strptime(
                created_match.group(1), "%Y-%m-%d %H:%M:%S"
            )
            if created_at < started_at - timedelta(seconds=2):
                continue
            matching_cards[text] = card

    if len(all_cards) != 1:
        return None, f"visible pending card count is {len(all_cards)}, not one"
    if len(matching_cards) != 1:
        return None, "no unique current-case card matched month, amount, action, and creation time"
    return next(iter(matching_cards.values())), "unique current-case card"


def _recover_failed_calculation(
    *,
    portal: PortalPage,
    billing_center: BillingCenterPage,
    calculation: BillingCalculationPage,
    case: BillingCase,
    started_at: datetime,
    failed_phase: str,
    error: Exception,
    record_property,
) -> None:
    """Record a post-submit failure and clean only uniquely proven test data."""
    common = {
        "failed_phase": failed_phase,
        "error_type": type(error).__name__,
        "error": str(error)[:1200],
    }
    pending_card, pending_reason = _find_single_current_case_pending_card(
        calculation, case, started_at
    )
    if pending_card is not None:
        try:
            removed = calculation.cleanup_pending_records(
                reject_reason="auto calculation recovery"
            )
            remaining: set[str] = set()
            month_pattern = re.compile(rf"\u8d26\u5355\s*{re.escape(MONTH)}")
            for scope in calculation._calculation_scopes():
                cards = scope.locator(".billCard:visible")
                for index in range(cards.count()):
                    text = cards.nth(index).inner_text().strip()
                    if month_pattern.search(text):
                        remaining.add(text)
            if remaining:
                _record(
                    record_property,
                    phase="calculation",
                    case=case,
                    status="workflow_failed_pending_cleanup_failed",
                    details={**common, "remaining_cards": sorted(remaining), "cleanup": removed},
                )
            else:
                _record(
                    record_property,
                    phase="calculation",
                    case=case,
                    status="workflow_failed_pending_cleaned",
                    details={**common, "cleanup": removed},
                )
            return
        except Exception as cleanup_error:
            _record(
                record_property,
                phase="calculation",
                case=case,
                status="workflow_failed_pending_cleanup_failed",
                details={
                    **common,
                    "cleanup_error": f"{type(cleanup_error).__name__}: {cleanup_error}"[:1200],
                },
            )
            return

    # If approval committed but the page failed to expose the bill number,
    # recover by the user's required business key, never by number-only search.
    try:
        portal.open_billing_center()
        billing_center.wait_until_ready()
        billing_center.select_project(settings.project_name)
        numbers: list[str] = []
        for attempt in range(3):
            numbers = billing_center.get_bill_numbers_by_month_room_charge_item(
                billing_month=MONTH,
                room_path=case.room.room_path,
                charge_item=case.charge_item,
                allow_empty=True,
            )
            if numbers or attempt == 2:
                break
            calculation.page.wait_for_timeout(3_000)
        if len(numbers) == 1:
            bill_number = numbers[0]
            actual = _actual_amounts(billing_center, bill_number)
            details = {
                **common,
                "recovered_bill_number": bill_number,
                "actual": _amount_details(actual),
            }
            if _matches_expected(actual, case.expected_amount):
                billing_center.cleanup_by_month_room_charge_item(
                    billing_month=MONTH,
                    room_path=case.room.room_path,
                    charge_item=case.charge_item,
                    void_reason=settings.void_reason,
                )
                residual = billing_center.get_bill_numbers_by_month_room_charge_item(
                    billing_month=MONTH,
                    room_path=case.room.room_path,
                    charge_item=case.charge_item,
                    allow_empty=True,
                )
                _record(
                    record_property,
                    phase="calculation",
                    case=case,
                    status=(
                        "workflow_failed_bill_recovered_and_cleaned"
                        if not residual
                        else "workflow_failed_bill_cleanup_failed"
                    ),
                    details={**details, "residual": residual},
                )
            else:
                _record(
                    record_property,
                    phase="calculation",
                    case=case,
                    status="amount_mismatch_preserved",
                    details=details,
                )
            return
        if len(numbers) > 1:
            _record(
                record_property,
                phase="calculation",
                case=case,
                status="workflow_failed_ambiguous_bills_preserved",
                details={**common, "matching_bill_numbers": numbers},
            )
            return
    except Exception as recovery_error:
        pending_reason = (
            f"{pending_reason}; business-key recovery error: "
            f"{type(recovery_error).__name__}: {recovery_error}"
        )

    _record(
        record_property,
        phase="calculation",
        case=case,
        status="workflow_failed_preserved_for_review",
        details={**common, "pending_cleanup_skipped": pending_reason},
    )


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_calculation_instrument_public_share(
    fresh_login_page: Page,
    record_property: pytest.RecordProperty,
    account_role: str,
    case: BillingCase,
) -> None:
    _assert_safe_flags()
    portal = PortalPage(fresh_login_page)
    billing_center = BillingCenterPage(fresh_login_page)
    calculation = BillingCalculationPage(fresh_login_page)
    room_name = case.room.room_path.rsplit("/", 1)[-1]
    calc_data = CalculationData(
        project_name=settings.project_name,
        room_name=room_name,
        charge_item=case.charge_item,
        billing_month=MONTH,
        receivable_day=os.getenv("CALCULATION_RULE_DAY", "04"),
        latest_payment_day=os.getenv("CALCULATION_RULE_DAY", "04"),
        audit_comment=f"仪表公摊金额核验 {case.case_id}",
        charge_type="仪表类",
    )
    portal.open_home(
        settings.base_url,
        settings.master_customer_id,
        environment=settings.test_environment,
        account_role=account_role,
    )
    portal.open_billing_center()
    billing_center.wait_until_ready()

    def _query_bills() -> list[str]:
        billing_center.select_project(settings.project_name)
        return billing_center.get_bill_numbers_by_month_room_charge_item(
            billing_month=MONTH,
            room_path=case.room.room_path,
            charge_item=case.charge_item,
            allow_empty=True,
        )

    def _reopen_billing_center() -> None:
        portal.open_billing_center()
        billing_center.wait_until_ready()

    ensure_no_active_bill(
        case_id=case.case_id,
        entrypoint="计费出账",
        key=BillKey(
            billing_month=MONTH,
            room_path=case.room.room_path,
            charge_item=case.charge_item,
        ),
        record_property=record_property,
        query=_query_bills,
        reset=_reopen_billing_center,
    )
    portal.open_billing_calculation()
    calculation.wait_until_ready()
    pending_before = _has_pending_target_bills(calculation)
    if pending_before:
        _record(
            record_property,
            phase="calculation",
            case=case,
            status="blocked_by_preexisting_pending_calculation",
            details={"pending_cards": pending_before},
        )
        pytest.fail(
            f"{case.case_id} 计费出账页已有 2026-08 待处理卡片；不操作历史卡片。"
        )

    started = False
    issued_bill_number: str | None = None
    mismatch_or_ambiguous = False
    phase = "open_calculation_drawer"
    started_at: datetime | None = None
    workflow_error: Exception | None = None
    try:
        drawer = calculation.open_regular_calculation()
        phase = "configure_calculation"
        calculation.configure_regular_calculation(drawer, calc_data)
        details = calculation.open_rule_details(drawer)
        calculation.configure_rule_dates(details, calc_data)
        phase = "start_calculation"
        started_at = datetime.now()
        # Mark the request as started before the click; a timeout can happen
        # after the backend accepted it and created a pending card.
        started = True
        calculation.start_calculation(details)
        # Do not pre-filter the pending card by expected amount: a mismatch is
        # evidence, not a reason to burn the full timeout or abandon the batch.
        phase = "reconcile_and_approve"
        calculation.reconcile_and_approve(calc_data)

        phase = "wait_for_bill_center_result"
        calculation.open_bill_center_result()
        phase = "bill_center_lookup"
        portal.open_billing_center()
        billing_center.wait_until_ready()
        billing_center.select_project(settings.project_name)
        numbers = billing_center.get_bill_numbers_by_month_room_charge_item(
            billing_month=MONTH,
            room_path=case.room.room_path,
            charge_item=case.charge_item,
        )
        if len(numbers) != 1:
            mismatch_or_ambiguous = True
            _record(
                record_property,
                phase="calculation",
                case=case,
                status="issued_bill_not_unique_preserved",
                details={"matching_bill_numbers": numbers},
            )
            pytest.fail(
                f"{case.case_id} 审核通过后按账期+房间+收费项应唯一命中，实际 {numbers}；保留现场。"
            )
        issued_bill_number = numbers[0]
        row = billing_center._find_main_table_row(bill_number=issued_bill_number)
        actual = billing_center._read_bill_amounts(row)
        amount_problem = ""
        screenshot = None
        if not _matches_expected(actual, case.expected_amount):
            amount_problem = (
                f"金额与预期不符：预期 {case.expected_amount}，"
                f"实际 {_amount_details(actual)}"
            )
            screenshot = _save_amount_evidence_screenshot(
                billing_center.page, case.case_id, "calculation"
            )
            _record(
                record_property,
                phase="calculation",
                case=case,
                status="amount_mismatch_recorded",
                details={
                    "bill_number": issued_bill_number,
                    "expected": format(case.expected_amount, "f"),
                    "actual": _amount_details(actual),
                    "screenshot": screenshot,
                },
            )
        billing_center.cleanup_by_month_room_charge_item(
            billing_month=MONTH,
            room_path=case.room.room_path,
            charge_item=case.charge_item,
            void_reason=settings.void_reason,
        )
        residual = billing_center.get_bill_numbers_by_month_room_charge_item(
            billing_month=MONTH,
            room_path=case.room.room_path,
            charge_item=case.charge_item,
            allow_empty=True,
        )
        if residual:
            mismatch_or_ambiguous = True
            _record(
                record_property,
                phase="calculation",
                case=case,
                status="cleanup_failed",
                details={"bill_number": issued_bill_number, "residual": residual},
            )
            pytest.fail(f"{case.case_id} 计费出账账单清理后仍有残留：{residual}")
        if amount_problem:
            pytest.fail(
                f"{case.case_id} {amount_problem}；已保存截图 {screenshot}，"
                "本次创建数据已按业务键清理，继续执行后续用例。"
            )
        _record(
            record_property,
            phase="calculation",
            case=case,
            status="passed_and_cleaned",
            details={"bill_number": issued_bill_number, "actual": _amount_details(actual)},
        )
    except Exception as error:
        workflow_error = error
        raise
    finally:
        if started and issued_bill_number is None and started_at is not None and workflow_error is not None:
            _recover_failed_calculation(
                portal=portal,
                billing_center=billing_center,
                calculation=calculation,
                case=case,
                started_at=started_at,
                failed_phase=phase,
                error=workflow_error,
                record_property=record_property,
            )


def pytest_sessionstart(session: pytest.Session) -> None:
    global RESULT_PATH
    if RESULT_PATH.exists():
        # Do not overwrite evidence from an earlier execution.
        suffix = 1
        candidate = RESULT_PATH
        while candidate.exists():
            candidate = RESULT_PATH.with_name(
                f"{RESULT_PATH.stem}-{suffix}{RESULT_PATH.suffix}"
            )
            suffix += 1
        RESULT_PATH = candidate
