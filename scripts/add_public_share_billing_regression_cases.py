"""Add room-level public-share billing cases to the maintained regression workbook."""

from __future__ import annotations

import argparse
from copy import copy
from datetime import date
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".tools" / "python"))

from openpyxl import load_workbook  # noqa: E402

from src.config.environments import load_test_environment  # noqa: E402

WORKBOOK = ROOT / "UI自动化回归测试用例模板_Demo.xlsx"
ENVIRONMENT = "standard1"
CUSTOMER_ID = "93537"
PROJECT_NAME = "云收费UI自动化"


def _normal_header(value: object) -> str:
    return str(value or "").splitlines()[0].rstrip("*").strip()


def _headers(worksheet) -> dict[str, int]:
    return {
        _normal_header(worksheet.cell(1, column).value): column
        for column in range(1, worksheet.max_column + 1)
        if _normal_header(worksheet.cell(1, column).value)
    }


def _runtime_parameter_values() -> dict[str, str]:
    workbook = load_workbook(WORKBOOK, read_only=True, data_only=True)
    try:
        worksheet = workbook["运行参数"]
        columns = _headers(worksheet)
        values: dict[str, str] = {}
        for row in range(2, worksheet.max_row + 1):
            if str(worksheet.cell(row, columns["环境"]).value or "").strip() != ENVIRONMENT:
                continue
            if str(worksheet.cell(row, columns["客户号"]).value or "").strip() != CUSTOMER_ID:
                continue
            name = str(worksheet.cell(row, columns["参数名"]).value or "").strip()
            value = str(worksheet.cell(row, columns["默认值"]).value or "").strip()
            if name:
                values[name] = value
        return values
    finally:
        workbook.close()


def _copy_row_style(worksheet, source_row: int, target_row: int) -> None:
    worksheet.row_dimensions[target_row].height = worksheet.row_dimensions[source_row].height
    for column in range(1, worksheet.max_column + 1):
        source = worksheet.cell(source_row, column)
        target = worksheet.cell(target_row, column)
        if source.has_style:
            target._style = copy(source._style)
        target.number_format = source.number_format
        target.alignment = copy(source.alignment)


def _row_for_id(worksheet, case_id: str) -> int:
    for row in range(2, worksheet.max_row + 1):
        if str(worksheet.cell(row, 1).value or "").strip() == case_id:
            return row
    return worksheet.max_row + 1


def _donor_row(worksheet, required_prefixes: tuple[str, ...]) -> int:
    for row in range(2, worksheet.max_row + 1):
        value = str(worksheet.cell(row, 1).value or "").strip()
        if any(value.startswith(prefix) for prefix in required_prefixes):
            return row
    return 2


def _write_fields(worksheet, row: int, fields: dict[str, object]) -> None:
    columns = _headers(worksheet)
    for name, value in fields.items():
        if name not in columns:
            raise ValueError(f"工作表 {worksheet.title} 缺少列：{name}")
        worksheet.cell(row, columns[name], value)


