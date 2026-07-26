# -*- coding: utf-8 -*-
"""Optimize execution and risk controls for frozen development combinations."""

from __future__ import annotations

import importlib.util
import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

BASE_SCRIPT = Path("/tmp/search_trigger_filters.py")
REFINE_SCRIPT = Path("/tmp/refine_trigger_filter_portfolios.py")
REFINED_PATH = Path("/tmp/clx_trigger_filter_refined.json")
CANDIDATE_PATH = Path("/tmp/clx_trigger_filter_dev_candidates.parquet")
OUTPUT_PATH = Path("/tmp/clx_trigger_filter_risk_optimized.json")
SNAPSHOT_ROOT = (
    "/opt/clx-backtest/snapshots/"
    "cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4/"
    "bars"
)

RISK_MODES = (
    "none",
    "hard_stop_08",
    "hard_stop_10",
    "hard_stop_12",
    "hard_stop_15",
    "structural_stop",
    "hard10_take20",
    "trail12",
)
RANKING_POLICIES = ("source_strength", "pullback")
MAX_POSITIONS_CHOICES = (30, 40)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_risk_bars(codes: set[str]) -> dict[str, tuple[np.ndarray, ...]]:
    dataset = ds.dataset(SNAPSHOT_ROOT, format="parquet")
    table = dataset.to_table(
        columns=[
            "code",
            "trade_date",
            "qfq_open",
            "qfq_high",
            "qfq_low",
            "qfq_close",
        ],
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
            rows["qfq_high"].to_numpy(dtype=float),
            rows["qfq_low"].to_numpy(dtype=float),
            rows["qfq_close"].to_numpy(dtype=float),
        )
        for code, rows in frame.groupby("code", sort=False)
    }


def mark_price(
    bars: tuple[np.ndarray, ...],
    date: np.datetime64,
    field: int,
) -> float:
    offset = int(np.searchsorted(bars[0], date, side="right") - 1)
    if offset < 0:
        return float("nan")
    return float(bars[field][offset])


def risk_contract(
    risk_mode: str,
    entry_price: float,
    structural_stop: float,
) -> tuple[float | None, float | None, float | None]:
    hard_stop: float | None = None
    take_profit: float | None = None
    trailing: float | None = None
    if risk_mode.startswith("hard_stop_"):
        hard_stop = entry_price * (1 - int(risk_mode.rsplit("_", 1)[1]) / 100)
    elif risk_mode == "structural_stop":
        if np.isfinite(structural_stop) and 0 < structural_stop < entry_price:
            hard_stop = structural_stop
    elif risk_mode == "hard10_take20":
        hard_stop = entry_price * 0.90
        take_profit = entry_price * 1.20
    elif risk_mode == "trail12":
        trailing = 0.12
    return hard_stop, take_profit, trailing


