"""Canonical XTData ``preClose`` based QFQ factor pipeline.

The public entry points are intentionally dependency-injectable.  Production
uses ``xtquant.xtdata`` and Mongo; unit tests can provide a bar loader and an
in-memory database without changing the factor contract.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from freshquant.data.qfq_contract import (
    QFQ_DATA_NOT_READY,
    require_qfq_ready_marker,
    validate_factor_documents,
)
from freshquant.db import DBQuantAxis
from freshquant.instrument.general import is_trading_etf_code
from freshquant.util.code import normalize_to_base_code

QFQ_SOURCE = "xtdata_preclose"
QFQ_WRITER = "freshquant.market_data.xtdata.qfq"
FACTOR_COLLECTIONS = {"stock": "stock_adj", "etf": "etf_adj"}
# BFQ is the coverage authority for each factor universe.  ``index_day`` is
# intentionally used for ETF history because QUANTAXIS stores exchange-traded
# funds in that collection alongside real indexes.
BFQ_COLLECTIONS = {"stock": "stock_day", "etf": "index_day"}
READY_COLLECTION = "qfq_ready"
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
    parsed = _parse_timestamp(value)
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


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
        if base.startswith(("5", "6")):
            suffix = "SH"
        elif base.startswith(("8", "4")):
            suffix = "BJ"
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
    sample = next(
        (value for value in fields.values() if isinstance(value, pd.DataFrame)), None
    )
    if sample is not None and not sample.empty:
        key = _row_key(sample, code)
        if key is not None:
            columns = list(sample.columns)
            rows: list[dict[str, Any]] = []
            for column in columns:
                row: dict[str, Any] = {"time": column}
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
    frame["date"] = [
        (
            _parse_timestamp(value).strftime("%Y-%m-%d")
            if not pd.isna(_parse_timestamp(value))
            else ""
        )
        for value in source_dates
    ]
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
    if frame[["close", "preClose"]].isna().any().any():
        raise QFQSyncError(f"invalid close/preClose values for code={code}")
    if (frame[["close", "preClose"]] <= 0).any().any():
        raise QFQSyncError(f"non-positive close/preClose values for code={code}")
    return frame


def compute_preclose_adj(bars: Any, *, code: str | None = None) -> pd.DataFrame:
    """Compute canonical QFQ factors from an ascending actual-date bar axis."""

    day = normalize_xtdata_bars(bars, code=code)
    factors = [1.0] * len(day)
    for index in range(len(day) - 2, -1, -1):
        next_preclose = float(day.iloc[index + 1]["preClose"])
        close = float(day.iloc[index]["close"])
        ratio = next_preclose / close
        if not math.isfinite(ratio) or ratio <= 0:
            raise QFQSyncError(f"invalid preClose/close ratio for code={code}")
        factors[index] = factors[index + 1] * ratio
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


def load_factor_universe(
    *,
    kind: str,
    db=DBQuantAxis,
    codes: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Load the full factor universe without monitor-pool/max-symbol limits."""

    if kind not in FACTOR_COLLECTIONS:
        raise ValueError(f"unsupported factor kind: {kind}")
    collection_name = "stock_list" if kind == "stock" else "etf_list"
    requested = {
        normalize_code(value) for value in (codes or ()) if normalize_code(value)
    }
    query = {} if codes is None else {"code": {"$in": sorted(requested)}}
    documents = list(db[collection_name].find(query, {"_id": 0}))
    included: list[str] = []
    excluded: list[dict[str, Any]] = []
    found_codes = {normalize_code(document.get("code")) for document in documents}
    if codes is not None:
        excluded.extend(
            {"code": code, "reason": f"not_in_{collection_name}"}
            for code in sorted(requested - found_codes)
        )
    for document in documents:
        code = normalize_code(document.get("code"))
        if not code:
            continue
        if kind == "etf" and not is_trading_etf(document):
            excluded.append({"code": code, "reason": "non_trading_open_fund"})
            continue
        if kind == "stock" and is_trading_etf_code(code):
            excluded.append({"code": code, "reason": "etf_like_code"})
            continue
        included.append(code)
    return {
        "kind": kind,
        "codes": sorted(set(included)),
        "excluded": excluded,
        "monitor_pool_independent": True,
    }


