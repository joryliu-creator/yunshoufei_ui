"""Split shared billing scenarios by their actual UI entry point.

The workbook is the source of truth.  Existing cases keep their steps; only
their scenario references are made entry-point specific.
"""
from __future__ import annotations

from copy import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))
from openpyxl import load_workbook  # noqa: E402

WORKBOOK = ROOT / "UI自动化回归测试用例模板_Demo.xlsx"
MODULE_SUFFIX = {
    "智能计费/账单中心": ("BILL", "账单中心"),
    "智能计费/计费出账": ("CALC", "计费出账"),
    "智能计费/临时台账": ("LEDGER", "临时台账"),
}


def copy_style(ws, source: int, target: int, columns: int) -> None:
    ws.row_dimensions[target].height = ws.row_dimensions[source].height
    for col in range(1, columns + 1):
        ws.cell(target, col)._style = copy(ws.cell(source, col)._style)
        ws.cell(target, col).number_format = ws.cell(source, col).number_format
        ws.cell(target, col).alignment = copy(ws.cell(source, col).alignment)


def main() -> None:
    wb = load_workbook(WORKBOOK)
    scenarios = wb["收费场景配置"]
    cases = wb["用例清单"]
    # Older runs of this script could split an already entrypoint-specific
    # reference again, producing BILL-BILL / CALC-CALC identifiers.  Normalize
    # those rows first so regeneration stays idempotent.
    duplicate_suffixes = {
        "-BILL-BILL-": "-BILL-",
        "-CALC-CALC-": "-CALC-",
        "-LEDGER-LEDGER-": "-LEDGER-",
    }
    replacements: dict[str, str] = {}
    for row in range(2, scenarios.max_row + 1):
        scenario_id = str(scenarios.cell(row, 1).value or "")
        for duplicate, normalized in duplicate_suffixes.items():
            if duplicate in scenario_id:
                replacements[scenario_id] = scenario_id.replace(
                    duplicate, normalized, 1
                )
                break
    for row in range(2, cases.max_row + 1):
        reference = str(cases.cell(row, 11).value or "")
        if reference.startswith("SCENARIO_ID="):
            scenario_id = reference.split("=", 1)[1]
            if scenario_id in replacements:
                cases.cell(row, 11, f"SCENARIO_ID={replacements[scenario_id]}")
    existing_ids = {
        str(scenarios.cell(row, 1).value or "")
        for row in range(2, scenarios.max_row + 1)
    }
    rows_to_delete: list[int] = []
    for row in range(2, scenarios.max_row + 1):
        scenario_id = str(scenarios.cell(row, 1).value or "")
        normalized = replacements.get(scenario_id)
        if not normalized:
            continue
        if normalized in existing_ids:
            rows_to_delete.append(row)
        else:
            scenarios.cell(row, 1, normalized)
            existing_ids.add(normalized)
    for row in reversed(rows_to_delete):
        scenarios.delete_rows(row, 1)

    scenario_rows = {
        str(scenarios.cell(row, 1).value): row
        for row in range(2, scenarios.max_row + 1)
        if scenarios.cell(row, 1).value
    }

    # Collect the modules that actually reference each scenario.
    references: dict[str, set[str]] = {}
    for row in range(2, cases.max_row + 1):
        ref = str(cases.cell(row, 11).value or "")
        module = str(cases.cell(row, 3).value or "")
        if ref.startswith("SCENARIO_ID=") and module in MODULE_SUFFIX:
            references.setdefault(ref.split("=", 1)[1], set()).add(module)

    legacy_rows_to_delete: list[int] = []
    created = 0
    updated_cases = 0
    for base_id, modules in references.items():
        if not base_id.startswith("YSF-SCENE-") or "-DEPOSIT-" in base_id:
            continue
        parts = base_id.split("-")
        if len(parts) > 3 and parts[3] in {"BILL", "CALC", "LEDGER"}:
            continue
        base_row = scenario_rows.get(base_id)
        if base_row is None:
            continue
        base_name = str(scenarios.cell(base_row, 2).value or "")
        for module in sorted(modules):
            suffix, label = MODULE_SUFFIX[module]
            parts = base_id.split("-")
            # YSF-SCENE-{PERIODIC|METER|TEMP}-{room}
            if len(parts) < 4:
                continue
            new_id = "-".join(parts[:3] + [suffix] + parts[3:])
            new_name = f"{base_name}-{label}"
            target_row = scenario_rows.get(new_id)
            if target_row is None:
                target_row = scenarios.max_row + 1
                copy_style(scenarios, base_row, target_row, 30)
                scenario_rows[new_id] = target_row
                created += 1
            scenarios.cell(target_row, 1, new_id)
            scenarios.cell(target_row, 2, new_name)
            for col in range(3, 31):
                scenarios.cell(target_row, col, scenarios.cell(base_row, col).value)

            for case_row in range(2, cases.max_row + 1):
                if (
                    cases.cell(case_row, 3).value == module
                    and cases.cell(case_row, 11).value == f"SCENARIO_ID={base_id}"
                ):
                    cases.cell(case_row, 11, f"SCENARIO_ID={new_id}")
                    updated_cases += 1
        legacy_rows_to_delete.append(base_row)

    for row in sorted(set(legacy_rows_to_delete), reverse=True):
        # Keep template rows and remove only the shared scenario row.
        scenarios.delete_rows(row, 1)

    wb.save(WORKBOOK)
    print(f"updated={WORKBOOK}")
    print(f"created_entrypoint_scenarios={created}")
    print(f"updated_case_references={updated_cases}")


if __name__ == "__main__":
    main()
