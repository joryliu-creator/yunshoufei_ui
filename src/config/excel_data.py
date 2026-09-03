from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
try:
    from openpyxl import load_workbook
except ModuleNotFoundError:  # 本地兼容尚未重新安装 requirements 的工作区
    sys.path.insert(0, str(ROOT / ".tools" / "python"))
    from openpyxl import load_workbook


DEFAULT_WORKBOOK = ROOT / "UI自动化回归测试用例模板_Demo.xlsx"
VARIABLE_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


@dataclass(frozen=True, slots=True)
class ChargeScenarioData:
    scenario_id: str
    environment: str
    customer_id: str
    project_name: str
    room_path: str
    charge_type: str
    charge_item: str
    charge_standard: str
    formula: str
    calculation_parameters: str
    suggested_billing_month: str
    discount_config: str
    expected_original_amount: str
    expected_discount_amount: str
    expected_receivable_amount: str


@dataclass(frozen=True, slots=True)
class ExcelTestData:
    scenario: ChargeScenarioData
    runtime_parameters: dict[str, str]


@dataclass(frozen=True, slots=True)
class CaseDataReference:
    case_id: str
    scenario_id: str
    account_role: str


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _header_map(worksheet: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for column in range(1, worksheet.max_column + 1):
        raw_header = _text(worksheet.cell(1, column).value)
        if not raw_header:
            continue
        first_line = raw_header.splitlines()[0].rstrip("*").strip()
        result[first_line] = column
        variable = VARIABLE_PATTERN.search(raw_header)
        if variable:
            result[variable.group(1)] = column
    return result


def _required_column(headers: dict[str, int], name: str) -> int:
    if name not in headers:
        raise ValueError(f"Excel 缺少必需列 {name!r}。")
    return headers[name]


def _load_scenario(
    workbook: Any,
    environment: str,
    customer_id: str,
    scenario_id: str,
) -> ChargeScenarioData:
    if "收费场景配置" not in workbook.sheetnames:
        raise ValueError("Excel 缺少“收费场景配置”工作表。")
    worksheet = workbook["收费场景配置"]
    headers = _header_map(worksheet)
    id_column = _required_column(headers, "场景编号")
    matches = [
        row
        for row in range(2, worksheet.max_row + 1)
        if _text(worksheet.cell(row, id_column).value) == scenario_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"场景编号 {scenario_id!r} 应唯一存在，实际匹配 {len(matches)} 行。"
        )
    row = matches[0]

    def value(name: str) -> str:
        return _text(worksheet.cell(row, _required_column(headers, name)).value)

    scenario_environment = value("环境")
    scenario_customer = value("客户号")
    if scenario_environment != environment or scenario_customer != customer_id:
        raise ValueError(
            f"场景 {scenario_id!r} 属于环境 {scenario_environment!r}、"
            f"客户 {scenario_customer!r}，与本次运行不一致。"
        )
    maintenance_status = value("维护状态")
    # 场景维护状态允许追加审核结论（如“已核验-通过”）；只要基础
    # 状态为已核验即可执行，避免状态备注使已确认场景无法加载。
    if not maintenance_status.startswith("已核验") or value("是否启用") != "是":
        raise ValueError(
            f"场景 {scenario_id!r} 尚未同时满足“已核验且启用”。"
        )

    required_variables = {
        name: value(name)
        for name in ("PROJECT_NAME", "ROOM_PATH", "CHARGE_TYPE", "CHARGE_ITEM")
    }
    missing = [name for name, item in required_variables.items() if not item]
    if missing:
        raise ValueError(
            f"场景 {scenario_id!r} 缺少步骤变量：{', '.join(missing)}。"
        )

    return ChargeScenarioData(
        scenario_id=scenario_id,
        environment=scenario_environment,
        customer_id=scenario_customer,
        project_name=required_variables["PROJECT_NAME"],
        room_path=required_variables["ROOM_PATH"],
        charge_type=required_variables["CHARGE_TYPE"],
        charge_item=required_variables["CHARGE_ITEM"],
        charge_standard=value("收费标准"),
        formula=value("计费公式"),
        calculation_parameters=value("计算参数"),
        suggested_billing_month=value("建议测试账期"),
        discount_config=value("减免配置"),
        expected_original_amount=value("预期原始金额"),
        expected_discount_amount=value("预期减免金额"),
        expected_receivable_amount=value("预期应收金额"),
    )


def _load_runtime_parameters(
    workbook: Any, environment: str, customer_id: str
) -> dict[str, str]:
    if "运行参数" not in workbook.sheetnames:
        raise ValueError("Excel 缺少“运行参数”工作表。")
    worksheet = workbook["运行参数"]
    headers = _header_map(worksheet)
    columns = {
        name: _required_column(headers, name)
        for name in ("环境", "客户号", "参数名", "默认值", "维护状态")
    }
    parameters: dict[str, str] = {}
    for row in range(2, worksheet.max_row + 1):
        row_environment = _text(
            worksheet.cell(row, columns["环境"]).value
        )
        row_customer = _text(
            worksheet.cell(row, columns["客户号"]).value
        )
        status = _text(worksheet.cell(row, columns["维护状态"]).value)
        if status != "有效":
            continue
        if row_environment not in {"", environment}:
            continue
        if row_customer not in {"", customer_id}:
            continue
        name = _text(worksheet.cell(row, columns["参数名"]).value)
        if not name:
            continue
        if name in parameters:
            raise ValueError(
                f"运行参数 {name!r} 在环境 {environment!r}、"
                f"客户 {customer_id!r} 下重复。"
            )
        parameters[name] = _text(
            worksheet.cell(row, columns["默认值"]).value
        )
    return parameters


def _load_case_reference(
    workbook: Any, case_id: str
) -> CaseDataReference:
    if "用例清单" not in workbook.sheetnames:
        raise ValueError("Excel 缺少“用例清单”工作表。")
    worksheet = workbook["用例清单"]
    headers = _header_map(worksheet)
    id_column = _required_column(headers, "用例编号")
    reference_column = _required_column(headers, "场景引用/覆盖项")
    role_column = _required_column(headers, "账号/角色")
    matches = [
        row
        for row in range(2, worksheet.max_row + 1)
        if _text(worksheet.cell(row, id_column).value) == case_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"用例编号 {case_id!r} 应唯一存在，实际匹配 {len(matches)} 行。"
        )
    row = matches[0]
    reference_text = _text(worksheet.cell(row, reference_column).value)
    match = re.search(
        r"(?:^|\n)SCENARIO_ID\s*=\s*([^\s]+)", reference_text
    )
    if not match:
        raise ValueError(f"用例 {case_id!r} 未配置 SCENARIO_ID。")
    role_text = _text(worksheet.cell(row, role_column).value)
    account_role = role_text.split("/", 1)[0].strip().lower()
    if not account_role:
        raise ValueError(f"用例 {case_id!r} 未配置账号/角色别名。")
    return CaseDataReference(
        case_id=case_id,
        scenario_id=match.group(1).strip(),
        account_role=account_role,
    )


def load_case_reference(
    case_id: str,
    workbook_path: Path | None = None,
) -> CaseDataReference:
    path = workbook_path or DEFAULT_WORKBOOK
    if not path.exists():
        raise FileNotFoundError(f"测试数据 Excel 不存在：{path}")
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        return _load_case_reference(workbook, case_id)
    finally:
        workbook.close()


def load_excel_test_data(
    environment: str,
    customer_id: str,
    scenario_id: str,
    workbook_path: Path | None = None,
) -> ExcelTestData:
    path = workbook_path or DEFAULT_WORKBOOK
    if not path.exists():
        raise FileNotFoundError(f"测试数据 Excel 不存在：{path}")
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        scenario = _load_scenario(
            workbook, environment, customer_id, scenario_id
        )
        runtime_parameters = _load_runtime_parameters(
            workbook, environment, customer_id
        )
    finally:
        workbook.close()
    return ExcelTestData(
        scenario=scenario,
        runtime_parameters=runtime_parameters,
    )
