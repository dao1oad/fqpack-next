# -*- coding: utf-8 -*-
"""存量双账本归一回填（Issue #571 根治方案 v4，步骤 1）。

在读侧切换前把存量数据归一为最终架构字段，避免 LedgerResolver 内置隐式默认：

1. ``om_order_requests.ledger_intent``：对缺失的 buy/sell 请求做一次性推导
   （仅迁移用途，运行期判定不再读旧字段）：
   - sell：TPSL 止盈（source/scope_type）→ base；stoploss → ``-``；
     Guardian 做T（guardian_sell_sources）→ t；手动/网页/api/cli → ``-``；
   - buy：base_line / new_open / 手动/网页/api/cli → base；holding_add → t；
   - buy flatten 重建（严格证据组合：``source=order_ledger_rebuild`` 且
     ``rebuild_source=position_snapshot_flatten`` 且 ``rebuilt_open=True``）
     → base；任一字段缺失/不匹配仍 fail-closed；
   - **无法从确定证据推导（如空/未知 buy path + strategy source）时在
     dry-run/execute 中显式冲突并停止**，不得静默归 base（fail-closed）。
2. ``om_position_entries / om_entry_slices``：缺失 ``position_type`` 补 base
   （已有 ``t`` 保留不覆盖）；``aggregation_members[]`` 按 entry 同步
   ``position_type``（A6 可审计）。

守恒校验（默认 dry-run 输出，execute 后强制复验）：
- L1：entry 与 slices 数量守恒（original/remaining 逐 entry 对齐）；
- S1：slice remaining <= original；
- D1：base/t 双账本 entry↔slice 分账本守恒；
- allocation_integrity（L2 引用/数量守恒）复用
  ``freshquant.order_management.allocation_integrity``；
- 幂等：重复执行变更数为 0。

用法：
    python script/maintenance/backfill_ledger_intent.py --dry-run
    python script/maintenance/backfill_ledger_intent.py --execute [--backup-db <name>]
"""

from __future__ import annotations

from collections import defaultdict

import click

from freshquant.order_management.allocation_integrity import (
    find_exit_allocation_integrity_errors,
)
from freshquant.order_management.db import get_order_management_db
from freshquant.order_management.entry_adapter import (
    POSITION_TYPE_BASE,
    POSITION_TYPE_T,
    position_type_of,
)
from freshquant.order_management.ledger_resolver import (
    LEDGER_BASE,
    LEDGER_T,
    LEDGER_UNSPECIFIED,
    is_takeprofit_request,
    normalize_ledger_intent,
)
from freshquant.order_management.tracking.order_state import OrderStateService

_BUY_BASE_EVIDENCE_SOURCES = {
    "manual",
    "manual_import",
    "reset",
    "manual_reset",
    "manual_locked",
    "api",
    "web",
    "web-order",
    "cli",
    "external",
}
_SELL_UNSPECIFIED_SOURCES = _BUY_BASE_EVIDENCE_SOURCES
_REBUILD_FLATTEN_SOURCE = "order_ledger_rebuild"
_REBUILD_FLATTEN_REBUILD_SOURCE = "position_snapshot_flatten"


