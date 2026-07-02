from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from freshquant.db import DBfreshquant

COL_TRADE_CALENDAR_CACHE = "trade_calendar_cache"
DEFAULT_MARKET = "cn_a"
DEFAULT_SOURCE = "sina"
SCHEMA_VERSION = 1
MIN_RETAIN_RATIO = 0.8
SNAPSHOT_PATH_ENV = "FQ_TRADE_CALENDAR_SNAPSHOT_PATH"
SNAPSHOT_STATE_DIR_ENV = "FQ_TRADE_CALENDAR_STATE_DIR"
FRAME_ATTR_STATUS = "freshquant_trade_calendar_status"
FRAME_ATTR_ERROR_TYPE = "freshquant_trade_calendar_error_type"
FRAME_ATTR_ERROR_MESSAGE = "freshquant_trade_calendar_error_message"
STATUS_LIVE = "live"
STATUS_MONGO_CACHE = "mongo_cache"
STATUS_FILE_SNAPSHOT = "file_snapshot"

logger = logging.getLogger(__name__)


class TradeCalendarUnavailable(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _today(now_provider=None) -> date:
    now = now_provider() if callable(now_provider) else datetime.now()
    if isinstance(now, datetime):
        return now.date()
    return now


def _cache_id(market: str, source: str) -> str:
    return f"{market}:{source}"


def _get_collection(collection=None):
    if collection is not None:
        return collection
    return DBfreshquant[COL_TRADE_CALENDAR_CACHE]


def ensure_trade_calendar_cache_indexes(collection=None) -> None:
    target_collection = _get_collection(collection)
    if hasattr(target_collection, "create_index"):
        target_collection.create_index(
            [("market", 1), ("source", 1)],
            unique=True,
            name="uniq_market_source",
        )


def _normalize_trade_dates(frame: pd.DataFrame) -> list[str]:
    if "trade_date" not in frame.columns:
        raise ValueError("trade calendar dataframe missing trade_date column")
    values = pd.to_datetime(frame["trade_date"], errors="coerce")
    if values.isna().any():
        raise ValueError("trade calendar contains unparseable trade_date values")
    dates = sorted({value.date().isoformat() for value in values})
    if not dates:
        raise ValueError("trade calendar is empty")
    return dates


def _dates_to_frame(trade_dates: list[str]) -> pd.DataFrame:
    values = pd.to_datetime(list(trade_dates)).date
    return pd.DataFrame({"trade_date": list(values)})


def _with_frame_attrs(
    frame: pd.DataFrame,
    *,
    status: str,
    error: Exception | None = None,
) -> pd.DataFrame:
    frame.attrs[FRAME_ATTR_STATUS] = status
    if error is not None:
        frame.attrs[FRAME_ATTR_ERROR_TYPE] = type(error).__name__
        frame.attrs[FRAME_ATTR_ERROR_MESSAGE] = str(error)
    return frame


def _checksum(trade_dates: list[str]) -> str:
    payload = "\n".join(trade_dates).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _load_cache_doc(
    *,
    market: str = DEFAULT_MARKET,
    source: str = DEFAULT_SOURCE,
    collection=None,
) -> dict[str, Any] | None:
    target_collection = _get_collection(collection)
    if not hasattr(target_collection, "find_one"):
        return None
    return target_collection.find_one({"market": market, "source": source})


def _doc_trade_dates(doc: dict[str, Any] | None) -> list[str]:
    if not doc:
        return []
    trade_dates = doc.get("trade_dates")
    if not isinstance(trade_dates, list):
        return []
    return sorted({str(value).strip() for value in trade_dates if str(value).strip()})


def _doc_covers_today(doc: dict[str, Any] | None, *, now_provider=None) -> bool:
    trade_dates = _doc_trade_dates(doc)
    if not trade_dates:
        return False
    return trade_dates[-1] >= _today(now_provider).isoformat()


def _validate_update_against_existing(
    trade_dates: list[str],
    existing_doc: dict[str, Any] | None,
) -> None:
    existing_dates = _doc_trade_dates(existing_doc)
    if not existing_dates:
        return
    min_allowed = int(len(existing_dates) * MIN_RETAIN_RATIO)
    if len(trade_dates) < min_allowed:
        raise ValueError(
            "trade calendar update rejected because it shrank from "
            f"{len(existing_dates)} to {len(trade_dates)} dates"
        )


def _build_cache_doc(
    trade_dates: list[str],
    *,
    market: str,
    source: str,
    now_provider=None,
) -> dict[str, Any]:
    now = now_provider() if callable(now_provider) else _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return {
        "_id": _cache_id(market, source),
        "market": market,
        "source": source,
        "schema_version": SCHEMA_VERSION,
        "trade_dates": trade_dates,
        "min_trade_date": trade_dates[0],
        "max_trade_date": trade_dates[-1],
        "date_count": len(trade_dates),
        "checksum": _checksum(trade_dates),
        "last_success_at": now,
        "last_error_at": None,
        "last_error_type": "",
        "last_error_message": "",
    }


def _json_safe_doc(doc: dict[str, Any]) -> dict[str, Any]:
    safe_doc = dict(doc)
    for key, value in list(safe_doc.items()):
        if isinstance(value, datetime):
            safe_doc[key] = value.isoformat()
        elif isinstance(value, date):
            safe_doc[key] = value.isoformat()
    safe_doc["snapshot_written_at"] = _utc_now().isoformat()
    return safe_doc


def _snapshot_filename(market: str, source: str) -> str:
    return f"{market}_{source}.json"


def resolve_trade_calendar_snapshot_path(
    *,
    market: str = DEFAULT_MARKET,
    source: str = DEFAULT_SOURCE,
    snapshot_path: str | os.PathLike[str] | None = None,
) -> Path | None:
    explicit_path = str(
        snapshot_path or os.environ.get(SNAPSHOT_PATH_ENV) or ""
    ).strip()
    if explicit_path:
        return Path(explicit_path)

    state_dir = str(os.environ.get(SNAPSHOT_STATE_DIR_ENV) or "").strip()
    if state_dir:
        return Path(state_dir) / _snapshot_filename(market, source)

    dagster_home = str(os.environ.get("DAGSTER_HOME") or "").strip()
    if dagster_home:
        return (
            Path(dagster_home).parent
            / "state"
            / "trade-calendar"
            / _snapshot_filename(market, source)
        )

    return None


def write_trade_calendar_snapshot(
    doc: dict[str, Any],
    *,
    market: str = DEFAULT_MARKET,
    source: str = DEFAULT_SOURCE,
    snapshot_path: str | os.PathLike[str] | None = None,
) -> Path | None:
    target_path = resolve_trade_calendar_snapshot_path(
        market=market, source=source, snapshot_path=snapshot_path
    )
    if target_path is None:
        return None

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(f".{target_path.name}.tmp")
    temp_path.write_text(
        json.dumps(_json_safe_doc(doc), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.replace(temp_path, target_path)
    return target_path


def read_trade_calendar_snapshot(
    *,
    market: str = DEFAULT_MARKET,
    source: str = DEFAULT_SOURCE,
    require_covering_today: bool = True,
    now_provider=None,
    snapshot_path: str | os.PathLike[str] | None = None,
) -> pd.DataFrame | None:
    target_path = resolve_trade_calendar_snapshot_path(
        market=market, source=source, snapshot_path=snapshot_path
    )
    if target_path is None or not target_path.exists():
        return None
    payload = json.loads(target_path.read_text(encoding="utf-8"))
    if str(payload.get("market") or "") != market:
        return None
    if str(payload.get("source") or "") != source:
        return None
    if require_covering_today and not _doc_covers_today(
        payload, now_provider=now_provider
    ):
        return None
    trade_dates = _doc_trade_dates(payload)
    if not trade_dates:
        return None
    return _with_frame_attrs(_dates_to_frame(trade_dates), status=STATUS_FILE_SNAPSHOT)


def _record_source_error(
    exc: Exception,
    *,
    market: str,
    source: str,
    collection=None,
    increment_fallback_hits: bool = False,
    now_provider=None,
) -> None:
    target_collection = _get_collection(collection)
    if not hasattr(target_collection, "update_one"):
        return
    now = now_provider() if callable(now_provider) else _utc_now()
    update: dict[str, Any] = {
        "$set": {
            "market": market,
            "source": source,
            "last_error_at": now,
            "last_error_type": type(exc).__name__,
            "last_error_message": str(exc),
        }
    }
    if increment_fallback_hits:
        update["$inc"] = {"fallback_hits": 1}
    target_collection.update_one(
        {"market": market, "source": source},
        update,
        upsert=False,
    )


def _safe_record_source_error(exc: Exception, **kwargs) -> None:
    try:
        _record_source_error(exc, **kwargs)
    except Exception:
        logger.warning("failed to record trade calendar source error", exc_info=True)


def read_trade_calendar_cache(
    *,
    market: str = DEFAULT_MARKET,
    source: str = DEFAULT_SOURCE,
    collection=None,
    require_covering_today: bool = True,
    now_provider=None,
) -> pd.DataFrame | None:
    doc = _load_cache_doc(market=market, source=source, collection=collection)
    if require_covering_today and not _doc_covers_today(doc, now_provider=now_provider):
        return None
    trade_dates = _doc_trade_dates(doc)
    if not trade_dates:
        return None
    return _with_frame_attrs(_dates_to_frame(trade_dates), status=STATUS_MONGO_CACHE)


def refresh_trade_calendar_cache(
    fetcher: Callable[[], pd.DataFrame],
    *,
    market: str = DEFAULT_MARKET,
    source: str = DEFAULT_SOURCE,
    collection=None,
    now_provider=None,
    snapshot_path: str | os.PathLike[str] | None = None,
) -> pd.DataFrame:
    target_collection = _get_collection(collection)
    trade_dates = _normalize_trade_dates(fetcher())
    existing_doc = None
    try:
        ensure_trade_calendar_cache_indexes(target_collection)
        existing_doc = _load_cache_doc(
            market=market, source=source, collection=target_collection
        )
    except Exception:
        logger.warning("failed to inspect trade calendar mongo cache", exc_info=True)
    _validate_update_against_existing(trade_dates, existing_doc)
    cache_doc = _build_cache_doc(
        trade_dates,
        market=market,
        source=source,
        now_provider=now_provider,
    )
    try:
        target_collection.update_one(
            {"market": market, "source": source},
            {"$set": cache_doc, "$setOnInsert": {"fallback_hits": 0}},
            upsert=True,
        )
    except Exception:
        logger.warning("failed to persist trade calendar mongo cache", exc_info=True)
    try:
        write_trade_calendar_snapshot(
            cache_doc,
            market=market,
            source=source,
            snapshot_path=snapshot_path,
        )
    except Exception:
        logger.warning("failed to write trade calendar snapshot", exc_info=True)
    return _with_frame_attrs(_dates_to_frame(trade_dates), status=STATUS_LIVE)


def fetch_trade_dates_with_persistent_cache(
    fetcher: Callable[[], pd.DataFrame],
    *,
    market: str = DEFAULT_MARKET,
    source: str = DEFAULT_SOURCE,
    collection=None,
    now_provider=None,
    prefer_cache: bool = True,
    snapshot_path: str | os.PathLike[str] | None = None,
) -> pd.DataFrame:
    target_collection = _get_collection(collection)
    if prefer_cache:
        try:
            cached = read_trade_calendar_cache(
                market=market,
                source=source,
                collection=target_collection,
                require_covering_today=True,
                now_provider=now_provider,
            )
        except Exception:
            logger.warning("failed to read trade calendar mongo cache", exc_info=True)
            cached = None
        if cached is not None:
            return cached
        try:
            snapshot = read_trade_calendar_snapshot(
                market=market,
                source=source,
                require_covering_today=True,
                now_provider=now_provider,
                snapshot_path=snapshot_path,
            )
        except Exception:
            logger.warning("failed to read trade calendar snapshot", exc_info=True)
            snapshot = None
        if snapshot is not None:
            return snapshot

    try:
        return refresh_trade_calendar_cache(
            fetcher,
            market=market,
            source=source,
            collection=target_collection,
            now_provider=now_provider,
            snapshot_path=snapshot_path,
        )
    except Exception as exc:
        try:
            cached = read_trade_calendar_cache(
                market=market,
                source=source,
                collection=target_collection,
                require_covering_today=True,
                now_provider=now_provider,
            )
        except Exception:
            logger.warning("failed to read trade calendar mongo cache", exc_info=True)
            cached = None
        if cached is not None:
            _safe_record_source_error(
                exc,
                market=market,
                source=source,
                collection=target_collection,
                increment_fallback_hits=True,
                now_provider=now_provider,
            )
            _with_frame_attrs(cached, status=STATUS_MONGO_CACHE, error=exc)
            logger.warning("using cached trade calendar after source failure: %s", exc)
            return cached
        try:
            snapshot = read_trade_calendar_snapshot(
                market=market,
                source=source,
                require_covering_today=True,
                now_provider=now_provider,
                snapshot_path=snapshot_path,
            )
        except Exception:
            logger.warning("failed to read trade calendar snapshot", exc_info=True)
            snapshot = None
        if snapshot is not None:
            _safe_record_source_error(
                exc,
                market=market,
                source=source,
                collection=target_collection,
                increment_fallback_hits=True,
                now_provider=now_provider,
            )
            _with_frame_attrs(snapshot, status=STATUS_FILE_SNAPSHOT, error=exc)
            logger.warning(
                "using trade calendar file snapshot after source failure: %s", exc
            )
            return snapshot

        _safe_record_source_error(
            exc,
            market=market,
            source=source,
            collection=target_collection,
            now_provider=now_provider,
        )
        raise TradeCalendarUnavailable(
            f"trade calendar unavailable for {market}:{source}: {exc}"
        ) from exc
