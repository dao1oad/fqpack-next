# -*- coding: utf-8 -*-
"""Search causal filters for CLX model x trigger strategies.

Development uses 2005-2023 only.  Candidate rules are deliberately simple,
causal, and capped at three clauses.  Search scoring rewards positive temporal
folds and penalizes instability, small samples, and rule complexity.  The final
ranking is produced by a CNY 5m / 40-slot account simulation with fees and
open-limit execution checks.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pymongo

CANDIDATE_PATH = Path("/tmp/clx_trigger_filter_dev_candidates.parquet")
OUTPUT_PATH = Path("/tmp/clx_trigger_filter_search.json")
SNAPSHOT_ROOT = (
    "/opt/clx-backtest/snapshots/"
    "cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4/"
    "bars"
)
INITIAL_CAPITAL = 5_000_000.0
MAX_POSITIONS = 40
FEE_PER_SIDE = 0.002
LIMIT_MOVE = 0.095
FOLDS = (
    ("F1_2005_2009", 2005, 2009),
    ("F2_2010_2014", 2010, 2014),
    ("F3_2015_2019", 2015, 2019),
    ("F4_2020_2023", 2020, 2023),
)
EXIT_MODES = ("hold5", "hold10", "hold15", "hold20", "hold30", "signal")
MIN_GROUP_ROWS = 100
BEAM_WIDTH = 7
MAX_RULE_DEPTH = 3


@dataclass(frozen=True)
class Rule:
    name: str
    family: str
    predicate: Callable[[pd.DataFrame], pd.Series]


def finite_between(
    column: str, low: float, high: float
) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda frame: frame[column].between(low, high, inclusive="both")


def finite_le(column: str, value: float) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda frame: frame[column].notna() & (frame[column] <= value)


def finite_ge(column: str, value: float) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda frame: frame[column].notna() & (frame[column] >= value)


RULES = (
    Rule("occurrence_eq_1", "occurrence", lambda f: f["occurrence"] == 1),
    Rule("occurrence_le_2", "occurrence", lambda f: f["occurrence"] <= 2),
    Rule("occurrence_le_3", "occurrence", lambda f: f["occurrence"] <= 3),
    Rule("price_3_10", "price", finite_between("raw_entry_open", 3.0, 10.0)),
    Rule("price_5_20", "price", finite_between("raw_entry_open", 5.0, 20.0)),
    Rule("price_5_30", "price", finite_between("raw_entry_open", 5.0, 30.0)),
    Rule("price_8_30", "price", finite_between("raw_entry_open", 8.0, 30.0)),
    Rule("price_10_50", "price", finite_between("raw_entry_open", 10.0, 50.0)),
    Rule("price_le_20", "price", finite_le("raw_entry_open", 20.0)),
    Rule("price_ge_5", "price", finite_ge("raw_entry_open", 5.0)),
    Rule(
        "concurrent_ge_2",
        "concurrent",
        lambda f: f["concurrent_trigger_count"] >= 2,
    ),
    Rule(
        "concurrent_ge_3",
        "concurrent",
        lambda f: f["concurrent_trigger_count"] >= 3,
    ),
    Rule(
        "same_code_models_ge_2",
        "consensus",
        lambda f: f["same_code_model_count"] >= 2,
    ),
    Rule(
        "same_code_models_ge_4",
        "consensus",
        lambda f: f["same_code_model_count"] >= 4,
    ),
    Rule("stock20_neg", "stock20", finite_le("stock_return_20", 0.0)),
    Rule("stock20_pos", "stock20", finite_ge("stock_return_20", 0.0)),
    Rule(
        "stock20_pullback",
        "stock20",
        finite_between("stock_return_20", -0.20, 0.0),
    ),
    Rule(
        "stock20_flat",
        "stock20",
        finite_between("stock_return_20", -0.10, 0.10),
    ),
    Rule("stock60_neg", "stock60", finite_le("stock_return_60", 0.0)),
    Rule("stock60_pos", "stock60", finite_ge("stock_return_60", 0.0)),
    Rule("market20_neg", "market20", finite_le("market_return_20", 0.0)),
    Rule("market20_pos", "market20", finite_ge("market_return_20", 0.0)),
    Rule(
        "market20_calm",
        "market20",
        finite_between("market_return_20", -0.10, 0.08),
    ),
    Rule("market60_pos", "market60", finite_ge("market_return_60", 0.0)),
    Rule("market60_neg", "market60", finite_le("market_return_60", 0.0)),
    Rule("market_above_ma60", "market_trend", finite_ge("market_above_ma60", 0.0)),
    Rule("market_below_ma60", "market_trend", finite_le("market_above_ma60", 0.0)),
    Rule("vol20_le_4pct", "volatility", finite_le("stock_volatility_20", 0.04)),
    Rule("vol20_le_6pct", "volatility", finite_le("stock_volatility_20", 0.06)),
    Rule("vol20_ge_3pct", "volatility", finite_ge("stock_volatility_20", 0.03)),
    Rule("atr20_2_6pct", "atr", finite_between("stock_atr_20", 0.02, 0.06)),
    Rule("atr20_le_5pct", "atr", finite_le("stock_atr_20", 0.05)),
    Rule("drawdown20_le_10pct", "drawdown", finite_ge("stock_drawdown_20", -0.10)),
    Rule("drawdown20_ge_10pct", "drawdown", finite_le("stock_drawdown_20", -0.10)),
    Rule("above_ma20", "stock_trend", finite_ge("stock_above_ma20", 0.0)),
    Rule("below_ma20", "stock_trend", finite_le("stock_above_ma20", 0.0)),
    Rule("above_ma60", "stock_long_trend", finite_ge("stock_above_ma60", 0.0)),
    Rule("below_ma60", "stock_long_trend", finite_le("stock_above_ma60", 0.0)),
    Rule("amount20_ge_10m", "liquidity", finite_ge("amount_median_20", 10_000_000.0)),
    Rule("amount20_ge_30m", "liquidity", finite_ge("amount_median_20", 30_000_000.0)),
    Rule("amount20_ge_100m", "liquidity", finite_ge("amount_median_20", 100_000_000.0)),
    Rule(
        "stop_distance_3_12pct",
        "stop_distance",
        finite_between("structural_stop_distance", 0.03, 0.12),
    ),
    Rule(
        "stop_distance_4_15pct",
        "stop_distance",
        finite_between("structural_stop_distance", 0.04, 0.15),
    ),
    Rule(
        "stop_distance_le_20pct",
        "stop_distance",
        finite_between("structural_stop_distance", 0.0, 0.20),
    ),
    Rule(
        "buy_crowding_z_le_0", "buy_crowding", finite_le("market_buy_count_z252", 0.0)
    ),
    Rule(
        "buy_crowding_z_le_1", "buy_crowding", finite_le("market_buy_count_z252", 1.0)
    ),
    Rule(
        "sell_crowding_z_le_0",
        "sell_crowding",
        finite_le("market_sell_count_z252", 0.0),
    ),
    Rule(
        "sell_crowding_z_le_1",
        "sell_crowding",
        finite_le("market_sell_count_z252", 1.0),
    ),
    Rule(
        "entry_gap_le_3pct",
        "entry_gap",
        lambda f: f["entry_gap"].between(-LIMIT_MOVE, 0.03, inclusive="both"),
    ),
    Rule(
        "entry_gap_nonpositive",
        "entry_gap",
        lambda f: f["entry_gap"].between(-LIMIT_MOVE, 0.0, inclusive="both"),
    ),
    Rule(
        "concurrent_engulfing",
        "concurrent_semantic",
        lambda f: (f["concurrent_trigger_mask"].astype("int64") & (1 << 2)) != 0,
    ),
    Rule(
        "concurrent_strong_fractal",
        "concurrent_semantic",
        lambda f: (f["concurrent_trigger_mask"].astype("int64") & (1 << 3)) != 0,
    ),
    Rule(
        "concurrent_macd",
        "concurrent_semantic",
        lambda f: (f["concurrent_trigger_mask"].astype("int64") & (1 << 6)) != 0,
    ),
)
RULE_BY_NAME = {rule.name: rule for rule in RULES}


def net_return(gross: np.ndarray) -> np.ndarray:
    return (1 + gross) * (1 - FEE_PER_SIDE) / (1 + FEE_PER_SIDE) - 1


def exit_return_column(exit_mode: str) -> str:
    return (
        f"{exit_mode}_gross_return" if exit_mode != "signal" else "signal_gross_return"
    )


def fold_metrics(
    frame: pd.DataFrame, mask: np.ndarray, exit_mode: str
) -> dict[str, Any] | None:
    values = frame[exit_return_column(exit_mode)].to_numpy(dtype=float)
    dates = pd.to_datetime(frame["entry_date"])
    years = dates.dt.year.to_numpy()
    valid = mask & np.isfinite(values)
    if valid.sum() < MIN_GROUP_ROWS:
        return None
    clipped = np.clip(net_return(values), -0.30, 0.50)
    fold_rows: list[dict[str, Any]] = []
    fold_means: list[float] = []
    fold_counts: list[int] = []
    for name, start, end in FOLDS:
        selected = valid & (years >= start) & (years <= end)
        count = int(selected.sum())
        if count < 8:
            return None
        returns = clipped[selected]
        mean = float(returns.mean())
        fold_counts.append(count)
        fold_means.append(mean)
        fold_rows.append(
            {
                "fold": name,
                "n": count,
                "mean_net": round(mean, 6),
                "win_rate": round(float((net_return(values[selected]) > 0).mean()), 6),
            }
        )
    selected_returns = net_return(values[valid])
    selected_clipped = clipped[valid]
    complexity = 0
    mean_fold = float(np.mean(fold_means))
    median_fold = float(np.median(fold_means))
    worst_fold = float(np.min(fold_means))
    instability = float(np.std(fold_means))
    sample_factor = min(1.0, math.sqrt(valid.sum() / 500.0))
    score = (
        0.40 * mean_fold + 0.25 * median_fold + 0.25 * worst_fold - 0.10 * instability
    ) * sample_factor
    return {
        "score": score,
        "n": int(valid.sum()),
        "mean_net": float(selected_returns.mean()),
        "median_net": float(np.median(selected_returns)),
        "winsor_mean_net": float(selected_clipped.mean()),
        "win_rate": float((selected_returns > 0).mean()),
        "worst_fold_mean": worst_fold,
        "positive_folds": int(sum(item > 0 for item in fold_means)),
        "folds": fold_rows,
        "complexity": complexity,
    }


def with_complexity(metrics: dict[str, Any], complexity: int) -> dict[str, Any]:
    result = dict(metrics)
    result["complexity"] = complexity
    result["score"] = float(metrics["score"]) - complexity * 0.00015
    return result


def search_strategy(frame: pd.DataFrame) -> dict[str, Any]:
    frame = frame.reset_index(drop=True)
    rule_masks = {
        rule.name: rule.predicate(frame).fillna(False).to_numpy(dtype=bool)
        for rule in RULES
    }
    base_mask = np.ones(len(frame), dtype=bool)
    cache: dict[tuple[str, ...], tuple[np.ndarray, dict[str, Any]]] = {}

    def evaluate(
        rule_names: tuple[str, ...],
    ) -> tuple[np.ndarray, dict[str, Any]] | None:
        if rule_names in cache:
            return cache[rule_names]
        mask = base_mask.copy()
        for name in rule_names:
            mask &= rule_masks[name]
        metrics = fold_metrics(frame, mask, "hold10")
        if metrics is None:
            return None
        metrics = with_complexity(metrics, len(rule_names))
        cache[rule_names] = (mask, metrics)
        return mask, metrics

    base_eval = evaluate(())
    if base_eval is None:
        return {
            "status": "INSUFFICIENT_SAMPLE",
            "rows": len(frame),
            "rules": [],
            "exit_mode": "hold10",
        }

    all_candidates: dict[tuple[str, ...], dict[str, Any]] = {
        (): base_eval[1],
    }
    beam: list[tuple[str, ...]] = [()]
    for _depth in range(1, MAX_RULE_DEPTH + 1):
        expanded: dict[tuple[str, ...], dict[str, Any]] = {}
        for existing in beam:
            used_families = {RULE_BY_NAME[name].family for name in existing}
            for rule in RULES:
                if rule.family in used_families or rule.name in existing:
                    continue
                names = tuple(sorted((*existing, rule.name)))
                evaluated = evaluate(names)
                if evaluated is None:
                    continue
                expanded[names] = evaluated[1]
        if not expanded:
            break
        all_candidates.update(expanded)
        beam = [
            names
            for names, _metrics in sorted(
                expanded.items(),
                key=lambda item: item[1]["score"],
                reverse=True,
            )[:BEAM_WIDTH]
        ]

    top_rule_sets = [
        names
        for names, _metrics in sorted(
            all_candidates.items(),
            key=lambda item: item[1]["score"],
            reverse=True,
        )[:8]
    ]
    exit_candidates: list[dict[str, Any]] = []
    for names in top_rule_sets:
        mask = cache[names][0]
        for exit_mode in EXIT_MODES:
            metrics = fold_metrics(frame, mask, exit_mode)
            if metrics is None:
                continue
            metrics = with_complexity(metrics, len(names))
            exit_candidates.append(
                {
                    "rules": list(names),
                    "exit_mode": exit_mode,
                    **metrics,
                }
            )
    exit_candidates.sort(key=lambda item: item["score"], reverse=True)
    winner = exit_candidates[0]
    base_metrics = with_complexity(base_eval[1], 0)
    if winner["score"] < base_metrics["score"] + 0.0005:
        winner = {
            "rules": [],
            "exit_mode": "hold10",
            **base_metrics,
        }
    return {
        "status": "OK",
        "rows": len(frame),
        "baseline_trade": {
            "rules": [],
            "exit_mode": "hold10",
            **base_metrics,
        },
        "winner_trade": winner,
        "top_trade_candidates": exit_candidates[:10],
    }


def load_calendar() -> np.ndarray:
    client = pymongo.MongoClient(
        "mongodb://fq_mongodb:27017",
        serverSelectionTimeoutMS=5_000,
    )
    records = list(
        client["quantaxis"]["index_day"].find(
            {
                "code": "000001",
                "date": {"$gte": "2005-01-01", "$lte": "2023-12-31"},
            },
            {"_id": 0, "date": 1},
        )
    )
    return np.sort(
        pd.to_datetime([item["date"] for item in records]).values.astype(
            "datetime64[ns]"
        )
    )


def load_mark_bars(codes: set[str]) -> dict[str, tuple[np.ndarray, ...]]:
    dataset = ds.dataset(SNAPSHOT_ROOT, format="parquet")
    table = dataset.to_table(
        columns=["code", "trade_date", "qfq_open", "qfq_close"],
        filter=(ds.field("trade_year") >= 2004) & (ds.field("trade_year") <= 2024),
    )
    frame = table.to_pandas()
    frame = frame[frame["code"].isin(codes)].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"].astype(str))
    frame = frame.sort_values(["code", "trade_date"])
    return {
        code: (
            rows["trade_date"].values.astype("datetime64[ns]"),
            rows["qfq_open"].to_numpy(dtype=float),
            rows["qfq_close"].to_numpy(dtype=float),
        )
        for code, rows in frame.groupby("code", sort=False)
    }


def rule_mask(frame: pd.DataFrame, names: list[str]) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for name in names:
        mask &= RULE_BY_NAME[name].predicate(frame).fillna(False)
    return mask


def mark_price(
    bars: tuple[np.ndarray, ...],
    date: np.datetime64,
    field: int,
) -> float:
    offset = int(np.searchsorted(bars[0], date, side="right") - 1)
    if offset < 0:
        return float("nan")
    return float(bars[field][offset])


def planned_exit_date(row: Any, exit_mode: str) -> np.datetime64:
    column = f"{exit_mode}_exit_date" if exit_mode != "signal" else "signal_exit_date"
    value = getattr(row, column)
    return np.datetime64(value) if not pd.isna(value) else np.datetime64("NaT")


def simulate_account(
    frame: pd.DataFrame,
    mark_bars: dict[str, tuple[np.ndarray, ...]],
    calendar: np.ndarray,
    *,
    exit_mode: str,
    start_year: int,
    end_year: int,
    ranking_policy: str = "canonical",
) -> dict[str, Any]:
    period_calendar = calendar[
        (pd.DatetimeIndex(calendar).year >= start_year)
        & (pd.DatetimeIndex(calendar).year <= end_year)
    ]
    if len(period_calendar) == 0:
        raise RuntimeError(f"missing calendar for {start_year}-{end_year}")
    frame = frame[
        (pd.to_datetime(frame["entry_date"]).dt.year >= start_year)
        & (pd.to_datetime(frame["entry_date"]).dt.year <= end_year)
    ].copy()
    if ranking_policy == "quality":
        frame = frame.sort_values(
            [
                "entry_date",
                "concurrent_trigger_count",
                "same_code_model_count",
                "market_sell_count_z252",
                "amount_median_20",
                "code",
            ],
            ascending=[True, False, False, True, False, True],
        )
    else:
        frame = frame.sort_values(["entry_date", "reveal_date", "code"])
    entries = {
        date.to_datetime64(): list(rows.itertuples(index=False))
        for date, rows in frame.groupby("entry_date", sort=False)
    }
    cash = INITIAL_CAPITAL
    positions: dict[str, dict[str, Any]] = {}
    equity_dates: list[np.datetime64] = []
    equity_values: list[float] = []
    trade_returns: list[float] = []
    total_fees = 0.0
    skipped_slots = 0
    skipped_duplicate = 0
    skipped_limit_up = 0
    blocked_exits = 0
    signal_count = len(frame)

    def position_value(date: np.datetime64, field: int) -> float:
        value = 0.0
        for code, position in positions.items():
            price = mark_price(mark_bars[code], date, field)
            if np.isfinite(price):
                value += position["units"] * price
        return value

    for date in period_calendar:
        for code in list(positions):
            position = positions[code]
            planned = position["exit_date"]
            if np.isnat(planned) or date < planned:
                continue
            bars = mark_bars[code]
            offset = int(np.searchsorted(bars[0], date))
            if offset >= len(bars[0]) or bars[0][offset] != date:
                continue
            open_price = float(bars[1][offset])
            prior_close = float(bars[2][offset - 1]) if offset > 0 else open_price
            if open_price / prior_close - 1 < -LIMIT_MOVE:
                blocked_exits += 1
                continue
            gross = position["units"] * open_price
            fee = gross * FEE_PER_SIDE
            proceeds = gross - fee
            cash += proceeds
            total_fees += fee
            trade_returns.append(proceeds / position["entry_cost"] - 1)
            positions.pop(code)

        for row in entries.get(date, []):
            code = str(row.code)
            if code in positions:
                skipped_duplicate += 1
                continue
            if len(positions) >= MAX_POSITIONS:
                skipped_slots += 1
                continue
            open_price = float(row.qfq_entry_open)
            if not np.isfinite(open_price) or open_price <= 0:
                continue
            if float(row.entry_gap) > LIMIT_MOVE:
                skipped_limit_up += 1
                continue
            equity_at_open = cash + position_value(date, field=1)
            target = min(equity_at_open / MAX_POSITIONS, cash / (1 + FEE_PER_SIDE))
            if target <= 0:
                skipped_slots += 1
                continue
            gross = target
            fee = gross * FEE_PER_SIDE
            cost = gross + fee
            units = gross / open_price
            cash -= cost
            total_fees += fee
            positions[code] = {
                "units": units,
                "entry_cost": cost,
                "exit_date": planned_exit_date(row, exit_mode),
            }

        equity = cash + position_value(date, field=2)
        equity_dates.append(date)
        equity_values.append(equity)
        if cash < -0.01 or len(positions) > MAX_POSITIONS or equity <= 0:
            raise RuntimeError(
                f"account invariant failed {date}: cash={cash}, "
                f"positions={len(positions)}, equity={equity}"
            )

    final_date = period_calendar[-1]
    final_equity = cash + position_value(final_date, field=2)
    liquidation_fee = position_value(final_date, field=2) * FEE_PER_SIDE
    final_equity -= liquidation_fee
    total_fees += liquidation_fee
    equity_values[-1] = final_equity
    equity = pd.Series(
        equity_values,
        index=pd.to_datetime(equity_dates),
        dtype=float,
    )
    drawdown = equity / equity.cummax() - 1
    years = max(
        (pd.Timestamp(final_date) - pd.Timestamp(period_calendar[0])).days / 365.25,
        1 / 365.25,
    )
    total_return = final_equity / INITIAL_CAPITAL - 1
    cagr = (final_equity / INITIAL_CAPITAL) ** (1 / years) - 1
    return {
        "period": [start_year, end_year],
        "initial_capital": INITIAL_CAPITAL,
        "final_equity": round(float(final_equity), 2),
        "total_return": round(float(total_return), 6),
        "cagr": round(float(cagr), 6),
        "max_drawdown": round(float(drawdown.min()), 6),
        "signals": signal_count,
        "trades": len(trade_returns),
        "open_positions_at_end": len(positions),
        "win_rate": (
            round(float(np.mean(np.asarray(trade_returns) > 0)), 6)
            if trade_returns
            else None
        ),
        "mean_trade_return": (
            round(float(np.mean(trade_returns)), 6) if trade_returns else None
        ),
        "total_fees": round(float(total_fees), 2),
        "skipped_slots": skipped_slots,
        "skipped_duplicate": skipped_duplicate,
        "skipped_limit_up": skipped_limit_up,
        "blocked_exits": blocked_exits,
    }


def development_objective(segments: dict[str, dict[str, Any]]) -> float:
    values = list(segments.values())
    cagrs = np.asarray([item["cagr"] for item in values], dtype=float)
    drawdowns = np.asarray([abs(item["max_drawdown"]) for item in values], dtype=float)
    return float(
        0.35 * cagrs.mean()
        + 0.35 * np.median(cagrs)
        + 0.30 * cagrs.min()
        - 0.15 * drawdowns.mean()
    )


def account_segments(
    frame: pd.DataFrame,
    bars: dict[str, tuple[np.ndarray, ...]],
    calendar: np.ndarray,
    exit_mode: str,
    ranking_policy: str = "canonical",
) -> dict[str, Any]:
    segments = {
        name: simulate_account(
            frame,
            bars,
            calendar,
            exit_mode=exit_mode,
            start_year=start,
            end_year=end,
            ranking_policy=ranking_policy,
        )
        for name, start, end in FOLDS
    }
    full = simulate_account(
        frame,
        bars,
        calendar,
        exit_mode=exit_mode,
        start_year=2005,
        end_year=2023,
        ranking_policy=ranking_policy,
    )
    return {
        "segments": segments,
        "full": full,
        "objective": round(development_objective(segments), 8),
    }


def main() -> None:
    print("loading candidate table", flush=True)
    candidates = pd.read_parquet(CANDIDATE_PATH)
    candidates["entry_date"] = pd.to_datetime(candidates["entry_date"])
    candidates["reveal_date"] = pd.to_datetime(candidates["reveal_date"])
    strategies = sorted(candidates["strategy_id"].unique())
    search_results: dict[str, dict[str, Any]] = {}
    for index, strategy_id in enumerate(strategies, start=1):
        frame = candidates[candidates["strategy_id"] == strategy_id]
        result = search_strategy(frame)
        search_results[strategy_id] = result
        print(
            f"search {index}/{len(strategies)} {strategy_id} "
            f"status={result['status']}",
            flush=True,
        )

    print("loading mark bars", flush=True)
    bars = load_mark_bars(set(candidates["code"].astype(str)))
    calendar = load_calendar()
    leaderboard: list[dict[str, Any]] = []
    for index, strategy_id in enumerate(strategies, start=1):
        result = search_results[strategy_id]
        strategy_frame = candidates[candidates["strategy_id"] == strategy_id]
        baseline_account = account_segments(
            strategy_frame,
            bars,
            calendar,
            "hold10",
        )
        if result["status"] == "OK":
            winner = result["winner_trade"]
            filtered = strategy_frame[rule_mask(strategy_frame, winner["rules"])]
            filtered_account = account_segments(
                filtered,
                bars,
                calendar,
                winner["exit_mode"],
            )
        else:
            winner = {
                "rules": [],
                "exit_mode": "hold10",
            }
            filtered = strategy_frame
            filtered_account = baseline_account
        improvement = filtered_account["objective"] - baseline_account["objective"]
        leaderboard.append(
            {
                "strategy_id": strategy_id,
                "model_code": strategy_frame["model_code"].iloc[0],
                "primary_trigger_semantic": strategy_frame[
                    "primary_trigger_semantic"
                ].iloc[0],
                "raw_signals": len(strategy_frame),
                "filtered_signals": len(filtered),
                "rules": winner["rules"],
                "exit_mode": winner["exit_mode"],
                "trade_search": result,
                "baseline_account": baseline_account,
                "filtered_account": filtered_account,
                "objective_improvement": round(float(improvement), 8),
            }
        )
        print(
            f"account {index}/{len(strategies)} {strategy_id} "
            f"base={baseline_account['objective']:.4f} "
            f"filtered={filtered_account['objective']:.4f}",
            flush=True,
        )
    leaderboard.sort(
        key=lambda item: item["filtered_account"]["objective"],
        reverse=True,
    )
    payload = {
        "run_id": "01KBYC7REC0V3RY99634853AAB",
        "status": "DEVELOPMENT_SEARCH",
        "development_period": [2005, 2023],
        "holdout_rows_read": 0,
        "account_contract": {
            "initial_capital": INITIAL_CAPITAL,
            "max_positions": MAX_POSITIONS,
            "fee_per_side": FEE_PER_SIDE,
            "limit_move": LIMIT_MOVE,
            "price_domain": "QFQ_TOTAL_RETURN_APPROXIMATION",
            "entry": "NEXT_STOCK_TRADING_DAY_OPEN",
            "ranking_policy": "canonical reveal_date/code",
        },
        "search_contract": {
            "temporal_folds": FOLDS,
            "rule_count": len(RULES),
            "beam_width": BEAM_WIDTH,
            "max_rule_depth": MAX_RULE_DEPTH,
            "exit_modes": EXIT_MODES,
            "minimum_group_rows": MIN_GROUP_ROWS,
        },
        "strategy_count": len(leaderboard),
        "leaderboard": leaderboard,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT_PATH),
                "strategy_count": len(leaderboard),
                "top10": [
                    {
                        "strategy_id": item["strategy_id"],
                        "rules": item["rules"],
                        "exit_mode": item["exit_mode"],
                        "objective": item["filtered_account"]["objective"],
                        "full_return": item["filtered_account"]["full"]["total_return"],
                    }
                    for item in leaderboard[:10]
                ],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