def _derive_ledger_intent(request) -> tuple[str | None, str | None]:
    """一次性推导（仅回填迁移用途）。

    返回 ``(ledger_intent, unresolved_reason)``：无法从确定证据推导时返回
    ``(None, reason)``，调用方必须显式冲突并停止，不提供隐式默认。
    """

    action = str((request or {}).get("action") or "").strip().lower()
    if action not in {"buy", "sell"}:
        return None, None
    context = dict((request or {}).get("strategy_context") or {})
    source = str((request or {}).get("source") or "").strip().lower()
    if action == "sell":
        scope_type = str((request or {}).get("scope_type") or "").strip().lower()
        if is_takeprofit_request(request):
            return LEDGER_BASE, None
        if "stoploss" in scope_type:
            return LEDGER_UNSPECIFIED, None
        if context.get("guardian_sell_sources"):
            return LEDGER_T, None
        if source in _SELL_UNSPECIFIED_SOURCES:
            return LEDGER_UNSPECIFIED, None
        return (
            None,
            f"sell 无法确定归属（source={source!r}，无 TP/stoploss/"
            "guardian_sell_sources 证据）",
        )
    # 严格证据组合：持仓快照 flatten 重建的 broker-only open entry 确定归
    # base；action/source/rebuild_source/rebuilt_open 任一缺失或不匹配仍
    # fail-closed（unresolved），不做字段缺省推断。
    if (
        source == _REBUILD_FLATTEN_SOURCE
        and str((request or {}).get("rebuild_source") or "").strip().lower()
        == _REBUILD_FLATTEN_REBUILD_SOURCE
        and (request or {}).get("rebuilt_open") is True
    ):
        return LEDGER_BASE, None
    buy_ledger = str(context.get("buy_ledger") or "").strip().lower()
    grid = dict(context.get("guardian_buy_grid") or {})
    path = str(grid.get("path") or "").strip().lower()
    if buy_ledger == "base_line" or path == "base_line":
        return LEDGER_BASE, None
    if path == "new_open":
        return LEDGER_BASE, None
    if path == "holding_add":
        return LEDGER_T, None
    if source in _BUY_BASE_EVIDENCE_SOURCES:
        return LEDGER_BASE, None
    return (
        None,
        f"buy 无法确定归属（guardian_buy_grid.path={path!r}，" f"source={source!r}）",
    )


def _collect_request_updates(database):
    """返回 (待更新列表, unresolved 列表)。unresolved 时必须显式停止。"""

    updates = []
    unresolved = []
    for request in database["om_order_requests"].find({}):
        if normalize_ledger_intent(request.get("ledger_intent")) is not None:
            continue
        intent, unresolved_reason = _derive_ledger_intent(request)
        if intent is None:
            if unresolved_reason is not None:
                unresolved.append(
                    {
                        "request_id": request.get("request_id"),
                        "action": request.get("action"),
                        "reason": unresolved_reason,
                    }
                )
            continue
        updates.append(
            {
                "request_id": request.get("request_id"),
                "ledger_intent": intent,
            }
        )
    return updates, unresolved


def _derive_entry_position_type(
    entry,
    *,
    requests_by_id,
    orders_by_request_id,
) -> str | None:
    """从 entry 的可审计证据推导 position_type（仅回填迁移用途）。

    证据优先级：
    1. entry 自身的 ``request_id``（直接指向 om_order_requests）；
    2. ``aggregation_members[*].broker_order_key`` 反查 om_orders 的
       ``request_id``，再指向 om_order_requests；
    3. ``source_ref_id`` 中的 broker_order_key 片段反查（rebuild/buy_cluster
       形态，例如 ``buy_cluster:600104:...:ord_xxx``）。

    最终以该 request 的 ``_derive_ledger_intent`` 为真值；buy 的
    ``base``/``t`` 映射为 entry 的 ``base``/``t``。任何一步无确定证据返回
    ``None``（调用方必须 fail-closed，不做隐式默认）。
    """

    def request_for_entry(entry_doc):
        direct = str(entry_doc.get("request_id") or "").strip()
        if direct in requests_by_id:
            return requests_by_id[direct]
        for member in list(entry_doc.get("aggregation_members") or []):
            broker_order_key = str(member.get("broker_order_key") or "").strip()
            if broker_order_key in orders_by_request_id:
                request_id = orders_by_request_id[broker_order_key]
                if request_id in requests_by_id:
                    return requests_by_id[request_id]
        source_ref_id = str(entry_doc.get("source_ref_id") or "")
        for token in source_ref_id.split(":"):
            token = token.strip()
            if token.startswith("ord_") and token in orders_by_request_id:
                request_id = orders_by_request_id[token]
                if request_id in requests_by_id:
                    return requests_by_id[request_id]
        return None

    request = request_for_entry(entry)
    if request is None:
        return None
    intent, _ = _derive_ledger_intent(request)
    if intent == LEDGER_T:
        return POSITION_TYPE_T
    if intent == LEDGER_BASE:
        return POSITION_TYPE_BASE
    return None