def load_bfq_dates(*, kind: str, code: str, db=DBQuantAxis) -> list[str]:
    """Return the actual BFQ trading-date axis for one included instrument."""

    if kind not in BFQ_COLLECTIONS:
        raise ValueError(f"unsupported BFQ kind: {kind}")
    code6 = normalize_code(code)
    collection = db[BFQ_COLLECTIONS[kind]]
    query = {"code": code6}
    projection = {"_id": 0, "date": 1}
    try:
        cursor = collection.find(query, projection)
    except TypeError:
        cursor = collection.find(query)
    try:
        cursor = cursor.sort("date", 1)
    except AttributeError:
        pass
    dates: list[str] = []
    invalid: list[Any] = []
    for row in cursor:
        value = row.get("date") if isinstance(row, Mapping) else None
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
    return sorted(set(dates))


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
    missing_dates: list[tuple[str, str]] = []
    extra_dates: list[tuple[str, str]] = []
    for code in sorted({normalize_code(c) for c in (included_codes or by_code)}):
        audit = validate_factor_documents(
            by_code.get(code, []),
            expected_dates=expected_map.get(code, ()),
            code=code,
        )
        invalid += int(audit["invalid"])
        duplicates += int(audit["duplicates"])
        missing_dates.extend((code, date) for date in audit["missing_dates"])
        if require_exact_dates and expected_map.get(code):
            actual_dates = {
                key
                for key in (_date_key(row.get("date")) for row in by_code.get(code, []))
                if key
            }
            expected_dates = {
                key for key in (_date_key(value) for value in expected_map[code]) if key
            }
            extra_dates.extend(
                (code, date) for date in sorted(actual_dates - expected_dates)
            )
        if not by_code.get(code):
            missing_codes.append(code)
    return {
        "codes": len(set(by_code) | set(expected_map)),
        "rows": len(rows),
        "missing": len(missing_codes) + len(missing_dates),
        "missing_codes": missing_codes,
        "missing_dates": missing_dates,
        "extra": len(extra_dates),
        "extra_dates": extra_dates,
        "invalid": invalid,
        "duplicates": duplicates,
        "ok": (
            not missing_codes
            and not missing_dates
            and not extra_dates
            and invalid == 0
            and duplicates == 0
        ),
    }


def _ensure_factor_indexes(collection) -> None:
    try:
        collection.create_index(
            [("code", 1), ("date", 1)], unique=True, name="code_date_unique"
        )
        collection.create_index([("date", 1)], name="date_idx")
    except Exception:
        # Lightweight test doubles and legacy Mongo versions may not support
        # all index keyword arguments; data validation remains authoritative.
        return


def _write_ready_marker(db, marker: Mapping[str, Any]) -> None:
    """Write the publication state without swallowing infrastructure errors."""

    db[READY_COLLECTION].update_one(
        {"collection": marker["collection"]}, {"$set": dict(marker)}, upsert=True
    )


