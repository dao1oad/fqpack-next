"""Build the causal CLX18 target-hit event universe from sealed event facts.

The development invocation opens only TRAIN/VALIDATION event partitions.  AUDIT
partitions require an already materialised immutable candidate lock.  Unlike the
older 20-session candidate builder, this program does not filter on
``split_boundary_status``: horizon-specific purge/embargo is applied later by
``compute_event_outcomes.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import polars as pl
import pyarrow.parquet as pq

DEFAULT_EVENT_ROOT = Path("/opt/clx-backtest/events/clx-preview-99634853b/event-study")
DEFAULT_SNAPSHOT_ROOT = Path(
    "/opt/clx-backtest/snapshots/"
    "cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4/"
    "bars"
)
DEFAULT_INDEX_PATH = Path("/tmp/clx18_multihorizon_f7_v2/index_daily.parquet")
DEFAULT_OUTPUT_ROOT = Path("/tmp/clx18_target_hit_v1")

DEVELOPMENT_STAGES = ("TRAIN", "VALIDATION")
AUDIT_STAGES = ("AUDIT",)
LEGACY_FEATURE_WINDOWS = {
    DEVELOPMENT_STAGES: (
        np.datetime64("2004-01-01"),
        np.datetime64("2024-12-31"),
    ),
    AUDIT_STAGES: (
        np.datetime64("2023-01-01"),
        np.datetime64("2027-12-31"),
    ),
}
FULL_HISTORY_FEATURES = {"qfq_ma250_reveal", "stock_above_ma250"}
STAGE_YEAR_RANGES = {
    "TRAIN": (2005, 2019),
    "VALIDATION": (2020, 2023),
    "AUDIT": (2024, 9999),
}
EXPECTED_LEGACY_ELIGIBLE_ROWS = {
    DEVELOPMENT_STAGES: 1_970_926,
    AUDIT_STAGES: 560_287,
}
EXPECTED_GLOBAL_SUPPLEMENTAL_BOUNDARY_ROWS = 72_489
REGIME_LOOKBACK = 60
REGIME_RETURN_THRESHOLD = 0.05
REGIME_CONFIRMATION_SESSIONS = 5

# Kept in sync with compute_event_outcomes.py.  Additional provenance and
# feature columns are deliberately retained in the output.
EVENT_COLUMNS = [
    "event_id",
    "model_code",
    "code",
    "reveal_date",
    "entry_date",
    "stage",
    "year",
    "quarter",
    "concurrent_trigger_mask",
    "concurrent_trigger_count",
    "filter_pass_mask",
    "same_code_model_count",
    "amount_median_20",
    "market_regime",
    "segment_id",
    "recomputed_entry_index",
    "qfq_entry_open_recomputed",
    "stock_above_ma250",
]

SOURCE_COLUMNS = [
    "signal_fact_id",
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
    "entry_trade_date",
    "entry_status",
    "raw_entry_open",
    "split_id",
    "split_boundary_status",
    "quality_mask",
]

BAR_COLUMNS = [
    "trade_date",
    "qfq_open",
    "qfq_high",
    "qfq_low",
    "qfq_close",
    "raw_open",
    "raw_amount",
]

FILTER_DEFINITIONS = [
    {
        "code": "F1",
        "bit": 1,
        "expression": "1 <= raw_entry_open_recomputed <= 6",
    },
    {"code": "F2", "bit": 2, "expression": "stock_return_20 <= 0"},
    {"code": "F3", "bit": 4, "expression": "stock_drawdown_20 <= -0.10"},
    {"code": "F4", "bit": 8, "expression": "stock_volatility_20 >= 0.03"},
    {"code": "F5", "bit": 16, "expression": "stock_above_ma60 <= 0"},
    {"code": "F6", "bit": 32, "expression": "market_return_20 <= 0"},
    {"code": "F7", "bit": 64, "expression": "stock_above_ma250 > 0"},
]

_REVEAL_YEAR_PATTERN = re.compile(r"^reveal_year=(\d{4})$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def canonical_sha(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=json_default,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parse_stages(value: str | Iterable[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        stages = tuple(
            part.strip().upper() for part in value.split(",") if part.strip()
        )
    else:
        stages = tuple(str(part).strip().upper() for part in value)
    if stages == DEVELOPMENT_STAGES:
        return stages
    if stages == AUDIT_STAGES:
        return stages
    raise ValueError("stages must be exactly TRAIN,VALIDATION or AUDIT")


def verify_audit_lock(
    stages: tuple[str, ...],
    path: Path | None,
    portfolio_path: Path | None,
) -> dict[str, Any] | None:
    """Fail before event discovery unless both pre-AUDIT locks are valid."""

    if stages != AUDIT_STAGES:
        return None
    if path is None or not path.is_file():
        raise RuntimeError("AUDIT event read requires --candidate-lock")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "clx18-target-hit-candidate-lock-v1":
        raise RuntimeError("candidate lock schema is invalid")
    if payload.get("selection_stages") != ["TRAIN", "VALIDATION"]:
        raise RuntimeError("candidate lock was not selected on TRAIN/VALIDATION")
    if payload.get("audit_read") is not False or not payload.get("candidates"):
        raise RuntimeError("candidate lock does not prove pre-AUDIT selection")
    recorded_sha = payload.get("lock_sha256")
    unsigned = dict(payload)
    unsigned.pop("lock_sha256", None)
    if recorded_sha != canonical_sha(unsigned):
        raise RuntimeError("candidate lock canonical hash mismatch")
    candidate_file_sha = sha256_file(path)

    if portfolio_path is None or not portfolio_path.is_file():
        raise RuntimeError("AUDIT event read requires --portfolio-lock")
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    if portfolio.get("schema_version") != "clx18-target-hit-portfolio-lock-v1":
        raise RuntimeError("portfolio lock schema is invalid")
    if portfolio.get("selection_stages") != ["TRAIN", "VALIDATION"]:
        raise RuntimeError("portfolio lock was not selected on TRAIN/VALIDATION")
    winner = portfolio.get("winner")
    if portfolio.get("audit_read") is not False or not isinstance(winner, dict):
        raise RuntimeError("portfolio lock does not prove pre-AUDIT selection")
    portfolio_recorded_sha = portfolio.get("lock_sha256")
    portfolio_unsigned = dict(portfolio)
    portfolio_unsigned.pop("lock_sha256", None)
    if portfolio_recorded_sha != canonical_sha(portfolio_unsigned):
        raise RuntimeError("portfolio lock canonical hash mismatch")
    inputs = portfolio.get("inputs")
    if not isinstance(inputs, dict):
        raise RuntimeError("portfolio lock inputs are invalid")
    if inputs.get("candidate_lock_sha256") != recorded_sha:
        raise RuntimeError("portfolio lock is not bound to candidate lock")
    if inputs.get("candidate_lock_file_sha256") != candidate_file_sha:
        raise RuntimeError("portfolio lock candidate file hash mismatch")
    candidate_ids = {
        str(candidate.get("candidate_id"))
        for candidate in payload["candidates"]
        if isinstance(candidate, dict) and candidate.get("candidate_id")
    }
    if str(winner.get("candidate_id")) not in candidate_ids:
        raise RuntimeError("portfolio winner is absent from candidate lock")
    return {
        "candidate_lock": {
            "path": str(path),
            "sha256": candidate_file_sha,
            "lock_sha256": recorded_sha,
            "selection_stages": payload["selection_stages"],
            "audit_read": payload["audit_read"],
        },
        "portfolio_lock": {
            "path": str(portfolio_path),
            "sha256": sha256_file(portfolio_path),
            "lock_sha256": portfolio_recorded_sha,
            "selection_stages": portfolio["selection_stages"],
            "audit_read": portfolio["audit_read"],
            "winner_candidate_id": str(winner["candidate_id"]),
        },
        "portfolio_binds_candidate": True,
    }


def reveal_year(path: Path) -> int:
    for part in path.parts:
        match = _REVEAL_YEAR_PATTERN.match(part)
        if match:
            return int(match.group(1))
    raise ValueError(f"event path has no reveal_year partition: {path}")


def year_belongs_to_stages(year: int, stages: tuple[str, ...]) -> bool:
    return any(
        lower <= year <= upper
        for stage in stages
        for lower, upper in (STAGE_YEAR_RANGES[stage],)
    )


def discover_event_files(root: Path, stages: tuple[str, ...]) -> list[Path]:
    pattern = "code_buckets/code_bucket=*/event_outcomes/reveal_year=*/part-*.parquet"
    files = [
        path
        for path in root.glob(pattern)
        if year_belongs_to_stages(reveal_year(path), stages)
    ]
    files.sort()
    if not files:
        raise RuntimeError(f"no {','.join(stages)} event files under {root}")
    return files


def _normalise_stage(values: pd.Series) -> pd.Series:
    return values.astype("string").replace({"HOLDOUT": "AUDIT"})


def _bit_count(values: np.ndarray) -> np.ndarray:
    return np.fromiter(
        (int(value).bit_count() for value in values),
        dtype=np.int8,
        count=len(values),
    )


def load_events(
    root: Path,
    stages: tuple[str, ...],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read only requested year partitions and retain every boundary status."""

    files = discover_event_files(root, stages)
    frames: list[pd.DataFrame] = []
    rows_read = 0
    for path in files:
        schema = set(pq.ParquetFile(path).schema.names)
        missing = sorted(set(SOURCE_COLUMNS) - schema)
        if missing:
            raise RuntimeError(f"{path} misses event columns: {missing}")
        frame = pd.read_parquet(path, columns=SOURCE_COLUMNS)
        rows_read += len(frame)
        frame = frame.loc[
            frame["direction"].eq(1) & frame["entry_status"].eq("EXECUTABLE")
        ].copy()
        if len(frame):
            frames.append(frame)
    if not frames:
        raise RuntimeError("no executable buy events in requested stages")

    events = pd.concat(frames, ignore_index=True)
    events["stage"] = _normalise_stage(events["split_id"])
    events = events.loc[events["stage"].isin(stages)].copy()
    if events.empty:
        raise RuntimeError("requested partitions contain no requested split rows")
    events["code"] = events["code"].astype("string").str.zfill(6)
    events["model_code"] = events["model_code"].astype("string")
    events["reveal_date"] = pd.to_datetime(events["reveal_date"], errors="raise")
    events["entry_trade_date"] = pd.to_datetime(
        events["entry_trade_date"], errors="raise"
    )
    events["revision_no"] = pd.to_numeric(events["revision_no"], errors="raise").astype(
        np.int64
    )
    events["concurrent_trigger_mask"] = pd.to_numeric(
        events["concurrent_trigger_mask"], errors="raise"
    ).astype(np.int16)

    key = ["code", "model_code", "direction", "reveal_date"]
    selected = events.sort_values(
        [*key, "revision_no", "signal_fact_id"], kind="stable"
    ).drop_duplicates(key, keep="last")
    selected = selected.sort_values(
        ["code", "reveal_date", "model_code"], kind="stable"
    ).reset_index(drop=True)
    if selected.duplicated(key).any():
        raise AssertionError("latest-revision event key is not unique")

    boundary_counts = {
        str(status): int(count)
        for status, count in selected["split_boundary_status"]
        .value_counts(dropna=False)
        .items()
    }
    eligible = selected.loc[selected["split_boundary_status"].eq("ELIGIBLE")]
    supplemental = selected.loc[selected["split_boundary_status"].ne("ELIGIBLE")]
    trigger_masks = selected["concurrent_trigger_mask"].to_numpy(dtype=np.int64)
    metadata = {
        "files_opened": len(files),
        "opened_reveal_years": sorted({reveal_year(path) for path in files}),
        "rows_read": rows_read,
        "executable_buy_rows_before_latest_revision": len(events),
        "rows_after_latest_revision": len(selected),
        "superseded_revision_rows": len(events) - len(selected),
        "boundary_status_counts_after_latest_revision": boundary_counts,
        "legacy_eligible_rows": len(eligible),
        "legacy_eligible_model_counts": {
            str(model): int(count)
            for model, count in eligible["model_code"]
            .value_counts()
            .sort_index()
            .items()
        },
        "supplemental_boundary_rows": len(supplemental),
        "supplemental_boundary_model_counts": {
            str(model): int(count)
            for model, count in supplemental["model_code"]
            .value_counts()
            .sort_index()
            .items()
        },
        "expected_global_supplemental_boundary_rows": (
            EXPECTED_GLOBAL_SUPPLEMENTAL_BOUNDARY_ROWS
        ),
        "non_eligible_rows_after_latest_revision": len(supplemental),
        "latest_revision_duplicate_key_rows": int(selected.duplicated(key).sum()),
        "concurrent_trigger_mask_invalid_rows": int(
            ((trigger_masks < 0) | ((trigger_masks & ~127) != 0)).sum()
        ),
        "file_inventory_sha256": canonical_sha(
            [
                {
                    "path": str(path),
                    "size": path.stat().st_size,
                    "reveal_year": reveal_year(path),
                }
                for path in files
            ]
        ),
    }
    return selected, metadata


