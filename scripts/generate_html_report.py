"""Generate a complete 102-scenario Cloud Billing UI regression report."""
from __future__ import annotations

from html import escape
import json
import os
from pathlib import Path
import re
from xml.etree import ElementTree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))
from openpyxl import load_workbook  # noqa: E402


def locate_workbook() -> Path:
    path = next((p for p in ROOT.glob("UI*.xlsx") if not p.name.startswith("~$")), None)
    if path is None:
        raise FileNotFoundError("未找到回归用例 Excel")
    return path


def amount(text: object) -> str:
    match = re.search(r"(?<![\d.])\d+(?:\.\d{1,2})?(?![\d.])", str(text or ""))
    return match.group(0) if match else "-"


def main() -> None:
    workbook = locate_workbook()
    source = ROOT / "artifacts" / "latest_entrypoint_regression_report.json"
    data = json.loads(source.read_text(encoding="utf-8")) if source.exists() else {"results": []}
    junit = Path(os.getenv("JUNIT_REPORT_PATH", str(ROOT / "artifacts" / "junit-report.xml")))
    if junit.exists():
        results = []
        testcases = list(ElementTree.parse(junit).getroot().iter("testcase"))
        targeted_case_id = os.getenv("TEST_CASE_ID", "").strip()
        created_artifact = ROOT / "artifacts" / "temporary-created-bill.json"
        created_data = (
            json.loads(created_artifact.read_text(encoding="utf-8"))
            if created_artifact.exists()
            else {}
        )
        for testcase in testcases:
            name = testcase.attrib.get("name", "")
            ids = re.findall(r"YSF-[A-Z0-9-]+", name)
            case_id = ids[-1] if ids else (
                targeted_case_id if len(testcases) == 1 else ""
            )
            if not case_id:
                continue
            failure = testcase.find("failure")
            error = testcase.find("error")
            problem = failure if failure is not None else error
            result = {
                "case_id": case_id,
                "status": "失败" if problem is not None else "通过",
                "detail": problem.attrib.get("message", "") if problem is not None else "本次专项执行通过",
            }
            if str(created_data.get("case_id", "")) == case_id:
                result["actual_amount"] = created_data.get("amount", "-")
                result["cleanup_status"] = (
                    "已清理" if created_data.get("cleanup_status") == "completed" else "清理未完成"
                )
                result["detail"] = (
                    f"账单编号={created_data.get('bill_number', '-')}；"
                    f"创建、金额/账期断言及清理均通过"
                    if problem is None
                    else result["detail"]
                )
            results.append(result)
        if results:
            data = {"run_date": data.get("run_date", "本次执行"), "results": results}

    wb = load_workbook(workbook, data_only=True)
    cases_ws, scenes_ws = wb.worksheets[0], wb.worksheets[1]
    cases = {str(row[0].value): [cell.value for cell in row] for row in cases_ws.iter_rows(min_row=2) if row[0].value}
    scenes = {str(row[0].value): [cell.value for cell in row] for row in scenes_ws.iter_rows(min_row=2) if row[0].value}
    scenario_cases: dict[str, list[str]] = {}
    for case_id, case in cases.items():
        if len(case) <= 10:
            continue
        match = re.search(r"SCENARIO_ID\s*=\s*([^\s;]+)", str(case[10] or ""))
        if match:
            scenario_cases.setdefault(match.group(1), []).append(case_id)
    results_by_case = {str(r.get("case_id")): r for r in data.get("results", [])}

    rows = []
    for scene_id, scene in scenes.items():
        if not scene_id.startswith("YSF-SCENE-") or "UI" not in str(scene[4] if len(scene) > 4 else ""):
            continue
        candidates = scenario_cases.get(scene_id, [])
        case_id = sorted(candidates, key=lambda value: (any(ord(c) > 127 for c in value), len(value), value))[0] if candidates else "-"
        result = results_by_case.get(case_id, {})
        detail = str(result.get("detail") or "")
        executed = bool(result)
        rows.append({
            "case_id": case_id,
            "environment": scene[2] if len(scene) > 2 and scene[2] else "-",
            "scenario": scene_id,
            "room": scene[5] if len(scene) > 5 and scene[5] else "-",
            "item": scene[10] if len(scene) > 10 and scene[10] else "-",
            "expected": scene[21] if len(scene) > 21 and scene[21] else "-",
            "actual": result.get("actual_amount") or (amount(detail) if any(ch.isdigit() for ch in detail) else "-"),
            "status": result.get("status", "未执行") if executed else "未执行",
            "cleanup": result.get("cleanup_status", "未执行") if executed else "未执行",
            "detail": detail or "本次未执行",
        })
    passed = sum(str(row["status"]) in {"通过", "passed", "PASS"} for row in rows)
    failed = sum(str(row["status"]) in {"失败", "failed", "FAIL"} for row in rows)
    body_rows = "\n".join("<tr>" + "".join(f"<td>{escape(str(row[key]))}</td>" for key in ("case_id", "environment", "scenario", "room", "item", "expected", "actual", "status", "cleanup", "detail")) + "</tr>" for row in rows)
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>云收费 UI 自动化回归报告</title><style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;color:#1f2937}}.summary{{display:flex;gap:16px;margin:16px 0}}.card{{padding:12px 20px;border-radius:8px;background:#f3f4f6}}.pass{{color:#15803d}}.fail{{color:#b91c1c}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{border:1px solid #d1d5db;padding:8px;text-align:left;vertical-align:top}}th{{background:#1f4e79;color:white;position:sticky;top:0}}tr:nth-child(even){{background:#f9fafb}}td:last-child{{max-width:360px;white-space:pre-wrap}}</style></head><body><h1>云收费 UI 自动化回归报告</h1><div>执行日期：{escape(str(data.get("run_date", "-")))}</div><div class="summary"><div class="card">总场景：{len(rows)}</div><div class="card pass">通过：{passed}</div><div class="card fail">失败：{failed}</div><div class="card">未执行：{len(rows)-passed-failed}</div></div><table><thead><tr><th>用例编号</th><th>环境</th><th>场景</th><th>房间</th><th>收费项</th><th>预期金额</th><th>实际金额</th><th>状态</th><th>清理结果</th><th>详情</th></tr></thead><tbody>{body_rows}</tbody></table></body></html>'''
    configured_output = os.getenv("HTML_REPORT_PATH", "").strip()
    output = Path(configured_output) if configured_output else ROOT / "artifacts" / "latest_regression_report.html"
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    print(f"generated={output}; scenarios={len(rows)}; passed={passed}; failed={failed}; not_executed={len(rows)-passed-failed}")


if __name__ == "__main__":
    main()