def _build_ready_marker(
    *,
    collection_name: str,
    status: str,
    included_codes: Iterable[str],
    rows: int,
    excluded: Iterable[Mapping[str, Any]],
    run_id: str | None,
) -> dict[str, Any]:
    return {
        "collection": collection_name,
        "source": QFQ_SOURCE,
        "writer": QFQ_WRITER,
        "status": status,
        "run_id": run_id or uuid.uuid4().hex,
        "codes": len(set(included_codes)),
        "rows": int(rows),
        "missing": 0,
        "extra": 0,
        "invalid": 0,
        "duplicates": 0,
        "excluded": list(excluded),
        "updated_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    }


def publish_factor_snapshot(
    *,
    db,
    collection_name: str,
    documents: Iterable[Mapping[str, Any]],
    expected_dates_by_code: Mapping[str, Iterable[Any]],
    included_codes: Iterable[str],
    excluded: Iterable[Mapping[str, Any]] = (),
    run_id: str | None = None,
    require_exact_dates: bool = False,
) -> dict[str, Any]:
    """Atomically publish a validated full snapshot and then mark it ready."""

    rows = [
        {
            "code": normalize_code(row.get("code")),
            "date": str(row.get("date"))[:10],
            "adj": float(row.get("adj")),
        }
        for row in (documents or ())
    ]
    audit = audit_factor_snapshot(
        rows,
        expected_dates_by_code=expected_dates_by_code,
        included_codes=included_codes,
        require_exact_dates=require_exact_dates,
    )
    if not audit["ok"]:
        raise QFQSyncError("factor snapshot audit failed", stats=audit)

    stage_name = f"{collection_name}__xtdata_staging__{uuid.uuid4().hex}"
    if hasattr(db, "drop_collection"):
        db.drop_collection(stage_name)
    stage = db[stage_name]
    _ensure_factor_indexes(stage)
    if rows:
        stage.insert_many(rows, ordered=False)
    # Mark the old snapshot as unavailable before changing the collection.
    # Consumers that honor qfq_ready therefore fail closed during publication.
    marker = _build_ready_marker(
        collection_name=collection_name,
        status="publishing",
        included_codes=included_codes,
        rows=len(rows),
        excluded=excluded,
        run_id=run_id,
    )
    try:
        _write_ready_marker(db, marker)
    except Exception as exc:
        if hasattr(db, "drop_collection"):
            db.drop_collection(stage_name)
        raise QFQSyncError(
            "factor snapshot staging marker write failed",
            stats={**marker, "marker_error": str(exc)},
        ) from exc

    target = db[collection_name]
    if hasattr(stage, "rename"):
        stage.rename(collection_name, dropTarget=True)
    else:  # pragma: no cover - defensive fallback for tiny test doubles
        target.delete_many({})
        if rows:
            target.insert_many(rows, ordered=False)
        if hasattr(db, "drop_collection"):
            db.drop_collection(stage_name)
    _ensure_factor_indexes(db[collection_name])

    marker = {**marker, "status": "ready"}
    try:
        _write_ready_marker(db, marker)
    except Exception as exc:
        # The factor collection has already been atomically renamed, but it is
        # deliberately not marked ready when the publication boundary cannot
        # be recorded.  Callers must retry and the consumer remains fail-closed.
        raise QFQSyncError(
            "factor snapshot published but ready marker write failed",
            stats={**marker, "marker_error": str(exc)},
        ) from exc
    return {**marker, "audit": audit}


class _FactorSnapshotStage:
    """Stream one factor snapshot into a Mongo staging collection."""

    def __init__(self, *, db, collection_name: str, run_id: str | None = None):
        self.db = db
        self.collection_name = collection_name
        self.run_id = run_id or uuid.uuid4().hex
        self.stage_name = f"{collection_name}__xtdata_staging__{uuid.uuid4().hex}"
        if hasattr(db, "drop_collection"):
            db.drop_collection(self.stage_name)
        self.stage = db[self.stage_name]
        _ensure_factor_indexes(self.stage)
        self.codes: list[str] = []
        self.rows = 0

    def add(
        self,
        *,
        code: str,
        documents: Iterable[Mapping[str, Any]],
        expected_dates: Iterable[Any],
    ) -> dict[str, Any]:
        code6 = normalize_code(code)
        rows = [
            {
                "code": code6,
                "date": str(row.get("date"))[:10],
                "adj": float(row.get("adj")),
            }
            for row in documents
        ]
        audit = audit_factor_snapshot(
            rows,
            expected_dates_by_code={code6: list(expected_dates)},
            included_codes=[code6],
            require_exact_dates=True,
        )
        if not audit["ok"]:
            raise QFQSyncError(
                f"factor date coverage failed for code={code6}", stats=audit
            )
        if rows:
            self.stage.insert_many(rows, ordered=False)
        self.codes.append(code6)
        self.rows += len(rows)
        return audit

    def abort(self) -> None:
        if hasattr(self.db, "drop_collection"):
            self.db.drop_collection(self.stage_name)

    def publish(self, *, excluded: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        audit = {
            "codes": len(set(self.codes)),
            "rows": self.rows,
            "missing": 0,
            "missing_codes": [],
            "missing_dates": [],
            "extra": 0,
            "extra_dates": [],
            "invalid": 0,
            "duplicates": 0,
            "ok": True,
        }
        marker = _build_ready_marker(
            collection_name=self.collection_name,
            status="publishing",
            included_codes=self.codes,
            rows=self.rows,
            excluded=excluded,
            run_id=self.run_id,
        )
        try:
            _write_ready_marker(self.db, marker)
        except Exception as exc:
            self.abort()
            raise QFQSyncError(
                "factor snapshot staging marker write failed",
                stats={**marker, "marker_error": str(exc)},
            ) from exc

        try:
            if hasattr(self.stage, "rename"):
                self.stage.rename(self.collection_name, dropTarget=True)
            else:  # pragma: no cover - defensive fallback for tiny test doubles
                target = self.db[self.collection_name]
                target.delete_many({})
                for code in self.codes:
                    cursor = self.stage.find({"code": code}, {"_id": 0})
                    rows = list(cursor)
                    if rows:
                        target.insert_many(rows, ordered=False)
                self.abort()
            _ensure_factor_indexes(self.db[self.collection_name])
        except Exception as exc:
            self.abort()
            raise QFQSyncError(
                "factor snapshot atomic rename failed",
                stats={**marker, "publish_error": str(exc)},
            ) from exc

        marker = {**marker, "status": "ready"}
        try:
            _write_ready_marker(self.db, marker)
        except Exception as exc:
            raise QFQSyncError(
                "factor snapshot published but ready marker write failed",
                stats={**marker, "status": "publishing", "marker_error": str(exc)},
            ) from exc
        return {**marker, "audit": audit}


class XtDataQfqClient:
    def __init__(self, xtdata_module=None, *, port: int | None = None):
        if xtdata_module is None:
            from xtquant import xtdata as xtdata_module  # type: ignore

        self.xtdata = xtdata_module
        self.port = int(port or 58610)
        self.connected = False

    def load_daily_bars(
        self,
        code: str,
        *,
        market: str | None = None,
        start_time: str = "",
        end_time: str = "",
    ) -> pd.DataFrame:
        if not self.connected and hasattr(self.xtdata, "connect"):
            self.xtdata.connect(port=self.port)
            self.connected = True
        xt_code = to_xt_code(code, market=market)
        if hasattr(self.xtdata, "download_history_data"):
            self.xtdata.download_history_data(xt_code, "1d", start_time, end_time)
        payload = self.xtdata.get_market_data(
            field_list=["time", "close", "preClose"],
            stock_list=[xt_code],
            period="1d",
            start_time=start_time,
            end_time=end_time,
            dividend_type="none",
            fill_data=False,
        )
        return normalize_xtdata_bars(payload, code=xt_code)


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


def _factor_dates_are_exact(
    rows: Iterable[Mapping[str, Any]], expected_dates: Iterable[str], code: str
) -> bool:
    rows = list(rows)
    expected = list(expected_dates)
    audit = validate_factor_documents(rows, expected_dates=expected, code=code)
    actual = {_date_key(row.get("date")) for row in rows}
    actual.discard(None)
    return audit["ok"] and actual == set(expected)


def _build_incremental_rows(
    *,
    code: str,
    bfq_dates: list[str],
    existing_rows: list[dict[str, Any]],
    loader: Callable[..., Any],
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """Extend one canonical factor series from its previous terminal date.

    ``None`` means the old snapshot cannot be trusted as a complete prefix and
    the caller should perform a full rebuild for this code.
    """

    code6 = normalize_code(code)
    expected_all = list(sorted(set(bfq_dates)))
    if not existing_rows:
        return None, {"mode": "full", "reason": "no_existing_factors"}
    existing_dates = {_date_key(row.get("date")) for row in existing_rows}
    existing_dates.discard(None)
    if not existing_dates or not existing_dates.issubset(set(expected_all)):
        return None, {"mode": "full", "reason": "existing_date_axis_mismatch"}
    last_existing = max(existing_dates)
    prefix_dates = [value for value in expected_all if value <= last_existing]
    if not _factor_dates_are_exact(existing_rows, prefix_dates, code6):
        return None, {"mode": "full", "reason": "existing_coverage_audit_failed"}

    tail_dates = [value for value in expected_all if value >= last_existing]
    load_start = _xt_date_arg(last_existing)
    load_end = _xt_date_arg(expected_all[-1])
    bars = _call_loader(loader, code6, load_start, load_end)
    tail_factors = compute_preclose_adj(bars, code=code6)
    tail_rows = tail_factors.to_dict(orient="records")
    if not _factor_dates_are_exact(tail_rows, tail_dates, code6):
        raise QFQSyncError(
            f"incremental BFQ/XTData date coverage failed for code={code6}",
            stats={
                "code": code6,
                "expected_dates": len(tail_dates),
                "actual_dates": len(
                    {
                        value
                        for value in (_date_key(row.get("date")) for row in tail_rows)
                        if value
                    }
                ),
            },
        )
    tail_by_date = {_date_key(row["date"]): float(row["adj"]) for row in tail_rows}
    scale = tail_by_date[last_existing]
    output: list[dict[str, Any]] = []
    for row in existing_rows:
        date_key = _date_key(row.get("date"))
        if date_key is None:
            continue
        output.append(
            {
                "code": code6,
                "date": date_key,
                "adj": float(row["adj"]) * scale,
            }
        )
    output.extend(
        {
            "code": code6,
            "date": date_key,
            "adj": factor,
        }
        for date_key, factor in tail_by_date.items()
        if date_key > last_existing
    )
    if not _factor_dates_are_exact(output, expected_all, code6):
        raise QFQSyncError(
            f"incremental factor output coverage failed for code={code6}"
        )
    return output, {
        "mode": "incremental",
        "start_date": load_start,
        "end_date": load_end,
        "previous_last_date": last_existing,
        "new_dates": len([value for value in tail_dates if value > last_existing]),
    }


def sync_qfq_factors(
    *,
    scope: str,
    db=DBQuantAxis,
    codes: Iterable[str] | None = None,
    bars_loader: Callable[..., Any] | None = None,
    xtdata_client: XtDataQfqClient | None = None,
    start_time: str = "",
    end_time: str = "",
    run_id: str | None = None,
    incremental: bool = False,
) -> dict[str, Any]:
    """Bootstrap or incrementally publish Stock/ETF factors.

    The BFQ collection supplies both the download bounds and the expected date
    axis.  This keeps a successful XTData response from hiding a local day/min
    gap.  Incremental runs download only the terminal overlap and new dates,
    then still publish a complete idempotent snapshot through staging.
    """

    scopes = [item.strip().lower() for item in str(scope).split(",") if item.strip()]
    if not scopes or any(item not in FACTOR_COLLECTIONS for item in scopes):
        raise ValueError(f"unsupported QFQ scope: {scope}")
    client = xtdata_client or XtDataQfqClient()
    loader = bars_loader or client.load_daily_bars
    combined: dict[str, Any] = {
        "source": QFQ_SOURCE,
        "writer": QFQ_WRITER,
        "scopes": scopes,
        "by_scope": {},
    }
    for kind in scopes:
        universe = load_factor_universe(kind=kind, db=db, codes=codes)
        requested_codes = universe["codes"]
        included_codes: list[str] = []
        failed: list[dict[str, Any]] = []
        excluded = list(universe["excluded"])
        no_bfq_history: list[dict[str, Any]] = []
        mode_counts = {"incremental": 0, "full": 0}
        full_fallbacks: list[dict[str, Any]] = []
        incremental_source_ready = False
        if incremental:
            try:
                require_qfq_ready_marker(
                    db=db,
                    collection_name=FACTOR_COLLECTIONS[kind],
                )
                incremental_source_ready = True
            except Exception as exc:  # noqa: BLE001
                full_fallbacks.append(
                    {"code": "*", "reason": f"source_marker_not_ready: {exc}"}
                )
        stage = _FactorSnapshotStage(
            db=db,
            collection_name=FACTOR_COLLECTIONS[kind],
            run_id=run_id,
        )
        for code in requested_codes:
            try:
                bfq_dates = load_bfq_dates(kind=kind, code=code, db=db)
                if not bfq_dates:
                    no_bfq_history.append({"code": code, "reason": "no_bfq_history"})
                    continue
                rows: list[dict[str, Any]] | None = None
                mode = {"mode": "full", "reason": "bootstrap"}
                if incremental_source_ready:
                    existing_rows = _load_existing_factor_rows(
                        db=db,
                        collection_name=FACTOR_COLLECTIONS[kind],
                        code=code,
                    )
                    rows, mode = _build_incremental_rows(
                        code=code,
                        bfq_dates=bfq_dates,
                        existing_rows=existing_rows,
                        loader=loader,
                    )
                if rows is None:
                    load_start, load_end, expected_dates = _bfq_download_bounds(
                        bfq_dates,
                        start_time="" if incremental else start_time,
                        end_time="" if incremental else end_time,
                    )
                    bars = _call_loader(loader, code, load_start, load_end)
                    factors = compute_preclose_adj(bars, code=code)
                    rows = factors.to_dict(orient="records")
                    if incremental:
                        full_fallbacks.append(
                            {"code": code, "reason": str(mode.get("reason") or "full")}
                        )
                    mode = {"mode": "full"}
                else:
                    expected_dates = list(bfq_dates)
                stage.add(
                    code=code,
                    documents=rows,
                    expected_dates=expected_dates,
                )
                included_codes.append(code)
                mode_counts[str(mode["mode"])] += 1
            except Exception as exc:  # noqa: BLE001
                failed.append({"code": code, "error": str(exc)})
        excluded.extend(no_bfq_history)
        stats = {
            "kind": kind,
            "total": len(requested_codes),
            "included": len(included_codes),
            "ok": len(included_codes),
            "failed": len(failed),
            "failed_codes": failed,
            "no_bfq_history": no_bfq_history,
            "excluded": excluded,
            "incremental": bool(incremental),
            "incremental_source_ready": incremental_source_ready,
            "mode_counts": mode_counts,
            "full_fallbacks": full_fallbacks[:100],
        }
        if failed:
            stage.abort()
            combined["by_scope"][kind] = stats
            raise QFQSyncError(f"{kind} XTData factor download failed", stats=combined)
        if not included_codes:
            stage.abort()
            combined["by_scope"][kind] = stats
            raise QFQSyncError(f"{kind} has no BFQ history to publish", stats=combined)

        published = stage.publish(excluded=excluded)
        stats.update(
            {
                "published": True,
                "ready": published["status"],
                "rows": published["rows"],
                "audit": published["audit"],
            }
        )
        combined["by_scope"][kind] = stats
    combined["ready"] = True
    return combined


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
    "bootstrap_qfq",
    "compute_preclose_adj",
    "compute_qfq_factors",
    "compute_xtdata_preclose_adj",
    "incremental_qfq",
    "is_trading_etf",
    "load_factor_universe",
    "normalize_code",
    "normalize_xtdata_bars",
    "publish_factor_snapshot",
    "sync_etf_adj_all",
    "sync_qfq_factors",
    "sync_stock_adj_all",
    "to_xt_code",
]