def simulate(
    base: Any,
    frame: pd.DataFrame,
    bars_by_code: dict[str, tuple[np.ndarray, ...]],
    calendar: np.ndarray,
    *,
    start_year: int,
    end_year: int,
    risk_mode: str,
    ranking_policy: str,
    max_positions: int,
    per_source_cap: int | None,
    extra_slippage_per_side: float = 0.0,
    max_participation_rate: float | None = None,
) -> dict[str, Any]:
    period_calendar = calendar[
        (pd.DatetimeIndex(calendar).year >= start_year)
        & (pd.DatetimeIndex(calendar).year <= end_year)
    ]
    frame = frame[
        (pd.to_datetime(frame["entry_date"]).dt.year >= start_year)
        & (pd.to_datetime(frame["entry_date"]).dt.year <= end_year)
    ].copy()
    if ranking_policy == "pullback":
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
    else:
        frame = frame.sort_values(
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
    entries = {
        date.to_datetime64(): list(rows.itertuples(index=False))
        for date, rows in frame.groupby("entry_date", sort=False)
    }
    fee_rate = base.FEE_PER_SIDE + extra_slippage_per_side
    cash = base.INITIAL_CAPITAL
    positions: dict[str, dict[str, Any]] = {}
    source_positions: dict[str, int] = defaultdict(int)
    equity_dates: list[np.datetime64] = []
    equity_values: list[float] = []
    trade_returns: list[float] = []
    exit_reasons: dict[str, int] = defaultdict(int)
    source_trades: dict[str, int] = defaultdict(int)
    total_fees = 0.0
    skipped_slots = 0
    skipped_source_cap = 0
    skipped_duplicate = 0
    skipped_limit_up = 0
    blocked_exits = 0
    capacity_capped_entries = 0

    def position_value(date: np.datetime64, field: int) -> float:
        value = 0.0
        for code, position in positions.items():
            price = mark_price(bars_by_code[code], date, field)
            if np.isfinite(price):
                value += position["units"] * price
        return value

    def close_position(
        code: str,
        price: float,
        reason: str,
    ) -> None:
        nonlocal cash, total_fees
        position = positions.pop(code)
        gross = position["units"] * price
        fee = gross * fee_rate
        proceeds = gross - fee
        cash += proceeds
        total_fees += fee
        trade_returns.append(proceeds / position["entry_cost"] - 1)
        source = position["source_strategy"]
        source_trades[source] += 1
        source_positions[source] -= 1
        exit_reasons[reason] += 1

    for date in period_calendar:
        for code in list(positions):
            position = positions[code]
            bars = bars_by_code[code]
            offset = int(np.searchsorted(bars[0], date))
            if offset >= len(bars[0]) or bars[0][offset] != date:
                continue
            open_price = float(bars[1][offset])
            high_price = float(bars[2][offset])
            low_price = float(bars[3][offset])
            prior_close = float(bars[4][offset - 1]) if offset > 0 else open_price
            blocked = open_price / prior_close - 1 < -base.LIMIT_MOVE
            planned = position["exit_date"]
            if not np.isnat(planned) and date >= planned:
                if blocked:
                    blocked_exits += 1
                    continue
                close_position(code, open_price, "TIME_OR_SIGNAL")
                continue
            hard_stop = position["hard_stop"]
            if hard_stop is not None and low_price <= hard_stop:
                if blocked:
                    blocked_exits += 1
                    continue
                close_position(code, min(open_price, hard_stop), "STOP")
                continue
            take_profit = position["take_profit"]
            if take_profit is not None and high_price >= take_profit:
                if blocked:
                    blocked_exits += 1
                    continue
                close_position(code, max(open_price, take_profit), "TAKE_PROFIT")
                continue
            trailing = position["trailing"]
            if trailing is not None:
                trailing_stop = position["high_water"] * (1 - trailing)
                if low_price <= trailing_stop:
                    if blocked:
                        blocked_exits += 1
                        continue
                    close_position(
                        code,
                        min(open_price, trailing_stop),
                        "TRAILING_STOP",
                    )
                    continue
                position["high_water"] = max(
                    position["high_water"],
                    high_price,
                )

        for row in entries.get(date, []):
            code = str(row.code)
            source = str(row.source_strategy)
            if code in positions:
                skipped_duplicate += 1
                continue
            if len(positions) >= max_positions:
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
                equity_at_open / max_positions,
                cash / (1 + fee_rate),
            )
            if max_participation_rate is not None:
                median_amount = float(row.amount_median_20)
                if not np.isfinite(median_amount) or median_amount <= 0:
                    continue
                capacity_target = median_amount * max_participation_rate
                if capacity_target < target:
                    capacity_capped_entries += 1
                    target = capacity_target
            if target <= 0:
                skipped_slots += 1
                continue
            fee = target * fee_rate
            cost = target + fee
            cash -= cost
            total_fees += fee
            exit_mode = str(row.source_exit_mode)
            hard_stop, take_profit, trailing = risk_contract(
                risk_mode,
                open_price,
                float(row.structural_stop_price),
            )
            positions[code] = {
                "units": target / open_price,
                "entry_cost": cost,
                "exit_date": base.planned_exit_date(row, exit_mode),
                "source_strategy": source,
                "hard_stop": hard_stop,
                "take_profit": take_profit,
                "trailing": trailing,
                "high_water": open_price,
            }
            source_positions[source] += 1

        equity = cash + position_value(date, field=4)
        equity_dates.append(date)
        equity_values.append(equity)
        if cash < -0.01 or len(positions) > max_positions or equity <= 0:
            raise RuntimeError(
                f"risk account invariant failed {date}: cash={cash}, "
                f"positions={len(positions)}, equity={equity}"
            )

    final_date = period_calendar[-1]
    final_market_value = position_value(final_date, field=4)
    liquidation_fee = final_market_value * fee_rate
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
        "exit_reasons": dict(exit_reasons),
        "total_fees_and_slippage": round(float(total_fees), 2),
        "skipped_slots": skipped_slots,
        "skipped_source_cap": skipped_source_cap,
        "skipped_duplicate": skipped_duplicate,
        "skipped_limit_up": skipped_limit_up,
        "blocked_exits": blocked_exits,
        "capacity_capped_entries": capacity_capped_entries,
    }


def segments(
    base: Any,
    frame: pd.DataFrame,
    bars: dict[str, tuple[np.ndarray, ...]],
    calendar: np.ndarray,
    **contract: Any,
) -> dict[str, Any]:
    fold_results = {
        name: simulate(
            base,
            frame,
            bars,
            calendar,
            start_year=start,
            end_year=end,
            **contract,
        )
        for name, start, end in base.FOLDS
    }
    full = simulate(
        base,
        frame,
        bars,
        calendar,
        start_year=2005,
        end_year=2023,
        **contract,
    )
    return {
        "segments": fold_results,
        "full": full,
        "objective": round(base.development_objective(fold_results), 8),
        "contract": contract,
    }


