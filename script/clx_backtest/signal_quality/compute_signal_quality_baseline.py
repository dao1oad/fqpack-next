# -*- coding: utf-8 -*-
"""Compute the CLX signal-quality baseline over sealed event artifacts.

Evaluation unit: one cell = (model_code, primary_trigger_semantic, direction).
Primary metric: 5-trading-day excess return, entered at the next raw session
open after the reveal date (T+1 open) and exited at the T+6 open, minus the
same-window index open-to-open return.

Per cell and split the script reports sample counts, mean/median excess,
win rate, t statistics with Benjamini-Hochberg FDR correction, yearly
stability, a 1/3/5/10/20 day horizon decay curve, cost-adjusted means, and
two randomized controls (same-pool random dates and date-shifted entries).

The script only reads sealed artifacts and writes a single JSON document.
"""

from __future__ import annotations

import glob
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pymongo

RUN_ID = os.environ.get("CLX_SQ_RUN_ID", "01KBYC7REC0V3RY99634853AAB")
EVENT_GLOB = os.environ.get(
    "CLX_SQ_EVENT_GLOB",
    "/opt/clx-backtest/events/clx-preview-99634853b/event-study/"
    "code_buckets/code_bucket=*/event_outcomes/reveal_year=*/part-*.parquet",
)
SNAPSHOT_GLOB = os.environ.get(
    "CLX_SQ_SNAPSHOT_GLOB",
    "/opt/clx-backtest/snapshots/"
    "cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4/bars",
)
OUTPUT_PATH = Path(
    os.environ.get(
        "CLX_SQ_OUTPUT_PATH",
        f"/opt/clx-backtest/signal-quality/{RUN_ID}/baseline.json",
    )
)
MONGO_URI = os.environ.get("CLX_SQ_MONGO_URI", "mongodb://fq_mongodb:27017")

START_YEAR = int(os.environ.get("CLX_SQ_START_YEAR", "2005"))
END_YEAR = int(os.environ.get("CLX_SQ_END_YEAR", "2026"))
HORIZONS = (1, 3, 5, 10, 20)
PRIMARY_HORIZON = 5
LIMIT_MOVE = 0.095
FEE_PER_SIDE = 0.002
SLIPPAGE_PER_SIDE = 0.0005
ROUND_TRIP_COST = 2 * (FEE_PER_SIDE + SLIPPAGE_PER_SIDE)
MIN_CELL_STAT_N = 30
MIN_BOOTSTRAP_N = 100
BOOTSTRAP_REPS = 300
SHIFT_REPS = 200
BOOTSTRAP_SAMPLE_CAP = 2000
SHIFT_RANGE = (20, 60)
SEED = 20260726

QUALIFY = {
    "fdr_q_max": 0.05,
    "watch_fdr_q_max": 0.10,
    "min_train_executable": 500,
    "min_validation_executable": 100,
    "min_mean_excess": 0.005,
    "worst_year_floor": -0.015,
    "min_positive_year_ratio": 0.60,
    "control_percentile_min": 0.95,
}

SPLIT_YEARS = {
    "TRAIN": (2005, 2019),
    "VALIDATION": (2020, 2023),
    "HOLDOUT": (2024, 2026),
}


def load_events() -> pd.DataFrame:
    columns = [
        "code",
        "model_code",
        "direction",
        "reveal_date",
        "entry_status",
        "split_id",
        "split_boundary_status",
        "primary_trigger_semantic",
        "occurrence",
    ]
    frames: list[pd.DataFrame] = []
    for filename in sorted(glob.glob(EVENT_GLOB)):
        year = int(filename.split("reveal_year=")[1].split("/")[0])
        if START_YEAR <= year <= END_YEAR:
            frame = pd.read_parquet(filename, columns=columns)
            frame = frame[frame["split_boundary_status"] == "ELIGIBLE"]
            frames.append(frame)
    events = pd.concat(frames, ignore_index=True)
    events["reveal_date"] = pd.to_datetime(events["reveal_date"].astype(str))
    events = events.drop_duplicates(
        ["code", "model_code", "direction", "reveal_date", "primary_trigger_semantic"]
    )
    return events


