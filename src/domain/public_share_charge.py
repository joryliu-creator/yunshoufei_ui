from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PublicShareBillCase:
    """One room-level assertion for a periodic public-share bill."""

    room: str
    pair: tuple[str, str]
    scheme_key: str
    method_key: str
    expected_amount: Decimal
    calculation_parameters: str


# These are the ten rooms covered by the five formal initialization schemes.
# Each room is an independent assertion: the pair is only the allocation
# context, not a reason to assert the same amount for both rooms.
PUBLIC_SHARE_BILL_CASES: tuple[PublicShareBillCase, ...] = (
    PublicShareBillCase(
        room="1201",
        pair=("1201", "1202"),
        scheme_key="RATIO-1201-1202",
        method_key="RATIO",
        expected_amount=Decimal("400.00"),
        calculation_parameters="PUBLIC_SHARE_TOTAL=1000\nALLOCATION_RATIO=40%\nMONTHS=1",
    ),
    PublicShareBillCase(
        room="1202",
        pair=("1201", "1202"),
        scheme_key="RATIO-1201-1202",
        method_key="RATIO",
        expected_amount=Decimal("600.00"),
        calculation_parameters="PUBLIC_SHARE_TOTAL=1000\nALLOCATION_RATIO=60%\nMONTHS=1",
    ),
    PublicShareBillCase(
        room="1203",
        pair=("1203", "1204"),
        scheme_key="AMOUNT-1203-1204",
        method_key="AMOUNT",
        expected_amount=Decimal("300.00"),
        calculation_parameters="PUBLIC_SHARE_TOTAL=1000\nALLOCATION_AMOUNT=300\nMONTHS=1",
    ),
    PublicShareBillCase(
        room="1204",
        pair=("1203", "1204"),
        scheme_key="AMOUNT-1203-1204",
        method_key="AMOUNT",
        expected_amount=Decimal("700.00"),
        calculation_parameters="PUBLIC_SHARE_TOTAL=1000\nALLOCATION_AMOUNT=700\nMONTHS=1",
    ),
    PublicShareBillCase(
        room="1205",
        pair=("1205", "1206"),
        scheme_key="BUILDING-1205-1206",
        method_key="BUILDING_AREA",
        expected_amount=Decimal("1800.72"),
        calculation_parameters=(
            "BUILDING_AREA=300.12\nUSABLE_AREA=280.01\nFEE_AREA=260.00\n"
            "FLOOR=1\nUNIT_PRICE=2\nFLOOR_COEFFICIENT=3\nMONTHS=1"
        ),
    ),
    PublicShareBillCase(
        room="1206",
        pair=("1205", "1206"),
        scheme_key="BUILDING-1205-1206",
        method_key="BUILDING_AREA",
        expected_amount=Decimal("2162.16"),
        calculation_parameters=(
            "BUILDING_AREA=360.36\nUSABLE_AREA=315.15\nFEE_AREA=300.00\n"
            "FLOOR=1\nUNIT_PRICE=2\nFLOOR_COEFFICIENT=3\nMONTHS=1"
        ),
    ),
    PublicShareBillCase(
        room="1271",
        pair=("1271", "1272"),
        scheme_key="USABLE-1271-1272",
        method_key="USABLE_AREA",
        expected_amount=Decimal("1680.06"),
        calculation_parameters=(
            "BUILDING_AREA=300.12\nUSABLE_AREA=280.01\nFEE_AREA=260.00\n"
            "FLOOR=1\nUNIT_PRICE=2\nFLOOR_COEFFICIENT=3\nMONTHS=1"
        ),
    ),
    PublicShareBillCase(
        room="1272",
        pair=("1271", "1272"),
        scheme_key="USABLE-1271-1272",
        method_key="USABLE_AREA",
        expected_amount=Decimal("1890.90"),
        calculation_parameters=(
            "BUILDING_AREA=360.36\nUSABLE_AREA=315.15\nFEE_AREA=300.00\n"
            "FLOOR=1\nUNIT_PRICE=2\nFLOOR_COEFFICIENT=3\nMONTHS=1"
        ),
    ),
    PublicShareBillCase(
        room="1273",
        pair=("1273", "1274"),
        scheme_key="FEE-1273-1274",
        method_key="FEE_AREA",
        expected_amount=Decimal("1560.00"),
        calculation_parameters=(
            "BUILDING_AREA=300.12\nUSABLE_AREA=280.01\nFEE_AREA=260.00\n"
            "FLOOR=1\nUNIT_PRICE=2\nFLOOR_COEFFICIENT=3\nMONTHS=1"
        ),
    ),
    PublicShareBillCase(
        room="1274",
        pair=("1273", "1274"),
        scheme_key="FEE-1273-1274",
        method_key="FEE_AREA",
        expected_amount=Decimal("1890.00"),
        calculation_parameters=(
            "BUILDING_AREA=360.36\nUSABLE_AREA=315.15\nFEE_AREA=315.00\n"
            "FLOOR=1\nUNIT_PRICE=2\nFLOOR_COEFFICIENT=3\nMONTHS=1"
        ),
    ),
)

PUBLIC_SHARE_BY_ROOM = {case.room: case for case in PUBLIC_SHARE_BILL_CASES}


def expected_public_share_amount(room: str) -> Decimal:
    try:
        return PUBLIC_SHARE_BY_ROOM[room].expected_amount
    except KeyError as exc:
        raise KeyError(f"no public-share assertion is configured for room {room}") from exc
