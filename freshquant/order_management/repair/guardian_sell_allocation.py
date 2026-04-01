# -*- coding: utf-8 -*-

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json

from freshquant.order_management.guardian.allocation_policy import (
    allocate_sell_to_entry_slices,
)
from freshquant.order_management.guardian.sell_semantics import (
    normalize_preferred_entry_quantities,
    resolve_guardian_sell_source_entries_from_open_slices,
)
from freshquant.order_management.reconcile.service import (
    _after_holdings_reconciled,
    _resolve_entry_status,
)
from freshquant.order_management.repository import OrderManagementRepository


def replay_symbol_entry_ledger(*, seed_entries, seed_slices, sell_events):
    entries = [_reset_entry(item) for item in sorted(_clone_rows(seed_entries), key=_entry_sort_key)]
    entry_by_id = {item["entry_id"]: item for item in entries}
    slices = [_reset_entry_slice(item) for item in sorted(_clone_rows(seed_slices), key=_slice_sort_key, reverse=True)]

    event_results = []
    exit_allocations = []

    for event in sorted(_clone_rows(sell_events), key=_event_sort_key):
        open_slices = [item for item in slices if int(item.get("remaining_quantity") or 0) > 0]
        open_slices.sort(key=_slice_sort_key, reverse=True)
        preferred = _resolve_sell_event_preferred_entries(
            request=event.get("request"),
            open_slices=open_slices,
            quantity=event.get("quantity"),
        )
        trade_fact = {
            "trade_fact_id": event["event_id"],
            "symbol": event["symbol"],
            "side": "sell",
            "quantity": int(event.get("quantity") or 0),
            "price": float(event.get("price") or 0.0),
            "trade_time": int(event.get("event_time") or 0),
        }
        allocations = allocate_sell_to_entry_slices(
            entries=list(entry_by_id.values()),
            open_slices=slices,
            sell_trade_fact=trade_fact,
            preferred_entry_quantities=preferred,
        )
        if event.get("event_kind") == "auto_close":
            for allocation in allocations:
                allocation["resolution_id"] = event["event_id"]
                allocation.pop("exit_trade_fact_id", None)
        exit_allocations.extend(allocations)
        event_results.append(
            {
                "event_id": event["event_id"],
                "event_kind": event.get("event_kind"),
                "symbol": event.get("symbol"),
                "quantity": int(event.get("quantity") or 0),
                "preferred_entry_quantities": list(preferred or []),
                "allocations": [
                    {
                        "entry_id": item.get("entry_id"),
                        "allocated_quantity": int(item.get("allocated_quantity") or 0),
                    }
                    for item in allocations
                ],
            }
        )

    for entry in entries:
        entry["status"] = _resolve_entry_status(
            entry.get("remaining_quantity"),
            entry.get("original_quantity"),
        )
    for item in slices:
        item["status"] = (
            "CLOSED" if int(item.get("remaining_quantity") or 0) <= 0 else "OPEN"
        )
        item["remaining_amount"] = round(
            float(item.get("guardian_price") or 0.0)
            * int(item.get("remaining_quantity") or 0),
            2,
        )

    return {
        "entries": entries,
        "entry_slices": slices,
        "exit_allocations": exit_allocations,
        "event_results": event_results,
    }


def repair_guardian_sell_allocations(
    *,
    database,
    symbols=None,
    execute=False,
    backup_dir=None,
):
    repository = OrderManagementRepository(database=database)
    target_symbols = _resolve_target_symbols(database, symbols=symbols)
    planned_repairs = []

    for symbol in target_symbols:
        plan = _plan_symbol_repair(database, repository=repository, symbol=symbol)
        if plan is None or not plan.get("changed"):
            continue
        if execute:
            _backup_symbol_state(symbol, plan, backup_dir=backup_dir)
            _apply_symbol_repair(database, repository=repository, symbol=symbol, plan=plan)
        planned_repairs.append(plan["summary"])

    return {
        "symbols": target_symbols,
        "changed_symbols": [item["symbol"] for item in planned_repairs],
        "changed_count": len(planned_repairs),
        "execute": bool(execute),
        "repairs": planned_repairs,
    }


def _resolve_target_symbols(database, *, symbols=None):
    if symbols:
        return sorted({str(item).strip() for item in symbols if str(item).strip()})
    return sorted(
        {
            str(item.get("symbol") or "").strip()
            for item in database["om_order_requests"].find(
                {"action": "sell", "source": "strategy"},
                {"symbol": 1},
            )
            if str(item.get("symbol") or "").strip()
        }
    )


