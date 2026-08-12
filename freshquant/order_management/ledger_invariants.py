# -*- coding: utf-8 -*-

"""账本守恒只读校验（#582 PR4）。

三条守恒不变量：

1. entry 数量 == Σ聚合成员数量（``aggregation_members[].quantity``）；
   成员缺失（如 flattened/legacy 形态）不判定为违反，只标记 degraded。
2. Σentry slice 数量 == entry 数量（按 entry_id 聚合
   ``om_entry_slices.original_quantity``）。
3. 券商持仓数量 == 账本 open entry 剩余数量（按 symbol，base+t 合并口径）。

全部为纯函数：只读输入数据，不访问数据库、不修改任何集合，可重复执行。
"""

from __future__ import annotations

from typing import Any


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _normalize_code(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for suffix in (".SH", ".SZ", ".BJ"):
        if text.upper().endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def check_entry_member_conservation(entries: list[dict]) -> list[dict]:
    """entry.original_quantity 必须等于 Σ成员 quantity（有成员时）。"""

    violations: list[dict] = []
    for entry in list(entries or []):
        members = list(entry.get("aggregation_members") or [])
        if not members:
            continue
        member_quantity = sum(
            _coerce_int(member.get("quantity")) for member in members
        )
        original_quantity = _coerce_int(entry.get("original_quantity"))
        if member_quantity != original_quantity:
            violations.append(
                {
                    "invariant": "entry_member_conservation",
                    "symbol": entry.get("symbol"),
                    "entry_id": entry.get("entry_id"),
                    "entry_quantity": original_quantity,
                    "member_quantity": member_quantity,
                }
            )
    return violations


def check_slice_conservation(entries: list[dict], slices: list[dict]) -> list[dict]:
    """Σ slice.original_quantity 必须等于 entry.original_quantity（按 entry）。"""

    quantity_by_entry: dict[str, int] = {}
    for slice_document in list(slices or []):
        entry_id = str(slice_document.get("entry_id") or "").strip()
        if not entry_id:
            continue
        quantity_by_entry[entry_id] = quantity_by_entry.get(entry_id, 0) + _coerce_int(
            slice_document.get("original_quantity")
        )
    violations: list[dict] = []
    for entry in list(entries or []):
        entry_id = str(entry.get("entry_id") or "").strip()
        slice_quantity = quantity_by_entry.get(entry_id, 0)
        original_quantity = _coerce_int(entry.get("original_quantity"))
        if slice_quantity != original_quantity:
            violations.append(
                {
                    "invariant": "slice_conservation",
                    "symbol": entry.get("symbol"),
                    "entry_id": entry_id,
                    "entry_quantity": original_quantity,
                    "slice_quantity": slice_quantity,
                }
            )
    return violations


def check_ledger_vs_positions(positions: list[dict], entries: list[dict]) -> list[dict]:
    """券商持仓数量必须等于账本 open entry 剩余数量（按 symbol 合并 base+t）。"""

    broker_quantity: dict[str, int] = {}
    for position in list(positions or []):
        code = _normalize_code(position.get("stock_code") or position.get("symbol"))
        if not code:
            continue
        broker_quantity[code] = broker_quantity.get(code, 0) + _coerce_int(
            position.get("volume")
        )
    ledger_quantity: dict[str, int] = {}
    for entry in list(entries or []):
        code = _normalize_code(
            entry.get("symbol") or entry.get("stock_code") or entry.get("code")
        )
        if not code:
            continue
        if str(entry.get("status") or "OPEN").upper() != "OPEN":
            continue
        ledger_quantity[code] = ledger_quantity.get(code, 0) + _coerce_int(
            entry.get("remaining_quantity")
        )
    violations: list[dict] = []
    for code in sorted(set(broker_quantity) | set(ledger_quantity)):
        if broker_quantity.get(code, 0) != ledger_quantity.get(code, 0):
            violations.append(
                {
                    "invariant": "ledger_vs_positions",
                    "symbol": code,
                    "broker_quantity": broker_quantity.get(code, 0),
                    "ledger_quantity": ledger_quantity.get(code, 0),
                }
            )
    return violations


def check_all_ledger_invariants(
    *,
    positions: list[dict] | None = None,
    entries: list[dict] | None = None,
    slices: list[dict] | None = None,
) -> dict[str, list[dict]]:
    """汇总执行全部守恒检查，返回按 invariant 分组的违规列表。"""

    entries = list(entries or [])
    return {
        "entry_member_conservation": check_entry_member_conservation(entries),
        "slice_conservation": check_slice_conservation(entries, list(slices or [])),
        "ledger_vs_positions": check_ledger_vs_positions(
            list(positions or []),
            entries,
        ),
    }