def _upsert_runtime_parameters(worksheet, period_days: str, unit_price: str) -> None:
    columns = _headers(worksheet)
    parameter_column = columns["参数名"]
    existing: dict[str, int] = {}
    used_ids: set[str] = set()
    for row in range(2, worksheet.max_row + 1):
        name = str(worksheet.cell(row, parameter_column).value or "").strip()
        if name:
            if name in existing:
                raise ValueError(f"运行参数重复：{name}")
            existing[name] = row
        id_column = columns.get("参数编号")
        if id_column:
            used_ids.add(str(worksheet.cell(row, id_column).value or "").strip())

    donor = next(
        (row for name, row in existing.items() if name in {"BILLING_MONTH", "CALCULATION_BILLING_MONTH"}),
        2,
    )
    values = {
        "PUBLIC_SHARE_PERIOD_DAYS": (
            period_days,
            "仪表公摊抄表周期按首尾包含的自然日数；当前抄表周期为 2026-07-04 至 2026-08-04，共 32 天",
        ),
        "PUBLIC_SHARE_UNIT_PRICE": (
            unit_price,
            "仪表公摊收费标准当前单价，以已确认收费标准为准",
        ),
    }
    for name, (value, purpose) in values.items():
        row = existing.get(name)
        if row is None:
            row = worksheet.max_row + 1
            _copy_row_style(worksheet, donor, row)
            next_id = 1
            while f"PARAM-{next_id:03d}" in used_ids:
                next_id += 1
            _write_fields(worksheet, row, {"参数编号": f"PARAM-{next_id:03d}"})
            used_ids.add(f"PARAM-{next_id:03d}")
        _write_fields(
            worksheet,
            row,
            {
                "环境": ENVIRONMENT,
                "客户号": CUSTOMER_ID,
                "参数名": name,
                "默认值": value,
                "参数类型": "业务运行参数",
                "用途": purpose,
                "是否可覆盖": "是",
                "维护状态": "有效",
                "备注": "仪表类公摊账单回归；执行时允许用同名环境变量覆盖",
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    current_parameters = _runtime_parameter_values()
    parser.add_argument(
        "--period-days",
        default=os.getenv(
            "PUBLIC_SHARE_PERIOD_DAYS",
            current_parameters.get("PUBLIC_SHARE_PERIOD_DAYS", "32"),
        ),
    )
    parser.add_argument(
        "--unit-price",
        default=os.getenv(
            "PUBLIC_SHARE_UNIT_PRICE",
            current_parameters.get("PUBLIC_SHARE_UNIT_PRICE", "5"),
        ),
    )
    args = parser.parse_args()
    if int(args.period_days) <= 0 or float(args.unit_price) <= 0:
        raise ValueError("周期天数和仪表单价必须大于 0。")

    load_test_environment(ROOT, ENVIRONMENT)
    os.environ["PUBLIC_SHARE_PERIOD_DAYS"] = str(args.period_days)
    os.environ["PUBLIC_SHARE_UNIT_PRICE"] = str(args.unit_price)

    # Import after loading the confirmed run parameters. This reuses the same
    # per-room expected-amount builder as the UI billing tests.
    from scripts.test_instrument_public_share_billing import CASES, MONTH
    from src.config.settings import settings

    if settings.test_environment != ENVIRONMENT or settings.master_customer_id != CUSTOMER_ID:
        raise ValueError("当前环境/客户与水表、电表公摊基线场景不一致。")
    if len(CASES) != 32:
        raise ValueError(f"水表/电表公摊参与房间应为 32 间，实际 {len(CASES)} 间。")
    if MONTH != "2026-08":
        raise ValueError(f"当前已确认的公摊出账基准账期是 2026-08，实际为 {MONTH}。")

    workbook = load_workbook(WORKBOOK)
    try:
        case_sheet = workbook["用例清单"]
        scenario_sheet = workbook["收费场景配置"]
        runtime_sheet = workbook["运行参数"]
        _upsert_runtime_parameters(runtime_sheet, str(args.period_days), str(args.unit_price))

        scenario_donor = _donor_row(
            scenario_sheet,
            ("YSF-SCENE-PUBLIC-SHARE-PERIODIC-CALC-",),
        )
        bill_donor = _donor_row(
            case_sheet,
            ("YSF-BILL-PUBLIC-SHARE-PERIODIC-",),
        )
        calc_donor = _donor_row(
            case_sheet,
            ("YSF-CALC-PUBLIC-SHARE-PERIODIC-",),
        )

        written_scenarios = 0
        written_cases = 0
        for billing_case in CASES:
            room = billing_case.room.room
            expected = f"{billing_case.expected_amount:.2f}"
            source_note = (
                "计费面积系数金额暂按用户确认的账单中心实际出账金额作为阶段性回归基准；该来源不代表已独立验证公摊公式，待公式核对后再更新。"
                if "按住户计费面积对应系数" in billing_case.method
                else "预期金额按已确认的公摊业务规则独立计算。"
            )
            parameters = (
                f"PAIR={billing_case.pair[0]},{billing_case.pair[1]}\n"
                f"INSTRUMENT={billing_case.instrument_name}\n"
                f"INSTRUMENT_TYPE={billing_case.instrument_type}\n"
                f"PERIOD_USAGE={billing_case.period_usage}\n"
                f"UNIT_PRICE={args.unit_price}\n"
                f"PUBLIC_SHARE_PERIOD_DAYS={args.period_days}\n"
                f"INCOMPLETE_MONTH_RULE={billing_case.month_rule}\n"
                f"EXPECTED_SOURCE={source_note}"
            )

            for entrypoint in ("BILL", "CALC"):
                scenario_id = f"YSF-SCENE-PUBLIC-SHARE-METER-{entrypoint}-{room}"
                scenario_row = _row_for_id(scenario_sheet, scenario_id)
                if scenario_row > scenario_sheet.max_row:
                    _copy_row_style(scenario_sheet, scenario_donor, scenario_row)
                scenario_name = f"仪表公摊-{billing_case.instrument_type}-{room}-{entrypoint}"
                _write_fields(
                    scenario_sheet,
                    scenario_row,
                    {
                        "场景编号": scenario_id,
                        "场景名称": scenario_name,
                        "环境": ENVIRONMENT,
                        "客户号": CUSTOMER_ID,
                        "项目名称": settings.project_name,
                        "房间路径": billing_case.room.room_path,
                        "收费类型": "仪表类",
                        "收费项": billing_case.charge_item,
                        "收费标准": billing_case.charge_standard,
                        "计费公式": f"仪表公摊-{billing_case.method}-{billing_case.month_rule}",
                        "计算参数": parameters,
                        "建议测试账期": MONTH,
                        "减免配置": "无减免",
                        "预期原始金额": expected,
                        "预期减免金额": "0.00",
                        "预期应收金额": expected,
                        "舍入规则": "四舍五入保留2位",
                        "前置条件": (
                            f"公摊方案已存在；{billing_case.instrument_name}及抄表用量已导入；"
                            "房间客户已入住；收费项和收费标准有效；目标账期无重复账单"
                        ),
                        "是否共享房间": "是",
                        "维护状态": "已核验-账单中心实际基准；纳入入口回归",
                        "是否启用": "是",
                        "数据负责人": "Codex",
                        "最近检查日期": date.today().isoformat(),
                        "备注": source_note,
                    },
                )
                written_scenarios += 1

                case_id = f"YSF-{entrypoint}-PUBLIC-SHARE-METER-{room}"
                case_row = _row_for_id(case_sheet, case_id)
                if case_row > case_sheet.max_row:
                    donor = bill_donor if entrypoint == "BILL" else calc_donor
                    _copy_row_style(case_sheet, donor, case_row)
                is_bill_center = entrypoint == "BILL"
                module = "智能计费/账单中心" if is_bill_center else "智能计费/计费出账"
                if is_bill_center:
                    steps = (
                        f"1. 进入账单中心，选择项目 {settings.project_name}。\n"
                        f"2. 创建仪表类账单，按房间选择 {billing_case.room.room_path}。\n"
                        f"3. 账期设为 ${{BILLING_MONTH}}，选择收费项 {billing_case.charge_item} 和标准 {billing_case.charge_standard}。\n"
                        "4. 新增收费项后点击编辑，设置最晚缴款日并保存；保持系统计费期间。\n"
                        f"5. 提交账单，核对账期、房间、收费项及金额 {expected}。\n"
                        "6. 高级搜索按顺序设置收费项、账期，再将‘收费对象’切换为‘收费对象-房间’，在相邻房间树选择目标房间并确认；‘关联对象’是关联资产的附加条件，按房间清理时留空。按账期+房间+收费项唯一定位本次有效账单，账单编号只作报告证据；若不唯一则停止并报告。勾选目标行，点击‘更多/批量作废’，填写‘${VOID_REASON}’并确认；按相同业务键重查并选中本次已作废账单，点击‘更多/批量删除’并确认；相同组合复查为0条。"
                    )
                else:
                    steps = (
                        "1. 进入计费出账常规类，按房间选择本场景房间。\n"
                        f"2. 开始月份和结束月份均选择 ${{BILLING_MONTH}}，选择收费项 {billing_case.charge_item}。\n"
                        f"3. 完成计算，核对待处理金额 {expected}，再核对并审核通过。\n"
                        "4. 跳转账单中心，打开高级搜索，按顺序设置收费项、账期，再将‘收费对象’切换为‘收费对象-房间’并选择目标房间；‘关联对象’是关联资产的附加条件，按房间清理时留空；按账期+房间+收费项唯一定位本次账单并核对金额。\n"
                        "5. 按相同业务键确认唯一目标后，填写作废原因并批量作废、批量删除；账单编号只作证据、不作筛选条件；相同组合复查为0条。"
                    )
                _write_fields(
                    case_sheet,
                    case_row,
                    {
                        "用例编号": case_id,
                        "一级模块": "云收费",
                        "二级模块": module,
                        "功能点": "仪表类公摊账单出账及清理",
                        "用例名称": f"{room}房间仪表类公摊{('账单中心' if is_bill_center else '计费出账')}、金额断言及清理",
                        "优先级": "P0",
                        "用例类型": "正向",
                        "是否主流程": "是",
                        "前置条件": (
                            f"{billing_case.room.room_path}已关联{billing_case.instrument_name}公摊方案；"
                            "用量和收费标准有效；目标账期没有同房间同收费项账单"
                        ),
                        "操作步骤": steps,
                        "场景引用/覆盖项": f"SCENARIO_ID={scenario_id}",
                        "预期结果": (
                            f"原价及应收金额均为 {expected}；审核通过后账单中心能按业务键查到唯一账单；"
                            "账单中心填写作废原因后批量作废、批量删除；账单编号仅为证据且不作筛选，按相同账期+房间+收费项复查结果为 0；若定位不唯一则停止并报告"
                        ),
                        "账号/角色": "DEFAULT / 测试管理员",
                        "数据影响": "新增后清理",
                        "风险操作": "是，需确认",
                        "自动化状态": "已实现",
                        "依赖条件": "公摊基线方案、公共仪表、抄表用量、客户入住数据及收费标准",
                        "标签": f"regression,billing,public-share,instrument,{entrypoint.lower()}",
                        "维护状态": "有效",
                        "备注": "水表/电表公摊出账专项扩展；按房间与入口分别参数化，不并入原 102 条核心业务矩阵。",
                    },
                )
                written_cases += 1

        workbook.save(WORKBOOK)
        print(f"updated {WORKBOOK}")
        print(f"instrument rooms={len(CASES)}; scenarios={written_scenarios}; cases={written_cases}")
    finally:
        workbook.close()


if __name__ == "__main__":
    main()
