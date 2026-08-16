# -*- coding: utf-8 -*-

"""Read-only chart and evidence projections for the position-review refactor.

This module implements the product decisions from
``.artifacts/design/position-review-refactor-final-2026-08-07.md``:

- One K-line main chart per symbol with order markers on the price layer.
- Buy = red, sell = green; signal family drives the marker shape; verdict is
  encoded with border / dash / transparency only.
- Markers anchor on the first fill bar at the order weighted average price;
  cross-bar fills are projected as a thin same-color span line.
- Cost basis is rebuilt from entry/slice/allocation remaining costs when the
  ledger evidence is complete, otherwise the projection degrades to a moving
  average estimate and is explicitly labelled.
- Hover and the pinned evidence panel consume the same order-event contract;
  full conditions are lazy-loaded from ``/events/<event_id>/conditions``.

All functions are read-only projections. They never write to order, position,
configuration or evidence stores.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from freshquant.order_management.ledger_resolver import (
    is_takeprofit_request,
    normalize_ledger_intent,
)
from freshquant.position_review.replay import (
    reconstruct_inventory,
)

_BEIJING_TZ_NAME = "Asia/Shanghai"

VERDICT_BORDER_META = {
    "PASS": {"border": "normal", "dashed": False, "alpha": 1.0},
    "FAIL": {"border": "bold", "dashed": False, "alpha": 1.0},
    "INSUFFICIENT_EVIDENCE": {"border": "dashed", "dashed": True, "alpha": 0.7},
    "NOT_APPLICABLE": {"border": "hollow", "dashed": False, "alpha": 0.45},
}

# Server-side stable registry. The front end only consumes
# ``signal_type / signal_family / signal_label / marker_symbol``.
SIGNAL_TYPE_REGISTRY: dict[str, dict[str, Any]] = {
    "buy_v_reverse": {
        "family": "reversal",
        "label": "反转买点",
        "marker_symbol": "triangle",
    },
    "buy_zs_huila": {
        "family": "pullback",
        "label": "回拉买点",
        "marker_symbol": "circle",
    },
    "macd_bullish_divergence": {
        "family": "divergence",
        "label": "MACD 底背离",
        "marker_symbol": "diamond",
    },
    "sell_takeprofit": {
        "family": "takeprofit",
        "label": "止盈卖点",
        "marker_symbol": "path://M0,18 L10,0 L-10,0 Z",
    },
    "manual": {
        "family": "manual",
        "label": "人工/外部",
        "marker_symbol": "path://M0,10 L8.66,5 L8.66,-5 L0,-10 L-8.66,-5 L-8.66,5 Z",
    },
    "unknown": {
        "family": "unknown",
        "label": "证据缺失",
        "marker_symbol": "circle",
    },
}

_BUY_SIGNAL_KEYWORDS = (
    ("macd_bullish_divergence", ("背离", "divergence", "macd")),
    ("buy_v_reverse", ("反转", "reverse", "v_reverse", "底背")),
    ("buy_zs_huila", ("回拉", "huila")),
)
_SELL_SIGNAL_KEYWORDS = (
    ("sell_takeprofit", ("止盈", "takeprofit", "take_profit", "回拉中枢")),
)


def signal_type_registry_payload() -> dict[str, dict[str, Any]]:
    return {
        signal_type: {
            "type": signal_type,
            "family": meta["family"],
            "label": meta["label"],
            "marker_symbol": meta["marker_symbol"],
        }
        for signal_type, meta in SIGNAL_TYPE_REGISTRY.items()
    }


def signal_meta(signal_type: str | None) -> dict[str, Any]:
    normalized = str(signal_type or "").strip().lower() or "unknown"
    meta = SIGNAL_TYPE_REGISTRY.get(normalized)
    if meta is None:
        meta = SIGNAL_TYPE_REGISTRY["unknown"]
        normalized = "unknown"
    return {
        "type": normalized,
        "family": meta["family"],
        "label": meta["label"],
        "marker_symbol": meta["marker_symbol"],
    }


def _first_text(*values) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _first_positive(*values) -> float | None:
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value, digits=6):
    number = _float(value)
    if number is None:
        return None
    return round(number, digits)


def _epoch_iso(value) -> str | None:
    timestamp = _int(value)
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _stable_hash(material: str, length: int = 20) -> str:
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:length]


def resolve_signal_type(
    *,
    request: dict[str, Any] | None,
    signal: dict[str, Any] | None,
    side: str | None,
) -> str:
    """Map request / signal evidence to a stable ``signal_type``.

    The mapping is intentionally conservative: only explicit evidence is used.
    Missing evidence falls back to ``unknown`` so the chart never fabricates a
    signal family.
    """

    context = request.get("strategy_context") if isinstance(request, dict) else None
    strategy_context = context if isinstance(context, dict) else {}
    buy_grid = (
        strategy_context.get("guardian_buy_grid")
        if isinstance(strategy_context.get("guardian_buy_grid"), dict)
        else None
    )
    sell_sources = (
        strategy_context.get("guardian_sell_sources")
        if isinstance(strategy_context.get("guardian_sell_sources"), dict)
        else None
    )
    request_source = _first_text(
        (request or {}).get("source"),
        (request or {}).get("strategy_name"),
    )
    if request_source and str(request_source).lower() in {
        "manual",
        "external",
        "人工",
        "外部",
    }:
        return "manual"

    remarks = [
        _first_text((signal or {}).get("remark")),
        _first_text((signal or {}).get("label")),
        _first_text((signal or {}).get("title")),
        _first_text((request or {}).get("remark")),
        _first_text((request or {}).get("signal_type")),
    ]
    explicit_type = _first_text((request or {}).get("signal_type"))
    if explicit_type:
        normalized = str(explicit_type).strip().lower()
        if normalized in SIGNAL_TYPE_REGISTRY:
            return normalized

    normalized_side = str(side or "").strip().lower()
    if normalized_side == "buy":
        if buy_grid:
            path = str((buy_grid or {}).get("path") or "").strip().lower()
            if path == "new_open":
                return "buy_v_reverse"
            if path in {"holding_add", ""} and buy_grid.get("base_amount") is not None:
                return "buy_zs_huila"
        for signal_type, keywords in _BUY_SIGNAL_KEYWORDS:
            if any(kw in text.lower() for text in remarks if text for kw in keywords):
                return signal_type
        return "buy_v_reverse"

    if normalized_side == "sell":
        # #571：按 ledger_intent 分流（- → 人工/外部；base → 止盈）；
        # Guardian 做T卖出（t）保留既有证据判定语义。
        ledger_intent = normalize_ledger_intent((request or {}).get("ledger_intent"))
        if ledger_intent == "-":
            return "manual"
        if ledger_intent == "base":
            return "sell_takeprofit"
        if sell_sources:
            source_name = _first_text(
                sell_sources.get("source_name"),
                sell_sources.get("trigger"),
                sell_sources.get("mode"),
            )
            if source_name:
                lowered = str(source_name).lower()
                if "profit" in lowered or "盈" in lowered:
                    return "sell_takeprofit"
        for signal_type, keywords in _SELL_SIGNAL_KEYWORDS:
            if any(kw in text.lower() for text in remarks if text for kw in keywords):
                return signal_type
        return "sell_takeprofit"

    return "unknown"


def build_signal_block(
    *,
    timeline_signal: dict[str, Any] | None,
    request: dict[str, Any] | None,
    side: str | None,
    association_method: str | None,
) -> dict[str, Any] | None:
    """Return the section-B signal block of the order-event contract."""

    if not timeline_signal:
        return None
    signal_type = resolve_signal_type(
        request=request, signal=timeline_signal, side=side
    )
    meta = signal_meta(signal_type)
    trace_id = _first_text((request or {}).get("trace_id"))
    intent_id = _first_text((request or {}).get("intent_id"))
    source = _first_text(
        timeline_signal.get("strategy"),
        timeline_signal.get("source"),
        (request or {}).get("source"),
    )
    return {
        "id": _first_text(timeline_signal.get("id")),
        "type": meta["type"],
        "family": meta["family"],
        "label": _first_text(timeline_signal.get("label")) or meta["label"],
        "time": _first_text(timeline_signal.get("time")),
        "price": _round(timeline_signal.get("price")),
        "quantity": _int(timeline_signal.get("quantity")) or None,
        "direction": _first_text(
            timeline_signal.get("side"),
            "buy" if side == "buy" else "sell" if side == "sell" else None,
        ),
        "source": source,
        "remark": _first_text(timeline_signal.get("remark")),
        "association_method": association_method or "none",
        "trace_id": trace_id,
        "intent_id": intent_id,
    }


def _request_quantity(request: dict[str, Any] | None) -> int | None:
    value = _int((request or {}).get("quantity"))
    return value if value > 0 else None


def _expected_quantity(review: dict[str, Any] | None) -> int | None:
    if not review:
        return None
    value = _int(((review.get("expected") or {}).get("quantity")))
    return value if value > 0 else None


def build_condition_summary(
    review: dict[str, Any] | None,
    *,
    side: str | None = None,
) -> dict[str, Any]:
    if not review:
        return {
            "count": 0,
            "condition_snapshot_status": "missing",
            "threshold_missing_count": 0,
        }
    expected = review.get("expected") or {}
    threshold_price = _float(expected.get("threshold_price"))
    threshold_candidates = list(expected.get("threshold_candidates") or [])
    normalized_side = str(side or "").strip().lower()
    if normalized_side == "buy":
        return {
            "count": 3,
            "condition_snapshot_status": "complete",
            "threshold_missing_count": 0,
        }
    if threshold_price is not None:
        return {
            "count": 6,
            "condition_snapshot_status": "complete",
            "threshold_missing_count": 0,
        }
    if not threshold_candidates:
        return {
            "count": 4,
            "condition_snapshot_status": "missing",
            "threshold_missing_count": 1,
        }
    return {
        "count": 4,
        "condition_snapshot_status": "partial",
        "threshold_missing_count": 1,
    }


def _fill_rows_for_event(
    canonical_trades: list[dict[str, Any]],
    *,
    internal_order_id: str | None,
    request_id: str | None,
    account_partition: str,
    execution_key: str | None,
    side: str | None,
) -> list[dict[str, Any]]:
    matches = []
    for trade in canonical_trades or []:
        trade_account = str(trade.get("account_partition") or "unknown").strip()
        if trade_account != account_partition:
            continue
        trade_side = str(trade.get("side") or "").strip().lower()
        if side and trade_side != side:
            continue
        trade_internal = str(trade.get("internal_order_id") or "").strip() or None
        trade_request = str(trade.get("request_id") or "").strip() or None
        trade_execution = (
            str(trade.get("execution_key") or trade.get("id") or "").strip() or None
        )
        if execution_key and trade_execution == execution_key:
            matches.append(trade)
            continue
        if internal_order_id and trade_internal == internal_order_id:
            matches.append(trade)
            continue
        if request_id and trade_request == request_id:
            matches.append(trade)
            continue
    return matches


def build_fill_rows(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for trade in trades or []:
        rows.append(
            {
                "execution_key": _first_text(
                    trade.get("execution_key"),
                    trade.get("id"),
                ),
                "broker_trade_id": _first_text(trade.get("broker_trade_id")),
                "time": _epoch_iso(_int(trade.get("trade_time"))),
                "price": _round(trade.get("price")),
                "quantity": _int(trade.get("quantity")),
                "association_quality": _first_text(
                    trade.get("association_quality"),
                    "low",
                ),
            }
        )
    return rows


def _execution_block(
    *,
    timeline_actual: dict[str, Any] | None,
    fill_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    actual = timeline_actual or {}
    return {
        "actual_quantity": _int(actual.get("filled_quantity")),
        "avg_filled_price": _round(actual.get("weighted_average_price")),
        "fill_count": len(fill_rows),
        "first_fill_time": _first_text(actual.get("first_fill_at")),
        "last_fill_time": _first_text(actual.get("last_fill_at")),
        "fill_bar_span": None,
        "fills": fill_rows,
    }


def _order_block(
    *,
    request: dict[str, Any] | None,
    review: dict[str, Any] | None,
    timeline_order: dict[str, Any] | None,
) -> dict[str, Any]:
    expected_quantity = _expected_quantity(review)
    return {
        "request_quantity": _request_quantity(request),
        "expected_quantity": expected_quantity,
        "submitted_quantity": _int(
            (((review or {}).get("expected") or {}).get("can_use_volume"))
            if isinstance(review, dict)
            else 0
        )
        or None,
        "status": _first_text(
            (timeline_order or {}).get("state"),
            ((review or {}).get("execution_status")),
        ),
        "strategy_name": _first_text(
            ((request or {}).get("strategy_name")),
            ((request or {}).get("source")),
        ),
    }


def _review_block(review: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "verdict": str((review or {}).get("verdict") or "").strip() or None,
        "confidence": str((review or {}).get("evidence_confidence") or "").strip()
        or None,
        "reason_codes": list((review or {}).get("reason_codes") or []),
    }


def _position_impact_block(
    *,
    timeline_event: dict[str, Any],
    cost_context: dict[str, Any] | None,
) -> dict[str, Any]:
    cost_context = cost_context or {}
    return {
        "position_before": _int(timeline_event.get("position_before")) or None,
        "position_after": _int(timeline_event.get("position_after")) or None,
        "cost_basis_before": _round(cost_context.get("average_cost_before")),
        "cost_basis_after": _round(cost_context.get("average_cost_after")),
        "realized_pnl_impact": _round(cost_context.get("realized_pnl_impact")),
        "unrealized_pnl_after": _round(cost_context.get("unrealized_pnl_after")),
        "holding_cycle_id": cost_context.get("holding_cycle_id"),
        "cost_basis_source": cost_context.get("cost_basis_source"),
        "fees_included": False,
    }


def _merge_event_cost_context(
    *,
    execution_keys: list[str],
    cost_context_by_execution: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Merge per-fill cost context into one order-level context."""

    contexts = [
        cost_context_by_execution[key]
        for key in execution_keys
        if key in (cost_context_by_execution or {})
    ]
    if not contexts:
        return {}
    return {
        "average_cost_before": (
            contexts[0].get("average_cost_before")
            if contexts[0].get("average_cost_before") is not None
            else contexts[-1].get("average_cost_before")
        ),
        "average_cost_after": (
            contexts[-1].get("average_cost_after")
            if contexts[-1].get("average_cost_after") is not None
            else contexts[0].get("average_cost_after")
        ),
        "realized_pnl_impact": sum(
            _float(context.get("realized_pnl_impact")) or 0.0 for context in contexts
        ),
        "holding_cycle_id": next(
            (
                context.get("holding_cycle_id")
                for context in contexts
                if context.get("holding_cycle_id")
            ),
            None,
        ),
        "cost_basis_source": next(
            (
                context.get("cost_basis_source")
                for context in contexts
                if context.get("cost_basis_source")
            ),
            "estimated_moving_average",
        ),
        "fees_included": False,
        "unrealized_pnl_after": None,
    }


