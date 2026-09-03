"""Record the rerun outcomes after room fee-area corrections."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))
from openpyxl import load_workbook  # noqa: E402

RESULTS = {
    **{f"YSF-BILL-PERIODIC-{room}": ("通过", "重跑通过，收费面积修正后金额断言通过并完成清理")
       for room in ["1003", "1007", "1010", "1050", "1054", "1057"]},
    "YSF-CALC-TEMP-1019": ("通过", "收费面积修正后重跑通过，金额 104000.00 并完成账单中心清理"),
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
    report_path = ROOT / "artifacts" / "latest_entrypoint_regression_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    by_case = {item["case_id"]: item for item in report["results"]}
    for case_id, (status, detail) in RESULTS.items():
        row = case_rows[case_id]
        cases.cell(row, 16).value = "已验证-通过" if status == "通过" else "已验证-失败"
        cases.cell(row, 20).value = append_note(cases.cell(row, 20).value, f"重跑结果：{detail}")
        ref = str(cases.cell(row, 11).value or "")
        scenario_id = ref.split("=", 1)[1].split(";", 1)[0].strip()
        if scenario_id in scenario_rows:
            sr = scenario_rows[scenario_id]
            scenarios.cell(sr, 26).value = "已核验"
            scenarios.cell(sr, 30).value = append_note(scenarios.cell(sr, 30).value, f"重跑结果：{detail}")
        by_case[case_id].update({"status": status, "detail": detail})
    wb.save(workbook)
    report["results"] = list(by_case.values())
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"updated={workbook}")
    print(f"report={report_path}")


if __name__ == "__main__":
    main()
