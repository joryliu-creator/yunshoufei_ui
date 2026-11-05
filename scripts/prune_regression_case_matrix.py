"""Keep only the maintained 102 entrypoint-level billing cases in Excel."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))

from openpyxl import load_workbook  # noqa: E402


WORKBOOK = ROOT / "UI自动化回归测试用例模板_Demo.xlsx"
CASE_SHEET = "用例清单"
SCENARIO_SHEET = "收费场景配置"
SCENARIO_PATTERN = re.compile(
    r"^YSF-SCENE-(PUBLIC-SHARE-PERIODIC|PERIODIC|METER|TEMP|DEPOSIT)-(BILL|CALC|LEDGER)-(.+)$"
)


def is_maintained_case(case_id: str, scenario_id: str) -> bool:
    match = SCENARIO_PATTERN.fullmatch(scenario_id)
    if not match:
        return False
    charge_type, entrypoint, room = match.groups()

    if charge_type == "PUBLIC-SHARE-PERIODIC" and entrypoint == "BILL":
        return case_id == f"YSF-BILL-PUBLIC-SHARE-PERIODIC-{room}"
    if charge_type == "PUBLIC-SHARE-PERIODIC" and entrypoint == "CALC":
        return case_id == f"YSF-CALC-PUBLIC-SHARE-PERIODIC-{room}"
    if charge_type == "PERIODIC" and entrypoint == "BILL":
        return case_id == f"YSF-BILL-PERIODIC-{room}"
    if charge_type == "PUBLIC-SHARE-PERIODIC" and entrypoint == "BILL":
        return case_id == f"YSF-BILL-PUBLIC-SHARE-PERIODIC-{room}"
    if charge_type == "PERIODIC" and entrypoint == "CALC":
        # The legacy 1001 scenario ID ends in 001; the case ID uses the
        # actual room suffix so reports do not make 001 look like a room.
        case_room = "1001" if room == "001" else room
        expected = f"YSF-CALC-PERIODIC-{case_room}"
        return case_id == expected
    if charge_type == "METER" and entrypoint == "BILL":
        return case_id == f"YSF-BILL-METER-{room}"
    if charge_type == "METER" and entrypoint == "CALC":
        return case_id == f"YSF-CALC-METER-{room}"
    if charge_type == "TEMP" and entrypoint == "LEDGER":
        return bool(re.fullmatch(r"YSF-BILL-TEMP-\d{3}", case_id))
    if charge_type == "TEMP" and entrypoint == "CALC":
        return case_id == f"YSF-CALC-TEMP-{room}"
    if charge_type == "DEPOSIT" and entrypoint == "LEDGER":
        return case_id == f"YSF-DEPOSIT-LEDGER-{room}"
    if charge_type == "DEPOSIT" and entrypoint == "CALC":
        return case_id == f"YSF-DEPOSIT-CALC-{room}"
    return False


def main() -> None:
    workbook = load_workbook(WORKBOOK)
    cases = workbook[CASE_SHEET]
    scenarios = workbook[SCENARIO_SHEET]

    formal_scenarios = {
        str(scenarios.cell(row, 1).value or "").strip()
        for row in range(2, scenarios.max_row + 1)
        if SCENARIO_PATTERN.fullmatch(
            str(scenarios.cell(row, 1).value or "").strip()
        )
    }
    expected_scenario_count = 122
    if len(formal_scenarios) != expected_scenario_count:
        raise ValueError(f"正式收费场景应为102条，实际为{len(formal_scenarios)}条")

    kept: list[tuple[str, str]] = []
    removed: list[str] = []
    rows_to_delete: list[int] = []
    for row in range(2, cases.max_row + 1):
        case_id = str(cases.cell(row, 1).value or "").strip()
        reference = str(cases.cell(row, 11).value or "").strip()
        scenario_id = reference.removeprefix("SCENARIO_ID=")
        if (
            scenario_id in formal_scenarios
            and is_maintained_case(case_id, scenario_id)
        ):
            kept.append((case_id, scenario_id))
        elif case_id:
            rows_to_delete.append(row)
            removed.append(case_id)

    if len(kept) != expected_scenario_count or len({case_id for case_id, _ in kept}) != expected_scenario_count:
        raise ValueError(
            "整理前正式用例不是102条唯一记录："
            f"rows={len(kept)}, unique={len({case_id for case_id, _ in kept})}"
        )
    if len({scenario_id for _, scenario_id in kept}) != expected_scenario_count:
        raise ValueError("正式用例没有与102条入口级收费场景一一对应")

    for row in reversed(rows_to_delete):
        cases.delete_rows(row, 1)
    cases.auto_filter.ref = f"A1:T{cases.max_row}"
    workbook.save(WORKBOOK)

    counts = Counter()
    for _, scenario_id in kept:
        charge_type, entrypoint, _ = SCENARIO_PATTERN.fullmatch(scenario_id).groups()
        counts[(charge_type, entrypoint)] += 1
    print(f"updated={WORKBOOK}")
    print(f"kept={len(kept)} removed={len(removed)}")
    for key in sorted(counts):
        print(f"{key[0]}_{key[1]}={counts[key]}")
    print("removed_ids=" + ",".join(removed))


if __name__ == "__main__":
    main()