def stock_feature_arrays(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    amounts: np.ndarray,
) -> dict[str, np.ndarray]:
    """Use the exact causal daily feature definitions from the candidate builder."""

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
    ma60 = close_series.rolling(60).mean()
    ma250 = close_series.rolling(250, min_periods=250).mean()
    return {
        "stock_return_5": close_series.pct_change(5, fill_method=None).to_numpy(),
        "stock_return_20": close_series.pct_change(20, fill_method=None).to_numpy(),
        "stock_return_60": close_series.pct_change(60, fill_method=None).to_numpy(),
        "stock_volatility_20": returns.rolling(20).std().to_numpy(),
        "stock_atr_20": (true_range.rolling(20).mean() / close_series).to_numpy(),
        "stock_drawdown_20": (close_series / rolling_high20 - 1).to_numpy(),
        "stock_above_ma20": (
            close_series / close_series.rolling(20).mean() - 1
        ).to_numpy(),
        "stock_above_ma60": (close_series / ma60 - 1).to_numpy(),
        "amount_median_20": pd.Series(amounts).rolling(20).median().shift(1).to_numpy(),
        "qfq_ma250_reveal": ma250.to_numpy(),
        "stock_above_ma250": (close_series / ma250 - 1).to_numpy(),
    }


def feature_window_for_events(
    events: pd.DataFrame,
) -> tuple[np.datetime64, np.datetime64]:
    stages = set(events["stage"].astype(str))
    if stages and stages <= set(DEVELOPMENT_STAGES):
        return LEGACY_FEATURE_WINDOWS[DEVELOPMENT_STAGES]
    if stages == set(AUDIT_STAGES):
        return LEGACY_FEATURE_WINDOWS[AUDIT_STAGES]
    raise ValueError("stock features require isolated TRAIN+VALIDATION or AUDIT events")