def load_bars(codes: set[str]) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    dataset = ds.dataset(glob.glob(SNAPSHOT_GLOB)[0], format="parquet")
    table = dataset.to_table(
        columns=["code", "trade_date", "qfq_open", "qfq_close"],
        filter=(ds.field("trade_year") >= START_YEAR - 1)
        & (ds.field("trade_year") <= END_YEAR + 1),
    )
    bars = table.to_pandas()
    bars = bars[bars["code"].isin(codes)]
    bars["trade_date"] = pd.to_datetime(bars["trade_date"].astype(str))
    bars = bars.dropna(subset=["qfq_open", "qfq_close"]).sort_values(
        ["code", "trade_date"]
    )
    return {
        code: (
            frame["trade_date"].values,
            frame["qfq_open"].to_numpy(dtype=float),
            frame["qfq_close"].to_numpy(dtype=float),
        )
        for code, frame in bars.groupby("code", sort=False)
    }


def load_index_opens() -> tuple[np.ndarray, np.ndarray]:
    client: pymongo.MongoClient = pymongo.MongoClient(
        MONGO_URI, serverSelectionTimeoutMS=5_000
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
            {"_id": 0, "date": 1, "open": 1},
        )
    )
    index = pd.DataFrame(records).sort_values("date")
    dates = pd.to_datetime(index["date"]).values
    opens = index["open"].to_numpy(dtype=float)
    return dates, opens


def index_open_at(index_dates: np.ndarray, index_opens: np.ndarray, date) -> float:
    offset = int(np.searchsorted(index_dates, date, side="right") - 1)
    if offset < 0:
        return float("nan")
    return float(index_opens[offset])


def normal_two_sided_p(t_stat: float) -> float:
    return 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0))))


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    n = len(p_values)
    order = sorted(range(n), key=lambda i: p_values[i])
    q_values = [1.0] * n
    running = 1.0
    for rank_from_end in range(n, 0, -1):
        idx = order[rank_from_end - 1]
        candidate = p_values[idx] * n / rank_from_end
        running = min(running, candidate)
        q_values[idx] = min(running, 1.0)
    return q_values


def build_forward_excess(
    code_bars: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]],
    index_dates: np.ndarray,
    index_opens: np.ndarray,
) -> dict[str, dict[int, np.ndarray]]:
    """Per code and horizon: excess open-to-open forward return per bar index."""
    result: dict[str, dict[int, np.ndarray]] = {}
    for code, (dates, opens, _closes) in code_bars.items():
        idx_open = np.empty(len(dates))
        offsets = np.searchsorted(index_dates, dates, side="right") - 1
        valid = offsets >= 0
        idx_open[:] = np.nan
        idx_open[valid] = index_opens[offsets[valid]]
        per_horizon: dict[int, np.ndarray] = {}
        for horizon in HORIZONS:
            fwd = np.full(len(dates), np.nan)
            if len(dates) > horizon:
                stock = opens[horizon:] / opens[:-horizon] - 1.0
                bench = idx_open[horizon:] / idx_open[:-horizon] - 1.0
                fwd[: len(dates) - horizon] = stock - bench
            per_horizon[horizon] = fwd
        result[code] = per_horizon
    return result


