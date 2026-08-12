# -*- coding: utf-8 -*-

"""账本守恒只读校验（#582 PR4 / 收口）。

四条守恒不变量：

1. entry 数量 == Σ聚合成员数量（``aggregation_members[].quantity``）；
   成员缺失（如 flattened/legacy 形态）不判定为违反，只标记 degraded。
2. Σentry slice 数量 == entry 数量（按 entry_id 聚合
   ``om_entry_slices.original_quantity``）。
3. 券商持仓数量 == 账本 open entry 剩余数量（按 symbol，base+t 合并口径）。
4. 归属一致性：``buy_cluster`` entry 及其成员的 ``position_type`` 必须与
   对应 ``om_order_requests.ledger_intent`` 一致（t→t、base→base、
   broker-only/无请求→base）；无法反查订单的成员跳过（degraded 不误报）。

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


def _position_type_of(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"t", "base", "-", "mixed"}:
        return text
    return "base"


def _member_is_broker_evidence(member: dict) -> bool:
    """仅评估能关联真实券商订单的成员（canonical key 或 internal 占位键）。"""

    key = str(member.get("broker_order_key") or "").strip()
    return key.startswith("account:") or key.startswith("ord_")


def check_entry_member_conservation(entries: list[dict]) -> list[dict]:
    """entry.original_quantity 必须等于 Σ成员 quantity（有成员时）。"""

    violations: list[dict] = []
    for entry in list(entries or []):
        members = list(entry.get("aggregation_members") or [])
        if not members:
            continue
        member_quantity = sum(_coerce_int(member.get("quantity")) for member in members)
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
    """券商持仓数量必须等于账本 entry 剩余数量（按 symbol 合并 base+t）。

    计数口径为 ``remaining_quantity > 0``（含 PARTIALLY_EXITED 等非 OPEN 但仍
    持有剩余仓位的 entry，#587：按 status==OPEN 过滤会把部分退出的持仓误报为
    账本 0）；remaining<=0 的 CLOSED/清仓 entry 不参与。
    """

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
        if _coerce_int(entry.get("remaining_quantity")) <= 0:
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


def check_ledger_intent_alignment(
    *,
    entries: list[dict],
    broker_orders: list[dict],
    requests: list[dict],
    orders: list[dict] | None = None,
) -> list[dict]:
    """归属一致性：buy_cluster entry 归属必须与订单 ledger_intent 一致（#582 收口）。

    - 只评估 ``source_ref_type=buy_cluster`` 且有可反查订单成员的 entry；
    - 成员键为 canonical（``account:...``）或 internal（``ord_...``）时按
      broker order → request 反查；``reconciliation_resolution:`` 自愈成员跳过；
    - 反查不到 broker order / request 的成员跳过（degraded，不误报）；
    - broker-only（无请求）预期 base；``ledger_intent=t`` 预期 t；
      ``ledger_intent=base`` 或缺失预期 base；
    - broker-only 成员若 broker order 携带 OM 提交 token（``FQOM`` 前缀），表示
      该订单经 OrderManagement 提交（共享账户镜像机上本地无 request 属预期），
      跳过不误报（#588）；broker order 侧 token 缺失时回退到 ``om_orders``
      同名字段（历史幽灵写入可能抹掉 broker order 侧 token，#588 加固）。
    """

    requests_by_id = {
        str(item.get("request_id") or "").strip(): item
        for item in list(requests or [])
        if str(item.get("request_id") or "").strip()
    }
    brokers_by_key = {
        str(item.get("broker_order_key") or "").strip(): item
        for item in list(broker_orders or [])
        if str(item.get("broker_order_key") or "").strip()
    }
    brokers_by_internal = {
        str(item.get("internal_order_id") or "").strip(): item
        for item in list(broker_orders or [])
        if str(item.get("internal_order_id") or "").strip()
    }
    orders_by_internal = {
        str(item.get("internal_order_id") or "").strip(): item
        for item in list(orders or [])
        if str(item.get("internal_order_id") or "").strip()
    }
    violations: list[dict] = []
    for entry in list(entries or []):
        if str(entry.get("source_ref_type") or "").strip() != "buy_cluster":
            continue
        entry_type = _position_type_of(entry.get("position_type"))
        for member in list(entry.get("aggregation_members") or []):
            if not _member_is_broker_evidence(member):
                continue
            key = str(member.get("broker_order_key") or "").strip()
            broker = brokers_by_key.get(key)
            if broker is None and key.startswith("ord_"):
                broker = brokers_by_internal.get(key)
            if broker is None:
                continue
            token = str(broker.get("broker_correlation_token") or "").strip()
            if not token:
                order_doc = orders_by_internal.get(
                    str(broker.get("internal_order_id") or "").strip()
                )
                token = str(
                    (order_doc or {}).get("broker_correlation_token") or ""
                ).strip()
            request = requests_by_id.get(str(broker.get("request_id") or "").strip())
            if request is None:
                if token.startswith("FQOM"):
                    # 仅限"本地无 request"的镜像机场景：OM 提交订单在镜像机无本地
                    # request 属预期（#588）。提交机（request 存在）不受影响，
                    # 错标仍按 request 分支校验（#588 复审修正）。
                    continue
                expected = "base"
            else:
                intent = str(request.get("ledger_intent") or "").strip().lower()
                if intent == "t":
                    expected = "t"
                elif intent in {"base", ""}:
                    expected = "base"
                else:
                    continue
            member_type = _position_type_of(member.get("position_type"))
            if entry_type != expected or member_type != expected:
                violations.append(
                    {
                        "invariant": "ledger_intent_alignment",
                        "symbol": entry.get("symbol"),
                        "entry_id": entry.get("entry_id"),
                        "entry_type": entry_type,
                        "member_type": member_type,
                        "expected": expected,
                        "broker_order_key": key,
                        "request_id": broker.get("request_id"),
                        "ledger_intent": (request or {}).get("ledger_intent"),
                    }
                )
    return violations


def check_all_ledger_invariants(
    *,
    positions: list[dict] | None = None,
    entries: list[dict] | None = None,
    slices: list[dict] | None = None,
    broker_orders: list[dict] | None = None,
    requests: list[dict] | None = None,
    orders: list[dict] | None = None,
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
        "ledger_intent_alignment": check_ledger_intent_alignment(
            entries=entries,
            broker_orders=list(broker_orders or []),
            requests=list(requests or []),
            orders=list(orders or []),
        ),
    }