def _collect_entry_updates(database):
    """返回 ``(entry_updates, slice_updates, unresolved)``。

    ``position_type`` 权威语义：entry 由关联 request 的 ledger_intent 推导
    （已有标记直接沿用，无证据 fail-closed）；**slice 与聚合成员强制继承
    所属 entry**——缺失或不一致（例如历史已错误写成 base 的 t 账本 slice）
    一律修正为 entry 的 position_type，杜绝"先解析归属再聚类"之外的账本
    漂移。
    """

    requests_by_id = {
        str(item.get("request_id") or "").strip(): item
        for item in database["om_order_requests"].find({})
        if str(item.get("request_id") or "").strip()
    }
    orders_by_request_id = {}
    for order in database["om_orders"].find({}):
        request_id = str(order.get("request_id") or "").strip()
        broker_order_key = str(order.get("broker_order_key") or "").strip()
        if request_id:
            orders_by_request_id[broker_order_key] = request_id

    entry_position_types: dict[str, str] = {}
    entry_member_updates: dict[str, list[int]] = {}
    entry_raw_missing: set[str] = set()
    unresolved: list[dict] = []
    for entry in database["om_position_entries"].find({}):
        entry_id = str(entry.get("entry_id") or "").strip()
        if not entry_id:
            continue
        raw_type = entry.get("position_type")
        if raw_type not in (None, ""):
            entry_position_type = position_type_of(raw_type)
        else:
            entry_raw_missing.add(entry_id)
            entry_position_type = _derive_entry_position_type(
                entry,
                requests_by_id=requests_by_id,
                orders_by_request_id=orders_by_request_id,
            )
            if entry_position_type is None:
                unresolved.append(
                    {
                        "entry_id": entry_id,
                        "symbol": entry.get("symbol"),
                        "reason": "entry 无 position_type 且无法从 request/"
                        "aggregation/source_ref 推导确定归属",
                    }
                )
                continue
        entry_position_types[entry_id] = entry_position_type
        members = list(entry.get("aggregation_members") or [])
        member_updates = [
            index
            for index, member in enumerate(members)
            if member.get("position_type") in (None, "")
            or position_type_of(member.get("position_type")) != entry_position_type
        ]
        entry_member_updates[entry_id] = member_updates

    slice_updates = []
    for slice_document in database["om_entry_slices"].find({}):
        entry_id = str(slice_document.get("entry_id") or "").strip()
        if not entry_id or entry_id not in entry_position_types:
            continue
        expected = entry_position_types[entry_id]
        if (
            slice_document.get("position_type") in (None, "")
            or position_type_of(slice_document.get("position_type")) != expected
        ):
            slice_updates.append(
                {
                    "entry_slice_id": slice_document.get("entry_slice_id"),
                    "entry_id": entry_id,
                    "position_type": expected,
                }
            )

    entry_updates = [
        {
            "entry_id": entry_id,
            "position_type": entry_position_types[entry_id],
            "member_indices": entry_member_updates[entry_id],
        }
        for entry_id in entry_position_types
        if entry_id in entry_raw_missing or entry_member_updates[entry_id]
    ]
    return entry_updates, slice_updates, unresolved


def _apply_request_updates(database, updates):
    for update in updates:
        request_id = update.get("request_id")
        if not request_id:
            continue
        database["om_order_requests"].update_one(
            {"request_id": request_id},
            {"$set": {"ledger_intent": update["ledger_intent"]}},
        )


