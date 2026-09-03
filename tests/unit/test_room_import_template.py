from __future__ import annotations

from scripts.update_room_import_template import formula_mappings, room_names


def test_room_names_cover_all_formula_variants_without_duplicates() -> None:
    names = room_names()

    assert len(names) == 60
    assert len(set(names)) == 60
    assert names == [str(value) for value in range(1001, 1061)]


def test_every_billing_area_formula_is_expanded_to_three_rooms() -> None:
    mappings = formula_mappings()
    standard_names = [item.standard_name for item in mappings]

    for stem in (
        "周期常用公式（月单价*{}*月数）",
        "周期阶梯计费（对应月单价*{}*月数）",
        "周期系数公式（月单价*{}*月数*系数）",
        "UI临时类-天数公式（天单价*{}*天数）",
    ):
        assert all(
            any(name.startswith(stem.format(area)) for name in standard_names)
            for area in ("建筑面积", "使用面积", "收费面积")
        )

    assert {
        "押金类-面积公式（计费面积*单价）建筑",
        "押金类-面积公式（计费面积*单价）使用",
        "押金类-面积公式（计费面积*单价）收费",
    }.issubset(standard_names)


def test_mapping_keeps_formula_and_area_meaning() -> None:
    mappings = formula_mappings()

    assert mappings[0].room_name == "1001"
    assert mappings[0].charge_type == "周期类"
    assert mappings[0].formula == "周期常用公式（月单价*计费面积*月数）"
    assert mappings[0].area_type == "建筑面积"
    assert mappings[0].partial_month_rule == "按天"
    assert mappings[0].standard_name == "周期常用公式（月单价*建筑面积*月数）-按天"


def test_every_periodic_mapping_has_a_separate_full_month_room() -> None:
    mappings = formula_mappings()
    periodic = [item for item in mappings if item.charge_type == "周期类"]

    assert len(periodic) == 22
    full_month = [item for item in periodic if item.partial_month_rule == "按满月"]
    assert len(full_month) == 11
    assert full_month[0].room_name == "1048"
    assert full_month[0].area_type == "建筑面积"
    assert full_month[0].standard_name == "周期常用公式（月单价*建筑面积*月数）-按满月"
    daily = [item for item in periodic if item.partial_month_rule == "按天"]
    assert len(daily) == 11
    assert [item.room_name for item in full_month] == [
        str(value) for value in range(1048, 1059)
    ]
    assert [item.standard_name.removesuffix("-按满月") for item in full_month] == [
        item.standard_name.removesuffix("-按天") for item in daily
    ]


def test_deposit_formula_parameters_are_structured() -> None:
    deposits = {
        item.room_name: item for item in formula_mappings()
        if item.charge_type == "押金类"
    }

    assert deposits["1021"].calculation_parameters == "无"
    assert deposits["1022"].calculation_parameters == "固定金额=1000"
    assert deposits["1023"].calculation_parameters == "单价=100"
    for room in ("1024", "1025", "1026"):
        assert deposits[room].calculation_parameters == "单价=10"

    assert deposits["1021"].charge_item == "押金类收费项"
    assert [deposits[room].standard_name for room in ("1024", "1025", "1026")] == [
        "押金类-面积公式（计费面积*单价）建筑",
        "押金类-面积公式（计费面积*单价）使用",
        "押金类-面积公式（计费面积*单价）收费",
    ]


def test_temporary_formula_names_and_parameters_are_structured() -> None:
    temporary = [
        item for item in formula_mappings() if item.charge_type == "临时类"
    ]

    assert len(temporary) == 11
    assert all(item.standard_name.startswith("UI临时类-") for item in temporary)
    assert [
        item.room_name for item in temporary
        if item.formula == "面积多阶梯固定金额（不同面积，不同固定金额）"
    ] == ["1013", "1059", "1060"]
    parameters = {item.formula: item.calculation_parameters for item in temporary}
    assert parameters["仪表无阶梯（固定单价*用量*系数）"] == "单价=3;系数=2"
    assert parameters["固定金额"] == "固定金额=100"
    assert parameters["天数公式（天单价*计费面积*天数）"] == "单价=200"
    assert parameters["数量公式（数量*单价）"] == "单价=20"


def test_commission_formula_parameters_are_structured() -> None:
    commissions = {
        item.room_name: item for item in formula_mappings()
        if item.charge_type == "抽成类"
    }

    assert list(commissions) == ["1027", "1028", "1029", "1030", "1031"]
    assert commissions["1027"].calculation_parameters == "抽成比例=10%"
    assert commissions["1028"].calculation_parameters == (
        "抽成比例阶梯=0-10000:10%;10000-20000:20%;20000以上:25%"
    )
    assert commissions["1029"].calculation_parameters == (
        "抽成比例阶梯=0-10000:10%;10000-20000:20%;20000以上:25%"
    )
    assert commissions["1030"].calculation_parameters == "无"
    assert commissions["1031"].calculation_parameters == (
        "抽成金额阶梯=0-10000:1000;10000以上:2000"
    )
    assert [item.standard_name for item in commissions.values()] == [
        "抽成类-计费周期收入比例抽成",
        "抽成类-计费周期收入阶梯抽成-比例",
        "抽成类-合作期收入阶梯抽成-比例",
        "抽成类-自定义抽成金额",
        "抽成类-计费周期收入阶梯抽成-固定金额",
    ]
    assert all(len(item.standard_name) <= 30 for item in commissions.values())
    assert commissions["1027"].creation_policy == "创建"
    assert all(
        commissions[room].creation_policy
        == "不创建-当前代码限制一个抽成收费项仅一个标准"
        for room in ("1028", "1029", "1030", "1031")
    )
