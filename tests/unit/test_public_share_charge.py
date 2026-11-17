from decimal import Decimal

from src.domain.public_share_charge import PUBLIC_SHARE_BILL_CASES, PUBLIC_SHARE_BY_ROOM


def test_public_share_has_ten_unique_room_assertions() -> None:
    assert len(PUBLIC_SHARE_BILL_CASES) == 10
    assert len(PUBLIC_SHARE_BY_ROOM) == 10
    assert {case.room for case in PUBLIC_SHARE_BILL_CASES} == {
        "1201", "1202", "1203", "1204", "1205", "1206",
        "1271", "1272", "1273", "1274",
    }


def test_public_share_expected_amounts_are_independent_per_room() -> None:
    expected = {
        "1201": "400.00", "1202": "600.00",
        "1203": "300.00", "1204": "700.00",
        "1205": "1800.72", "1206": "2162.16",
        "1271": "1680.06", "1272": "1890.90",
        "1273": "1800.72", "1274": "2162.16",
    }
    assert {
        room: case.expected_amount
        for room, case in PUBLIC_SHARE_BY_ROOM.items()
    } == {room: Decimal(value) for room, value in expected.items()}


def test_fee_area_public_share_baseline_matches_confirmed_room_areas() -> None:
    assert "FEE_AREA=300.12" in PUBLIC_SHARE_BY_ROOM["1273"].calculation_parameters
    assert "FEE_AREA=360.36" in PUBLIC_SHARE_BY_ROOM["1274"].calculation_parameters
