"""运行前业务键守卫：同一账期+房间+收费项已有有效账单时跳过本条。

重跑场景下最重要的一条规则是“不重复创建、不自动删除既有数据”。各入口的
用例在真正写入之前都先按业务键做一次只读查询，命中后记录证据并跳过，而不是
失败或清理，避免把人工核对过的历史账单卷进自动化批次。

平台的高级搜索房间树是懒加载的，偶发会渲染成“暂无数据”，使这条只读查询
本身抛错。此时按“失败安全”处理：登记证据后跳过该条，绝不带着未知状态去创建
账单（宁可少跑一条，也不制造重复账单）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

import pytest


@dataclass(frozen=True, slots=True)
class BillKey:
    """账单业务键：账期 + 房间 + 收费项。"""

    billing_month: str
    room_path: str
    charge_item: str

    def as_dict(self) -> dict[str, str]:
        return {
            "billing_month": self.billing_month,
            "room_path": self.room_path,
            "charge_item": self.charge_item,
        }


def skip_existing_active_bill(
    *,
    case_id: str,
    entrypoint: str,
    key: BillKey,
    numbers: list[str],
    record_property: Callable[..., None],
    extra: dict[str, Any] | None = None,
) -> None:
    """记录既有账单证据并跳过当前用例（不创建、不删除）。"""
    payload: dict[str, Any] = {
        "case_id": case_id,
        "entrypoint": entrypoint,
        **key.as_dict(),
        "existing_bill_numbers": list(numbers),
    }
    if extra:
        payload.update(extra)
    record_property(
        "preexisting_active_bill",
        json.dumps(payload, ensure_ascii=False),
    )
    pytest.skip(
        f"{case_id} 运行前已存在同账期+房间+收费项的有效账单 {numbers}；"
        "保留既有数据，不重复创建、不自动删除，本条跳过。"
    )


def ensure_no_active_bill(
    *,
    case_id: str,
    entrypoint: str,
    key: BillKey,
    record_property: Callable[..., None],
    query: Callable[[], list[str]],
    reset: Callable[[], None] | None = None,
) -> None:
    """只读预检：无有效账单则继续，有则跳过，查询失败也跳过（失败安全）。

    ``query`` 返回该业务键下的有效账单号列表；``reset`` 在第一次查询失败时
    重新进入目标页面（例如重开账单中心），用干净页面重试一次。
    """
    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            numbers = query()
        except Exception as error:  # 文本/懒加载类 UI 抖动都归到这一类
            last_error = error
            if reset is not None and attempt == 1:
                try:
                    reset()
                except Exception:
                    pass
                continue
            break
        if numbers:
            skip_existing_active_bill(
                case_id=case_id,
                entrypoint=entrypoint,
                key=key,
                numbers=numbers,
                record_property=record_property,
            )
        return
    record_property(
        "precheck_unavailable",
        json.dumps(
            {
                "case_id": case_id,
                "entrypoint": entrypoint,
                **key.as_dict(),
                "error": f"{type(last_error).__name__}: {last_error}"[:800],
            },
            ensure_ascii=False,
        ),
    )
    pytest.skip(
        f"{case_id} 运行前的业务键预检查询失败"
        f"（{type(last_error).__name__}），无法确认是否已有有效账单；"
        "为避免重复创建，本条跳过，请人工复核该账期+房间+收费项。"
    )