def main() -> None:
    rng = np.random.default_rng(SEED)
    events = load_events()
    codes = set(events["code"])
    code_bars = load_bars(codes)
    index_dates, index_opens = load_index_opens()
    forward_excess = build_forward_excess(code_bars, index_dates, index_opens)
    print(
        f"loaded events={len(events)} codes={len(code_bars)}",
        flush=True,
    )

    # Locate the entry bar and executability for every event once.
    entry_records: dict[tuple[str, str, int], dict[str, list]] = defaultdict(
        lambda: defaultdict(list)
    )
    total_counts: dict[tuple[str, str, int, str], int] = defaultdict(int)
    blocked_counts: dict[tuple[str, str, int, str], int] = defaultdict(int)

    for row in events.itertuples(index=False):
        direction = int(row.direction)
        trigger = str(row.primary_trigger_semantic)
        split = str(row.split_id)
        cell_key = (str(row.model_code), trigger, direction)
        total_counts[(*cell_key, split)] += 1
        bar_data = code_bars.get(row.code)
        if bar_data is None:
            blocked_counts[(*cell_key, split)] += 1
            continue
        dates, opens, closes = bar_data
        reveal = row.reveal_date.to_datetime64()
        entry_index = int(np.searchsorted(dates, reveal, side="right"))
        if entry_index >= len(dates) or entry_index == 0:
            blocked_counts[(*cell_key, split)] += 1
            continue
        entry_open = float(opens[entry_index])
        prior_close = float(closes[entry_index - 1])
        if not (np.isfinite(entry_open) and entry_open > 0 and prior_close > 0):
            blocked_counts[(*cell_key, split)] += 1
            continue
        move = entry_open / prior_close - 1.0
        if direction == 1 and move > LIMIT_MOVE:
            blocked_counts[(*cell_key, split)] += 1
            continue
        if direction == -1 and move < -LIMIT_MOVE:
            blocked_counts[(*cell_key, split)] += 1
            continue
        bucket = entry_records[cell_key][split]
        bucket.append((row.code, entry_index, int(str(reveal)[:4])))

    # Same-pool random-date control needs, per code, the bar indexes with a
    # finite primary-horizon excess return.
    valid_index_cache: dict[str, np.ndarray] = {}

    def valid_indexes(code: str) -> np.ndarray:
        cached = valid_index_cache.get(code)
        if cached is None:
            fwd = forward_excess[code][PRIMARY_HORIZON]
            cached = np.flatnonzero(np.isfinite(fwd))
            valid_index_cache[code] = cached
        return cached

    cells: list[dict] = []
    for (model_code, trigger, direction), split_map in sorted(entry_records.items()):
        cell_id = f"{model_code}|{trigger}|{direction:+d}"
        splits_out: dict[str, dict] = {}
        for split, records in split_map.items():
            if split not in SPLIT_YEARS or not records:
                continue
            record_codes = [item[0] for item in records]
            entry_idx = np.array([item[1] for item in records], dtype=int)
            years = np.array([item[2] for item in records], dtype=int)

            sign = 1.0 if direction == 1 else -1.0
            returns_by_horizon: dict[int, np.ndarray] = {}
            for horizon in HORIZONS:
                values = np.array(
                    [
                        forward_excess[code][horizon][idx]
                        for code, idx in zip(record_codes, entry_idx)
                    ]
                )
                returns_by_horizon[horizon] = sign * values

            primary = returns_by_horizon[PRIMARY_HORIZON]
            finite = np.isfinite(primary)
            sample = primary[finite]
            sample_years = years[finite]
            n_exec = int(len(sample))
            key = (model_code, trigger, direction, split)
            n_total = int(total_counts[key])
            stats: dict = {
                "n_total": n_total,
                "n_blocked": int(blocked_counts[key]),
                "n_executable": n_exec,
                "execution_rate": round(n_exec / n_total, 6) if n_total else None,
            }
            if n_exec >= MIN_CELL_STAT_N:
                mean = float(np.mean(sample))
                std = float(np.std(sample, ddof=1))
                t_stat = mean / (std / math.sqrt(n_exec)) if std > 0 else 0.0
                yearly = {
                    str(year): round(float(np.mean(sample[sample_years == year])), 6)
                    for year in sorted(set(sample_years.tolist()))
                }
                yearly_values = list(yearly.values())
                decay = {}
                for horizon in HORIZONS:
                    horizon_sample = returns_by_horizon[horizon]
                    horizon_sample = horizon_sample[np.isfinite(horizon_sample)]
                    decay[str(horizon)] = (
                        round(float(np.mean(horizon_sample)), 6)
                        if len(horizon_sample)
                        else None
                    )
                stats.update(
                    {
                        "mean_excess": round(mean, 6),
                        "median_excess": round(float(np.median(sample)), 6),
                        "std_excess": round(std, 6),
                        "win_rate": round(float(np.mean(sample > 0)), 6),
                        "t_stat": round(t_stat, 4),
                        "p_value": round(normal_two_sided_p(t_stat), 8),
                        "net_mean_excess": round(mean - ROUND_TRIP_COST, 6),
                        "information_ratio": round(mean / std, 6) if std > 0 else None,
                        "yearly_mean_excess": yearly,
                        "worst_year_mean": round(min(yearly_values), 6),
                        "positive_year_ratio": round(
                            sum(1 for v in yearly_values if v > 0) / len(yearly_values),
                            6,
                        ),
                        "horizon_decay": decay,
                    }
                )

                if n_exec >= MIN_BOOTSTRAP_N:
                    draw_n = min(n_exec, BOOTSTRAP_SAMPLE_CAP)
                    unique_codes = sorted(set(record_codes))
                    pools = [valid_indexes(code) for code in unique_codes]
                    pool_ok = [
                        (code, pool)
                        for code, pool in zip(unique_codes, pools)
                        if len(pool)
                    ]
                    if pool_ok:
                        means = np.empty(BOOTSTRAP_REPS)
                        for rep in range(BOOTSTRAP_REPS):
                            code_pick = rng.integers(0, len(pool_ok), draw_n)
                            values = np.empty(draw_n)
                            for j, code_offset in enumerate(code_pick):
                                code, pool = pool_ok[code_offset]
                                bar = pool[rng.integers(0, len(pool))]
                                values[j] = forward_excess[code][PRIMARY_HORIZON][bar]
                            means[rep] = sign * float(np.mean(values))
                        stats["random_pool_control"] = {
                            "reps": BOOTSTRAP_REPS,
                            "draw_n": draw_n,
                            "control_mean": round(float(np.mean(means)), 6),
                            "percentile": round(float(np.mean(mean > means)), 6),
                        }

                    exec_codes = [code for code, ok in zip(record_codes, finite) if ok]
                    exec_idx = entry_idx[finite]
                    shift_means = []
                    for _rep in range(SHIFT_REPS):
                        offsets = rng.integers(
                            SHIFT_RANGE[0], SHIFT_RANGE[1] + 1, draw_n
                        ) * rng.choice([-1, 1], draw_n)
                        pick = rng.integers(0, n_exec, draw_n)
                        shift_values: list[float] = []
                        for j in range(draw_n):
                            code = exec_codes[pick[j]]
                            shifted = int(exec_idx[pick[j]]) + int(offsets[j])
                            fwd = forward_excess[code][PRIMARY_HORIZON]
                            if 0 <= shifted < len(fwd) and np.isfinite(fwd[shifted]):
                                shift_values.append(sign * float(fwd[shifted]))
                        if shift_values:
                            shift_means.append(float(np.mean(shift_values)))
                    if shift_means:
                        shift_arr = np.array(shift_means)
                        stats["date_shift_control"] = {
                            "reps": len(shift_means),
                            "draw_n": draw_n,
                            "control_mean": round(float(np.mean(shift_arr)), 6),
                            "percentile": round(float(np.mean(mean > shift_arr)), 6),
                        }
            splits_out[split] = stats
        cells.append(
            {
                "cell_id": cell_id,
                "model_code": model_code,
                "model_id": int(model_code[1:]),
                "trigger": trigger,
                "direction": direction,
                "splits": splits_out,
            }
        )

    # BH-FDR within each split over cells that produced a p-value.
    for split in SPLIT_YEARS:
        indexed = [
            (i, cell_doc["splits"][split]["p_value"])
            for i, cell_doc in enumerate(cells)
            if split in cell_doc["splits"] and "p_value" in cell_doc["splits"][split]
        ]
        if not indexed:
            continue
        q_values = benjamini_hochberg([p for _, p in indexed])
        for (i, _), q in zip(indexed, q_values):
            cells[i]["splits"][split]["fdr_q_value"] = round(q, 8)

    # Qualification is pre-registered in QUALIFY and uses TRAIN for the
    # thresholds with a VALIDATION sign confirmation.
    for cell_doc in cells:
        train = cell_doc["splits"].get("TRAIN", {})
        validation = cell_doc["splits"].get("VALIDATION", {})
        checks = {
            "train_fdr": train.get("fdr_q_value") is not None
            and train["fdr_q_value"] < QUALIFY["fdr_q_max"],
            "train_samples": train.get("n_executable", 0)
            >= QUALIFY["min_train_executable"],
            "validation_samples": validation.get("n_executable", 0)
            >= QUALIFY["min_validation_executable"],
            "validation_sign": (
                train.get("mean_excess") is not None
                and validation.get("mean_excess") is not None
                and train["mean_excess"] * validation["mean_excess"] > 0
            ),
            "net_positive": (train.get("net_mean_excess") or 0) > 0,
            "mean_excess_floor": (train.get("mean_excess") or 0)
            >= QUALIFY["min_mean_excess"],
            "worst_year": train.get("worst_year_mean") is not None
            and train["worst_year_mean"] > QUALIFY["worst_year_floor"],
            "year_stability": (train.get("positive_year_ratio") or 0)
            >= QUALIFY["min_positive_year_ratio"],
            "beats_random_pool": (
                train.get("random_pool_control", {}).get("percentile") or 0
            )
            >= QUALIFY["control_percentile_min"],
            "beats_date_shift": (
                train.get("date_shift_control", {}).get("percentile") or 0
            )
            >= QUALIFY["control_percentile_min"],
        }
        qualified = all(checks.values())
        watch = (
            not qualified
            and checks["validation_sign"]
            and train.get("fdr_q_value") is not None
            and train["fdr_q_value"] < QUALIFY["watch_fdr_q_max"]
            and checks["train_samples"]
        )
        cell_doc["qualification"] = {
            "status": "CORE" if qualified else "WATCH" if watch else "REJECTED",
            "checks": checks,
        }

    status_counts: dict[str, int] = defaultdict(int)
    for cell_doc in cells:
        status_counts[cell_doc["qualification"]["status"]] += 1

    output = {
        "schema_version": "1.0",
        "run_id": RUN_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": {
            "primary_horizon": PRIMARY_HORIZON,
            "horizons": list(HORIZONS),
            "entry": "next session raw open after reveal (T+1 open)",
            "exit": "T+1+horizon open (open-to-open)",
            "benchmark": "SH index 000001 open-to-open same window",
            "excess_definition": "stock_return - index_return",
            "direction_minus_one": "evaluated as negated excess (predictive only)",
            "limit_filter": f"entry blocked when |open/prev_close-1| > {LIMIT_MOVE}",
            "round_trip_cost": ROUND_TRIP_COST,
            "splits": {k: list(v) for k, v in SPLIT_YEARS.items()},
            "fdr": "Benjamini-Hochberg within split across cells",
            "controls": {
                "random_pool": {
                    "reps": BOOTSTRAP_REPS,
                    "sample_cap": BOOTSTRAP_SAMPLE_CAP,
                    "min_n": MIN_BOOTSTRAP_N,
                },
                "date_shift": {
                    "reps": SHIFT_REPS,
                    "shift_range_days": list(SHIFT_RANGE),
                },
            },
            "qualification": QUALIFY,
            "seed": SEED,
            "holdout_note": (
                "HOLDOUT stats are computed for completeness; treat them as "
                "confirmation only, never for selection."
            ),
        },
        "status_counts": dict(status_counts),
        "cell_count": len(cells),
        "cells": cells,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"wrote={OUTPUT_PATH} cells={len(cells)}", flush=True)


if __name__ == "__main__":
    main()
