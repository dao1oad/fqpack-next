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
from datetime import datetime, timedelta, timezone
from typing import Any

_BEIJING_TZ = timezone(timedelta(hours=8))
# 左上角选择器是「时间窗口」（看多长的跨度），曲线固定按 5 分钟粒度
# 展示：value = (窗口天数, 展示名)。窗口按最近一笔快照往前截取，
# 缺失区间不插值；5 分钟桶取该桶末笔快照。
_PERIOD_WINDOWS: dict[str, tuple[int, str]] = {
    "day": (1, "日"),
    "week": (7, "周"),
    "month": (30, "月"),
    "30d": (30, "30日"),
    "60d": (60, "60日"),
    "90d": (90, "90日"),
    "6m": (183, "半年"),
    "1y": (365, "一年"),
    "2y": (730, "两年"),
}
_PERIODS = tuple(_PERIOD_WINDOWS)


def period_window_days(period: str) -> int | None:
    """窗口天数；非法窗口返回 None。"""

    spec = _PERIOD_WINDOWS.get(str(period or "").strip().lower())
    return spec[0] if spec else None


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


def _beijing_datetime(value) -> datetime | None:
    """Parse an ISO-ish timestamp into an Asia/Shanghai datetime."""

    text = _iso_time(value)
    if text is None:
        return None
    normalized = str(text).strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    if " " in normalized and "T" not in normalized:
        normalized = normalized.replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_BEIJING_TZ)
    return parsed.astimezone(_BEIJING_TZ)


def _period_bucket_key(time_text: str, period: str) -> tuple[str, str] | None:
    """Return (bucket_key, period_label) for a Beijing 5-minute bucket.

    Buckets follow Beijing time.  ``period`` 参数保留兼容（所有窗口统一
    5 分钟粒度）。
    """

    parsed = _beijing_datetime(time_text)
    if parsed is None:
        return None
    minute = (parsed.minute // 5) * 5
    bucket = parsed.replace(minute=minute, second=0, microsecond=0)
    label = bucket.strftime("%Y-%m-%d %H:%M")
    return (label, label)


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
        signal_type = str((review.get("signal") or {}).get("type") or "unknown").strip()
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
        round(market_value - remaining_cost, 2) if market_value is not None else None
    )
    return remaining_cost, floating_pnl, used_estimate


