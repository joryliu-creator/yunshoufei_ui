from __future__ import annotations

from scripts.add_bill_demo_to_excel import (
    SCENARIO_HEADERS,
    SCENARIO_ROWS,
)


def test_charge_scenario_rows_match_header_schema() -> None:
    expected_columns = len(SCENARIO_HEADERS)
    assert expected_columns == 30
    assert all(len(row) == expected_columns for row in SCENARIO_ROWS)


def test_charge_scenario_ids_are_unique() -> None:
    scenario_ids = [row[0] for row in SCENARIO_ROWS]
    assert len(scenario_ids) == len(set(scenario_ids))


def test_template_scenarios_are_disabled() -> None:
    template_rows = [
        row for row in SCENARIO_ROWS if row[0].startswith("TEMPLATE-")
    ]
    assert template_rows
    assert all(row[25] == "模板" for row in template_rows)
    assert all(row[26] == "否" for row in template_rows)
