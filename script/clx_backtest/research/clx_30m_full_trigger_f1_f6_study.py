"""Execute the independent CLX18 30-minute full-trigger/F1-F6 study.

This entry point deliberately does not reuse or overwrite the artifacts from
``clx-30m-regime-trigger-v1``.  It reads the local QuantAxis MongoDB source,
freezes a per-code immutable snapshot, performs exact from-zero prefix replay,
and stores one executable row per model/reveal with all seven native trigger
bits plus the count of same-model facts collapsed by that execution key.

The later matrix/lock/portfolio stages consume these immutable facts.  This
module owns the source audit and candidate-event milestones because those two
steps are the expensive, resumable part of the research.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import inspect
import json
import math
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pymongo

from freshquant.backtest.clx.engine import ClxEngineOptions, FqCopilotClxEngine
from freshquant.backtest.clx.intraday import (
    BAR_SLOT_CLOCKS,
    LIMIT_MOVE,
    MONGO_MINUTE_TYPE,
    SHANGHAI_TIMEZONE,
    attach_previous_session_regimes,
    build_intraday_bars,
    replay_prefix_events,
)
from script.clx_backtest.research.clx_regime_trigger_study import (
    build_market_segments,
    classify_market_regimes,
)

STUDY_ID = "clx-30m-full-trigger-f1-f6-v1"
SNAPSHOT_CONTRACT_VERSION = 4
SIGNAL_REPLAY_CONTRACT_VERSION = 2
STUDY_CONTRACT_VERSION = 1
MODEL_CODES = tuple(f"S{model_id:04d}" for model_id in range(18))
TRIGGER_BITS = {
    "MODEL_STRUCTURAL": 0x01,
    "PIN_BAR": 0x02,
    "ENGULFING": 0x04,
    "STRONG_FRACTAL": 0x08,
    "MA5_TURN": 0x10,
    "PRICE_VOLUME_CONFIRMATION": 0x20,
    "MACD_CROSS": 0x40,
}
TRIGGER_MASK = sum(TRIGGER_BITS.values())
HORIZONS = (5, 30, 60, 90)
FEE_PER_SIDE = 0.0002
DEFAULT_START_DATE = "2014-01-01"
DEFAULT_OUTPUT_ROOT = Path("D:/fqpack/runtime/clx-backtest/studies/" + STUDY_ID)
DEFAULT_MONGO_URI = "mongodb://127.0.0.1:27027"
INDEX_CODE = "000001"
INDEX_PROXY_CODE = "510980"
INDEX_PROXY_NAME = "上证综合"
BAR_WINDOWS = {
    "20d": 160,
    "60d": 480,
}
EXPECTED_SESSION_LABELS = frozenset(BAR_SLOT_CLOCKS)

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
DAY_PROJECTION = {
    "_id": 0,
    "code": 1,
    "date": 1,
    "date_stamp": 1,
    "open": 1,
    "high": 1,
    "low": 1,
    "close": 1,
    "vol": 1,
    "amount": 1,
}


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
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
    if value is pd.NA:
        return None
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(
        (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                default=_json_default,
            )
            + "\n"
        ).encode("utf-8")
    )
    os.replace(temporary, path)


def write_frame_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


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
        meta = read_json(meta_path)
        if meta.get(identity_key) != identity_value:
            return None
        if meta.get("file_sha256") != sha256_file(data_path):
            return None
        return meta
    except (OSError, TypeError, ValueError, RuntimeError):
        return None


def _snapshot_code_paths(root: Path, code: str) -> tuple[Path, Path]:
    return (
        root / "snapshot" / "bars" / f"{code}.parquet",
        root / "snapshot" / "checkpoints" / f"{code}.json",
    )


def _replay_code_paths(root: Path, code: str) -> tuple[Path, Path]:
    return (
        root / "replay" / "candidates" / f"{code}.parquet",
        root / "replay" / "checkpoints" / f"{code}.json",
    )


def _mongo_client(mongo_uri: str) -> pymongo.MongoClient:
    return pymongo.MongoClient(
        mongo_uri,
        serverSelectionTimeoutMS=10_000,
        connectTimeoutMS=10_000,
        socketTimeoutMS=120_000,
    )


def discover_source(mongo_uri: str) -> dict[str, Any]:
    """Discover the local source without a type-only collection scan."""

    client = _mongo_client(mongo_uri)
    client.admin.command("ping")
    database = client["quantaxis"]
    collections = {
        name: int(database[name].estimated_document_count())
        for name in ("stock_min", "stock_day", "stock_adj", "index_day", "stock_list")
    }
    codes = sorted(
        str(value)
        for value in database["stock_min"].distinct("code")
        if str(value).isdigit() and len(str(value)) == 6
    )
    latest_daily = database["stock_day"].find_one(
        {},
        {"_id": 0, "date": 1},
        sort=[("date", pymongo.DESCENDING)],
    )
    if not latest_daily:
        raise RuntimeError("quantaxis.stock_day has no latest date")
    stock_list_codes = {
        str(value)
        for value in database["stock_list"].distinct("code")
        if str(value).isdigit() and len(str(value)) == 6
    }
    minute_indexes = database["stock_min"].index_information()
    client.close()
    return {
        "mongo_uri_redacted": mongo_uri.split("@")[-1],
        "collections": collections,
        "stock_min_code_count": len(codes),
        "codes": codes,
        "stock_list_code_count": len(stock_list_codes),
        "codes_absent_from_current_stock_list": sorted(set(codes) - stock_list_codes),
        "stock_list_codes_without_minute_history": sorted(
            stock_list_codes - set(codes)
        ),
        "latest_stock_day": str(latest_daily["date"]),
        "stock_min_indexes": minute_indexes,
    }


def _load_code_source_documents(
    *,
    mongo_uri: str,
    code: str,
    start_date: str,
    end_date: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    client = _mongo_client(mongo_uri)
    try:
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
        daily_docs = list(
            database["stock_day"]
            .find(
                {"code": code, "date": {"$gte": start_date, "$lte": end_date}},
                DAY_PROJECTION,
            )
            .sort([("date", pymongo.ASCENDING)])
        )
        previous_daily = database["stock_day"].find_one(
            {"code": code, "date": {"$lt": start_date}},
            DAY_PROJECTION,
            sort=[("date", pymongo.DESCENDING)],
        )
        if previous_daily is not None:
            daily_docs.insert(0, previous_daily)
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
    finally:
        client.close()
    return minute_docs, adj_docs, daily_docs


def _stock_trading_calendar(
    *,
    daily_docs: Sequence[Mapping[str, Any]],
    start_date: str,
    end_date: str,
) -> tuple[list[str], dict[str, int]]:
    """Freeze the per-stock daily calendar used to count exit horizons."""

    parsed = pd.to_datetime(
        [document.get("date") for document in daily_docs],
        errors="coerce",
    )
    valid_dates = [
        value.date().isoformat()
        for value in parsed
        if pd.notna(value) and start_date <= value.date().isoformat() <= end_date
    ]
    unique_dates = sorted(set(valid_dates))
    return (
        unique_dates,
        {
            "source_rows": len(daily_docs),
            "invalid_date_rows": int(pd.isna(parsed).sum()),
            "in_period_rows": len(valid_dates),
            "duplicate_date_rows": len(valid_dates) - len(unique_dates),
            "trading_dates": len(unique_dates),
        },
    )


def _daily_source_quality(
    *,
    daily_docs: Sequence[Mapping[str, Any]],
    adj_docs: Sequence[Mapping[str, Any]],
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    daily_dates = pd.to_datetime(
        [document.get("date") for document in daily_docs],
        errors="coerce",
    )
    adj_dates = {
        pd.Timestamp(value).date()
        for value in pd.to_datetime(
            [document.get("date") for document in adj_docs],
            errors="coerce",
        )
        if pd.notna(value)
    }
    valid_daily_dates = [
        value.date()
        for value in daily_dates
        if pd.notna(value) and start_date <= value.date().isoformat() <= end_date
    ]
    return {
        "daily_rows": len(valid_daily_dates),
        "daily_adj_rows": len(adj_docs),
        "daily_min_date": (
            min(valid_daily_dates).isoformat() if valid_daily_dates else None
        ),
        "daily_max_date": (
            max(valid_daily_dates).isoformat() if valid_daily_dates else None
        ),
        "daily_invalid_date_rows": int(pd.isna(daily_dates).sum()),
        "daily_duplicate_date_rows": len(valid_daily_dates)
        - len(set(valid_daily_dates)),
        "daily_adj_missing_rows": sum(
            value not in adj_dates for value in set(valid_daily_dates)
        ),
    }


def _document_clock(document: Mapping[str, Any]) -> str:
    value = str(document.get("datetime", ""))
    return value[11:16] if len(value) >= 16 else ""


def _select_usable_session_documents(
    documents: Iterable[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """Keep complete and partial sessions made only of real standard bars."""

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
    partial_sessions: list[dict[str, Any]] = []
    unique_bars = 0
    duplicate_extra_docs = 0
    complete_sessions = 0
    partial_missing_slot_count = 0
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
        if (
            not labels
            or not labels.issubset(EXPECTED_SESSION_LABELS)
            or len(labels) != unique_count
        ):
            reasons.append("NONSTANDARD_OR_DUPLICATE_BAR_SLOT")
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
        if labels == EXPECTED_SESSION_LABELS:
            complete_sessions += 1
            continue
        missing_slots = sorted(EXPECTED_SESSION_LABELS - labels)
        partial_missing_slot_count += len(missing_slots)
        partial_sessions.append(
            {
                "code": code,
                "date": trade_date,
                "raw_docs": len(session_rows),
                "unique_bars": unique_count,
                "labels": sorted(labels),
                "missing_slots": missing_slots,
            }
        )

    return selected, {
        "raw_docs": len(rows),
        "unique_bars": unique_bars,
        "duplicate_extra_docs": duplicate_extra_docs,
        "source_sessions": len(grouped),
        "standard_sessions": complete_sessions + len(partial_sessions),
        "usable_sessions": complete_sessions + len(partial_sessions),
        "complete_sessions": complete_sessions,
        "partial_session_count": len(partial_sessions),
        "partial_missing_slot_count": partial_missing_slot_count,
        "partial_sessions": partial_sessions,
        "excluded_session_count": len(excluded_sessions),
        "excluded_sessions": excluded_sessions,
        "ignored_non_30min_docs": sum(
            document.get("type") != MONGO_MINUTE_TYPE for document in source_rows
        ),
    }


def _select_joinable_session_documents(
    documents: Iterable[Mapping[str, Any]],
    *,
    adj_docs: Iterable[Mapping[str, Any]],
    daily_docs: Iterable[Mapping[str, Any]],
    quality: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """Keep usable sessions with exact daily and adjustment joins."""

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
    joinable_complete_sessions = 0
    joinable_partial_sessions = 0
    for (code, trade_date), session_rows in sorted(grouped.items()):
        reasons: list[str] = []
        if (code, trade_date) not in adj_keys:
            reasons.append("MISSING_ADJ_FACTOR")
        if (code, trade_date) not in daily_keys:
            reasons.append("MISSING_STOCK_DAY")
        stamp_groups: dict[object, list[Mapping[str, Any]]] = {}
        for document in session_rows:
            stamp_groups.setdefault(document.get("time_stamp"), []).append(document)
        labels = {_document_clock(group[0]) for group in stamp_groups.values()}
        if reasons:
            excluded.append(
                {
                    "code": code,
                    "date": trade_date,
                    "raw_docs": len(session_rows),
                    "unique_bars": len(stamp_groups),
                    "labels": sorted(labels),
                    "reasons": reasons,
                }
            )
            continue
        selected.extend(session_rows)
        if labels == EXPECTED_SESSION_LABELS:
            joinable_complete_sessions += 1
        else:
            joinable_partial_sessions += 1

    existing_excluded = [dict(item) for item in quality.get("excluded_sessions", [])]
    updated = dict(quality)
    updated.update(
        {
            "complete_sessions": joinable_complete_sessions,
            "joinable_partial_session_count": joinable_partial_sessions,
            "joinable_sessions": (
                joinable_complete_sessions + joinable_partial_sessions
            ),
            "cross_source_excluded_session_count": len(excluded),
            "excluded_session_count": len(existing_excluded) + len(excluded),
            "excluded_sessions": existing_excluded + excluded,
        }
    )
    return selected, updated


def _snapshot_logic_sha256() -> str:
    functions = (
        _load_code_source_documents,
        _stock_trading_calendar,
        _daily_source_quality,
        _document_clock,
        _select_usable_session_documents,
        _select_joinable_session_documents,
        build_intraday_bars,
        _write_index_snapshot,
        snapshot_one_code,
    )
    return sha256_bytes(
        "\n".join(
            ast.dump(
                ast.parse(inspect.getsource(function)),
                annotate_fields=True,
                include_attributes=False,
            )
            for function in functions
        ).encode("utf-8")
    )


def _snapshot_config(
    *,
    start_date: str,
    end_date: str,
    index_source: Mapping[str, Any],
    mongo_uri_redacted: str,
) -> dict[str, Any]:
    return {
        "study_id": STUDY_ID,
        "study_contract_version": STUDY_CONTRACT_VERSION,
        "snapshot_contract_version": SNAPSHOT_CONTRACT_VERSION,
        "snapshot_logic_sha256": _snapshot_logic_sha256(),
        "source": {
            "mongo_uri": mongo_uri_redacted,
            "database": "quantaxis",
            "minute_collection": "stock_min",
            "daily_collection": "stock_day",
            "adjustment_collection": "stock_adj",
            "index_collection": "index_day",
            "download_permitted": False,
        },
        "period": {
            "requested_research_start": "2015-01-01",
            "indicator_warmup_start": start_date,
            "source_end": end_date,
        },
        "minute_type": MONGO_MINUTE_TYPE,
        "required_bar_slots": list(BAR_SLOT_CLOCKS),
        "session_quality": (
            "retain every actually present standard 30-minute slot from "
            "positive-volume/amount complete or partial sessions; do not "
            "fabricate missing slots; exclude full code-days containing a "
            "nonstandard/duplicate slot, zero-trading placeholders, or missing "
            "exact stock_day/stock_adj joins"
        ),
        "qfq_formula": "raw_price * stock_adj.adj",
        "stock_trading_day_calendar": (
            "sorted unique quantaxis.stock_day dates for the code; target "
            "horizon dates count this frozen calendar even when the target "
            "30-minute slot or the whole intraday session is absent"
        ),
        "enhanced_filters": {
            "F1": "1 <= raw 30-minute signal-bar open <= 6",
            "F2": "160-actual-bar QFQ close return <= 0",
            "F3": "QFQ close drawdown from 160-actual-bar high >= 10%",
            "F4": (
                "non-annualised daily-equivalent volatility = sample std of "
                "160 actual 30-minute QFQ close returns * sqrt(8), >= 3%"
            ),
            "F5": "QFQ close <= rolling mean of 480 actual 30-minute closes",
            "F6": (
                "Shanghai-index 20-completed-session return <= 0, mapped "
                "strictly from the prior completed index session"
            ),
        },
        "entry": "next actually existing 30-minute bar open after reveal",
        "horizons_stock_trading_days": list(HORIZONS),
        "fee_per_side": FEE_PER_SIDE,
        "net_return_formula": ("net=(1+gross)*(1-0.0002)/(1+0.0002)-1"),
        "unmodelled_costs": [
            "slippage",
            "stamp_duty",
            "minimum_commission",
            "100-share lot rounding",
        ],
        "native_trigger_bits": TRIGGER_BITS,
        "index_source": dict(index_source),
    }


def _write_index_snapshot(
    *,
    mongo_uri: str,
    root: Path,
    start_date: str,
    end_date: str,
) -> tuple[dict[str, Any], list[str]]:
    client = _mongo_client(mongo_uri)
    database = client["quantaxis"]
    findings: list[str] = []
    actual_count = database["index_day"].count_documents({"code": INDEX_CODE})
    if actual_count:
        source_code = INDEX_CODE
        source_kind = "SHANGHAI_COMPOSITE"
        source_name = "上证指数"
    else:
        proxy = database["etf_list"].find_one(
            {"code": INDEX_PROXY_CODE},
            {"_id": 0, "code": 1, "name": 1},
        )
        if proxy is None:
            raise RuntimeError("Mongo lacks both index 000001 and proxy 510980")
        source_code = INDEX_PROXY_CODE
        source_kind = "SHANGHAI_COMPOSITE_ETF_PROXY"
        source_name = str(proxy.get("name") or INDEX_PROXY_NAME)
        findings.append(
            "quantaxis.index_day has zero code=000001 rows; code=510980 "
            f"({source_name}) is frozen as the market-regime proxy"
        )
    records = list(
        database["index_day"]
        .find(
            {
                "code": source_code,
                "date": {"$gte": start_date, "$lte": end_date},
            },
            {
                "_id": 0,
                "code": 1,
                "date": 1,
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "vol": 1,
                "amount": 1,
            },
        )
        .sort([("date_stamp", pymongo.ASCENDING)])
    )
    client.close()
    if not records:
        raise RuntimeError(f"index source {source_code} has no rows")
    frame = pd.DataFrame(records)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for field in ("open", "high", "low", "close", "vol", "amount"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    duplicate_rows = int(frame["date"].duplicated(keep=False).sum())
    frame = (
        frame.dropna(subset=["date", "close"])
        .sort_values("date", kind="stable")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    invalid_ohlc = int(
        (
            frame["high"].lt(frame[["open", "close"]].max(axis=1))
            | frame["low"].gt(frame[["open", "close"]].min(axis=1))
            | frame["high"].lt(frame["low"])
            | frame["close"].le(0)
        ).sum()
    )
    frame["return_20"] = frame["close"].pct_change(20, fill_method=None)
    path = root / "snapshot" / "index_day.parquet"
    write_frame_atomic(frame, path)
    meta = {
        "source_code": source_code,
        "source_kind": source_kind,
        "source_name": source_name,
        "actual_shanghai_composite_rows": actual_count,
        "rows": len(frame),
        "min_date": frame["date"].min().date().isoformat(),
        "max_date": frame["date"].max().date().isoformat(),
        "duplicate_date_rows": duplicate_rows,
        "invalid_ohlc_rows": invalid_ohlc,
        "file_size": path.stat().st_size,
        "file_sha256": sha256_file(path),
        "logical_path": "snapshot/index_day.parquet",
    }
    return meta, findings


def snapshot_one_code(
    *,
    mongo_uri: str,
    root: str,
    code: str,
    start_date: str,
    end_date: str,
    config_sha256: str,
    market_dates: Sequence[str],
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
        stock_trading_dates = existing.get("stock_trading_dates")
        expected_calendar_sha256 = existing.get("stock_trading_calendar_sha256")
        if isinstance(
            stock_trading_dates, list
        ) and expected_calendar_sha256 == sha256_bytes(
            canonical_json_bytes(stock_trading_dates)
        ):
            return {**existing, "checkpoint_status": "REUSED"}

    started = time.perf_counter()
    minute_docs, adj_docs, daily_docs = _load_code_source_documents(
        mongo_uri=mongo_uri,
        code=code,
        start_date=start_date,
        end_date=end_date,
    )
    selected_docs, quality = _select_usable_session_documents(minute_docs)
    selected_docs, quality = _select_joinable_session_documents(
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
    daily_quality = _daily_source_quality(
        daily_docs=daily_docs,
        adj_docs=adj_docs,
        start_date=start_date,
        end_date=end_date,
    )
    stock_trading_dates, calendar_quality = _stock_trading_calendar(
        daily_docs=daily_docs,
        start_date=start_date,
        end_date=end_date,
    )
    stock_trading_calendar_sha256 = sha256_bytes(
        canonical_json_bytes(stock_trading_dates)
    )
    if not bars.empty and set(bars["code"]) != {code}:
        raise RuntimeError(f"{code} snapshot contains another code")
    bar_trade_dates = {
        pd.Timestamp(value).date().isoformat() for value in bars["trade_date"]
    }
    missing_calendar_dates = sorted(bar_trade_dates - set(stock_trading_dates))
    if missing_calendar_dates:
        raise RuntimeError(
            f"{code} intraday dates are absent from stock_day calendar: "
            f"{missing_calendar_dates[:3]}"
        )

    session_dates = sorted(
        {pd.Timestamp(value).date().isoformat() for value in bars["trade_date"]}
    )
    market = [
        value
        for value in market_dates
        if session_dates and session_dates[0] <= value <= session_dates[-1]
    ]
    missing_trade_dates = sorted(set(market) - set(session_dates))
    yearly_rows: list[dict[str, Any]] = []
    if not bars.empty:
        grouped = bars.groupby("trade_year", sort=True)
        for year, frame in grouped:
            yearly_rows.append(
                {
                    "year": int(year),
                    "bar_rows": len(frame),
                    "trading_sessions": int(frame["trade_date"].nunique()),
                    "zero_volume_bars": int(frame["raw_volume"].le(0).sum()),
                    "duplicate_extra_docs": int(
                        (frame["source_duplicate_count"] - 1).clip(lower=0).sum()
                    ),
                }
            )

    write_frame_atomic(bars, data_path)
    meta = {
        "code": code,
        "snapshot_config_sha256": config_sha256,
        "logical_path": f"snapshot/bars/{code}.parquet",
        "rows": len(bars),
        "min_bar_at": bars["bar_at"].min().isoformat() if len(bars) else None,
        "max_bar_at": bars["bar_at"].max().isoformat() if len(bars) else None,
        "session_count": len(session_dates),
        "missing_market_session_count_active_span": len(missing_trade_dates),
        "missing_market_sessions_sample": missing_trade_dates[:100],
        "yearly_coverage": yearly_rows,
        "source_quality": quality,
        "daily_quality": daily_quality,
        "stock_trading_dates": stock_trading_dates,
        "stock_trading_calendar_sha256": stock_trading_calendar_sha256,
        "stock_trading_calendar_quality": calendar_quality,
        "stock_trading_calendar_min_date": (
            stock_trading_dates[0] if stock_trading_dates else None
        ),
        "stock_trading_calendar_max_date": (
            stock_trading_dates[-1] if stock_trading_dates else None
        ),
        "file_size": data_path.stat().st_size,
        "file_sha256": sha256_file(data_path),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json_atomic(meta_path, meta)
    return {**meta, "checkpoint_status": "BUILT"}


def _aggregate_year_coverage(metas: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    rows = [
        {**year, "code": str(meta["code"])}
        for meta in metas
        for year in meta.get("yearly_coverage", [])
    ]
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    return (
        frame.groupby("year", as_index=False)
        .agg(
            code_count=("code", "nunique"),
            bar_rows=("bar_rows", "sum"),
            trading_sessions=("trading_sessions", "sum"),
            zero_volume_bars=("zero_volume_bars", "sum"),
            duplicate_extra_docs=("duplicate_extra_docs", "sum"),
        )
        .sort_values("year")
        .reset_index(drop=True)
    )


def _freeze_splits(
    market_dates: Sequence[str],
    signal_start: str,
    end_date: str,
) -> dict[str, list[str]]:
    dates = sorted(
        {value for value in market_dates if signal_start <= value <= end_date}
    )
    if len(dates) < 30:
        raise RuntimeError("too few market dates to freeze time splits")
    preferred = {
        "TRAIN": [max(signal_start, "2015-01-01"), "2019-12-31"],
        "VALIDATION": ["2020-01-01", "2023-12-31"],
        "AUDIT": ["2024-01-01", end_date],
    }
    preferred_dates = {
        split_id: [value for value in dates if bounds[0] <= value <= bounds[1]]
        for split_id, bounds in preferred.items()
    }
    if (
        signal_start <= "2015-01-31"
        and end_date >= "2024-01-01"
        and all(preferred_dates.values())
    ):
        return {
            split_id: [values[0], values[-1]]
            for split_id, values in preferred_dates.items()
        }
    train_end_index = max(0, math.floor(len(dates) * 0.50) - 1)
    validation_end_index = max(train_end_index + 1, math.floor(len(dates) * 0.80) - 1)
    return {
        "TRAIN": [dates[0], dates[train_end_index]],
        "VALIDATION": [
            dates[train_end_index + 1],
            dates[validation_end_index],
        ],
        "AUDIT": [dates[validation_end_index + 1], dates[-1]],
    }


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    source = discover_source(args.mongo_uri)
    end_date = args.end_date or str(source["latest_stock_day"])
    index_meta, findings = _write_index_snapshot(
        mongo_uri=args.mongo_uri,
        root=root,
        start_date=args.start_date,
        end_date=end_date,
    )
    config = _snapshot_config(
        start_date=args.start_date,
        end_date=end_date,
        index_source=index_meta,
        mongo_uri_redacted=str(source["mongo_uri_redacted"]),
    )
    config_sha256 = sha256_bytes(canonical_json_bytes(config))
    codes = list(source["codes"])
    if args.code:
        requested = {str(value) for value in args.code}
        codes = [code for code in codes if code in requested]
    if args.code_limit is not None:
        codes = codes[: args.code_limit]
    if not codes:
        raise RuntimeError("no 30-minute source codes selected")

    index_frame = pd.read_parquet(root / "snapshot" / "index_day.parquet")
    market_dates = [
        pd.Timestamp(value).date().isoformat() for value in index_frame["date"]
    ]
    progress_path = root / "audit" / "progress.json"
    outputs: dict[str, dict[str, Any]] = {}
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
                end_date=end_date,
                config_sha256=config_sha256,
                market_dates=market_dates,
            ): code
            for code in codes
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            code = futures[future]
            try:
                outputs[code] = future.result()
            except Exception as exc:  # noqa: BLE001 - persisted worker boundary
                failures[code] = f"{type(exc).__name__}: {exc}"
            if (
                completed == len(codes)
                or completed % args.progress_every == 0
                or failures
            ):
                progress = {
                    "phase": "audit_snapshot",
                    "total_codes": len(codes),
                    "completed_codes": completed,
                    "successful_codes": len(outputs),
                    "failed_codes": len(failures),
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "failures": failures,
                }
                write_json_atomic(progress_path, progress)
                print(json.dumps(progress, ensure_ascii=False), flush=True)
    if failures:
        raise RuntimeError(
            f"audit snapshot failed for {len(failures)} codes; inspect {progress_path}"
        )

    metas = [outputs[code] for code in codes]
    nonempty = [meta for meta in metas if int(meta["rows"]) > 0]
    if not nonempty:
        raise RuntimeError("all 30-minute snapshots are empty")
    min_bar_at = min(str(meta["min_bar_at"]) for meta in nonempty)
    max_bar_at = max(str(meta["max_bar_at"]) for meta in nonempty)
    actual_end_date = pd.Timestamp(max_bar_at).date().isoformat()
    source_quality_keys = (
        "raw_docs",
        "unique_bars",
        "duplicate_extra_docs",
        "source_sessions",
        "standard_sessions",
        "usable_sessions",
        "complete_sessions",
        "partial_session_count",
        "partial_missing_slot_count",
        "joinable_partial_session_count",
        "joinable_sessions",
        "cross_source_excluded_session_count",
        "excluded_session_count",
    )
    source_quality = {
        key: sum(int(meta["source_quality"].get(key, 0)) for meta in metas)
        for key in source_quality_keys
    }
    excluded = [
        row
        for meta in metas
        for row in meta["source_quality"].get("excluded_sessions", [])
    ]
    partial_sessions = [
        row
        for meta in metas
        for row in meta["source_quality"].get("partial_sessions", [])
    ]
    year_coverage = _aggregate_year_coverage(metas)
    signal_start = max(
        "2015-01-01",
        pd.Timestamp(min_bar_at).date().isoformat(),
    )
    splits = _freeze_splits(market_dates, signal_start, actual_end_date)
    config["time_splits"] = splits
    config["time_split_policy"] = (
        "PREFERRED_2015_2019_2020_2023_2024_LATEST"
        if splits["VALIDATION"][0][:4] == "2020" and splits["AUDIT"][0][:4] == "2024"
        else "COVERAGE_PROPORTIONAL_50_30_20"
    )
    config["evidence_grade"] = (
        "FULL_HISTORY"
        if pd.Timestamp(min_bar_at).date() <= date(2015, 1, 31)
        else "SHORT_SAMPLE"
    )
    config["actual_minute_period"] = [
        pd.Timestamp(min_bar_at).date().isoformat(),
        pd.Timestamp(max_bar_at).date().isoformat(),
    ]
    config["snapshot_config_sha256"] = config_sha256

    audit_dir = root / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    year_coverage.to_csv(
        audit_dir / "data_coverage_by_year.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(
        excluded,
        columns=[
            "code",
            "date",
            "raw_docs",
            "unique_bars",
            "labels",
            "reasons",
        ],
    ).to_csv(
        audit_dir / "data_exclusions.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(
        partial_sessions,
        columns=[
            "code",
            "date",
            "raw_docs",
            "unique_bars",
            "labels",
            "missing_slots",
        ],
    ).to_csv(
        audit_dir / "data_partial_sessions.csv",
        index=False,
        encoding="utf-8-sig",
    )
    by_code_rows = []
    for meta in metas:
        by_code_rows.append(
            {
                "code": meta["code"],
                "bar_rows": meta["rows"],
                "session_count": meta["session_count"],
                "min_bar_at": meta["min_bar_at"],
                "max_bar_at": meta["max_bar_at"],
                "missing_market_session_count_active_span": meta[
                    "missing_market_session_count_active_span"
                ],
                "excluded_session_count": meta["source_quality"].get(
                    "excluded_session_count", 0
                ),
                "partial_session_count": meta["source_quality"].get(
                    "partial_session_count", 0
                ),
                "partial_missing_slot_count": meta["source_quality"].get(
                    "partial_missing_slot_count", 0
                ),
                "joinable_partial_session_count": meta["source_quality"].get(
                    "joinable_partial_session_count", 0
                ),
                "daily_rows": meta["daily_quality"]["daily_rows"],
                "daily_adj_rows": meta["daily_quality"]["daily_adj_rows"],
                "daily_adj_missing_rows": meta["daily_quality"][
                    "daily_adj_missing_rows"
                ],
                "stock_trading_dates": meta["stock_trading_calendar_quality"][
                    "trading_dates"
                ],
                "stock_trading_calendar_min_date": meta[
                    "stock_trading_calendar_min_date"
                ],
                "stock_trading_calendar_max_date": meta[
                    "stock_trading_calendar_max_date"
                ],
                "stock_trading_calendar_duplicate_date_rows": meta[
                    "stock_trading_calendar_quality"
                ]["duplicate_date_rows"],
                "file_sha256": meta["file_sha256"],
            }
        )
    pd.DataFrame(by_code_rows).to_csv(
        audit_dir / "data_coverage_by_code.csv",
        index=False,
        encoding="utf-8-sig",
    )
    identity_payload = {
        "config": config,
        "index_file_sha256": index_meta["file_sha256"],
        "code_files": [
            {
                "code": meta["code"],
                "rows": meta["rows"],
                "file_sha256": meta["file_sha256"],
                "stock_trading_calendar_sha256": meta["stock_trading_calendar_sha256"],
            }
            for meta in metas
        ],
    }
    snapshot_id = "sha256:" + sha256_bytes(canonical_json_bytes(identity_payload))
    total_bars = sum(int(meta["rows"]) for meta in metas)
    runtime_estimate = {
        "prefix_calls": total_bars,
        "native_models_per_prefix_call": len(MODEL_CODES),
        "native_model_prefix_evaluations": total_bars * len(MODEL_CODES),
        "candidate_event_rows_estimate": {
            "low": int(total_bars * 0.05),
            "high": int(total_bars * 1.00),
            "basis": "before the immutable full-trigger replay is observed",
        },
        "snapshot_disk_bytes": sum(int(meta["file_size"]) for meta in metas),
        "matrix_filter_subsets": 64,
        "horizons": list(HORIZONS),
        "models": len(MODEL_CODES),
    }
    audit = {
        "study_id": STUDY_ID,
        "snapshot_id": snapshot_id,
        "generated_at": pd.Timestamp.now(tz=SHANGHAI_TIMEZONE).isoformat(),
        "source": {key: value for key, value in source.items() if key != "codes"},
        "config": config,
        "coverage": {
            "snapshot_codes": len(metas),
            "nonempty_codes": len(nonempty),
            "bar_rows": total_bars,
            "stock_sessions": sum(int(meta["session_count"]) for meta in metas),
            "min_bar_at": min_bar_at,
            "max_bar_at": max_bar_at,
        },
        "source_quality": source_quality,
        "index_quality": index_meta,
        "data_findings": findings,
        "runtime_estimate": runtime_estimate,
    }
    write_json_atomic(audit_dir / "study_config.json", config)
    write_json_atomic(audit_dir / "run_volume_estimate.json", runtime_estimate)
    write_json_atomic(audit_dir / "data_audit.json", audit)
    manifest = {
        "study_id": STUDY_ID,
        "snapshot_id": snapshot_id,
        "snapshot_contract_version": SNAPSHOT_CONTRACT_VERSION,
        "snapshot_config_sha256": config_sha256,
        "audit_sha256": sha256_file(audit_dir / "data_audit.json"),
        "index": index_meta,
        "code_files": [
            {
                key: meta[key]
                for key in (
                    "code",
                    "rows",
                    "min_bar_at",
                    "max_bar_at",
                    "file_size",
                    "file_sha256",
                    "stock_trading_calendar_sha256",
                    "stock_trading_calendar_min_date",
                    "stock_trading_calendar_max_date",
                )
            }
            for meta in metas
        ],
    }
    write_json_atomic(root / "snapshot" / "manifest.json", manifest)
    result = {
        "study_id": STUDY_ID,
        "evidence_grade": config["evidence_grade"],
        "snapshot_id": snapshot_id,
        "code_count": len(metas),
        "nonempty_code_count": len(nonempty),
        "bar_rows": total_bars,
        "minute_period": config["actual_minute_period"],
        "splits": splits,
        "index_source_kind": index_meta["source_kind"],
        "audit_path": str(audit_dir / "data_audit.json"),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def _sum_nested_counts(values: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for mapping in values:
        for key, value in mapping.items():
            result[str(key)] = result.get(str(key), 0) + int(value)
    return dict(sorted(result.items()))


def _split_id(value: object, splits: Mapping[str, Sequence[str]]) -> str:
    trade_date = pd.Timestamp(value).date().isoformat()
    for split_id, bounds in splits.items():
        if str(bounds[0]) <= trade_date <= str(bounds[1]):
            return split_id
    return "WARMUP"


def _feature_arrays(bars: pd.DataFrame) -> dict[str, np.ndarray]:
    close = pd.Series(
        pd.to_numeric(bars["qfq_close"], errors="coerce").to_numpy(dtype=float)
    )
    amount = pd.Series(
        pd.to_numeric(bars["raw_amount"], errors="coerce").to_numpy(dtype=float)
    )
    returns = close.pct_change(fill_method=None)
    window20 = BAR_WINDOWS["20d"]
    window60 = BAR_WINDOWS["60d"]
    return {
        "stock_return_20d": close.pct_change(window20, fill_method=None).to_numpy(),
        "stock_drawdown_20d": (
            close / close.rolling(window20, min_periods=window20).max() - 1
        ).to_numpy(),
        # Non-annualised daily-equivalent volatility: 30m std * sqrt(8).
        "stock_volatility_20d": (
            returns.rolling(window20, min_periods=window20).std() * math.sqrt(8)
        ).to_numpy(),
        "stock_above_ma60d_equivalent": (
            close / close.rolling(window60, min_periods=window60).mean() - 1
        ).to_numpy(),
        "amount_median_20d": amount.rolling(window20, min_periods=window20)
        .median()
        .to_numpy(),
    }


def _normalise_stock_trading_dates(
    values: Iterable[object],
) -> list[date]:
    parsed: set[date] = set()
    for value in values:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp):
            raise RuntimeError("stock trading calendar contains an invalid date")
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert(SHANGHAI_TIMEZONE)
        parsed.add(timestamp.date())
    return sorted(parsed)


def compute_code_outcome_map(
    bars: pd.DataFrame,
    reveal_times: Iterable[object],
    *,
    horizons: Sequence[int] = HORIZONS,
    fee_per_side: float = FEE_PER_SIDE,
    stock_trading_dates: Sequence[object] | None = None,
) -> dict[int, dict[str, Any]]:
    """Match next-bar entries and stock-calendar/same-slot exits for one code."""

    frame = bars.sort_values("bar_at", kind="stable").reset_index(drop=True).copy()
    bar_at = pd.DatetimeIndex(frame["bar_at"])
    if bar_at.tz is None:
        bar_at = bar_at.tz_localize(SHANGHAI_TIMEZONE)
    else:
        bar_at = bar_at.tz_convert(SHANGHAI_TIMEZONE)
    if bar_at.has_duplicates:
        raise RuntimeError("snapshot contains duplicate bar_at")
    times = bar_at.asi8
    trade_dates = [pd.Timestamp(value).date() for value in frame["trade_date"]]
    calendar_dates = _normalise_stock_trading_dates(
        stock_trading_dates if stock_trading_dates is not None else trade_dates
    )
    calendar_index = {value: index for index, value in enumerate(calendar_dates)}
    missing_calendar_dates = sorted(set(trade_dates) - set(calendar_dates))
    if missing_calendar_dates:
        raise RuntimeError(
            "execution bars contain dates absent from the frozen stock trading "
            f"calendar: {missing_calendar_dates[:3]}"
        )
    horizon_values: list[int] = []
    for horizon in horizons:
        if isinstance(horizon, bool) or not isinstance(horizon, (int, np.integer)):
            raise TypeError("horizons must contain positive integers")
        parsed_horizon = int(horizon)
        if parsed_horizon <= 0:
            raise RuntimeError("horizons must contain positive integers")
        horizon_values.append(parsed_horizon)
    if not (0 <= fee_per_side < 1):
        raise RuntimeError("fee_per_side must be in [0, 1)")
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
        outcome: dict[str, Any] = {
            "reveal_at": reveal_at,
            "entry_executable": False,
            "entry_status": "NO_NEXT_BAR",
        }
        entry_index = int(np.searchsorted(times, reveal_at.value, side="right"))
        if entry_index >= len(frame):
            for horizon in horizon_values:
                outcome[f"h{horizon}_status"] = "NO_NEXT_BAR"
            outcomes[reveal_at.value] = outcome
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
            for horizon in horizon_values:
                outcome[f"h{horizon}_status"] = "INVALID_ENTRY_PRICE"
            outcomes[reveal_at.value] = outcome
            continue
        entry_gap = entry_raw / prior_close - 1
        outcome["raw_entry_gap"] = entry_gap
        if entry_gap > LIMIT_MOVE:
            outcome["entry_status"] = "ENTRY_LIMIT_UP"
            for horizon in horizon_values:
                outcome[f"h{horizon}_status"] = "ENTRY_LIMIT_UP"
            outcomes[reveal_at.value] = outcome
            continue
        outcome["entry_status"] = "OK"
        outcome["entry_executable"] = True
        entry_session_index = calendar_index[entry_date]
        for horizon in horizon_values:
            prefix = f"h{horizon}"
            target_session_index = entry_session_index + int(horizon)
            if target_session_index >= len(calendar_dates):
                outcome[f"{prefix}_status"] = "CENSORED"
                outcome[f"{prefix}_censor_reason"] = "NO_TARGET_STOCK_TRADING_DAY"
                continue
            target_date = calendar_dates[target_session_index]
            target_at = pd.Timestamp(
                f"{target_date.isoformat()} {BAR_SLOT_CLOCKS[entry_slot]}",
                tz=SHANGHAI_TIMEZONE,
            )
            outcome[f"{prefix}_target_trade_date"] = target_date
            outcome[f"{prefix}_target_at"] = target_at
            candidate_index = int(np.searchsorted(times, target_at.value, side="left"))
            target_slot_exists = bool(
                candidate_index < len(frame)
                and times[candidate_index] == target_at.value
            )
            limit_down_skips = 0
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
                    limit_down_skips += 1
                    candidate_index += 1
                    continue
                break
            if candidate_index >= len(frame):
                outcome[f"{prefix}_status"] = (
                    "CENSORED_LIMIT_DOWN" if limit_down_skips else "CENSORED"
                )
                outcome[f"{prefix}_censor_reason"] = (
                    "NO_TRADABLE_BAR_AFTER_LIMIT_DOWN"
                    if limit_down_skips
                    else "NO_EXIT_BAR_AT_OR_AFTER_TARGET"
                )
                outcome[f"{prefix}_target_slot_exists"] = target_slot_exists
                outcome[f"{prefix}_limit_down_skip_count"] = limit_down_skips
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
            if exit_date not in calendar_index:
                raise RuntimeError(
                    f"exit date {exit_date} is absent from stock calendar"
                )
            delay = (
                (calendar_index[exit_date] - target_session_index)
                * len(BAR_SLOT_CLOCKS)
                + exit_slot
                - entry_slot
            )
            fallback_reasons = []
            if not target_slot_exists:
                fallback_reasons.append("TARGET_SLOT_OR_SESSION_MISSING")
            if limit_down_skips:
                fallback_reasons.append("LIMIT_DOWN")
            gross_return = exit_qfq / entry_qfq - 1
            net_return = (1 + gross_return) * (1 - fee_per_side) / (
                1 + fee_per_side
            ) - 1
            outcome.update(
                {
                    f"{prefix}_status": "OK",
                    f"{prefix}_exit_at": bar_at[candidate_index],
                    f"{prefix}_exit_trade_date": exit_date,
                    f"{prefix}_exit_bar_slot": exit_slot,
                    f"{prefix}_exit_delay": delay,
                    f"{prefix}_target_slot_exists": target_slot_exists,
                    f"{prefix}_limit_down_skip_count": limit_down_skips,
                    f"{prefix}_exit_fallback_used": bool(fallback_reasons),
                    f"{prefix}_exit_fallback_reason": "+".join(fallback_reasons),
                    f"{prefix}_gross_return": gross_return,
                    f"{prefix}_net_return": net_return,
                }
            )
        outcomes[reveal_at.value] = outcome
    return outcomes


def build_full_candidate_frame(
    *,
    events: Sequence[Mapping[str, Any]],
    bars: pd.DataFrame,
    splits: Mapping[str, Sequence[str]],
    stock_trading_dates: Sequence[object] | None = None,
) -> pd.DataFrame:
    """Keep one executable row per model/reveal and audit collapsed facts."""

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
    duplicate_keys = ["code", "model_code", "reveal_at"]
    frame["same_model_reveal_fact_count"] = (
        frame.groupby(duplicate_keys)["signal_fact_id"]
        .transform("size")
        .astype("int16")
    )
    frame["same_model_reveal_unique_signal_count"] = (
        frame.groupby(duplicate_keys)["signal_at"].transform("nunique").astype("int16")
    )
    frame["same_model_reveal_collapsed_fact_count"] = (
        frame["same_model_reveal_fact_count"] - 1
    ).astype("int16")
    frame["same_model_reveal_selection_policy"] = (
        "LATEST_SIGNAL_AT_THEN_REVISION_THEN_FACT_ID"
    )
    frame = (
        frame.sort_values(
            [
                "code",
                "model_code",
                "reveal_at",
                "signal_at",
                "revision_no",
                "signal_fact_id",
            ],
            kind="stable",
        )
        .drop_duplicates(duplicate_keys, keep="last")
        .reset_index(drop=True)
    )
    trigger_masks = pd.to_numeric(
        frame["concurrent_trigger_mask"], errors="raise"
    ).astype("int64")
    invalid_masks = trigger_masks.lt(0) | trigger_masks.map(
        lambda value: bool(int(value) & ~TRIGGER_MASK)
    )
    if invalid_masks.any():
        invalid_values = sorted({int(value) for value in trigger_masks[invalid_masks]})
        raise RuntimeError(
            f"native output contains unknown trigger bits: {invalid_values[:5]}"
        )
    frame["concurrent_trigger_mask"] = trigger_masks
    frame = frame[frame["concurrent_trigger_mask"].ne(0)].copy()
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
    outcomes = compute_code_outcome_map(
        sorted_bars,
        frame["reveal_at"],
        stock_trading_dates=stock_trading_dates,
    )
    enriched: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        reveal = pd.Timestamp(row["reveal_at"])
        signal = pd.Timestamp(row["signal_at"])
        split_id = _split_id(reveal, splits)
        split_bounds = splits.get(split_id)
        reveal_index = bar_index[reveal.value]
        signal_index = bar_index[signal.value]
        outcome = dict(outcomes[reveal.value])
        entry_index = outcome.pop("_entry_index", None)
        values: dict[str, Any] = {
            name: float(array[reveal_index]) for name, array in features.items()
        }
        raw_open = float(sorted_bars.at[reveal_index, "raw_open"])
        values.update(
            {
                "raw_signal_open": raw_open,
                "qfq_signal_close": float(sorted_bars.at[reveal_index, "qfq_close"]),
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
                "split_id": split_id,
                "split_start_trade_date": (
                    pd.Timestamp(split_bounds[0]).date()
                    if split_bounds is not None
                    else None
                ),
                "split_end_trade_date": (
                    pd.Timestamp(split_bounds[1]).date()
                    if split_bounds is not None
                    else None
                ),
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
        for horizon in HORIZONS:
            prefix = f"h{horizon}"
            maturity_at = outcome.get(f"{prefix}_exit_at")
            outcome[f"{prefix}_result_maturity_at"] = maturity_at
            if split_bounds is None:
                boundary_status = "OUT_OF_SCOPE"
            elif outcome.get(f"{prefix}_status") != "OK":
                boundary_status = "UNAVAILABLE"
            elif (
                pd.Timestamp(maturity_at).date() <= pd.Timestamp(split_bounds[1]).date()
            ):
                boundary_status = "AVAILABLE"
            else:
                boundary_status = "PURGED"
            outcome[f"{prefix}_split_boundary_status"] = boundary_status
        for trigger_name, bit in TRIGGER_BITS.items():
            values[f"trigger_{trigger_name.lower()}"] = bool(
                int(row["concurrent_trigger_mask"]) & bit
            )
        values.update(
            {
                "f1_raw_open_1_to_6": 1.0 <= raw_open <= 6.0,
                "f2_return_20d_le_0": (
                    math.isfinite(values["stock_return_20d"])
                    and values["stock_return_20d"] <= 0
                ),
                "f3_drawdown_20d_ge_10pct": (
                    math.isfinite(values["stock_drawdown_20d"])
                    and values["stock_drawdown_20d"] <= -0.10
                ),
                "f4_volatility_20d_ge_3pct": (
                    math.isfinite(values["stock_volatility_20d"])
                    and values["stock_volatility_20d"] >= 0.03
                ),
                "f5_close_le_ma60d_equivalent": (
                    math.isfinite(values["stock_above_ma60d_equivalent"])
                    and values["stock_above_ma60d_equivalent"] <= 0
                ),
            }
        )
        enriched.append({**row, **values, **outcome})
    return (
        pd.DataFrame(enriched)
        .sort_values(["code", "reveal_at", "model_code"], kind="stable")
        .reset_index(drop=True)
    )


def _engine_identity() -> dict[str, Any]:
    backend = importlib.import_module("fqcopilot")
    path = Path(str(backend.__file__)).resolve()
    detailed = callable(getattr(backend, "fq_clxs_all_detailed", None))
    if not detailed:
        raise RuntimeError("native fqcopilot lacks fq_clxs_all_detailed")
    return {
        "module": "fqcopilot",
        "path": str(path),
        "file_size": path.stat().st_size,
        "file_sha256": sha256_file(path),
        "detailed_output": True,
    }


def _module_identity(module_name: str) -> dict[str, Any]:
    module = importlib.import_module(module_name)
    path = Path(str(module.__file__)).resolve()
    return {
        "module": module_name,
        "path": str(path),
        "file_size": path.stat().st_size,
        "file_sha256": sha256_file(path),
    }


def _replay_logic_sha256() -> str:
    functions = (
        _feature_arrays,
        _normalise_stock_trading_dates,
        compute_code_outcome_map,
        build_full_candidate_frame,
        replay_one_code,
    )
    return sha256_bytes(
        "\n".join(
            ast.dump(
                ast.parse(inspect.getsource(function)),
                annotate_fields=True,
                include_attributes=False,
            )
            for function in functions
        ).encode("utf-8")
    )


def replay_one_code(
    *,
    root: str,
    code: str,
    snapshot_file_sha256: str,
    stock_trading_calendar_sha256: str,
    signal_set_id: str,
    options: Mapping[str, int],
    splits: Mapping[str, Sequence[str]],
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
        and existing.get("stock_trading_calendar_sha256")
        == stock_trading_calendar_sha256
    ):
        return {**existing, "checkpoint_status": "REUSED"}
    snapshot_path, snapshot_meta_path = _snapshot_code_paths(output_root, code)
    if sha256_file(snapshot_path) != snapshot_file_sha256:
        raise RuntimeError(f"{code} snapshot file hash changed")
    snapshot_meta = read_json(snapshot_meta_path)
    stock_trading_dates = snapshot_meta.get("stock_trading_dates")
    if not isinstance(stock_trading_dates, list):
        raise TypeError(f"{code} snapshot has no frozen stock calendar")
    actual_calendar_sha256 = sha256_bytes(canonical_json_bytes(stock_trading_dates))
    if actual_calendar_sha256 != stock_trading_calendar_sha256:
        raise RuntimeError(f"{code} stock trading calendar hash changed")
    bars = pd.read_parquet(snapshot_path)
    started = time.perf_counter()
    engine = FqCopilotClxEngine()
    if not engine.supports_detailed_output:
        raise RuntimeError("native fqcopilot lacks fq_clxs_all_detailed")
    events = replay_prefix_events(
        bars=bars,
        engine=engine,
        signal_set_id=signal_set_id,
        options=ClxEngineOptions(**dict(options)),
        code=code,
    )
    candidates = build_full_candidate_frame(
        events=events,
        bars=bars,
        splits=splits,
        stock_trading_dates=stock_trading_dates,
    )
    write_frame_atomic(candidates, data_path)
    mask_counts = (
        candidates["concurrent_trigger_mask"].value_counts().sort_index().to_dict()
        if len(candidates)
        else {}
    )
    meta = {
        "code": code,
        "signal_set_id": signal_set_id,
        "snapshot_file_sha256": snapshot_file_sha256,
        "stock_trading_calendar_sha256": stock_trading_calendar_sha256,
        "logical_path": f"replay/candidates/{code}.parquet",
        "source_bar_rows": len(bars),
        "prefix_calls": len(bars),
        "revision_event_rows": len(events),
        "candidate_rows": len(candidates),
        "unique_reveal_times": (
            int(candidates["reveal_at"].nunique()) if len(candidates) else 0
        ),
        "exact_trigger_mask_counts": {
            str(key): int(value) for key, value in mask_counts.items()
        },
        "file_size": data_path.stat().st_size,
        "file_sha256": sha256_file(data_path),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json_atomic(meta_path, meta)
    return {**meta, "checkpoint_status": "BUILT"}


def run_replay(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    snapshot_manifest_path = root / "snapshot" / "manifest.json"
    audit_path = root / "audit" / "data_audit.json"
    snapshot_manifest = read_json(snapshot_manifest_path)
    audit = read_json(audit_path)
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
        "engine_identity": engine_identity,
        "python_adapter_identities": [
            _module_identity("freshquant.backtest.clx.engine"),
            _module_identity("freshquant.backtest.clx.intraday"),
        ],
        "replay_logic_sha256": _replay_logic_sha256(),
        "engine_options": options,
        "causal_route": "EXACT_FROM_ZERO_PREFIX_PER_ACTUAL_30MIN_BAR",
        "direction": "BUY_ONLY",
        "trigger_mask": TRIGGER_MASK,
        "native_trigger_bits": TRIGGER_BITS,
        "horizons": list(HORIZONS),
        "horizon_calendar": "PER_CODE_FROZEN_STOCK_DAY_DATES",
        "target_exit": (
            "entry slot on the Nth later frozen stock_day date, then the first "
            "actual tradable 30-minute open at or after that timestamp"
        ),
        "fee_per_side": FEE_PER_SIDE,
        "splits": audit["config"]["time_splits"],
    }
    signal_set_id = "sha256:" + sha256_bytes(canonical_json_bytes(signal_contract))
    metas = [
        dict(meta) for meta in snapshot_manifest["code_files"] if int(meta["rows"]) > 0
    ]
    if args.code:
        requested = {str(value) for value in args.code}
        metas = [meta for meta in metas if str(meta["code"]) in requested]
    if args.code_limit is not None:
        metas = metas[: args.code_limit]
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
                stock_trading_calendar_sha256=str(
                    meta["stock_trading_calendar_sha256"]
                ),
                signal_set_id=signal_set_id,
                options=options,
                splits=audit["config"]["time_splits"],
            ): str(meta["code"])
            for meta in metas
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            code = futures[future]
            try:
                outputs[code] = future.result()
            except Exception as exc:  # noqa: BLE001 - persisted worker boundary
                failures[code] = f"{type(exc).__name__}: {exc}"
            if (
                completed == len(metas)
                or completed % args.progress_every == 0
                or failures
            ):
                elapsed = time.perf_counter() - started
                progress = {
                    "phase": "full_trigger_replay",
                    "total_codes": len(metas),
                    "completed_codes": completed,
                    "successful_codes": len(outputs),
                    "failed_codes": len(failures),
                    "prefix_calls_completed": sum(
                        int(meta["prefix_calls"]) for meta in outputs.values()
                    ),
                    "revision_event_rows": sum(
                        int(meta["revision_event_rows"]) for meta in outputs.values()
                    ),
                    "candidate_rows": sum(
                        int(meta["candidate_rows"]) for meta in outputs.values()
                    ),
                    "elapsed_seconds": round(elapsed, 3),
                    "estimated_remaining_seconds": (
                        round(elapsed / completed * (len(metas) - completed), 1)
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
    ordered = [outputs[str(meta["code"])] for meta in metas]
    replay_manifest = {
        "study_id": STUDY_ID,
        "signal_set_id": signal_set_id,
        "signal_contract": signal_contract,
        "snapshot_id": snapshot_manifest["snapshot_id"],
        "snapshot_manifest_file_sha256": sha256_file(snapshot_manifest_path),
        "code_files": [
            {
                key: meta[key]
                for key in (
                    "code",
                    "source_bar_rows",
                    "prefix_calls",
                    "revision_event_rows",
                    "candidate_rows",
                    "file_size",
                    "file_sha256",
                    "stock_trading_calendar_sha256",
                )
            }
            for meta in ordered
        ],
        "totals": {
            "codes": len(ordered),
            "prefix_calls": sum(int(meta["prefix_calls"]) for meta in ordered),
            "revision_event_rows": sum(
                int(meta["revision_event_rows"]) for meta in ordered
            ),
            "candidate_rows": sum(int(meta["candidate_rows"]) for meta in ordered),
            "exact_trigger_mask_counts": _sum_nested_counts(
                meta["exact_trigger_mask_counts"] for meta in ordered
            ),
        },
    }
    manifest_path = root / "replay" / "manifest.json"
    write_json_atomic(manifest_path, replay_manifest)
    result = {
        "study_id": STUDY_ID,
        "signal_set_id": signal_set_id,
        "codes": len(ordered),
        **replay_manifest["totals"],
        "manifest_path": str(manifest_path),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def _load_replay_candidates(
    *,
    root: Path,
    allow_partial: bool,
) -> tuple[pd.DataFrame, list[dict[str, Any]], list[str]]:
    snapshot_manifest = read_json(root / "snapshot" / "manifest.json")
    expected_by_code = {
        str(meta["code"]): dict(meta)
        for meta in snapshot_manifest["code_files"]
        if int(meta["rows"]) > 0
    }
    expected = list(expected_by_code)
    frames: list[pd.DataFrame] = []
    metas: list[dict[str, Any]] = []
    missing: list[str] = []
    for code in expected:
        path, meta_path = _replay_code_paths(root, code)
        if not path.is_file() or not meta_path.is_file():
            missing.append(code)
            continue
        meta = read_json(meta_path)
        if meta["file_sha256"] != sha256_file(path):
            raise RuntimeError(f"{code} replay candidate hash mismatch")
        snapshot_meta = expected_by_code[code]
        if meta.get("snapshot_file_sha256") != snapshot_meta["file_sha256"]:
            raise RuntimeError(f"{code} replay uses a stale snapshot file")
        if (
            meta.get("stock_trading_calendar_sha256")
            != snapshot_meta["stock_trading_calendar_sha256"]
        ):
            raise RuntimeError(f"{code} replay uses a stale stock calendar")
        metas.append(meta)
        if int(meta["candidate_rows"]) > 0:
            frames.append(pd.read_parquet(path))
    if missing and not allow_partial:
        raise RuntimeError(f"replay incomplete: {len(missing)} codes are absent")
    if not frames:
        raise RuntimeError("no full-trigger candidate facts")
    signal_set_ids = {str(meta.get("signal_set_id")) for meta in metas}
    if len(signal_set_ids) != 1:
        raise RuntimeError("replay checkpoints mix multiple signal_set_id values")
    replay_manifest_path = root / "replay" / "manifest.json"
    if replay_manifest_path.is_file():
        replay_manifest = read_json(replay_manifest_path)
        if signal_set_ids != {str(replay_manifest["signal_set_id"])}:
            raise RuntimeError("replay checkpoints disagree with replay manifest")
    return pd.concat(frames, ignore_index=True), metas, missing


def _attach_index_features(events: pd.DataFrame, index: pd.DataFrame) -> pd.DataFrame:
    classified = classify_market_regimes(index)
    classified["index_return_20"] = classified["close"].pct_change(20, fill_method=None)
    keep = [
        column
        for column in classified.columns
        if column == "date"
        or column.startswith("index_")
        or column
        in {
            "market_regime",
            "raw_market_regime",
            "regime_segment_no",
        }
    ]
    frame = attach_previous_session_regimes(events, classified.loc[:, keep])
    if (
        (
            pd.to_datetime(frame["index_feature_date"]).dt.date
            >= pd.to_datetime(frame["reveal_at"]).dt.date
        )
        .fillna(False)
        .any()
    ):
        raise RuntimeError("future-or-same-session index feature join detected")
    frame["f6_index_return_20d_le_0"] = (
        pd.to_numeric(frame["index_return_20"], errors="coerce").le(0)
        & frame["index_return_20"].notna()
    )
    return frame


def _filter_pass_mask(frame: pd.DataFrame) -> np.ndarray:
    columns = (
        "f1_raw_open_1_to_6",
        "f2_return_20d_le_0",
        "f3_drawdown_20d_ge_10pct",
        "f4_volatility_20d_ge_3pct",
        "f5_close_le_ma60d_equivalent",
        "f6_index_return_20d_le_0",
    )
    output = np.zeros(len(frame), dtype=np.uint8)
    for offset, column in enumerate(columns):
        output |= (
            frame[column].fillna(False).to_numpy(dtype=bool).astype(np.uint8) << offset
        )
    return output


def run_features(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    events, metas, missing = _load_replay_candidates(
        root=root,
        allow_partial=args.allow_partial,
    )
    for column in ("signal_at", "reveal_at", "entry_at"):
        if column in events:
            events[column] = pd.to_datetime(events[column], utc=True).dt.tz_convert(
                SHANGHAI_TIMEZONE
            )
    index = pd.read_parquet(root / "snapshot" / "index_day.parquet")
    events = _attach_index_features(events, index)
    events["filter_pass_mask"] = _filter_pass_mask(events)
    events["union_signal_id"] = [
        "sha256:"
        + sha256_bytes(
            canonical_json_bytes(
                {
                    "code": str(code),
                    "reveal_at": pd.Timestamp(reveal).isoformat(),
                }
            )
        )
        for code, reveal in zip(events["code"], events["reveal_at"], strict=True)
    ]
    events["same_code_reveal_model_count"] = (
        events.groupby(["code", "reveal_at"])["model_code"]
        .transform("nunique")
        .astype("int16")
    )
    events["same_reveal_stock_count"] = (
        events.groupby("reveal_at")["code"].transform("nunique").astype("int32")
    )
    events["same_reveal_event_count"] = (
        events.groupby("reveal_at")["signal_fact_id"]
        .transform("nunique")
        .astype("int32")
    )
    output_path = root / "features" / "candidate_events.parquet"
    write_frame_atomic(events, output_path)
    segments = build_market_segments(classify_market_regimes(index))
    segments.to_csv(
        root / "features" / "market_segments.csv",
        index=False,
        encoding="utf-8-sig",
    )
    summary = {
        "study_id": STUDY_ID,
        "partial": bool(missing),
        "missing_codes": missing,
        "replayed_codes": len(metas),
        "candidate_event_rows": len(events),
        "unique_union_signals": int(events["union_signal_id"].nunique()),
        "unique_stocks": int(events["code"].nunique()),
        "unique_reveal_times": int(events["reveal_at"].nunique()),
        "models": sorted(events["model_code"].unique()),
        "exact_trigger_mask_counts": {
            str(key): int(value)
            for key, value in events["concurrent_trigger_mask"]
            .value_counts()
            .sort_index()
            .items()
        },
        "trigger_concurrency_counts": {
            str(key): int(value)
            for key, value in events["concurrent_trigger_count"]
            .value_counts()
            .sort_index()
            .items()
        },
        "execution_audit": {
            "entry_status_counts": {
                str(key): int(value)
                for key, value in events["entry_status"]
                .value_counts(dropna=False)
                .items()
            },
            "entry_overnight_rows": int(events["entry_overnight"].fillna(False).sum()),
            "horizons": {
                str(horizon): {
                    "status_counts": {
                        str(key): int(value)
                        for key, value in events[f"h{horizon}_status"]
                        .value_counts(dropna=False)
                        .items()
                    },
                    "fallback_rows": int(
                        events.get(
                            f"h{horizon}_exit_fallback_used",
                            pd.Series(False, index=events.index),
                        )
                        .fillna(False)
                        .sum()
                    ),
                    "purged_rows": int(
                        events[f"h{horizon}_split_boundary_status"].eq("PURGED").sum()
                    ),
                }
                for horizon in HORIZONS
            },
        },
        "within_cross_model_duplicates": {
            "rows_with_same_model_reveal_collapsed_facts": int(
                events["same_model_reveal_fact_count"].gt(1).sum()
            ),
            "same_model_reveal_facts_collapsed": int(
                events["same_model_reveal_collapsed_fact_count"].sum()
            ),
            "max_facts_same_model_reveal": int(
                events["same_model_reveal_fact_count"].max()
            ),
            "same_model_reveal_selection_policy": (
                "LATEST_SIGNAL_AT_THEN_REVISION_THEN_FACT_ID"
            ),
            "rows_with_cross_model_same_code_reveal": int(
                events["same_code_reveal_model_count"].gt(1).sum()
            ),
            "max_models_same_code_reveal": int(
                events["same_code_reveal_model_count"].max()
            ),
        },
        "future_or_same_day_index_joins": int(
            (
                pd.to_datetime(events["index_feature_date"]).dt.date
                >= events["reveal_at"].dt.date
            )
            .fillna(False)
            .sum()
        ),
        "output": {
            "path": str(output_path),
            "file_size": output_path.stat().st_size,
            "file_sha256": sha256_file(output_path),
        },
    }
    write_json_atomic(root / "features" / "summary.json", summary)
    write_json_atomic(
        root / "features" / "manifest.json",
        {
            "study_id": STUDY_ID,
            "snapshot_id": read_json(root / "snapshot" / "manifest.json")[
                "snapshot_id"
            ],
            "signal_set_id": metas[0]["signal_set_id"],
            "summary": summary,
        },
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def run_status(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    snapshot_manifest = root / "snapshot" / "manifest.json"
    replay_manifest = root / "replay" / "manifest.json"
    feature_manifest = root / "features" / "manifest.json"
    result = {
        "study_id": STUDY_ID,
        "root": str(root),
        "audit_complete": (root / "audit" / "data_audit.json").is_file(),
        "snapshot_complete": snapshot_manifest.is_file(),
        "replay_complete": replay_manifest.is_file(),
        "features_complete": feature_manifest.is_file(),
        "audit_progress": (
            read_json(root / "audit" / "progress.json")
            if (root / "audit" / "progress.json").is_file()
            else None
        ),
        "replay_progress": (
            read_json(root / "replay" / "progress.json")
            if (root / "replay" / "progress.json").is_file()
            else None
        ),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit")
    audit.add_argument("--mongo-uri", default=DEFAULT_MONGO_URI)
    audit.add_argument("--start-date", default=DEFAULT_START_DATE)
    audit.add_argument("--end-date")
    audit.add_argument("--workers", type=_positive_int, default=8)
    audit.add_argument("--progress-every", type=_positive_int, default=25)
    audit.add_argument("--code", action="append", default=[])
    audit.add_argument("--code-limit", type=int)
    audit.set_defaults(handler=run_audit)

    replay = subparsers.add_parser("replay")
    replay.add_argument(
        "--workers",
        type=_positive_int,
        default=max(1, min(24, (os.cpu_count() or 2) - 4)),
    )
    replay.add_argument("--progress-every", type=_positive_int, default=10)
    replay.add_argument("--code", action="append", default=[])
    replay.add_argument("--code-limit", type=int)
    replay.add_argument("--wave-opt", type=int, default=1560)
    replay.add_argument("--stretch-opt", type=int, default=0)
    replay.add_argument("--trend-opt", type=int, default=0)
    replay.set_defaults(handler=run_replay)

    features = subparsers.add_parser("features")
    features.add_argument("--allow-partial", action="store_true")
    features.set_defaults(handler=run_features)

    status = subparsers.add_parser("status")
    status.set_defaults(handler=run_status)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