def unique_shortlist(refined: dict[str, Any]) -> list[tuple[str, ...]]:
    selected: list[tuple[str, ...]] = []
    for item in refined["combination_leaderboard"][:4]:
        value = tuple(item["strategies"])
        if value not in selected:
            selected.append(value)
    low_drawdown = sorted(
        (
            item
            for item in refined["combination_leaderboard"]
            if item["account"]["full"]["max_drawdown"] >= -0.35
        ),
        key=lambda item: item["account"]["objective"],
        reverse=True,
    )
    for item in low_drawdown[:4]:
        value = tuple(item["strategies"])
        if value not in selected:
            selected.append(value)
    return selected[:6]


def main() -> None:
    base = load_module(BASE_SCRIPT, "trigger_filter_base")
    refine = load_module(REFINE_SCRIPT, "trigger_filter_refine")
    refined = json.loads(REFINED_PATH.read_text(encoding="utf-8"))
    candidates = pd.read_parquet(CANDIDATE_PATH)
    candidates["entry_date"] = pd.to_datetime(candidates["entry_date"])
    candidates["reveal_date"] = pd.to_datetime(candidates["reveal_date"])
    atomic_by_id = {item["strategy_id"]: item for item in refined["atomic_leaderboard"]}
    print("loading risk bars", flush=True)
    bars = load_risk_bars(set(candidates["code"].astype(str)))
    calendar = base.load_calendar()
    shortlist = unique_shortlist(refined)
    print(f"shortlist={shortlist}", flush=True)
    results: list[dict[str, Any]] = []
    for combo_index, strategies in enumerate(shortlist, start=1):
        frame = refine.combined_entries(
            base,
            candidates,
            atomic_by_id,
            strategies,
        )
        cap_choices = {
            None,
            max(5, 40 // len(strategies)),
        }
        for (
            risk_mode,
            ranking_policy,
            max_positions,
            per_source_cap,
        ) in itertools.product(
            RISK_MODES,
            RANKING_POLICIES,
            MAX_POSITIONS_CHOICES,
            cap_choices,
        ):
            account = segments(
                base,
                frame,
                bars,
                calendar,
                risk_mode=risk_mode,
                ranking_policy=ranking_policy,
                max_positions=max_positions,
                per_source_cap=per_source_cap,
                extra_slippage_per_side=0.0,
            )
            results.append(
                {
                    "strategies": list(strategies),
                    "account": account,
                }
            )
        print(
            f"risk combo {combo_index}/{len(shortlist)} " f"variants={len(results)}",
            flush=True,
        )
    results.sort(key=lambda item: item["account"]["objective"], reverse=True)

    # Cost sensitivity is evaluated after the development execution winner is frozen.
    winner = results[0]
    winner_strategies = tuple(winner["strategies"])
    winner_frame = refine.combined_entries(
        base,
        candidates,
        atomic_by_id,
        winner_strategies,
    )
    sensitivity: list[dict[str, Any]] = []
    winner_contract = dict(winner["account"]["contract"])
    for extra_bps in (0, 5, 10, 20):
        contract = dict(winner_contract)
        contract["extra_slippage_per_side"] = extra_bps / 10_000
        account = segments(
            base,
            winner_frame,
            bars,
            calendar,
            **contract,
        )
        sensitivity.append(
            {
                "extra_slippage_bps_per_side": extra_bps,
                "account": account,
            }
        )
    payload = {
        "run_id": refined["run_id"],
        "status": "RISK_OPTIMIZED_DEVELOPMENT",
        "development_period": [2005, 2023],
        "holdout_rows_read": 0,
        "account_contract": {
            **refined["account_contract"],
            "risk_modes": RISK_MODES,
            "max_position_choices": MAX_POSITIONS_CHOICES,
        },
        "combination_shortlist": [list(item) for item in shortlist],
        "risk_leaderboard": results,
        "development_winner": winner,
        "cost_sensitivity": sensitivity,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT_PATH),
                "winner": {
                    "strategies": winner["strategies"],
                    "contract": winner["account"]["contract"],
                    "objective": winner["account"]["objective"],
                    "full_return": winner["account"]["full"]["total_return"],
                    "cagr": winner["account"]["full"]["cagr"],
                    "max_drawdown": winner["account"]["full"]["max_drawdown"],
                },
                "top10": [
                    {
                        "strategies": item["strategies"],
                        "contract": item["account"]["contract"],
                        "objective": item["account"]["objective"],
                        "full_return": item["account"]["full"]["total_return"],
                        "max_drawdown": item["account"]["full"]["max_drawdown"],
                    }
                    for item in results[:10]
                ],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
