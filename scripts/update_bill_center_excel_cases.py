from pathlib import Path

from openpyxl import load_workbook


WORKBOOK = Path(__file__).resolve().parents[1] / "UI自动化回归测试用例模板_Demo.xlsx"

STEPS = """1. 进入智能计费-账单中心，选择项目“${PROJECT_NAME}”。
2. 点击“创建账单”，选择房间“${ROOM_PATH}”；房间树加载完成后，在左侧房间名称输入框输入房间名称/编号，等待唯一叶子节点出现后勾选并确认。
3. 选择账期“${BILLING_MONTH}”和应收日期“${RECEIVABLE_DATE}”。账期按场景配置填写，不能使用页面默认值替代。
4. 点击“新增收费项”，等待选择收费项抽屉加载；在左侧收费项搜索框输入“${CHARGE_ITEM}”，等待筛选结果后仅勾选目标收费项，点击抽屉右下角“确定”（不勾选收费项列表表头复选框，不使用右侧已选收费项筛选框）。
5. 点击新增收费项右侧“编辑”，最晚缴款日选择“${LATEST_PAYMENT_DATE}”，计费期间和用户端展示计费期间保持不变；按场景配置核对收费标准和金额，点击该行“保存”。
6. 点击创建账单抽屉右下角“确定”，在“是否需要进行线下收款”提示中点击“取消/不需要”。
7. 校验账单创建成功、账期为“${BILLING_MONTH}”、收费项和最终应收金额为“${EXPECTED_RECEIVABLE_AMOUNT}”。
8. 按本次创建的账单编号在账单中心定位唯一账单，执行“作废”并确认，再执行“删除”；复查列表中不存在该账单，记录作废、删除和清理结果。"""

EXPECTED = """1. 创建账单成功并生成唯一账单编号。
2. 房间、收费项、账期、应收日期、最晚缴款日和计费期间与场景配置一致。
3. 账单原始金额/减免金额/应收金额与预期“${EXPECTED_RECEIVABLE_AMOUNT}”一致。
4. 账单中心按账单编号作废、删除均成功，复查列表中不再存在本次账单。"""


def main() -> None:
    wb = load_workbook(WORKBOOK)
    ws = wb.worksheets[0]
    updated = []
    for row in range(2, ws.max_row + 1):
        case_id = ws.cell(row, 1).value
        if not isinstance(case_id, str):
            continue
        if case_id == "YSF-BILL-001" or case_id.startswith("YSF-BILL-METER-") or case_id.startswith("YSF-BILL-PERIODIC-"):
            ws.cell(row, 10).value = STEPS
            ws.cell(row, 12).value = EXPECTED
            updated.append(case_id)
    wb.save(WORKBOOK)
    print(f"updated={len(updated)}")
    print("ids=" + ",".join(updated))


if __name__ == "__main__":
    main()
