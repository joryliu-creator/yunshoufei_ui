from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "python"))
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo


WORKBOOK = ROOT / "房间导入模版.xlsx"
MAPPING_WORKBOOK = ROOT / "房间收费标准映射表.xlsx"
AREA_TYPES = ("建筑面积", "使用面积", "收费面积")
PARTIAL_MONTH_RULES = ("按天", "按满月")
CHARGE_ITEM_NAMES = {
    "周期类": "UI周期性收费项",
    "临时类": "UI临时类收费项",
    "押金类": "押金类收费项",
    "抽成类": "UI抽成类收费项",
    "水表仪表类": "UI仪表类收费项-水表",
    "电表仪表类": "UI仪表类收费项-电表",
}
FULL_MONTH_FORMULA = "周期常用公式（月单价*计费面积*月数）"
PERIODIC_FORMULA_PARAMETERS = {
    FULL_MONTH_FORMULA: "月单价=10",
    "周期固定金额（月固定金额*月数）": "月固定金额=10",
    "周期阶梯计费（对应月单价*计费面积*月数）": (
        "楼层阶梯=1-10:2;11-20:3"
    ),
    "周期系数公式（月单价*计费面积*月数*系数）": (
        "月单价=3;系数=2"
    ),
    "周期系数公式（月固定金额*月数*系数）": (
        "月固定金额=3;系数=2"
    ),
}
METER_FORMULA_PARAMETERS = {
    "仪表无阶梯（固定单价*用量）": "单价=2",
    "仪表多阶梯多单价（阶梯单价*用量 ；年清用量）": (
        "用量阶梯=0-10:1.5;10以上:2"
    ),
    "仪表无阶梯（固定单价*用量*系数）": "单价=3;系数=2",
    "仪表多阶梯多系数（固定单价*用量*阶梯系数）": (
        "单价=2;楼层阶梯=1-10:2;11及以上:3"
    ),
    "仪表累计用量计费（累计用量对应单价*用量）": (
        "累计用量阶梯=0-10:1.5;10以上:2;合并客户所有房间用量=开启"
    ),
    "仪表多阶梯多单价（阶梯单价*用量 ；月清用量）": (
        "用量阶梯=0-10:1.5;10以上:2"
    ),
}
DEPOSIT_FORMULA_PARAMETERS = {
    "人工输入收费金额": "无",
    "固定金额": "固定金额=1000",
    "数量公式（数量*单价）": "单价=100",
    "面积公式（计费面积*单价）": "单价=10",
}
COMMISSION_FORMULA_PARAMETERS = {
    "计费周期收入比例抽成（计费周期内营业额*固定抽成比例）": (
        "抽成比例=10%"
    ),
    "计费周期收入阶梯抽成（计费周期内营业额*对应抽成比例）": (
        "抽成比例阶梯=0-10000:10%;10000-20000:20%;20000以上:25%"
    ),
    "合作期收入阶梯抽成（合作期总营业额*对应抽成比例）": (
        "抽成比例阶梯=0-10000:10%;10000-20000:20%;20000以上:25%"
    ),
    "自定义抽成金额": "无",
    "计费周期收入阶梯抽成（计费周期内营业额对应固定抽成金额）": (
        "抽成金额阶梯=0-10000:1000;10000以上:2000"
    ),
}
COMMISSION_STANDARD_NAMES = {
    "计费周期收入比例抽成（计费周期内营业额*固定抽成比例）": (
        "抽成类-计费周期收入比例抽成"
    ),
    "计费周期收入阶梯抽成（计费周期内营业额*对应抽成比例）": (
        "抽成类-计费周期收入阶梯抽成-比例"
    ),
    "合作期收入阶梯抽成（合作期总营业额*对应抽成比例）": (
        "抽成类-合作期收入阶梯抽成-比例"
    ),
    "自定义抽成金额": "抽成类-自定义抽成金额",
    "计费周期收入阶梯抽成（计费周期内营业额对应固定抽成金额）": (
        "抽成类-计费周期收入阶梯抽成-固定金额"
    ),
}
COMMISSION_CREATION_POLICIES = {
    "计费周期收入比例抽成（计费周期内营业额*固定抽成比例）": "创建",
    "计费周期收入阶梯抽成（计费周期内营业额*对应抽成比例）": (
        "不创建-当前代码限制一个抽成收费项仅一个标准"
    ),
    "合作期收入阶梯抽成（合作期总营业额*对应抽成比例）": (
        "不创建-当前代码限制一个抽成收费项仅一个标准"
    ),
    "自定义抽成金额": "不创建-当前代码限制一个抽成收费项仅一个标准",
    "计费周期收入阶梯抽成（计费周期内营业额对应固定抽成金额）": (
        "不创建-当前代码限制一个抽成收费项仅一个标准"
    ),
}
TEMPORARY_FORMULA_PARAMETERS = {
    "仪表无阶梯（固定单价*用量*系数）": "单价=3;系数=2",
    "面积多阶梯固定金额（不同面积，不同固定金额）": (
        "面积固定金额阶梯=0-200:10;200以上:15"
    ),
    "楼层多阶梯固定金额（不同楼层，不同固定金额）": (
        "楼层固定金额阶梯=1-10:100;11-20:200"
    ),
    "人工输入收费金额": "无",
    "固定金额": "固定金额=100",
    "天数公式（天单价*计费面积*天数）": "单价=200",
    "数量公式（数量*单价）": "单价=20",
}

