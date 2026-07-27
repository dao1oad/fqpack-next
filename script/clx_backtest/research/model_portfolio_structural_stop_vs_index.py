# -*- coding: utf-8 -*-
"""Backtest each CLX model in a constrained account with structural stops.

For each S0000-S0017 model, buy its long signals in an independent CNY
1,000,000 account with at most 20 equal-weight positions. Exit at the earlier
of:

* the next open after any CLX model reveals a sell signal for the symbol; or
* an intraday touch of the latest causally confirmed five-bar fractal low.

The fractal low is a reproducible approximation of ClxsStrategy's latest
down-bi-low stop. A center bar is eligible only after both right-hand bars are
visible on or before the signal reveal date.

The script reads the sealed TRAIN/VALIDATION artifacts and QFQ snapshot without
modifying them. It writes /tmp/clx_model_portfolio_structural_stop.json.
"""

from __future__ import annotations

import glob
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pymongo

EVENT_GLOB = (
    "/opt/clx-backtest/events/clx-preview-99634853b/event-study/"
    "code_buckets/code_bucket=*/event_outcomes/reveal_year=*/part-*.parquet"
)
SNAPSHOT_GLOB = (
    "/opt/clx-backtest/snapshots/"
    "cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4/"
    "bars"
)
OUTPUT_PATH = Path("/tmp/clx_model_portfolio_structural_stop.json")

START_YEAR = 2005
END_YEAR = 2023
INITIAL_CAPITAL = 1_000_000.0
SLOTS = 20
FEE_PER_SIDE = 0.002
LIMIT_MOVE = 0.095
BOARD_LOT = 100


@dataclass(frozen=True)
class Candidate:
    code: str
    model_code: str
    reveal_date: np.datetime64
    entry_date: np.datetime64
    entry_index: int
    stop_price: float | None
    signal_exit_date: np.datetime64 | None


@dataclass
class Position:
    shares: int
    entry_cost: float
    entry_date: np.datetime64
    stop_price: float | None
    signal_exit_date: np.datetime64 | None


def load_events() -> pd.DataFrame:
    columns = [
        "code",
        "model_code",
        "direction",
        "reveal_date",
        "entry_status",
        "split_id",
        "split_boundary_status",
    ]
    frames: list[pd.DataFrame] = []
    for filename in sorted(glob.glob(EVENT_GLOB)):
        year = int(filename.split("reveal_year=")[1].split("/")[0])
        if START_YEAR <= year <= END_YEAR:
            frame = pd.read_parquet(filename, columns=columns)
            frame = frame[
                (frame["split_boundary_status"] == "ELIGIBLE")
                & (frame["entry_status"] == "EXECUTABLE")
                & (frame["split_id"].isin(["TRAIN", "VALIDATION"]))
            ]
            frames.append(frame)
    events = pd.concat(frames, ignore_index=True)
    events["reveal_date"] = pd.to_datetime(events["reveal_date"].astype(str))
    events = events.drop_duplicates(["code", "model_code", "direction", "reveal_date"])
    return events


def load_bars(codes: set[str]) -> dict[str, tuple[np.ndarray, ...]]:
    dataset = ds.dataset(glob.glob(SNAPSHOT_GLOB)[0], format="parquet")
    table = dataset.to_table(
        columns=[
            "code",
            "trade_date",
            "qfq_open",
            "qfq_low",
            "qfq_close",
        ],
        filter=(ds.field("trade_year") >= START_YEAR - 1)
        & (ds.field("trade_year") <= END_YEAR + 1),
    )
    bars = table.to_pandas()
    bars = bars[bars["code"].isin(codes)]
    bars["trade_date"] = pd.to_datetime(bars["trade_date"].astype(str))
    bars = bars.dropna(subset=["qfq_open", "qfq_low", "qfq_close"]).sort_values(
        ["code", "trade_date"]
    )
    return {
        code: (
            frame["trade_date"].values,
            frame["qfq_open"].to_numpy(dtype=float),
            frame["qfq_low"].to_numpy(dtype=float),
            frame["qfq_close"].to_numpy(dtype=float),
        )
        for code, frame in bars.groupby("code", sort=False)
    }


