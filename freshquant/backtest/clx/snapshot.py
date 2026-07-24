"""Immutable Mongo-to-Parquet source snapshot for CLX research.

The source collections are read only.  A snapshot is published with an atomic
directory rename only after the filtered Mongo state is observed unchanged
before and after extraction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, SupportsFloat, SupportsIndex
from zoneinfo import ZoneInfo

import polars as pl
from pymongo import ASCENDING, DESCENDING, MongoClient

SNAPSHOT_SCHEMA_VERSION = "clx-mongo-snapshot-v1"
CODE_BUCKET_COUNT = 64
CLX_BASELINE_OPTIONS = {"wave_opt": 1560, "stretch_opt": 0, "trend_opt": 0}
PARQUET_WRITER = {
    "library": "polars",
    "version": pl.__version__,
    "compression": "zstd",
    "compression_level": 9,
    "statistics": True,
    "row_group_size": 65536,
}

QUALITY_ADJ_MISSING = 1 << 0
QUALITY_ADJ_REBUILT_VERIFIED = 1 << 1
QUALITY_SENTINEL_VOLUME_NORMALIZED = 1 << 2
QUALITY_RAW_PRICE_INVALID = 1 << 3
QUALITY_RAW_VOLUME_INVALID = 1 << 4
QUALITY_EXCLUDED_CLX = 1 << 5
QUALITY_EXCLUDED_MATCHING = 1 << 6
QUALITY_AMOUNT_INVALID = 1 << 7

QUALITY_FLAGS = {
    "ADJ_MISSING": QUALITY_ADJ_MISSING,
    "ADJ_REBUILT_VERIFIED": QUALITY_ADJ_REBUILT_VERIFIED,
    "SENTINEL_VOLUME_NORMALIZED": QUALITY_SENTINEL_VOLUME_NORMALIZED,
    "RAW_PRICE_INVALID": QUALITY_RAW_PRICE_INVALID,
    "RAW_VOLUME_INVALID": QUALITY_RAW_VOLUME_INVALID,
    "EXCLUDED_CLX": QUALITY_EXCLUDED_CLX,
    "EXCLUDED_MATCHING": QUALITY_EXCLUDED_MATCHING,
    "AMOUNT_INVALID": QUALITY_AMOUNT_INVALID,
}

_CODE_RE = re.compile(r"^[0-9]{6}$")
_SENTINEL_VOLUME_MAX = 1e-30
_PRICE_FIELDS = ("open", "high", "low", "close")
_SOURCE_TIMEZONE = ZoneInfo("Asia/Shanghai")

# These are the complete missing stock_adj keys observed in the VM source at
# the frozen 2026-07-21 boundary.  Rebuild is limited to zero-volume placeholder
# bars whose neighboring factors prove continuity.  The three newest gaps stay
# quarantined instead of guessing a factor.
KNOWN_ADJ_GAPS: dict[tuple[str, str], dict[str, str]] = {
    ("000001", "1991-09-30"): {
        "disposition": "REBUILT_VERIFIED",
        "method": "PREVIOUS_FACTOR_WITH_EQUAL_NEXT_FACTOR",
    },
    ("000014", "1993-07-14"): {
        "disposition": "REBUILT_VERIFIED",
        "method": "PREVIOUS_FACTOR_WITH_EQUAL_NEXT_FACTOR",
    },
    ("000017", "1992-05-05"): {
        "disposition": "REBUILT_VERIFIED",
        "method": "PREVIOUS_FACTOR_WITH_EQUAL_NEXT_FACTOR",
    },
    ("600651", "2016-08-25"): {
        "disposition": "REBUILT_VERIFIED",
        "method": "PREVIOUS_FACTOR_WITH_EQUAL_NEXT_FACTOR_OR_TERMINAL_LOCF",
    },
    ("301234", "2026-07-21"): {
        "disposition": "EXCLUDED_ADJ_GAP",
        "method": "NO_FACTOR_IMPUTATION",
    },
    ("688237", "2026-07-21"): {
        "disposition": "EXCLUDED_ADJ_GAP",
        "method": "NO_FACTOR_IMPUTATION",
    },
    ("688277", "2026-07-21"): {
        "disposition": "EXCLUDED_ADJ_GAP",
        "method": "NO_FACTOR_IMPUTATION",
    },
}


class SnapshotError(RuntimeError):
    """Raised when a source snapshot cannot be proven reproducible."""


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid ISO date: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class SnapshotSpec:
    """Frozen source boundary and optional explicit universe."""

    start_date: str
    as_of: str
    codes: tuple[str, ...] = ()
    quiet_window_confirmed: bool = False

    def __post_init__(self) -> None:
        start = _parse_iso_date(self.start_date)
        end = _parse_iso_date(self.as_of)
        if start > end:
            raise ValueError("start_date must be on or before as_of")
        normalized = tuple(sorted(set(self.codes)))
        invalid = [code for code in normalized if not _CODE_RE.fullmatch(code)]
        if invalid:
            raise ValueError(f"stock codes must be six digits: {invalid}")
        if not isinstance(self.quiet_window_confirmed, bool):
            raise ValueError("quiet_window_confirmed must be a boolean")
        object.__setattr__(self, "codes", normalized)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _code_bucket(code: str) -> int:
    return (
        int(hashlib.sha256(code.encode("ascii")).hexdigest()[:8], 16)
        % CODE_BUCKET_COUNT
    )


def _logical_frame_sha256(frame: pl.DataFrame) -> str:
    """Hash ordered typed values independently from Parquet encoding bytes."""

    digest = hashlib.sha256()
    digest.update(
        _canonical_json([(name, str(dtype)) for name, dtype in frame.schema.items()])
    )
    digest.update(b"\n")
    for row in frame.iter_rows():
        canonical_row = []
        for value in row:
            if isinstance(value, float):
                canonical_row.append({"float64_hex": value.hex()})
            elif isinstance(value, date):
                canonical_row.append({"date": value.isoformat()})
            else:
                canonical_row.append(value)
        digest.update(_canonical_json(canonical_row))
        digest.update(b"\n")
    return digest.hexdigest()


def _snapshot_identity_payload(
    *,
    spec: Mapping[str, Any],
    source_state: Mapping[str, Any],
    calendar_file: Mapping[str, Any],
    universe_file: Mapping[str, Any],
    adjustment_gaps_file: Mapping[str, Any],
    bar_files: Sequence[Mapping[str, Any]],
    observed_adj_gaps: Sequence[Mapping[str, Any]],
    parquet_writer: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "spec": dict(spec),
        "source_state": dict(source_state),
        "parquet_writer": dict(parquet_writer),
        "artifact_files": {
            "calendar": dict(calendar_file),
            "universe": dict(universe_file),
            "adjustment_gaps": dict(adjustment_gaps_file),
            "bars": [dict(item) for item in bar_files],
        },
        "observed_adj_gaps": [dict(item) for item in observed_adj_gaps],
    }


def _date_stamp(value: str) -> int:
    parsed = _parse_iso_date(value)
    return int(datetime.combine(parsed, time.min, _SOURCE_TIMEZONE).timestamp())


def _source_filters(
    codes: Sequence[str], spec: SnapshotSpec
) -> dict[str, dict[str, Any]]:
    code_filter = {"$in": list(codes)}
    return {
        "stock_day": {
            "code": code_filter,
            "date_stamp": {
                "$gte": _date_stamp(spec.start_date),
                "$lte": _date_stamp(spec.as_of),
            },
        },
        "stock_adj": {
            "code": code_filter,
            "date": {"$gte": spec.start_date, "$lte": spec.as_of},
        },
        "stock_list": {"code": code_filter},
    }


def _universe_day_filter(spec: SnapshotSpec) -> dict[str, Any]:
    query: dict[str, Any] = {
        "date_stamp": {
            "$gte": _date_stamp(spec.start_date),
            "$lte": _date_stamp(spec.as_of),
        }
    }
    if spec.codes:
        query["code"] = {"$in": list(spec.codes)}
    return query


def _read_universe(database: Any, spec: SnapshotSpec) -> list[dict[str, Any]]:
    # Historical bars, not today's stock_list, define membership.  Otherwise a
    # delisted name silently disappears and the backtest gains survivorship bias.
    codes = sorted(
        str(code)
        for code in database["stock_day"].distinct("code", _universe_day_filter(spec))
    )
    if spec.codes:
        missing_day = sorted(set(spec.codes) - set(codes))
        if missing_day:
            raise SnapshotError(
                f"requested codes have no stock_day rows in the frozen range: {missing_day}"
            )
    query: dict[str, Any] = {"code": {"$in": codes}}
    docs = list(
        database["stock_list"].find(
            query,
            {
                "_id": 0,
                "code": 1,
                "name": 1,
                "sse": 1,
                "sec": 1,
                "volunit": 1,
                "decimal_point": 1,
            },
            sort=[("code", ASCENDING)],
        )
    )
    metadata_by_code: dict[str, Mapping[str, Any]] = {}
    for doc in docs:
        code = str(doc.get("code", ""))
        if code in metadata_by_code:
            raise SnapshotError("stock_list contains duplicate code keys")
        metadata_by_code[code] = doc
    if len(metadata_by_code) != len(docs):
        raise SnapshotError("stock_list contains duplicate code keys")
    invalid = [code for code in codes if not _CODE_RE.fullmatch(code)]
    if invalid:
        raise SnapshotError(f"stock_day contains invalid codes: {invalid[:10]}")
    return [
        {
            "code": code,
            "name": metadata_by_code.get(code, {}).get("name"),
            "exchange": metadata_by_code.get(code, {}).get("sse"),
            "security_type": metadata_by_code.get(code, {}).get("sec"),
            "volunit": metadata_by_code.get(code, {}).get("volunit"),
            "decimal_point": metadata_by_code.get(code, {}).get("decimal_point"),
            "in_current_stock_list": code in metadata_by_code,
        }
        for code in codes
    ]


def _collection_structure(database: Any, name: str) -> dict[str, Any]:
    collection_info = list(database.list_collections(filter={"name": name}))
    if len(collection_info) != 1:
        raise SnapshotError(
            f"source collection metadata is missing or ambiguous: {name}"
        )
    raw_uuid = collection_info[0].get("info", {}).get("uuid")
    collection_uuid = bytes(raw_uuid).hex() if raw_uuid is not None else None

    raw_indexes = database[name].index_information()
    indexes = []
    for index_name in sorted(raw_indexes):
        raw = raw_indexes[index_name]
        summary = {
            "name": index_name,
            "keys": [[field, direction] for field, direction in raw.get("key", [])],
            "unique": bool(raw.get("unique", False)),
            "sparse": bool(raw.get("sparse", False)),
        }
        if "partialFilterExpression" in raw:
            summary["partial_filter"] = raw["partialFilterExpression"]
        if "expireAfterSeconds" in raw:
            summary["expire_after_seconds"] = raw["expireAfterSeconds"]
        indexes.append(summary)
    return {
        "collection_uuid": collection_uuid,
        "indexes": indexes,
        "indexes_sha256": _sha256_bytes(_canonical_json(indexes)),
    }


def _source_state(
    database: Any,
    filters: Mapping[str, Mapping[str, Any]],
    universe_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for name in ("stock_day", "stock_adj"):
        query = dict(filters[name])
        date_sort_field = "date_stamp" if name == "stock_day" else "date"
        earliest = database[name].find_one(
            query,
            {"_id": 0, "date": 1},
            sort=[(date_sort_field, ASCENDING)],
        )
        latest = database[name].find_one(
            query,
            {"_id": 0, "date": 1},
            sort=[(date_sort_field, DESCENDING)],
        )
        state[name] = {
            "count": int(database[name].count_documents(query)),
            "distinct_code_count": len(database[name].distinct("code", query)),
            "min_date": earliest.get("date") if earliest else None,
            "max_date": latest.get("date") if latest else None,
            **_collection_structure(database, name),
        }
    state["stock_list"] = {
        "count": int(
            database["stock_list"].count_documents(dict(filters["stock_list"]))
        ),
        "distinct_code_count": len(
            database["stock_list"].distinct("code", dict(filters["stock_list"]))
        ),
        "min_date": None,
        "max_date": None,
        "content_sha256": _sha256_bytes(_canonical_json(universe_rows)),
        **_collection_structure(database, "stock_list"),
    }
    return state


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (str, bytes, bytearray, SupportsFloat, SupportsIndex)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _adj_gap_evidence(
    database: Any, code: str, trade_date: str, as_of: str
) -> dict[str, Any]:
    collection = database["stock_adj"]
    previous = collection.find_one(
        {"code": code, "date": {"$lt": trade_date}},
        {"_id": 0, "date": 1, "adj": 1},
        sort=[("date", DESCENDING)],
    )
    following = collection.find_one(
        {"code": code, "date": {"$gt": trade_date, "$lte": as_of}},
        {"_id": 0, "date": 1, "adj": 1},
        sort=[("date", ASCENDING)],
    )
    return {
        "previous": previous,
        "following_within_as_of": following,
        "filters": {
            "previous": {"code": code, "date": {"$lt": trade_date}},
            "following_within_as_of": {
                "code": code,
                "date": {"$gt": trade_date, "$lte": as_of},
            },
        },
    }


def _rebuild_factor(
    code: str,
    trade_date: str,
    policy: Mapping[str, str],
    evidence: Mapping[str, Any],
) -> float:
    previous = evidence.get("previous")
    following = evidence.get("following_within_as_of")
    previous_factor = _finite_number(previous.get("adj")) if previous else None
    following_factor = _finite_number(following.get("adj")) if following else None
    if previous_factor is None or previous_factor <= 0:
        raise SnapshotError(f"{code}/{trade_date} has no valid previous adj factor")
    if following_factor is not None and not math.isclose(
        previous_factor, following_factor, rel_tol=0.0, abs_tol=1e-12
    ):
        raise SnapshotError(
            f"{code}/{trade_date} neighboring adj factors disagree: "
            f"{previous_factor} != {following_factor}"
        )
    if following_factor is None and "TERMINAL_LOCF" not in policy["method"]:
        raise SnapshotError(
            f"{code}/{trade_date} needs an equal following adj factor before as_of"
        )
    return previous_factor


def _build_code_frame(
    *,
    code: str,
    day_docs: Iterable[Mapping[str, Any]],
    adj_docs: Iterable[Mapping[str, Any]],
    gap_evidence: Mapping[tuple[str, str], Mapping[str, Any]],
    session_by_date: Mapping[date, int] | None = None,
) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    """Join one code in memory; pure except for supplied repair evidence."""

    ordered_days = sorted(day_docs, key=lambda doc: str(doc.get("date", "")))
    day_keys = [
        (str(doc.get("code", "")), str(doc.get("date", ""))) for doc in ordered_days
    ]
    if len(day_keys) != len(set(day_keys)):
        raise SnapshotError(f"stock_day duplicate primary key for {code}")

    adj_by_date: dict[str, object] = {}
    for doc in adj_docs:
        trade_date = str(doc.get("date", ""))
        if trade_date in adj_by_date:
            raise SnapshotError(
                f"stock_adj duplicate primary key for {code}/{trade_date}"
            )
        adj_by_date[trade_date] = doc.get("adj")

    rows: list[dict[str, Any]] = []
    gap_audit: list[dict[str, Any]] = []
    if session_by_date is None:
        local_dates = sorted(
            _parse_iso_date(str(doc.get("date", ""))) for doc in ordered_days
        )
        session_by_date = {
            trade_date: index for index, trade_date in enumerate(local_dates, 1)
        }
    for doc in ordered_days:
        trade_date = str(doc.get("date", ""))
        if str(doc.get("code", "")) != code:
            raise SnapshotError(
                f"stock_day row belongs to another code in partition {code}"
            )
        try:
            parsed_date = _parse_iso_date(trade_date)
        except ValueError as exc:
            raise SnapshotError(
                f"invalid stock_day date for {code}: {trade_date!r}"
            ) from exc
        source_date_stamp_number = _finite_number(doc.get("date_stamp"))
        if (
            source_date_stamp_number is None
            or not source_date_stamp_number.is_integer()
            or int(source_date_stamp_number) != _date_stamp(trade_date)
        ):
            raise SnapshotError(f"invalid source date_stamp for {code}/{trade_date}")
        session_no = session_by_date.get(parsed_date)
        if session_no is None:
            raise SnapshotError(f"calendar has no session for {code}/{trade_date}")

        quality_mask = 0
        raw_open = _finite_number(doc.get("open"))
        raw_high = _finite_number(doc.get("high"))
        raw_low = _finite_number(doc.get("low"))
        raw_close = _finite_number(doc.get("close"))
        raw_prices = {
            "open": raw_open,
            "high": raw_high,
            "low": raw_low,
            "close": raw_close,
        }
        valid_price_shape = not any(
            value is None or value <= 0 for value in raw_prices.values()
        )
        if valid_price_shape:
            assert raw_open is not None
            assert raw_high is not None
            assert raw_low is not None
            assert raw_close is not None
            valid_price_shape = bool(
                raw_high >= max(raw_open, raw_close)
                and raw_low <= min(raw_open, raw_close)
                and raw_high >= raw_low
            )
        if not valid_price_shape:
            quality_mask |= (
                QUALITY_RAW_PRICE_INVALID
                | QUALITY_EXCLUDED_CLX
                | QUALITY_EXCLUDED_MATCHING
            )

        raw_volume = _finite_number(doc.get("vol"))
        raw_amount = _finite_number(doc.get("amount"))
        source_volume = raw_volume
        source_amount = raw_amount
        if raw_volume is None or raw_volume < 0:
            raw_volume = None
            quality_mask |= (
                QUALITY_RAW_VOLUME_INVALID
                | QUALITY_EXCLUDED_CLX
                | QUALITY_EXCLUDED_MATCHING
            )
        elif 0 < abs(raw_volume) <= _SENTINEL_VOLUME_MAX:
            raw_volume = 0.0
            raw_amount = 0.0
            quality_mask |= QUALITY_SENTINEL_VOLUME_NORMALIZED

        if raw_amount is None or raw_amount < 0:
            raw_amount = None
            quality_mask |= QUALITY_AMOUNT_INVALID | QUALITY_EXCLUDED_MATCHING

        adj_factor = _finite_number(adj_by_date.get(trade_date))
        adjustment_status = "EXACT"
        gap_key = (code, trade_date)
        if adj_factor is None:
            policy = KNOWN_ADJ_GAPS.get(gap_key)
            if policy is None:
                raise SnapshotError(
                    f"unexpected missing stock_adj key: {code}/{trade_date}"
                )
            quality_mask |= QUALITY_ADJ_MISSING
            evidence = gap_evidence.get(gap_key, {})
            audit = {
                "code": code,
                "trade_date": trade_date,
                "disposition": policy["disposition"],
                "method": policy["method"],
                "source_volume": source_volume,
                "source_amount": source_amount,
                "normalized_volume": raw_volume,
                "normalized_amount": raw_amount,
                "evidence": evidence,
            }
            if policy["disposition"] == "REBUILT_VERIFIED":
                if not quality_mask & QUALITY_SENTINEL_VOLUME_NORMALIZED:
                    raise SnapshotError(
                        f"{code}/{trade_date} rebuild is allowed only for a sentinel-volume bar"
                    )
                adj_factor = _rebuild_factor(code, trade_date, policy, evidence)
                adjustment_status = "REBUILT_VERIFIED"
                quality_mask |= QUALITY_ADJ_REBUILT_VERIFIED
                audit["rebuilt_adj_factor"] = adj_factor
            else:
                adjustment_status = "EXCLUDED_ADJ_GAP"
                quality_mask |= QUALITY_EXCLUDED_CLX | QUALITY_EXCLUDED_MATCHING
            gap_audit.append(audit)
        elif adj_factor <= 0:
            raise SnapshotError(
                f"invalid non-positive stock_adj factor: {code}/{trade_date}={adj_factor}"
            )

        qfq_prices = {
            f"qfq_{field}": (
                raw_price * adj_factor
                if raw_price is not None and adj_factor is not None
                else None
            )
            for field, raw_price in raw_prices.items()
        }
        rows.append(
            {
                "code": code,
                "trade_date": parsed_date,
                "trade_year": parsed_date.year,
                "code_bucket": _code_bucket(code),
                "source_date_stamp": int(source_date_stamp_number),
                "session_no": session_no,
                "raw_open": raw_prices["open"],
                "raw_high": raw_prices["high"],
                "raw_low": raw_prices["low"],
                "raw_close": raw_prices["close"],
                "raw_volume": raw_volume,
                "volume_shares": raw_volume * 100.0 if raw_volume is not None else None,
                "raw_amount": raw_amount,
                "adj_factor": adj_factor,
                "adjustment_status": adjustment_status,
                **qfq_prices,
                "quality_mask": quality_mask,
            }
        )

    schema = {
        "code": pl.String,
        "trade_date": pl.Date,
        "trade_year": pl.Int16,
        "code_bucket": pl.UInt8,
        "source_date_stamp": pl.Int64,
        "session_no": pl.UInt32,
        "raw_open": pl.Float64,
        "raw_high": pl.Float64,
        "raw_low": pl.Float64,
        "raw_close": pl.Float64,
        "raw_volume": pl.Float64,
        "volume_shares": pl.Float64,
        "raw_amount": pl.Float64,
        "adj_factor": pl.Float64,
        "adjustment_status": pl.String,
        "qfq_open": pl.Float64,
        "qfq_high": pl.Float64,
        "qfq_low": pl.Float64,
        "qfq_close": pl.Float64,
        "quality_mask": pl.UInt32,
    }
    frame = pl.DataFrame(rows, schema=schema).sort(["code", "trade_date"])
    return frame, gap_audit


def _adjustment_gap_frame(observed_gaps: Sequence[Mapping[str, Any]]) -> pl.DataFrame:
    rows = []
    for item in observed_gaps:
        evidence = item.get("evidence", {})
        previous = evidence.get("previous") or {}
        following = evidence.get("following_within_as_of") or {}
        rows.append(
            {
                "code": item["code"],
                "trade_date": _parse_iso_date(item["trade_date"]),
                "disposition": item["disposition"],
                "method": item["method"],
                "source_volume": item.get("source_volume"),
                "source_amount": item.get("source_amount"),
                "normalized_volume": item.get("normalized_volume"),
                "normalized_amount": item.get("normalized_amount"),
                "rebuilt_adj_factor": item.get("rebuilt_adj_factor"),
                "previous_date": (
                    _parse_iso_date(previous["date"]) if previous.get("date") else None
                ),
                "previous_adj_factor": previous.get("adj"),
                "following_date": (
                    _parse_iso_date(following["date"])
                    if following.get("date")
                    else None
                ),
                "following_adj_factor": following.get("adj"),
                "evidence_sha256": _sha256_bytes(_canonical_json(evidence)),
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "code": pl.String,
            "trade_date": pl.Date,
            "disposition": pl.String,
            "method": pl.String,
            "source_volume": pl.Float64,
            "source_amount": pl.Float64,
            "normalized_volume": pl.Float64,
            "normalized_amount": pl.Float64,
            "rebuilt_adj_factor": pl.Float64,
            "previous_date": pl.Date,
            "previous_adj_factor": pl.Float64,
            "following_date": pl.Date,
            "following_adj_factor": pl.Float64,
            "evidence_sha256": pl.String,
        },
    ).sort(["code", "trade_date"])


def _write_parquet(frame: pl.DataFrame, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    frame.write_parquet(
        temporary,
        compression="zstd",
        compression_level=9,
        statistics=True,
        row_group_size=65536,
    )
    os.replace(temporary, path)
    result: dict[str, Any] = {
        "path": path.as_posix(),
        "rows": frame.height,
        "sha256": _sha256_file(path),
        "logical_sha256": _logical_frame_sha256(frame),
        "schema_fingerprint": _sha256_bytes(
            _canonical_json(
                [(name, str(dtype)) for name, dtype in frame.schema.items()]
            )
        ),
    }
    if frame.height and "trade_date" in frame.columns:
        result["min_trade_date"] = frame["trade_date"].min().isoformat()
        result["max_trade_date"] = frame["trade_date"].max().isoformat()
    return result


def _extract_code_frame(
    database: Any,
    *,
    code: str,
    filters: Mapping[str, Mapping[str, Any]],
    spec: SnapshotSpec,
    session_by_date: Mapping[date, int],
) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    day_docs = list(
        database["stock_day"].find(
            {"code": code, "date_stamp": filters["stock_day"]["date_stamp"]},
            {
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
            },
            sort=[("date_stamp", ASCENDING)],
        )
    )
    adj_docs = list(
        database["stock_adj"].find(
            {"code": code, "date": filters["stock_adj"]["date"]},
            {"_id": 0, "code": 1, "date": 1, "adj": 1},
            sort=[("date", ASCENDING)],
        )
    )
    day_dates = {str(doc.get("date", "")) for doc in day_docs}
    adj_dates = {str(doc.get("date", "")) for doc in adj_docs}
    missing_dates = sorted(day_dates - adj_dates)
    unexpected = [
        trade_date
        for trade_date in missing_dates
        if (code, trade_date) not in KNOWN_ADJ_GAPS
    ]
    if unexpected:
        raise SnapshotError(
            f"unexpected missing stock_adj keys for {code}: {unexpected[:10]}"
        )
    evidence = {
        (code, trade_date): _adj_gap_evidence(database, code, trade_date, spec.as_of)
        for trade_date in missing_dates
    }
    return _build_code_frame(
        code=code,
        day_docs=day_docs,
        adj_docs=adj_docs,
        gap_evidence=evidence,
        session_by_date=session_by_date,
    )


def create_snapshot(database: Any, output_dir: str | Path, spec: SnapshotSpec) -> Path:
    """Create and atomically publish one immutable CLX source snapshot."""

    output = Path(output_dir).resolve()
    if output.exists():
        existing = verify_snapshot(output)
        existing_manifest = json.loads((output / "manifest.json").read_text("utf-8"))
        if (
            existing_manifest["spec"]["start_date"] != spec.start_date
            or existing_manifest["spec"]["as_of"] != spec.as_of
            or existing_manifest["spec"].get("quiet_window_confirmed", False)
            != spec.quiet_window_confirmed
            or tuple(existing_manifest["spec"].get("requested_codes", ())) != spec.codes
        ):
            raise SnapshotError(f"existing snapshot has a different spec: {output}")
        if existing["status"] != "verified":
            raise SnapshotError(f"existing snapshot did not verify: {output}")
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    request_key = _sha256_bytes(
        _canonical_json(
            {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "start_date": spec.start_date,
                "as_of": spec.as_of,
                "requested_codes": list(spec.codes),
                "quiet_window_confirmed": spec.quiet_window_confirmed,
            }
        )
    )[:16]
    staging = output.parent / f".{output.name}.checkpoint-{request_key}"
    staging.mkdir(exist_ok=True)

    try:
        universe_before = _read_universe(database, spec)
        codes = tuple(row["code"] for row in universe_before)
        if not codes:
            raise SnapshotError("snapshot universe is empty")
        filters = _source_filters(codes, spec)
        state_before = _source_state(database, filters, universe_before)
        checkpoint_contract = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "spec": {
                "start_date": spec.start_date,
                "as_of": spec.as_of,
                "codes": list(codes),
                "quiet_window_confirmed": spec.quiet_window_confirmed,
            },
            "source_state_before": state_before,
            "checkpoint_unit": "code",
        }
        checkpoint_contract_path = staging / ".checkpoint.json"
        if checkpoint_contract_path.exists():
            recorded_checkpoint = json.loads(
                checkpoint_contract_path.read_text(encoding="utf-8")
            )
            if recorded_checkpoint != checkpoint_contract:
                stale = staging.with_name(f"{staging.name}.stale-{os.getpid()}")
                if stale.exists():
                    raise SnapshotError(
                        f"stale checkpoint target already exists: {stale}"
                    )
                os.replace(staging, stale)
                staging.mkdir()
        _atomic_write_bytes(
            checkpoint_contract_path,
            (
                json.dumps(
                    checkpoint_contract,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8"),
        )
        checkpoint_dir = staging / ".code-checkpoints"
        checkpoint_dir.mkdir(exist_ok=True)
        calendar_dates = sorted(
            _parse_iso_date(str(value))
            for value in database["stock_day"].distinct("date", filters["stock_day"])
        )
        if not calendar_dates:
            raise SnapshotError("snapshot calendar is empty")
        session_by_date = {
            trade_date: index for index, trade_date in enumerate(calendar_dates, 1)
        }
        calendar_frame = pl.DataFrame(
            {
                "trade_date": calendar_dates,
                "source_date_stamp": [
                    _date_stamp(value.isoformat()) for value in calendar_dates
                ],
                "session_no": list(range(1, len(calendar_dates) + 1)),
            },
            schema={
                "trade_date": pl.Date,
                "source_date_stamp": pl.Int64,
                "session_no": pl.UInt32,
            },
        )
        calendar_file = staging / "calendar" / "part-00000.parquet"
        calendar_meta = _write_parquet(calendar_frame, calendar_file)
        calendar_meta["path"] = calendar_file.relative_to(staging).as_posix()

        data_files: list[dict[str, Any]] = []
        observed_gaps: list[dict[str, Any]] = []
        universe_stats: dict[str, dict[str, Any]] = {}
        quality_counts = {name: 0 for name in QUALITY_FLAGS}
        total_rows = 0
        for code in codes:
            bucket = _code_bucket(code)
            parquet = (
                staging
                / "bars"
                / f"code_bucket={bucket:02d}"
                / f"code={code}"
                / "part-00000.parquet"
            )
            checkpoint_meta_path = checkpoint_dir / f"code={code}.json"
            if parquet.exists() and checkpoint_meta_path.exists():
                checkpoint_meta = json.loads(
                    checkpoint_meta_path.read_text(encoding="utf-8")
                )
                frame = pl.read_parquet(parquet)
                meta = checkpoint_meta["file"]
                if (
                    _sha256_file(parquet) != meta["sha256"]
                    or _logical_frame_sha256(frame) != meta["logical_sha256"]
                ):
                    raise SnapshotError(f"checkpoint hash mismatch for code {code}")
                code_gaps = checkpoint_meta["observed_adj_gaps"]
            else:
                frame, code_gaps = _extract_code_frame(
                    database,
                    code=code,
                    filters=filters,
                    spec=spec,
                    session_by_date=session_by_date,
                )
                meta = _write_parquet(frame, parquet)
                meta["path"] = parquet.relative_to(staging).as_posix()
                meta["partition"] = {"code_bucket": bucket, "code": code}
                _atomic_write_bytes(
                    checkpoint_meta_path,
                    (
                        json.dumps(
                            {"file": meta, "observed_adj_gaps": code_gaps},
                            ensure_ascii=False,
                            sort_keys=True,
                            indent=2,
                        )
                        + "\n"
                    ).encode("utf-8"),
                )
            observed_gaps.extend(code_gaps)
            total_rows += frame.height
            universe_stats[code] = {
                "first_trade_date": (
                    frame["trade_date"].min() if frame.height else None
                ),
                "last_trade_date": (
                    frame["trade_date"].max() if frame.height else None
                ),
                "bar_count": frame.height,
            }
            for flag_name, bit in QUALITY_FLAGS.items():
                quality_counts[flag_name] += int(
                    frame.select(((pl.col("quality_mask") & bit) != 0).sum()).item()
                )
            data_files.append(meta)

        universe_output = [
            {**row, **universe_stats[row["code"]], "quality_mask": 0}
            for row in universe_before
        ]
        universe_frame = pl.DataFrame(
            universe_output,
            schema={
                "code": pl.String,
                "name": pl.String,
                "exchange": pl.String,
                "security_type": pl.String,
                "volunit": pl.Int64,
                "decimal_point": pl.Int64,
                "in_current_stock_list": pl.Boolean,
                "first_trade_date": pl.Date,
                "last_trade_date": pl.Date,
                "bar_count": pl.UInt32,
                "quality_mask": pl.UInt32,
            },
        ).sort("code")
        universe_file = staging / "universe" / "part-00000.parquet"
        universe_meta = _write_parquet(universe_frame, universe_file)
        universe_meta["path"] = universe_file.relative_to(staging).as_posix()

        universe_after = _read_universe(database, spec)
        state_after = _source_state(database, filters, universe_after)
        if state_before != state_after or universe_before != universe_after:
            raise SnapshotError("filtered Mongo source changed during extraction")
        if total_rows != state_before["stock_day"]["count"]:
            raise SnapshotError(
                "extracted stock_day row count differs from the frozen source count"
            )
        shutil.rmtree(checkpoint_dir)
        checkpoint_contract_path.unlink()
        for temporary in staging.rglob(".*.tmp-*"):
            if temporary.is_file():
                temporary.unlink()

        known_gap_contract = [
            {"code": code, "trade_date": trade_date, **policy}
            for (code, trade_date), policy in sorted(KNOWN_ADJ_GAPS.items())
        ]
        manifest_spec = {
            "start_date": spec.start_date,
            "as_of": spec.as_of,
            "requested_codes": list(spec.codes),
            "codes": list(codes),
            "quiet_window_confirmed": spec.quiet_window_confirmed,
        }
        sorted_observed_gaps = sorted(
            observed_gaps, key=lambda row: (row["code"], row["trade_date"])
        )
        adjustment_gaps_frame = _adjustment_gap_frame(sorted_observed_gaps)
        adjustment_gaps_path = staging / "quality" / "adjustment_gaps.parquet"
        adjustment_gaps_meta = _write_parquet(
            adjustment_gaps_frame, adjustment_gaps_path
        )
        adjustment_gaps_meta["path"] = adjustment_gaps_path.relative_to(
            staging
        ).as_posix()
        snapshot_identity = _snapshot_identity_payload(
            spec=manifest_spec,
            source_state=state_before,
            calendar_file=calendar_meta,
            universe_file=universe_meta,
            adjustment_gaps_file=adjustment_gaps_meta,
            bar_files=data_files,
            observed_adj_gaps=sorted_observed_gaps,
            parquet_writer=PARQUET_WRITER,
        )
        snapshot_id = _sha256_bytes(_canonical_json(snapshot_identity))
        manifest: dict[str, Any] = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "spec": manifest_spec,
            "clx_engine_baseline": CLX_BASELINE_OPTIONS,
            "source": {
                "database": "quantaxis",
                "collections": ["stock_day", "stock_adj", "stock_list"],
                "access_mode": "READ_ONLY",
                "universe_derivation": {
                    "collection": "stock_day",
                    "operation": "distinct(code)",
                    "filter": _universe_day_filter(spec),
                },
                "filters": filters,
                "state_before": state_before,
                "state_after": state_after,
                "consistency_model": {
                    "gate": "before/after count+distinct_code_count+min/max+collection/index summaries",
                    "known_limit": (
                        "equal aggregate statistics cannot prove that no in-place source row "
                        "changed; ordered Parquet byte and logical hashes are the final evidence"
                    ),
                    "v2_quiet_window_required": True,
                },
            },
            "price_domains": {
                "raw": [
                    "raw_open",
                    "raw_high",
                    "raw_low",
                    "raw_close",
                    "raw_volume",
                    "volume_shares",
                    "raw_amount",
                ],
                "qfq": ["qfq_open", "qfq_high", "qfq_low", "qfq_close"],
                "formula": "qfq_{open,high,low,close}=raw_*adj_factor",
                "clx_input": "qfq_ohlc+raw_volume",
                "matching_input": "raw_ohlc",
                "units": {
                    "raw_volume": "LOT_100_SHARES",
                    "volume_shares": "SHARE (derived as raw_volume*100)",
                    "raw_amount": "CNY",
                },
            },
            "bias_disclosure": {
                "universe_basis": "distinct stock_day.code inside the frozen date range",
                "stock_list_role": (
                    "left-joined current metadata only; absence never removes a historical code"
                ),
                "known_limitations": [
                    "historical ST status is incomplete",
                    "historical delisting state is incomplete",
                    "stock_list metadata is current-state rather than point-in-time",
                ],
            },
            "quality_contract": {
                "mask_column": "quality_mask",
                "flags": QUALITY_FLAGS,
                "sentinel_volume_rule": (
                    "0 < abs(source vol) <= 1e-30 becomes raw_volume=0 and "
                    "raw_amount=0"
                ),
                "unknown_adj_gap_policy": "FAIL_SNAPSHOT",
                "excluded_rule": (
                    "rows carrying EXCLUDED_CLX or EXCLUDED_MATCHING are forbidden "
                    "in that downstream domain"
                ),
            },
            "known_adj_gap_contract": known_gap_contract,
            "observed_adj_gaps": sorted_observed_gaps,
            "dataset": {
                "primary_key": ["code", "trade_date"],
                "sort_order": ["code", "trade_date"],
                "partitioning": (
                    "bars/code_bucket=<00..63>/code=<six-digit-code>/part-00000.parquet"
                ),
                "partition_implementation": {
                    "choice": "one deterministic Parquet file per code",
                    "code_bucket_count": CODE_BUCKET_COUNT,
                    "code_bucket_formula": "int(sha256(code).hexdigest()[0:8],16)%64",
                    "reason": (
                        "bounded-memory extraction, whole-history CLX prefix reads, and one "
                        "immutable checkpoint per code"
                    ),
                },
                "publication": {
                    "canonical_layout": "snapshots/{snapshot_id}",
                    "atomic_unit": "whole snapshot directory rename on one filesystem",
                    "checkpoint_unit": "one code Parquet file",
                    "completed_artifacts_are_immutable": True,
                },
                "calendar": {
                    "source": "ascending distinct bar trade_date",
                    "session_numbering": "one-based contiguous",
                },
                "parquet_writer": PARQUET_WRITER,
                "row_count": total_rows,
                "quality_counts": quality_counts,
                "calendar_file": calendar_meta,
                "universe_file": universe_meta,
                "adjustment_gaps_file": adjustment_gaps_meta,
                "bar_files": data_files,
            },
        }
        manifest_bytes = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        manifest_sha256 = _sha256_bytes(manifest_bytes)
        _atomic_write_bytes(staging / "manifest.json", manifest_bytes)
        _atomic_write_bytes(
            staging / "manifest.sha256",
            f"{manifest_sha256}  manifest.json\n".encode("ascii"),
        )
        os.replace(staging, output)
        return output
    except BaseException:
        # Keep verified per-code checkpoints for an idempotent retry.  A changed
        # source state is detected by .checkpoint.json and starts a new staging
        # directory instead of mixing source versions.
        raise


def _all_bar_frames(
    snapshot_dir: Path, files: Sequence[Mapping[str, Any]]
) -> pl.DataFrame:
    frames = [pl.read_parquet(snapshot_dir / str(meta["path"])) for meta in files]
    if not frames:
        raise SnapshotError("manifest has no bar files")
    return pl.concat(frames, how="vertical")


def verify_snapshot(snapshot_dir: str | Path) -> dict[str, Any]:
    """Recompute hashes and invariants without consulting Mongo."""

    root = Path(snapshot_dir).resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "manifest_sha256" in manifest:
        raise SnapshotError("manifest must not contain a self-referential hash field")
    digest_path = root / "manifest.sha256"
    digest_line = digest_path.read_text(encoding="ascii").strip()
    match = re.fullmatch(r"([0-9a-f]{64})  manifest\.json", digest_line)
    if match is None:
        raise SnapshotError("manifest.sha256 format is invalid")
    recorded_manifest_hash = match.group(1)
    actual_manifest_hash = _sha256_file(manifest_path)
    if recorded_manifest_hash != actual_manifest_hash:
        raise SnapshotError("manifest_sha256 mismatch")

    file_entries = [
        manifest["dataset"]["calendar_file"],
        manifest["dataset"]["universe_file"],
        manifest["dataset"]["adjustment_gaps_file"],
        *manifest["dataset"]["bar_files"],
    ]
    listed_paths = {str(meta["path"]) for meta in file_entries}
    expected_paths = listed_paths | {"manifest.json", "manifest.sha256"}
    actual_paths = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    if expected_paths != actual_paths:
        raise SnapshotError("manifest artifact file set mismatch")
    for meta in file_entries:
        path = root / str(meta["path"])
        if _sha256_file(path) != meta["sha256"]:
            raise SnapshotError(f"Parquet SHA-256 mismatch: {meta['path']}")
        artifact_frame = pl.read_parquet(path)
        if _logical_frame_sha256(artifact_frame) != meta["logical_sha256"]:
            raise SnapshotError(f"Parquet logical SHA-256 mismatch: {meta['path']}")
        schema_fingerprint = _sha256_bytes(
            _canonical_json(
                [(name, str(dtype)) for name, dtype in artifact_frame.schema.items()]
            )
        )
        if schema_fingerprint != meta["schema_fingerprint"]:
            raise SnapshotError(f"Parquet schema fingerprint mismatch: {meta['path']}")

    expected_snapshot_id = _sha256_bytes(
        _canonical_json(
            _snapshot_identity_payload(
                spec=manifest["spec"],
                source_state=manifest["source"]["state_before"],
                calendar_file=manifest["dataset"]["calendar_file"],
                universe_file=manifest["dataset"]["universe_file"],
                adjustment_gaps_file=manifest["dataset"]["adjustment_gaps_file"],
                bar_files=manifest["dataset"]["bar_files"],
                observed_adj_gaps=manifest["observed_adj_gaps"],
                parquet_writer=manifest["dataset"]["parquet_writer"],
            )
        )
    )
    if manifest.get("snapshot_id") != expected_snapshot_id:
        raise SnapshotError("snapshot_id mismatch")
    if manifest["source"]["state_before"] != manifest["source"]["state_after"]:
        raise SnapshotError(
            "manifest source states differ before versus after extraction"
        )
    for collection_name in ("stock_day", "stock_adj", "stock_list"):
        source_summary = manifest["source"]["state_before"].get(collection_name, {})
        required_summary = {
            "count",
            "distinct_code_count",
            "min_date",
            "max_date",
            "collection_uuid",
            "indexes",
            "indexes_sha256",
        }
        if not required_summary.issubset(source_summary):
            raise SnapshotError(f"source summary is incomplete: {collection_name}")
        if source_summary["distinct_code_count"] > source_summary["count"]:
            raise SnapshotError(
                f"source distinct code count is invalid: {collection_name}"
            )
        if (
            _sha256_bytes(_canonical_json(source_summary["indexes"]))
            != source_summary["indexes_sha256"]
        ):
            raise SnapshotError(
                f"source index summary hash mismatch: {collection_name}"
            )
        if collection_name == "stock_list" and "content_sha256" not in source_summary:
            raise SnapshotError("stock_list source summary lacks its content hash")

    bars = _all_bar_frames(root, manifest["dataset"]["bar_files"])
    required = {
        "code",
        "trade_date",
        "trade_year",
        "code_bucket",
        "source_date_stamp",
        "session_no",
        "raw_open",
        "raw_high",
        "raw_low",
        "raw_close",
        "raw_volume",
        "volume_shares",
        "raw_amount",
        "adj_factor",
        "adjustment_status",
        "qfq_open",
        "qfq_high",
        "qfq_low",
        "qfq_close",
        "quality_mask",
    }
    if not required.issubset(bars.columns):
        raise SnapshotError(
            f"missing snapshot columns: {sorted(required - set(bars.columns))}"
        )
    if bars.height != manifest["dataset"]["row_count"]:
        raise SnapshotError("manifest row_count mismatch")
    if bars.select(pl.struct(["code", "trade_date"]).n_unique()).item() != bars.height:
        raise SnapshotError("duplicate (code, trade_date) primary key")
    if not bars.equals(bars.sort(["code", "trade_date"])):
        raise SnapshotError("bar dataset is not deterministically sorted")

    for meta in manifest["dataset"]["bar_files"]:
        partition = meta.get("partition", {})
        code = partition.get("code")
        bucket = partition.get("code_bucket")
        if not isinstance(code, str) or bucket != _code_bucket(code):
            raise SnapshotError("bar manifest has an invalid code partition")
        expected_path = f"bars/code_bucket={bucket:02d}/code={code}/part-00000.parquet"
        if meta["path"] != expected_path:
            raise SnapshotError(
                "bar path does not match its code_bucket/code partition"
            )
        partition_frame = pl.read_parquet(root / meta["path"])
        if (
            partition_frame["code"].n_unique() != 1
            or partition_frame["code"].item(0) != code
            or partition_frame["code_bucket"].n_unique() != 1
            or partition_frame["code_bucket"].item(0) != bucket
        ):
            raise SnapshotError("bar file rows do not match their manifest partition")

    if bars.filter(pl.col("trade_year") != pl.col("trade_date").dt.year()).height:
        raise SnapshotError("trade_year does not match trade_date")

    calendar = pl.read_parquet(root / manifest["dataset"]["calendar_file"]["path"])
    if calendar.columns != ["trade_date", "source_date_stamp", "session_no"]:
        raise SnapshotError("calendar schema mismatch")
    if not calendar.equals(calendar.sort("trade_date")):
        raise SnapshotError("calendar is not sorted")
    if calendar["trade_date"].n_unique() != calendar.height:
        raise SnapshotError("calendar contains duplicate trade_date")
    if calendar["session_no"].to_list() != list(range(1, calendar.height + 1)):
        raise SnapshotError("calendar session_no is not one-based contiguous")
    if bars.join(
        calendar,
        on=["trade_date", "source_date_stamp", "session_no"],
        how="anti",
    ).height:
        raise SnapshotError("bar has no matching calendar session")
    if calendar.join(
        bars.select("trade_date").unique(), on="trade_date", how="anti"
    ).height:
        raise SnapshotError("calendar contains a date absent from bars")

    universe = pl.read_parquet(root / manifest["dataset"]["universe_file"]["path"])
    universe_required = {
        "code",
        "name",
        "exchange",
        "volunit",
        "decimal_point",
        "in_current_stock_list",
        "first_trade_date",
        "last_trade_date",
        "bar_count",
        "quality_mask",
    }
    if not universe_required.issubset(universe.columns):
        raise SnapshotError("universe schema mismatch")
    if universe["code"].n_unique() != universe.height:
        raise SnapshotError("universe contains duplicate code")
    bar_stats = bars.group_by("code").agg(
        pl.col("trade_date").min().alias("actual_first"),
        pl.col("trade_date").max().alias("actual_last"),
        pl.len().alias("actual_count"),
    )
    universe_check = universe.join(bar_stats, on="code", how="full", coalesce=True)
    if universe_check.filter(
        (pl.col("first_trade_date") != pl.col("actual_first"))
        | (pl.col("last_trade_date") != pl.col("actual_last"))
        | (pl.col("bar_count") != pl.col("actual_count"))
        | pl.col("bar_count").is_null()
        | pl.col("actual_count").is_null()
    ).height:
        raise SnapshotError("universe first/last/bar_count mismatch")

    float_columns = [name for name, dtype in bars.schema.items() if dtype == pl.Float64]
    nan_count = int(
        bars.select(
            pl.sum_horizontal(
                [pl.col(name).is_nan().fill_null(False) for name in float_columns]
            )
            .sum()
            .alias("nan_count")
        ).item()
    )
    if nan_count:
        raise SnapshotError(f"snapshot contains {nan_count} IEEE NaN values")

    price_shape_valid = (
        pl.all_horizontal(
            [pl.col(f"raw_{field}").is_not_null() for field in _PRICE_FIELDS]
        )
        & pl.all_horizontal([pl.col(f"raw_{field}") > 0 for field in _PRICE_FIELDS])
        & (pl.col("raw_high") >= pl.max_horizontal("raw_open", "raw_close"))
        & (pl.col("raw_low") <= pl.min_horizontal("raw_open", "raw_close"))
        & (pl.col("raw_high") >= pl.col("raw_low"))
    )
    if bars.filter(
        ~price_shape_valid & ((pl.col("quality_mask") & QUALITY_RAW_PRICE_INVALID) == 0)
    ).height:
        raise SnapshotError("raw OHLC invariant violation is missing its quality flag")
    if bars.filter(pl.col("raw_volume") < 0).height:
        raise SnapshotError("raw_volume must be non-negative")
    if bars.filter(
        pl.col("raw_volume").is_null()
        & ((pl.col("quality_mask") & QUALITY_RAW_VOLUME_INVALID) == 0)
    ).height:
        raise SnapshotError("null raw_volume is missing its quality flag")
    volume_rows = bars.filter(pl.col("raw_volume").is_not_null())
    if volume_rows.filter(
        (pl.col("volume_shares") - pl.col("raw_volume") * 100.0).abs() > 1e-9
    ).height:
        raise SnapshotError("volume_shares must equal raw_volume lots times 100")
    if bars.filter(
        pl.col("raw_volume").is_null() & pl.col("volume_shares").is_not_null()
    ).height:
        raise SnapshotError("volume_shares must be null when raw_volume is null")
    if bars.filter(pl.col("raw_amount") < 0).height:
        raise SnapshotError("raw_amount must be non-negative")
    if bars.filter(
        pl.col("raw_amount").is_null()
        & (
            ((pl.col("quality_mask") & QUALITY_AMOUNT_INVALID) == 0)
            | ((pl.col("quality_mask") & QUALITY_EXCLUDED_MATCHING) == 0)
        )
    ).height:
        raise SnapshotError(
            "null raw_amount lacks amount-invalid/matching-excluded flags"
        )

    allowed_adjustment_status = {
        "EXACT",
        "REBUILT_VERIFIED",
        "EXCLUDED_ADJ_GAP",
    }
    if not set(bars["adjustment_status"].unique().to_list()).issubset(
        allowed_adjustment_status
    ):
        raise SnapshotError("bar has an unknown adjustment_status")

    for field in _PRICE_FIELDS:
        calculable = bars.filter(
            pl.col("adj_factor").is_not_null() & pl.col(f"raw_{field}").is_not_null()
        )
        mismatch = calculable.filter(
            (pl.col(f"qfq_{field}") - pl.col(f"raw_{field}") * pl.col("adj_factor"))
            .abs()
            .fill_null(float("inf"))
            > 1e-12
        ).height
        if mismatch:
            raise SnapshotError(f"qfq_{field} formula mismatch in {mismatch} rows")
        if bars.filter(
            (pl.col("adj_factor").is_null() | pl.col(f"raw_{field}").is_null())
            & pl.col(f"qfq_{field}").is_not_null()
        ).height:
            raise SnapshotError(
                f"qfq_{field} exists without both raw price and adj factor"
            )
    missing_adj = bars.filter(pl.col("adj_factor").is_null())
    if missing_adj.filter(
        ~(
            ((pl.col("quality_mask") & QUALITY_EXCLUDED_CLX) != 0)
            & ((pl.col("quality_mask") & QUALITY_EXCLUDED_MATCHING) != 0)
        )
    ).height:
        raise SnapshotError(
            "null adj_factor row is not excluded from both downstream domains"
        )
    for field in _PRICE_FIELDS:
        if missing_adj.filter(pl.col(f"qfq_{field}").is_not_null()).height:
            raise SnapshotError(f"qfq_{field} must be null when adj_factor is null")

    observed_gaps = manifest["observed_adj_gaps"]
    gap_keys = [(item["code"], item["trade_date"]) for item in observed_gaps]
    if len(gap_keys) != len(set(gap_keys)):
        raise SnapshotError("observed gap disposition is not unique by primary key")
    adjustment_gaps = pl.read_parquet(
        root / manifest["dataset"]["adjustment_gaps_file"]["path"]
    )
    expected_adjustment_gaps = _adjustment_gap_frame(observed_gaps)
    if not adjustment_gaps.equals(expected_adjustment_gaps):
        raise SnapshotError(
            "quality/adjustment_gaps.parquet does not match manifest evidence"
        )
    if (
        adjustment_gaps.select(pl.struct(["code", "trade_date"]).n_unique()).item()
        != adjustment_gaps.height
    ):
        raise SnapshotError("adjustment gap quality table has duplicate primary keys")
    for item in observed_gaps:
        row = bars.filter(
            (pl.col("code") == item["code"])
            & (pl.col("trade_date") == _parse_iso_date(item["trade_date"]))
        )
        if row.height != 1 or row["adjustment_status"].item() != item["disposition"]:
            raise SnapshotError("observed gap disposition does not match its bar")

    return {
        "snapshot_id": manifest["snapshot_id"],
        "manifest_sha256": recorded_manifest_hash,
        "row_count": bars.height,
        "code_count": bars["code"].n_unique(),
        "session_count": calendar.height,
        "nan_count": nan_count,
        "null_adj_count": missing_adj.height,
        "status": "verified",
    }


def publish_snapshot(
    database: Any, artifact_root: str | Path, spec: SnapshotSpec
) -> Path:
    """Publish to ``snapshots/{snapshot_id}`` with idempotent crash recovery."""

    if not spec.quiet_window_confirmed:
        raise SnapshotError(
            "canonical V2 publication requires quiet_window_confirmed=true"
        )
    snapshots_root = Path(artifact_root).resolve() / "snapshots"
    snapshots_root.mkdir(parents=True, exist_ok=True)
    request_key = _sha256_bytes(
        _canonical_json(
            {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "start_date": spec.start_date,
                "as_of": spec.as_of,
                "requested_codes": list(spec.codes),
                "quiet_window_confirmed": spec.quiet_window_confirmed,
            }
        )
    )[:16]
    candidate = snapshots_root / f".candidate-{request_key}"
    create_snapshot(database, candidate, spec)
    result = verify_snapshot(candidate)
    final = snapshots_root / result["snapshot_id"]
    if final.exists():
        final_result = verify_snapshot(final)
        if final_result["snapshot_id"] != result["snapshot_id"]:
            raise SnapshotError(f"content-addressed snapshot collision: {final}")
        shutil.rmtree(candidate)
        return final

    os.replace(candidate, final)
    for path in final.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    for path in sorted(
        (path for path in final.rglob("*") if path.is_dir()),
        key=lambda value: len(value.parts),
        reverse=True,
    ):
        path.chmod(0o555)
    final.chmod(0o555)
    verify_snapshot(final)
    return final


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="create an immutable Mongo snapshot")
    create.add_argument(
        "--mongo-uri", default=os.getenv("CLX_MONGO_URI", "mongodb://fq_mongodb:27017")
    )
    create.add_argument("--database", default="quantaxis")
    create.add_argument("--start-date", required=True)
    create.add_argument("--as-of", required=True)
    create.add_argument("--code", action="append", default=[])
    create.add_argument("--quiet-window-confirmed", action="store_true")
    destination = create.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output-dir")
    destination.add_argument("--artifact-root")
    verify = subparsers.add_parser("verify", help="verify an existing snapshot")
    verify.add_argument("--snapshot-dir", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "verify":
        print(
            json.dumps(
                verify_snapshot(args.snapshot_dir), ensure_ascii=False, sort_keys=True
            )
        )
        return 0

    spec = SnapshotSpec(
        start_date=args.start_date,
        as_of=args.as_of,
        codes=tuple(args.code),
        quiet_window_confirmed=args.quiet_window_confirmed,
    )
    client = MongoClient(args.mongo_uri, appname="freshquant-clx-snapshot-v1")
    try:
        if args.artifact_root:
            output = publish_snapshot(client[args.database], args.artifact_root, spec)
        else:
            output = create_snapshot(client[args.database], args.output_dir, spec)
    finally:
        client.close()
    result = verify_snapshot(output)
    result["snapshot_dir"] = str(output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