CATEGORY_FORMULAS = {
    # 保留用户已填写的前三条命名格式，不增加类别前缀。
    "": [
        "周期常用公式（月单价*计费面积*月数）",
        "周期固定金额（月固定金额*月数）",
        "周期阶梯计费（对应月单价*计费面积*月数）",
        "周期系数公式（月单价*计费面积*月数*系数）",
        "周期系数公式（月固定金额*月数*系数）",
    ],
    "临时类-": [
        "仪表无阶梯（固定单价*用量*系数）",
        "面积多阶梯固定金额（不同面积，不同固定金额）",
        "楼层多阶梯固定金额（不同楼层，不同固定金额）",
        "人工输入收费金额",
        "固定金额",
        "天数公式（天单价*计费面积*天数）",
        "数量公式（数量*单价）",
    ],
    "押金类-": [
        "人工输入收费金额",
        "固定金额",
        "数量公式（数量*单价）",
        "面积公式（计费面积*单价）",
    ],
    "抽成类-": [
        "计费周期收入比例抽成（计费周期内营业额*固定抽成比例）",
        "计费周期收入阶梯抽成（计费周期内营业额*对应抽成比例）",
        "合作期收入阶梯抽成（合作期总营业额*对应抽成比例）",
        "自定义抽成金额",
        "计费周期收入阶梯抽成（计费周期内营业额对应固定抽成金额）",
    ],
    "水表仪表类-": [
        "仪表无阶梯（固定单价*用量）",
        "仪表多阶梯多单价（阶梯单价*用量 ；年清用量）",
        "仪表无阶梯（固定单价*用量*系数）",
        "仪表多阶梯多系数（固定单价*用量*阶梯系数）",
        "仪表多时段多单价（时段对应单价*用量）",
        "仪表累计用量计费（累计用量对应单价*用量）",
        "仪表多阶梯多单价（阶梯单价*用量 ；月清用量）",
        "固定金额",
    ],
    "电表仪表类-": [
        "仪表无阶梯（固定单价*用量）",
        "仪表多阶梯多单价（阶梯单价*用量 ；年清用量）",
        "仪表无阶梯（固定单价*用量*系数）",
        "仪表多阶梯多系数（固定单价*用量*阶梯系数）",
        "仪表多时段多单价（时段对应单价*用量）",
        "仪表累计用量计费（累计用量对应单价*用量）",
        "仪表多阶梯多单价（阶梯单价*用量 ；月清用量）",
        "固定金额",
    ],
}

CATEGORY_TYPES = {
    "": "周期类",
    "临时类-": "临时类",
    "押金类-": "押金类",
    "抽成类-": "抽成类",
    "水表仪表类-": "水表仪表类",
    "电表仪表类-": "电表仪表类",
}


