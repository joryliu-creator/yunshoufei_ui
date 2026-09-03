from __future__ import annotations

from decimal import Decimal

import pytest

from scripts.set_room_fee_area import normalize_fee_area, selected_rooms


def test_fee_area_is_normalized_to_two_decimals() -> None:
    assert normalize_fee_area("260") == Decimal("260.00")


def test_fee_area_must_be_positive() -> None:
    with pytest.raises(ValueError, match="大于 0"):
        normalize_fee_area("0")


def test_default_rooms_come_from_mapping_and_are_unique() -> None:
    rooms = selected_rooms(None)
    assert rooms[0] == "1001"
    assert len(rooms) == len(set(rooms))
    assert len(rooms) == 60


def test_unknown_room_is_rejected() -> None:
    with pytest.raises(ValueError, match="映射表不存在房间"):
        selected_rooms(["9999"])