def _plan_symbol_repair(database, *, repository, symbol):
    seed_entries = list(database["om_position_entries"].find({"symbol": symbol}))
    if not seed_entries:
        return None
    seed_slices = list(database["om_entry_slices"].find({"symbol": symbol}))
    candidate_events = _build_candidate_auto_close_events(database, symbol=symbol)
    if not candidate_events:
        return None

    working_entries = {
        item["entry_id"]: dict(item)
        for item in sorted(_clone_rows(seed_entries), key=_entry_sort_key)
    }
    working_slices = {
        item["entry_slice_id"]: dict(item)
        for item in sorted(_clone_rows(seed_slices), key=_slice_sort_key, reverse=True)
    }

    prepared_events = []
    for event in sorted(candidate_events, key=_event_sort_key, reverse=True):
        current_allocations = _list_current_resolution_allocations(
            database,
            resolution_id=event["event_id"],
        )
        _undo_allocations(
            entries=working_entries,
            slices=working_slices,
            allocations=current_allocations,
        )
        repaired = _build_repaired_resolution_allocations(
            event=event,
            entries=working_entries,
            slices=working_slices,
        )
        prepared_events.append(
            {
                **event,
                "current_allocations": current_allocations,
                "repaired_allocations": repaired["allocations"],
                "preferred_entry_quantities": repaired["preferred_entry_quantities"],
            }
        )

    candidate_signature = _build_candidate_signature(prepared_events)
    signature_by_event_id = {
        item["event_id"]: item
        for item in candidate_signature["events"]
    }
    for event in prepared_events:
        event["should_repair"] = bool(
            signature_by_event_id.get(event["event_id"], {}).get("should_repair")
        )
    final_entries = {key: dict(value) for key, value in working_entries.items()}
    final_slices = {key: dict(value) for key, value in working_slices.items()}
    for event in sorted(prepared_events, key=_event_sort_key):
        _apply_allocations(
            entries=final_entries,
            slices=final_slices,
            allocations=(
                event["repaired_allocations"]
                if event.get("should_repair")
                else event["current_allocations"]
            ),
        )

    changed = any(
        bool(event.get("should_repair"))
        for event in candidate_signature["events"]
    )
    changed = changed or _build_entry_signature(seed_entries) != _build_entry_signature(
        final_entries.values()
    )
    return {
        "symbol": symbol,
        "changed": changed,
        "seed_entries": seed_entries,
        "seed_slices": seed_slices,
        "candidate_events": prepared_events,
        "repaired_entries": list(final_entries.values()),
        "repaired_slices": list(final_slices.values()),
        "current_signature": {
            "entries": _build_entry_signature(seed_entries),
            "candidates": {
                item["event_id"]: item["current_signature"]
                for item in candidate_signature["events"]
            },
        },
        "replay_signature": {
            "entries": _build_entry_signature(final_entries.values()),
            "candidates": {
                item["event_id"]: item["repaired_signature"]
                for item in candidate_signature["events"]
            },
        },
        "summary": {
            "symbol": symbol,
            "changed": changed,
            "entry_count": len(seed_entries),
            "candidate_count": sum(
                1 for item in prepared_events if item.get("should_repair")
            ),
        },
    }


def _build_symbol_sell_events(database, *, symbol):
    trade_facts_by_id = {
        item["trade_fact_id"]: item
        for item in database["om_trade_facts"].find({"symbol": symbol, "side": "sell"})
    }
    events = []
    for trade_fact in trade_facts_by_id.values():
        request = _resolve_request_for_trade_fact(database, trade_fact)
        events.append(
            {
                "event_kind": "trade",
                "event_id": trade_fact["trade_fact_id"],
                "symbol": symbol,
                "quantity": int(trade_fact.get("quantity") or 0),
                "price": float(trade_fact.get("price") or 0.0),
                "event_time": int(trade_fact.get("trade_time") or 0),
                "request": request,
            }
        )

    for resolution in database["om_reconciliation_resolutions"].find(
        {"resolution_type": "auto_close_allocation"}
    ):
        gap = database["om_reconciliation_gaps"].find_one({"gap_id": resolution.get("gap_id")})
        if gap is None or gap.get("symbol") != symbol or gap.get("side") != "sell":
            continue
        request = _resolve_request_for_auto_close_event(
            database,
            symbol=symbol,
            gap=gap,
            resolution=resolution,
        )
        if request is not None and _request_has_sell_trade_facts(database, request):
            continue
        events.append(
            {
                "event_kind": "auto_close",
                "event_id": resolution["resolution_id"],
                "symbol": symbol,
                "quantity": int(resolution.get("resolved_quantity") or 0),
                "price": float(resolution.get("resolved_price") or 0.0),
                "event_time": int(resolution.get("resolved_at") or 0),
                "request": request,
                "gap_id": gap.get("gap_id"),
            }
        )

    return events


