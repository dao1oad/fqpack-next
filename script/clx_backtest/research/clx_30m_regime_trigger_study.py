# -*- coding: utf-8 -*-
"""Run the causal CLX 30-minute regime/trigger study.

This is a separate research path.  It does not reinterpret or overwrite the
daily CLX snapshot and signal-fact artifacts.

The workflow is intentionally split into resumable phases:

1. ``snapshot`` freezes normalized per-code 30-minute bars from QuantAxis;
2. ``replay`` performs exact from-zero prefix replay and checkpoints each code;
3. ``aggregate`` joins the prior Shanghai-index session, measures 30/60/90
   stock-trading-day outcomes, and searches at most two causal filters.

The current Mongo stock history starts on 2024-04-15.  Results from that source
are therefore marked as short-history provisional evidence rather than a
2015-present study.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import itertools
import json
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import pymongo

from freshquant.backtest.clx.engine import (
    ClxEngineOptions,
    FqCopilotClxEngine,
)
from freshquant.backtest.clx.intraday import (
    BAR_SLOT_CLOCKS,
    FEE_PER_SIDE,
    HORIZONS,
    LIMIT_MOVE,
    MONGO_MINUTE_TYPE,
    SHANGHAI_TIMEZONE,
    attach_previous_session_regimes,
    build_intraday_bars,
    replay_prefix_events,
)

try:
    from script.clx_backtest.research.clx_regime_trigger_study import (
        REGIMES,
        build_market_segments,
        classify_market_regimes,
        return_metrics,
    )
except ModuleNotFoundError:
    from clx_regime_trigger_study import (  # type: ignore[no-redef]
        REGIMES,
        build_market_segments,
        classify_market_regimes,
        return_metrics,
    )

STUDY_ID = "clx-30m-regime-trigger-v1"
SNAPSHOT_CONTRACT_VERSION = 2
SIGNAL_REPLAY_CONTRACT_VERSION = 1
AGGREGATE_CONTRACT_VERSION = 1
MODEL_CODES = tuple(f"S{model_id:04d}" for model_id in range(18))
TARGET_TRIGGER_BITS = {
    "ENGULFING": 0x04,
    "STRONG_FRACTAL": 0x08,
}
TARGET_MASK = sum(TARGET_TRIGGER_BITS.values())
DEFAULT_START_DATE = "2024-04-15"
DEFAULT_END_DATE = "2026-07-24"
DEFAULT_OUTPUT_ROOT = Path(f"/opt/clx-backtest/studies/{STUDY_ID}")
EXPECTED_SESSION_LABELS = frozenset(BAR_SLOT_CLOCKS)
BAR_WINDOWS = {
    "5d": 40,
    "20d": 160,
    "60d": 480,
}
SPLIT_RANGES = {
    "TRAIN": (date(2024, 7, 1), date(2024, 12, 31)),
    "VALIDATION": (date(2025, 1, 1), date(2025, 12, 31)),
    "HOLDOUT": (date(2026, 1, 1), date(2026, 12, 31)),
}
AUDITED_FULL_SOURCE_STATE = {
    "code_count": 5_201,
    "raw_docs": 22_700_036,
    "unique_bars": 20_392_812,
    "duplicate_extra_docs": 2_307_224,
    "source_sessions": 2_549_102,
    "standard_sessions": 2_549_091,
}

MINUTE_PROJECTION = {
    "_id": 0,
    "code": 1,
    "type": 1,
    "date": 1,
    "datetime": 1,
    "time_stamp": 1,
    "date_stamp": 1,
    "open": 1,
    "high": 1,
    "low": 1,
    "close": 1,
    "vol": 1,
    "amount": 1,
}
ADJ_PROJECTION = {"_id": 0, "code": 1, "date": 1, "adj": 1}
DAY_PROJECTION = {"_id": 0, "code": 1, "date": 1, "close": 1}


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=_json_default,
        )
        + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def write_frame_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_parquet(
        temporary,
        index=False,
        compression="zstd",
    )
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return value


def _document_clock(document: Mapping[str, Any]) -> str:
    value = str(document.get("datetime", ""))
    return value[11:16] if len(value) >= 16 else ""


def select_complete_session_documents(
    documents: Iterable[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """Keep only complete, standard, non-placeholder stock sessions.

    Exact source duplicates remain in the selected rows so
    :func:`build_intraday_bars` can validate and count them deterministically.
    Entire anomalous code-days are removed; no bar is fabricated.
    """

    source_rows = list(documents)
    rows = [
        document
        for document in source_rows
        if document.get("type") == MONGO_MINUTE_TYPE
    ]
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for document in rows:
        key = (str(document.get("code", "")), str(document.get("date", "")))
        grouped.setdefault(key, []).append(document)

    selected: list[Mapping[str, Any]] = []
    excluded_sessions: list[dict[str, Any]] = []
    unique_bars = 0
    duplicate_extra_docs = 0
    complete_sessions = 0
    for (code, trade_date), session_rows in sorted(grouped.items()):
        stamp_groups: dict[object, list[Mapping[str, Any]]] = {}
        for document in session_rows:
            stamp_groups.setdefault(document.get("time_stamp"), []).append(document)
        unique_count = len(stamp_groups)
        unique_bars += unique_count
        duplicate_extra_docs += len(session_rows) - unique_count
        labels = {_document_clock(group[0]) for group in stamp_groups.values()}
        total_volume = sum(float(row.get("vol", 0.0) or 0.0) for row in session_rows)
        total_amount = sum(float(row.get("amount", 0.0) or 0.0) for row in session_rows)
        reasons: list[str] = []
        if unique_count != len(BAR_SLOT_CLOCKS):
            reasons.append("UNIQUE_BAR_COUNT")
        if labels != EXPECTED_SESSION_LABELS:
            reasons.append("BAR_SLOT_SET")
        if total_volume <= 1e-12 or total_amount <= 1e-12:
            reasons.append("NON_TRADING_PLACEHOLDER")
        if reasons:
            excluded_sessions.append(
                {
                    "code": code,
                    "date": trade_date,
                    "raw_docs": len(session_rows),
                    "unique_bars": unique_count,
                    "labels": sorted(labels),
                    "reasons": reasons,
                }
            )
            continue
        selected.extend(session_rows)
        complete_sessions += 1

    return selected, {
        "raw_docs": len(rows),
        "unique_bars": unique_bars,
        "duplicate_extra_docs": duplicate_extra_docs,
        "source_sessions": len(grouped),
        "complete_sessions": complete_sessions,
        "excluded_session_count": len(excluded_sessions),
        "excluded_sessions": excluded_sessions,
        "ignored_non_30min_docs": sum(
            document.get("type") != MONGO_MINUTE_TYPE for document in source_rows
        ),
    }


def select_joinable_session_documents(
    documents: Iterable[Mapping[str, Any]],
    *,
    adj_docs: Iterable[Mapping[str, Any]],
    daily_docs: Iterable[Mapping[str, Any]],
    quality: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """Exclude complete minute sessions lacking an exact daily/adj join."""

    rows = list(documents)
    adj_keys = {
        (str(document.get("code", "")), str(document.get("date", "")))
        for document in adj_docs
    }
    daily_keys = {
        (str(document.get("code", "")), str(document.get("date", "")))
        for document in daily_docs
    }
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for document in rows:
        key = (str(document.get("code", "")), str(document.get("date", "")))
        grouped.setdefault(key, []).append(document)

    selected: list[Mapping[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for (code, trade_date), session_rows in sorted(grouped.items()):
        reasons: list[str] = []
        if (code, trade_date) not in adj_keys:
            reasons.append("MISSING_ADJ_FACTOR")
        if (code, trade_date) not in daily_keys:
            reasons.append("MISSING_STOCK_DAY")
        if not reasons:
            selected.extend(session_rows)
            continue
        stamp_groups: dict[object, list[Mapping[str, Any]]] = {}
        for document in session_rows:
            stamp_groups.setdefault(document.get("time_stamp"), []).append(document)
        excluded.append(
            {
                "code": code,
                "date": trade_date,
                "raw_docs": len(session_rows),
                "unique_bars": len(stamp_groups),
                "labels": sorted(
                    {_document_clock(group[0]) for group in stamp_groups.values()}
                ),
                "reasons": reasons,
            }
        )

    updated = dict(quality)
    existing_excluded = [dict(item) for item in quality.get("excluded_sessions", [])]
    standard_sessions = int(quality["complete_sessions"])
    updated.update(
        {
            "standard_sessions": standard_sessions,
            "complete_sessions": standard_sessions - len(excluded),
            "cross_source_excluded_session_count": len(excluded),
            "excluded_session_count": len(existing_excluded) + len(excluded),
            "excluded_sessions": existing_excluded + excluded,
        }
    )
    return selected, updated


def _snapshot_config(start_date: str, end_date: str) -> dict[str, Any]:
    return {
        "study_id": STUDY_ID,
        "snapshot_contract_version": SNAPSHOT_CONTRACT_VERSION,
        "source_database": "quantaxis",
        "minute_collection": "stock_min",
        "minute_type": MONGO_MINUTE_TYPE,
        "minute_primary_key": ["code", "type", "time_stamp"],
        "adjustment_collection": "stock_adj",
        "daily_collection": "stock_day",
        "index_collection": "index_day",
        "start_date": start_date,
        "end_date": end_date,
        "timezone": SHANGHAI_TIMEZONE,
        "required_bar_slots": list(BAR_SLOT_CLOCKS),
        "session_quality": (
            "exact 8 standard slots, positive aggregate volume/amount, and exact "
            "stock_adj plus stock_day joins; exclude the full anomalous code-day "
            "without fabricating bars or carrying factors"
        ),
        "qfq_formula": "raw_price * stock_adj.adj",
        "prior_close": "latest stock_day.close with date < bar trade_date",
    }


def _snapshot_code_paths(root: Path, code: str) -> tuple[Path, Path]:
    return (
        root / "snapshot" / "bars" / f"{code}.parquet",
        root / "snapshot" / "checkpoints" / f"{code}.json",
    )


def _valid_checkpoint(
    *,
    data_path: Path,
    meta_path: Path,
    identity_key: str,
    identity_value: str,
) -> dict[str, Any] | None:
    if not data_path.is_file() or not meta_path.is_file():
        return None
    try:
        meta = _read_json(meta_path)
        if meta.get(identity_key) != identity_value:
            return None
        if meta.get("file_sha256") != sha256_file(data_path):
            return None
        return meta
    except (OSError, ValueError, RuntimeError):
        return None


def _load_code_source_documents(
    *,
    mongo_uri: str,
    code: str,
    start_date: str,
    end_date: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    client = pymongo.MongoClient(
        mongo_uri,
        serverSelectionTimeoutMS=10_000,
        connectTimeoutMS=10_000,
    )
    database = client["quantaxis"]
    minute_docs = list(
        database["stock_min"]
        .find(
            {
                "code": code,
                "type": MONGO_MINUTE_TYPE,
                "date": {"$gte": start_date, "$lte": end_date},
            },
            MINUTE_PROJECTION,
        )
        .sort([("time_stamp", pymongo.ASCENDING)])
    )
    adj_docs = list(
        database["stock_adj"]
        .find(
            {
                "code": code,
                "date": {"$gte": start_date, "$lte": end_date},
            },
            ADJ_PROJECTION,
        )
        .sort([("date", pymongo.ASCENDING)])
    )
    daily_docs = list(
        database["stock_day"]
        .find(
            {
                "code": code,
                "date": {"$gte": start_date, "$lte": end_date},
            },
            DAY_PROJECTION,
        )
        .sort([("date", pymongo.ASCENDING)])
    )
    previous = database["stock_day"].find_one(
        {"code": code, "date": {"$lt": start_date}},
        DAY_PROJECTION,
        sort=[("date", pymongo.DESCENDING)],
    )
    if previous is not None:
        daily_docs.insert(0, previous)
    client.close()
    return minute_docs, adj_docs, daily_docs


def snapshot_one_code(
    *,
    mongo_uri: str,
    root: str,
    code: str,
    start_date: str,
    end_date: str,
    config_sha256: str,
) -> dict[str, Any]:
    output_root = Path(root)
    data_path, meta_path = _snapshot_code_paths(output_root, code)
    existing = _valid_checkpoint(
        data_path=data_path,
        meta_path=meta_path,
        identity_key="snapshot_config_sha256",
        identity_value=config_sha256,
    )
    if existing is not None:
        return {**existing, "checkpoint_status": "REUSED"}

    started = time.perf_counter()
    minute_docs, adj_docs, daily_docs = _load_code_source_documents(
        mongo_uri=mongo_uri,
        code=code,
        start_date=start_date,
        end_date=end_date,
    )
    selected_docs, quality = select_complete_session_documents(minute_docs)
    selected_docs, quality = select_joinable_session_documents(
        selected_docs,
        adj_docs=adj_docs,
        daily_docs=daily_docs,
        quality=quality,
    )
    bars = build_intraday_bars(
        minute_docs=selected_docs,
        adj_docs=adj_docs,
        daily_docs=daily_docs,
    )
    if not bars.empty and set(bars["code"]) != {code}:
        raise RuntimeError(f"{code} snapshot contains another code")
    write_frame_atomic(bars, data_path)
    meta = {
        "code": code,
        "snapshot_config_sha256": config_sha256,
        "logical_path": f"snapshot/bars/{code}.parquet",
        "rows": len(bars),
        "min_bar_at": bars["bar_at"].min().isoformat() if len(bars) else None,
        "max_bar_at": bars["bar_at"].max().isoformat() if len(bars) else None,
        "file_size": data_path.stat().st_size,
        "file_sha256": sha256_file(data_path),
        "source_quality": quality,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json_atomic(meta_path, meta)
    return {**meta, "checkpoint_status": "BUILT"}


def _write_index_snapshot(
    *,
    mongo_uri: str,
    root: Path,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    index_start = (pd.Timestamp(start_date) - pd.Timedelta(days=500)).date().isoformat()
    client = pymongo.MongoClient(
        mongo_uri,
        serverSelectionTimeoutMS=10_000,
        connectTimeoutMS=10_000,
    )
    records = list(
        client["quantaxis"]["index_day"]
        .find(
            {
                "code": "000001",
                "date": {"$gte": index_start, "$lte": end_date},
            },
            {"_id": 0, "date": 1, "close": 1},
        )
        .sort([("date", pymongo.ASCENDING)])
    )
    client.close()
    if not records:
        raise RuntimeError("missing Shanghai Composite index_day records")
    frame = pd.DataFrame(records)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = (
        frame.dropna(subset=["date", "close"])
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    path = root / "snapshot" / "index_day.parquet"
    write_frame_atomic(frame, path)
    return {
        "logical_path": "snapshot/index_day.parquet",
        "rows": len(frame),
        "min_date": frame["date"].min().date().isoformat(),
        "max_date": frame["date"].max().date().isoformat(),
        "file_size": path.stat().st_size,
        "file_sha256": sha256_file(path),
    }


def _select_codes(
    *,
    mongo_uri: str,
    start_date: str,
    end_date: str,
    requested_codes: Sequence[str],
    code_limit: int | None,
) -> list[str]:
    if requested_codes:
        codes = sorted({str(code).strip() for code in requested_codes})
    else:
        client = pymongo.MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=10_000,
            connectTimeoutMS=10_000,
        )
        codes = sorted(
            str(value)
            for value in client["quantaxis"]["stock_min"].distinct(
                "code",
                {
                    "type": MONGO_MINUTE_TYPE,
                    "date": {"$gte": start_date, "$lte": end_date},
                },
            )
        )
        client.close()
    invalid = [code for code in codes if len(code) != 6 or not code.isdigit()]
    if invalid:
        raise RuntimeError(f"invalid stock codes: {invalid[:10]}")
    if code_limit is not None:
        codes = codes[:code_limit]
    if not codes:
        raise RuntimeError("30min snapshot universe is empty")
    return codes


def run_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    config = _snapshot_config(args.start_date, args.end_date)
    config_sha256 = sha256_bytes(canonical_json_bytes(config))
    codes = _select_codes(
        mongo_uri=args.mongo_uri,
        start_date=args.start_date,
        end_date=args.end_date,
        requested_codes=args.code,
        code_limit=args.code_limit,
    )
    progress_path = root / "snapshot" / "progress.json"
    metas: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                snapshot_one_code,
                mongo_uri=args.mongo_uri,
                root=str(root),
                code=code,
                start_date=args.start_date,
                end_date=args.end_date,
                config_sha256=config_sha256,
            ): code
            for code in codes
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            code = futures[future]
            try:
                metas[code] = future.result()
            except Exception as exc:  # noqa: BLE001 - persisted worker boundary
                failures[code] = f"{type(exc).__name__}: {exc}"
            progress = {
                "phase": "snapshot",
                "total_codes": len(codes),
                "completed_codes": completed,
                "successful_codes": len(metas),
                "failed_codes": len(failures),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "failures": failures,
            }
            write_json_atomic(progress_path, progress)
            print(json.dumps(progress, ensure_ascii=False), flush=True)

    if failures:
        raise RuntimeError(
            f"snapshot failed for {len(failures)} codes; inspect {progress_path}"
        )
    index_meta = _write_index_snapshot(
        mongo_uri=args.mongo_uri,
        root=root,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    ordered_metas = [
        {
            key: value
            for key, value in metas[code].items()
            if key not in {"checkpoint_status", "elapsed_seconds"}
        }
        for code in codes
    ]
    identity_payload = {
        "config": config,
        "index_file_sha256": index_meta["file_sha256"],
        "code_files": [
            {
                "code": meta["code"],
                "rows": meta["rows"],
                "file_sha256": meta["file_sha256"],
            }
            for meta in ordered_metas
        ],
    }
    snapshot_id = "sha256:" + sha256_bytes(canonical_json_bytes(identity_payload))
    quality_totals = {
        key: sum(int(meta["source_quality"][key]) for meta in ordered_metas)
        for key in (
            "raw_docs",
            "unique_bars",
            "duplicate_extra_docs",
            "source_sessions",
            "standard_sessions",
            "complete_sessions",
            "cross_source_excluded_session_count",
            "excluded_session_count",
        )
    }
    excluded_sessions = [
        row
        for meta in ordered_metas
        for row in meta["source_quality"]["excluded_sessions"]
    ]
    full_universe = not args.code and args.code_limit is None
    if full_universe:
        actual_source_state = {
            "code_count": len(codes),
            **{
                key: quality_totals[key]
                for key in AUDITED_FULL_SOURCE_STATE
                if key != "code_count"
            },
        }
        if actual_source_state != AUDITED_FULL_SOURCE_STATE:
            raise RuntimeError(
                "full source state differs from the frozen Mongo audit: "
                f"{actual_source_state!r}"
            )
    manifest: dict[str, Any] = {
        "study_id": STUDY_ID,
        "snapshot_id": snapshot_id,
        "snapshot_config_sha256": config_sha256,
        "config": config,
        "universe": {
            "code_count": len(codes),
            "codes": codes,
        },
        "coverage": {
            "min_bar_at": min(
                meta["min_bar_at"] for meta in ordered_metas if meta["min_bar_at"]
            ),
            "max_bar_at": max(
                meta["max_bar_at"] for meta in ordered_metas if meta["max_bar_at"]
            ),
            "bar_rows": sum(int(meta["rows"]) for meta in ordered_metas),
        },
        "source_quality": {
            **quality_totals,
            "excluded_sessions": excluded_sessions,
        },
        "source_audit_contract": {
            "full_universe": full_universe,
            "expected": AUDITED_FULL_SOURCE_STATE if full_universe else None,
            "matched": full_universe,
        },
        "index": index_meta,
        "code_files": ordered_metas,
    }
    manifest_path = root / "snapshot" / "manifest.json"
    write_json_atomic(manifest_path, manifest)
    result = {
        "snapshot_manifest": str(manifest_path),
        "snapshot_id": snapshot_id,
        "code_count": len(codes),
        "bar_rows": manifest["coverage"]["bar_rows"],
        "source_quality": manifest["source_quality"],
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def _research_split(value: object) -> str:
    trade_date = pd.Timestamp(value).date()
    for split_id, (start, end) in SPLIT_RANGES.items():
        if start <= trade_date <= end:
            return split_id
    return "WARMUP"


def _feature_arrays(bars: pd.DataFrame) -> dict[str, np.ndarray]:
    close = pd.Series(
        pd.to_numeric(bars["qfq_close"], errors="coerce").to_numpy(dtype=float)
    )
    high = pd.Series(
        pd.to_numeric(bars["qfq_high"], errors="coerce").to_numpy(dtype=float)
    )
    low = pd.Series(
        pd.to_numeric(bars["qfq_low"], errors="coerce").to_numpy(dtype=float)
    )
    amount = pd.Series(
        pd.to_numeric(bars["raw_amount"], errors="coerce").to_numpy(dtype=float)
    )
    returns = close.pct_change(fill_method=None)
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    window20 = BAR_WINDOWS["20d"]
    median_amount = amount.rolling(window20, min_periods=window20).median()
    return {
        "stock_return_5": close.pct_change(
            BAR_WINDOWS["5d"], fill_method=None
        ).to_numpy(),
        "stock_return_20": close.pct_change(window20, fill_method=None).to_numpy(),
        "stock_return_60": close.pct_change(
            BAR_WINDOWS["60d"], fill_method=None
        ).to_numpy(),
        # Scale 30-minute return dispersion to a daily-equivalent value.
        "stock_volatility_20": (
            returns.rolling(window20, min_periods=window20).std() * math.sqrt(8)
        ).to_numpy(),
        "stock_atr_20": (
            true_range.rolling(window20, min_periods=window20).mean()
            / close
            * math.sqrt(8)
        ).to_numpy(),
        "stock_drawdown_20": (
            close / close.rolling(window20, min_periods=window20).max() - 1
        ).to_numpy(),
        "stock_above_ma20": (
            close / close.rolling(window20, min_periods=window20).mean() - 1
        ).to_numpy(),
        "stock_above_ma60": (
            close
            / close.rolling(BAR_WINDOWS["60d"], min_periods=BAR_WINDOWS["60d"]).mean()
            - 1
        ).to_numpy(),
        "amount_median_20": median_amount.to_numpy(),
        "amount_ratio_20": (amount / median_amount).to_numpy(),
    }


def compute_code_outcome_map(
    bars: pd.DataFrame,
    reveal_times: Iterable[object],
) -> dict[int, dict[str, Any]]:
    """Efficiently reproduce next-bar and same-slot execution per code."""

    frame = bars.sort_values("bar_at", kind="stable").reset_index(drop=True).copy()
    bar_at = pd.DatetimeIndex(frame["bar_at"])
    if bar_at.tz is None:
        bar_at = bar_at.tz_localize(SHANGHAI_TIMEZONE)
    else:
        bar_at = bar_at.tz_convert(SHANGHAI_TIMEZONE)
    if bar_at.has_duplicates:
        raise RuntimeError("snapshot contains duplicate bar_at")
    times = bar_at.asi8
    trade_dates = [
        value if isinstance(value, date) else pd.Timestamp(value).date()
        for value in frame["trade_date"]
    ]
    session_dates = sorted(set(trade_dates))
    session_index = {
        trade_date: index for index, trade_date in enumerate(session_dates)
    }
    slots = pd.to_numeric(frame["bar_slot"], errors="raise").to_numpy(dtype=int)
    raw_opens = pd.to_numeric(frame["raw_open"], errors="coerce").to_numpy(dtype=float)
    qfq_opens = pd.to_numeric(frame["qfq_open"], errors="coerce").to_numpy(dtype=float)
    prior_closes = pd.to_numeric(
        frame["prior_raw_daily_close"], errors="coerce"
    ).to_numpy(dtype=float)

    outcomes: dict[int, dict[str, Any]] = {}
    unique_reveals = {
        (
            pd.Timestamp(value).tz_localize(SHANGHAI_TIMEZONE)
            if pd.Timestamp(value).tzinfo is None
            else pd.Timestamp(value).tz_convert(SHANGHAI_TIMEZONE)
        )
        for value in reveal_times
    }
    for reveal_at in sorted(unique_reveals):
        reveal_ns = reveal_at.value
        outcome: dict[str, Any] = {
            "reveal_at": reveal_at,
            "entry_executable": False,
            "entry_status": "NO_NEXT_BAR",
        }
        entry_index = int(np.searchsorted(times, reveal_ns, side="right"))
        if entry_index >= len(frame):
            for horizon in HORIZONS:
                outcome[f"h{horizon}_status"] = "NO_NEXT_BAR"
            outcomes[reveal_ns] = outcome
            continue

        entry_raw = float(raw_opens[entry_index])
        entry_qfq = float(qfq_opens[entry_index])
        prior_close = float(prior_closes[entry_index])
        entry_date = trade_dates[entry_index]
        entry_slot = int(slots[entry_index])
        outcome.update(
            {
                "_entry_index": entry_index,
                "entry_at": bar_at[entry_index],
                "entry_trade_date": entry_date,
                "entry_bar_slot": entry_slot,
                "raw_entry_open": entry_raw,
                "qfq_entry_open": entry_qfq,
                "prior_raw_daily_close": prior_close,
            }
        )
        if not (
            math.isfinite(entry_raw)
            and entry_raw > 0
            and math.isfinite(entry_qfq)
            and entry_qfq > 0
            and math.isfinite(prior_close)
            and prior_close > 0
        ):
            outcome["entry_status"] = "INVALID_ENTRY_PRICE"
            for horizon in HORIZONS:
                outcome[f"h{horizon}_status"] = "INVALID_ENTRY_PRICE"
            outcomes[reveal_ns] = outcome
            continue
        entry_gap = entry_raw / prior_close - 1
        outcome["raw_entry_gap"] = entry_gap
        if entry_gap > LIMIT_MOVE:
            outcome["entry_status"] = "ENTRY_LIMIT_UP"
            for horizon in HORIZONS:
                outcome[f"h{horizon}_status"] = "ENTRY_LIMIT_UP"
            outcomes[reveal_ns] = outcome
            continue

        outcome["entry_status"] = "OK"
        outcome["entry_executable"] = True
        entry_session_index = session_index[entry_date]
        for horizon in HORIZONS:
            prefix = f"h{horizon}"
            target_session_index = entry_session_index + horizon
            if target_session_index >= len(session_dates):
                outcome[f"{prefix}_status"] = "CENSORED"
                continue
            target_date = session_dates[target_session_index]
            target_at = pd.Timestamp(
                f"{target_date.isoformat()} {BAR_SLOT_CLOCKS[entry_slot]}",
                tz=SHANGHAI_TIMEZONE,
            )
            candidate_index = int(np.searchsorted(times, target_at.value, side="left"))
            invalid_exit = False
            while candidate_index < len(frame):
                raw_open = float(raw_opens[candidate_index])
                candidate_prior_close = float(prior_closes[candidate_index])
                if not (
                    math.isfinite(raw_open)
                    and raw_open > 0
                    and math.isfinite(candidate_prior_close)
                    and candidate_prior_close > 0
                ):
                    invalid_exit = True
                    break
                if raw_open / candidate_prior_close - 1 <= -LIMIT_MOVE:
                    candidate_index += 1
                    continue
                break
            if candidate_index >= len(frame):
                outcome[f"{prefix}_status"] = "CENSORED_LIMIT_DOWN"
                continue
            if invalid_exit:
                outcome[f"{prefix}_status"] = "INVALID_EXIT_PRICE"
                continue
            exit_qfq = float(qfq_opens[candidate_index])
            if not math.isfinite(exit_qfq) or exit_qfq <= 0:
                outcome[f"{prefix}_status"] = "INVALID_EXIT_PRICE"
                continue
            exit_date = trade_dates[candidate_index]
            exit_slot = int(slots[candidate_index])
            delay = (
                (session_index[exit_date] - target_session_index) * len(BAR_SLOT_CLOCKS)
                + exit_slot
                - entry_slot
            )
            gross_return = exit_qfq / entry_qfq - 1
            net_return = (
                exit_qfq * (1 - FEE_PER_SIDE) / (entry_qfq * (1 + FEE_PER_SIDE)) - 1
            )
            outcome.update(
                {
                    f"{prefix}_status": "OK",
                    f"{prefix}_target_trade_date": target_date,
                    f"{prefix}_exit_at": bar_at[candidate_index],
                    f"{prefix}_exit_trade_date": exit_date,
                    f"{prefix}_exit_bar_slot": exit_slot,
                    f"{prefix}_exit_delay": delay,
                    f"{prefix}_gross_return": gross_return,
                    f"{prefix}_net_return": net_return,
                }
            )
        outcomes[reveal_ns] = outcome
    return outcomes


def build_target_candidate_frame(
    *,
    events: Sequence[Mapping[str, Any]],
    bars: pd.DataFrame,
) -> pd.DataFrame:
    """Keep causal buy facts carrying target concurrent-trigger bits."""

    if not events:
        return pd.DataFrame()
    frame = pd.DataFrame(events)
    frame = frame[frame["actionable"].eq(True) & frame["direction"].eq(1)].copy()
    if frame.empty:
        return frame
    frame["signal_at"] = pd.to_datetime(frame["signal_at"], utc=True).dt.tz_convert(
        SHANGHAI_TIMEZONE
    )
    frame["reveal_at"] = pd.to_datetime(frame["reveal_at"], utc=True).dt.tz_convert(
        SHANGHAI_TIMEZONE
    )
    # Match the daily study's one-model-per-reveal convention.
    frame = (
        frame.sort_values(
            ["code", "model_code", "reveal_at", "signal_at", "revision_no"],
            kind="stable",
        )
        .drop_duplicates(["code", "model_code", "reveal_at"], keep="last")
        .reset_index(drop=True)
    )
    consensus = frame.groupby("reveal_at")["model_code"].transform("nunique")
    frame["same_code_model_count"] = consensus.astype("int16")
    mask = frame["concurrent_trigger_mask"].astype("int64")
    frame = frame.loc[(mask & TARGET_MASK).ne(0)].copy()
    if frame.empty:
        return frame

    sorted_bars = bars.sort_values("bar_at", kind="stable").reset_index(drop=True)
    bar_at = pd.DatetimeIndex(sorted_bars["bar_at"])
    if bar_at.tz is None:
        bar_at = bar_at.tz_localize(SHANGHAI_TIMEZONE)
    else:
        bar_at = bar_at.tz_convert(SHANGHAI_TIMEZONE)
    bar_index = {int(value): index for index, value in enumerate(bar_at.asi8)}
    features = _feature_arrays(sorted_bars)
    outcomes = compute_code_outcome_map(sorted_bars, frame["reveal_at"])

    enriched: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        reveal = pd.Timestamp(row["reveal_at"])
        signal = pd.Timestamp(row["signal_at"])
        reveal_index = bar_index[reveal.value]
        signal_index = bar_index[signal.value]
        outcome = dict(outcomes[reveal.value])
        entry_index = outcome.pop("_entry_index", None)
        values: dict[str, Any] = {
            name: float(array[reveal_index]) for name, array in features.items()
        }
        values.update(
            {
                "reveal_bar_slot": int(sorted_bars.at[reveal_index, "bar_slot"]),
                "signal_bar_slot": int(sorted_bars.at[signal_index, "bar_slot"]),
                "signal_age_bars": reveal_index - signal_index,
                "source_duplicate_count_at_reveal": int(
                    sorted_bars.at[reveal_index, "source_duplicate_count"]
                ),
                "concurrent_trigger_count": int(
                    int(row["concurrent_trigger_mask"]).bit_count()
                ),
                "reveal_trade_date": reveal.date(),
                "split_id": _research_split(reveal),
                "entry_overnight": (
                    bool(
                        entry_index is not None
                        and sorted_bars.at[entry_index, "trade_date"] > reveal.date()
                    )
                    if entry_index is not None
                    else None
                ),
                "entry_delay_bars": (
                    int(entry_index - reveal_index) if entry_index is not None else None
                ),
            }
        )
        enriched.append({**row, **values, **outcome})

    base = pd.DataFrame(enriched)
    expanded: list[pd.DataFrame] = []
    mask = base["concurrent_trigger_mask"].astype("int64")
    for trigger, bit in TARGET_TRIGGER_BITS.items():
        selected = base.loc[(mask & bit).ne(0)].copy()
        selected["target_trigger"] = trigger
        expanded.append(selected)
    return (
        pd.concat(expanded, ignore_index=True)
        .sort_values(
            ["code", "reveal_at", "model_code", "target_trigger"],
            kind="stable",
        )
        .reset_index(drop=True)
    )


def _replay_code_paths(root: Path, code: str) -> tuple[Path, Path]:
    return (
        root / "replay" / "candidates" / f"{code}.parquet",
        root / "replay" / "checkpoints" / f"{code}.json",
    )


def replay_one_code(
    *,
    root: str,
    code: str,
    snapshot_file_sha256: str,
    signal_set_id: str,
    options: Mapping[str, int],
) -> dict[str, Any]:
    output_root = Path(root)
    data_path, meta_path = _replay_code_paths(output_root, code)
    existing = _valid_checkpoint(
        data_path=data_path,
        meta_path=meta_path,
        identity_key="signal_set_id",
        identity_value=signal_set_id,
    )
    if (
        existing is not None
        and existing.get("snapshot_file_sha256") == snapshot_file_sha256
    ):
        return {**existing, "checkpoint_status": "REUSED"}

    snapshot_path, _ = _snapshot_code_paths(output_root, code)
    if sha256_file(snapshot_path) != snapshot_file_sha256:
        raise RuntimeError(f"{code} snapshot file hash changed")
    bars = pd.read_parquet(snapshot_path)
    started = time.perf_counter()
    engine = FqCopilotClxEngine()
    if not engine.supports_detailed_output:
        raise RuntimeError("native fqcopilot lacks fq_clxs_all_detailed")
    engine_options = ClxEngineOptions(**dict(options))
    events = replay_prefix_events(
        bars=bars,
        engine=engine,
        signal_set_id=signal_set_id,
        options=engine_options,
        code=code,
    )
    candidates = build_target_candidate_frame(events=events, bars=bars)
    write_frame_atomic(candidates, data_path)
    meta = {
        "code": code,
        "signal_set_id": signal_set_id,
        "snapshot_file_sha256": snapshot_file_sha256,
        "logical_path": f"replay/candidates/{code}.parquet",
        "source_bar_rows": len(bars),
        "prefix_calls": len(bars),
        "revision_event_rows": len(events),
        "candidate_rows": len(candidates),
        "file_size": data_path.stat().st_size,
        "file_sha256": sha256_file(data_path),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json_atomic(meta_path, meta)
    return {**meta, "checkpoint_status": "BUILT"}


def _engine_identity() -> dict[str, Any]:
    backend = importlib.import_module("fqcopilot")
    path = Path(str(backend.__file__)).resolve()
    detailed = callable(getattr(backend, "fq_clxs_all_detailed", None))
    if not detailed:
        raise RuntimeError("native fqcopilot lacks fq_clxs_all_detailed")
    return {
        "module": "fqcopilot",
        "path_name": path.name,
        "file_size": path.stat().st_size,
        "file_sha256": sha256_file(path),
        "detailed_output": detailed,
    }


def _module_file_identity(module_name: str) -> dict[str, Any]:
    module = importlib.import_module(module_name)
    path = Path(str(module.__file__)).resolve()
    return {
        "module": module_name,
        "path_name": path.name,
        "file_size": path.stat().st_size,
        "file_sha256": sha256_file(path),
    }


def _replay_logic_sha256() -> str:
    functions = (
        _feature_arrays,
        compute_code_outcome_map,
        build_target_candidate_frame,
        replay_one_code,
    )
    return sha256_bytes(
        "\n\n".join(inspect.getsource(function) for function in functions).encode(
            "utf-8"
        )
    )


def _selected_snapshot_metas(
    manifest: Mapping[str, Any],
    requested_codes: Sequence[str],
    code_limit: int | None,
) -> list[dict[str, Any]]:
    metas = [dict(meta) for meta in manifest["code_files"] if int(meta["rows"]) > 0]
    if requested_codes:
        requested = {str(code) for code in requested_codes}
        missing = requested - {str(meta["code"]) for meta in metas}
        if missing:
            raise RuntimeError(
                f"requested codes absent from snapshot: {sorted(missing)}"
            )
        metas = [meta for meta in metas if str(meta["code"]) in requested]
    if code_limit is not None:
        metas = metas[:code_limit]
    return metas


def run_replay(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    snapshot_manifest_path = root / "snapshot" / "manifest.json"
    snapshot_manifest = _read_json(snapshot_manifest_path)
    engine_identity = _engine_identity()
    options = {
        "wave_opt": args.wave_opt,
        "stretch_opt": args.stretch_opt,
        "trend_opt": args.trend_opt,
    }
    signal_contract = {
        "study_id": STUDY_ID,
        "signal_replay_contract_version": SIGNAL_REPLAY_CONTRACT_VERSION,
        "snapshot_id": snapshot_manifest["snapshot_id"],
        "snapshot_manifest_sha256": sha256_file(snapshot_manifest_path),
        "engine_identity": engine_identity,
        "python_adapter_identities": [
            _module_file_identity("freshquant.backtest.clx.engine"),
            _module_file_identity("freshquant.backtest.clx.intraday"),
        ],
        "replay_logic_sha256": _replay_logic_sha256(),
        "engine_options": options,
        "causal_route": "EXACT_FROM_ZERO_PREFIX_PER_30MIN_BAR",
        "persistent_direction": "BUY_ONLY",
        "persistent_target_mask": TARGET_MASK,
        "signal_clock": "signal_at",
        "reveal_clock": "reveal_at",
    }
    signal_set_id = "sha256:" + sha256_bytes(canonical_json_bytes(signal_contract))
    metas = _selected_snapshot_metas(
        snapshot_manifest,
        args.code,
        args.code_limit,
    )
    if not metas:
        raise RuntimeError("no non-empty snapshot codes selected")
    progress_path = root / "replay" / "progress.json"
    outputs: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                replay_one_code,
                root=str(root),
                code=str(meta["code"]),
                snapshot_file_sha256=str(meta["file_sha256"]),
                signal_set_id=signal_set_id,
                options=options,
            ): str(meta["code"])
            for meta in metas
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            code = futures[future]
            try:
                outputs[code] = future.result()
            except Exception as exc:  # noqa: BLE001 - persisted worker boundary
                failures[code] = f"{type(exc).__name__}: {exc}"
            elapsed = time.perf_counter() - started
            progress = {
                "phase": "replay",
                "signal_set_id": signal_set_id,
                "total_codes": len(metas),
                "completed_codes": completed,
                "successful_codes": len(outputs),
                "failed_codes": len(failures),
                "elapsed_seconds": round(elapsed, 3),
                "codes_per_hour": (
                    round(completed / elapsed * 3600, 3) if elapsed > 0 else None
                ),
                "estimated_remaining_seconds": (
                    round((len(metas) - completed) * elapsed / completed, 3)
                    if completed
                    else None
                ),
                "failures": failures,
            }
            write_json_atomic(progress_path, progress)
            print(json.dumps(progress, ensure_ascii=False), flush=True)

    if failures:
        raise RuntimeError(
            f"replay failed for {len(failures)} codes; inspect {progress_path}"
        )
    ordered = [
        {
            key: value
            for key, value in outputs[str(meta["code"])].items()
            if key not in {"checkpoint_status", "elapsed_seconds"}
        }
        for meta in metas
    ]
    manifest: dict[str, Any] = {
        "study_id": STUDY_ID,
        "signal_set_id": signal_set_id,
        "signal_contract": signal_contract,
        "selected_code_count": len(metas),
        "complete_snapshot_universe": (
            len(metas)
            == sum(int(meta["rows"]) > 0 for meta in snapshot_manifest["code_files"])
        ),
        "prefix_calls": sum(int(meta["prefix_calls"]) for meta in ordered),
        "revision_event_rows": sum(
            int(meta["revision_event_rows"]) for meta in ordered
        ),
        "candidate_rows": sum(int(meta["candidate_rows"]) for meta in ordered),
        "code_files": ordered,
    }
    manifest_path = root / "replay" / "manifest.json"
    write_json_atomic(manifest_path, manifest)
    result = {
        "replay_manifest": str(manifest_path),
        "signal_set_id": signal_set_id,
        "code_count": len(metas),
        "prefix_calls": manifest["prefix_calls"],
        "candidate_rows": manifest["candidate_rows"],
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


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
        "同股同揭示bar模型共识≥2",
        "model_consensus",
        lambda frame: frame["same_code_model_count"].ge(2),
    ),
    FilterRule(
        "same_code_models_ge_3",
        "同股同揭示bar模型共识≥3",
        "model_consensus",
        lambda frame: frame["same_code_model_count"].ge(3),
    ),
    FilterRule(
        "same_code_models_ge_4",
        "同股同揭示bar模型共识≥4",
        "model_consensus",
        lambda frame: frame["same_code_model_count"].ge(4),
    ),
    FilterRule(
        "both_target_patterns",
        "吞没与强分型同K线共振",
        "target_concurrence",
        lambda frame: (
            frame["concurrent_trigger_mask"].astype("int64") & TARGET_MASK
        ).eq(TARGET_MASK),
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
        "reveal_morning",
        "上午揭示",
        "time_of_day",
        lambda frame: frame["reveal_bar_slot"].le(3),
    ),
    FilterRule(
        "reveal_afternoon",
        "下午揭示",
        "time_of_day",
        lambda frame: frame["reveal_bar_slot"].ge(4),
    ),
    FilterRule(
        "reveal_first_hour",
        "10:00或10:30揭示",
        "time_of_day",
        lambda frame: frame["reveal_bar_slot"].le(1),
    ),
    FilterRule(
        "reveal_late",
        "14:30或15:00揭示",
        "time_of_day",
        lambda frame: frame["reveal_bar_slot"].ge(6),
    ),
    FilterRule(
        "entry_same_day",
        "同日下一bar入场",
        "entry_clock",
        lambda frame: frame["entry_overnight"].eq(False),
    ),
    FilterRule(
        "entry_overnight",
        "隔夜下一bar入场",
        "entry_clock",
        lambda frame: frame["entry_overnight"].eq(True),
    ),
    FilterRule(
        "signal_age_le_2",
        "信号在2根bar内揭示",
        "revision_age",
        lambda frame: frame["signal_age_bars"].le(2),
    ),
    FilterRule(
        "signal_age_ge_3",
        "信号延迟至少3根bar揭示",
        "revision_age",
        lambda frame: frame["signal_age_bars"].ge(3),
    ),
    FilterRule(
        "entry_vs_prior_close_nonpositive",
        "入场价不高于昨收",
        "entry_gap",
        lambda frame: _finite(frame["raw_entry_gap"]).le(0),
    ),
    FilterRule(
        "entry_vs_prior_close_le_3pct",
        "入场价相对昨收涨幅≤3%",
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
        "个股近160根收益≤0",
        "stock_momentum_20",
        lambda frame: _finite(frame["stock_return_20"]).le(0),
    ),
    FilterRule(
        "stock20_pullback_10",
        "个股近160根收益≤-10%",
        "stock_momentum_20",
        lambda frame: _finite(frame["stock_return_20"]).le(-0.10),
    ),
    FilterRule(
        "stock20_pos",
        "个股近160根收益>0",
        "stock_momentum_20",
        lambda frame: _finite(frame["stock_return_20"]).gt(0),
    ),
    FilterRule(
        "stock60_neg",
        "个股近480根收益≤0",
        "stock_momentum_60",
        lambda frame: _finite(frame["stock_return_60"]).le(0),
    ),
    FilterRule(
        "stock60_pos",
        "个股近480根收益>0",
        "stock_momentum_60",
        lambda frame: _finite(frame["stock_return_60"]).gt(0),
    ),
    FilterRule(
        "drawdown20_ge_10pct",
        "距近160根高点回撤≥10%",
        "drawdown",
        lambda frame: _finite(frame["stock_drawdown_20"]).le(-0.10),
    ),
    FilterRule(
        "drawdown20_ge_15pct",
        "距近160根高点回撤≥15%",
        "drawdown",
        lambda frame: _finite(frame["stock_drawdown_20"]).le(-0.15),
    ),
    FilterRule(
        "vol20_ge_3pct",
        "近160根日化波动率≥3%",
        "volatility",
        lambda frame: _finite(frame["stock_volatility_20"]).ge(0.03),
    ),
    FilterRule(
        "vol20_2_6pct",
        "近160根日化波动率2%～6%",
        "volatility",
        lambda frame: _finite(frame["stock_volatility_20"]).between(0.02, 0.06),
    ),
    FilterRule(
        "vol20_le_4pct",
        "近160根日化波动率≤4%",
        "volatility",
        lambda frame: _finite(frame["stock_volatility_20"]).le(0.04),
    ),
    FilterRule(
        "below_ma20",
        "个股位于MA160下方",
        "stock_trend",
        lambda frame: _finite(frame["stock_above_ma20"]).le(0),
    ),
    FilterRule(
        "above_ma20",
        "个股位于MA160上方",
        "stock_trend",
        lambda frame: _finite(frame["stock_above_ma20"]).gt(0),
    ),
    FilterRule(
        "below_ma60",
        "个股位于MA480下方",
        "stock_trend",
        lambda frame: _finite(frame["stock_above_ma60"]).le(0),
    ),
    FilterRule(
        "above_ma60",
        "个股位于MA480上方",
        "stock_trend",
        lambda frame: _finite(frame["stock_above_ma60"]).gt(0),
    ),
    FilterRule(
        "amount20_ge_10m",
        "近160根中位成交额≥1000万",
        "liquidity",
        lambda frame: _finite(frame["amount_median_20"]).ge(10_000_000),
    ),
    FilterRule(
        "amount20_ge_30m",
        "近160根中位成交额≥3000万",
        "liquidity",
        lambda frame: _finite(frame["amount_median_20"]).ge(30_000_000),
    ),
    FilterRule(
        "amount_ratio_ge_15",
        "当前成交额≥近160根中位数1.5倍",
        "volume_expansion",
        lambda frame: _finite(frame["amount_ratio_20"]).ge(1.5),
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
        "target_crowding_z_le_0",
        "全市场双形态买入拥挤度≤过去63日均值",
        "signal_crowding",
        lambda frame: _finite(frame["market_target_buy_count_z504"]).le(0),
    ),
)
RULE_BY_NAME = {rule.name: rule for rule in FILTER_RULES}


def _rule_sets() -> list[tuple[str, ...]]:
    sets: list[tuple[str, ...]] = [()]
    sets.extend((rule.name,) for rule in FILTER_RULES)
    for left, right in itertools.combinations(FILTER_RULES, 2):
        if left.family != right.family:
            sets.append((left.name, right.name))
    return sets


def _scope_outcome_mask(
    frame: pd.DataFrame,
    horizon: int,
    scope: str,
) -> np.ndarray:
    valid = frame[f"h{horizon}_status"].eq("OK").to_numpy(dtype=bool)
    if scope == "FULL":
        return valid
    if scope not in SPLIT_RANGES:
        raise ValueError(f"unknown scope {scope}")
    selected = frame["split_id"].eq(scope).to_numpy(dtype=bool)
    exit_dates = pd.to_datetime(frame[f"h{horizon}_exit_trade_date"], errors="coerce")
    split_end = pd.Timestamp(SPLIT_RANGES[scope][1])
    within_boundary = exit_dates.le(split_end).fillna(False).to_numpy(dtype=bool)
    return valid & selected & within_boundary


def _metrics_from_mask(
    frame: pd.DataFrame,
    filter_mask: np.ndarray,
    horizon: int,
    scope: str,
) -> dict[str, Any]:
    cached_column = f"_eligible_{scope.lower()}_h{horizon}"
    outcome_mask = (
        frame[cached_column].to_numpy(dtype=bool)
        if cached_column in frame.columns
        else _scope_outcome_mask(frame, horizon, scope)
    )
    values = frame.loc[
        filter_mask & outcome_mask,
        f"h{horizon}_net_return",
    ].to_numpy(dtype=float)
    return return_metrics(values)


def build_win_rate_table(events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scope, model_code, trigger, regime, horizon in itertools.product(
        ("FULL", "TRAIN", "VALIDATION", "HOLDOUT"),
        MODEL_CODES,
        TARGET_TRIGGER_BITS,
        REGIMES,
        HORIZONS,
    ):
        subset = events[
            events["model_code"].eq(model_code)
            & events["target_trigger"].eq(trigger)
            & events["market_regime"].eq(regime)
        ].reset_index(drop=True)
        filter_mask = np.ones(len(subset), dtype=bool)
        metrics = _metrics_from_mask(subset, filter_mask, horizon, scope)
        scope_rows = (
            subset["split_id"].eq(scope)
            if scope != "FULL"
            else pd.Series(True, index=subset.index)
        )
        status_ok = subset[f"h{horizon}_status"].eq("OK")
        if scope == "FULL":
            purged = 0
        else:
            split_end = pd.Timestamp(SPLIT_RANGES[scope][1])
            exits = pd.to_datetime(
                subset[f"h{horizon}_exit_trade_date"], errors="coerce"
            )
            purged = int((scope_rows & status_ok & exits.gt(split_end)).sum())
        rows.append(
            {
                "scope": scope,
                "model_code": model_code,
                "trigger": trigger,
                "market_regime": regime,
                "horizon_trading_days": horizon,
                "purged_boundary_count": purged,
                **metrics,
            }
        )
    return pd.DataFrame(rows)


def _train_score(
    frame: pd.DataFrame,
    mask: np.ndarray,
    horizon: int,
    complexity: int,
) -> tuple[float, dict[str, Any]] | None:
    full = _metrics_from_mask(frame, mask, horizon, "TRAIN")
    if full["sample_count"] < 60:
        return None
    fold_rates: list[float] = []
    fold_counts: list[int] = []
    for fold_id in (1, 2):
        fold_mask = mask & frame[f"_train_fold_h{horizon}"].eq(fold_id).to_numpy(
            dtype=bool
        )
        fold = _metrics_from_mask(frame, fold_mask, horizon, "TRAIN")
        if fold["sample_count"] < 20:
            return None
        fold_rates.append(float(fold["win_rate"]))
        fold_counts.append(int(fold["sample_count"]))
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


def _validation_score(metrics: Mapping[str, Any], complexity: int) -> float:
    return (
        float(metrics["win_rate_ci_low"])
        + 0.20 * float(np.clip(metrics["mean_net_return"], -0.10, 0.10))
        - 0.004 * complexity
    )


def search_filters(events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    events = events.copy()
    for scope in ("TRAIN", "VALIDATION", "HOLDOUT"):
        for horizon in HORIZONS:
            events[f"_eligible_{scope.lower()}_h{horizon}"] = _scope_outcome_mask(
                events, horizon, scope
            )
    recommendations: list[dict[str, Any]] = []
    audit: dict[str, Any] = {}
    all_rule_sets = _rule_sets()
    for model_code, trigger in itertools.product(MODEL_CODES, TARGET_TRIGGER_BITS):
        group_id = f"{model_code}|{trigger}"
        recommendation: dict[str, Any]
        frame = events[
            events["model_code"].eq(model_code) & events["target_trigger"].eq(trigger)
        ].reset_index(drop=True)
        if frame.empty:
            recommendation = {
                "model_code": model_code,
                "trigger": trigger,
                "selection_status": "INSUFFICIENT_SAMPLE",
                "holdout_status": "INSUFFICIENT_SAMPLE",
            }
            recommendations.append(recommendation)
            audit[group_id] = {
                "status": "INSUFFICIENT_SAMPLE",
                "top_candidates": [],
            }
            continue
        frame_reveal = pd.to_datetime(frame["reveal_at"], utc=True).dt.tz_convert(
            SHANGHAI_TIMEZONE
        )
        for horizon in HORIZONS:
            eligible = frame[f"_eligible_train_h{horizon}"].to_numpy(dtype=bool)
            eligible_dates = np.sort(frame_reveal.loc[eligible].unique())
            folds = np.zeros(len(frame), dtype=np.int8)
            if len(eligible_dates) >= 2:
                split_at = eligible_dates[(len(eligible_dates) - 1) // 2]
                folds[eligible & frame_reveal.le(split_at).to_numpy(dtype=bool)] = 1
                folds[eligible & frame_reveal.gt(split_at).to_numpy(dtype=bool)] = 2
            frame[f"_train_fold_h{horizon}"] = folds
        rule_masks = {
            rule.name: rule.predicate(frame).fillna(False).to_numpy(dtype=bool)
            for rule in FILTER_RULES
        }
        base_mask = np.ones(len(frame), dtype=bool)
        horizon_shortlists: list[dict[str, Any]] = []
        for horizon in HORIZONS:
            trained_candidates: list[dict[str, Any]] = []
            for names in all_rule_sets:
                mask = base_mask.copy()
                for name in names:
                    mask &= rule_masks[name]
                trained = _train_score(frame, mask, horizon, len(names))
                if trained is None:
                    continue
                score, metrics = trained
                trained_candidates.append(
                    {
                        "rules": names,
                        "mask": mask,
                        "train_score": score,
                        "train_metrics": metrics,
                    }
                )
            trained_candidates.sort(
                key=lambda item: (
                    item["train_score"],
                    -len(item["rules"]),
                    item["rules"],
                ),
                reverse=True,
            )
            shortlist = trained_candidates[:12]
            baseline = next(
                (item for item in trained_candidates if not item["rules"]),
                None,
            )
            if baseline is not None and not any(
                not item["rules"] for item in shortlist
            ):
                shortlist.append(baseline)
            baseline_validation = _metrics_from_mask(
                frame, base_mask, horizon, "VALIDATION"
            )
            for candidate in shortlist:
                validation = _metrics_from_mask(
                    frame,
                    candidate["mask"],
                    horizon,
                    "VALIDATION",
                )
                minimum_validation = max(
                    50,
                    math.ceil(baseline_validation["sample_count"] * 0.03),
                )
                if validation["sample_count"] < minimum_validation:
                    continue
                item = dict(candidate)
                item["horizon"] = horizon
                item["validation_metrics"] = validation
                item["validation_score"] = _validation_score(
                    validation, len(item["rules"])
                )
                item["baseline_validation_metrics"] = baseline_validation
                horizon_shortlists.append(item)

        horizon_shortlists.sort(
            key=lambda item: (
                item["validation_score"],
                item["train_score"],
                -len(item["rules"]),
            ),
            reverse=True,
        )
        baseline_choices = [item for item in horizon_shortlists if not item["rules"]]
        filtered_choices = [
            item
            for item in horizon_shortlists
            if item["rules"]
            and item["validation_metrics"]["win_rate"]
            >= item["baseline_validation_metrics"]["win_rate"] + 0.02
            and item["validation_metrics"]["mean_net_return"] > 0
        ]
        selected = (
            filtered_choices[0]
            if filtered_choices
            else (baseline_choices[0] if baseline_choices else None)
        )
        if selected is None:
            recommendation = {
                "model_code": model_code,
                "trigger": trigger,
                "selection_status": "INSUFFICIENT_SAMPLE",
                "holdout_status": "INSUFFICIENT_SAMPLE",
            }
            recommendations.append(recommendation)
            audit[group_id] = {
                "status": "INSUFFICIENT_SAMPLE",
                "top_candidates": [],
            }
            continue

        horizon = int(selected["horizon"])
        rules = tuple(selected["rules"])
        validation = selected["validation_metrics"]
        baseline_validation = selected["baseline_validation_metrics"]
        holdout = _metrics_from_mask(frame, selected["mask"], horizon, "HOLDOUT")
        baseline_holdout = _metrics_from_mask(frame, base_mask, horizon, "HOLDOUT")
        if not rules:
            selection_status = "NO_STABLE_FILTER"
            holdout_status = "NOT_APPLICABLE"
        elif holdout["sample_count"] < 50:
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
            "horizon_trading_days": horizon,
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
        audit[group_id] = {
            "status": selection_status,
            "selected": recommendation,
            "top_candidates": [
                {
                    "horizon_trading_days": item["horizon"],
                    "rule_names": list(item["rules"]),
                    "rule_labels": [RULE_BY_NAME[name].label for name in item["rules"]],
                    "train_score": round(float(item["train_score"]), 8),
                    "train_metrics": item["train_metrics"],
                    "validation_score": round(float(item["validation_score"]), 8),
                    "validation_metrics": item["validation_metrics"],
                    "baseline_validation_metrics": item["baseline_validation_metrics"],
                }
                for item in horizon_shortlists[:10]
            ],
        }
    return pd.DataFrame(recommendations), audit


def _attach_target_crowding(events: pd.DataFrame, index: pd.DataFrame) -> pd.DataFrame:
    frame = events.copy()
    unique = frame.drop_duplicates("signal_fact_id")
    counts = unique.groupby("reveal_at").size()
    min_date = pd.Timestamp(frame["reveal_at"].min()).date()
    max_date = pd.Timestamp(frame["reveal_at"].max()).date()
    trading_dates = [
        pd.Timestamp(value).date()
        for value in index["date"]
        if min_date <= pd.Timestamp(value).date() <= max_date
    ]
    timeline = pd.DatetimeIndex(
        [
            pd.Timestamp(
                f"{trade_date.isoformat()} {clock}",
                tz=SHANGHAI_TIMEZONE,
            )
            for trade_date in trading_dates
            for clock in BAR_SLOT_CLOCKS
        ]
    )
    crowding = pd.DataFrame(index=timeline)
    crowding["market_target_buy_count"] = counts.reindex(timeline, fill_value=0)
    history = crowding["market_target_buy_count"].shift(1)
    mean = history.rolling(504, min_periods=160).mean()
    std = history.rolling(504, min_periods=160).std().replace(0, np.nan)
    crowding["market_target_buy_count_z504"] = (
        crowding["market_target_buy_count"] - mean
    ) / std
    mapping_count = crowding["market_target_buy_count"].to_dict()
    mapping_z = crowding["market_target_buy_count_z504"].to_dict()
    frame["market_target_buy_count"] = frame["reveal_at"].map(mapping_count)
    frame["market_target_buy_count_z504"] = frame["reveal_at"].map(mapping_z)
    return frame


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
                "horizon_trading_days": horizon,
                **return_metrics(
                    subset[f"h{horizon}_net_return"].to_numpy(dtype=float)
                ),
            }
        )
    return rows


def _load_replay_candidates(
    *,
    root: Path,
    snapshot_manifest: Mapping[str, Any],
    allow_partial: bool,
) -> tuple[pd.DataFrame, list[dict[str, Any]], list[str]]:
    expected_codes = [
        str(meta["code"])
        for meta in snapshot_manifest["code_files"]
        if int(meta["rows"]) > 0
    ]
    frames: list[pd.DataFrame] = []
    metas: list[dict[str, Any]] = []
    missing: list[str] = []
    for code in expected_codes:
        path, meta_path = _replay_code_paths(root, code)
        if not path.is_file() or not meta_path.is_file():
            missing.append(code)
            continue
        meta = _read_json(meta_path)
        if meta.get("file_sha256") != sha256_file(path):
            raise RuntimeError(f"{code} replay candidate hash mismatch")
        metas.append(meta)
        if int(meta["candidate_rows"]) > 0:
            frames.append(pd.read_parquet(path))
    if missing and not allow_partial:
        raise RuntimeError(
            f"replay is incomplete: {len(missing)} codes have no checkpoint"
        )
    if not frames:
        raise RuntimeError("no replay candidate rows to aggregate")
    signal_set_ids = {str(meta.get("signal_set_id")) for meta in metas}
    if len(signal_set_ids) != 1:
        raise RuntimeError(
            f"replay checkpoints mix signal sets: {sorted(signal_set_ids)}"
        )
    return pd.concat(frames, ignore_index=True), metas, missing


def run_aggregate(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    snapshot_manifest_path = root / "snapshot" / "manifest.json"
    snapshot_manifest = _read_json(snapshot_manifest_path)
    events, replay_metas, missing_codes = _load_replay_candidates(
        root=root,
        snapshot_manifest=snapshot_manifest,
        allow_partial=args.allow_partial,
    )
    events["signal_at"] = pd.to_datetime(events["signal_at"], utc=True).dt.tz_convert(
        SHANGHAI_TIMEZONE
    )
    events["reveal_at"] = pd.to_datetime(events["reveal_at"], utc=True).dt.tz_convert(
        SHANGHAI_TIMEZONE
    )
    index_source = pd.read_parquet(root / "snapshot" / "index_day.parquet")
    index = classify_market_regimes(index_source)
    events = attach_previous_session_regimes(events, index)
    events = _attach_target_crowding(events, index)
    if (
        (
            pd.to_datetime(events["index_feature_date"]).dt.date
            >= events["reveal_at"].dt.date
        )
        .fillna(False)
        .any()
    ):
        raise RuntimeError("future or same-session index regime join detected")

    aggregate_dir = root / "aggregate"
    aggregate_dir.mkdir(parents=True, exist_ok=True)
    segments = build_market_segments(index)
    signal_min_date = events["reveal_at"].min().date().isoformat()
    signal_max_date = events["reveal_at"].max().date().isoformat()
    segments = segments[
        segments["end_date"].ge(signal_min_date)
        & segments["start_date"].le(signal_max_date)
    ].reset_index(drop=True)
    win_rates = build_win_rate_table(events)
    recommendations, filter_audit = search_filters(events)

    output_paths = {
        "candidate_events": aggregate_dir / "candidate_events.parquet",
        "market_segments": aggregate_dir / "market_segments.csv",
        "regime_win_rates": aggregate_dir / "regime_win_rates.csv",
        "filter_recommendations": aggregate_dir / "filter_recommendations.csv",
        "filter_search_audit": aggregate_dir / "filter_search_audit.json",
        "summary": aggregate_dir / "summary.json",
    }
    write_frame_atomic(events, output_paths["candidate_events"])
    segments.to_csv(output_paths["market_segments"], index=False, encoding="utf-8")
    win_rates.to_csv(output_paths["regime_win_rates"], index=False, encoding="utf-8")
    recommendations.to_csv(
        output_paths["filter_recommendations"],
        index=False,
        encoding="utf-8",
    )
    write_json_atomic(output_paths["filter_search_audit"], filter_audit)

    model_coverage = sorted(events["model_code"].unique())
    future_index_joins = int(
        (
            pd.to_datetime(events["index_feature_date"]).dt.date
            >= events["reveal_at"].dt.date
        )
        .fillna(False)
        .sum()
    )
    expected_rows = (
        4 * len(MODEL_CODES) * len(TARGET_TRIGGER_BITS) * len(REGIMES) * len(HORIZONS)
    )
    summary = {
        "study_id": STUDY_ID,
        "evidence_grade": "SHORT_HISTORY_PROVISIONAL",
        "requested_research_period": ["2015-01-01", "LATEST"],
        "available_stock_30m_period": [
            snapshot_manifest["config"]["start_date"],
            snapshot_manifest["config"]["end_date"],
        ],
        "signal_period": [signal_min_date, signal_max_date],
        "history_gap": (
            "QuantAxis stock_min/type=30min begins on 2024-04-15; "
            "the 2015-present stock study requires an older source backfill"
        ),
        "contracts": {
            "market_regime": {
                "source": "quantaxis.index_day/code=000001",
                "clock": "latest index session strictly before reveal trade date",
                "up": "return_60>=5% and close>=MA60",
                "down": "return_60<=-5% and close<=MA60",
                "sideways": "otherwise",
                "confirmation_sessions": 5,
            },
            "target_trigger_membership": (
                "BUY actionable fact and concurrent_trigger_mask bits 0x04/0x08; "
                "one fact may expand into both trigger groups"
            ),
            "causality": "exact from-zero prefix replay at every actual 30min bar",
            "entry": "first actual stock 30min bar strictly after reveal_at",
            "exit": (
                "entry stock-session +30/+60/+90, same bar slot open; "
                "missing slot or limit-down advances to the next actual bar"
            ),
            "return_price_domain": "QFQ raw_price * stock_adj.adj",
            "execution_price_domain": "RAW open vs prior stock_day close",
            "fee_per_side": FEE_PER_SIDE,
            "limit_move": LIMIT_MOVE,
            "feature_bar_windows": BAR_WINDOWS,
            "splits": {
                name: [start.isoformat(), end.isoformat()]
                for name, (start, end) in SPLIT_RANGES.items()
            },
            "purge": (
                "for each horizon, an outcome crossing its split end is excluded "
                "from that split; maximum purge horizon is 90 stock trading days"
            ),
            "max_filter_conditions": 2,
        },
        "coverage": {
            "snapshot_codes": snapshot_manifest["universe"]["code_count"],
            "replayed_codes": len(replay_metas),
            "missing_codes": missing_codes,
            "partial_aggregate": bool(missing_codes),
            "candidate_rows": len(events),
            "unique_signal_facts": int(events["signal_fact_id"].nunique()),
            "models": model_coverage,
            "model_count": len(model_coverage),
            "target_trigger_count": int(events["target_trigger"].nunique()),
        },
        "source_quality": snapshot_manifest["source_quality"],
        "invariants": {
            "future_or_same_session_index_joins": future_index_joins,
            "win_rate_table_rows": len(win_rates),
            "expected_win_rate_table_rows": expected_rows,
        },
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
    write_json_atomic(output_paths["summary"], summary)
    output_files = {
        name: {
            "path": path.name,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for name, path in output_paths.items()
    }
    manifest: dict[str, Any] = {
        "study_id": STUDY_ID,
        "aggregate_contract_version": AGGREGATE_CONTRACT_VERSION,
        "aggregate_script_sha256": sha256_file(Path(__file__).resolve()),
        "snapshot_id": snapshot_manifest["snapshot_id"],
        "signal_set_id": replay_metas[0]["signal_set_id"],
        "snapshot_manifest_sha256": sha256_file(snapshot_manifest_path),
        "replay_code_files": [
            {
                "code": meta["code"],
                "file_sha256": meta["file_sha256"],
                "candidate_rows": meta["candidate_rows"],
            }
            for meta in replay_metas
        ],
        "missing_codes": missing_codes,
        "outputs": output_files,
        "summary_invariants": summary["invariants"],
    }
    manifest_path = aggregate_dir / "manifest.json"
    write_json_atomic(manifest_path, manifest)
    result = {
        "aggregate_manifest": str(manifest_path),
        "evidence_grade": summary["evidence_grade"],
        "candidate_rows": len(events),
        "confirmed_filter_count": len(summary["confirmed_filters"]),
        "partial_aggregate": bool(missing_codes),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def run_status(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    snapshot_manifest_path = root / "snapshot" / "manifest.json"
    snapshot_manifest = (
        _read_json(snapshot_manifest_path) if snapshot_manifest_path.is_file() else None
    )
    expected_codes = (
        [
            str(meta["code"])
            for meta in snapshot_manifest["code_files"]
            if int(meta["rows"]) > 0
        ]
        if snapshot_manifest
        else []
    )
    replayed = [
        code for code in expected_codes if _replay_code_paths(root, code)[1].is_file()
    ]
    progress_path = root / "replay" / "progress.json"
    result = {
        "study_id": STUDY_ID,
        "root": str(root),
        "snapshot_complete": snapshot_manifest is not None,
        "snapshot_codes": len(expected_codes),
        "replay_completed_codes": len(replayed),
        "replay_remaining_codes": len(expected_codes) - len(replayed),
        "replay_progress": (
            _read_json(progress_path) if progress_path.is_file() else None
        ),
        "aggregate_complete": (root / "aggregate" / "manifest.json").is_file(),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def _positive_workers(value: str) -> int:
    workers = int(value)
    if workers <= 0:
        raise argparse.ArgumentTypeError("workers must be positive")
    return workers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument(
        "--mongo-uri",
        default="mongodb://fq_mongodb:27017",
    )
    snapshot.add_argument("--start-date", default=DEFAULT_START_DATE)
    snapshot.add_argument("--end-date", default=DEFAULT_END_DATE)
    snapshot.add_argument(
        "--workers",
        type=_positive_workers,
        default=8,
    )
    snapshot.add_argument("--code", action="append", default=[])
    snapshot.add_argument("--code-limit", type=int)
    snapshot.set_defaults(handler=run_snapshot)

    replay = subparsers.add_parser("replay")
    replay.add_argument(
        "--workers",
        type=_positive_workers,
        default=max(1, (os.cpu_count() or 2) - 2),
    )
    replay.add_argument("--code", action="append", default=[])
    replay.add_argument("--code-limit", type=int)
    replay.add_argument("--wave-opt", type=int, default=1560)
    replay.add_argument("--stretch-opt", type=int, default=0)
    replay.add_argument("--trend-opt", type=int, default=0)
    replay.set_defaults(handler=run_replay)

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--allow-partial", action="store_true")
    aggregate.set_defaults(handler=run_aggregate)

    status = subparsers.add_parser("status")
    status.set_defaults(handler=run_status)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