@dataclass(frozen=True, slots=True)
class FormulaMapping:
    room_name: str
    charge_type: str
    charge_item: str
    formula: str
    area_type: str
    partial_month_rule: str
    standard_name: str
    calculation_parameters: str
    creation_policy: str


def formula_mappings() -> list[FormulaMapping]:
    mappings: list[FormulaMapping] = []
    for prefix, formulas in CATEGORY_FORMULAS.items():
        for formula in formulas:
            if formula == "面积多阶梯固定金额（不同面积，不同固定金额）":
                # 保留既有房间编号：主序列先放建筑面积，另外两种面积在
                # 既有 1001～1058 映射之后追加为 1059、1060。
                area_types = (AREA_TYPES[0],)
            else:
                area_types = AREA_TYPES if "计费面积" in formula else ("",)
            for area_type in area_types:
                rules = (PARTIAL_MONTH_RULES[0],) if not prefix else ("",)
                for partial_month_rule in rules:
                    standard_formula = formula
                    if area_type:
                        standard_formula = standard_formula.replace(
                            "计费面积", area_type
                        ).replace("不同面积", f"不同{area_type}")
                    rule_suffix = (
                        f"-{partial_month_rule}" if partial_month_rule else ""
                    )
                    charge_type = CATEGORY_TYPES[prefix]
                    standard_name = (
                        COMMISSION_STANDARD_NAMES[formula]
                        if charge_type == "抽成类"
                        # 押金类面积公式在系统中统一保留“计费面积”字样，
                        # 再以 建筑/使用/收费 区分三个标准。
                        else f"押金类-{formula}{area_type.removesuffix('面积')}"
                        if (
                            charge_type == "押金类"
                            and formula == "面积公式（计费面积*单价）"
                        )
                        else (
                            f"{'UI' if charge_type == '临时类' else ''}"
                            f"{prefix}{standard_formula}{rule_suffix}"
                        )
                    )
                    mappings.append(
                        FormulaMapping(
                            room_name=str(1001 + len(mappings)),
                            charge_type=charge_type,
                            charge_item=CHARGE_ITEM_NAMES[charge_type],
                            formula=formula,
                            area_type=area_type,
                            partial_month_rule=partial_month_rule,
                            # 计费公式保留系统原名，收费标准名称中的
                            # “计费面积”替换为实际面积，并追加不足月规则。
                            standard_name=standard_name,
                            calculation_parameters=(
                                PERIODIC_FORMULA_PARAMETERS.get(formula, "")
                                if CATEGORY_TYPES[prefix] == "周期类"
                                else TEMPORARY_FORMULA_PARAMETERS.get(formula, "")
                                if CATEGORY_TYPES[prefix] == "临时类"
                                else DEPOSIT_FORMULA_PARAMETERS.get(formula, "")
                                if CATEGORY_TYPES[prefix] == "押金类"
                                else COMMISSION_FORMULA_PARAMETERS.get(
                                    formula, ""
                                )
                                if CATEGORY_TYPES[prefix] == "抽成类"
                                else METER_FORMULA_PARAMETERS.get(
                                    formula, ""
                                )
                                if CATEGORY_TYPES[prefix]
                                in {"水表仪表类", "电表仪表类"}
                                else ""
                            ),
                            creation_policy=(
                                COMMISSION_CREATION_POLICIES[formula]
                                if CATEGORY_TYPES[prefix] == "抽成类"
                                else "不创建"
                                if CATEGORY_TYPES[prefix]
                                in {"水表仪表类", "电表仪表类"}
                                and formula == "固定金额"
                                else "待补充参数"
                                if CATEGORY_TYPES[prefix]
                                in {"水表仪表类", "电表仪表类"}
                                and formula.startswith("仪表多时段多单价")
                                else "创建"
                            ),
                        )
                    )
    periodic_daily = [
        item for item in mappings if item.charge_type == "周期类"
    ]
    for daily in periodic_daily:
        mappings.append(
            FormulaMapping(
                room_name=str(1001 + len(mappings)),
                charge_type=daily.charge_type,
                charge_item=daily.charge_item,
                formula=daily.formula,
                area_type=daily.area_type,
                partial_month_rule=PARTIAL_MONTH_RULES[1],
                standard_name=(
                    daily.standard_name.removesuffix("-按天") + "-按满月"
                ),
                calculation_parameters=daily.calculation_parameters,
                creation_policy="创建",
            )
        )
    temporary_area_formula = "面积多阶梯固定金额（不同面积，不同固定金额）"
    for area_type in AREA_TYPES[1:]:
        mappings.append(
            FormulaMapping(
                room_name=str(1001 + len(mappings)),
                charge_type="临时类",
                charge_item=CHARGE_ITEM_NAMES["临时类"],
                formula=temporary_area_formula,
                area_type=area_type,
                partial_month_rule="",
                standard_name=(
                    "UI临时类-"
                    + temporary_area_formula.replace(
                        "不同面积", f"不同{area_type}"
                    )
                ),
                calculation_parameters=TEMPORARY_FORMULA_PARAMETERS[
                    temporary_area_formula
                ],
                creation_policy="创建",
            )
        )
    room_ids = [item.room_name for item in mappings]
    if len(room_ids) != len(set(room_ids)):
        raise ValueError("生成的房间编号存在重复。")
    return mappings