def _resolve_request_for_trade_fact(database, trade_fact):
    internal_order_id = str(trade_fact.get("internal_order_id") or "").strip()
    if not internal_order_id:
        return None
    order = database["om_orders"].find_one({"internal_order_id": internal_order_id})
    if order is None:
        return None
    request_id = str(order.get("request_id") or "").strip()
    if not request_id:
        return None
    return database["om_order_requests"].find_one({"request_id": request_id})


def _resolve_request_for_auto_close_event(database, *, symbol, gap, resolution):
    quantity = int(resolution.get("resolved_quantity") or 0)
    event_time = int(resolution.get("resolved_at") or gap.get("detected_at") or 0)
    request_rows = list(
        database["om_order_requests"]
        .find(
            {
                "symbol": symbol,
                "action": "sell",
                "quantity": quantity,
            }
        )
        .sort("created_at", -1)
    )
    best_request = None
    best_score = None
    for request in request_rows:
        created_at_epoch = _coerce_epoch_seconds(request.get("created_at"))
        if created_at_epoch is None:
            continue
        if created_at_epoch > event_time + 5:
            continue
        score = (abs(event_time - created_at_epoch), -created_at_epoch)
        if best_score is None or score < best_score:
            best_score = score
            best_request = request
    return best_request


def _request_has_sell_trade_facts(database, request):
    request_id = str((request or {}).get("request_id") or "").strip()
    if not request_id:
        return False
    order = database["om_orders"].find_one({"request_id": request_id})
    if order is None:
        return False
    internal_order_id = str(order.get("internal_order_id") or "").strip()
    if not internal_order_id:
        return False
    return (
        database["om_trade_facts"].count_documents(
            {"internal_order_id": internal_order_id, "side": "sell"}
        )
        > 0
    )


def _build_candidate_auto_close_events(database, *, symbol):
    events = []
    for resolution in database["om_reconciliation_resolutions"].find(
        {"resolution_type": "auto_close_allocation"}
    ):
        gap = database["om_reconciliation_gaps"].find_one(
            {"gap_id": resolution.get("gap_id")}
        )
        if gap is None or gap.get("symbol") != symbol or gap.get("side") != "sell":
            continue
        request = _resolve_request_for_auto_close_event(
            database,
            symbol=symbol,
            gap=gap,
            resolution=resolution,
        )
        if request is None:
            continue
        if _request_has_sell_trade_facts(database, request):
            continue
        events.append(
            {
                "event_kind": "auto_close",
                "event_id": resolution["resolution_id"],
                "symbol": symbol,
                "quantity": int(resolution.get("resolved_quantity") or 0),
                "price": float(resolution.get("resolved_price") or 0.0),
                "event_time": int(resolution.get("resolved_at") or 0),
                "request": request,
                "gap_id": gap.get("gap_id"),
            }
        )
    return events


def _resolve_sell_event_preferred_entries(*, request, open_slices, quantity):
    if request is None:
        return []
    runtime_entries = resolve_guardian_sell_source_entries_from_open_slices(
        open_slices,
        exit_price=request.get("price"),
        quantity=quantity,
    )
    if runtime_entries:
        return runtime_entries
    context = dict((request or {}).get("strategy_context") or {})
    sell_sources = dict(context.get("guardian_sell_sources") or {})
    return normalize_preferred_entry_quantities(
        sell_sources.get("entries"),
        remaining_quantity=quantity,
    )


def _list_current_resolution_allocations(database, *, resolution_id):
    return list(
        database["om_exit_allocations"].find({"resolution_id": str(resolution_id or "").strip()})
    )


def _undo_allocations(*, entries, slices, allocations):
    for allocation in list(allocations or []):
        _apply_allocation_delta(
            entries=entries,
            slices=slices,
            allocation=allocation,
            direction=-1,
        )


def _apply_allocations(*, entries, slices, allocations):
    for allocation in list(allocations or []):
        _apply_allocation_delta(
            entries=entries,
            slices=slices,
            allocation=allocation,
            direction=1,
        )