def _apply_entry_updates(database, entry_updates):
    for update in entry_updates:
        entry = database["om_position_entries"].find_one(
            {"entry_id": update["entry_id"]}
        )
        if entry is None:
            continue
        fields = {"position_type": update["position_type"]}
        members = list(entry.get("aggregation_members") or [])
        for index in update.get("member_indices") or []:
            if 0 <= index < len(members):
                members[index] = {
                    **dict(members[index]),
                    "position_type": update["position_type"],
                }
        if members:
            fields["aggregation_members"] = members
        database["om_position_entries"].update_one(
            {"entry_id": update["entry_id"]},
            {"$set": fields},
        )


def _apply_slice_updates(database, slice_updates):
    for update in slice_updates:
        entry_slice_id = update.get("entry_slice_id")
        if not entry_slice_id:
            continue
        database["om_entry_slices"].update_one(
            {"entry_slice_id": entry_slice_id},
            {"$set": {"position_type": update["position_type"]}},
        )


def _collect_allocation_updates(database):
    """exit allocations 缺 internal_order_id：经 exit_trade_fact_id 唯一关联
    om_trade_facts.trade_fact_id 回填；0/多条候选或 trade_fact 无
    internal_order_id 时 fail-closed（unresolved，显式停止）。"""

    trade_facts_by_id: dict[str, list] = defaultdict(list)
    for trade_fact in database["om_trade_facts"].find({}):
        key = str(trade_fact.get("trade_fact_id") or "").strip()
        if key:
            trade_facts_by_id[key].append(trade_fact)
    updates = []
    unresolved = []
    for allocation in database["om_exit_allocations"].find({}):
        if str(allocation.get("internal_order_id") or "").strip():
            continue
        exit_trade_fact_id = str(allocation.get("exit_trade_fact_id") or "").strip()
        if not exit_trade_fact_id:
            unresolved.append(
                {
                    "allocation_id": allocation.get("allocation_id"),
                    "reason": "exit_trade_fact_id missing",
                }
            )
            continue
        candidates = trade_facts_by_id.get(exit_trade_fact_id, [])
        if len(candidates) != 1:
            unresolved.append(
                {
                    "allocation_id": allocation.get("allocation_id"),
                    "exit_trade_fact_id": exit_trade_fact_id,
                    "reason": f"trade_fact lookup candidates={len(candidates)}",
                }
            )
            continue
        trade_fact = candidates[0]
        internal_order_id = str(trade_fact.get("internal_order_id") or "").strip()
        if not internal_order_id:
            unresolved.append(
                {
                    "allocation_id": allocation.get("allocation_id"),
                    "exit_trade_fact_id": exit_trade_fact_id,
                    "reason": "trade_fact has no internal_order_id",
                }
            )
            continue
        updates.append(
            {
                "allocation_id": allocation.get("allocation_id"),
                "internal_order_id": internal_order_id,
                "request_id": str(trade_fact.get("request_id") or "").strip() or None,
            }
        )
    return updates, unresolved


def _apply_allocation_updates(database, updates):
    for update in updates:
        allocation_id = update.get("allocation_id")
        if not allocation_id:
            continue
        fields = {"internal_order_id": update["internal_order_id"]}
        if update.get("request_id"):
            fields["request_id"] = update["request_id"]
        database["om_exit_allocations"].update_one(
            {"allocation_id": allocation_id},
            {"$set": fields},
        )


def _broker_order_has_fill_evidence(broker_order) -> bool:
    """broker 聚合是否有成交证据（filled_quantity>0 或 fill_count>0）。"""

    return (
        int(broker_order.get("filled_quantity") or 0) > 0
        or int(broker_order.get("fill_count") or 0) > 0
    )