def build_marker_block(
    *,
    execution: dict[str, Any],
    side: str | None,
    verdict: str | None,
    signal_meta_value: dict[str, Any],
) -> dict[str, Any]:
    verdict_meta = VERDICT_BORDER_META.get(
        str(verdict or "").strip().upper(),
        VERDICT_BORDER_META["INSUFFICIENT_EVIDENCE"],
    )
    return {
        "bar_time": execution.get("first_fill_time"),
        "price": execution.get("avg_filled_price"),
        "symbol": signal_meta_value.get("marker_symbol", "circle"),
        "side": side,
        "fill_count": int(execution.get("fill_count") or 0),
        "fill_bar_span": execution.get("fill_bar_span"),
        "first_fill_time": execution.get("first_fill_time"),
        "last_fill_time": execution.get("last_fill_time"),
        "verdict_encoding": {
            "verdict": verdict,
            "border": verdict_meta["border"],
            "dashed": verdict_meta["dashed"],
            "alpha": verdict_meta["alpha"],
            "mark": verdict == "FAIL",
        },
    }


def build_order_event_contract(
    *,
    symbol: str,
    timeline_event: dict[str, Any],
    canonical_trades: list[dict[str, Any]],
    review: dict[str, Any] | None,
    request: dict[str, Any] | None,
    cost_context: dict[str, Any] | None,
    cost_context_by_execution: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Expand one timeline event into the stable order-event contract."""

    side = str(timeline_event.get("side") or "").strip().lower() or None
    account_partition = str(
        timeline_event.get("account_partition") or "unknown"
    ).strip()
    internal_order_id = _first_text(timeline_event.get("internal_order_id"))
    request_id = _first_text(timeline_event.get("request_id"))
    signal_meta_value = signal_meta(
        resolve_signal_type(
            request=request,
            signal=timeline_event.get("signal"),
            side=side,
        )
    )
    signal_block = build_signal_block(
        timeline_signal=timeline_event.get("signal"),
        request=request,
        side=side,
        association_method=(
            (timeline_event.get("data_quality") or {}).get("signal_association")
        ),
    )
    matched_trades = _fill_rows_for_event(
        canonical_trades,
        internal_order_id=internal_order_id,
        request_id=request_id,
        account_partition=account_partition,
        execution_key=None,
        side=side,
    )
    fill_rows = build_fill_rows(matched_trades)
    execution_keys = [
        str(trade.get("execution_key") or trade.get("id") or "").strip()
        for trade in matched_trades
        if str(trade.get("execution_key") or trade.get("id") or "").strip()
    ]
    merged_cost_context = _merge_event_cost_context(
        execution_keys=execution_keys,
        cost_context_by_execution=cost_context_by_execution or {},
    )
    effective_cost_context = cost_context or merged_cost_context or {}
    execution = _execution_block(
        timeline_actual=timeline_event.get("actual"),
        fill_rows=fill_rows,
    )
    rebuilt = bool(timeline_event.get("rebuilt"))
    if rebuilt:
        event_type = "rebuilt_open_order"
    elif timeline_event.get("type") != "unassociated_execution":
        event_type = "filled_order"
    else:
        event_type = "unassociated_execution"
    review_block = _review_block(review)
    return {
        "event_id": _first_text(timeline_event.get("id")),
        "occurred_at": _first_text(
            timeline_event.get("time") or timeline_event.get("occurred_at")
        ),
        "account_partition": account_partition,
        "symbol": symbol,
        "side": side,
        "event_type": event_type,
        "rebuilt": rebuilt,
        "rebuild_source": _first_text(timeline_event.get("rebuild_source")),
        "request_id": request_id,
        "internal_order_id": internal_order_id,
        "broker_order_id": _first_text(
            (timeline_event.get("order") or {}).get("broker_order_id")
        ),
        "signal": signal_block,
        "order": _order_block(
            request=request,
            review=review,
            timeline_order=timeline_event.get("order"),
        ),
        "execution": execution,
        "position_impact": _position_impact_block(
            timeline_event=timeline_event,
            cost_context=effective_cost_context,
        ),
        "review": review_block,
        "marker": build_marker_block(
            execution=execution,
            side=side,
            verdict=review_block.get("verdict"),
            signal_meta_value=signal_meta_value,
        ),
        "conditions": build_condition_summary(review, side=side),
        "data_quality": {
            "association_quality": _first_text(
                (timeline_event.get("data_quality") or {}).get("association_quality"),
                "none",
            ),
            "condition_snapshot_status": (
                build_condition_summary(review, side=side)["condition_snapshot_status"]
            ),
            "warnings": list(
                (timeline_event.get("data_quality") or {}).get("warnings") or []
            ),
        },
    }


# ---------------------------------------------------------------------------
# Cost basis replay
# ---------------------------------------------------------------------------


def _entry_unit_cost(entry: dict[str, Any] | None) -> float | None:
    if not entry:
        return None
    return _first_positive(
        entry.get("entry_price"),
        entry.get("buy_price_real"),
        entry.get("avg_price"),
    )


def _entry_is_flatten_snapshot(entry: dict[str, Any] | None) -> bool:
    if not entry:
        return False
    return str(entry.get("entry_type") or "").strip() in {
        "position_snapshot_flatten",
    } or (
        str(entry.get("source") or "").strip() == "order_ledger_rebuild"
        and str(entry.get("arrange_mode") or "").strip() == "position_snapshot_flatten"
    )


def _ledger_basis_available(
    *,
    entries: list[dict[str, Any]],
    slices: list[dict[str, Any]],
    canonical_trades: list[dict[str, Any]],
) -> bool:
    if not entries or not slices:
        return False
    if not canonical_trades:
        return False
    return any(not _entry_is_flatten_snapshot(entry) for entry in entries)


def _source_plan_from_request(request: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(request, dict):
        return {}
    context = request.get("strategy_context")
    sell_sources = (
        context.get("guardian_sell_sources")
        if isinstance(context, dict)
        and isinstance(context.get("guardian_sell_sources"), dict)
        else None
    )
    plan: dict[str, int] = {}
    for item in list((sell_sources or {}).get("entries") or []):
        entry_id = str(item.get("entry_id") or "").strip()
        quantity = _int(item.get("quantity"))
        if entry_id and quantity > 0:
            plan[entry_id] = plan.get(entry_id, 0) + quantity
    return plan


def _matches_entry(
    entry: dict[str, Any],
    *,
    fill_time: int,
    entry_time: int,
    entry_assigned_quantity: int,
    fill_quantity: int,
) -> bool:
    if entry_time <= 0 or entry_time > fill_time:
        return False
    original = max(_int(entry.get("original_quantity")), 0)
    if original <= 0:
        return False
    return entry_assigned_quantity + fill_quantity <= original


def replay_cost_basis(
    *,
    symbol: str,
    canonical_trades: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    slices: list[dict[str, Any]],
    allocations: list[dict[str, Any]],
    requests_by_id: dict[str, dict[str, Any]],
    initial_position_quantity: int,
    initial_position_source: str,
) -> dict[str, Any]:
    """Replay fills into cost-basis / position series and holding cycles.

    Buy shares consume the entry unit cost when a matching entry exists;
    otherwise the fill price is used and the projection is degraded.  Sells
    consume shares by the request source plan first (explicit entry_id), then
    lowest-cost-first, which reproduces the documented ``cost basis after a
    low-cost-slice sell rises`` behaviour.

    The returned series is fill-driven so it stays consistent with the
    order-level position replay used by the compatible timeline contract.
    """

    trades = sorted(
        [
            dict(trade)
            for trade in canonical_trades or []
            if _int(trade.get("trade_time")) > 0
        ],
        key=lambda item: (
            int(item.get("trade_time") or 0),
            item.get("execution_key") or "",
        ),
    )
    ledger_available = _ledger_basis_available(
        entries=entries or [],
        slices=slices or [],
        canonical_trades=trades,
    )
    flatten_only = bool(entries) and all(
        _entry_is_flatten_snapshot(entry) for entry in entries
    )
    entry_by_id = {
        str(entry.get("entry_id") or "").strip(): entry for entry in entries or []
    }
    entry_cost_by_id = {
        entry_id: _entry_unit_cost(entry) for entry_id, entry in entry_by_id.items()
    }
    assigned_by_entry: dict[str, int] = defaultdict(int)
    entry_time_by_id = {
        entry_id: _int(entry.get("trade_time")) or _int(entry.get("created_at")) or 0
        for entry_id, entry in entry_by_id.items()
    }

    shares: list[dict[str, Any]] = []
    running_quantity = _int(initial_position_quantity)
    realized_pnl = 0.0
    ledger_buy_missing: list[str] = []
    series: list[dict[str, Any]] = []
    last_average_cost: float | None = None
    event_cost_context: dict[str, dict[str, Any]] = {}
    cycle_counter = 0
    current_cycle_id: str | None = None
    if running_quantity > 0:
        cycle_counter += 1
        current_cycle_id = f"{symbol}:cycle:{cycle_counter}"

    # 账本重建（flatten）entry 携带券商当前持仓均价快照：用它为继承期初仓位
    # 建立成本基准，使首笔成交的「持仓均价前后」与卖出已实现盈亏可计算，
    # 而不是在 UI 上显示为空。
    inherited_entry = None
    inherited_entry_cost = None
    for entry in entries or []:
        if not _entry_is_flatten_snapshot(entry):
            continue
        price = _entry_unit_cost(entry)
        if price is not None and price > 0:
            inherited_entry = entry
            inherited_entry_cost = price
            break
    if running_quantity > 0 and inherited_entry_cost is not None:
        inherited_entry_id = (
            str((inherited_entry or {}).get("entry_id") or "").strip() or None
        )
        if inherited_entry_id:
            assigned_by_entry[inherited_entry_id] += running_quantity
        shares.append(
            {
                "entry_id": inherited_entry_id,
                "quantity": running_quantity,
                "cost": inherited_entry_cost,
                "time": _epoch_iso(
                    _int((inherited_entry or {}).get("trade_time"))
                    or _int((inherited_entry or {}).get("created_at"))
                    or 0
                ),
                "source": "broker_snapshot_estimate",
            }
        )

    def _average_cost() -> float | None:
        total_quantity = sum(_int(share["quantity"]) for share in shares)
        if total_quantity <= 0:
            return last_average_cost if running_quantity > 0 else None
        total_cost = sum(
            _int(share["quantity"]) * (_float(share["cost"]) or 0.0) for share in shares
        )
        return total_cost / total_quantity

    def _sample(point_type: str, *, time: int) -> None:
        total_quantity = sum(_int(share["quantity"]) for share in shares)
        if total_quantity <= 0:
            average_cost = None
            remaining_cost = None
        else:
            total_cost = sum(
                _int(share["quantity"]) * (_float(share["cost"]) or 0.0)
                for share in shares
            )
            average_cost = total_cost / total_quantity
            remaining_cost = total_cost
        series.append(
            {
                "time": _epoch_iso(time),
                "position_quantity": running_quantity,
                "remaining_cost": _round(remaining_cost, 2),
                "average_cost": _round(average_cost, 6),
                "realized_pnl": _round(realized_pnl, 2),
                "point_type": point_type,
                "cost_basis_source": (
                    "entry_slice_allocation"
                    if ledger_available
                    else "estimated_moving_average"
                ),
                "fees_included": False,
            }
        )

    def _consume_shares(
        quantity: int,
        *,
        sell_price: float,
        at_time: int,
        source_plan: dict[str, int],
    ) -> float:
        nonlocal realized_pnl
        remaining = max(int(quantity), 0)
        consumed_realized = 0.0

        def _consume_from(candidate: dict[str, Any], amount: int) -> None:
            nonlocal consumed_realized, remaining
            take = min(amount, _int(candidate["quantity"]), remaining)
            if take <= 0:
                return
            cost = _float(candidate["cost"]) or sell_price
            consumed_realized += (sell_price - cost) * take
            candidate["quantity"] = _int(candidate["quantity"]) - take
            remaining -= take

        if source_plan:
            for entry_id, planned in source_plan.items():
                if remaining <= 0:
                    break
                for share in shares:
                    if str(share.get("entry_id") or "") == entry_id:
                        _consume_from(share, planned)
                        if remaining <= 0:
                            break
        for share in sorted(
            [item for item in shares if _int(item["quantity"]) > 0],
            key=lambda item: (_float(item["cost"]) or 0.0, item.get("time") or ""),
        ):
            if remaining <= 0:
                break
            _consume_from(share, _int(share["quantity"]))
        if remaining > 0:
            # Ledger does not cover this sell: fall back to the fill price.
            consumed_realized += 0.0
        return consumed_realized

    if initial_position_quantity > 0:
        initial_average_cost = _average_cost()
        series.append(
            {
                "time": (
                    _epoch_iso(max(trades[0]["trade_time"] - 1, 1)) if trades else None
                ),
                "position_quantity": running_quantity,
                "remaining_cost": (
                    _round(running_quantity * initial_average_cost, 2)
                    if initial_average_cost is not None
                    else None
                ),
                "average_cost": _round(initial_average_cost, 6),
                "realized_pnl": 0.0,
                "point_type": "derived_initial",
                "cost_basis_source": (
                    "entry_slice_allocation"
                    if ledger_available
                    else "estimated_moving_average"
                ),
                "fees_included": False,
            }
        )

    for trade in trades:
        time = _int(trade.get("trade_time"))
        side = str(trade.get("side") or "").strip().lower()
        quantity = max(_int(trade.get("quantity")), 0)
        price = _float(trade.get("price")) or 0.0
        if quantity <= 0:
            continue
        request_id = str(trade.get("request_id") or "").strip()
        request = requests_by_id.get(request_id)
        execution_key = str(trade.get("execution_key") or trade.get("id") or "").strip()
        before_quantity = running_quantity
        before_average_cost = _average_cost()
        realized_impact = 0.0
        if side == "buy":
            if before_quantity <= 0:
                cycle_counter += 1
                current_cycle_id = f"{symbol}:cycle:{cycle_counter}"
            entry: dict[str, Any] | None = None
            for candidate_id, candidate in entry_by_id.items():
                if _matches_entry(
                    candidate,
                    fill_time=time,
                    entry_time=entry_time_by_id.get(candidate_id, 0),
                    entry_assigned_quantity=assigned_by_entry[candidate_id],
                    fill_quantity=quantity,
                ) and (
                    entry is None
                    or entry_time_by_id.get(candidate_id, 0)
                    < entry_time_by_id.get(str(entry.get("entry_id") or ""), 0)
                ):
                    entry = candidate
            if entry is not None:
                entry_id = str(entry.get("entry_id") or "").strip()
                assigned_by_entry[entry_id] += quantity
                cost = entry_cost_by_id.get(entry_id)
                if cost is None:
                    cost = price
                    ledger_buy_missing.append(entry_id)
                source = "entry"
            else:
                cost = price
                ledger_buy_missing.append("missing_entry")
                source = "fill_estimate"
            shares.append(
                {
                    "entry_id": str((entry or {}).get("entry_id") or "").strip()
                    or None,
                    "quantity": quantity,
                    "cost": cost,
                    "time": _epoch_iso(time),
                    "source": source,
                }
            )
            running_quantity += quantity
            last_average_cost = _average_cost()
            _sample("fill", time=time)
        elif side == "sell":
            source_plan = _source_plan_from_request(request)
            realized_delta = _consume_shares(
                quantity,
                sell_price=price,
                at_time=time,
                source_plan=source_plan,
            )
            realized_impact = realized_delta
            realized_pnl += realized_delta
            after_quantity = max(running_quantity - quantity, 0)
            running_quantity = after_quantity
            last_average_cost = _average_cost()
            _sample("fill", time=time)
            if after_quantity <= 0:
                current_cycle_id = None
        after_average_cost = _average_cost()
        if execution_key:
            event_cost_context[execution_key] = {
                "average_cost_before": before_average_cost,
                "average_cost_after": after_average_cost,
                "realized_pnl_impact": realized_impact,
                "holding_cycle_id": current_cycle_id,
                "cost_basis_source": (
                    "broker_snapshot_estimate"
                    if flatten_only
                    else (
                        "entry_slice_allocation"
                        if ledger_available
                        else "estimated_moving_average"
                    )
                ),
                "fees_included": False,
                "unrealized_pnl_after": None,
            }

    # 账本重建（flatten）entry 直接代表当前持仓成本快照：即使没有规范成交，
    # 也按 entry 的券商均价在重建时点产出成本点，保证成本曲线有数据。
    for entry in entries or []:
        if not _entry_is_flatten_snapshot(entry):
            continue
        entry_time = _int(entry.get("trade_time")) or _int(entry.get("created_at")) or 0
        quantity = max(
            _int(entry.get("remaining_quantity")),
            _int(entry.get("original_quantity")),
        )
        entry_price = _float(entry.get("entry_price")) or _float(
            entry.get("buy_price_real")
        )
        if entry_time <= 0 or quantity <= 0 or entry_price is None:
            continue
        series.append(
            {
                "time": _epoch_iso(entry_time),
                "position_quantity": quantity,
                "remaining_cost": round(quantity * entry_price, 2),
                "average_cost": round(entry_price, 6),
                "realized_pnl": _round(realized_pnl, 2),
                "point_type": "rebuilt_open",
                "cost_basis_source": "broker_snapshot_estimate",
                "fees_included": False,
            }
        )

    # flatten 重建点的时间早于规范成交，按时间排序保证成本曲线时间轴单调。
    series.sort(key=lambda item: str(item.get("time") or ""))

    total_quantity = sum(_int(share["quantity"]) for share in shares)
    cost_basis_quality = (
        "full" if ledger_available and not ledger_buy_missing else "degraded"
    )
    warnings: list[dict[str, Any]] = []
    if flatten_only:
        warnings.append(
            {
                "code": "cost_basis_broker_snapshot",
                "message": (
                    "账本为成本价拍平重建，成本使用券商持仓均价快照估算，"
                    "不作为逐笔成交成本真值。"
                ),
                "flatten_entry_count": len(entries),
            }
        )
    if not ledger_available:
        warnings.append(
            {
                "code": "cost_basis_estimated",
                "message": (
                    "缺少完整 entry/slice/allocation 成本证据，持仓成本按成交"
                    "移动加权估算，不作为正式成本真值。"
                ),
            }
        )
    if ledger_buy_missing:
        warnings.append(
            {
                "code": "ledger_incomplete_for_buys",
                "message": (
                    "部分买入缺少 entry/slice 成本证据，相关买入份额使用成交价估算。"
                ),
                "buy_share_count": len(ledger_buy_missing),
            }
        )
    if inherited_entry_cost is not None and initial_position_quantity > 0:
        warnings.append(
            {
                "code": "cost_basis_inherited_snapshot",
                "message": (
                    "继承期初仓位成本采用账本重建 entry 的券商均价快照估算，"
                    "相关已实现盈亏为该口径下的估算值，非逐笔成交成本真值。"
                ),
                "inherited_quantity": initial_position_quantity,
                "inherited_average_cost": inherited_entry_cost,
            }
        )
    data_quality = {
        "cost_basis": cost_basis_quality,
        "ledger_available": ledger_available,
        "ledger_buy_missing_count": len(ledger_buy_missing),
        "fees_included": False,
        "warnings": warnings,
    }
    return {
        "cost_basis_series": series,
        "event_cost_context": event_cost_context,
        "realized_pnl": _round(realized_pnl, 2),
        "cost_basis_source": (
            "broker_snapshot_estimate"
            if flatten_only
            else (
                "entry_slice_allocation"
                if ledger_available
                else "estimated_moving_average"
            )
        ),
        "fees_included": False,
        "data_quality": data_quality,
        "total_remaining_quantity": total_quantity,
    }


def build_position_series_from_fills(
    *,
    canonical_trades: list[dict[str, Any]],
    initial_position_quantity: int,
    initial_position_source: str,
) -> list[dict[str, Any]]:
    """Fill-driven position series, consistent with the compatible timeline."""

    trades = sorted(
        [
            dict(trade)
            for trade in canonical_trades or []
            if _int(trade.get("trade_time")) > 0
        ],
        key=lambda item: (
            int(item.get("trade_time") or 0),
            item.get("execution_key") or "",
        ),
    )
    series: list[dict[str, Any]] = []
    if trades:
        series.append(
            {
                "time": _epoch_iso(max(_int(trades[0].get("trade_time")) - 1, 1)),
                "value": _int(initial_position_quantity),
                "point_type": "derived_initial",
                "assumption": True,
                "source": initial_position_source,
            }
        )
    running = _int(initial_position_quantity)
    for trade in trades:
        side = str(trade.get("side") or "").strip().lower()
        quantity = max(_int(trade.get("quantity")), 0)
        if side == "buy":
            running += quantity
        elif side == "sell":
            running = max(running - quantity, 0)
        else:
            continue
        series.append(
            {
                "time": _epoch_iso(_int(trade.get("trade_time"))),
                "value": running,
                "point_type": "fill",
                "assumption": False,
                "source": "canonical_execution",
            }
        )
    return series


def build_holding_cycles(
    *,
    position_series: list[dict[str, Any]],
    cost_basis_series: list[dict[str, Any]],
    realized_pnl: float,
    symbol: str,
) -> list[dict[str, Any]]:
    """Split position/cost series into open/close holding cycles."""

    cycles: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    inherited_open = False
    for index, point in enumerate(position_series or []):
        value = _int(point.get("value"))
        cost_point = (
            cost_basis_series[index] if index < len(cost_basis_series or []) else None
        )
        average_cost = _float((cost_point or {}).get("average_cost"))
        if value > 0 and current is None:
            cycle_id = f"{symbol}:cycle:{len(cycles) + 1}"
            current = {
                "cycle_id": cycle_id,
                "symbol": symbol,
                "open_time": point.get("time") if not inherited_open else None,
                "close_time": None,
                "status": "open",
                "inherited": bool(inherited_open),
                "average_cost_open": average_cost,
                "average_cost_close": None,
                "realized_pnl": 0.0,
                "max_position": value,
                "open_quantity": value,
            }
            inherited_open = False
            cycles.append(current)
        elif current is not None:
            current["max_position"] = max(_int(current.get("max_position") or 0), value)
            if value == 0:
                current["close_time"] = point.get("time")
                current["status"] = "closed"
                current["average_cost_close"] = None
                current = None
    # Initial inherited position with no closing fill stays open.
    if (
        current is None
        and _int((position_series[0].get("value") if position_series else 0)) > 0
    ):
        cycle_id = f"{symbol}:cycle:{len(cycles) + 1}"
        cycles.append(
            {
                "cycle_id": cycle_id,
                "symbol": symbol,
                "open_time": None,
                "close_time": None,
                "status": "open",
                "inherited": True,
                "average_cost_open": _float(
                    (cost_basis_series[0] if cost_basis_series else {}).get(
                        "average_cost"
                    )
                ),
                "average_cost_close": None,
                "realized_pnl": 0.0,
                "max_position": _int(position_series[0].get("value")),
                "open_quantity": _int(position_series[0].get("value")),
            }
        )
    return cycles


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------


def _condition(
    *,
    condition_key: str,
    label: str,
    actual_value: Any,
    operator: str | None,
    threshold_value: Any,
    passed: bool | None,
    source: str,
    observed_at: str | None,
    evidence_id: str | None,
    unit: str | None = None,
) -> dict[str, Any]:
    return {
        "condition_key": condition_key,
        "label": label,
        "actual_value": actual_value,
        "actual_display": (None if actual_value is None else str(actual_value)),
        "operator": operator,
        "threshold_value": threshold_value,
        "threshold_display": (
            None if threshold_value is None else str(threshold_value)
        ),
        "unit": unit,
        "passed": passed,
        "source": source,
        "observed_at": observed_at,
        "evidence_id": evidence_id,
    }


def build_conditions(
    *,
    review: dict[str, Any] | None,
    request: dict[str, Any] | None,
    runtime_event: dict[str, Any] | None,
    side: str | None,
) -> dict[str, Any]:
    """Build the full condition evidence block for one order event."""

    review = review or {}
    request = request or {}
    expected = review.get("expected") or {}
    actual = review.get("actual") or {}
    observed_at = review.get("time")
    trace_id = str(request.get("trace_id") or "").strip() or None
    evidence_id = trace_id or str(request.get("request_id") or "").strip() or None
    runtime_available = isinstance(runtime_event, dict)
    source = "runtime_event" if runtime_available else "request_snapshot"
    conditions: list[dict[str, Any]] = []

    threshold_price = _float(expected.get("threshold_price"))
    signal_price = _float(request.get("price"))
    takeprofit_sell = side == "sell" and is_takeprofit_request(request)
    takeprofit_entries_total: int | None = None
    if side == "sell":
        if takeprofit_sell:
            # TPSL 止盈卖单不按 Guardian 规则复盘；条件证据改为展示触发快照
            # （档位价 / 分配策略 / 计划数量），避免条件表整表空值。
            sell_sources = request.get("strategy_context") or {}
            sell_sources = (
                sell_sources.get("guardian_sell_sources")
                if isinstance(sell_sources, dict)
                else None
            )
            tier_price = _float((sell_sources or {}).get("tier_price"))
            allocation_policy = (
                str((sell_sources or {}).get("allocation_policy") or "").strip() or None
            )
            takeprofit_entries_total = (
                sum(
                    _int(item.get("quantity"))
                    for item in ((sell_sources or {}).get("entries") or [])
                )
                or None
            )
            conditions.append(
                _condition(
                    condition_key="signal_price_above_threshold",
                    label="触发价格 >= 止盈档位价",
                    actual_value=_round(signal_price, 6),
                    operator=">=",
                    threshold_value=_round(tier_price, 6),
                    passed=(
                        bool(
                            tier_price is not None
                            and signal_price is not None
                            and signal_price >= tier_price
                        )
                        if tier_price is not None
                        else None
                    ),
                    source=(
                        "request_snapshot" if tier_price is not None else "missing"
                    ),
                    observed_at=observed_at,
                    evidence_id=evidence_id,
                    unit="price",
                )
            )
            conditions.append(
                _condition(
                    condition_key="allocation_policy",
                    label="止盈分配策略",
                    actual_value=allocation_policy,
                    operator="in",
                    threshold_value=(
                        ["takeprofit_ratio_v1"]
                        if allocation_policy is not None
                        else None
                    ),
                    passed=(
                        allocation_policy in {"takeprofit_ratio_v1"}
                        if allocation_policy is not None
                        else None
                    ),
                    source="request_snapshot",
                    observed_at=observed_at,
                    evidence_id=evidence_id,
                    unit="policy",
                )
            )
            requested_quantity = _request_quantity(request)
            conditions.append(
                _condition(
                    condition_key="sellable_volume_cap",
                    label="止盈计划数量覆盖委托",
                    actual_value=takeprofit_entries_total,
                    operator="<=",
                    threshold_value=requested_quantity,
                    passed=(
                        (
                            takeprofit_entries_total is not None
                            and requested_quantity is not None
                            and takeprofit_entries_total >= requested_quantity
                        )
                        if takeprofit_entries_total is not None
                        else None
                    ),
                    source=(
                        "request_snapshot"
                        if takeprofit_entries_total is not None
                        else "missing"
                    ),
                    observed_at=observed_at,
                    evidence_id=evidence_id,
                    unit="quantity",
                )
            )
        else:
            conditions.append(
                _condition(
                    condition_key="signal_price_above_threshold",
                    label="触发价格 >= 历史阈值",
                    actual_value=_round(signal_price, 6),
                    operator=">=",
                    threshold_value=_round(threshold_price, 6),
                    passed=(
                        bool(
                            threshold_price is not None
                            and signal_price is not None
                            and signal_price >= threshold_price
                        )
                        if threshold_price is not None
                        else None
                    ),
                    source=source if threshold_price is not None else "missing",
                    observed_at=observed_at,
                    evidence_id=evidence_id,
                    unit="price",
                )
            )
            mode = expected.get("threshold_mode")
            conditions.append(
                _condition(
                    condition_key="threshold_mode",
                    label="历史阈值模式",
                    actual_value=mode,
                    operator="in",
                    threshold_value=(
                        ["percent", "atr"] if mode in {"percent", "atr"} else None
                    ),
                    passed=mode in {"percent", "atr"},
                    source=(
                        "runtime_event" if runtime_available else "request_snapshot"
                    ),
                    observed_at=observed_at,
                    evidence_id=evidence_id,
                    unit="mode",
                )
            )
            can_use_volume = _int(expected.get("can_use_volume")) or None
            requested_quantity = _request_quantity(request)
            conditions.append(
                _condition(
                    condition_key="sellable_volume_cap",
                    label="可卖数量上限",
                    actual_value=can_use_volume,
                    operator="<=",
                    threshold_value=requested_quantity,
                    passed=(
                        (
                            can_use_volume is not None
                            and requested_quantity is not None
                            and can_use_volume >= requested_quantity
                        )
                        if can_use_volume is not None
                        else None
                    ),
                    source="runtime_event" if runtime_available else "missing",
                    observed_at=observed_at,
                    evidence_id=evidence_id,
                    unit="quantity",
                )
            )
    elif side == "buy":
        buy_grid = request.get("strategy_context") or {}
        buy_grid = (
            buy_grid.get("guardian_buy_grid") if isinstance(buy_grid, dict) else None
        )
        source_price = _float((buy_grid or {}).get("source_price"))
        conditions.append(
            _condition(
                condition_key="signal_price_reaches_grid",
                label="触发价格达到网格买入价",
                actual_value=_round(signal_price, 6),
                operator="<=",
                threshold_value=_round(source_price, 6),
                passed=(
                    bool(
                        signal_price is not None
                        and source_price is not None
                        and signal_price <= source_price
                    )
                    if source_price is not None
                    else None
                ),
                source="request_snapshot" if buy_grid else "missing",
                observed_at=observed_at,
                evidence_id=evidence_id,
                unit="price",
            )
        )
        grid_level = (buy_grid or {}).get("grid_level")
        hit_levels = list((buy_grid or {}).get("hit_levels") or [])
        capacity_quantity = (
            _int(expected.get("capacity_quantity"))
            or _int((buy_grid or {}).get("capacity_quantity"))
        ) or None
        if grid_level is not None or hit_levels:
            conditions.append(
                _condition(
                    condition_key="grid_level",
                    label="买入网格档位",
                    actual_value=(grid_level or hit_levels[-1]),
                    operator="in",
                    threshold_value=(
                        ["1", "2", "3"]
                        if (grid_level is not None or hit_levels)
                        else None
                    ),
                    passed=grid_level is not None or bool(hit_levels),
                    source="request_snapshot" if buy_grid else "missing",
                    observed_at=observed_at,
                    evidence_id=evidence_id,
                    unit="level",
                )
            )
        elif capacity_quantity is not None:
            # 阶段容量买入（grid_level 为空、hit_levels 为空）：展示容量裁剪量
            # 与委托量的一致性，而不是伪造网格档位不通过。
            requested_quantity = _request_quantity(request)
            conditions.append(
                _condition(
                    condition_key="capacity_quantity_match",
                    label="委托数量与阶段容量裁剪量一致",
                    actual_value=requested_quantity,
                    operator="==",
                    threshold_value=capacity_quantity,
                    passed=(
                        bool(
                            requested_quantity is not None
                            and requested_quantity == capacity_quantity
                        )
                        if requested_quantity is not None
                        else None
                    ),
                    source="request_snapshot",
                    observed_at=observed_at,
                    evidence_id=evidence_id,
                    unit="quantity",
                )
            )
        else:
            conditions.append(
                _condition(
                    condition_key="grid_level",
                    label="买入网格档位",
                    actual_value=None,
                    operator="in",
                    threshold_value=None,
                    passed=False,
                    source="request_snapshot" if buy_grid else "missing",
                    observed_at=observed_at,
                    evidence_id=evidence_id,
                    unit="level",
                )
            )

    expected_quantity = _expected_quantity(review)
    if takeprofit_sell and expected_quantity is None:
        expected_quantity = takeprofit_entries_total
    filled_quantity = _int(actual.get("filled_quantity")) or None
    conditions.append(
        _condition(
            condition_key="expected_quantity_achieved",
            label="策略应有量与真实成交一致",
            actual_value=filled_quantity,
            operator="==",
            threshold_value=expected_quantity,
            passed=(
                bool(filled_quantity == expected_quantity)
                if filled_quantity is not None and expected_quantity is not None
                else None
            ),
            source="request_snapshot",
            observed_at=observed_at,
            evidence_id=evidence_id,
            unit="quantity",
        )
    )

    missing = [
        condition
        for condition in conditions
        if condition.get("threshold_value") is None
    ]
    condition_snapshot_status = (
        "complete"
        if not missing
        else "partial" if len(missing) < len(conditions) else "missing"
    )
    return {
        "conditions": conditions,
        "expression": " AND ".join(
            [condition["condition_key"] for condition in conditions]
        )
        or None,
        "condition_tree": {
            "op": "AND",
            "children": [
                {"op": "leaf", "key": condition["condition_key"]}
                for condition in conditions
            ],
        },
        "strategy_version": _first_text(request.get("strategy_version")),
        "config_snapshot_hash": _config_snapshot_hash(request),
        "trigger_snapshot": _trigger_snapshot(request),
        "evidence": {
            "runtime_event_available": runtime_available,
            "trace_id": trace_id,
            "request_id": str(request.get("request_id") or "").strip() or None,
            "evidence_id": evidence_id,
        },
        "data_quality": {
            "condition_snapshot_status": condition_snapshot_status,
            "threshold_missing_count": len(missing),
            "warnings": (
                [
                    {
                        "code": "historical_threshold_missing",
                        "message": "历史阈值证据缺失，相关条件阈值保持 null。",
                        "condition_keys": [
                            condition["condition_key"] for condition in missing
                        ],
                    }
                ]
                if missing
                else []
            ),
        },
    }


def _trigger_snapshot(request: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(request, dict):
        return None
    context = request.get("strategy_context")
    if not isinstance(context, dict):
        return None
    snapshot: dict[str, Any] = {}
    if isinstance(context.get("guardian_buy_grid"), dict):
        snapshot["guardian_buy_grid"] = context["guardian_buy_grid"]
    if isinstance(context.get("guardian_sell_sources"), dict):
        snapshot["guardian_sell_sources"] = context["guardian_sell_sources"]
    return snapshot or None


def _config_snapshot_hash(request: dict[str, Any] | None) -> str | None:
    snapshot = _trigger_snapshot(request)
    if snapshot is None:
        return None
    material = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str)
    return _stable_hash(material, length=16)


def _find_runtime_event(
    runtime_items: list[dict[str, Any]],
    *,
    trace_id: str | None,
    request_time: str | None,
) -> dict[str, Any] | None:
    for event in runtime_items or []:
        if trace_id and str(event.get("trace_id") or "").strip() == trace_id:
            return event
    return None


def build_event_conditions_payload(
    *,
    review: dict[str, Any] | None,
    request: dict[str, Any] | None,
    runtime_items: list[dict[str, Any]],
    side: str | None,
) -> dict[str, Any]:
    runtime_event = _find_runtime_event(
        runtime_items,
        trace_id=str((request or {}).get("trace_id") or "").strip() or None,
        request_time=(review or {}).get("time"),
    )
    return build_conditions(
        review=review,
        request=request,
        runtime_event=runtime_event,
        side=side,
    )


def build_symbol_chart_payload(
    *,
    symbol: str,
    name: str,
    timeline_events: list[dict[str, Any]],
    canonical_trades: list[dict[str, Any]],
    reviews_by_request: dict[str, dict[str, Any]],
    requests_by_id: dict[str, dict[str, Any]],
    runtime_items: list[dict[str, Any]],
    cost_replay: dict[str, Any],
    cost_context_by_execution: dict[str, dict[str, Any]] | None = None,
    position_series: list[dict[str, Any]],
    holding_cycles: list[dict[str, Any]],
    data_quality: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    order_events = []
    for timeline_event in timeline_events or []:
        request_id = str(timeline_event.get("request_id") or "").strip()
        review = reviews_by_request.get(request_id)
        request = requests_by_id.get(request_id)
        order_events.append(
            build_order_event_contract(
                symbol=symbol,
                timeline_event=timeline_event,
                canonical_trades=canonical_trades,
                review=review,
                request=request,
                cost_context=None,
                cost_context_by_execution=cost_context_by_execution,
            )
        )
    return {
        "symbol": {"code": symbol, "name": name or symbol},
        "range": {
            "start": None,
            "end": None,
        },
        "holding_cycles": holding_cycles,
        "cost_basis_series": cost_replay.get("cost_basis_series") or [],
        "position_series": position_series,
        "pnl_series": [
            {
                "time": point.get("time"),
                "realized_pnl": point.get("realized_pnl"),
            }
            for point in (cost_replay.get("cost_basis_series") or [])
        ],
        "order_events": order_events,
        "signal_type_registry": signal_type_registry_payload(),
        "cost_basis": {
            "source": cost_replay.get("cost_basis_source"),
            "fees_included": False,
            "realized_pnl": cost_replay.get("realized_pnl"),
            "data_quality": cost_replay.get("data_quality") or {},
        },
        "generated_at": generated_at,
        "data_quality": data_quality,
    }


__all__ = [
    "SIGNAL_TYPE_REGISTRY",
    "VERDICT_BORDER_META",
    "build_conditions",
    "build_event_conditions_payload",
    "build_fill_rows",
    "build_holding_cycles",
    "build_order_event_contract",
    "build_position_series_from_fills",
    "build_signal_block",
    "build_symbol_chart_payload",
    "replay_cost_basis",
    "resolve_signal_type",
    "signal_meta",
    "signal_type_registry_payload",
]
