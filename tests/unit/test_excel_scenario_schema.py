from __future__ import annotations

from scripts.add_bill_demo_to_excel import (
    CASE,
    CALCULATION_CASE,
    METER_CASES,
    METER_SCENARIO_ROWS,
    OBSOLETE_RUNTIME_PARAMETERS,
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


def test_all_periodic_room_scenarios_have_independent_expected_amounts() -> None:
    periodic = [row for row in SCENARIO_ROWS if row[0].startswith("YSF-SCENE-PERIODIC-")]
    assert len(periodic) == 22
    assert all(row[4] == "云收费UI自动化" for row in periodic)
    assert all(row[19] and row[21] for row in periodic)
    assert all(row[19] == row[21] for row in periodic)
    executable = [row for row in periodic if row[25] == "已核验" and row[26] == "是"]
    blocked = [row for row in periodic if row[25] == "待补充" and row[26] == "否"]
    assert len(executable) == 22
    assert blocked == []


def test_all_meter_scenarios_use_august_readings_and_are_executable() -> None:
    assert len(METER_SCENARIO_ROWS) == 12
    assert len(METER_CASES) == 12
    assert all(row[17] == "2026-08" for row in METER_SCENARIO_ROWS)
    assert all("PERIOD_USAGE=80" in row[16] for row in METER_SCENARIO_ROWS)
    assert all("CURRENT_READING=360" in row[16] for row in METER_SCENARIO_ROWS)
    assert all(row[25] == "已核验" and row[26] == "是" for row in METER_SCENARIO_ROWS)


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
    assert not set(OBSOLETE_RUNTIME_PARAMETERS).intersection(parameter_names)
    assert not {
        "PROJECT_NAME", "ROOM_PATH", "CHARGE_TYPE", "CHARGE_ITEM"
    }.intersection(parameter_names)


def test_case_data_references_scenario_without_copying_business_data() -> None:
    case_data = CASE[10]
    assert case_data == "SCENARIO_ID=YSF-SCENE-PERIODIC-001"
    assert "PROJECT_NAME=" not in case_data
    assert "ROOM_PATH=" not in case_data


def test_calculation_case_reuses_periodic_scenario_and_runtime_parameters() -> None:
    assert CALCULATION_CASE[10] == "SCENARIO_ID=YSF-SCENE-PERIODIC-001"
    assert "${CALCULATION_BILLING_MONTH}" in CALCULATION_CASE[9]
    assert "${CALCULATION_RULE_DAY}" in CALCULATION_CASE[9]


def test_business_variable_names_are_visible_in_scenario_headers() -> None:
    header_text = "\n".join(header for header, _ in SCENARIO_HEADERS)
    for variable in (
        "PROJECT_NAME", "ROOM_PATH", "CHARGE_TYPE", "CHARGE_ITEM"
    ):
        assert f"${{{variable}}}" in header_text