def _collect_broker_state_updates(database):
    """om_orders 清除 filled_quantity 死字段；om_broker_orders.state 经
    OrderStateService 收敛。

    收敛仅作用于**有成交证据**（``filled_quantity>0`` 或 ``fill_count>0``）
    的 broker 聚合（按对应 om_orders terminal state + filled/requested 推导，
    终态不回退）；零成交行保持原状态——不把 FAILED/被拒/未成交挂单改写为
    ``PARTIAL_FILLED``（避免“复活”占用买入容量与污染失败统计），也不把
    ``requested=0`` 边界推导为 ``FILLED``。
    """

    orders_by_internal_id = {
        str(item.get("internal_order_id") or "").strip(): item
        for item in database["om_orders"].find({})
        if str(item.get("internal_order_id") or "").strip()
    }
    order_state_service = OrderStateService()
    broker_updates = []
    for broker_order in database["om_broker_orders"].find({}):
        if not _broker_order_has_fill_evidence(broker_order):
            continue
        internal_order_id = str(broker_order.get("internal_order_id") or "").strip()
        order = orders_by_internal_id.get(internal_order_id)
        current_order_state = (
            str((order or {}).get("state") or "").strip().upper() or None
        )
        next_state, _ = order_state_service.apply_fill_aggregate_state(
            current_order_state,
            next_quantity=int(broker_order.get("filled_quantity") or 0),
            requested_quantity=broker_order.get("requested_quantity"),
        )
        if str(broker_order.get("state") or "").strip().upper() != next_state:
            broker_updates.append(
                {
                    "broker_order_key": broker_order.get("broker_order_key"),
                    "state": next_state,
                }
            )
    return broker_updates


def _apply_broker_state_updates(database, broker_updates):
    for update in broker_updates:
        broker_order_key = update.get("broker_order_key")
        if not broker_order_key:
            continue
        database["om_broker_orders"].update_one(
            {"broker_order_key": broker_order_key},
            {"$set": {"state": update["state"]}},
        )


def _unset_order_filled_quantity(database):
    database["om_orders"].update_many(
        {},
        {"$unset": {"filled_quantity": ""}},
    )


def _data_contract_conservation(database):
    """新契约守恒：allocation 审计键、om_orders 死字段、broker state 一致性。"""

    missing_allocation_internal_order_id = sum(
        1
        for item in database["om_exit_allocations"].find({})
        if not str(item.get("internal_order_id") or "").strip()
    )
    order_filled_quantity_docs = sum(
        1 for item in database["om_orders"].find({}) if "filled_quantity" in item
    )
    orders_by_internal_id = {
        str(item.get("internal_order_id") or "").strip(): item
        for item in database["om_orders"].find({})
        if str(item.get("internal_order_id") or "").strip()
    }
    order_state_service = OrderStateService()
    broker_state_mismatches = []
    for broker_order in database["om_broker_orders"].find({}):
        if not _broker_order_has_fill_evidence(broker_order):
            continue
        order = orders_by_internal_id.get(
            str(broker_order.get("internal_order_id") or "").strip()
        )
        current_order_state = (
            str((order or {}).get("state") or "").strip().upper() or None
        )
        next_state, _ = order_state_service.apply_fill_aggregate_state(
            current_order_state,
            next_quantity=int(broker_order.get("filled_quantity") or 0),
            requested_quantity=broker_order.get("requested_quantity"),
        )
        if str(broker_order.get("state") or "").strip().upper() != next_state:
            broker_state_mismatches.append(
                {
                    "broker_order_key": broker_order.get("broker_order_key"),
                    "state": broker_order.get("state"),
                    "expected": next_state,
                }
            )
    return {
        "missing_allocation_internal_order_id": missing_allocation_internal_order_id,
        "order_filled_quantity_docs": order_filled_quantity_docs,
        "broker_state_mismatches": broker_state_mismatches,
    }