def build_portfolio_summary(
    *,
    catalog_rows: list[dict[str, Any]],
    detail_by_symbol: dict[str, dict[str, Any]],
    cost_by_symbol: dict[str, dict[str, Any]],
    position_by_symbol: dict[str, dict[str, Any]],
    xt_assets: list[dict[str, Any]],
    credit_snapshots: list[dict[str, Any]] | None = None,
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
            if (
                str(request.get("source") or "").strip() == "order_ledger_rebuild"
                or str(request.get("source") or "").strip() == "external_inferred"
            ):
                # 账本重建/外部推断的请求不是真实策略成交，不计入月度成交额，
                # 避免与真实成交重复计数。
                continue
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
        cost_basis_quality = (cost_replay.get("data_quality") or {}).get("cost_basis")
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
    current_net_value = None
    cash = None
    equity_basis = "estimated"
    latest_broker = None
    if xt_assets:
        latest_broker = sorted(
            xt_assets,
            key=lambda item: str(
                item.get("updated_at") or item.get("queried_at") or ""
            ),
        )[-1]
    # 忽略零值/缺时间的券商快照（例如初始化占位记录），否则会把总资产误算为 0。
    if (
        latest_broker is not None
        and (_float(latest_broker.get("total_asset")) or 0.0) > 0
    ):
        latest = latest_broker
        current_asset = _float(latest.get("total_asset"))
        current_net_value = current_asset
        cash = _float(latest.get("cash"))
        equity_basis = "broker_total_asset"
    elif credit_snapshots:
        latest_credit = sorted(
            credit_snapshots,
            key=lambda item: str(item.get("queried_at") or ""),
        )[-1]
        total_asset = _float(latest_credit.get("total_asset"))
        total_debt = _float(latest_credit.get("total_debt"))
        current_asset = total_asset
        current_net_value = (
            _round(total_asset - total_debt)
            if total_asset is not None and total_debt is not None
            else _round(total_asset)
        )
        cash = _float(latest_credit.get("available_amount"))
        equity_basis = "credit_snapshot_reconstructed"

    position_ratio = (
        round(market_value / current_asset, 6)
        if current_asset and market_value > 0
        else None
    )
    return {
        "generated_at": generated_at,
        "kpis": {
            "total_asset": _round(current_asset),
            "net_value": _round(current_net_value),
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
            round(verdict_counts["PASS"] / reviewable, 6) if reviewable > 0 else None
        ),
        "data_quality": {
            "equity_basis": equity_basis,
            "cost_basis": ("full" if degraded_cost_symbols == 0 else "degraded"),
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
    trade_events: list[dict[str, Any]] | None = None,
    period: str = "day",
    generated_at: str,
) -> dict[str, Any]:
    """Build the account net-value curve with an explicit basis.

    Priority: broker total-asset snapshots, then credit snapshot rebuild,
    then a current single-point estimate.  Missing ranges are never
    interpolated.  Net value follows the QMT formula:

    - 单位净值 = (基金资产总值 - 基金负债) / 基金总份额
    - 账户层面：净资产 = 总资产 - 总负债

    ``pm_credit_asset_snapshots`` carries both ``total_asset`` and
    ``total_debt``, so each point reports ``net_value = total_asset -
    total_debt``.  ``period`` 是时间窗口（``day``=1天 / ``week``=7天 /
    ``month``=30天 / ``30d``/``60d``/``90d``/``6m``/``1y``/``2y``），
    所有窗口统一按 5 分钟粒度展示（北京时区，每桶保留末笔快照）。
    交易发生在哪个 5 分钟桶就挂到哪个点，供 UI 渲染交易点与悬浮明细。
    """

    normalized_period = str(period or "day").strip().lower()
    if normalized_period not in _PERIODS:
        raise ValueError(
            "period must be one of day, week, month, 30d, 60d, 90d, 6m, 1y, 2y"
        )
    trade_events = list(trade_events or [])

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
                "estimated_equity": None,
                "net_value": _round(total_asset),
            }
        )

    credit_points = []
    if credit_snapshots:
        by_second: dict[str, dict[str, Any]] = {}
        for item in credit_snapshots:
            time_text = _iso_time(item.get("queried_at"))
            if time_text is None:
                continue
            # 高频快照先按北京时区聚合到分钟（queried_at 为 UTC，必须
            # 显式转北京时间再取分钟键，否则 5 分钟桶会整体偏移 8 小时）；
            # 缺失分钟不插值。
            parsed = _beijing_datetime(time_text)
            if parsed is None:
                continue
            key = parsed.strftime("%Y-%m-%d %H:%M")
            total_asset = _float(item.get("total_asset"))
            total_debt = _float(item.get("total_debt"))
            existing = by_second.get(key)
            if existing is None:
                net_value = (
                    _round(total_asset - total_debt)
                    if total_asset is not None and total_debt is not None
                    else _round(total_asset)
                )
                by_second[key] = {
                    "time": parsed.isoformat(),
                    "total_equity": _round(total_asset),
                    "estimated_equity": net_value,
                    "net_value": net_value,
                }
        credit_points = [by_second[key] for key in sorted(by_second) if by_second[key]]

    if broker_points:
        raw_series = broker_points
        equity_basis = "broker_total_asset"
        label = "账户总资产（券商历史快照）"
    elif credit_points:
        raw_series = credit_points
        equity_basis = "credit_snapshot_reconstructed"
        label = "账户净资产（信用资产快照重建）"
    else:
        raw_series = []
        equity_basis = "estimated"
        label = "账户净资产（证据不足）"

    window_start: datetime | None = None
    window_covered = True
    window_days = period_window_days(normalized_period)
    if window_days is not None:
        anchor = None
        for point in raw_series:
            parsed = _beijing_datetime(point.get("time"))
            if parsed is not None and (anchor is None or parsed > anchor):
                anchor = parsed
        if anchor is None:
            anchor = _beijing_datetime(generated_at) or datetime.now(_BEIJING_TZ)
        window_start = anchor - timedelta(days=window_days)
        raw_series = [
            point
            for point in raw_series
            if (
                (parsed := _beijing_datetime(point.get("time"))) is not None
                and parsed >= window_start
            )
        ]
        first_point_time = min(
            (
                parsed
                for point in raw_series
                if (parsed := _beijing_datetime(point.get("time"))) is not None
            ),
            default=None,
        )
        window_covered = bool(
            first_point_time is not None
            and first_point_time <= window_start + timedelta(days=1)
        )

    series = _bucket_series(
        raw_series,
        trade_events=trade_events,
        period="day",
    )
    period_label = _PERIOD_WINDOWS.get(normalized_period, (1, "日"))[1]

    warnings = []
    if equity_basis != "broker_total_asset":
        warnings.append(
            {
                "code": "equity_evidence_limited",
                "message": (
                    "缺少券商历史总资产快照，权益曲线为信用资产快照重建口径，"
                    "缺失区间不插值。"
                ),
            }
        )
    if window_days is not None and not window_covered:
        warnings.append(
            {
                "code": "equity_window_partial",
                "message": (
                    f"请求窗口 {window_days} 天，但账户快照历史晚于窗口起点，"
                    "曲线仅覆盖可用区间，早段不做插值。"
                ),
            }
        )

    return {
        "label": label,
        "equity_basis": equity_basis,
        "period": normalized_period,
        "period_label": period_label,
        "series": series,
        "generated_at": generated_at,
        "data_quality": {
            "equity_basis": equity_basis,
            "interpolated": False,
            "point_count": len(series),
            "window": {
                "period": normalized_period,
                "granularity": "5min",
                "window_days": window_days,
                "window_start": (
                    window_start.isoformat() if window_start is not None else None
                ),
                "covered": window_covered,
                "available_from": (series[0].get("time") if series else None),
            },
            "net_value_formula": "net_value = total_asset - total_debt",
            "qmt_reference": (
                "单位净值=(基金资产总值-基金负债)/基金总份额；账户净资产=总资产-总负债"
            ),
            "trade_point_count": sum(
                len(point.get("trades") or []) for point in series
            ),
            "warnings": warnings,
        },
    }


