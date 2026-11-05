from __future__ import annotations

"""维护账单减免专项场景（1101-1103）。"""

from copy import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

WORKBOOK = ROOT / "UI自动化回归测试用例模板_Demo.xlsx"
CASES = [
    dict(room="1101", scheme="减免方案-按折扣", amount="", discount="5.00", note="按折扣=5折"),
    dict(room="1102", scheme="减免方案-按固定金额", amount="", discount="5.00", note="按固定金额=5"),
    dict(room="1103", scheme="减免方案-自定义金额", amount="5", discount="5.00", note="自定义金额输入=5"),
]

def _headers(ws):
    return {str(ws.cell(1, c).value).splitlines()[0].rstrip("*").strip(): c for c in range(1, ws.max_column + 1) if ws.cell(1, c).value}

def _copy_row(ws, source_row, target_row):
    ws.row_dimensions[target_row].height = ws.row_dimensions[source_row].height
    for col in range(1, ws.max_column + 1):
        src, dst = ws.cell(source_row, col), ws.cell(target_row, col)
        if src.has_style: dst._style = copy(src._style)
        dst.number_format = src.number_format
        dst.alignment = copy(src.alignment)

def _upsert_scenarios(wb):
    ws = wb.worksheets[1]; headers = _headers(ws); id_col = headers["场景编号"]
    for item in CASES:
        sid = f"YSF-SCENE-DISCOUNT-{item['room']}"
        rows = [r for r in range(2, ws.max_row + 1) if ws.cell(r, id_col).value == sid]
        row = rows[0] if rows else ws.max_row + 1
        if not rows: _copy_row(ws, max(2, ws.max_row), row)
        values = {
            "场景编号": sid, "场景名称": f"{item['room']}账单减免-{item['scheme'].replace('减免方案-', '')}", "环境": "standard1", "客户号": "93537", "项目名称": "云收费UI自动化",
            "房间路径": f"A栋/1层/{item['room']}", "收费类型": "周期类", "收费项": "UI周期性收费项", "收费标准": "周期固定金额（月固定金额*月数）", "生效开始": "2023-01-01", "生效结束": "2028-12-31", "计费公式": "周期固定金额（月固定金额*月数）-按满月", "计算参数": "月固定金额=10\n月数=1", "建议测试账期": "2026-08", "减免配置": f"{item['note']}；方案={item['scheme']}", "预期原始金额": "10.00", "预期减免金额": item["discount"], "预期应收金额": "5.00", "舍入规则": "保留2位小数", "前置条件": f"{item['room']}已绑定周期性收费项；{item['scheme']}已存在", "是否共享房间": "否", "维护状态": "已核验", "是否启用": "是", "数据负责人": "Codex", "最近检查日期": "2026-09-09", "备注": "账单减免专项；1104-1106因无违约金暂不执行",
        }
        for name, value in values.items():
            if name in headers: ws.cell(row, headers[name]).value = value

def _upsert_case_sheet(wb):
    title = "账单减免专项"; ws = wb[title] if title in wb.sheetnames else wb.create_sheet(title)
    ws.delete_rows(1, ws.max_row)
    headers = ["用例编号", "场景引用", "目标房间", "减免方案", "设置减免金额", "减免说明", "预期原始金额", "预期减免金额", "预期应收金额", "清理策略", "是否启用", "维护状态", "操作步骤", "预期结果"]
    ws.append(headers)
    for item in CASES:
        sid = f"YSF-SCENE-DISCOUNT-{item['room']}"
        steps = (f"1. 账单中心创建 A栋/1层/{item['room']} 的 2026-08 周期类账单，不先清理\n2. 进入收费设置→减免管理-新，选择项目\n3. 点击新增减免；房间输入框输入 {item['room']}，过滤后勾选叶子节点并确定\n4. 搜索并勾选账单，点击下一步\n5. 选择{item['scheme']}，{('在减免金额右侧输入框输入5，' if item['amount'] else '')}说明填写 autotest，下一步→发起审核\n6. 高级搜索直接在房间名称中选择 {item['room']} 并搜索\n7. 点击审核并确认审批通过\n8. 回到账单中心按账期+房间+收费项核对金额\n9. 验证完成后按账期+房间+收费项作废并删除本次账单")
        ws.append([f"YSF-BILL-DISCOUNT-{item['room']}", f"SCENARIO_ID={sid}", f"A栋/1层/{item['room']}", item["scheme"], item["amount"], "autotest", "10.00", item["discount"], "5.00", "账单中心按账期+房间+收费项作废删除", "是", "已核验", steps, f"申请成功；审核通过；减免={item['discount']}；清理后组合查询结果为0"])
    fill = PatternFill("solid", fgColor="1F4E78")
    for cell in ws[1]: cell.font = Font(color="FFFFFF", bold=True); cell.fill = fill; cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        for cell in row: cell.alignment = Alignment(vertical="top", wrap_text=True)
    ws.freeze_panes = "A2"
    for i, width in enumerate([22, 28, 20, 22, 16, 14, 16, 16, 16, 34, 10, 12, 90, 60], 1): ws.column_dimensions[chr(64 + i)].width = width

def main():
    wb = load_workbook(WORKBOOK); _upsert_scenarios(wb); _upsert_case_sheet(wb); wb.save(WORKBOOK); print("updated discount cases: 1101, 1102, 1103")

if __name__ == "__main__": main()