def _entry_quantity_errors(database):
    """L1：entry 与 slices 数量守恒；S1：slice remaining <= original。"""

    errors = []
    entries = {
        str(item.get("entry_id") or ""): item
        for item in database["om_position_entries"].find({})
        if str(item.get("entry_id") or "")
    }
    slices_by_entry: dict[str, list] = defaultdict(list)
    for slice_document in database["om_entry_slices"].find({}):
        entry_id = str(slice_document.get("entry_id") or "")
        if entry_id:
            slices_by_entry[entry_id].append(slice_document)
    for entry_id, entry in entries.items():
        slices = slices_by_entry.get(entry_id, [])
        original_total = sum(int(item.get("original_quantity") or 0) for item in slices)
        remaining_total = sum(
            int(item.get("remaining_quantity") or 0) for item in slices
        )
        if original_total != int(entry.get("original_quantity") or 0):
            errors.append(
                {
                    "code": "L1_original_mismatch",
                    "entry_id": entry_id,
                    "entry_original": int(entry.get("original_quantity") or 0),
                    "slices_original": original_total,
                }
            )
        if remaining_total != int(entry.get("remaining_quantity") or 0):
            errors.append(
                {
                    "code": "L1_remaining_mismatch",
                    "entry_id": entry_id,
                    "entry_remaining": int(entry.get("remaining_quantity") or 0),
                    "slices_remaining": remaining_total,
                }
            )
        for slice_document in slices:
            if int(slice_document.get("remaining_quantity") or 0) > int(
                slice_document.get("original_quantity") or 0
            ):
                errors.append(
                    {
                        "code": "S1_remaining_exceeds_original",
                        "entry_slice_id": slice_document.get("entry_slice_id"),
                    }
                )
    return errors


def _ledger_conservation(database):
    """D1：base/t 双账本 entry↔slice 分账本守恒 + position_type 缺失统计。"""

    ledger_entry_remaining: dict[str, dict[str, int]] = defaultdict(
        lambda: {"base": 0, "t": 0}
    )
    ledger_slice_remaining: dict[str, dict[str, int]] = defaultdict(
        lambda: {"base": 0, "t": 0}
    )
    missing_entry_type = 0
    missing_slice_type = 0
    missing_member_type = 0
    for entry in database["om_position_entries"].find({}):
        symbol = str(entry.get("symbol") or "")
        raw_type = entry.get("position_type")
        if raw_type in (None, ""):
            missing_entry_type += 1
        position_type = position_type_of(raw_type)
        ledger_entry_remaining[symbol][position_type] += int(
            entry.get("remaining_quantity") or 0
        )
        for member in list(entry.get("aggregation_members") or []):
            if member.get("position_type") in (None, ""):
                missing_member_type += 1
    for slice_document in database["om_entry_slices"].find({}):
        symbol = str(slice_document.get("symbol") or "")
        if slice_document.get("position_type") in (None, ""):
            missing_slice_type += 1
        position_type = position_type_of(slice_document.get("position_type"))
        ledger_slice_remaining[symbol][position_type] += int(
            slice_document.get("remaining_quantity") or 0
        )
    mismatches = []
    for symbol in sorted(set(ledger_entry_remaining) | set(ledger_slice_remaining)):
        for ledger in (LEDGER_BASE, LEDGER_T):
            entry_quantity = ledger_entry_remaining[symbol][ledger]
            slice_quantity = ledger_slice_remaining[symbol][ledger]
            if entry_quantity != slice_quantity:
                mismatches.append(
                    {
                        "symbol": symbol,
                        "ledger": ledger,
                        "entry_remaining": entry_quantity,
                        "slice_remaining": slice_quantity,
                    }
                )
    return {
        "missing_entry_position_type": missing_entry_type,
        "missing_slice_position_type": missing_slice_type,
        "missing_member_position_type": missing_member_type,
        "ledger_mismatches": mismatches,
    }


def _verify_allocation_integrity(database):
    errors = find_exit_allocation_integrity_errors(
        position_entries=database["om_position_entries"].find({}),
        entry_slices=database["om_entry_slices"].find({}),
        exit_allocations=database["om_exit_allocations"].find({}),
    )
    return list(errors)


