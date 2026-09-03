"""Synchronize executed JUnit outcomes into the regression workbook."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
WB_PATH = ROOT / "UI自动化回归测试用例模板_Demo.xlsx"
JUNIT_PATH = ROOT / "artifacts" / "jenkins-junit.xml"
REPORT_PATH = ROOT / "artifacts" / "latest_entrypoint_regression_report.json"


def main() -> None:
    from openpyxl import load_workbook

    root = ElementTree.parse(JUNIT_PATH).getroot()
    results = []
    for case in root.iter("testcase"):
        name = case.attrib.get("name", "")
        ids = re.findall(r"YSF-[A-Z0-9-]+", name)
        if not ids:
            continue
        issue = case.find("failure")
        if issue is None:
            issue = case.find("error")
        results.append({
            "case_id": ids[-1],
            "status": "失败" if issue is not None else "通过",
            "detail": (issue.attrib.get("message", "") if issue is not None else "本次 JUnit 执行通过"),
        })
    wb = load_workbook(WB_PATH)
    cases, scenes = wb.worksheets[0], wb.worksheets[1]
    case_rows = {str(cases.cell(r, 1).value): r for r in range(2, cases.max_row + 1) if cases.cell(r, 1).value}
    scene_rows = {str(scenes.cell(r, 1).value): r for r in range(2, scenes.max_row + 1) if scenes.cell(r, 1).value}
    for result in results:
        row = case_rows.get(result["case_id"])
        if not row:
            continue
        passed = result["status"] == "通过"
        cases.cell(row, 16).value = "已验证通过" if passed else "已验证失败"
        cases.cell(row, 20).value = f"{date.today().isoformat()} JUnit真实回归：{result['detail']}"
        ref = str(cases.cell(row, 11).value or "")
        scenario_id = ref.split("=", 1)[1].split(";", 1)[0].strip() if ref.startswith("SCENARIO_ID=") else ""
        scene_row = scene_rows.get(scenario_id)
        if scene_row:
            # Keep the scenario's executable maintenance/enabled flags intact;
            # the execution outcome belongs in the note/status columns below.
            scenes.cell(scene_row, 29).value = date.today().isoformat()
            scenes.cell(scene_row, 30).value = f"{date.today().isoformat()} JUnit真实回归：{result['detail']}"
    wb.save(WB_PATH)
    REPORT_PATH.write_text(json.dumps({"run_date": date.today().isoformat(), "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"synced={len(results)}; workbook={WB_PATH}; report={REPORT_PATH}")


if __name__ == "__main__":
    main()
