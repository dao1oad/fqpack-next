from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timezone
from typing import Any, Callable

import pandas as pd

from freshquant.db import DBfreshquant

COL_TRADE_CALENDAR_CACHE = "trade_calendar_cache"
DEFAULT_MARKET = "cn_a"
DEFAULT_SOURCE = "sina"
SCHEMA_VERSION = 1
MIN_RETAIN_RATIO = 0.8

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
    return _dates_to_frame(trade_dates)


def refresh_trade_calendar_cache(
    fetcher: Callable[[], pd.DataFrame],
    *,
    market: str = DEFAULT_MARKET,
    source: str = DEFAULT_SOURCE,
    collection=None,
    now_provider=None,
) -> pd.DataFrame:
    target_collection = _get_collection(collection)
    ensure_trade_calendar_cache_indexes(target_collection)
    existing_doc = _load_cache_doc(
        market=market, source=source, collection=target_collection
    )
    trade_dates = _normalize_trade_dates(fetcher())
    _validate_update_against_existing(trade_dates, existing_doc)
    cache_doc = _build_cache_doc(
        trade_dates,
        market=market,
        source=source,
        now_provider=now_provider,
    )
    target_collection.update_one(
        {"market": market, "source": source},
        {"$set": cache_doc, "$setOnInsert": {"fallback_hits": 0}},
        upsert=True,
    )
    return _dates_to_frame(trade_dates)


def fetch_trade_dates_with_persistent_cache(
    fetcher: Callable[[], pd.DataFrame],
    *,
    market: str = DEFAULT_MARKET,
    source: str = DEFAULT_SOURCE,
    collection=None,
    now_provider=None,
    prefer_cache: bool = True,
) -> pd.DataFrame:
    target_collection = _get_collection(collection)
    if prefer_cache:
        cached = read_trade_calendar_cache(
            market=market,
            source=source,
            collection=target_collection,
            require_covering_today=True,
            now_provider=now_provider,
        )
        if cached is not None:
            return cached

    try:
        return refresh_trade_calendar_cache(
            fetcher,
            market=market,
            source=source,
            collection=target_collection,
            now_provider=now_provider,
        )
    except Exception as exc:
        cached = read_trade_calendar_cache(
            market=market,
            source=source,
            collection=target_collection,
            require_covering_today=True,
            now_provider=now_provider,
        )
        if cached is not None:
            _record_source_error(
                exc,
                market=market,
                source=source,
                collection=target_collection,
                increment_fallback_hits=True,
                now_provider=now_provider,
            )
            logger.warning("using cached trade calendar after source failure: %s", exc)
            return cached

        _record_source_error(
            exc,
            market=market,
            source=source,
            collection=target_collection,
            now_provider=now_provider,
        )
        raise TradeCalendarUnavailable(
            f"trade calendar unavailable for {market}:{source}: {exc}"
        ) from exc