def _backup_collections(database, backup_db_name, collection_names):
    if not backup_db_name:
        return
    target = database.client[str(backup_db_name).strip()]
    for collection_name in collection_names:
        documents = list(database[collection_name].find({}))
        target[collection_name].delete_many({})
        if documents:
            target[collection_name].insert_many(documents, ordered=False)
        click.echo(
            f"backup {collection_name} -> {backup_db_name}: {len(documents)} docs"
        )


def _run_conservation(database):
    l1_errors = _entry_quantity_errors(database)
    allocation_errors = _verify_allocation_integrity(database)
    ledger_report = _ledger_conservation(database)
    return l1_errors, allocation_errors, ledger_report


def _record_execute_audit(database, *, counts, backup_db):
    """execute 写前审计（#582 PR5）：记录操作/时间/影响计数/备份库。

    best-effort：审计写失败只告警不阻断；写侧始终走字段级 $set，
    内容无变化的行不刷新任何时间戳（消灭无痕直写）。
    """

    try:
        import socket
        from datetime import datetime, timezone

        database["audit_log"].insert_one(
            {
                "operation": "maintenance_backfill_ledger_intent_execute",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "host": socket.gethostname(),
                "counts": {
                    "requests": len(counts.get("requests") or []),
                    "entries": len(counts.get("entries") or []),
                    "slices": len(counts.get("slices") or []),
                    "allocations": len(counts.get("allocations") or []),
                    "broker_states": len(counts.get("broker_states") or []),
                },
                "backup_db": backup_db,
            }
        )
    except Exception as exc:  # pragma: no cover - 防御降级
        click.echo(f"warning: audit write failed: {exc}")


