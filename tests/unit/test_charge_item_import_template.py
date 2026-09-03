from __future__ import annotations

from collections import Counter

from scripts.update_charge_item_import_template import (
    MeterRecord,
    build_import_rows,
    load_meter_records,
)


def test_charge_item_import_rows_follow_active_room_mapping() -> None:
    rows, issues = build_import_rows(
        "A栋/1层", "2023-01-01", "2028-12-31"
    )

    assert len(rows) == 34
    assert len({row.room_path for row in rows}) == 34
    assert issues == []
    assert rows[0].room_path == "A栋/1层/1001"
    assert rows[0].charge_item == "UI周期性收费项"
    assert rows[0].charge_standard == "周期常用公式（月单价*建筑面积*月数）-按天"
    assert rows[0].start_date == "2023-01-01"
    assert rows[0].end_date == "2028-12-31"


def test_charge_item_names_and_meter_names_are_complete() -> None:
    rows, issues = build_import_rows(
        "A栋/1层", "2023-01-01", "2028-12-31"
    )
    counts = Counter(row.charge_item for row in rows)

    assert counts == {
        "UI周期性收费项": 22,
        "UI仪表类收费项-水表": 6,
        "UI仪表类收费项-电表": 6,
    }
    meter_rows = [row for row in rows if "仪表类收费项" in row.charge_item]
    assert len(meter_rows) == 12
    assert all(row.meter_name for row in meter_rows)
    assert issues == []
    assert all(
        row.room_path.rsplit("/", 1)[-1]
        not in {"1028", "1029", "1030", "1031", "1036", "1039", "1044", "1047"}
        for row in rows
    )


def test_meter_names_are_joined_by_room_and_expected_type() -> None:
    meter_records = [
        MeterRecord("A栋/1层/1032", "水表1032", "水表"),
        MeterRecord("A栋/1层/1040", "电表1040", "电表"),
    ]
    rows, issues = build_import_rows(
        "A栋/1层", "2023-01-01", "2028-12-31", meter_records
    )
    by_room = {row.room_path.rsplit("/", 1)[-1]: row for row in rows}

    assert by_room["1032"].meter_name == "水表1032"
    assert by_room["1040"].meter_name == "电表1040"
    assert len(issues) == 10


def test_current_meter_template_matches_charge_standard_types() -> None:
    records = load_meter_records()
    rows, issues = build_import_rows(
        "A栋/1层", "2023-01-01", "2028-12-31", records
    )

    assert len(rows) == 34
    assert issues == []
    assert all(row.meter_name for row in rows if row.charge_type != "周期类")
    by_room = {row.room_path.rsplit("/", 1)[-1]: row for row in rows}
    assert by_room["1032"].meter_name == "水表1032"
    assert by_room["1040"].meter_name == "电表1040"
