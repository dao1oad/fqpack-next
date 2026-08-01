"""Canonical XTData ``preClose`` based QFQ factor pipeline.

The public entry points are intentionally dependency-injectable.  Production
uses ``xtquant.xtdata`` and Mongo; unit tests can provide a bar loader and an
in-memory database without changing the factor contract.
"""

from __future__ import annotations

import math
import re
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from freshquant.bootstrap_config import bootstrap_config
from freshquant.db import DBQuantAxis
from freshquant.instrument.general import is_trading_etf_code

QFQ_DATA_NOT_READY = "QFQ_DATA_NOT_READY"
QFQ_SOURCE = "xtdata_preclose"
QFQ_WRITER = "freshquant.market_data.xtdata.qfq"
QFQ_SCHEMA_VERSION = 1
FACTOR_COLLECTIONS = {
    "stock": {
        "a": "stock_adj_qfq_a",
        "b": "stock_adj_qfq_b",
    },
    "etf": {
        "a": "etf_adj_qfq_a",
        "b": "etf_adj_qfq_b",
    },
}
LEGACY_FACTOR_COLLECTIONS = {"stock": "stock_adj", "etf": "etf_adj"}
# BFQ is the coverage authority for each factor universe.  ``index_day`` is
# intentionally used for ETF history because QUANTAXIS stores exchange-traded
# funds in that collection alongside real indexes.
BFQ_COLLECTIONS = {"stock": "stock_day", "etf": "index_day"}
READY_COLLECTION = "qfq_ready"
WRITER_LOCK_COLLECTION = "qfq_writer_locks"
DEFAULT_TAIL_AUDIT_DAYS = 60
DEFAULT_READER_GRACE_SECONDS = 300
DEFAULT_WRITER_LEASE_SECONDS = 3600
XTDATA_TRADING_TIMEZONE = timezone(timedelta(hours=8))
BFQ_SENTINEL_VALUE = 5.877471754e-39
ETF_OPEN_FUND_HINTS = (
    "开放式",
    "联接",
    "场外",
)


class QFQSyncError(RuntimeError):
    """A synchronization run failed before its snapshot became visible."""

    error_code = QFQ_DATA_NOT_READY

    def __init__(self, message: str, *, stats: Mapping[str, Any] | None = None):
        self.stats = dict(stats or {})
        super().__init__(f"{QFQ_DATA_NOT_READY}: {message}")


def _date_key(value: Any) -> str | None:
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        try:
            if (
                len(text) == 10
                and text[4] == "-"
                and text[7] == "-"
                and text.replace("-", "").isdigit()
            ):
                return date.fromisoformat(text).isoformat()
            if len(text) == 8 and text.isdigit():
                return date(int(text[:4]), int(text[4:6]), int(text[6:8])).isoformat()
        except ValueError:
            return None
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(
        value, (bool, np.bool_)
    ):
        number = float(value)
        if not math.isfinite(number):
            return None
        try:
            if 10_000_000 <= number < 100_000_000:
                text = str(int(number))
                return date(int(text[:4]), int(text[4:6]), int(text[6:8])).isoformat()
            if number > 10_000_000_000:
                return (
                    datetime.fromtimestamp(number / 1000, tz=timezone.utc)
                    .date()
                    .isoformat()
                )
            if number > 1_000_000_000:
                return (
                    datetime.fromtimestamp(number, tz=timezone.utc).date().isoformat()
                )
        except (OSError, OverflowError, ValueError):
            return None
    parsed = _parse_timestamp(value)
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def _xtdata_date_key(value: Any) -> str | None:
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(
        value, (bool, np.bool_)
    ):
        number = float(value)
        if math.isfinite(number):
            try:
                if number > 10_000_000_000:
                    return (
                        datetime.fromtimestamp(
                            number / 1000, tz=XTDATA_TRADING_TIMEZONE
                        )
                        .date()
                        .isoformat()
                    )
                if number > 1_000_000_000:
                    return (
                        datetime.fromtimestamp(number, tz=XTDATA_TRADING_TIMEZONE)
                        .date()
                        .isoformat()
                    )
            except (OSError, OverflowError, ValueError):
                return None
    return _date_key(value)


def _xt_date_arg(value: Any) -> str:
    """Format a BFQ boundary in the date form accepted by XTData."""

    key = _date_key(value)
    return key.replace("-", "") if key else ""


def normalize_code(code: Any) -> str:
    """Normalize a security code to the six-character factor contract."""

    text = str(code or "").strip().lower()
    match = re.search(r"(\d{6})", text)
    if match:
        return match.group(1)
    digits = "".join(char for char in text if char.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def to_xt_code(code: Any, *, market: str | None = None) -> str:
    """Convert a prefixed/base code to XTData's ``000001.SZ`` form."""

    text = str(code or "").strip().upper()
    if "." in text and len(text.rsplit(".", 1)[-1]) == 2:
        return text
    base = normalize_code(text)
    suffix = str(market or "").strip().upper()
    if suffix not in {"SH", "SZ", "BJ"}:
        if base.startswith("920") or base.startswith(("4", "8")):
            suffix = "BJ"
        elif base.startswith(("5", "6")):
            suffix = "SH"
        else:
            suffix = "SZ"
    return f"{base}.{suffix}"


def _parse_timestamp(value: Any) -> pd.Timestamp:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number):
            return pd.NaT
        if 10_000_000 <= number < 100_000_000:
            return pd.to_datetime(str(int(number)), format="%Y%m%d", errors="coerce")
        if number > 10_000_000_000:
            return pd.to_datetime(number, unit="ms", errors="coerce")
        if number > 1_000_000_000:
            return pd.to_datetime(number, unit="s", errors="coerce")
    return pd.to_datetime(value, errors="coerce")


def _row_key(frame: pd.DataFrame, code: str | None) -> Any:
    if frame.empty:
        return None
    candidates = [str(code or ""), str(code or "").upper(), str(code or "").lower()]
    for candidate in candidates:
        if candidate and candidate in frame.index:
            return candidate
    return frame.index[0] if len(frame.index) == 1 else None