@click.command()
@click.option("--dry-run", "dry_run", is_flag=True, default=False)
@click.option("--execute", "execute", is_flag=True, default=False)
@click.option("--backup-db", type=str, default=None)
def main(*, dry_run, execute, backup_db):
    if not dry_run and not execute:
        dry_run = True
    if dry_run and execute:
        raise click.UsageError("choose either --dry-run or --execute, not both")

    database = get_order_management_db()
    request_updates, unresolved_requests = _collect_request_updates(database)
    entry_updates, slice_updates, unresolved_entries = _collect_entry_updates(database)
    allocation_updates, unresolved_allocations = _collect_allocation_updates(database)
    broker_state_updates = _collect_broker_state_updates(database)
    if unresolved_requests:
        for item in unresolved_requests[:20]:
            click.echo(f"  unresolved ledger_intent: {item}")
        raise click.ClickException(
            f"{len(unresolved_requests)} requests cannot derive ledger_intent "
            "from definitive evidence; resolve manually and re-run "
            "(fail-closed, no silent default)"
        )
    if unresolved_entries:
        for item in unresolved_entries[:20]:
            click.echo(f"  unresolved entry position_type: {item}")
        raise click.ClickException(
            f"{len(unresolved_entries)} entries cannot derive position_type "
            "from definitive evidence; resolve manually and re-run "
            "(fail-closed, no silent default)"
        )
    if unresolved_allocations:
        for item in unresolved_allocations[:20]:
            click.echo(f"  unresolved allocation internal_order_id: {item}")
        raise click.ClickException(
            f"{len(unresolved_allocations)} exit allocations cannot be linked to "
            "a unique trade_fact; resolve manually and re-run "
            "(fail-closed, no silent default)"
        )
    click.echo(
        f"backfill plan: requests={len(request_updates)} "
        f"entries={len(entry_updates)} slices={len(slice_updates)} "
        f"allocations={len(allocation_updates)} "
        f"broker_states={len(broker_state_updates)} "
        f"mode={'execute' if execute else 'dry-run'}"
    )
    if not execute:
        click.echo("dry-run complete; no writes performed")
        return

    if backup_db:
        _backup_collections(
            database,
            backup_db,
            [
                "om_order_requests",
                "om_position_entries",
                "om_entry_slices",
                "om_exit_allocations",
                "om_orders",
                "om_broker_orders",
            ],
        )
    _apply_request_updates(database, request_updates)
    _apply_entry_updates(database, entry_updates)
    _apply_slice_updates(database, slice_updates)
    _apply_allocation_updates(database, allocation_updates)
    _apply_broker_state_updates(database, broker_state_updates)
    _unset_order_filled_quantity(database)

    l1_errors, allocation_errors, ledger_report = _run_conservation(database)
    contract_report = _data_contract_conservation(database)
    click.echo(
        f"backfill verify: L1_errors={len(l1_errors)} "
        f"allocation_integrity_errors={len(allocation_errors)} "
        f"missing_entry_position_type={ledger_report['missing_entry_position_type']} "
        f"missing_slice_position_type={ledger_report['missing_slice_position_type']} "
        f"missing_member_position_type={ledger_report['missing_member_position_type']} "
        f"ledger_mismatches={len(ledger_report['ledger_mismatches'])} "
        f"missing_allocation_internal_order_id="
        f"{contract_report['missing_allocation_internal_order_id']} "
        f"order_filled_quantity_docs={contract_report['order_filled_quantity_docs']} "
        f"broker_state_mismatches={len(contract_report['broker_state_mismatches'])}"
    )
    if l1_errors:
        for error in l1_errors[:10]:
            click.echo(f"  L1/S1 error: {error}")
    if allocation_errors:
        for error in allocation_errors[:10]:
            click.echo(f"  allocation integrity error: {error}")
    if ledger_report["ledger_mismatches"]:
        for mismatch in ledger_report["ledger_mismatches"][:10]:
            click.echo(f"  ledger mismatch: {mismatch}")
    if contract_report["broker_state_mismatches"]:
        for mismatch in contract_report["broker_state_mismatches"][:10]:
            click.echo(f"  broker state mismatch: {mismatch}")
    if (
        l1_errors
        or allocation_errors
        or ledger_report["ledger_mismatches"]
        or contract_report["missing_allocation_internal_order_id"]
        or contract_report["order_filled_quantity_docs"]
        or contract_report["broker_state_mismatches"]
    ):
        raise click.ClickException("backfill conservation verification failed")

    # 幂等复验：再次收集应为 0 变更。
    repeat_requests, repeat_unresolved = _collect_request_updates(database)
    (
        repeat_entries,
        repeat_slices,
        repeat_unresolved_entries,
    ) = _collect_entry_updates(database)
    repeat_allocations, repeat_unresolved_allocations = _collect_allocation_updates(
        database
    )
    repeat_broker_states = _collect_broker_state_updates(database)
    repeat_contract = _data_contract_conservation(database)
    click.echo(
        f"backfill idempotency: repeat_requests={len(repeat_requests)} "
        f"repeat_entries={len(repeat_entries)} repeat_slices={len(repeat_slices)} "
        f"repeat_allocations={len(repeat_allocations)} "
        f"repeat_broker_states={len(repeat_broker_states)} "
        f"repeat_filled_quantity_docs="
        f"{repeat_contract['order_filled_quantity_docs']}"
    )
    if (
        repeat_requests
        or repeat_unresolved
        or repeat_unresolved_entries
        or repeat_entries
        or repeat_slices
        or repeat_allocations
        or repeat_unresolved_allocations
        or repeat_broker_states
        or repeat_contract["missing_allocation_internal_order_id"]
        or repeat_contract["order_filled_quantity_docs"]
        or repeat_contract["broker_state_mismatches"]
    ):
        raise click.ClickException("backfill is not idempotent; abort")

    _record_execute_audit(
        database,
        counts={
            "requests": request_updates,
            "entries": entry_updates,
            "slices": slice_updates,
            "allocations": allocation_updates,
            "broker_states": broker_state_updates,
        },
        backup_db=backup_db,
    )
    click.echo("backfill audit recorded")


if __name__ == "__main__":
    main()