def load_index() -> pd.DataFrame:
    client = pymongo.MongoClient(
        "mongodb://fq_mongodb:27017", serverSelectionTimeoutMS=5_000
    )
    records = list(
        client["quantaxis"]["index_day"].find(
            {
                "code": "000001",
                "date": {
                    "$gte": f"{START_YEAR - 1}-01-01",
                    "$lte": f"{END_YEAR}-12-31",
                },
            },
            {"_id": 0, "date": 1, "close": 1},
        )
    )
    index = pd.DataFrame(records).sort_values("date")
    index["date"] = pd.to_datetime(index["date"])
    index["close"] = index["close"].astype(float)
    return index


def confirmed_fractal_stops(lows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return confirmation indexes and stop values for five-bar fractal lows."""
    if len(lows) < 5:
        return np.array([], dtype=int), np.array([], dtype=float)
    centers = np.arange(2, len(lows) - 2)
    windows = np.lib.stride_tricks.sliding_window_view(lows, 5)
    is_bottom = lows[centers] == windows.min(axis=1)
    bottom_centers = centers[is_bottom]
    return bottom_centers + 2, lows[bottom_centers]


def build_candidates(
    events: pd.DataFrame,
    code_bars: dict[str, tuple[np.ndarray, ...]],
) -> dict[str, list[Candidate]]:
    sells = events[events["direction"] == -1][["code", "reveal_date"]]
    sells = sells.drop_duplicates()
    sell_map = {
        code: np.sort(frame["reveal_date"].values)
        for code, frame in sells.groupby("code", sort=False)
    }
    buys = events[events["direction"] == 1]
    by_model: dict[str, list[Candidate]] = defaultdict(list)

    for code, frame in buys.groupby("code", sort=False):
        bar_data = code_bars.get(code)
        if bar_data is None:
            continue
        dates, _opens, lows, _closes = bar_data
        confirmations, stop_values = confirmed_fractal_stops(lows)
        sell_dates = sell_map.get(code)
        for row in frame.itertuples(index=False):
            reveal = row.reveal_date.to_datetime64()
            entry_index = int(np.searchsorted(dates, reveal, side="right"))
            if entry_index >= len(dates):
                continue

            reveal_bar = int(np.searchsorted(dates, reveal, side="right") - 1)
            stop_price: float | None = None
            if reveal_bar >= 0 and len(confirmations):
                stop_offset = int(
                    np.searchsorted(confirmations, reveal_bar, side="right") - 1
                )
                if stop_offset >= 0:
                    value = float(stop_values[stop_offset])
                    if np.isfinite(value) and value > 0:
                        stop_price = value

            signal_exit_date: np.datetime64 | None = None
            if sell_dates is not None:
                sell_offset = int(np.searchsorted(sell_dates, reveal, side="right"))
                if sell_offset < len(sell_dates):
                    exit_index = int(
                        np.searchsorted(dates, sell_dates[sell_offset], side="right")
                    )
                    executable_exit_index = max(exit_index, entry_index + 1)
                    if executable_exit_index < len(dates):
                        signal_exit_date = dates[executable_exit_index]

            by_model[row.model_code].append(
                Candidate(
                    code=code,
                    model_code=row.model_code,
                    reveal_date=reveal,
                    entry_date=dates[entry_index],
                    entry_index=entry_index,
                    stop_price=stop_price,
                    signal_exit_date=signal_exit_date,
                )
            )

    for candidates in by_model.values():
        candidates.sort(
            key=lambda item: (
                item.entry_date,
                item.reveal_date,
                item.code,
            )
        )
    return by_model


def previous_close(bars: tuple[np.ndarray, ...], bar_index: int) -> float | None:
    if bar_index <= 0:
        return None
    return float(bars[3][bar_index - 1])


def is_limit_move(open_price: float, prior_close: float | None, side: str) -> bool:
    if prior_close is None or prior_close <= 0:
        return False
    move = open_price / prior_close - 1
    return move > LIMIT_MOVE if side == "buy" else move < -LIMIT_MOVE


def mark_price(bars: tuple[np.ndarray, ...], date: np.datetime64, field: int) -> float:
    dates = bars[0]
    offset = int(np.searchsorted(dates, date, side="right") - 1)
    if offset < 0:
        return float("nan")
    return float(bars[field][offset])


def annual_returns(equity: pd.Series) -> dict[str, float]:
    year_end = equity.groupby(equity.index.year).last()
    returns: dict[str, float] = {}
    prior = INITIAL_CAPITAL
    for year, value in year_end.items():
        returns[str(int(year))] = round(float(value / prior - 1), 6)
        prior = float(value)
    return returns


def simulate_model(
    model_code: str,
    candidates: list[Candidate],
    calendar: np.ndarray,
    code_bars: dict[str, tuple[np.ndarray, ...]],
) -> dict[str, Any]:
    entries: dict[np.datetime64, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        entries[candidate.entry_date].append(candidate)

    cash = INITIAL_CAPITAL
    positions: dict[str, Position] = {}
    equity_rows: list[tuple[np.datetime64, float]] = []
    trades: list[dict[str, Any]] = []
    skipped_slots = 0
    skipped_limit_up = 0
    skipped_duplicate = 0
    blocked_exits = 0
    missing_stop = 0

    def total_equity(date: np.datetime64, price_field: int) -> float:
        market_value = 0.0
        for code, position in positions.items():
            price = mark_price(code_bars[code], date, price_field)
            if np.isfinite(price):
                market_value += position.shares * price
        return cash + market_value

    def close_position(
        code: str, date: np.datetime64, price: float, reason: str
    ) -> None:
        nonlocal cash
        position = positions.pop(code)
        proceeds = position.shares * price * (1 - FEE_PER_SIDE)
        cash += proceeds
        trades.append(
            {
                "code": code,
                "entry_date": str(position.entry_date)[:10],
                "exit_date": str(date)[:10],
                "return": proceeds / position.entry_cost - 1,
                "reason": reason,
            }
        )

    for date in calendar:
        # Sell-signal orders execute at the open before intraday stop checks.
        for code in list(positions):
            position = positions[code]
            if position.signal_exit_date is None or position.signal_exit_date > date:
                continue
            bars = code_bars[code]
            offset = int(np.searchsorted(bars[0], date))
            if offset >= len(bars[0]) or bars[0][offset] != date:
                continue
            open_price = float(bars[1][offset])
            if is_limit_move(open_price, previous_close(bars, offset), side="sell"):
                blocked_exits += 1
                continue
            close_position(code, date, open_price, "ANY_MODEL_SELL")

        # Entries execute at the open and use a dynamic 1/20 equity target.
        for candidate in entries.get(date, []):
            code = candidate.code
            if code in positions:
                skipped_duplicate += 1
                continue
            if len(positions) >= SLOTS:
                skipped_slots += 1
                continue
            bars = code_bars[code]
            offset = candidate.entry_index
            open_price = float(bars[1][offset])
            if is_limit_move(open_price, previous_close(bars, offset), side="buy"):
                skipped_limit_up += 1
                continue
            target = min(total_equity(date, price_field=1) / SLOTS, cash)
            shares = (
                int(target / (open_price * (1 + FEE_PER_SIDE)) // BOARD_LOT) * BOARD_LOT
            )
            if shares < BOARD_LOT:
                skipped_slots += 1
                continue
            cost = shares * open_price * (1 + FEE_PER_SIDE)
            cash -= cost
            positions[code] = Position(
                shares=shares,
                entry_cost=cost,
                entry_date=date,
                stop_price=candidate.stop_price,
                signal_exit_date=candidate.signal_exit_date,
            )
            if candidate.stop_price is None:
                missing_stop += 1

        # Structural stops may trigger after today's open, including entry day.
        for code in list(positions):
            position = positions[code]
            if position.stop_price is None:
                continue
            bars = code_bars[code]
            offset = int(np.searchsorted(bars[0], date))
            if offset >= len(bars[0]) or bars[0][offset] != date:
                continue
            open_price = float(bars[1][offset])
            low_price = float(bars[2][offset])
            if low_price > position.stop_price:
                continue
            if is_limit_move(open_price, previous_close(bars, offset), side="sell"):
                blocked_exits += 1
                continue
            exit_price = min(open_price, position.stop_price)
            close_position(code, date, exit_price, "STRUCTURAL_STOP")

        equity = total_equity(date, price_field=3)
        if not np.isfinite(equity) or equity <= 0:
            raise RuntimeError(
                f"{model_code} produced invalid equity on {date}: {equity}"
            )
        if cash < -0.01 or len(positions) > SLOTS:
            raise RuntimeError(f"{model_code} violated cash/slot constraints on {date}")
        equity_rows.append((date, equity))

    equity = pd.Series(
        [value for _, value in equity_rows],
        index=pd.to_datetime([date for date, _ in equity_rows]),
    )
    drawdown = equity / equity.cummax() - 1
    trade_frame = pd.DataFrame(trades)
    reason_counts = (
        trade_frame["reason"].value_counts().to_dict() if len(trade_frame) else {}
    )
    return {
        "model_code": model_code,
        "candidate_signals": len(candidates),
        "closed_trades": len(trades),
        "open_positions_at_end": len(positions),
        "win_rate": (
            round(float((trade_frame["return"] > 0).mean()), 6)
            if len(trade_frame)
            else None
        ),
        "mean_trade_return": (
            round(float(trade_frame["return"].mean()), 6) if len(trade_frame) else None
        ),
        "final_equity": round(float(equity.iloc[-1]), 2),
        "total_return": round(float(equity.iloc[-1] / INITIAL_CAPITAL - 1), 6),
        "max_drawdown": round(float(drawdown.min()), 6),
        "exit_reasons": {key: int(value) for key, value in reason_counts.items()},
        "skipped_slots": skipped_slots,
        "skipped_limit_up": skipped_limit_up,
        "skipped_duplicate": skipped_duplicate,
        "blocked_exits": blocked_exits,
        "entries_without_stop": missing_stop,
        "yearly_returns": annual_returns(equity),
        "year_end_equity": {
            str(int(year)): round(float(value), 2)
            for year, value in equity.groupby(equity.index.year).last().items()
        },
    }


def index_annual_returns(index: pd.DataFrame) -> dict[str, float]:
    year_end = index.groupby(index["date"].dt.year)["close"].last()
    return {
        str(year): round(float(year_end.loc[year] / year_end.loc[year - 1] - 1), 6)
        for year in range(START_YEAR, END_YEAR + 1)
        if year in year_end.index and year - 1 in year_end.index
    }


def main() -> None:
    events = load_events()
    print(f"events={len(events)}", flush=True)
    buys = events[events["direction"] == 1]
    code_bars = load_bars(set(buys["code"]))
    print(f"bar_codes={len(code_bars)}", flush=True)
    index = load_index()
    calendar = index[
        (index["date"].dt.year >= START_YEAR) & (index["date"].dt.year <= END_YEAR)
    ]["date"].values
    candidates = build_candidates(events, code_bars)
    print(
        "candidates="
        + json.dumps(
            {model: len(items) for model, items in sorted(candidates.items())}
        ),
        flush=True,
    )

    models: dict[str, Any] = {}
    for model_code in [f"S{number:04d}" for number in range(18)]:
        result = simulate_model(
            model_code,
            candidates.get(model_code, []),
            calendar,
            code_bars,
        )
        models[model_code] = result
        print(
            model_code,
            f"trades={result['closed_trades']}",
            f"return={result['total_return']:.4f}",
            f"mdd={result['max_drawdown']:.4f}",
            f"reasons={result['exit_reasons']}",
            flush=True,
        )

    output = {
        "run_id": "01KBYC7REC0V3RY99634853AAB",
        "sample": "TRAIN+VALIDATION",
        "period": [START_YEAR, END_YEAR],
        "capital": INITIAL_CAPITAL,
        "slots": SLOTS,
        "fee_per_side": FEE_PER_SIDE,
        "board_lot": BOARD_LOT,
        "limit_move": LIMIT_MOVE,
        "price_domain": "QFQ",
        "stop_contract": {
            "kind": "LATEST_CAUSALLY_CONFIRMED_FIVE_BAR_FRACTAL_LOW",
            "confirmation_lag_bars": 2,
            "online_semantic_approximated": "latest fq_recognise_bi down-bi low",
            "trigger": "qfq_low <= stop_price",
            "fill": "min(qfq_open, stop_price), unless limit-down blocked",
        },
        "sell_contract": "first any-model sell reveal after buy, next qfq open",
        "models": models,
        "sh_index_yearly_returns": index_annual_returns(index),
    }
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote={OUTPUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
