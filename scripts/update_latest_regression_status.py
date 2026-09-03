"""Write the latest real-page regression results to the workbook."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))
from openpyxl import load_workbook  # noqa: E402

RUN_DATE = str(date.today())
RESULTS = {
    # Periodic bill-center entry point.
    **{f"YSF-BILL-PERIODIC-{room}": {"status": "通过", "detail": "金额断言通过，账单已作废并删除"}
       for room in ["1002", "1004", "1005", "1006", "1008", "1009", "1011", "1048", "1049", "1051", "1052", "1053", "1055", "1056", "1058"]},
    "YSF-BILL-PERIODIC-1003": {"status": "失败", "detail": "实际 3001.20；期望 2600.00，账单已清理"},
    "YSF-BILL-PERIODIC-1007": {"status": "失败", "detail": "实际 600.24；期望 520.00，账单已清理"},
    "YSF-BILL-PERIODIC-1010": {"status": "失败", "detail": "实际 1800.72；期望 1560.00，账单已清理"},
    "YSF-BILL-PERIODIC-1050": {"status": "失败", "detail": "实际 3001.20；期望 2600.00，账单已清理"},
    "YSF-BILL-PERIODIC-1054": {"status": "失败", "detail": "实际 600.24；期望 520.00，账单已清理"},
    "YSF-BILL-PERIODIC-1057": {"status": "失败", "detail": "实际 1800.72；期望 1560.00，账单已清理"},
    # Temporary calculation entry point.
    **{f"YSF-CALC-TEMP-{room}": {"status": "通过", "detail": "创建、金额断言和账单中心清理通过"}
       for room in ["1012", "1013", "1014", "1015", "1016", "1017", "1018", "1020", "1059", "1060"]},
    "YSF-CALC-TEMP-1019": {"status": "失败", "detail": "金额未稳定为 104000.00，未提交账单"},
}


def append_note(current: object, note: str) -> str:
    old = str(current or "").strip()
    return f"{old}；{note}" if old else note


def main() -> None:
    workbook = next(ROOT.glob("UI*.xlsx"))
    wb = load_workbook(workbook)
    cases = wb.worksheets[0]
    scenarios = wb.worksheets[1]
    case_rows = {str(cases.cell(r, 1).value): r for r in range(2, cases.max_row + 1) if cases.cell(r, 1).value}
    scenario_rows = {str(scenarios.cell(r, 1).value): r for r in range(2, scenarios.max_row + 1) if scenarios.cell(r, 1).value}
    updated = []
    for case_id, result in RESULTS.items():
        row = case_rows.get(case_id)
        if row is None:
            raise RuntimeError(f"用例不存在: {case_id}")
        status = "已验证-通过" if result["status"] == "通过" else "已验证-失败"
        cases.cell(row, 16).value = status
        cases.cell(row, 19).value = "有效"
        cases.cell(row, 20).value = append_note(cases.cell(row, 20).value, f"{RUN_DATE}真实页面回归：{result['detail']}")
        ref = str(cases.cell(row, 11).value or "")
        scenario_id = ref.split("=", 1)[1].split(";", 1)[0].strip() if ref.startswith("SCENARIO_ID=") else ""
        if scenario_id in scenario_rows:
            sr = scenario_rows[scenario_id]
            scenarios.cell(sr, 26).value = "已核验-通过" if result["status"] == "通过" else "已核验-失败"
            scenarios.cell(sr, 29).value = RUN_DATE
            scenarios.cell(sr, 30).value = append_note(scenarios.cell(sr, 30).value, f"{RUN_DATE}真实页面回归：{result['detail']}")
        updated.append({"case_id": case_id, "scenario_id": scenario_id, **result})
    wb.save(workbook)
    report = ROOT / "artifacts" / "latest_entrypoint_regression_report.json"
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps({"run_date": RUN_DATE, "results": updated}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"updated={workbook}")
    print(f"report={report}")
    print(f"passed={sum(item['status'] == '通过' for item in updated)} failed={sum(item['status'] == '失败' for item in updated)}")


if __name__ == "__main__":
    main()
