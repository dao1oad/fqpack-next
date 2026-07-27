# -*- coding: utf-8 -*-
"""Build a causal candidate table for CLX model x primary-trigger research.

The default invocation reads TRAIN and VALIDATION only (2005-2023).  HOLDOUT is
materialized separately after the development winner has been frozen.
"""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pymongo

EVENT_GLOB = (
    "/opt/clx-backtest/events/clx-preview-99634853b/event-study/"
    "code_buckets/code_bucket=*/event_outcomes/reveal_year=*/part-*.parquet"
)
SNAPSHOT_ROOT = (
    "/opt/clx-backtest/snapshots/"
    "cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4/"
    "bars"
)
START_YEAR = int(os.environ.get("CLX_START_YEAR", "2005"))
END_YEAR = int(os.environ.get("CLX_END_YEAR", "2023"))
OUTPUT_PATH = Path(
    os.environ.get(
        "CLX_CANDIDATE_OUTPUT",
        "/tmp/clx_trigger_filter_dev_candidates.parquet",
    )
)
SUMMARY_PATH = Path(
    os.environ.get(
        "CLX_CANDIDATE_SUMMARY",
        "/tmp/clx_trigger_filter_dev_candidates.summary.json",
    )
)

EVENT_COLUMNS = [
    "code",
    "model_code",
    "direction",
    "reveal_date",
    "revision_no",
    "occurrence",
    "primary_entrypoint",
    "primary_trigger_semantic",
    "concurrent_trigger_mask",
    "dedup_group_size",
    "entry_status",
    "split_id",
    "split_boundary_status",
    "quality_mask",
]
BAR_COLUMNS = [
    "code",
    "trade_date",
    "qfq_open",
    "qfq_high",
    "qfq_low",
    "qfq_close",
    "raw_open",
    "raw_amount",
]
HOLD_DAYS = (5, 10, 15, 20, 30)


def _bit_count(values: np.ndarray) -> np.ndarray:
    return np.fromiter(
        (int(value).bit_count() for value in values),
        dtype=np.int16,
        count=len(values),
    )


def load_events() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for filename in sorted(glob.glob(EVENT_GLOB)):
        year = int(filename.split("reveal_year=")[1].split("/")[0])
        if START_YEAR <= year <= END_YEAR:
            frames.append(pd.read_parquet(filename, columns=EVENT_COLUMNS))
    if not frames:
        raise RuntimeError(f"no event rows for {START_YEAR}-{END_YEAR}")
    events = pd.concat(frames, ignore_index=True)
    events = events[
        (events["split_boundary_status"] == "ELIGIBLE")
        & (events["entry_status"] == "EXECUTABLE")
    ].copy()
    events["reveal_date"] = pd.to_datetime(events["reveal_date"].astype(str))
    events = events.sort_values(
        ["code", "model_code", "direction", "reveal_date", "revision_no"]
    ).drop_duplicates(
        ["code", "model_code", "direction", "reveal_date"],
        keep="last",
    )
    return events


