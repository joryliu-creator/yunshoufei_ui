from __future__ import annotations

import pytest

from src.config.excel_data import (
    DEFAULT_WORKBOOK,
    load_case_reference,
    load_excel_test_data,
)


def test_case_reference_resolves_scenario_and_account_role() -> None:
    reference = load_case_reference("YSF-BILL-001", DEFAULT_WORKBOOK)

    assert reference.scenario_id == "YSF-SCENE-PERIODIC-001"
    assert reference.account_role == "default"


def test_excel_is_the_runtime_source_for_business_and_execution_data() -> None:
    loaded = load_excel_test_data(
        "standard1", "93537", "YSF-SCENE-PERIODIC-001", DEFAULT_WORKBOOK
    )

    assert loaded.scenario.project_name == "云收费自动化MS1"
    assert loaded.scenario.room_path.endswith("周期性收费房间001")
    assert loaded.scenario.charge_type == "周期类"
    assert loaded.scenario.charge_item == "周期性收费项"
    assert loaded.runtime_parameters["BILLING_MONTH"] == "2026-07"
    assert {
        "SCENARIO_ID",
        "ACCOUNT_ROLE",
        "ALLOW_BILL_CREATION",
        "CLEANUP_CREATED_BILL",
        "ALLOW_BILL_DELETION",
    }.isdisjoint(loaded.runtime_parameters)


def test_scenario_must_match_selected_environment_and_customer() -> None:
    with pytest.raises(ValueError, match="与本次运行不一致"):
        load_excel_test_data(
            "uat", "93537", "YSF-SCENE-PERIODIC-001", DEFAULT_WORKBOOK
        )