def _apply_allocation_delta(*, entries, slices, allocation, direction):
    entry_id = str(allocation.get("entry_id") or "").strip()
    slice_id = str(allocation.get("entry_slice_id") or "").strip()
    quantity = int(allocation.get("allocated_quantity") or 0)
    if not entry_id or not slice_id or quantity <= 0:
        return
    signed_quantity = quantity if int(direction or 1) > 0 else -quantity
    entry = entries[entry_id]
    slice_document = slices[slice_id]
    entry["remaining_quantity"] = int(entry.get("remaining_quantity") or 0) - signed_quantity
    entry["status"] = _resolve_entry_status(
        entry.get("remaining_quantity"),
        entry.get("original_quantity"),
    )
    slice_document["remaining_quantity"] = (
        int(slice_document.get("remaining_quantity") or 0) - signed_quantity
    )
    slice_document["remaining_amount"] = round(
        float(slice_document.get("guardian_price") or 0.0)
        * int(slice_document.get("remaining_quantity") or 0),
        2,
    )
    slice_document["status"] = (
        "CLOSED" if int(slice_document.get("remaining_quantity") or 0) <= 0 else "OPEN"
    )


def _build_repaired_resolution_allocations(*, event, entries, slices):
    working_entries = {key: deepcopy(value) for key, value in entries.items()}
    working_slices = {key: deepcopy(value) for key, value in slices.items()}
    open_slices = [
        item for item in working_slices.values() if int(item.get("remaining_quantity") or 0) > 0
    ]
    open_slices.sort(key=_slice_sort_key, reverse=True)
    preferred_entries = _resolve_sell_event_preferred_entries(
        request=event.get("request"),
        open_slices=open_slices,
        quantity=event.get("quantity"),
    )
    allocations = allocate_sell_to_entry_slices(
        entries=list(working_entries.values()),
        open_slices=list(working_slices.values()),
        sell_trade_fact={
            "trade_fact_id": event["event_id"],
            "symbol": event["symbol"],
            "side": "sell",
            "quantity": int(event.get("quantity") or 0),
            "price": float(event.get("price") or 0.0),
            "trade_time": int(event.get("event_time") or 0),
        },
        preferred_entry_quantities=preferred_entries,
    )
    for item in allocations:
        item["resolution_id"] = event["event_id"]
        item.pop("exit_trade_fact_id", None)
    return {
        "preferred_entry_quantities": preferred_entries,
        "allocations": allocations,
    }


def _build_entry_signature(entries):
    return {
        item["entry_id"]: (
            int(item.get("remaining_quantity") or 0),
            str(item.get("status") or ""),
        )
        for item in list(entries or [])
    }


def _build_candidate_signature(events):
    normalized = []
    for event in list(events or []):
        current_signature = _build_event_entry_signature(
            event.get("current_allocations") or []
        )
        repaired_signature = _build_event_entry_signature(
            event.get("repaired_allocations") or []
        )
        normalized.append(
            {
                "event_id": event.get("event_id"),
                "current_signature": current_signature,
                "repaired_signature": repaired_signature,
                "should_repair": current_signature != repaired_signature,
            }
        )
    return {"events": normalized}


def _build_event_entry_signature(allocations):
    grouped = {}
    for item in list(allocations or []):
        entry_id = str(item.get("entry_id") or "").strip()
        allocated_quantity = int(item.get("allocated_quantity") or 0)
        if not entry_id or allocated_quantity <= 0:
            continue
        grouped[entry_id] = grouped.get(entry_id, 0) + allocated_quantity
    return sorted(grouped.items())


def _build_current_symbol_signature(database, *, symbol):
    entries = {
        item["entry_id"]: (
            int(item.get("remaining_quantity") or 0),
            str(item.get("status") or ""),
        )
        for item in database["om_position_entries"].find({"symbol": symbol})
    }
    grouped_allocations = {}
    for item in database["om_exit_allocations"].find({"symbol": symbol}):
        resolution_id = str(item.get("resolution_id") or "").strip()
        if resolution_id:
            key = ("resolution", resolution_id)
        else:
            key = ("trade", str(item.get("exit_trade_fact_id") or "").strip())
        grouped_allocations.setdefault(key, []).append(
            (
                str(item.get("entry_id") or "").strip(),
                int(item.get("allocated_quantity") or 0),
            )
        )
    normalized_groups = {
        key: sorted(value)
        for key, value in grouped_allocations.items()
        if key[1]
    }
    return {
        "entries": entries,
        "allocations": normalized_groups,
    }


