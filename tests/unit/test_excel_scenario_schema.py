from __future__ import annotations

from scripts.add_bill_demo_to_excel import (
    CASE,
    RUNTIME_PARAMETER_HEADERS,
    RUNTIME_PARAMETER_ROWS,
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


def test_runtime_parameter_rows_are_focused_on_execution() -> None:
    assert len(RUNTIME_PARAMETER_HEADERS) == 10
    assert all(
        len(row) == len(RUNTIME_PARAMETER_HEADERS)
        for row in RUNTIME_PARAMETER_ROWS
    )
    parameter_names = [row[3] for row in RUNTIME_PARAMETER_ROWS]
    assert len(parameter_names) == len(set(parameter_names))
    assert "SCENARIO_ID" in parameter_names
    assert not {
        "PROJECT_NAME", "ROOM_PATH", "CHARGE_TYPE", "CHARGE_ITEM"
    }.intersection(parameter_names)


def test_case_data_references_scenario_without_copying_business_data() -> None:
    case_data = CASE[10]
    assert "SCENARIO_ID=YSF-SCENE-PERIODIC-001" in case_data
    assert "BILLING_MONTH=2026-07" in case_data
    assert "ACCOUNT_ROLE=default" in case_data
    assert "PROJECT_NAME=" not in case_data
    assert "ROOM_PATH=" not in case_data