def room_names() -> list[str]:
    return [item.room_name for item in formula_mappings()]


def copy_cell(source, target) -> None:
    target.value = source.value
    if source.has_style:
        target._style = copy(source._style)
    target.number_format = source.number_format
    target.protection = copy(source.protection)
    target.alignment = copy(source.alignment)
    target.comment = copy(source.comment)
    if source.hyperlink:
        target._hyperlink = copy(source.hyperlink)


def write_mapping_workbook(mappings: list[FormulaMapping]) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "房间收费标准映射"
    headers = (
        "序号",
        "房间名称",
        "收费类型",
        "收费项",
        "计费公式",
        "计费面积类型",
        "不足月计费规则",
        "建议收费标准名称",
        "计价参数",
        "创建策略",
        "备注",
    )
    worksheet.append(headers)
    for index, item in enumerate(mappings, 1):
        worksheet.append(
            (
                index,
                item.room_name,
                item.charge_type,
                item.charge_item,
                item.formula,
                item.area_type,
                item.partial_month_rule,
                item.standard_name,
                item.calculation_parameters,
                item.creation_policy,
                "按公式截图整理；创建收费标准并绑定对应房间后补充实际标准编码",
            )
        )

    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    widths = (10, 14, 16, 22, 52, 16, 18, 62, 34, 16, 48)
    for column, width in enumerate(widths, 1):
        worksheet.column_dimensions[
            worksheet.cell(1, column).column_letter
        ].width = width
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = f"A1:K{worksheet.max_row}"
    table = Table(
        displayName="RoomChargeStandardMapping",
        ref=f"A1:K{worksheet.max_row}",
    )
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    worksheet.add_table(table)
    workbook.save(MAPPING_WORKBOOK)
    workbook.close()


def main() -> None:
    if not WORKBOOK.exists():
        raise FileNotFoundError(f"未找到房间导入模板：{WORKBOOK}")
    workbook = load_workbook(WORKBOOK)
    worksheet = workbook["Sheet1"]
    if worksheet.max_column != 19 or "房间号" not in str(
        worksheet.cell(1, 3).value
    ):
        raise ValueError("房间导入模板结构与预期不一致，已停止覆盖。")

    mappings = formula_mappings()
    names = [item.room_name for item in mappings]
    template_row = 2
    for offset, name in enumerate(names):
        target_row = template_row + offset
        for column in range(1, worksheet.max_column + 1):
            copy_cell(
                worksheet.cell(template_row, column),
                worksheet.cell(target_row, column),
            )
        worksheet.cell(target_row, 3, name)
        worksheet.row_dimensions[target_row].height = (
            worksheet.row_dimensions[template_row].height
        )

    for row in range(template_row + len(names), worksheet.max_row + 1):
        for column in range(1, worksheet.max_column + 1):
            worksheet.cell(row, column).value = None

    workbook.save(WORKBOOK)
    workbook.close()
    write_mapping_workbook(mappings)
    print(f"updated={WORKBOOK}")
    print(f"mapping={MAPPING_WORKBOOK}")
    print(f"room_count={len(names)}")


if __name__ == "__main__":
    main()