def _build_replay_symbol_signature(replay, *, sell_events):
    entries = {
        item["entry_id"]: (
            int(item.get("remaining_quantity") or 0),
            str(item.get("status") or ""),
        )
        for item in replay.get("entries") or []
    }
    grouped_allocations = {}
    event_kind_by_id = {
        item["event_id"]: item.get("event_kind") for item in list(sell_events or [])
    }
    for item in replay.get("exit_allocations") or []:
        resolution_id = str(item.get("resolution_id") or "").strip()
        if resolution_id:
            key = ("resolution", resolution_id)
        else:
            trade_fact_id = str(item.get("exit_trade_fact_id") or "").strip()
            key = (
                "trade",
                trade_fact_id,
            )
        grouped_allocations.setdefault(key, []).append(
            (
                str(item.get("entry_id") or "").strip(),
                int(item.get("allocated_quantity") or 0),
            )
        )
    normalized_groups = {
        key: sorted(value)
        for key, value in grouped_allocations.items()
        if key[1] and event_kind_by_id.get(key[1], key[0]) is not None
    }
    return {
        "entries": entries,
        "allocations": normalized_groups,
    }


def _apply_symbol_repair(database, *, repository, symbol, plan):
    for entry in plan["repaired_entries"]:
        repository.replace_position_entry(entry)
        repository.replace_entry_slices_for_entry(
            entry["entry_id"],
            [
                item
                for item in plan["repaired_slices"]
                if item.get("entry_id") == entry["entry_id"]
            ],
        )
    for event in plan.get("candidate_events") or []:
        if not event.get("should_repair"):
            continue
        database["om_exit_allocations"].delete_many({"resolution_id": event["event_id"]})
        if event["repaired_allocations"]:
            database["om_exit_allocations"].insert_many(
                event["repaired_allocations"],
                ordered=False,
            )
        preferred_entries = list(event.get("preferred_entry_quantities") or [])
        allocation_ids = [
            item["allocation_id"] for item in event["repaired_allocations"]
        ]
        database["om_reconciliation_resolutions"].update_one(
            {"resolution_id": event["event_id"]},
            {
                "$set": {
                    "entry_allocation_ids": allocation_ids,
                    "sell_source_entries": preferred_entries,
                }
            },
        )
        gap_id = str(event.get("gap_id") or "").strip()
        if gap_id:
            database["om_reconciliation_gaps"].update_one(
                {"gap_id": gap_id},
                {"$set": {"sell_source_entries": preferred_entries}},
            )

    _after_holdings_reconciled(symbol, repository=repository)


def _backup_symbol_state(symbol, plan, *, backup_dir=None):
    backup_root = Path(backup_dir or ".artifacts/guardian-sell-allocation-repair")
    backup_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol": symbol,
        "seed_entries": plan.get("seed_entries") or [],
        "seed_slices": plan.get("seed_slices") or [],
        "candidate_events": plan.get("candidate_events") or [],
        "current_signature": plan.get("current_signature") or {},
        "replay_signature": plan.get("replay_signature") or {},
    }
    backup_path = backup_root / f"{symbol}.json"
    backup_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _clone_rows(rows):
    return [deepcopy(item) for item in list(rows or [])]


def _reset_entry(entry):
    entry = dict(entry)
    entry["remaining_quantity"] = int(entry.get("original_quantity") or 0)
    entry["status"] = _resolve_entry_status(
        entry.get("remaining_quantity"),
        entry.get("original_quantity"),
    )
    entry["sell_history"] = []
    return entry


def _reset_entry_slice(item):
    row = dict(item)
    row["remaining_quantity"] = int(row.get("original_quantity") or 0)
    row["remaining_amount"] = round(
        float(row.get("guardian_price") or 0.0)
        * int(row.get("original_quantity") or 0),
        2,
    )
    row["status"] = "OPEN"
    return row


def _entry_sort_key(item):
    return (
        int(item.get("trade_time") or 0),
        int(item.get("date") or 0),
        str(item.get("time") or ""),
        str(item.get("entry_id") or ""),
    )


def _slice_sort_key(item):
    return (
        float(item.get("guardian_price") or 0.0),
        int(item.get("slice_seq") or 0),
        str(item.get("entry_slice_id") or ""),
    )


def _event_sort_key(item):
    return (
        int(item.get("event_time") or 0),
        0 if item.get("event_kind") == "trade" else 1,
        str(item.get("event_id") or ""),
    )


def _coerce_epoch_seconds(value):
    if value in {None, ""}:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        pass
    try:
        normalized_text = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized_text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except Exception:
        return None