def load_bars(codes: set[str]) -> dict[str, tuple[np.ndarray, ...]]:
    dataset = ds.dataset(SNAPSHOT_ROOT, format="parquet")
    table = dataset.to_table(
        columns=BAR_COLUMNS,
        filter=(ds.field("trade_year") >= START_YEAR - 1)
        & (ds.field("trade_year") <= END_YEAR + 1),
    )
    bars = table.to_pandas()
    bars = bars[bars["code"].isin(codes)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"].astype(str))
    bars = bars.sort_values(["code", "trade_date"])
    result: dict[str, tuple[np.ndarray, ...]] = {}
    for code, frame in bars.groupby("code", sort=False):
        result[code] = (
            frame["trade_date"].values.astype("datetime64[ns]"),
            frame["qfq_open"].to_numpy(dtype=float),
            frame["qfq_high"].to_numpy(dtype=float),
            frame["qfq_low"].to_numpy(dtype=float),
            frame["qfq_close"].to_numpy(dtype=float),
            frame["raw_open"].to_numpy(dtype=float),
            frame["raw_amount"].to_numpy(dtype=float),
        )
    return result


def load_index() -> pd.DataFrame:
    client = pymongo.MongoClient(
        "mongodb://fq_mongodb:27017",
        serverSelectionTimeoutMS=5_000,
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
    index["close"] = pd.to_numeric(index["close"], errors="coerce")
    index["market_return_20"] = index["close"].pct_change(20)
    index["market_return_60"] = index["close"].pct_change(60)
    index["market_above_ma60"] = index["close"] / index["close"].rolling(60).mean() - 1
    return index.dropna(subset=["close"])


def daily_signal_features(
    events: pd.DataFrame,
    index_dates: pd.Series,
) -> tuple[
    dict[np.datetime64, tuple[float, float, float, float]],
    pd.Series,
]:
    buys = events[events["direction"] == 1]
    sells = events[events["direction"] == -1]
    buy_counts = buys.groupby("reveal_date").size()
    sell_counts = sells.groupby("reveal_date").size()
    frame = pd.DataFrame({"reveal_date": index_dates}).drop_duplicates()
    frame = frame.set_index("reveal_date").sort_index()
    frame["market_buy_count"] = buy_counts.reindex(frame.index, fill_value=0)
    frame["market_sell_count"] = sell_counts.reindex(frame.index, fill_value=0)
    for name in ("market_buy_count", "market_sell_count"):
        past = frame[name].shift(1)
        mean = past.rolling(252, min_periods=60).mean()
        std = past.rolling(252, min_periods=60).std().replace(0, np.nan)
        frame[f"{name}_z252"] = (frame[name] - mean) / std
    mapping = {
        date.to_datetime64(): (
            float(row.market_buy_count),
            float(row.market_sell_count),
            float(row.market_buy_count_z252),
            float(row.market_sell_count_z252),
        )
        for date, row in frame.iterrows()
    }
    consensus = buys.groupby(["code", "reveal_date"])["model_code"].nunique()
    return mapping, consensus


def confirmed_fractal_stops(lows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if len(lows) < 5:
        return np.array([], dtype=int), np.array([], dtype=float)
    centers = np.arange(2, len(lows) - 2)
    windows = np.lib.stride_tricks.sliding_window_view(lows, 5)
    is_bottom = lows[centers] == windows.min(axis=1)
    bottom_centers = centers[is_bottom]
    return bottom_centers + 2, lows[bottom_centers]


def stock_feature_arrays(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    amounts: np.ndarray,
) -> dict[str, np.ndarray]:
    close_series = pd.Series(closes)
    returns = close_series.pct_change(fill_method=None)
    previous = close_series.shift(1)
    true_range = pd.concat(
        [
            pd.Series(highs - lows),
            (pd.Series(highs) - previous).abs(),
            (pd.Series(lows) - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    rolling_high20 = close_series.rolling(20).max()
    return {
        "stock_return_5": close_series.pct_change(
            5,
            fill_method=None,
        ).to_numpy(),
        "stock_return_20": close_series.pct_change(
            20,
            fill_method=None,
        ).to_numpy(),
        "stock_return_60": close_series.pct_change(
            60,
            fill_method=None,
        ).to_numpy(),
        "stock_volatility_20": returns.rolling(20).std().to_numpy(),
        "stock_atr_20": (true_range.rolling(20).mean() / close_series).to_numpy(),
        "stock_drawdown_20": (close_series / rolling_high20 - 1).to_numpy(),
        "stock_above_ma20": (
            close_series / close_series.rolling(20).mean() - 1
        ).to_numpy(),
        "stock_above_ma60": (
            close_series / close_series.rolling(60).mean() - 1
        ).to_numpy(),
        "amount_median_20": pd.Series(amounts).rolling(20).median().shift(1).to_numpy(),
    }


def build_candidates(
    events: pd.DataFrame,
    code_bars: dict[str, tuple[np.ndarray, ...]],
    index: pd.DataFrame,
) -> pd.DataFrame:
    index_dates = index["date"].values.astype("datetime64[ns]")
    index_features = {
        date: (
            float(ret20),
            float(ret60),
            float(above),
        )
        for date, ret20, ret60, above in zip(
            index_dates,
            index["market_return_20"],
            index["market_return_60"],
            index["market_above_ma60"],
            strict=True,
        )
    }
    daily_map, consensus = daily_signal_features(events, index["date"])
    sells = events[events["direction"] == -1][["code", "reveal_date"]]
    sell_map = {
        code: np.sort(frame["reveal_date"].values.astype("datetime64[ns]"))
        for code, frame in sells.groupby("code", sort=False)
    }
    buys = events[events["direction"] == 1].copy()
    buys["same_code_model_count"] = [
        int(consensus.get((code, reveal_date), 1))
        for code, reveal_date in zip(
            buys["code"],
            buys["reveal_date"],
            strict=True,
        )
    ]

    rows: list[pd.DataFrame] = []
    for code, frame in buys.groupby("code", sort=False):
        bars = code_bars.get(code)
        if bars is None:
            continue
        (
            dates,
            opens,
            highs,
            lows,
            closes,
            raw_opens,
            amounts,
        ) = bars
        feature_arrays = stock_feature_arrays(highs, lows, closes, amounts)
        confirmations, stop_values = confirmed_fractal_stops(lows)
        reveal_dates = frame["reveal_date"].values.astype("datetime64[ns]")
        entry_indexes = np.searchsorted(dates, reveal_dates, side="right")
        valid = entry_indexes < len(dates)
        if not valid.any():
            continue
        frame = frame.iloc[np.flatnonzero(valid)].copy()
        reveal_dates = reveal_dates[valid]
        entry_indexes = entry_indexes[valid]
        reveal_indexes = np.searchsorted(dates, reveal_dates, side="right") - 1

        result = frame[
            [
                "code",
                "model_code",
                "reveal_date",
                "occurrence",
                "primary_entrypoint",
                "primary_trigger_semantic",
                "concurrent_trigger_mask",
                "dedup_group_size",
                "quality_mask",
                "same_code_model_count",
                "split_id",
            ]
        ].reset_index(drop=True)
        result["entry_date"] = dates[entry_indexes]
        result["entry_index"] = entry_indexes
        result["qfq_entry_open"] = opens[entry_indexes]
        result["raw_entry_open"] = raw_opens[entry_indexes]
        result["entry_gap"] = np.where(
            entry_indexes > 0,
            opens[entry_indexes] / closes[np.maximum(entry_indexes - 1, 0)] - 1,
            np.nan,
        )
        result["concurrent_trigger_count"] = _bit_count(
            result["concurrent_trigger_mask"].to_numpy(dtype=np.int64)
        )
        for name, values in feature_arrays.items():
            result[name] = values[reveal_indexes]

        stop_indexes = (
            np.searchsorted(
                confirmations,
                reveal_indexes,
                side="right",
            )
            - 1
        )
        stop_prices = np.full(len(result), np.nan)
        has_stop = stop_indexes >= 0
        stop_prices[has_stop] = stop_values[stop_indexes[has_stop]]
        result["structural_stop_price"] = stop_prices
        result["structural_stop_distance"] = 1 - stop_prices / result[
            "qfq_entry_open"
        ].to_numpy(dtype=float)

        market_rows = np.searchsorted(index_dates, reveal_dates, side="right") - 1
        market_values = [
            (
                index_features.get(index_dates[offset], (np.nan, np.nan, np.nan))
                if offset >= 0
                else (np.nan, np.nan, np.nan)
            )
            for offset in market_rows
        ]
        result[
            [
                "market_return_20",
                "market_return_60",
                "market_above_ma60",
            ]
        ] = np.asarray(market_values)
        signal_values = [
            daily_map.get(date, (np.nan, np.nan, np.nan, np.nan))
            for date in reveal_dates
        ]
        result[
            [
                "market_buy_count",
                "market_sell_count",
                "market_buy_count_z252",
                "market_sell_count_z252",
            ]
        ] = np.asarray(signal_values)

        for hold in HOLD_DAYS:
            exit_indexes = entry_indexes + hold
            executable = exit_indexes < len(dates)
            exit_dates = np.full(
                len(result), np.datetime64("NaT"), dtype="datetime64[ns]"
            )
            exit_opens = np.full(len(result), np.nan)
            exit_gaps = np.full(len(result), np.nan)
            exit_dates[executable] = dates[exit_indexes[executable]]
            exit_opens[executable] = opens[exit_indexes[executable]]
            prior_indexes = exit_indexes[executable] - 1
            valid_prior = prior_indexes >= 0
            target_rows = np.flatnonzero(executable)
            exit_gaps[target_rows[valid_prior]] = (
                opens[exit_indexes[executable][valid_prior]]
                / closes[prior_indexes[valid_prior]]
                - 1
            )
            result[f"hold{hold}_exit_date"] = exit_dates
            result[f"hold{hold}_exit_open"] = exit_opens
            result[f"hold{hold}_exit_gap"] = exit_gaps
            result[f"hold{hold}_gross_return"] = (
                exit_opens / result["qfq_entry_open"].to_numpy(dtype=float) - 1
            )

        sell_dates = sell_map.get(code)
        signal_exit_dates = np.full(
            len(result),
            np.datetime64("NaT"),
            dtype="datetime64[ns]",
        )
        signal_exit_opens = np.full(len(result), np.nan)
        signal_exit_gaps = np.full(len(result), np.nan)
        if sell_dates is not None and len(sell_dates):
            sell_offsets = np.searchsorted(sell_dates, reveal_dates, side="right")
            has_sell = sell_offsets < len(sell_dates)
            sell_reveals = np.full(
                len(result),
                np.datetime64("NaT"),
                dtype="datetime64[ns]",
            )
            sell_reveals[has_sell] = sell_dates[sell_offsets[has_sell]]
            sell_entry_indexes = np.searchsorted(
                dates,
                sell_reveals[has_sell],
                side="right",
            )
            sell_entry_indexes = np.maximum(
                sell_entry_indexes,
                entry_indexes[has_sell] + 1,
            )
            executable = sell_entry_indexes < len(dates)
            target_rows = np.flatnonzero(has_sell)[executable]
            target_indexes = sell_entry_indexes[executable]
            signal_exit_dates[target_rows] = dates[target_indexes]
            signal_exit_opens[target_rows] = opens[target_indexes]
            valid_prior = target_indexes > 0
            signal_exit_gaps[target_rows[valid_prior]] = (
                opens[target_indexes[valid_prior]]
                / closes[target_indexes[valid_prior] - 1]
                - 1
            )
        result["signal_exit_date"] = signal_exit_dates
        result["signal_exit_open"] = signal_exit_opens
        result["signal_exit_gap"] = signal_exit_gaps
        result["signal_gross_return"] = (
            signal_exit_opens / result["qfq_entry_open"].to_numpy(dtype=float) - 1
        )
        rows.append(result)

    candidates = pd.concat(rows, ignore_index=True)
    candidates["strategy_id"] = (
        candidates["model_code"] + "|" + candidates["primary_trigger_semantic"]
    )
    candidates = candidates.replace([np.inf, -np.inf], np.nan)
    return candidates.sort_values(
        ["entry_date", "strategy_id", "code", "reveal_date"]
    ).reset_index(drop=True)


def main() -> None:
    print(f"loading events {START_YEAR}-{END_YEAR}", flush=True)
    events = load_events()
    print(f"events={len(events):,}", flush=True)
    codes = set(events["code"].astype(str))
    print(f"loading bars codes={len(codes):,}", flush=True)
    bars = load_bars(codes)
    index = load_index()
    print("building candidates", flush=True)
    candidates = build_candidates(events, bars, index)
    table = pa.Table.from_pandas(candidates, preserve_index=False)
    pq.write_table(
        table,
        OUTPUT_PATH,
        compression="zstd",
        row_group_size=100_000,
    )
    group_counts = (
        candidates.groupby(["strategy_id", "split_id"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
        .to_dict(orient="records")
    )
    summary = {
        "run_id": "01KBYC7REC0V3RY99634853AAB",
        "period": [START_YEAR, END_YEAR],
        "rows": len(candidates),
        "codes": int(candidates["code"].nunique()),
        "strategy_groups": int(candidates["strategy_id"].nunique()),
        "group_counts": group_counts,
        "output_path": str(OUTPUT_PATH),
    }
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
