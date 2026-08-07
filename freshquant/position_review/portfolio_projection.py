# -*- coding: utf-8 -*-

"""Read-only portfolio overview projections for the position-review refactor.

The MVP focuses on market value, remaining cost, floating PnL, realized PnL,
monthly turnover, position ratio and contribution Top N.  Equity curve naming
always follows the available evidence level:

- ``broker_total_asset``     broker historical total-asset snapshots
- ``credit_snapshot_reconstructed``  credit/asset snapshot series rebuilt from
                              ``pm_credit_asset_snapshots``
- ``estimated``              only current snapshots / positions are available

Missing ranges are never interpolated and the equity basis is always returned
so the UI cannot present an estimate as a real asset figure.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


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


def _round(value, digits=2):
    number = _float(value)
    if number is None:
        return None
    return round(number, digits)


def _iso_time(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"None", "0", ""}:
        return None
    return text


def _verdict_counts(reviews_by_request: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts = {
        "PASS": 0,
        "FAIL": 0,
        "INSUFFICIENT_EVIDENCE": 0,
        "NOT_APPLICABLE": 0,
    }
    for review in reviews_by_request.values():
        verdict = str(review.get("verdict") or "").strip().upper()
        if verdict in counts:
            counts[verdict] += 1
    return counts


def _signal_type_counts(
    reviews_by_request: dict[str, dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for review in reviews_by_request.values():
        signal_type = str(
            (review.get("signal") or {}).get("type") or "unknown"
        ).strip()
        if not signal_type:
            signal_type = "unknown"
        counts[signal_type] += 1
    return dict(counts)


def _remaining_cost_and_pnl(
    *,
    symbol_meta: dict[str, Any],
    position_snapshot: dict[str, Any] | None,
    cost_replay: dict[str, Any] | None,
) -> tuple[float | None, float | None, bool]:
    """Return (remaining_cost, floating_pnl) for one symbol.

    Prefers the ledger replay average cost when available, otherwise falls
    back to the broker average price snapshot.  The third return value marks
    whether the broker estimate was used.
    """

    quantity = _int((position_snapshot or {}).get("volume"))
    market_value = _float((position_snapshot or {}).get("market_value"))
    if market_value is None and quantity > 0:
        last_price = _float((position_snapshot or {}).get("last_price"))
        market_value = (
            round(quantity * last_price, 2) if last_price is not None else None
        )
    average_cost = None
    cost_source = "estimated_moving_average"
    used_estimate = True
    if cost_replay and (cost_replay.get("cost_basis_series") or []):
        last_point = cost_replay["cost_basis_series"][-1]
        average_cost = _float(last_point.get("average_cost"))
        cost_source = str(last_point.get("cost_basis_source") or cost_source)
        used_estimate = cost_source == "estimated_moving_average"
    if average_cost is None:
        average_cost = _float((position_snapshot or {}).get("avg_price"))
    if quantity <= 0 or average_cost is None:
        return None, None, False
    remaining_cost = round(quantity * average_cost, 2)
    floating_pnl = (
        round(market_value - remaining_cost, 2)
        if market_value is not None
        else None
    )
    return remaining_cost, floating_pnl, used_estimate


def build_portfolio_summary(
    *,
    catalog_rows: list[dict[str, Any]],
    detail_by_symbol: dict[str, dict[str, Any]],
    cost_by_symbol: dict[str, dict[str, Any]],
    position_by_symbol: dict[str, dict[str, Any]],
    xt_assets: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    market_value = 0.0
    remaining_cost = 0.0
    floating_pnl = 0.0
    realized_pnl = 0.0
    buy_amount = 0.0
    sell_amount = 0.0
    monthly_turnover: dict[str, dict[str, Any]] = {}
    reviewable = 0
    verdict_counts = {
        "PASS": 0,
        "FAIL": 0,
        "INSUFFICIENT_EVIDENCE": 0,
        "NOT_APPLICABLE": 0,
    }
    signal_type_counts: dict[str, int] = defaultdict(int)
    degraded_cost_symbols = 0
    estimated_cost_symbols = 0

    for symbol in detail_by_symbol:
        detail = detail_by_symbol[symbol] or {}
        reviews_by_request = {
            str(review.get("request_id") or "").strip(): review
            for review in (detail.get("reviews") or [])
            if str(review.get("request_id") or "").strip()
        }
        for verdict, count in _verdict_counts(reviews_by_request).items():
            verdict_counts[verdict] += count
        reviewable += verdict_counts["PASS"] + verdict_counts["FAIL"]
        for signal_type, count in _signal_type_counts(reviews_by_request).items():
            signal_type_counts[signal_type] += count
        for review in reviews_by_request.values():
            request = review.get("request") or {}
            requested = _int(request.get("quantity"))
            side = str(review.get("side") or "").strip().lower()
            price = _float(request.get("price"))
            if requested <= 0 or price is None:
                continue
            amount = round(requested * price, 2)
            time_text = review.get("time") or ""
            month = time_text[:7] if len(time_text) >= 7 else None
            if not month:
                continue
            bucket = monthly_turnover.setdefault(
                month, {"month": month, "buy": 0.0, "sell": 0.0}
            )
            bucket[side if side in {"buy", "sell"} else "buy"] += amount

        summary = detail.get("summary") or {}
        buy_amount += _float(summary.get("buy_amount")) or 0.0
        sell_amount += _float(summary.get("sell_amount")) or 0.0
        cost_replay = cost_by_symbol.get(symbol) or {}
        realized_pnl += _float(cost_replay.get("realized_pnl")) or 0.0
        cost_basis_quality = (
            (cost_replay.get("data_quality") or {}).get("cost_basis")
        )
        if cost_basis_quality == "degraded":
            degraded_cost_symbols += 1

    # Market value, remaining cost and floating PnL cover every position
    # snapshot (broker truth), not only the symbols that have review evidence.
    for symbol, position in position_by_symbol.items():
        detail = detail_by_symbol.get(symbol) or {}
        cost_replay = cost_by_symbol.get(symbol) or {}
        position_value = _float(position.get("market_value")) or 0.0
        market_value += position_value
        cost_value, floating_value, used_estimate = _remaining_cost_and_pnl(
            symbol_meta=detail.get("symbol") or {},
            position_snapshot=position,
            cost_replay=cost_replay,
        )
        if used_estimate:
            estimated_cost_symbols += 1
        if cost_value is None:
            continue
        remaining_cost += cost_value
        if floating_value is not None:
            floating_pnl += floating_value

    # Closed symbols still contribute their realized PnL.
    for symbol, cost_replay in cost_by_symbol.items():
        if symbol in position_by_symbol:
            continue
        realized_pnl += _float(cost_replay.get("realized_pnl")) or 0.0

    current_asset = None
    cash = None
    equity_basis = "estimated"
    if xt_assets:
        latest = sorted(
            xt_assets,
            key=lambda item: str(item.get("updated_at") or item.get("queried_at") or ""),
        )[-1]
        current_asset = _float(latest.get("total_asset"))
        cash = _float(latest.get("cash"))
        if current_asset is not None:
            equity_basis = "broker_total_asset"

    position_ratio = (
        round(market_value / current_asset, 6)
        if current_asset and market_value > 0
        else None
    )
    return {
        "generated_at": generated_at,
        "kpis": {
            "total_asset": _round(current_asset),
            "market_value": _round(market_value),
            "remaining_cost": _round(remaining_cost),
            "floating_pnl": _round(floating_pnl),
            "realized_pnl": _round(realized_pnl),
            "position_ratio": position_ratio,
            "cash": _round(cash),
        },
        "monthly_turnover": [
            monthly_turnover[key]
            for key in sorted(monthly_turnover)
            if monthly_turnover[key]
        ],
        "verdict_counts": verdict_counts,
        "signal_type_counts": dict(signal_type_counts),
        "reviewable": reviewable,
        "pass_rate": (
            round(verdict_counts["PASS"] / reviewable, 6)
            if reviewable > 0
            else None
        ),
        "data_quality": {
            "equity_basis": equity_basis,
            "cost_basis": (
                "full" if degraded_cost_symbols == 0 else "degraded"
            ),
            "degraded_cost_symbol_count": degraded_cost_symbols,
            "estimated_cost_symbol_count": estimated_cost_symbols,
            "market_value_scope": "all_positions",
            "symbol_count": len(detail_by_symbol),
            "warnings": (
                [
                    {
                        "code": "cost_basis_degraded_symbols",
                        "message": (
                            f"{degraded_cost_symbols} 个标的缺少完整 entry/slice/"
                            "allocation 成本证据，相关成本为估算口径。"
                        ),
                        "symbol_count": degraded_cost_symbols,
                    }
                ]
                if degraded_cost_symbols
                else []
            ),
        },
    }


def build_portfolio_series(
    *,
    xt_assets: list[dict[str, Any]],
    credit_snapshots: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    """Build the equity / estimated-equity curve with an explicit basis.

    Priority: broker total-asset snapshots, then credit snapshot rebuild,
    then a current single-point estimate.  Missing ranges are never
    interpolated.
    """

    broker_points = []
    for item in xt_assets or []:
        time_text = _iso_time(item.get("updated_at") or item.get("queried_at"))
        total_asset = _float(item.get("total_asset"))
        if time_text is None or total_asset is None:
            continue
        broker_points.append(
            {
                "time": time_text,
                "total_equity": _round(total_asset),
                "cash": _round(item.get("cash")),
                "market_value": _round(item.get("market_value")),
                "estimated_equity": None,
                "net_external_flow": None,
                "position_ratio": _round(item.get("position_pct")),
                "drawdown": None,
                "equity_basis": "broker_total_asset",
                "data_quality": {"source": "xt_assets"},
            }
        )

    credit_points = []
    if credit_snapshots:
        by_second: dict[str, dict[str, Any]] = {}
        for item in credit_snapshots:
            time_text = _iso_time(item.get("queried_at"))
            if time_text is None:
                continue
            # High-frequency credit snapshots are aggregated to minute
            # buckets; missing minutes are never interpolated.
            key = time_text[:16]
            total_asset = _float(item.get("total_asset"))
            market_value = _float(item.get("market_value"))
            total_debt = _float(item.get("total_debt"))
            available = _float(item.get("available_amount"))
            existing = by_second.get(key)
            if existing is None:
                by_second[key] = {
                    "time": key,
                    "total_equity": _round(total_asset),
                    "market_value": _round(market_value),
                    "total_debt": _round(total_debt),
                    "cash": _round(available),
                    "estimated_equity": _round(total_asset),
                    "net_external_flow": None,
                    "position_ratio": (
                        round(market_value / total_asset, 6)
                        if total_asset and market_value is not None
                        else None
                    ),
                    "drawdown": None,
                    "equity_basis": "credit_snapshot_reconstructed",
                    "data_quality": {"source": "pm_credit_asset_snapshots"},
                }
        credit_points = [
            by_second[key] for key in sorted(by_second) if by_second[key]
        ]

    if broker_points:
        series = broker_points
        equity_basis = "broker_total_asset"
        label = "账户总资产（券商历史快照）"
    elif credit_points:
        series = credit_points
        equity_basis = "credit_snapshot_reconstructed"
        label = "估算权益（信用资产快照重建）"
    else:
        series = []
        equity_basis = "estimated"
        label = "估算权益（证据不足）"

    return {
        "label": label,
        "equity_basis": equity_basis,
        "series": series,
        "generated_at": generated_at,
        "data_quality": {
            "equity_basis": equity_basis,
            "interpolated": False,
            "point_count": len(series),
            "warnings": (
                [
                    {
                        "code": "equity_evidence_limited",
                        "message": (
                            "缺少券商历史总资产快照，权益曲线为估算口径，"
                            "缺失区间不插值。"
                        ),
                    }
                ]
                if equity_basis != "broker_total_asset"
                else []
            ),
        },
    }


def build_portfolio_contributions(
    *,
    detail_by_symbol: dict[str, dict[str, Any]],
    cost_by_symbol: dict[str, dict[str, Any]],
    position_by_symbol: dict[str, dict[str, Any]],
    top_n: int = 10,
) -> dict[str, Any]:
    rows = []
    for symbol, detail in detail_by_symbol.items():
        symbol_meta = detail.get("symbol") or {}
        cost_replay = cost_by_symbol.get(symbol) or {}
        realized_pnl = _float(cost_replay.get("realized_pnl")) or 0.0
        position = position_by_symbol.get(symbol)
        _, floating_pnl, _ = _remaining_cost_and_pnl(
            symbol_meta=symbol_meta,
            position_snapshot=position,
            cost_replay=cost_replay,
        )
        review_counts = ((detail.get("summary") or {}).get("review_counts")) or {}
        rows.append(
            {
                "symbol": symbol,
                "name": str(symbol_meta.get("name") or "").strip() or symbol,
                "is_holding": _int((position or {}).get("volume")) > 0,
                "realized_pnl": _round(realized_pnl),
                "floating_pnl": _round(floating_pnl),
                "total_pnl": _round(
                    (realized_pnl or 0.0) + (floating_pnl or 0.0)
                ),
                "market_value": _round((position or {}).get("market_value")),
                "quantity": _int((position or {}).get("volume")),
                "verdict_counts": {
                    verdict: _int(review_counts.get(verdict))
                    for verdict in (
                        "PASS",
                        "FAIL",
                        "INSUFFICIENT_EVIDENCE",
                        "NOT_APPLICABLE",
                    )
                },
                "cost_basis_source": cost_replay.get("cost_basis_source"),
            }
        )
    rows.sort(
        key=lambda item: (
            item.get("total_pnl") is None,
            -(item.get("total_pnl") or 0.0),
            item.get("symbol") or "",
        )
    )
    return {
        "top": rows[: max(int(top_n), 1)],
        "total": len(rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


__all__ = [
    "build_portfolio_contributions",
    "build_portfolio_series",
    "build_portfolio_summary",
]