def _bucket_series(
    points: list[dict[str, Any]],
    *,
    trade_events: list[dict[str, Any]],
    period: str,
) -> list[dict[str, Any]]:
    """Aggregate minute-level points to Beijing calendar buckets.

    Each bucket keeps the last observed snapshot (no interpolation).  Trade
    events are attached to the bucket whose day/week/month matches their
    timestamp.
    """

    buckets: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for point in points or []:
        bucket = _period_bucket_key(str(point.get("time") or ""), period)
        if bucket is None:
            continue
        key, label = bucket
        previous_trades = list((buckets.get(key) or {}).get("trades") or [])
        buckets[key] = dict(point)
        buckets[key]["period_key"] = key
        buckets[key]["period_label"] = label
        buckets[key]["trades"] = previous_trades
        buckets[key]["trade_count"] = len(previous_trades)
        if key not in order:
            order.append(key)

    for trade in trade_events:
        bucket = _period_bucket_key(str(trade.get("time") or ""), period)
        if bucket is None:
            continue
        key = bucket[0]
        target = buckets.get(key)
        if target is None:
            continue
        trades = list(target.get("trades") or [])
        trades.append(dict(trade))
        target["trades"] = trades
        target["trade_count"] = len(trades)

    result = []
    for key in order:
        point = buckets[key]
        trades = sorted(
            list(point.get("trades") or []),
            key=lambda item: str(item.get("time") or ""),
        )
        point["trades"] = trades
        point["trade_count"] = len(trades)
        result.append(point)
    return result


def build_portfolio_benchmark(
    *,
    index_bars: list[dict[str, Any]],
    series: list[dict[str, Any]],
    period: str,
    code: str = "510210",
    name: str = "上证综指ETF",
) -> dict[str, Any]:
    """Align benchmark daily bars onto the equity series buckets.

    Each equity bucket (5-minute) takes the benchmark daily close of the same
    trading day; buckets on a day without a fresh bar carry the previous
    close forward (benchmark "as of" value).  ``covered_count`` only counts
    buckets with an observed bar, ``carried_count`` counts carry-forward
    buckets.
    ``normalized`` rebases the aligned series to the first available point so
    the UI can render period returns and the beat/miss spread against the
    account curve.
    """

    daily_closes: dict[str, float] = {}
    for bar in index_bars or []:
        date = str((bar or {}).get("date") or "").strip()
        close = _float((bar or {}).get("close"))
        if not date or close is None:
            continue
        daily_closes[date[:10]] = close

    aligned = []
    last_close: float | None = None
    observed_count = 0
    carried_count = 0
    for point in series or []:
        key = str(point.get("period_key") or "").strip()
        close = daily_closes.get(key[:10])
        if close is None:
            close = last_close
            if close is not None:
                carried_count += 1
        else:
            observed_count += 1
            last_close = close
        aligned.append(
            {
                "period_key": key,
                "period_label": point.get("period_label"),
                "close": _round(close),
            }
        )
    first_close = next(
        (item.get("close") for item in aligned if item.get("close") is not None),
        None,
    )
    for item in aligned:
        item["normalized"] = (
            round(item["close"] / first_close, 6)
            if first_close and item.get("close") is not None
            else None
        )
    covered = observed_count
    warnings = []
    if aligned and covered < len(aligned):
        warnings.append(
            {
                "code": "benchmark_partial",
                "message": (
                    f"基准日线仅覆盖 {covered}/{len(aligned)} 个账户分桶，"
                    "缺失分桶沿用上一收盘价（carry-forward）。"
                ),
            }
        )
    return {
        "code": code,
        "name": name,
        "basis": "quantaxis_index_day",
        "series": aligned,
        "point_count": len(aligned),
        "covered_count": covered,
        "carried_count": carried_count,
        "warnings": warnings,
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
                "total_pnl": _round((realized_pnl or 0.0) + (floating_pnl or 0.0)),
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