def _field_column_date(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return _date_key(value)
    text = str(value).strip()
    if (len(text) == 8 and text.isdigit()) or (
        len(text) == 10
        and text[4] == "-"
        and text[7] == "-"
        and text.replace("-", "").isdigit()
    ):
        return _date_key(text)
    return None


def _field_table_to_rows(
    payload: Mapping[str, Any], code: str | None
) -> pd.DataFrame | None:
    fields = {str(key).lower(): value for key, value in payload.items()}
    known = {
        "time",
        "date",
        "datetime",
        "close",
        "preclose",
        "pre_close",
        "open",
        "high",
        "low",
    }
    if not (known & set(fields)):
        return None

    # ``get_market_data`` returns field -> DataFrame(index=code, columns=time).
    tables = [value for value in fields.values() if isinstance(value, pd.DataFrame)]
    sample = next((value for value in tables if not value.empty), None)
    if (
        tables
        and sample is None
        and all(isinstance(value, pd.DataFrame) for value in fields.values())
    ):
        return pd.DataFrame()
    if sample is not None:
        key = _row_key(sample, code)
        if key is not None:
            columns = list(sample.columns)
            rows: list[dict[str, Any]] = []
            for column in columns:
                column_date = _field_column_date(column)
                row: dict[str, Any] = (
                    {"date": column_date} if column_date else {"time": column}
                )
                for field_name, value in fields.items():
                    if isinstance(value, pd.DataFrame) and key in value.index:
                        row[field_name] = value.loc[key].get(column)
                    elif isinstance(value, pd.Series):
                        row[field_name] = value.get(column)
                    elif isinstance(value, Sequence) and not isinstance(
                        value, (str, bytes)
                    ):
                        index = columns.index(column)
                        if index < len(value):
                            row[field_name] = value[index]
                rows.append(row)
            return pd.DataFrame(rows)

    # Some test doubles return field -> list/Series directly.
    lengths = [
        len(value)
        for value in fields.values()
        if isinstance(value, (list, tuple, pd.Series))
    ]
    if lengths:
        size = max(lengths)
        rows = []
        for index in range(size):
            row = {}
            for field_name, value in fields.items():
                if isinstance(value, (list, tuple, pd.Series)) and index < len(value):
                    row[field_name] = value[index]
                elif not isinstance(value, (list, tuple, pd.Series)):
                    row[field_name] = value
            rows.append(row)
        return pd.DataFrame(rows)
    return None


def normalize_xtdata_bars(payload: Any, *, code: str | None = None) -> pd.DataFrame:
    """Normalize common XTData daily payload shapes.

    The result has ``date``, ``close`` and ``preClose`` columns and is sorted
    by the actual dates returned by XTData.  No calendar interpolation occurs.
    """

    frame: pd.DataFrame | None = None
    if isinstance(payload, pd.DataFrame):
        frame = payload.copy()
    elif isinstance(payload, Mapping):
        frame = _field_table_to_rows(payload, code)
        if frame is None:
            # ``get_market_data_ex`` returns code -> DataFrame.
            selected = None
            for key in (
                str(code or ""),
                str(code or "").upper(),
                str(code or "").lower(),
            ):
                if key and key in payload:
                    selected = payload[key]
                    break
            if selected is None and len(payload) == 1:
                selected = next(iter(payload.values()))
            if isinstance(selected, pd.DataFrame):
                frame = selected.copy()
            elif isinstance(selected, Sequence) and not isinstance(
                selected, (str, bytes)
            ):
                frame = pd.DataFrame(selected)
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        frame = pd.DataFrame(payload)
    if frame is None:
        raise QFQSyncError(f"unsupported XTData payload for code={code}")
    if frame.empty:
        raise QFQSyncError(f"XTData returned no daily bars for code={code}")

    aliases = {
        "pre_close": "preClose",
        "preclose": "preClose",
        "pre-close": "preClose",
        "timestamp": "time",
        "datetime": "time",
    }
    frame = frame.rename(
        columns={
            column: aliases.get(str(column).lower(), column) for column in frame.columns
        }
    )
    if "time" not in frame.columns and "date" not in frame.columns:
        frame = frame.copy()
        frame["time"] = frame.index
    if "close" not in frame.columns or "preClose" not in frame.columns:
        raise QFQSyncError(f"XTData daily bars missing close/preClose for code={code}")
    source_dates = frame["date"] if "date" in frame.columns else frame["time"]
    frame["date"] = [_xtdata_date_key(value) or "" for value in source_dates]
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["preClose"] = pd.to_numeric(frame["preClose"], errors="coerce")
    frame = frame.loc[frame["date"].astype(bool)].copy()
    frame = frame.sort_values("date").reset_index(drop=True)
    if frame["date"].duplicated().any():
        duplicates = sorted(
            frame.loc[frame["date"].duplicated(), "date"].unique().tolist()
        )
        raise QFQSyncError(
            f"duplicate XTData trading dates for code={code}: {duplicates[:10]}"
        )
    valid_close = frame["close"].map(
        lambda value: math.isfinite(float(value)) and float(value) > 0
    )
    if not valid_close.all():
        raise QFQSyncError(f"invalid close values for code={code}")
    used_preclose = frame["preClose"].iloc[1:]
    valid_used_preclose = used_preclose.map(
        lambda value: math.isfinite(float(value)) and float(value) > 0
    )
    if not valid_used_preclose.all():
        raise QFQSyncError(f"invalid used preClose values for code={code}")
    return frame


def compute_preclose_adj(bars: Any, *, code: str | None = None) -> pd.DataFrame:
    """Compute canonical QFQ factors from an ascending actual-date bar axis."""

    day = normalize_xtdata_bars(bars, code=code)
    close = day["close"].to_numpy(dtype=float)
    preclose = day["preClose"].to_numpy(dtype=float)
    factors = np.ones(len(day), dtype=float)
    if len(day) > 1:
        ratios = preclose[1:] / close[:-1]
        if not np.isfinite(ratios).all() or (ratios <= 0).any():
            raise QFQSyncError(f"invalid preClose/close ratio for code={code}")
        factors[:-1] = np.cumprod(ratios[::-1])[::-1]
    result = pd.DataFrame({"date": day["date"].tolist(), "adj": factors})
    result["adj"] = pd.to_numeric(result["adj"], errors="coerce")
    if (
        not result["adj"]
        .map(lambda value: math.isfinite(float(value)) and float(value) > 0)
        .all()
    ):
        raise QFQSyncError(f"invalid computed factors for code={code}")
    if code:
        result.insert(0, "code", normalize_code(code))
    return result


# Names used by callers and older migration notes.
compute_qfq_factors = compute_preclose_adj
compute_xtdata_preclose_adj = compute_preclose_adj
normalize_xtdata_daily_payload = normalize_xtdata_bars


def _doc_text(document: Mapping[str, Any]) -> str:
    return " ".join(
        str(document.get(key) or "")
        for key in ("name", "type", "category", "sec", "fund_type")
    ).lower()


def is_trading_etf(document_or_code: Any) -> bool:
    """Return true only for exchange-traded ETF candidates.

    Prefixes provide the fallback for sparse ``etf_list`` records; explicit
    open-ended/fund metadata always wins and excludes the record.
    """

    document = document_or_code if isinstance(document_or_code, Mapping) else {}
    code = normalize_code(document.get("code") if document else document_or_code)
    if not code or not is_trading_etf_code(code):
        return False
    if document.get("is_etf") is False or document.get("etf") is False:
        return False
    text = _doc_text(document)
    if any(hint in text for hint in ETF_OPEN_FUND_HINTS):
        return False
    type_value = str(
        document.get("instrument_type") or document.get("asset_type") or ""
    ).lower()
    if type_value and "etf" not in type_value and "exchange" not in type_value:
        return False
    return True


def _distinct_codes(collection) -> set[str]:
    try:
        values = collection.distinct("code")
    except (AttributeError, TypeError):
        try:
            values = [row.get("code") for row in collection.find({}, {"code": 1})]
        except TypeError:
            values = [row.get("code") for row in collection.find({})]
    return {normalize_code(value) for value in values if normalize_code(value)}


def load_factor_universe(
    *,
    kind: str,
    db=DBQuantAxis,
    codes: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Load the full factor universe without monitor-pool/max-symbol limits."""

    if kind not in FACTOR_COLLECTIONS:
        raise ValueError(f"unsupported factor kind: {kind}")
    list_collection_name = "stock_list" if kind == "stock" else "etf_list"
    requested = {
        normalize_code(value) for value in (codes or ()) if normalize_code(value)
    }
    documents = list(db[list_collection_name].find({}, {"_id": 0}))
    metadata = {
        normalize_code(document.get("code")): document
        for document in documents
        if normalize_code(document.get("code"))
    }
    candidates = (
        _distinct_codes(db[BFQ_COLLECTIONS[kind]])
        | set(metadata)
        | _distinct_codes(db[LEGACY_FACTOR_COLLECTIONS[kind]])
    )
    if codes is not None:
        candidates &= requested
    included: set[str] = set()
    excluded: list[dict[str, Any]] = []
    for code in sorted(candidates):
        document = metadata.get(code, {"code": code})
        if kind == "etf" and not is_trading_etf(document):
            excluded.append({"code": code, "reason": "not_trading_etf"})
            continue
        if kind == "stock" and is_trading_etf_code(code):
            excluded.append({"code": code, "reason": "etf_like_code"})
            continue
        included.add(code)
    missing_requested = requested - candidates if codes is not None else set()
    excluded.extend(
        {"code": code, "reason": "not_in_factor_universe"}
        for code in sorted(missing_requested)
    )
    return {
        "kind": kind,
        "codes": sorted(included),
        "excluded": excluded,
        "monitor_pool_independent": True,
    }


def _is_bfq_sentinel_row(row: Mapping[str, Any]) -> bool:
    volume = row.get("vol", row.get("volume"))
    amount = row.get("amount")
    if volume is None or amount is None:
        return False
    try:
        values = (float(volume), float(amount))
    except (TypeError, ValueError):
        return False
    return all(
        math.isfinite(value)
        and math.isclose(value, BFQ_SENTINEL_VALUE, rel_tol=1e-9, abs_tol=0.0)
        for value in values
    )


def _load_bfq_coverage(*, kind: str, code: str, db=DBQuantAxis) -> dict[str, Any]:
    if kind not in BFQ_COLLECTIONS:
        raise ValueError(f"unsupported BFQ kind: {kind}")
    code6 = normalize_code(code)
    collection = db[BFQ_COLLECTIONS[kind]]
    query = {"code": code6}
    projection = {
        "_id": 0,
        "date": 1,
        "vol": 1,
        "volume": 1,
        "amount": 1,
    }
    try:
        cursor = collection.find(query, projection)
    except TypeError:
        cursor = collection.find(query)
    dates: list[str] = []
    sentinel_dates: list[str] = []
    invalid: list[Any] = []
    for row in cursor:
        value = row.get("date") if isinstance(row, Mapping) else None
        if isinstance(row, Mapping) and _is_bfq_sentinel_row(row):
            sentinel_dates.append(_date_key(value) or str(value))
            continue
        key = _date_key(value)
        if key is None:
            invalid.append(value)
        else:
            dates.append(key)
    if invalid:
        raise QFQSyncError(
            f"{kind} BFQ history contains invalid dates for code={code6}",
            stats={"kind": kind, "code": code6, "invalid_dates": invalid[:20]},
        )
    return {
        "dates": sorted(set(dates)),
        "sentinel_rows": len(sentinel_dates),
        "sentinel_dates": sorted(set(sentinel_dates))[:20],
    }


def load_bfq_dates(*, kind: str, code: str, db=DBQuantAxis) -> list[str]:
    """Return valid BFQ trading dates, excluding explicit QASU filler rows."""

    return _load_bfq_coverage(kind=kind, code=code, db=db)["dates"]


def _new_bfq_coverage_summary() -> dict[str, Any]:
    return {
        "sentinel_rows_excluded": 0,
        "codes_with_sentinel_rows": 0,
        "skipped_codes": 0,
        "skipped": [],
    }


def _select_bfq_dates(
    *,
    code: str,
    coverage: Mapping[str, Any],
    target_date: str | None,
    summary: dict[str, Any],
) -> list[str]:
    sentinel_rows = int(coverage.get("sentinel_rows") or 0)
    if sentinel_rows:
        summary["sentinel_rows_excluded"] += sentinel_rows
        summary["codes_with_sentinel_rows"] += 1
    dates = list(coverage.get("dates") or ())
    selected = [date for date in dates if not target_date or date <= target_date]
    if selected:
        return selected
    if sentinel_rows and not dates:
        reason = "sentinel_only_bfq_history"
    elif dates and target_date:
        reason = "no_bfq_history_by_target"
    else:
        reason = "no_bfq_history"
    summary["skipped_codes"] += 1
    if len(summary["skipped"]) < 100:
        item: dict[str, Any] = {"code": normalize_code(code), "reason": reason}
        if sentinel_rows:
            item["sentinel_rows"] = sentinel_rows
        summary["skipped"].append(item)
    return []


def _bfq_download_bounds(
    bfq_dates: Iterable[str], *, start_time: str = "", end_time: str = ""
) -> tuple[str, str, list[str]]:
    """Resolve XTData bounds and the expected BFQ subset for a ticket."""

    dates = sorted(set(str(value)[:10] for value in bfq_dates if str(value).strip()))
    if not dates:
        return _xt_date_arg(start_time), _xt_date_arg(end_time), []
    requested_start = _date_key(start_time) if start_time else dates[0]
    requested_end = _date_key(end_time) if end_time else dates[-1]
    if requested_start is None:
        requested_start = dates[0]
    if requested_end is None:
        requested_end = dates[-1]
    if requested_start > requested_end:
        raise QFQSyncError(
            "invalid XTData date bounds",
            stats={"start_time": start_time, "end_time": end_time},
        )
    expected = [value for value in dates if requested_start <= value <= requested_end]
    return _xt_date_arg(requested_start), _xt_date_arg(requested_end), expected


def audit_factor_snapshot(
    documents: Iterable[Mapping[str, Any]],
    *,
    expected_dates_by_code: Mapping[str, Iterable[Any]] | None = None,
    included_codes: Iterable[str] | None = None,
    require_exact_dates: bool = False,
    bars_by_code: Mapping[str, Any] | None = None,
    rel_tol: float = 1e-10,
) -> dict[str, Any]:
    rows = [dict(item) for item in (documents or ())]
    by_code: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_code.setdefault(normalize_code(row.get("code")), []).append(row)
    expected_map = {
        normalize_code(code): list(dates)
        for code, dates in (expected_dates_by_code or {}).items()
    }
    missing_codes: list[str] = []
    invalid = 0
    duplicates = 0
    terminal_not_one: list[str] = []
    recurrence_errors: list[tuple[str, str]] = []
    missing_dates: list[tuple[str, str]] = []
    source_missing_dates: list[tuple[str, str]] = []
    extra_dates: list[tuple[str, str]] = []
    for code in sorted({normalize_code(c) for c in (included_codes or by_code)}):
        code_rows = by_code.get(code, [])
        normalized: list[tuple[str, float]] = []
        seen: set[str] = set()
        for row in code_rows:
            date_key = _date_key(row.get("date"))
            factor_value = row.get("adj")
            try:
                factor = float(factor_value) if factor_value is not None else math.nan
            except (TypeError, ValueError):
                factor = math.nan
            if not date_key or not math.isfinite(factor) or factor <= 0:
                invalid += 1
                continue
            if date_key in seen:
                duplicates += 1
            seen.add(date_key)
            normalized.append((date_key, factor))
        normalized.sort(key=lambda item: item[0])
        expected_dates = {
            key
            for key in (_date_key(value) for value in expected_map.get(code, ()))
            if key
        }
        actual_dates = {date for date, _factor in normalized}
        missing_dates.extend(
            (code, date) for date in sorted(expected_dates - actual_dates)
        )
        if require_exact_dates:
            extra_dates.extend(
                (code, date) for date in sorted(actual_dates - expected_dates)
            )
        if not code_rows:
            missing_codes.append(code)
            continue
        if normalized and not math.isclose(
            normalized[-1][1], 1.0, rel_tol=0.0, abs_tol=1e-12
        ):
            terminal_not_one.append(code)
        bars_payload = (bars_by_code or {}).get(code)
        if bars_payload is not None and normalized:
            bars = normalize_xtdata_bars(bars_payload, code=code)
            factors = {date: factor for date, factor in normalized}
            source_rows = compute_preclose_adj(bars, code=code)
            source_factors = dict(
                zip(source_rows["date"], source_rows["adj"], strict=True)
            )
            if require_exact_dates:
                source_missing_dates.extend(
                    (code, date) for date in sorted(set(factors) - set(source_factors))
                )
            for factor_date, factor in factors.items():
                source_factor = source_factors.get(factor_date)
                if source_factor is None:
                    continue
                if not math.isclose(
                    factor,
                    float(source_factor),
                    rel_tol=rel_tol,
                    abs_tol=1e-12,
                ):
                    recurrence_errors.append((code, factor_date))
    return {
        "codes": len(set(by_code) | set(expected_map)),
        "rows": len(rows),
        "missing": len(missing_codes) + len(missing_dates) + len(source_missing_dates),
        "missing_codes": missing_codes,
        "missing_dates": missing_dates,
        "source_missing_dates": source_missing_dates,
        "extra": len(extra_dates),
        "extra_dates": extra_dates,
        "invalid": invalid,
        "duplicates": duplicates,
        "terminal_not_one": terminal_not_one,
        "recurrence_errors": recurrence_errors,
        "ok": (
            not missing_codes
            and not missing_dates
            and not source_missing_dates
            and not extra_dates
            and invalid == 0
            and duplicates == 0
            and not terminal_not_one
            and not recurrence_errors
        ),
    }


def _ensure_factor_indexes(collection) -> None:
    collection.create_index(
        [("code", 1), ("date", 1)], unique=True, name="code_date_unique"
    )
    collection.create_index([("date", 1)], name="date_idx")


def _utc_now(now_provider=None) -> datetime:
    now = now_provider() if callable(now_provider) else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _datetime_iso(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _utc_iso(now_provider=None) -> str:
    return _datetime_iso(_utc_now(now_provider))


def _ensure_writer_lock_indexes(collection) -> None:
    collection.create_index([("scope", 1)], unique=True, name="scope_unique")


def _acquire_writer_lease(
    *,
    db,
    scope: str,
    now_provider=None,
    lease_seconds: int = DEFAULT_WRITER_LEASE_SECONDS,
) -> str:
    collection = db[WRITER_LOCK_COLLECTION]
    _ensure_writer_lock_indexes(collection)
    now = _utc_now(now_provider)
    existing = collection.find_one({"scope": scope}, {"_id": 0})
    if existing:
        expires_at = pd.Timestamp(existing.get("expires_at"))
        if pd.isna(expires_at):
            raise QFQSyncError(
                f"{scope} QFQ writer lease is invalid", stats={"lease": existing}
            )
        if expires_at.tzinfo is None:
            expires_at = expires_at.tz_localize("UTC")
        if expires_at.tz_convert("UTC") > pd.Timestamp(now):
            raise QFQSyncError(
                f"{scope} QFQ writer lease is held",
                stats={
                    "owner_id": existing.get("owner_id"),
                    "expires_at": existing.get("expires_at"),
                },
            )
        stale_result = collection.delete_one(
            {
                "scope": scope,
                "owner_id": existing.get("owner_id"),
                "expires_at": existing.get("expires_at"),
            }
        )
        if int(getattr(stale_result, "deleted_count", 0)) != 1:
            raise QFQSyncError(f"{scope} QFQ stale writer lease takeover lost")

    owner_id = uuid.uuid4().hex
    acquired_at = _datetime_iso(now)
    expires_at = _datetime_iso(now + timedelta(seconds=max(60, int(lease_seconds))))
    try:
        collection.insert_one(
            {
                "scope": scope,
                "owner_id": owner_id,
                "acquired_at": acquired_at,
                "updated_at": acquired_at,
                "expires_at": expires_at,
            }
        )
    except Exception as exc:
        raise QFQSyncError(f"{scope} QFQ writer lease acquisition lost") from exc
    return owner_id


def _refresh_writer_lease(
    *,
    db,
    scope: str,
    owner_id: str,
    now_provider=None,
    lease_seconds: int = DEFAULT_WRITER_LEASE_SECONDS,
) -> None:
    now = _utc_now(now_provider)
    result = db[WRITER_LOCK_COLLECTION].update_one(
        {"scope": scope, "owner_id": owner_id},
        {
            "$set": {
                "updated_at": _datetime_iso(now),
                "expires_at": _datetime_iso(
                    now + timedelta(seconds=max(60, int(lease_seconds)))
                ),
            }
        },
    )
    if int(getattr(result, "matched_count", 0)) != 1:
        raise QFQSyncError(f"{scope} QFQ writer lease was lost")


def _release_writer_lease(*, db, scope: str, owner_id: str) -> None:
    db[WRITER_LOCK_COLLECTION].delete_one({"scope": scope, "owner_id": owner_id})


class _WriterLeaseHeartbeat:
    def __init__(
        self,
        *,
        db,
        scope: str,
        owner_id: str,
        lease_seconds: int,
        now_provider=None,
        heartbeat_seconds: float | None = None,
    ):
        self.db = db
        self.scope = scope
        self.owner_id = owner_id
        self.lease_seconds = lease_seconds
        self.now_provider = now_provider
        self.interval = (
            max(0.01, float(heartbeat_seconds))
            if heartbeat_seconds is not None
            else min(60.0, max(1.0, float(lease_seconds) / 3.0))
        )
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._failure: Exception | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"qfq-lease-{scope}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            with self._lock:
                if self._stop.is_set():
                    return
                try:
                    self._refresh()
                except Exception as exc:  # noqa: BLE001
                    self._failure = exc
                    return

    def _refresh(self) -> None:
        _refresh_writer_lease(
            db=self.db,
            scope=self.scope,
            owner_id=self.owner_id,
            now_provider=self.now_provider,
            lease_seconds=self.lease_seconds,
        )

    def pulse(self) -> None:
        with self._lock:
            self._raise_if_failed_locked()
            self._refresh()

    def raise_if_failed(self) -> None:
        with self._lock:
            self._raise_if_failed_locked()

    def _raise_if_failed_locked(self) -> None:
        if self._failure is not None:
            raise QFQSyncError(
                f"{self.scope} QFQ writer lease heartbeat failed"
            ) from self._failure

    def run_fenced_publish(self, callback: Callable[[], Any]) -> Any:
        with self._lock:
            self._raise_if_failed_locked()
            self._refresh()
            result = callback()
            self._stop.set()
            return result

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5.0)


def _ensure_marker_indexes(collection) -> None:
    collection.create_index([("scope", 1)], unique=True, name="scope_unique")


def get_qfq_marker(*, scope: str, db=DBQuantAxis) -> dict[str, Any] | None:
    if scope not in FACTOR_COLLECTIONS:
        raise ValueError(f"unsupported QFQ scope: {scope}")
    marker = db[READY_COLLECTION].find_one({"scope": scope}, {"_id": 0})
    return dict(marker) if marker else None


def validate_qfq_marker(
    marker: Mapping[str, Any] | None, *, scope: str
) -> dict[str, Any]:
    if not marker:
        raise QFQSyncError(f"{scope} QFQ marker is missing")
    if marker.get("scope") != scope:
        raise QFQSyncError(f"{scope} QFQ marker scope mismatch")
    if marker.get("source") != QFQ_SOURCE:
        raise QFQSyncError(f"{scope} QFQ marker source mismatch")
    if marker.get("schema_version") != QFQ_SCHEMA_VERSION:
        raise QFQSyncError(f"{scope} QFQ marker schema mismatch")
    active_slot = marker.get("active_slot")
    slots = marker.get("slots")
    if active_slot not in {"a", "b"} or not isinstance(slots, Mapping):
        raise QFQSyncError(f"{scope} QFQ marker slots are invalid")
    for slot in ("a", "b"):
        document = slots.get(slot)
        expected_collection = FACTOR_COLLECTIONS[scope][slot]
        if not isinstance(document, Mapping):
            raise QFQSyncError(f"{scope} QFQ slot {slot} is missing")
        if document.get("collection") != expected_collection:
            raise QFQSyncError(f"{scope} QFQ slot {slot} collection mismatch")
        if not document.get("snapshot_id") or not document.get("factor_asof"):
            raise QFQSyncError(f"{scope} QFQ slot {slot} metadata is incomplete")
        if document.get("status") not in {"ready", "building", "failed"}:
            raise QFQSyncError(f"{scope} QFQ slot {slot} status is invalid")
    if slots[active_slot].get("status") != "ready":
        raise QFQSyncError(f"{scope} active QFQ slot is not ready")
    return dict(marker)


def resolve_active_slot(*, scope: str, db=DBQuantAxis) -> dict[str, Any]:
    marker = validate_qfq_marker(get_qfq_marker(scope=scope, db=db), scope=scope)
    active_slot = str(marker["active_slot"])
    return {
        "scope": scope,
        "slot": active_slot,
        **dict(marker["slots"][active_slot]),
    }


def _new_slot_document(
    *, scope: str, slot: str, snapshot_id: str, factor_asof: str, published_at: str
) -> dict[str, Any]:
    return {
        "collection": FACTOR_COLLECTIONS[scope][slot],
        "snapshot_id": snapshot_id,
        "factor_asof": factor_asof,
        "status": "ready",
        "published_at": published_at,
    }


def _insert_bootstrap_marker(
    *, db, scope: str, factor_asof: str, now_provider=None
) -> dict[str, Any]:
    published_at = _utc_iso(now_provider)
    marker = {
        "scope": scope,
        "active_slot": "a",
        "slots": {
            slot: _new_slot_document(
                scope=scope,
                slot=slot,
                snapshot_id=uuid.uuid4().hex,
                factor_asof=factor_asof,
                published_at=published_at,
            )
            for slot in ("a", "b")
        },
        "source": QFQ_SOURCE,
        "schema_version": QFQ_SCHEMA_VERSION,
    }
    collection = db[READY_COLLECTION]
    _ensure_marker_indexes(collection)
    if collection.find_one({"scope": scope}) is not None:
        raise QFQSyncError(f"{scope} QFQ marker already exists")
    try:
        collection.insert_one(marker)
    except Exception as exc:
        raise QFQSyncError(f"{scope} bootstrap marker insert failed") from exc
    return marker


def _inactive_slot_name(marker: Mapping[str, Any]) -> str:
    return "b" if marker.get("active_slot") == "a" else "a"


def _claim_inactive_slot(*, db, scope: str, marker: Mapping[str, Any]) -> str:
    active_slot = str(marker["active_slot"])
    inactive_slot = _inactive_slot_name(marker)
    active_snapshot = marker["slots"][active_slot]["snapshot_id"]
    result = db[READY_COLLECTION].update_one(
        {
            "scope": scope,
            "active_slot": active_slot,
            f"slots.{active_slot}.snapshot_id": active_snapshot,
            f"slots.{inactive_slot}.status": {"$in": ["ready", "failed"]},
        },
        {"$set": {f"slots.{inactive_slot}.status": "building"}},
    )
    if int(getattr(result, "matched_count", 0)) != 1:
        raise QFQSyncError(f"{scope} inactive QFQ slot claim lost")
    return inactive_slot


def _mark_inactive_failed(
    *, db, scope: str, active_slot: str, active_snapshot: str, inactive_slot: str
) -> None:
    db[READY_COLLECTION].update_one(
        {
            "scope": scope,
            "active_slot": active_slot,
            f"slots.{active_slot}.snapshot_id": active_snapshot,
            f"slots.{inactive_slot}.status": "building",
        },
        {"$set": {f"slots.{inactive_slot}.status": "failed"}},
    )


def _publish_inactive_slot(
    *,
    db,
    scope: str,
    marker: Mapping[str, Any],
    inactive_slot: str,
    factor_asof: str,
    now_provider=None,
) -> dict[str, Any]:
    active_slot = str(marker["active_slot"])
    active_snapshot = str(marker["slots"][active_slot]["snapshot_id"])
    slot_document = _new_slot_document(
        scope=scope,
        slot=inactive_slot,
        snapshot_id=uuid.uuid4().hex,
        factor_asof=factor_asof,
        published_at=_utc_iso(now_provider),
    )
    result = db[READY_COLLECTION].update_one(
        {
            "scope": scope,
            "active_slot": active_slot,
            f"slots.{active_slot}.snapshot_id": active_snapshot,
            f"slots.{inactive_slot}.status": "building",
        },
        {
            "$set": {
                "active_slot": inactive_slot,
                f"slots.{inactive_slot}": slot_document,
            }
        },
    )
    if int(getattr(result, "matched_count", 0)) != 1:
        raise QFQSyncError(f"{scope} QFQ marker CAS publish lost")
    return validate_qfq_marker(get_qfq_marker(scope=scope, db=db), scope=scope)


def _rollback_active_slot_locked(
    *, scope: str, db, now_provider=None
) -> dict[str, Any]:
    marker = validate_qfq_marker(get_qfq_marker(scope=scope, db=db), scope=scope)
    active_slot = str(marker["active_slot"])
    target_slot = _inactive_slot_name(marker)
    if marker["slots"][target_slot].get("status") != "ready":
        raise QFQSyncError(f"{scope} rollback slot is not ready")
    result = db[READY_COLLECTION].update_one(
        {
            "scope": scope,
            "active_slot": active_slot,
            f"slots.{active_slot}.snapshot_id": marker["slots"][active_slot][
                "snapshot_id"
            ],
            f"slots.{target_slot}.snapshot_id": marker["slots"][target_slot][
                "snapshot_id"
            ],
            f"slots.{target_slot}.status": "ready",
        },
        {
            "$set": {
                "active_slot": target_slot,
                f"slots.{target_slot}.published_at": _utc_iso(now_provider),
            }
        },
    )
    if int(getattr(result, "matched_count", 0)) != 1:
        raise QFQSyncError(f"{scope} QFQ rollback CAS lost")
    return validate_qfq_marker(get_qfq_marker(scope=scope, db=db), scope=scope)


def rollback_active_slot(
    *,
    scope: str,
    db=DBQuantAxis,
    now_provider=None,
    writer_lease_seconds: int = DEFAULT_WRITER_LEASE_SECONDS,
) -> dict[str, Any]:
    owner_id = _acquire_writer_lease(
        db=db,
        scope=scope,
        now_provider=now_provider,
        lease_seconds=writer_lease_seconds,
    )
    try:
        return _rollback_active_slot_locked(
            scope=scope, db=db, now_provider=now_provider
        )
    finally:
        _release_writer_lease(db=db, scope=scope, owner_id=owner_id)


def _recover_interrupted_build_locked(*, scope: str, db) -> dict[str, Any] | None:
    """Mark a leftover inactive build failed before the single writer retries."""

    marker = validate_qfq_marker(get_qfq_marker(scope=scope, db=db), scope=scope)
    active_slot = str(marker["active_slot"])
    inactive_slot = _inactive_slot_name(marker)
    if marker["slots"][inactive_slot].get("status") != "building":
        return None
    result = db[READY_COLLECTION].update_one(
        {
            "scope": scope,
            "active_slot": active_slot,
            f"slots.{active_slot}.snapshot_id": marker["slots"][active_slot][
                "snapshot_id"
            ],
            f"slots.{inactive_slot}.status": "building",
        },
        {"$set": {f"slots.{inactive_slot}.status": "failed"}},
    )
    if int(getattr(result, "matched_count", 0)) != 1:
        raise QFQSyncError(f"{scope} interrupted build recovery CAS lost")
    return validate_qfq_marker(get_qfq_marker(scope=scope, db=db), scope=scope)


def recover_interrupted_build(
    *,
    scope: str,
    db=DBQuantAxis,
    now_provider=None,
    writer_lease_seconds: int = DEFAULT_WRITER_LEASE_SECONDS,
) -> dict[str, Any] | None:
    owner_id = _acquire_writer_lease(
        db=db,
        scope=scope,
        now_provider=now_provider,
        lease_seconds=writer_lease_seconds,
    )
    try:
        return _recover_interrupted_build_locked(scope=scope, db=db)
    finally:
        _release_writer_lease(db=db, scope=scope, owner_id=owner_id)


class XtDataQfqClient:
    def __init__(self, xtdata_module=None, *, port: int | None = None):
        self.xtdata = xtdata_module
        self.port = int(port or bootstrap_config.xtdata.port or 58610)
        self.connected = False

    def _get_xtdata(self):
        if self.xtdata is None:
            from xtquant import xtdata  # type: ignore

            self.xtdata = xtdata
        return self.xtdata

    def load_daily_bars(
        self,
        code: str,
        *,
        market: str | None = None,
        start_time: str = "",
        end_time: str = "",
    ) -> pd.DataFrame:
        xtdata = self._get_xtdata()
        if not self.connected and hasattr(xtdata, "connect"):
            xtdata.connect(port=self.port)
            self.connected = True
        xt_code = to_xt_code(code, market=market)
        if hasattr(xtdata, "download_history_data"):
            xtdata.download_history_data(xt_code, "1d", start_time, end_time)

        def load_bars() -> pd.DataFrame:
            payload = xtdata.get_market_data(
                field_list=["time", "close", "preClose"],
                stock_list=[xt_code],
                period="1d",
                start_time=start_time,
                end_time=end_time,
                dividend_type="none",
                fill_data=False,
            )
            return normalize_xtdata_bars(payload, code=xt_code)

        bars = load_bars()
        requested_start = _date_key(start_time)
        earliest = _date_key(bars.iloc[0]["date"])
        while (
            hasattr(xtdata, "download_history_data")
            and requested_start
            and earliest
            and earliest > requested_start
        ):
            prefix_end = _xt_date_arg(date.fromisoformat(earliest) - timedelta(days=1))
            xtdata.download_history_data(xt_code, "1d", start_time, prefix_end)
            next_bars = load_bars()
            next_earliest = _date_key(next_bars.iloc[0]["date"])
            if not next_earliest or next_earliest >= earliest:
                raise QFQSyncError(
                    "XTData history prefix download made no progress "
                    f"for code={xt_code}: earliest={earliest}, "
                    f"prefix_end={prefix_end}"
                )
            bars = next_bars
            earliest = next_earliest
        return bars


def _call_loader(
    loader: Callable[..., Any], code: str, start_time: str, end_time: str
) -> Any:
    try:
        return loader(code, start_time=start_time, end_time=end_time)
    except TypeError:
        try:
            return loader(code, start_time, end_time)
        except TypeError:
            return loader(code)


def _load_existing_factor_rows(
    *, db, collection_name: str, code: str
) -> list[dict[str, Any]]:
    collection = db[collection_name]
    query = {"code": normalize_code(code)}
    projection = {"_id": 0, "code": 1, "date": 1, "adj": 1}
    try:
        cursor = collection.find(query, projection)
    except TypeError:
        cursor = collection.find(query)
    try:
        cursor = cursor.sort("date", 1)
    except AttributeError:
        pass
    return [dict(row) for row in cursor]


def _audit_code_rows(
    *,
    code: str,
    rows: Iterable[Mapping[str, Any]],
    expected_dates: Iterable[str],
    bars: Any | None = None,
) -> dict[str, Any]:
    code6 = normalize_code(code)
    return audit_factor_snapshot(
        rows,
        expected_dates_by_code={code6: list(expected_dates)},
        included_codes=[code6],
        require_exact_dates=True,
        bars_by_code={code6: bars} if bars is not None else None,
    )


def _replace_code_rows(
    *, collection, code: str, rows: Iterable[Mapping[str, Any]]
) -> int:
    code6 = normalize_code(code)
    normalized = [
        {
            "code": code6,
            "date": str(row["date"])[:10],
            "adj": float(row["adj"]),
        }
        for row in rows
    ]
    collection.delete_many({"code": code6})
    if normalized:
        collection.insert_many(normalized, ordered=False)
    return len(normalized)


def _full_rebuild_code(
    *,
    collection,
    code: str,
    expected_dates: list[str],
    loader: Callable[..., Any],
    reason: str,
) -> dict[str, Any]:
    load_start, load_end, expected = _bfq_download_bounds(expected_dates)
    bars = _call_loader(loader, code, load_start, load_end)
    expected_set = set(expected)
    rows = [
        row
        for row in compute_preclose_adj(bars, code=code).to_dict(orient="records")
        if str(row["date"])[:10] in expected_set
    ]
    audit = _audit_code_rows(code=code, rows=rows, expected_dates=expected, bars=bars)
    if not audit["ok"]:
        raise QFQSyncError(
            f"full QFQ rebuild audit failed for code={code}", stats=audit
        )
    written = _replace_code_rows(collection=collection, code=code, rows=rows)
    return {"mode": "full", "reason": reason, "rows_written": written}


def _rows_form_exact_prefix(
    *, rows: list[dict[str, Any]], expected_dates: list[str], code: str
) -> bool:
    if not rows or len(rows) > len(expected_dates):
        return False
    dates = [_date_key(row.get("date")) for row in rows]
    prefix = expected_dates[: len(rows)]
    audit = _audit_code_rows(code=code, rows=rows, expected_dates=prefix)
    return bool(audit["ok"] and dates == prefix)


def _reconcile_code(
    *,
    collection,
    code: str,
    expected_dates: list[str],
    loader: Callable[..., Any],
    tail_days: int,
) -> dict[str, Any]:
    existing = _load_existing_factor_rows(
        db={collection.name: collection}, collection_name=collection.name, code=code
    )
    if not _rows_form_exact_prefix(
        rows=existing, expected_dates=expected_dates, code=code
    ):
        return _full_rebuild_code(
            collection=collection,
            code=code,
            expected_dates=expected_dates,
            loader=loader,
            reason="missing_or_invalid_prefix",
        )

    existing_dates = [str(row["date"])[:10] for row in existing]
    last_existing = existing_dates[-1]
    last_index = expected_dates.index(last_existing)
    tail_start_index = max(0, last_index - max(2, int(tail_days)) + 1)
    tail_dates = expected_dates[tail_start_index:]
    bars = _call_loader(
        loader,
        code,
        _xt_date_arg(tail_dates[0]),
        _xt_date_arg(tail_dates[-1]),
    )
    tail_date_set = set(tail_dates)
    tail_rows = [
        row
        for row in compute_preclose_adj(bars, code=code).to_dict(orient="records")
        if str(row["date"])[:10] in tail_date_set
    ]
    tail_audit = _audit_code_rows(
        code=code, rows=tail_rows, expected_dates=tail_dates, bars=bars
    )
    if not tail_audit["ok"]:
        raise QFQSyncError(f"tail QFQ audit failed for code={code}", stats=tail_audit)
    tail_by_date = {str(row["date"])[:10]: float(row["adj"]) for row in tail_rows}
    if not math.isclose(tail_by_date[last_existing], 1.0, rel_tol=1e-10, abs_tol=1e-12):
        return _full_rebuild_code(
            collection=collection,
            code=code,
            expected_dates=expected_dates,
            loader=loader,
            reason="corporate_action_after_inactive_terminal",
        )

    existing_by_date = {str(row["date"])[:10]: float(row["adj"]) for row in existing}
    overlap_dates = [date for date in tail_dates if date <= last_existing]
    if any(
        not math.isclose(
            existing_by_date[date],
            tail_by_date[date],
            rel_tol=1e-10,
            abs_tol=1e-12,
        )
        for date in overlap_dates
    ):
        return _full_rebuild_code(
            collection=collection,
            code=code,
            expected_dates=expected_dates,
            loader=loader,
            reason="tail_revision",
        )

    missing_dates = [date for date in expected_dates if date > last_existing]
    for date in missing_dates:
        collection.update_one(
            {"code": normalize_code(code), "date": date},
            {
                "$set": {
                    "code": normalize_code(code),
                    "date": date,
                    "adj": tail_by_date[date],
                }
            },
            upsert=True,
        )
    updated = _load_existing_factor_rows(
        db={collection.name: collection}, collection_name=collection.name, code=code
    )
    audit = _audit_code_rows(code=code, rows=updated, expected_dates=expected_dates)
    if not audit["ok"]:
        raise QFQSyncError(
            f"incremental QFQ output audit failed for code={code}", stats=audit
        )
    return {
        "mode": "incremental" if missing_dates else "unchanged",
        "reason": "ordinary_tail",
        "rows_written": len(missing_dates),
        "previous_last_date": last_existing,
    }


def _copy_factor_collection(*, db, source_name: str, target_name: str) -> None:
    source = db[source_name]
    try:
        list(
            source.aggregate(
                [
                    {"$project": {"_id": 0, "code": 1, "date": 1, "adj": 1}},
                    {"$out": target_name},
                ],
                allowDiskUse=True,
            )
        )
    except (AttributeError, NotImplementedError, TypeError):
        target = db[target_name]
        target.delete_many({})
        batch: list[dict[str, Any]] = []
        for row in source.find({}, {"_id": 0, "code": 1, "date": 1, "adj": 1}):
            batch.append(dict(row))
            if len(batch) >= 10_000:
                target.insert_many(batch, ordered=False)
                batch = []
        if batch:
            target.insert_many(batch, ordered=False)
    _ensure_factor_indexes(db[target_name])


def _count_documents(collection, query: Mapping[str, Any] | None = None) -> int:
    try:
        return int(collection.count_documents(dict(query or {})))
    except AttributeError:
        return len(list(collection.find(dict(query or {}))))


def audit_qfq_slot(
    *,
    scope: str,
    slot: str,
    db=DBQuantAxis,
    codes: Iterable[str] | None = None,
    factor_asof: str | None = None,
    bars_loader: Callable[..., Any] | None = None,
    source_tail_days: int | None = None,
    progress_callback: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if scope not in FACTOR_COLLECTIONS or slot not in {"a", "b"}:
        raise ValueError(f"unsupported QFQ slot: {scope}/{slot}")
    marker = get_qfq_marker(scope=scope, db=db)
    if factor_asof is None and marker:
        factor_asof = str(
            marker.get("slots", {}).get(slot, {}).get("factor_asof") or ""
        )
    universe = load_factor_universe(kind=scope, db=db, codes=codes)
    collection = db[FACTOR_COLLECTIONS[scope][slot]]
    failures: list[dict[str, Any]] = []
    rows = 0
    checked_codes = 0
    coverage_summary = _new_bfq_coverage_summary()
    for code in universe["codes"]:
        if progress_callback:
            progress_callback()
        coverage = _load_bfq_coverage(kind=scope, code=code, db=db)
        expected = _select_bfq_dates(
            code=code,
            coverage=coverage,
            target_date=factor_asof,
            summary=coverage_summary,
        )
        if not expected:
            continue
        code_rows = _load_existing_factor_rows(
            db=db, collection_name=collection.name, code=code
        )
        audit_dates = expected
        bars = None
        audit_rows = code_rows
        if bars_loader is not None:
            if source_tail_days is not None:
                audit_dates = expected[-max(2, int(source_tail_days)) :]
            load_start, load_end, audit_dates = _bfq_download_bounds(audit_dates)
            bars = _call_loader(bars_loader, code, load_start, load_end)
            audit_date_set = set(audit_dates)
            audit_rows = [
                row for row in code_rows if _date_key(row.get("date")) in audit_date_set
            ]
        audit = _audit_code_rows(
            code=code,
            rows=audit_rows,
            expected_dates=audit_dates,
            bars=bars,
        )
        rows += len(audit_rows)
        checked_codes += 1
        if not audit["ok"]:
            failures.append({"code": code, "audit": audit})
    if progress_callback:
        progress_callback()
    return {
        "scope": scope,
        "slot": slot,
        "collection": collection.name,
        "factor_asof": factor_asof,
        "audit_mode": (
            "structure"
            if bars_loader is None
            else "tail_source" if source_tail_days is not None else "full_source"
        ),
        "codes": checked_codes,
        "rows": rows,
        "coverage": coverage_summary,
        "failed": len(failures),
        "failures": failures[:100],
        "ok": not failures and checked_codes > 0,
    }


def _bootstrap_scope(
    *,
    scope: str,
    target_date: str,
    db,
    codes: Iterable[str] | None,
    loader: Callable[..., Any],
    now_provider=None,
    progress_callback: Callable[[], None] | None = None,
    publish_callback: Callable[[Callable[[], Any]], Any] | None = None,
) -> dict[str, Any]:
    if get_qfq_marker(scope=scope, db=db):
        raise QFQSyncError(f"{scope} QFQ bootstrap requires no marker")
    universe = load_factor_universe(kind=scope, db=db, codes=codes)
    collection_a = db[FACTOR_COLLECTIONS[scope]["a"]]
    collection_a.delete_many({})
    _ensure_factor_indexes(collection_a)
    included: list[str] = []
    rows_written = 0
    coverage_summary = _new_bfq_coverage_summary()
    for code in universe["codes"]:
        if progress_callback:
            progress_callback()
        coverage = _load_bfq_coverage(kind=scope, code=code, db=db)
        expected = _select_bfq_dates(
            code=code,
            coverage=coverage,
            target_date=target_date,
            summary=coverage_summary,
        )
        if not expected:
            continue
        result = _full_rebuild_code(
            collection=collection_a,
            code=code,
            expected_dates=expected,
            loader=loader,
            reason="bootstrap",
        )
        rows_written += int(result["rows_written"])
        included.append(code)
    if not included:
        raise QFQSyncError(f"{scope} has no BFQ history to bootstrap")
    audit_a = audit_qfq_slot(
        scope=scope,
        slot="a",
        db=db,
        codes=included,
        factor_asof=target_date,
        progress_callback=progress_callback,
    )
    if not audit_a["ok"]:
        raise QFQSyncError(f"{scope} bootstrap slot A audit failed", stats=audit_a)
    if progress_callback:
        progress_callback()
    _copy_factor_collection(
        db=db,
        source_name=FACTOR_COLLECTIONS[scope]["a"],
        target_name=FACTOR_COLLECTIONS[scope]["b"],
    )
    audit_b = audit_qfq_slot(
        scope=scope,
        slot="b",
        db=db,
        codes=included,
        factor_asof=target_date,
        progress_callback=progress_callback,
    )
    if not audit_b["ok"] or audit_a["rows"] != audit_b["rows"]:
        raise QFQSyncError(f"{scope} bootstrap slot B audit failed", stats=audit_b)

    def publish_marker() -> dict[str, Any]:
        return _insert_bootstrap_marker(
            db=db, scope=scope, factor_asof=target_date, now_provider=now_provider
        )

    if publish_callback:
        marker = publish_callback(publish_marker)
    else:
        if progress_callback:
            progress_callback()
        marker = publish_marker()
    return {
        "scope": scope,
        "mode": "bootstrap",
        "factor_asof": target_date,
        "codes": len(included),
        "rows_written": rows_written,
        "coverage": coverage_summary,
        "marker": marker,
        "audit": {"a": audit_a, "b": audit_b},
    }


def _assert_reader_grace(
    *, marker: Mapping[str, Any], min_grace_seconds: int, now_provider=None
) -> None:
    if min_grace_seconds <= 0:
        return
    active_slot = str(marker["active_slot"])
    published_at = pd.Timestamp(marker["slots"][active_slot]["published_at"])
    now = now_provider() if callable(now_provider) else datetime.now(timezone.utc)
    now_ts = pd.Timestamp(now)
    if published_at.tzinfo is None:
        published_at = published_at.tz_localize("UTC")
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize("UTC")
    elapsed = (
        now_ts.tz_convert("UTC") - published_at.tz_convert("UTC")
    ).total_seconds()
    if elapsed < min_grace_seconds:
        raise QFQSyncError(
            "reader grace period has not elapsed",
            stats={"elapsed_seconds": elapsed, "required_seconds": min_grace_seconds},
        )


def _update_scope(
    *,
    scope: str,
    target_date: str,
    db,
    codes: Iterable[str] | None,
    loader: Callable[..., Any],
    tail_days: int,
    min_grace_seconds: int,
    force_full_rebuild: bool,
    now_provider=None,
    progress_callback: Callable[[], None] | None = None,
    publish_callback: Callable[[Callable[[], Any]], Any] | None = None,
) -> dict[str, Any]:
    marker = validate_qfq_marker(get_qfq_marker(scope=scope, db=db), scope=scope)
    active_slot = str(marker["active_slot"])
    active_snapshot = str(marker["slots"][active_slot]["snapshot_id"])
    active_asof = str(marker["slots"][active_slot]["factor_asof"])
    if target_date < active_asof:
        raise QFQSyncError(
            f"{scope} QFQ target date predates active snapshot",
            stats={"target_date": target_date, "active_factor_asof": active_asof},
        )
    if not force_full_rebuild and target_date <= active_asof:
        return {
            "scope": scope,
            "mode": "noop",
            "factor_asof": active_asof,
            "marker": marker,
        }
    _assert_reader_grace(
        marker=marker,
        min_grace_seconds=min_grace_seconds,
        now_provider=now_provider,
    )
    inactive_slot = _claim_inactive_slot(db=db, scope=scope, marker=marker)
    collection = db[FACTOR_COLLECTIONS[scope][inactive_slot]]
    stats = {
        "full": 0,
        "incremental": 0,
        "unchanged": 0,
        "rows_written": 0,
        "stale_codes_removed": 0,
    }
    coverage_summary = _new_bfq_coverage_summary()
    try:
        _ensure_factor_indexes(collection)
        universe = load_factor_universe(kind=scope, db=db, codes=codes)
        included: list[str] = []
        for code in universe["codes"]:
            if progress_callback:
                progress_callback()
            coverage = _load_bfq_coverage(kind=scope, code=code, db=db)
            expected = _select_bfq_dates(
                code=code,
                coverage=coverage,
                target_date=target_date,
                summary=coverage_summary,
            )
            if not expected:
                continue
            if force_full_rebuild:
                result = _full_rebuild_code(
                    collection=collection,
                    code=code,
                    expected_dates=expected,
                    loader=loader,
                    reason="forced_full_rebuild",
                )
            else:
                result = _reconcile_code(
                    collection=collection,
                    code=code,
                    expected_dates=expected,
                    loader=loader,
                    tail_days=tail_days,
                )
            stats[str(result["mode"])] += 1
            stats["rows_written"] += int(result["rows_written"])
            included.append(code)
        stale_codes = _distinct_codes(collection) - set(included)
        if stale_codes and force_full_rebuild:
            collection.delete_many({"code": {"$in": sorted(stale_codes)}})
            stats["stale_codes_removed"] = len(stale_codes)
            stale_codes = _distinct_codes(collection) - set(included)
        if stale_codes:
            raise QFQSyncError(
                f"{scope} inactive slot contains codes outside BFQ universe",
                stats={"stale_codes": sorted(stale_codes)[:100]},
            )
        audit = audit_qfq_slot(
            scope=scope,
            slot=inactive_slot,
            db=db,
            codes=included,
            factor_asof=target_date,
            progress_callback=progress_callback,
        )
        if not audit["ok"]:
            raise QFQSyncError(f"{scope} inactive slot audit failed", stats=audit)

        def publish_marker() -> dict[str, Any]:
            return _publish_inactive_slot(
                db=db,
                scope=scope,
                marker=marker,
                inactive_slot=inactive_slot,
                factor_asof=target_date,
                now_provider=now_provider,
            )

        if publish_callback:
            published = publish_callback(publish_marker)
        else:
            if progress_callback:
                progress_callback()
            published = publish_marker()
        return {
            "scope": scope,
            "mode": "update",
            "factor_asof": target_date,
            "slot": inactive_slot,
            "stats": stats,
            "coverage": coverage_summary,
            "audit": audit,
            "marker": published,
        }
    except Exception:
        _mark_inactive_failed(
            db=db,
            scope=scope,
            active_slot=active_slot,
            active_snapshot=active_snapshot,
            inactive_slot=inactive_slot,
        )
        raise


def sync_qfq_factors(
    *,
    scope: str,
    target_date: str,
    db=DBQuantAxis,
    codes: Iterable[str] | None = None,
    bars_loader: Callable[..., Any] | None = None,
    xtdata_client: XtDataQfqClient | None = None,
    tail_days: int = DEFAULT_TAIL_AUDIT_DAYS,
    min_grace_seconds: int = DEFAULT_READER_GRACE_SECONDS,
    force_full_rebuild: bool = False,
    writer_lease_seconds: int = DEFAULT_WRITER_LEASE_SECONDS,
    writer_heartbeat_seconds: float | None = None,
    now_provider=None,
) -> dict[str, Any]:
    scopes = [item.strip().lower() for item in str(scope).split(",") if item.strip()]
    if not scopes or any(item not in FACTOR_COLLECTIONS for item in scopes):
        raise ValueError(f"unsupported QFQ scope: {scope}")
    target = _date_key(target_date)
    if not target:
        raise ValueError(f"invalid QFQ target date: {target_date}")
    if force_full_rebuild and codes is not None:
        raise ValueError(
            "force_full_rebuild requires the full scope; codes must be omitted"
        )
    client = xtdata_client or XtDataQfqClient()
    loader = bars_loader or client.load_daily_bars
    result: dict[str, Any] = {
        "source": QFQ_SOURCE,
        "writer": QFQ_WRITER,
        "scopes": scopes,
        "by_scope": {},
    }
    for kind in scopes:
        owner_id = _acquire_writer_lease(
            db=db,
            scope=kind,
            now_provider=now_provider,
            lease_seconds=writer_lease_seconds,
        )

        lease_heartbeat = _WriterLeaseHeartbeat(
            db=db,
            scope=kind,
            owner_id=owner_id,
            lease_seconds=writer_lease_seconds,
            now_provider=now_provider,
            heartbeat_seconds=writer_heartbeat_seconds,
        )
        lease_heartbeat.start()

        try:
            marker = get_qfq_marker(scope=kind, db=db)
            if marker is not None:
                marker = validate_qfq_marker(marker, scope=kind)
                inactive_slot = _inactive_slot_name(marker)
                if marker["slots"][inactive_slot].get("status") == "building":
                    _recover_interrupted_build_locked(scope=kind, db=db)
            if marker is None:
                scope_result = _bootstrap_scope(
                    scope=kind,
                    target_date=target,
                    db=db,
                    codes=codes,
                    loader=loader,
                    now_provider=now_provider,
                    progress_callback=lease_heartbeat.pulse,
                    publish_callback=lease_heartbeat.run_fenced_publish,
                )
            else:
                scope_result = _update_scope(
                    scope=kind,
                    target_date=target,
                    db=db,
                    codes=codes,
                    loader=loader,
                    tail_days=tail_days,
                    min_grace_seconds=min_grace_seconds,
                    force_full_rebuild=force_full_rebuild,
                    now_provider=now_provider,
                    progress_callback=lease_heartbeat.pulse,
                    publish_callback=lease_heartbeat.run_fenced_publish,
                )
            lease_heartbeat.raise_if_failed()
            result["by_scope"][kind] = scope_result
        finally:
            lease_heartbeat.stop()
            _release_writer_lease(db=db, scope=kind, owner_id=owner_id)
    result["ready"] = True
    return result


def sync_stock_adj_all(**kwargs: Any) -> dict[str, Any]:
    return sync_qfq_factors(scope="stock", **kwargs)


def sync_etf_adj_all(**kwargs: Any) -> dict[str, Any]:
    return sync_qfq_factors(scope="etf", **kwargs)


bootstrap_qfq = sync_qfq_factors
incremental_qfq = sync_qfq_factors

__all__ = [
    "QFQ_DATA_NOT_READY",
    "QFQSyncError",
    "QFQ_SOURCE",
    "QFQ_WRITER",
    "XtDataQfqClient",
    "audit_factor_snapshot",
    "audit_qfq_slot",
    "bootstrap_qfq",
    "compute_preclose_adj",
    "compute_qfq_factors",
    "compute_xtdata_preclose_adj",
    "get_qfq_marker",
    "incremental_qfq",
    "is_trading_etf",
    "load_factor_universe",
    "normalize_code",
    "normalize_xtdata_bars",
    "resolve_active_slot",
    "recover_interrupted_build",
    "rollback_active_slot",
    "sync_etf_adj_all",
    "sync_qfq_factors",
    "sync_stock_adj_all",
    "to_xt_code",
]
