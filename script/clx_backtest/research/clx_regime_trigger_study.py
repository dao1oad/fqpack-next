# -*- coding: utf-8 -*-
"""Study ENGULFING/STRONG_FRACTAL CLX signals by causal SH-index regime.

The input candidate tables are produced by
``build_trigger_filter_candidates.py`` and contain only information available
on or before each signal's reveal date.  This script:

1. classifies the Shanghai Composite into causal UP/DOWN/SIDEWAYS regimes;
2. keeps the ENGULFING and STRONG_FRACTAL bits from the concurrent-trigger
   mask for all S0000-S0017 models;
3. measures fee-adjusted win rates at 30/60/90 stock-session exits; and
4. searches a deliberately small library of one- and two-condition filters on
   2005-2019, selects on 2020-2023, then reports 2024-2026 once.

QFQ opens are used for total-return approximation.  Raw prices are used only
for entry/exit limit-move executability checks.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pymongo

RUN_ID = "01KBYC7REC0V3RY99634853AAB"
STUDY_ID = "clx-regime-trigger-v1"
MODEL_CODES = tuple(f"S{model_id:04d}" for model_id in range(18))
TARGET_TRIGGER_BITS = {
    "ENGULFING": 1 << (3 - 1),
    "STRONG_FRACTAL": 1 << (4 - 1),
}
REGIMES = ("UP", "DOWN", "SIDEWAYS")
HORIZONS = (30, 60, 90)
FEE_PER_SIDE = 0.002
LIMIT_MOVE = 0.095
REGIME_LOOKBACK = 60
REGIME_RETURN_THRESHOLD = 0.05
REGIME_CONFIRMATION_SESSIONS = 5

DEFAULT_CANDIDATE_PATHS = (
    Path("/tmp/clx_trigger_filter_dev_candidates.parquet"),
    Path("/tmp/clx_trigger_filter_holdout_candidates.parquet"),
)
DEFAULT_SNAPSHOT_ROOT = Path(
    "/opt/clx-backtest/snapshots/"
    "cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4/"
    "bars"
)
DEFAULT_OUTPUT_DIR = Path(f"/opt/clx-backtest/studies/{STUDY_ID}")

CANDIDATE_COLUMNS = [
    "code",
    "model_code",
    "reveal_date",
    "occurrence",
    "primary_trigger_semantic",
    "concurrent_trigger_mask",
    "dedup_group_size",
    "quality_mask",
    "same_code_model_count",
    "split_id",
    "entry_date",
    "qfq_entry_open",
    "raw_entry_open",
    "entry_gap",
    "concurrent_trigger_count",
    "stock_return_5",
    "stock_return_20",
    "stock_return_60",
    "stock_volatility_20",
    "stock_atr_20",
    "stock_drawdown_20",
    "stock_above_ma20",
    "stock_above_ma60",
    "amount_median_20",
    "structural_stop_distance",
    "market_return_20",
    "market_return_60",
    "market_above_ma60",
    "market_buy_count_z252",
    "market_sell_count_z252",
]


@dataclass(frozen=True)
class FilterRule:
    name: str
    label: str
    family: str
    predicate: Callable[[pd.DataFrame], pd.Series]


def _finite(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)


FILTER_RULES = (
    FilterRule(
        "regime_up",
        "上证上涨阶段",
        "regime",
        lambda frame: frame["market_regime"].eq("UP"),
    ),
    FilterRule(
        "regime_down",
        "上证下跌阶段",
        "regime",
        lambda frame: frame["market_regime"].eq("DOWN"),
    ),
    FilterRule(
        "regime_sideways",
        "上证震荡阶段",
        "regime",
        lambda frame: frame["market_regime"].eq("SIDEWAYS"),
    ),
    FilterRule(
        "occurrence_eq_1",
        "模型内第1次信号",
        "occurrence",
        lambda frame: frame["occurrence"].eq(1),
    ),
    FilterRule(
        "occurrence_le_2",
        "模型内发生次数≤2",
        "occurrence",
        lambda frame: frame["occurrence"].le(2),
    ),
    FilterRule(
        "occurrence_ge_2",
        "模型内发生次数≥2",
        "occurrence",
        lambda frame: frame["occurrence"].ge(2),
    ),
    FilterRule(
        "same_code_models_ge_2",
        "同股同日模型共识≥2",
        "model_consensus",
        lambda frame: frame["same_code_model_count"].ge(2),
    ),
    FilterRule(
        "same_code_models_ge_3",
        "同股同日模型共识≥3",
        "model_consensus",
        lambda frame: frame["same_code_model_count"].ge(3),
    ),
    FilterRule(
        "same_code_models_ge_4",
        "同股同日模型共识≥4",
        "model_consensus",
        lambda frame: frame["same_code_model_count"].ge(4),
    ),
    FilterRule(
        "both_target_patterns",
        "吞没与强分型同K线共振",
        "target_concurrence",
        lambda frame: (
            frame["concurrent_trigger_mask"].astype("int64")
            & sum(TARGET_TRIGGER_BITS.values())
        ).eq(sum(TARGET_TRIGGER_BITS.values())),
    ),
    FilterRule(
        "concurrent_ge_2",
        "同K线触发条件数≥2",
        "concurrent_count",
        lambda frame: frame["concurrent_trigger_count"].ge(2),
    ),
    FilterRule(
        "concurrent_ge_3",
        "同K线触发条件数≥3",
        "concurrent_count",
        lambda frame: frame["concurrent_trigger_count"].ge(3),
    ),
    FilterRule(
        "entry_gap_nonpositive",
        "次日开盘不高开",
        "entry_gap",
        lambda frame: _finite(frame["raw_entry_gap"]).le(0),
    ),
    FilterRule(
        "entry_gap_le_3pct",
        "次日开盘涨幅≤3%",
        "entry_gap",
        lambda frame: _finite(frame["raw_entry_gap"]).le(0.03),
    ),
    FilterRule(
        "price_1_6",
        "入场原始价1～6元",
        "price",
        lambda frame: _finite(frame["raw_entry_open"]).between(1, 6),
    ),
    FilterRule(
        "price_2_8",
        "入场原始价2～8元",
        "price",
        lambda frame: _finite(frame["raw_entry_open"]).between(2, 8),
    ),
    FilterRule(
        "price_3_10",
        "入场原始价3～10元",
        "price",
        lambda frame: _finite(frame["raw_entry_open"]).between(3, 10),
    ),
    FilterRule(
        "price_le_20",
        "入场原始价≤20元",
        "price",
        lambda frame: _finite(frame["raw_entry_open"]).le(20),
    ),
    FilterRule(
        "stock20_neg",
        "个股近20日收益≤0",
        "stock_momentum_20",
        lambda frame: _finite(frame["stock_return_20"]).le(0),
    ),
    FilterRule(
        "stock20_pullback_10",
        "个股近20日收益≤-10%",
        "stock_momentum_20",
        lambda frame: _finite(frame["stock_return_20"]).le(-0.10),
    ),
    FilterRule(
        "stock20_pos",
        "个股近20日收益>0",
        "stock_momentum_20",
        lambda frame: _finite(frame["stock_return_20"]).gt(0),
    ),
    FilterRule(
        "stock60_neg",
        "个股近60日收益≤0",
        "stock_momentum_60",
        lambda frame: _finite(frame["stock_return_60"]).le(0),
    ),
    FilterRule(
        "stock60_pos",
        "个股近60日收益>0",
        "stock_momentum_60",
        lambda frame: _finite(frame["stock_return_60"]).gt(0),
    ),
    FilterRule(
        "drawdown20_ge_10pct",
        "距近20日高点回撤≥10%",
        "drawdown",
        lambda frame: _finite(frame["stock_drawdown_20"]).le(-0.10),
    ),
    FilterRule(
        "drawdown20_ge_15pct",
        "距近20日高点回撤≥15%",
        "drawdown",
        lambda frame: _finite(frame["stock_drawdown_20"]).le(-0.15),
    ),
    FilterRule(
        "vol20_ge_3pct",
        "20日波动率≥3%",
        "volatility",
        lambda frame: _finite(frame["stock_volatility_20"]).ge(0.03),
    ),
    FilterRule(
        "vol20_2_6pct",
        "20日波动率2%～6%",
        "volatility",
        lambda frame: _finite(frame["stock_volatility_20"]).between(0.02, 0.06),
    ),
    FilterRule(
        "vol20_le_4pct",
        "20日波动率≤4%",
        "volatility",
        lambda frame: _finite(frame["stock_volatility_20"]).le(0.04),
    ),
    FilterRule(
        "atr20_2_6pct",
        "20日ATR为2%～6%",
        "atr",
        lambda frame: _finite(frame["stock_atr_20"]).between(0.02, 0.06),
    ),
    FilterRule(
        "below_ma20",
        "个股位于MA20下方",
        "stock_trend",
        lambda frame: _finite(frame["stock_above_ma20"]).le(0),
    ),
    FilterRule(
        "above_ma20",
        "个股位于MA20上方",
        "stock_trend",
        lambda frame: _finite(frame["stock_above_ma20"]).gt(0),
    ),
    FilterRule(
        "below_ma60",
        "个股位于MA60下方",
        "stock_trend",
        lambda frame: _finite(frame["stock_above_ma60"]).le(0),
    ),
    FilterRule(
        "above_ma60",
        "个股位于MA60上方",
        "stock_trend",
        lambda frame: _finite(frame["stock_above_ma60"]).gt(0),
    ),
    FilterRule(
        "amount20_ge_10m",
        "近20日中位成交额≥1000万",
        "liquidity",
        lambda frame: _finite(frame["amount_median_20"]).ge(10_000_000),
    ),
    FilterRule(
        "amount20_ge_30m",
        "近20日中位成交额≥3000万",
        "liquidity",
        lambda frame: _finite(frame["amount_median_20"]).ge(30_000_000),
    ),
    FilterRule(
        "amount20_ge_100m",
        "近20日中位成交额≥1亿",
        "liquidity",
        lambda frame: _finite(frame["amount_median_20"]).ge(100_000_000),
    ),
    FilterRule(
        "stop_distance_4_15pct",
        "结构底距离4%～15%",
        "structure",
        lambda frame: _finite(frame["structural_stop_distance"]).between(0.04, 0.15),
    ),
    FilterRule(
        "market20_pos",
        "上证近20日收益>0",
        "market_short_trend",
        lambda frame: _finite(frame["index_return_20"]).gt(0),
    ),
    FilterRule(
        "market20_neg",
        "上证近20日收益≤0",
        "market_short_trend",
        lambda frame: _finite(frame["index_return_20"]).le(0),
    ),
    FilterRule(
        "market_above_ma200",
        "上证位于MA200上方",
        "market_long_trend",
        lambda frame: _finite(frame["index_above_ma200"]).gt(0),
    ),
    FilterRule(
        "market_below_ma200",
        "上证位于MA200下方",
        "market_long_trend",
        lambda frame: _finite(frame["index_above_ma200"]).le(0),
    ),
    FilterRule(
        "buy_crowding_z_le_0",
        "全市场CLX买入拥挤度≤历史均值",
        "signal_crowding",
        lambda frame: _finite(frame["market_buy_count_z252"]).le(0),
    ),
    FilterRule(
        "sell_crowding_z_le_0",
        "全市场CLX卖出拥挤度≤历史均值",
        "signal_crowding",
        lambda frame: _finite(frame["market_sell_count_z252"]).le(0),
    ),
)
RULE_BY_NAME = {rule.name: rule for rule in FILTER_RULES}


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wilson_interval(
    wins: int, count: int, z: float = 1.959963984540054
) -> tuple[float, float]:
    if count <= 0:
        return float("nan"), float("nan")
    rate = wins / count
    denominator = 1 + z * z / count
    center = (rate + z * z / (2 * count)) / denominator
    radius = (
        z
        * math.sqrt(rate * (1 - rate) / count + z * z / (4 * count * count))
        / denominator
    )
    return center - radius, center + radius


def return_metrics(values: Iterable[float]) -> dict[str, Any]:
    array = np.asarray(list(values), dtype=float)
    array = array[np.isfinite(array)]
    count = len(array)
    if count == 0:
        return {
            "sample_count": 0,
            "win_count": 0,
            "win_rate": None,
            "win_rate_ci_low": None,
            "win_rate_ci_high": None,
            "mean_net_return": None,
            "median_net_return": None,
        }
    wins = int((array > 0).sum())
    ci_low, ci_high = wilson_interval(wins, count)
    return {
        "sample_count": count,
        "win_count": wins,
        "win_rate": round(float(wins / count), 6),
        "win_rate_ci_low": round(float(ci_low), 6),
        "win_rate_ci_high": round(float(ci_high), 6),
        "mean_net_return": round(float(array.mean()), 6),
        "median_net_return": round(float(np.median(array)), 6),
    }


def classify_market_regimes(index: pd.DataFrame) -> pd.DataFrame:
    frame = index.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["date", "close"]).sort_values("date")
    frame = frame.drop_duplicates("date", keep="last").reset_index(drop=True)
    frame["index_return_20"] = frame["close"].pct_change(20, fill_method=None)
    frame["index_return_60"] = frame["close"].pct_change(
        REGIME_LOOKBACK, fill_method=None
    )
    frame["index_return_120"] = frame["close"].pct_change(120, fill_method=None)
    frame["index_ma60"] = frame["close"].rolling(REGIME_LOOKBACK).mean()
    frame["index_ma200"] = frame["close"].rolling(200).mean()
    frame["index_above_ma60"] = frame["close"] / frame["index_ma60"] - 1
    frame["index_above_ma200"] = frame["close"] / frame["index_ma200"] - 1
    frame["raw_market_regime"] = "SIDEWAYS"
    ready = frame["index_return_60"].notna() & frame["index_ma60"].notna()
    frame.loc[~ready, "raw_market_regime"] = "UNKNOWN"
    frame.loc[
        ready
        & frame["index_return_60"].ge(REGIME_RETURN_THRESHOLD)
        & frame["index_above_ma60"].ge(0),
        "raw_market_regime",
    ] = "UP"
    frame.loc[
        ready
        & frame["index_return_60"].le(-REGIME_RETURN_THRESHOLD)
        & frame["index_above_ma60"].le(0),
        "raw_market_regime",
    ] = "DOWN"
    stable_labels: list[str] = []
    current = "UNKNOWN"
    pending = ""
    pending_count = 0
    for raw_label in frame["raw_market_regime"]:
        if raw_label == "UNKNOWN":
            current = "UNKNOWN"
            pending = ""
            pending_count = 0
        elif current == "UNKNOWN":
            current = str(raw_label)
        elif raw_label == current:
            pending = ""
            pending_count = 0
        else:
            if raw_label == pending:
                pending_count += 1
            else:
                pending = str(raw_label)
                pending_count = 1
            if pending_count >= REGIME_CONFIRMATION_SESSIONS:
                current = str(raw_label)
                pending = ""
                pending_count = 0
        stable_labels.append(current)
    frame["market_regime"] = stable_labels
    frame["regime_segment_no"] = (
        frame["market_regime"].ne(frame["market_regime"].shift()).cumsum()
    )
    return frame


def build_market_segments(index: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for segment_no, segment in index.groupby("regime_segment_no", sort=True):
        regime = str(segment["market_regime"].iloc[0])
        if regime == "UNKNOWN":
            continue
        start_close = float(segment["close"].iloc[0])
        end_close = float(segment["close"].iloc[-1])
        rows.append(
            {
                "segment_id": f"{regime}-{int(segment_no):04d}",
                "regime": regime,
                "start_date": segment["date"].iloc[0].date().isoformat(),
                "end_date": segment["date"].iloc[-1].date().isoformat(),
                "sessions": len(segment),
                "start_close": round(start_close, 4),
                "end_close": round(end_close, 4),
                "segment_return": round(end_close / start_close - 1, 6),
            }
        )
    return pd.DataFrame(rows)


def load_index(mongo_uri: str) -> pd.DataFrame:
    client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=5_000)
    records = list(
        client["quantaxis"]["index_day"].find(
            {
                "code": "000001",
                "date": {"$gte": "2004-01-01", "$lte": "2026-12-31"},
            },
            {"_id": 0, "date": 1, "close": 1},
        )
    )
    if not records:
        raise RuntimeError("missing Shanghai Composite 000001 index_day records")
    return classify_market_regimes(pd.DataFrame(records))


def load_target_candidates(paths: tuple[Path, ...]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        frame = pd.read_parquet(path, columns=CANDIDATE_COLUMNS)
        mask = frame["concurrent_trigger_mask"].astype("int64")
        target_mask = np.zeros(len(frame), dtype=bool)
        for bit in TARGET_TRIGGER_BITS.values():
            target_mask |= (mask & bit).ne(0).to_numpy()
        frames.append(frame.loc[target_mask].copy())
    candidates = pd.concat(frames, ignore_index=True)
    candidates["reveal_date"] = pd.to_datetime(candidates["reveal_date"])
    candidates["entry_date"] = pd.to_datetime(candidates["entry_date"])
    candidates = candidates[candidates["model_code"].isin(MODEL_CODES)].drop_duplicates(
        ["code", "model_code", "reveal_date"],
        keep="last",
    )
    expanded: list[pd.DataFrame] = []
    mask = candidates["concurrent_trigger_mask"].astype("int64")
    for trigger, bit in TARGET_TRIGGER_BITS.items():
        selected = candidates.loc[(mask & bit).ne(0)].copy()
        selected["target_trigger"] = trigger
        expanded.append(selected)
    result = pd.concat(expanded, ignore_index=True)
    return result.sort_values(
        ["code", "entry_date", "model_code", "target_trigger"]
    ).reset_index(drop=True)


def attach_market_regimes(events: pd.DataFrame, index: pd.DataFrame) -> pd.DataFrame:
    market_columns = [
        "date",
        "index_return_20",
        "index_return_60",
        "index_return_120",
        "index_above_ma60",
        "index_above_ma200",
        "market_regime",
        "regime_segment_no",
    ]
    left = events.sort_values("reveal_date").copy()
    right = index[market_columns].sort_values("date").copy()
    merged = pd.merge_asof(
        left,
        right,
        left_on="reveal_date",
        right_on="date",
        direction="backward",
        allow_exact_matches=True,
    )
    if (merged["date"] > merged["reveal_date"]).fillna(False).any():
        raise RuntimeError("market regime joined from a future index date")
    merged = merged.rename(columns={"date": "index_feature_date"})
    merged["reveal_year"] = merged["reveal_date"].dt.year.astype("int16")
    return merged.sort_values(
        ["code", "entry_date", "model_code", "target_trigger"]
    ).reset_index(drop=True)


def _advance_past_limit_down(
    raw_opens: np.ndarray,
    raw_closes: np.ndarray,
    planned_index: int,
) -> tuple[int | None, int]:
    exit_index = planned_index
    delay = 0
    while exit_index < len(raw_opens):
        if exit_index <= 0:
            return exit_index, delay
        raw_open = float(raw_opens[exit_index])
        prior_close = float(raw_closes[exit_index - 1])
        if (
            np.isfinite(raw_open)
            and np.isfinite(prior_close)
            and prior_close > 0
            and raw_open / prior_close - 1 <= -LIMIT_MOVE
        ):
            exit_index += 1
            delay += 1
            continue
        return exit_index, delay
    return None, delay


def compute_event_exits(
    *,
    dates: np.ndarray,
    qfq_opens: np.ndarray,
    raw_opens: np.ndarray,
    raw_closes: np.ndarray,
    entry_date: np.datetime64,
) -> dict[str, Any]:
    entry_index = int(np.searchsorted(dates, entry_date))
    result: dict[str, Any] = {
        "entry_executable": False,
        "raw_entry_gap": np.nan,
    }
    if (
        entry_index >= len(dates)
        or dates[entry_index] != entry_date
        or entry_index <= 0
    ):
        for horizon in HORIZONS:
            result[f"h{horizon}_status"] = "MISSING_ENTRY"
        return result
    raw_entry_open = float(raw_opens[entry_index])
    prior_raw_close = float(raw_closes[entry_index - 1])
    qfq_entry_open = float(qfq_opens[entry_index])
    if not (
        np.isfinite(raw_entry_open)
        and np.isfinite(prior_raw_close)
        and prior_raw_close > 0
        and np.isfinite(qfq_entry_open)
        and qfq_entry_open > 0
    ):
        for horizon in HORIZONS:
            result[f"h{horizon}_status"] = "INVALID_ENTRY_PRICE"
        return result
    entry_gap = raw_entry_open / prior_raw_close - 1
    result["raw_entry_gap"] = entry_gap
    if entry_gap > LIMIT_MOVE:
        for horizon in HORIZONS:
            result[f"h{horizon}_status"] = "ENTRY_LIMIT_UP"
        return result
    result["entry_executable"] = True
    for horizon in HORIZONS:
        planned_index = entry_index + horizon
        if planned_index >= len(dates):
            result[f"h{horizon}_status"] = "CENSORED"
            continue
        exit_index, delay = _advance_past_limit_down(
            raw_opens, raw_closes, planned_index
        )
        if exit_index is None:
            result[f"h{horizon}_status"] = "CENSORED_LIMIT_DOWN"
            continue
        qfq_exit_open = float(qfq_opens[exit_index])
        if not np.isfinite(qfq_exit_open) or qfq_exit_open <= 0:
            result[f"h{horizon}_status"] = "INVALID_EXIT_PRICE"
            continue
        gross_return = qfq_exit_open / qfq_entry_open - 1
        net_return = (
            qfq_exit_open * (1 - FEE_PER_SIDE) / (qfq_entry_open * (1 + FEE_PER_SIDE))
            - 1
        )
        result.update(
            {
                f"h{horizon}_status": "OK",
                f"h{horizon}_exit_date": pd.Timestamp(dates[exit_index]),
                f"h{horizon}_exit_delay": delay,
                f"h{horizon}_gross_return": gross_return,
                f"h{horizon}_net_return": net_return,
            }
        )
    return result


def attach_exit_outcomes(
    events: pd.DataFrame,
    snapshot_root: Path,
) -> pd.DataFrame:
    dataset = ds.dataset(snapshot_root, format="parquet")
    table = dataset.to_table(
        columns=[
            "code",
            "trade_date",
            "qfq_open",
            "raw_open",
            "raw_close",
        ],
        filter=(ds.field("trade_year") >= 2004) & (ds.field("trade_year") <= 2026),
    )
    bars = table.to_pandas()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars = bars.sort_values(["code", "trade_date"])
    events = events.copy()
    outcome_rows: list[dict[str, Any]] = []
    outcome_indexes: list[int] = []
    event_groups = events.groupby("code", sort=False).groups
    for code, code_bars in bars.groupby("code", sort=False):
        indexes = event_groups.get(code)
        if indexes is None:
            continue
        dates = code_bars["trade_date"].values.astype("datetime64[ns]")
        qfq_opens = code_bars["qfq_open"].to_numpy(dtype=float)
        raw_opens = code_bars["raw_open"].to_numpy(dtype=float)
        raw_closes = code_bars["raw_close"].to_numpy(dtype=float)
        unique_entry_dates = events.loc[indexes, "entry_date"].drop_duplicates()
        outcomes = {
            date.to_datetime64(): compute_event_exits(
                dates=dates,
                qfq_opens=qfq_opens,
                raw_opens=raw_opens,
                raw_closes=raw_closes,
                entry_date=date.to_datetime64(),
            )
            for date in unique_entry_dates
        }
        for event_index in indexes:
            entry_date = events.at[event_index, "entry_date"].to_datetime64()
            outcome_indexes.append(int(event_index))
            outcome_rows.append(outcomes[entry_date])
    outcome_frame = pd.DataFrame(outcome_rows, index=outcome_indexes)
    missing = events.index.difference(outcome_frame.index)
    if len(missing):
        raise RuntimeError(f"snapshot bars missing for {len(missing)} target events")
    for column in outcome_frame.columns:
        events[column] = outcome_frame[column].reindex(events.index)
    return events


def build_win_rate_table(events: pd.DataFrame) -> pd.DataFrame:
    scopes = {
        "FULL": events["reveal_year"].between(2005, 2026),
        "TRAIN": events["reveal_year"].between(2005, 2019),
        "VALIDATION": events["reveal_year"].between(2020, 2023),
        "HOLDOUT": events["reveal_year"].between(2024, 2026),
    }
    rows: list[dict[str, Any]] = []
    for scope_name, scope_mask in scopes.items():
        scoped = events.loc[scope_mask]
        for model_code, trigger, regime, horizon in itertools.product(
            MODEL_CODES,
            TARGET_TRIGGER_BITS,
            REGIMES,
            HORIZONS,
        ):
            subset = scoped[
                scoped["model_code"].eq(model_code)
                & scoped["target_trigger"].eq(trigger)
                & scoped["market_regime"].eq(regime)
            ]
            valid = subset[f"h{horizon}_status"].eq("OK")
            metrics = return_metrics(
                subset.loc[valid, f"h{horizon}_net_return"].to_numpy(dtype=float)
            )
            rows.append(
                {
                    "scope": scope_name,
                    "model_code": model_code,
                    "trigger": trigger,
                    "market_regime": regime,
                    "horizon_sessions": horizon,
                    "signal_count": len(subset),
                    "entry_executable_count": int(
                        subset["entry_executable"].fillna(False).sum()
                    ),
                    "censored_or_blocked_count": int((~valid).sum()),
                    **metrics,
                }
            )
    return pd.DataFrame(rows)


def _rule_sets() -> list[tuple[str, ...]]:
    singles = [(rule.name,) for rule in FILTER_RULES]
    pairs = [
        (left.name, right.name)
        for left, right in itertools.combinations(FILTER_RULES, 2)
        if left.family != right.family
    ]
    return [(), *singles, *pairs]


def _metrics_from_mask(
    frame: pd.DataFrame,
    mask: np.ndarray,
    horizon: int,
    year_start: int,
    year_end: int,
) -> dict[str, Any]:
    valid = (
        mask
        & frame["reveal_year"].between(year_start, year_end).to_numpy()
        & frame[f"h{horizon}_status"].eq("OK").to_numpy()
    )
    values = frame.loc[valid, f"h{horizon}_net_return"].to_numpy(dtype=float)
    return return_metrics(values)


def _train_score(
    frame: pd.DataFrame,
    mask: np.ndarray,
    horizon: int,
    complexity: int,
) -> tuple[float, dict[str, Any]] | None:
    full = _metrics_from_mask(frame, mask, horizon, 2005, 2019)
    base_count = int(
        (
            frame["reveal_year"].between(2005, 2019)
            & frame[f"h{horizon}_status"].eq("OK")
        ).sum()
    )
    minimum_count = max(60, math.ceil(base_count * 0.05))
    if full["sample_count"] < minimum_count:
        return None
    fold_rates: list[float] = []
    fold_counts: list[int] = []
    for start, end in ((2005, 2009), (2010, 2014), (2015, 2019)):
        fold = _metrics_from_mask(frame, mask, horizon, start, end)
        if fold["sample_count"] >= 10:
            fold_rates.append(float(fold["win_rate"]))
            fold_counts.append(int(fold["sample_count"]))
    if len(fold_rates) < 2:
        return None
    score = (
        0.45 * float(full["win_rate_ci_low"])
        + 0.35 * float(np.mean(fold_rates))
        + 0.20 * float(np.min(fold_rates))
        + 0.20 * float(np.clip(full["mean_net_return"], -0.10, 0.10))
        - 0.004 * complexity
    )
    return score, {
        **full,
        "temporal_fold_win_rates": [round(value, 6) for value in fold_rates],
        "temporal_fold_counts": fold_counts,
    }


def _validation_score(metrics: dict[str, Any], complexity: int) -> float:
    return (
        float(metrics["win_rate_ci_low"])
        + 0.20 * float(np.clip(metrics["mean_net_return"], -0.10, 0.10))
        - 0.004 * complexity
    )


def search_filters(events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    audit: dict[str, Any] = {}
    all_rule_sets = _rule_sets()
    for model_code, trigger in itertools.product(MODEL_CODES, TARGET_TRIGGER_BITS):
        group_id = f"{model_code}|{trigger}"
        frame = events[
            events["model_code"].eq(model_code) & events["target_trigger"].eq(trigger)
        ].reset_index(drop=True)
        rule_masks = {
            rule.name: rule.predicate(frame).fillna(False).to_numpy(dtype=bool)
            for rule in FILTER_RULES
        }
        base_mask = np.ones(len(frame), dtype=bool)
        horizon_shortlists: list[dict[str, Any]] = []
        for horizon in HORIZONS:
            train_candidates: list[dict[str, Any]] = []
            for names in all_rule_sets:
                mask = base_mask.copy()
                for name in names:
                    mask &= rule_masks[name]
                trained = _train_score(frame, mask, horizon, len(names))
                if trained is None:
                    continue
                score, metrics = trained
                train_candidates.append(
                    {
                        "rules": names,
                        "mask": mask,
                        "train_score": score,
                        "train_metrics": metrics,
                    }
                )
            train_candidates.sort(
                key=lambda item: (
                    item["train_score"],
                    -len(item["rules"]),
                    item["rules"],
                ),
                reverse=True,
            )
            shortlist = train_candidates[:12]
            if not any(not item["rules"] for item in shortlist):
                baseline = next(
                    (item for item in train_candidates if not item["rules"]),
                    None,
                )
                if baseline is not None:
                    shortlist.append(baseline)
            baseline_validation = _metrics_from_mask(
                frame, base_mask, horizon, 2020, 2023
            )
            for candidate in shortlist:
                validation = _metrics_from_mask(
                    frame,
                    candidate["mask"],
                    horizon,
                    2020,
                    2023,
                )
                minimum_validation = max(
                    30,
                    math.ceil(baseline_validation["sample_count"] * 0.05),
                )
                if validation["sample_count"] < minimum_validation:
                    continue
                candidate = dict(candidate)
                candidate["horizon"] = horizon
                candidate["validation_metrics"] = validation
                candidate["validation_score"] = _validation_score(
                    validation, len(candidate["rules"])
                )
                candidate["baseline_validation_metrics"] = baseline_validation
                horizon_shortlists.append(candidate)
        horizon_shortlists.sort(
            key=lambda item: (
                item["validation_score"],
                item["train_score"],
                -len(item["rules"]),
            ),
            reverse=True,
        )
        baseline_choices = [item for item in horizon_shortlists if not item["rules"]]
        best_baseline = baseline_choices[0] if baseline_choices else None
        filtered_choices = [
            item
            for item in horizon_shortlists
            if item["rules"]
            and item["validation_metrics"]["win_rate"]
            >= item["baseline_validation_metrics"]["win_rate"] + 0.02
            and item["validation_metrics"]["mean_net_return"] > 0
        ]
        selected = filtered_choices[0] if filtered_choices else best_baseline
        if selected is None:
            recommendations.append(
                {
                    "model_code": model_code,
                    "trigger": trigger,
                    "selection_status": "INSUFFICIENT_SAMPLE",
                    "holdout_status": "INSUFFICIENT_SAMPLE",
                }
            )
            audit[group_id] = {"status": "INSUFFICIENT_SAMPLE", "top_candidates": []}
            continue
        horizon = int(selected["horizon"])
        selected_mask = selected["mask"]
        validation = selected["validation_metrics"]
        baseline_validation = selected["baseline_validation_metrics"]
        holdout = _metrics_from_mask(frame, selected_mask, horizon, 2024, 2026)
        baseline_holdout = _metrics_from_mask(frame, base_mask, horizon, 2024, 2026)
        rules = tuple(selected["rules"])
        if not rules:
            selection_status = "NO_STABLE_FILTER"
            holdout_status = "NOT_APPLICABLE"
        elif holdout["sample_count"] < 30:
            selection_status = "FILTER_SELECTED"
            holdout_status = "INSUFFICIENT_HOLDOUT"
        else:
            delta = float(holdout["win_rate"]) - float(baseline_holdout["win_rate"])
            if (
                delta >= 0.02
                and holdout["win_rate"] > 0.50
                and holdout["mean_net_return"] > 0
            ):
                holdout_status = "CONFIRMED"
            elif delta > 0 and holdout["mean_net_return"] > 0:
                holdout_status = "MIXED_POSITIVE"
            else:
                holdout_status = "NOT_CONFIRMED"
            selection_status = "FILTER_SELECTED"
        recommendation = {
            "model_code": model_code,
            "trigger": trigger,
            "selection_status": selection_status,
            "holdout_status": holdout_status,
            "horizon_sessions": horizon,
            "rule_names": "+".join(rules),
            "rule_labels": "；".join(RULE_BY_NAME[name].label for name in rules),
            "train_sample_count": selected["train_metrics"]["sample_count"],
            "train_win_rate": selected["train_metrics"]["win_rate"],
            "validation_base_count": baseline_validation["sample_count"],
            "validation_base_win_rate": baseline_validation["win_rate"],
            "validation_filtered_count": validation["sample_count"],
            "validation_filtered_win_rate": validation["win_rate"],
            "validation_win_rate_delta": (
                round(
                    float(validation["win_rate"])
                    - float(baseline_validation["win_rate"]),
                    6,
                )
                if rules
                else 0.0
            ),
            "validation_filtered_mean_return": validation["mean_net_return"],
            "holdout_base_count": baseline_holdout["sample_count"],
            "holdout_base_win_rate": baseline_holdout["win_rate"],
            "holdout_filtered_count": holdout["sample_count"],
            "holdout_filtered_win_rate": holdout["win_rate"],
            "holdout_win_rate_delta": (
                round(
                    float(holdout["win_rate"]) - float(baseline_holdout["win_rate"]),
                    6,
                )
                if (
                    rules
                    and holdout["win_rate"] is not None
                    and baseline_holdout["win_rate"] is not None
                )
                else 0.0
            ),
            "holdout_filtered_mean_return": holdout["mean_net_return"],
            "holdout_filtered_ci_low": holdout["win_rate_ci_low"],
            "holdout_filtered_ci_high": holdout["win_rate_ci_high"],
        }
        recommendations.append(recommendation)
        top_candidates = []
        for item in horizon_shortlists[:10]:
            item_rules = tuple(item["rules"])
            top_candidates.append(
                {
                    "horizon_sessions": item["horizon"],
                    "rule_names": list(item_rules),
                    "rule_labels": [RULE_BY_NAME[name].label for name in item_rules],
                    "train_score": round(float(item["train_score"]), 8),
                    "train_metrics": item["train_metrics"],
                    "validation_score": round(float(item["validation_score"]), 8),
                    "validation_metrics": item["validation_metrics"],
                    "baseline_validation_metrics": item["baseline_validation_metrics"],
                }
            )
        audit[group_id] = {
            "status": selection_status,
            "selected": recommendation,
            "top_candidates": top_candidates,
        }
    return pd.DataFrame(recommendations), audit


def _aggregate_overview(events: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trigger, regime, horizon in itertools.product(
        TARGET_TRIGGER_BITS, REGIMES, HORIZONS
    ):
        subset = events[
            events["target_trigger"].eq(trigger)
            & events["market_regime"].eq(regime)
            & events[f"h{horizon}_status"].eq("OK")
        ]
        rows.append(
            {
                "trigger": trigger,
                "market_regime": regime,
                "horizon_sessions": horizon,
                **return_metrics(
                    subset[f"h{horizon}_net_return"].to_numpy(dtype=float)
                ),
            }
        )
    return rows


def write_outputs(
    *,
    output_dir: Path,
    events: pd.DataFrame,
    index: pd.DataFrame,
    candidate_paths: tuple[Path, ...],
    snapshot_root: Path,
    script_path: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    segments = build_market_segments(index)
    segments = segments[
        segments["end_date"].ge("2005-01-01") & segments["start_date"].le("2026-12-31")
    ].reset_index(drop=True)
    win_rates = build_win_rate_table(events)
    recommendations, filter_audit = search_filters(events)
    output_paths = {
        "market_segments": output_dir / "market_segments.csv",
        "regime_win_rates": output_dir / "regime_win_rates.csv",
        "filter_recommendations": output_dir / "filter_recommendations.csv",
        "filter_search_audit": output_dir / "filter_search_audit.json",
        "summary": output_dir / "summary.json",
    }
    segments.to_csv(output_paths["market_segments"], index=False, encoding="utf-8")
    win_rates.to_csv(output_paths["regime_win_rates"], index=False, encoding="utf-8")
    recommendations.to_csv(
        output_paths["filter_recommendations"], index=False, encoding="utf-8"
    )
    output_paths["filter_search_audit"].write_bytes(
        canonical_json_bytes(filter_audit) + b"\n"
    )
    model_coverage = sorted(events["model_code"].unique())
    trigger_counts = (
        events.groupby(["model_code", "target_trigger"])
        .size()
        .rename("signal_count")
        .reset_index()
        .to_dict(orient="records")
    )
    summary = {
        "study_id": STUDY_ID,
        "run_id": RUN_ID,
        "period": [
            events["reveal_date"].min().date().isoformat(),
            events["reveal_date"].max().date().isoformat(),
        ],
        "contracts": {
            "target_trigger_membership": (
                "concurrent_trigger_mask bits 3/4; a signal may belong to both"
            ),
            "market_regime": {
                "lookback_sessions": REGIME_LOOKBACK,
                "confirmation_sessions": REGIME_CONFIRMATION_SESSIONS,
                "up": "return_60>=5% and close>=MA60",
                "down": "return_60<=-5% and close<=MA60",
                "sideways": "otherwise",
                "clock": "same-day Shanghai Composite close at reveal_date",
            },
            "entry": "next stock trading session QFQ open",
            "exit_horizons_stock_sessions": list(HORIZONS),
            "return_price_domain": "QFQ_TOTAL_RETURN_APPROXIMATION",
            "execution_price_domain": "RAW_LIMIT_MOVE_CHECKS",
            "fee_per_side": FEE_PER_SIDE,
            "limit_move": LIMIT_MOVE,
            "filter_train": [2005, 2019],
            "filter_validation": [2020, 2023],
            "filter_holdout": [2024, 2026],
            "max_filter_conditions": 2,
        },
        "invariants": {
            "model_count": len(model_coverage),
            "models": model_coverage,
            "target_trigger_count": int(events["target_trigger"].nunique()),
            "future_index_joins": int(
                (events["index_feature_date"] > events["reveal_date"])
                .fillna(False)
                .sum()
            ),
            "win_rate_table_rows": len(win_rates),
            "expected_win_rate_table_rows": (
                4
                * len(MODEL_CODES)
                * len(TARGET_TRIGGER_BITS)
                * len(REGIMES)
                * len(HORIZONS)
            ),
        },
        "signal_rows": len(events),
        "unique_model_signal_keys": int(
            events[["code", "model_code", "reveal_date"]].drop_duplicates().shape[0]
        ),
        "trigger_counts": trigger_counts,
        "market_segment_counts": segments.groupby("regime").size().to_dict(),
        "aggregate_overview": _aggregate_overview(events),
        "filter_status_counts": recommendations["selection_status"]
        .value_counts(dropna=False)
        .to_dict(),
        "holdout_status_counts": recommendations["holdout_status"]
        .value_counts(dropna=False)
        .to_dict(),
        "confirmed_filters": recommendations[
            recommendations["holdout_status"].eq("CONFIRMED")
        ].to_dict(orient="records"),
    }
    output_paths["summary"].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    input_files = [
        {
            "path": str(path),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in candidate_paths
    ]
    output_files = {
        name: {
            "path": path.name,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for name, path in output_paths.items()
    }
    snapshot_manifest = snapshot_root.parent / "manifest.json"
    manifest = {
        "study_id": STUDY_ID,
        "run_id": RUN_ID,
        "script_sha256": sha256_file(script_path),
        "candidate_inputs": input_files,
        "snapshot_root": str(snapshot_root),
        "snapshot_manifest_sha256": (
            sha256_file(snapshot_manifest) if snapshot_manifest.exists() else None
        ),
        "outputs": output_files,
        "summary_invariants": summary["invariants"],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "output_dir": str(output_dir),
        "manifest": str(manifest_path),
        "summary": summary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate-path",
        action="append",
        type=Path,
        dest="candidate_paths",
        help="Candidate Parquet path; repeat for development and holdout",
    )
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=DEFAULT_SNAPSHOT_ROOT,
    )
    parser.add_argument(
        "--mongo-uri",
        default="mongodb://fq_mongodb:27017",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    candidate_paths = tuple(args.candidate_paths or DEFAULT_CANDIDATE_PATHS)
    for path in candidate_paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    print("loading target candidates", flush=True)
    events = load_target_candidates(candidate_paths)
    print(
        f"target rows={len(events):,} models={events['model_code'].nunique()}",
        flush=True,
    )
    print("loading Shanghai Composite regimes", flush=True)
    index = load_index(args.mongo_uri)
    events = attach_market_regimes(events, index)
    print("computing 30/60/90-session exits", flush=True)
    events = attach_exit_outcomes(events, args.snapshot_root)
    print("writing statistics and filter search", flush=True)
    result = write_outputs(
        output_dir=args.output_dir,
        events=events,
        index=index,
        candidate_paths=candidate_paths,
        snapshot_root=args.snapshot_root,
        script_path=Path(__file__),
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
