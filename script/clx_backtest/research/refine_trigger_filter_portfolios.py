# -*- coding: utf-8 -*-
"""Refine atomic CLX filters at account level and search shared portfolios."""

from __future__ import annotations

import importlib.util
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_SCRIPT = Path("/tmp/search_trigger_filters.py")
SEARCH_PATH = Path("/tmp/clx_trigger_filter_search.json")
CANDIDATE_PATH = Path("/tmp/clx_trigger_filter_dev_candidates.parquet")
OUTPUT_PATH = Path("/tmp/clx_trigger_filter_refined.json")
TOP_STRATEGIES_TO_REFINE = 20
CORE_STRATEGIES = 8
MAX_COMBINATION_SIZE = 4


def load_base() -> Any:
    spec = importlib.util.spec_from_file_location("trigger_filter_base", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to import {BASE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def apply_config(
    base: Any, frame: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    return frame[base.rule_mask(frame, list(config["rules"]))].copy()


def refine_atomic(
    base: Any,
    candidates: pd.DataFrame,
    search: dict[str, Any],
    bars: dict[str, tuple[np.ndarray, ...]],
    calendar: np.ndarray,
) -> list[dict[str, Any]]:
    current_by_strategy = {item["strategy_id"]: item for item in search["leaderboard"]}
    priority = [
        item["strategy_id"] for item in search["leaderboard"][:TOP_STRATEGIES_TO_REFINE]
    ]
    refined: list[dict[str, Any]] = []
    for number, strategy_id in enumerate(
        sorted(current_by_strategy),
        start=1,
    ):
        current = current_by_strategy[strategy_id]
        frame = candidates[candidates["strategy_id"] == strategy_id]
        configs: list[dict[str, Any]] = [
            {
                "rules": list(current["rules"]),
                "exit_mode": current["exit_mode"],
            }
        ]
        if strategy_id in priority:
            for config in current["trade_search"].get("top_trade_candidates", []):
                candidate = {
                    "rules": list(config["rules"]),
                    "exit_mode": config["exit_mode"],
                }
                if candidate not in configs:
                    configs.append(candidate)
        evaluated: list[dict[str, Any]] = []
        for config in configs:
            filtered = apply_config(base, frame, config)
            account = base.account_segments(
                filtered,
                bars,
                calendar,
                config["exit_mode"],
            )
            evaluated.append(
                {
                    **config,
                    "filtered_signals": len(filtered),
                    "account": account,
                }
            )
        evaluated.sort(key=lambda item: item["account"]["objective"], reverse=True)
        winner = evaluated[0]
        refined.append(
            {
                "strategy_id": strategy_id,
                "model_code": current["model_code"],
                "primary_trigger_semantic": current["primary_trigger_semantic"],
                "raw_signals": len(frame),
                "rules": winner["rules"],
                "exit_mode": winner["exit_mode"],
                "filtered_signals": winner["filtered_signals"],
                "account": winner["account"],
                "evaluated_configs": evaluated,
            }
        )
        print(
            f"refine {number}/{len(current_by_strategy)} {strategy_id} "
            f"configs={len(configs)} objective={winner['account']['objective']:.4f}",
            flush=True,
        )
    refined.sort(key=lambda item: item["account"]["objective"], reverse=True)
    return refined


def combined_entries(
    base: Any,
    candidates: pd.DataFrame,
    atomic_by_id: dict[str, dict[str, Any]],
    strategies: tuple[str, ...],
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for strategy_id in strategies:
        config = atomic_by_id[strategy_id]
        frame = candidates[candidates["strategy_id"] == strategy_id]
        frame = apply_config(base, frame, config)
        frame = frame.copy()
        frame["source_strategy"] = strategy_id
        frame["source_strength"] = config["account"]["objective"]
        frame["source_exit_mode"] = config["exit_mode"]
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True)
    return result.sort_values(
        [
            "entry_date",
            "source_strength",
            "concurrent_trigger_count",
            "same_code_model_count",
            "amount_median_20",
            "code",
        ],
        ascending=[True, False, False, False, False, True],
    )


def simulate_shared_account(
    base: Any,
    frame: pd.DataFrame,
    mark_bars: dict[str, tuple[np.ndarray, ...]],
    calendar: np.ndarray,
    *,
    start_year: int,
    end_year: int,
    per_source_cap: int | None = None,
    ranking_policy: str = "source_strength",
) -> dict[str, Any]:
    period_calendar = calendar[
        (pd.DatetimeIndex(calendar).year >= start_year)
        & (pd.DatetimeIndex(calendar).year <= end_year)
    ]
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
                "source_strength",
                "amount_median_20",
                "code",
            ],
            ascending=[True, False, False, False, False, True],
        )
    elif ranking_policy == "pullback":
        frame = frame.sort_values(
            [
                "entry_date",
                "stock_return_20",
                "source_strength",
                "amount_median_20",
                "code",
            ],
            ascending=[True, True, False, False, True],
        )
    elif ranking_policy == "liquidity":
        frame = frame.sort_values(
            [
                "entry_date",
                "amount_median_20",
                "source_strength",
                "code",
            ],
            ascending=[True, False, False, True],
        )
    entries = {
        date.to_datetime64(): list(rows.itertuples(index=False))
        for date, rows in frame.groupby("entry_date", sort=False)
    }
    cash = base.INITIAL_CAPITAL
    positions: dict[str, dict[str, Any]] = {}
    source_positions: dict[str, int] = defaultdict(int)
    equity_dates: list[np.datetime64] = []
    equity_values: list[float] = []
    trade_returns: list[float] = []
    source_trades: dict[str, int] = defaultdict(int)
    total_fees = 0.0
    skipped_slots = 0
    skipped_source_cap = 0
    skipped_duplicate = 0
    skipped_limit_up = 0
    blocked_exits = 0

    def position_value(date: np.datetime64, field: int) -> float:
        value = 0.0
        for code, position in positions.items():
            price = base.mark_price(mark_bars[code], date, field)
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
            if open_price / prior_close - 1 < -base.LIMIT_MOVE:
                blocked_exits += 1
                continue
            gross = position["units"] * open_price
            fee = gross * base.FEE_PER_SIDE
            proceeds = gross - fee
            cash += proceeds
            total_fees += fee
            trade_returns.append(proceeds / position["entry_cost"] - 1)
            source = position["source_strategy"]
            source_trades[source] += 1
            source_positions[source] -= 1
            positions.pop(code)

        for row in entries.get(date, []):
            code = str(row.code)
            source = str(row.source_strategy)
            if code in positions:
                skipped_duplicate += 1
                continue
            if len(positions) >= base.MAX_POSITIONS:
                skipped_slots += 1
                continue
            if (
                per_source_cap is not None
                and source_positions[source] >= per_source_cap
            ):
                skipped_source_cap += 1
                continue
            open_price = float(row.qfq_entry_open)
            if not np.isfinite(open_price) or open_price <= 0:
                continue
            if float(row.entry_gap) > base.LIMIT_MOVE:
                skipped_limit_up += 1
                continue
            equity_at_open = cash + position_value(date, field=1)
            target = min(
                equity_at_open / base.MAX_POSITIONS,
                cash / (1 + base.FEE_PER_SIDE),
            )
            if target <= 0:
                skipped_slots += 1
                continue
            gross = target
            fee = gross * base.FEE_PER_SIDE
            cost = gross + fee
            cash -= cost
            total_fees += fee
            exit_mode = str(row.source_exit_mode)
            positions[code] = {
                "units": gross / open_price,
                "entry_cost": cost,
                "exit_date": base.planned_exit_date(row, exit_mode),
                "source_strategy": source,
            }
            source_positions[source] += 1

        equity = cash + position_value(date, field=2)
        equity_dates.append(date)
        equity_values.append(equity)
        if cash < -0.01 or len(positions) > base.MAX_POSITIONS or equity <= 0:
            raise RuntimeError(
                f"shared account invariant failed {date}: cash={cash}, "
                f"positions={len(positions)}, equity={equity}"
            )

    final_date = period_calendar[-1]
    final_market_value = position_value(final_date, field=2)
    liquidation_fee = final_market_value * base.FEE_PER_SIDE
    final_equity = cash + final_market_value - liquidation_fee
    total_fees += liquidation_fee
    equity_values[-1] = final_equity
    equity = pd.Series(equity_values, index=pd.to_datetime(equity_dates))
    drawdown = equity / equity.cummax() - 1
    years = max(
        (pd.Timestamp(final_date) - pd.Timestamp(period_calendar[0])).days / 365.25,
        1 / 365.25,
    )
    total_return = final_equity / base.INITIAL_CAPITAL - 1
    cagr = (final_equity / base.INITIAL_CAPITAL) ** (1 / years) - 1
    return {
        "period": [start_year, end_year],
        "final_equity": round(float(final_equity), 2),
        "total_return": round(float(total_return), 6),
        "cagr": round(float(cagr), 6),
        "max_drawdown": round(float(drawdown.min()), 6),
        "signals": len(frame),
        "trades": len(trade_returns),
        "win_rate": (
            round(float(np.mean(np.asarray(trade_returns) > 0)), 6)
            if trade_returns
            else None
        ),
        "mean_trade_return": (
            round(float(np.mean(trade_returns)), 6) if trade_returns else None
        ),
        "source_trades": dict(source_trades),
        "total_fees": round(float(total_fees), 2),
        "skipped_slots": skipped_slots,
        "skipped_source_cap": skipped_source_cap,
        "skipped_duplicate": skipped_duplicate,
        "skipped_limit_up": skipped_limit_up,
        "blocked_exits": blocked_exits,
    }


def shared_segments(
    base: Any,
    frame: pd.DataFrame,
    bars: dict[str, tuple[np.ndarray, ...]],
    calendar: np.ndarray,
    *,
    per_source_cap: int | None = None,
    ranking_policy: str = "source_strength",
) -> dict[str, Any]:
    segments = {
        name: simulate_shared_account(
            base,
            frame,
            bars,
            calendar,
            start_year=start,
            end_year=end,
            per_source_cap=per_source_cap,
            ranking_policy=ranking_policy,
        )
        for name, start, end in base.FOLDS
    }
    full = simulate_shared_account(
        base,
        frame,
        bars,
        calendar,
        start_year=2005,
        end_year=2023,
        per_source_cap=per_source_cap,
        ranking_policy=ranking_policy,
    )
    return {
        "segments": segments,
        "full": full,
        "objective": round(base.development_objective(segments), 8),
        "per_source_cap": per_source_cap,
        "ranking_policy": ranking_policy,
    }


def main() -> None:
    base = load_base()
    search = json.loads(SEARCH_PATH.read_text(encoding="utf-8"))
    candidates = pd.read_parquet(CANDIDATE_PATH)
    candidates["entry_date"] = pd.to_datetime(candidates["entry_date"])
    candidates["reveal_date"] = pd.to_datetime(candidates["reveal_date"])
    print("loading mark bars", flush=True)
    bars = base.load_mark_bars(set(candidates["code"].astype(str)))
    calendar = base.load_calendar()
    refined = refine_atomic(base, candidates, search, bars, calendar)
    atomic_by_id = {item["strategy_id"]: item for item in refined}

    eligible = [
        item
        for item in refined
        if item["account"]["objective"] > 0
        and item["account"]["full"]["trades"] >= 200
        and all(
            segment["total_return"] > 0
            for segment in item["account"]["segments"].values()
        )
    ]
    core_ids = tuple(item["strategy_id"] for item in eligible[:CORE_STRATEGIES])
    print(f"core strategies={core_ids}", flush=True)
    combination_results: list[dict[str, Any]] = []
    for size in range(1, MAX_COMBINATION_SIZE + 1):
        for strategies in itertools.combinations(core_ids, size):
            frame = combined_entries(base, candidates, atomic_by_id, strategies)
            account = shared_segments(base, frame, bars, calendar)
            combination_results.append(
                {
                    "strategies": list(strategies),
                    "account": account,
                }
            )
        print(
            f"combination size={size} total={len(combination_results)}",
            flush=True,
        )
    combination_results.sort(
        key=lambda item: item["account"]["objective"],
        reverse=True,
    )
    best_strategies = tuple(combination_results[0]["strategies"])
    best_frame = combined_entries(
        base,
        candidates,
        atomic_by_id,
        best_strategies,
    )
    execution_variants: list[dict[str, Any]] = []
    source_count = len(best_strategies)
    caps = sorted(
        {
            None,
            max(3, base.MAX_POSITIONS // max(source_count, 1)),
            max(5, int(math.ceil(base.MAX_POSITIONS * 0.50))),
        },
        key=lambda value: 10_000 if value is None else value,
    )
    for cap in caps:
        for policy in ("source_strength", "quality", "pullback", "liquidity"):
            account = shared_segments(
                base,
                best_frame,
                bars,
                calendar,
                per_source_cap=cap,
                ranking_policy=policy,
            )
            execution_variants.append(
                {
                    "strategies": list(best_strategies),
                    "per_source_cap": cap,
                    "ranking_policy": policy,
                    "account": account,
                }
            )
    execution_variants.sort(
        key=lambda item: item["account"]["objective"],
        reverse=True,
    )
    payload = {
        "run_id": search["run_id"],
        "status": "REFINED_DEVELOPMENT_SEARCH",
        "development_period": [2005, 2023],
        "holdout_rows_read": 0,
        "account_contract": search["account_contract"],
        "atomic_leaderboard": refined,
        "core_strategy_ids": list(core_ids),
        "combination_leaderboard": combination_results,
        "execution_variants": execution_variants,
        "development_winner": execution_variants[0],
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT_PATH),
                "top_atomic": [
                    {
                        "strategy_id": item["strategy_id"],
                        "rules": item["rules"],
                        "exit": item["exit_mode"],
                        "objective": item["account"]["objective"],
                    }
                    for item in refined[:10]
                ],
                "development_winner": {
                    "strategies": execution_variants[0]["strategies"],
                    "per_source_cap": execution_variants[0]["per_source_cap"],
                    "ranking_policy": execution_variants[0]["ranking_policy"],
                    "objective": execution_variants[0]["account"]["objective"],
                    "full_return": execution_variants[0]["account"]["full"][
                        "total_return"
                    ],
                    "max_drawdown": execution_variants[0]["account"]["full"][
                        "max_drawdown"
                    ],
                },
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