def build_filter_pass_mask(frame: pd.DataFrame) -> np.ndarray:
    def numeric(name: str) -> np.ndarray:
        return pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=np.float64)

    raw_entry = numeric("raw_entry_open_recomputed")
    return20 = numeric("stock_return_20")
    drawdown20 = numeric("stock_drawdown_20")
    volatility20 = numeric("stock_volatility_20")
    above60 = numeric("stock_above_ma60")
    market20 = numeric("market_return_20")
    above250 = numeric("stock_above_ma250")
    predicates = [
        np.isfinite(raw_entry) & (raw_entry >= 1.0) & (raw_entry <= 6.0),
        np.isfinite(return20) & (return20 <= 0.0),
        np.isfinite(drawdown20) & (drawdown20 <= -0.10),
        np.isfinite(volatility20) & (volatility20 >= 0.03),
        np.isfinite(above60) & (above60 <= 0.0),
        np.isfinite(market20) & (market20 <= 0.0),
        np.isfinite(above250) & (above250 > 0.0),
    ]
    result = np.zeros(len(frame), dtype=np.uint8)
    for bit, passed in enumerate(predicates):
        result |= passed.astype(np.uint8) << np.uint8(bit)
    return result


def normalise_index(frame: pd.DataFrame) -> pd.DataFrame:
    columns = {str(column).lower(): column for column in frame.columns}
    date_column = columns.get("date", columns.get("trade_date"))
    close_column = columns.get("close", columns.get("raw_close"))
    if date_column is None or close_column is None:
        raise RuntimeError("index needs date/trade_date and close/raw_close")
    result = frame[[date_column, close_column]].rename(
        columns={date_column: "date", close_column: "close"}
    )
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    result = (
        result.dropna(subset=["date", "close"])
        .sort_values("date", kind="stable")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    if result.empty or (result["close"] <= 0).any():
        raise RuntimeError("index close series is empty or non-positive")
    return result


def precomputed_market_features(index: pd.DataFrame) -> pd.DataFrame | None:
    """Validate and retain causal columns already sealed with index_daily."""

    required = {"market_return_20", "market_regime", "segment_id"}
    if not required.issubset(index.columns):
        return None
    columns = {str(column).lower(): column for column in index.columns}
    date_column = columns.get("date", columns.get("trade_date"))
    close_column = columns.get("close", columns.get("raw_close"))
    if date_column is None or close_column is None:
        raise RuntimeError(
            "precomputed index needs date/trade_date and close/raw_close"
        )
    result = index[
        [
            date_column,
            close_column,
            "market_return_20",
            "market_regime",
            "segment_id",
        ]
    ].rename(columns={date_column: "date", close_column: "close"})
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    result["market_return_20"] = pd.to_numeric(
        result["market_return_20"], errors="coerce"
    )
    result["market_regime"] = result["market_regime"].fillna("UNKNOWN").astype(str)
    result["segment_id"] = result["segment_id"].astype("string")
    result = (
        result.dropna(subset=["date", "close"])
        .sort_values("date", kind="stable")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    local_return20 = result["close"].pct_change(20, fill_method=None)
    comparable = local_return20.notna() & result["market_return_20"].notna()
    mismatches = ~np.isclose(
        local_return20.loc[comparable].to_numpy(dtype=np.float64),
        result.loc[comparable, "market_return_20"].to_numpy(dtype=np.float64),
        rtol=0.0,
        atol=1e-12,
    )
    if mismatches.any():
        raise AssertionError(
            f"precomputed market_return_20 drift: {int(mismatches.sum())} rows"
        )
    allowed = {"UP", "DOWN", "SIDEWAYS", "UNKNOWN"}
    invalid_regimes = sorted(set(result["market_regime"]) - allowed)
    if invalid_regimes:
        raise AssertionError(f"invalid precomputed market regimes: {invalid_regimes}")
    known = result["market_regime"].ne("UNKNOWN")
    missing_segments = known & result["segment_id"].isna()
    wrong_prefix = known & ~pd.Series(
        [
            str(segment).startswith(f"{regime}-")
            for regime, segment in zip(
                result["market_regime"],
                result["segment_id"],
                strict=True,
            )
        ],
        index=result.index,
    )
    if missing_segments.any() or wrong_prefix.any():
        raise AssertionError(
            "precomputed segment_id is missing or inconsistent with market_regime"
        )
    return result


def classify_market_regimes(index: pd.DataFrame) -> pd.DataFrame:
    """Causal Shanghai-index regime definition used by the existing CLX study."""

    frame = normalise_index(index)
    frame["market_return_20"] = frame["close"].pct_change(20, fill_method=None)
    frame["market_return_60"] = frame["close"].pct_change(
        REGIME_LOOKBACK, fill_method=None
    )
    ma60 = frame["close"].rolling(REGIME_LOOKBACK).mean()
    above60 = frame["close"] / ma60 - 1
    frame["raw_market_regime"] = "SIDEWAYS"
    ready = frame["market_return_60"].notna() & ma60.notna()
    frame.loc[~ready, "raw_market_regime"] = "UNKNOWN"
    frame.loc[
        ready & frame["market_return_60"].ge(REGIME_RETURN_THRESHOLD) & above60.ge(0),
        "raw_market_regime",
    ] = "UP"
    frame.loc[
        ready & frame["market_return_60"].le(-REGIME_RETURN_THRESHOLD) & above60.le(0),
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
    frame["segment_id"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    known = frame["market_regime"].ne("UNKNOWN")
    frame.loc[known, "segment_id"] = [
        f"{regime}-{int(number):04d}"
        for regime, number in zip(
            frame.loc[known, "market_regime"],
            frame.loc[known, "regime_segment_no"],
            strict=True,
        )
    ]
    return frame.drop(columns=["raw_market_regime"])


def map_bar_files(root: Path, codes: set[str]) -> dict[str, list[Path]]:
    mapping: dict[str, list[Path]] = {}
    for path in root.rglob("*.parquet"):
        code_part = next(
            (part for part in path.parts if part.startswith("code=")), None
        )
        if code_part is None:
            continue
        code = code_part.split("=", 1)[1].zfill(6)
        if code in codes:
            mapping.setdefault(code, []).append(path)
    for paths in mapping.values():
        paths.sort()
    return mapping


def load_code_bars(paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        schema = set(pq.ParquetFile(path).schema.names)
        missing = sorted(set(BAR_COLUMNS) - schema)
        if missing:
            raise RuntimeError(f"{path} misses snapshot bar columns: {missing}")
        frames.append(pd.read_parquet(path, columns=BAR_COLUMNS))
    bars = pd.concat(frames, ignore_index=True)
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="coerce")
    for column in BAR_COLUMNS[1:]:
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    return (
        bars.dropna(subset=["trade_date"])
        .sort_values("trade_date", kind="stable")
        .drop_duplicates("trade_date", keep="last")
        .reset_index(drop=True)
    )


def _initialise_feature_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.reset_index(drop=True).copy()
    result["entry_date"] = pd.NaT
    result["recomputed_entry_index"] = np.full(len(result), -1, dtype=np.int32)
    for column in (
        "qfq_entry_open_recomputed",
        "raw_entry_open_recomputed",
        "qfq_reveal_close",
        "stock_return_5",
        "stock_return_20",
        "stock_return_60",
        "stock_volatility_20",
        "stock_atr_20",
        "stock_drawdown_20",
        "stock_above_ma20",
        "stock_above_ma60",
        "amount_median_20",
        "qfq_ma250_reveal",
        "stock_above_ma250",
    ):
        result[column] = np.nan
    return result


def enrich_stock_features(
    events: pd.DataFrame,
    bar_files: dict[str, list[Path]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    result = _initialise_feature_columns(events)
    feature_window_start, feature_window_end = feature_window_for_events(result)
    missing_code_rows = 0
    missing_reveal_rows = 0
    missing_entry_rows = 0
    missing_feature_window_rows = 0
    entry_date_mismatches = 0
    raw_entry_price_mismatches = 0
    insufficient_ma250_rows = 0

    for code, row_index in result.groupby("code", sort=False).groups.items():
        paths = bar_files.get(str(code))
        if not paths:
            missing_code_rows += len(row_index)
            continue
        bars = load_code_bars(paths)
        dates = bars["trade_date"].to_numpy(dtype="datetime64[ns]")
        opens = bars["qfq_open"].to_numpy(dtype=np.float64)
        raw_opens = bars["raw_open"].to_numpy(dtype=np.float64)
        closes = bars["qfq_close"].to_numpy(dtype=np.float64)
        full_features = stock_feature_arrays(
            bars["qfq_high"].to_numpy(dtype=np.float64),
            bars["qfq_low"].to_numpy(dtype=np.float64),
            closes,
            bars["raw_amount"].to_numpy(dtype=np.float64),
        )
        feature_window = (dates >= feature_window_start) & (dates <= feature_window_end)
        window_bars = bars.loc[feature_window]
        window_dates = window_bars["trade_date"].to_numpy(dtype="datetime64[ns]")
        legacy_features = stock_feature_arrays(
            window_bars["qfq_high"].to_numpy(dtype=np.float64),
            window_bars["qfq_low"].to_numpy(dtype=np.float64),
            window_bars["qfq_close"].to_numpy(dtype=np.float64),
            window_bars["raw_amount"].to_numpy(dtype=np.float64),
        )

        rows = np.asarray(row_index)
        reveals = result.loc[rows, "reveal_date"].to_numpy(dtype="datetime64[ns]")
        reveal_positions = np.searchsorted(dates, reveals, side="left")
        reveal_valid = reveal_positions < len(dates)
        reveal_exact = np.zeros(len(rows), dtype=bool)
        reveal_exact[reveal_valid] = (
            dates[reveal_positions[reveal_valid]] == reveals[reveal_valid]
        )
        missing_reveal_rows += int((~reveal_exact).sum())
        target_rows = rows[reveal_exact]
        exact_reveal_positions = reveal_positions[reveal_exact]

        entry_positions = np.searchsorted(dates, reveals[reveal_exact], side="right")
        entry_valid = entry_positions < len(dates)
        missing_entry_rows += int((~entry_valid).sum())
        target_rows = target_rows[entry_valid]
        exact_reveal_positions = exact_reveal_positions[entry_valid]
        entry_positions = entry_positions[entry_valid]
        entry_dates = dates[entry_positions]
        exact_reveals = reveals[reveal_exact][entry_valid]
        window_reveal_positions = np.searchsorted(
            window_dates,
            exact_reveals,
            side="left",
        )
        window_valid = window_reveal_positions < len(window_dates)
        window_exact = np.zeros(len(target_rows), dtype=bool)
        window_exact[window_valid] = (
            window_dates[window_reveal_positions[window_valid]]
            == exact_reveals[window_valid]
        )
        missing_feature_window_rows += int((~window_exact).sum())
        if not window_exact.all():
            continue

        source_entry_dates = result.loc[target_rows, "entry_trade_date"].to_numpy(
            dtype="datetime64[ns]"
        )
        entry_date_mismatches += int((entry_dates != source_entry_dates).sum())
        source_raw_open = pd.to_numeric(
            result.loc[target_rows, "raw_entry_open"], errors="coerce"
        ).to_numpy(dtype=np.float64)
        recomputed_raw_open = raw_opens[entry_positions]
        comparable = np.isfinite(source_raw_open) & np.isfinite(recomputed_raw_open)
        raw_entry_price_mismatches += int(
            (
                comparable
                & ~np.isclose(
                    source_raw_open,
                    recomputed_raw_open,
                    rtol=0.0,
                    atol=1e-12,
                )
            ).sum()
        )

        result.loc[target_rows, "entry_date"] = entry_dates
        result.loc[target_rows, "recomputed_entry_index"] = entry_positions.astype(
            np.int32
        )
        result.loc[target_rows, "qfq_entry_open_recomputed"] = opens[entry_positions]
        result.loc[target_rows, "raw_entry_open_recomputed"] = recomputed_raw_open
        result.loc[target_rows, "qfq_reveal_close"] = closes[exact_reveal_positions]
        for name, values in legacy_features.items():
            if name not in FULL_HISTORY_FEATURES:
                result.loc[target_rows, name] = values[window_reveal_positions]
        for name in FULL_HISTORY_FEATURES:
            result.loc[target_rows, name] = full_features[name][exact_reveal_positions]
        insufficient_ma250_rows += int((exact_reveal_positions < 249).sum())

    checks = {
        "missing_snapshot_code_rows": missing_code_rows,
        "missing_reveal_bar_rows": missing_reveal_rows,
        "missing_entry_bar_rows": missing_entry_rows,
        "missing_feature_window_rows": missing_feature_window_rows,
        "source_entry_date_mismatches": entry_date_mismatches,
        "source_raw_entry_price_mismatches": raw_entry_price_mismatches,
        "reveal_rows_with_fewer_than_250_bars": insufficient_ma250_rows,
        "legacy_feature_window": {
            "start": str(feature_window_start),
            "end": str(feature_window_end),
            "f2_f5_and_auxiliary_stock_features": True,
            "f7_uses_full_history": True,
        },
    }
    failures = sum(
        (
            missing_code_rows,
            missing_reveal_rows,
            missing_entry_rows,
            missing_feature_window_rows,
            entry_date_mismatches,
            raw_entry_price_mismatches,
        )
    )
    if failures:
        raise AssertionError(f"snapshot event re-location checks failed: {checks}")
    return result, checks


def attach_market_features(
    events: pd.DataFrame,
    index: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    result = events.copy()
    market = precomputed_market_features(index)
    feature_source = "PRECOMPUTED_CAUSAL_COLUMNS"
    if market is None:
        market = classify_market_regimes(index)
        feature_source = "RECOMPUTED_FROM_INDEX_CLOSE"
    dates = market["date"].to_numpy(dtype="datetime64[ns]")
    reveal_dates = result["reveal_date"].to_numpy(dtype="datetime64[ns]")
    positions = np.searchsorted(dates, reveal_dates, side="right") - 1
    if feature_source == "RECOMPUTED_FROM_INDEX_CLOSE" and np.any(positions < 60):
        raise RuntimeError(
            "index close fallback lacks 60 pre-reveal sessions for market regime"
        )
    valid = positions >= 0
    safe = np.maximum(positions, 0)
    result["market_feature_date"] = pd.NaT
    result["market_return_20"] = np.nan
    result["market_regime"] = "UNKNOWN"
    result["segment_id"] = pd.Series(pd.NA, index=result.index, dtype="string")
    rows = np.flatnonzero(valid)
    result.loc[rows, "market_feature_date"] = dates[safe[valid]]
    result.loc[rows, "market_return_20"] = market["market_return_20"].to_numpy(
        dtype=np.float64
    )[safe[valid]]
    result.loc[rows, "market_regime"] = market["market_regime"].to_numpy()[safe[valid]]
    result.loc[rows, "segment_id"] = market["segment_id"].to_numpy()[safe[valid]]
    future = result["market_feature_date"].notna() & result["market_feature_date"].gt(
        result["reveal_date"]
    )
    checks = {
        "feature_source": feature_source,
        "missing_market_history_rows": int((~valid).sum()),
        "future_market_feature_rows": int(future.sum()),
        "market_regime_counts": {
            str(label): int(count)
            for label, count in result["market_regime"].value_counts().items()
        },
    }
    if checks["future_market_feature_rows"]:
        raise AssertionError("market features joined from a future session")
    return result, checks


def finalise_universe(events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    result = events.copy()
    result["concurrent_trigger_count"] = _bit_count(
        result["concurrent_trigger_mask"].to_numpy(dtype=np.int64)
    )
    consensus = result.groupby(["code", "reveal_date"])["model_code"].transform(
        "nunique"
    )
    result["same_code_model_count"] = consensus.astype(np.int16)
    result["filter_pass_mask"] = build_filter_pass_mask(result)
    result["year"] = result["reveal_date"].dt.year.astype(np.int16)
    result["quarter"] = result["reveal_date"].dt.to_period("Q").astype(str)
    result.insert(
        0,
        "event_id",
        pd.util.hash_pandas_object(
            result[["model_code", "code", "reveal_date"]], index=False
        ).to_numpy(dtype=np.uint64),
    )
    if result["event_id"].duplicated().any():
        raise AssertionError("uint64 event_id collision")

    insufficient = result["qfq_ma250_reveal"].isna()
    f7_pass = (result["filter_pass_mask"].to_numpy(dtype=np.uint8) & np.uint8(64)) != 0
    f7_expected = (
        pd.to_numeric(result["stock_above_ma250"], errors="coerce")
        .gt(0)
        .fillna(False)
        .to_numpy()
    )
    missing_columns = sorted(set(EVENT_COLUMNS) - set(result.columns))
    checks = {
        "event_columns_compatible": not missing_columns,
        "missing_event_columns": missing_columns,
        "non_buy_direction_rows": int(result["direction"].ne(1).sum()),
        "non_executable_entry_rows": int(result["entry_status"].ne("EXECUTABLE").sum()),
        "duplicate_latest_revision_keys": int(
            result.duplicated(["code", "model_code", "direction", "reveal_date"]).sum()
        ),
        "filter_mask_invalid_high_bits": int(
            (result["filter_pass_mask"].to_numpy(dtype=np.uint8) > 127).sum()
        ),
        "f7_mask_value_mismatches": int((f7_pass != f7_expected).sum()),
        "f7_missing_ma250_pass_rows": int((insufficient.to_numpy() & f7_pass).sum()),
        "boundary_status_counts": {
            str(status): int(count)
            for status, count in result["split_boundary_status"]
            .value_counts(dropna=False)
            .items()
        },
        "non_eligible_boundary_rows": int(
            result["split_boundary_status"].ne("ELIGIBLE").sum()
        ),
    }
    return (
        result.sort_values(
            ["entry_date", "model_code", "code", "reveal_date"],
            kind="stable",
        ).reset_index(drop=True),
        checks,
    )


def build_universe(
    events: pd.DataFrame,
    bar_files: dict[str, list[Path]],
    index: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    enriched, stock_checks = enrich_stock_features(events, bar_files)
    enriched, market_checks = attach_market_features(enriched, index)
    universe, final_checks = finalise_universe(enriched)
    return universe, {
        "stock": stock_checks,
        "market": market_checks,
        "universe": final_checks,
    }


def _legacy_key_frame(frame: pl.DataFrame | pl.LazyFrame) -> pl.DataFrame:
    return (
        frame.select(
            pl.col("stage").cast(pl.String),
            pl.col("model_code").cast(pl.String),
            pl.col("code").cast(pl.String).str.pad_start(6, "0"),
            pl.col("reveal_date").cast(pl.Date),
            pl.col("concurrent_trigger_mask").cast(pl.Int16),
            pl.col("filter_pass_mask").cast(pl.UInt8),
        ).collect()
        if isinstance(frame, pl.LazyFrame)
        else frame.select(
            pl.col("stage").cast(pl.String),
            pl.col("model_code").cast(pl.String),
            pl.col("code").cast(pl.String).str.pad_start(6, "0"),
            pl.col("reveal_date").cast(pl.Date),
            pl.col("concurrent_trigger_mask").cast(pl.Int16),
            pl.col("filter_pass_mask").cast(pl.UInt8),
        )
    )


def _model_counts(frame: pl.DataFrame) -> dict[str, int]:
    return {
        str(model): int(count)
        for model, count in frame.group_by("model_code")
        .len()
        .sort("model_code")
        .iter_rows()
    }


def compare_legacy_eligible(
    universe: pd.DataFrame,
    path: Path,
    stages: tuple[str, ...],
) -> dict[str, Any]:
    """Prove the legacy ELIGIBLE key/mask set did not drift.

    The scan predicate is pushed into Polars so an invocation for development
    returns only TRAIN/VALIDATION rows from the legacy artifact.
    """

    if not path.is_file():
        raise FileNotFoundError(path)
    required = {
        "stage",
        "model_code",
        "code",
        "reveal_date",
        "concurrent_trigger_mask",
        "filter_pass_mask",
    }
    schema = set(pl.scan_parquet(path).collect_schema().names())
    missing = sorted(required - schema)
    if missing:
        raise RuntimeError(f"{path} misses legacy eligible columns: {missing}")

    legacy = _legacy_key_frame(
        pl.scan_parquet(path).filter(pl.col("stage").is_in(list(stages)))
    )
    current_source = universe.loc[
        universe["split_boundary_status"].eq("ELIGIBLE"),
        list(required),
    ].copy()
    current = _legacy_key_frame(pl.from_pandas(current_source))
    key = ["stage", "model_code", "code", "reveal_date"]
    mask_columns = ["concurrent_trigger_mask", "filter_pass_mask"]
    key_with_mask = [*key, *mask_columns]

    legacy_duplicate_keys = legacy.select(key).is_duplicated()
    current_duplicate_keys = current.select(key).is_duplicated()
    legacy_unique = legacy.unique(key_with_mask, maintain_order=False)
    current_unique = current.unique(key_with_mask, maintain_order=False)
    missing_from_new = legacy_unique.join(current_unique, on=key_with_mask, how="anti")
    extra_in_new = current_unique.join(legacy_unique, on=key_with_mask, how="anti")
    joined_masks = current.select(key_with_mask).join(
        legacy.select(key_with_mask),
        on=key,
        how="inner",
        suffix="_legacy",
    )
    trigger_mask_mismatches = joined_masks.filter(
        pl.col("concurrent_trigger_mask") != pl.col("concurrent_trigger_mask_legacy")
    ).height
    filter_mask_mismatches = joined_masks.filter(
        pl.col("filter_pass_mask") != pl.col("filter_pass_mask_legacy")
    ).height
    filter_bit_mismatches = {
        f"F{bit_index + 1}": joined_masks.filter(
            (pl.col("filter_pass_mask").cast(pl.UInt8) & bit)
            != (pl.col("filter_pass_mask_legacy").cast(pl.UInt8) & bit)
        ).height
        for bit_index, bit in enumerate((1, 2, 4, 8, 16, 32, 64))
    }
    mismatch_samples = (
        joined_masks.filter(
            (
                pl.col("concurrent_trigger_mask")
                != pl.col("concurrent_trigger_mask_legacy")
            )
            | (pl.col("filter_pass_mask") != pl.col("filter_pass_mask_legacy"))
        )
        .head(20)
        .to_dicts()
    )
    expected_rows = EXPECTED_LEGACY_ELIGIBLE_ROWS[stages]
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "stages": list(stages),
        "expected_legacy_eligible_rows": expected_rows,
        "legacy_eligible_rows": legacy.height,
        "new_eligible_rows": current.height,
        "legacy_model_counts": _model_counts(legacy),
        "new_eligible_model_counts": _model_counts(current),
        "legacy_duplicate_key_rows": int(legacy_duplicate_keys.sum()),
        "new_eligible_duplicate_key_rows": int(current_duplicate_keys.sum()),
        "legacy_concurrent_trigger_mask_mismatch_rows": trigger_mask_mismatches,
        "legacy_filter_pass_mask_mismatch_rows": filter_mask_mismatches,
        "legacy_filter_bit_mismatch_rows": filter_bit_mismatches,
        "legacy_mismatch_samples": mismatch_samples,
        "legacy_keys_missing_from_new": missing_from_new.height,
        "new_keys_extra_vs_legacy": extra_in_new.height,
        "expected_count_matches": legacy.height == expected_rows,
        "eligible_key_mask_set_exact": (
            missing_from_new.height == 0
            and extra_in_new.height == 0
            and trigger_mask_mismatches == 0
            and filter_mask_mismatches == 0
            and int(legacy_duplicate_keys.sum()) == 0
            and int(current_duplicate_keys.sum()) == 0
        ),
    }


def boolean_checks(
    stages: tuple[str, ...],
    load_meta: dict[str, Any],
    build_checks: dict[str, Any],
    legacy: dict[str, Any] | None,
) -> dict[str, Any]:
    universe = build_checks["universe"]
    stock = build_checks["stock"]
    market = build_checks["market"]
    years = load_meta["opened_reveal_years"]
    checks = {
        "event_partition_stage_isolation": all(
            year_belongs_to_stages(int(year), stages) for year in years
        ),
        "latest_revision_keys_unique": (
            universe["duplicate_latest_revision_keys"] == 0
            and load_meta["latest_revision_duplicate_key_rows"] == 0
        ),
        "only_executable_buy_events": (
            universe["non_buy_direction_rows"] == 0
            and universe["non_executable_entry_rows"] == 0
        ),
        "concurrent_trigger_masks_valid": (
            load_meta["concurrent_trigger_mask_invalid_rows"] == 0
        ),
        "all_boundary_statuses_retained": (
            universe["boundary_status_counts"]
            == load_meta["boundary_status_counts_after_latest_revision"]
        ),
        "entry_relocation_exact": all(
            stock[name] == 0
            for name in (
                "missing_snapshot_code_rows",
                "missing_reveal_bar_rows",
                "missing_entry_bar_rows",
                "missing_feature_window_rows",
                "source_entry_date_mismatches",
                "source_raw_entry_price_mismatches",
            )
        ),
        "market_features_are_causal": market["future_market_feature_rows"] == 0,
        "f7_missing_history_fails": universe["f7_missing_ma250_pass_rows"] == 0,
        "f7_mask_matches_value": universe["f7_mask_value_mismatches"] == 0,
        "filter_mask_uses_only_f1_f7": universe["filter_mask_invalid_high_bits"] == 0,
        "compute_event_outcomes_columns_present": universe["event_columns_compatible"],
    }
    if legacy is not None:
        checks["legacy_expected_count_matches"] = legacy["expected_count_matches"]
        checks["old_eligible_signal_set_unchanged"] = legacy[
            "eligible_key_mask_set_exact"
        ]
    checks["all_passed"] = all(checks.values())
    return checks


def source_manifest_path(root: Path) -> Path | None:
    for candidate in (root / "manifest.json", root.parent / "manifest.json"):
        if candidate.is_file():
            return candidate
    return None


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            default=json_default,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    stages = parse_stages(args.stages)
    lock_meta = verify_audit_lock(
        stages,
        args.candidate_lock,
        args.portfolio_lock,
    )
    events, load_meta = load_events(args.event_root, stages)
    codes = set(events["code"].astype(str))
    bar_files = map_bar_files(args.snapshot_root, codes)
    index = pd.read_parquet(args.index_path)
    universe, build_checks = build_universe(events, bar_files, index)
    legacy = (
        compare_legacy_eligible(universe, args.legacy_eligible, stages)
        if args.legacy_eligible is not None
        else None
    )
    checks = boolean_checks(stages, load_meta, build_checks, legacy)
    if not checks["all_passed"]:
        raise AssertionError(
            "event universe checks failed: "
            + json.dumps(
                {
                    "checks": checks,
                    "legacy_eligible_comparison": legacy,
                    "build_details": build_checks,
                },
                ensure_ascii=False,
                default=json_default,
            )
        )

    output = args.output
    if output is None:
        filename = (
            "event_universe_audit.parquet"
            if stages == AUDIT_STAGES
            else "event_universe.parquet"
        )
        output = DEFAULT_OUTPUT_ROOT / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    universe.to_parquet(
        partial,
        index=False,
        compression="zstd",
        engine="pyarrow",
        row_group_size=100_000,
    )
    os.replace(partial, output)

    checks_path = output.with_suffix(".checks.json")
    write_json(
        checks_path,
        {
            "schema_version": "clx18-target-hit-universe-checks-v1",
            "stages": list(stages),
            "checks": checks,
            "details": build_checks,
        },
    )
    event_manifest = source_manifest_path(args.event_root)
    snapshot_manifest = source_manifest_path(args.snapshot_root)
    manifest = {
        "schema_version": "clx18-target-hit-event-universe-v1",
        "generated_at": utc_now(),
        "stages": list(stages),
        "audit_gate": lock_meta,
        "contract": {
            "source": "sealed clx-preview-99634853b event-study outcomes",
            "selection": {
                "direction": 1,
                "entry_status": "EXECUTABLE",
                "split_boundary_status": "ALL_RETAINED",
                "dedup_key": [
                    "code",
                    "model_code",
                    "direction",
                    "reveal_date",
                ],
                "dedup_winner": "greatest revision_no",
            },
            "entry": "first stock session strictly after reveal_date",
            "features": (
                "F1-F6 retain the legacy split-window candidate semantics "
                "(development 2004..2024; audit 2023..2027); F1 uses entry "
                "raw open and F7 alone uses full-history reveal-close MA250"
            ),
            "f7": (
                "qfq reveal close > inclusive qfq MA250; fewer than 250 bars "
                "or missing value fails"
            ),
            "filters": FILTER_DEFINITIONS,
            "market_regime": {
                "source": "Shanghai Composite close",
                "lookback": REGIME_LOOKBACK,
                "return_threshold": REGIME_RETURN_THRESHOLD,
                "confirmation_sessions": REGIME_CONFIRMATION_SESSIONS,
            },
            "purge_embargo": (
                "not applied here; compute_event_outcomes applies it per horizon"
            ),
        },
        "inputs": {
            "event_root": str(args.event_root),
            "event_manifest": (
                {
                    "path": str(event_manifest),
                    "sha256": sha256_file(event_manifest),
                }
                if event_manifest
                else None
            ),
            "event_load": load_meta,
            "legacy_eligible_comparison": legacy,
            "snapshot_root": str(args.snapshot_root),
            "snapshot_manifest": (
                {
                    "path": str(snapshot_manifest),
                    "sha256": sha256_file(snapshot_manifest),
                }
                if snapshot_manifest
                else None
            ),
            "index": {
                "path": str(args.index_path),
                "size": args.index_path.stat().st_size,
                "sha256": sha256_file(args.index_path),
            },
        },
        "output": {
            "path": str(output),
            "rows": len(universe),
            "codes": int(universe["code"].nunique()),
            "models": int(universe["model_code"].nunique()),
            "stage_counts": {
                str(stage): int(count)
                for stage, count in universe["stage"].value_counts().items()
            },
            "size": output.stat().st_size,
            "sha256": sha256_file(output),
            "columns": list(universe.columns),
        },
        "checks_path": str(checks_path),
        "checks_sha256": sha256_file(checks_path),
        "checks": checks,
    }
    manifest_path = output.with_suffix(".manifest.json")
    write_json(manifest_path, manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stages", default="TRAIN,VALIDATION")
    parser.add_argument("--event-root", type=Path, default=DEFAULT_EVENT_ROOT)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--index-path", type=Path, default=DEFAULT_INDEX_PATH)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--candidate-lock", type=Path, default=None)
    parser.add_argument("--portfolio-lock", type=Path, default=None)
    parser.add_argument(
        "--legacy-eligible",
        type=Path,
        default=None,
        help=(
            "optional old extended_events.parquet; validates the requested "
            "stage's ELIGIBLE key/mask set exactly"
        ),
    )
    return parser.parse_args()


def main() -> None:
    manifest = run(parse_args())
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=json_default))


if __name__ == "__main__":
    main()
