from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from freshquant.data.gantt_source_jygs import (
    COL_JYGS_ACTION_FIELDS,
    COL_JYGS_YIDONG,
    normalize_board_key,
    normalize_jygs_action_field_row,
)
from freshquant.data.gantt_source_xgb import (
    COL_XGB_TOP_GAINER_HISTORY,
    normalize_xgb_history_row,
)
from freshquant.db import DBGantt
from freshquant.chanlun_structure_service import get_chanlun_structure

COL_PLATE_REASON_DAILY = "plate_reason_daily"
COL_GANTT_PLATE_DAILY = "gantt_plate_daily"
COL_GANTT_STOCK_DAILY = "gantt_stock_daily"
COL_STOCK_HOT_REASON_DAILY = "stock_hot_reason_daily"
COL_SHOUBAN30_PLATES = "shouban30_plates"
COL_SHOUBAN30_STOCKS = "shouban30_stocks"
SHOUBAN30_STOCK_WINDOWS = (30, 45, 60, 90)
SHOUBAN30_CHANLUN_PERIOD = "30m"
SHOUBAN30_CHANLUN_FILTER_VERSION = "30m_v1"
SHOUBAN30_EXCLUDED_PLATE_NAMES = frozenset({"其他", "公告", "ST股", "ST板块"})
CN_TZ = ZoneInfo("Asia/Shanghai")
LEGACY_SHOUBAN30_PLATES_INDEX = "provider_1_plate_key_1_as_of_date_1"
LEGACY_SHOUBAN30_STOCKS_INDEX = "provider_1_plate_key_1_code6_1_as_of_date_1"


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_code6(value: Any) -> str:
    text = _to_str(value)
    if not text:
        return ""
    match = re.search(r"(\d{6})", text)
    if not match:
        return text
    return match.group(1)


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _calc_start_date(end_date: str, days: int) -> str:
    if days <= 1:
        return end_date
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    return (end_dt - timedelta(days=days - 1)).strftime("%Y-%m-%d")


def _resolve_shouban30_stock_window_days(value: Any, default: int = 30) -> int:
    parsed = _to_int(value, default)
    if parsed in SHOUBAN30_STOCK_WINDOWS:
        return parsed
    return default


def _sorted_unique_texts(values: list[Any]) -> list[str]:
    return sorted({_to_str(item) for item in values if _to_str(item)})


def _get_collection(name: str):
    return DBGantt[name]


def _find_rows(collection_name: str, query: dict[str, Any]) -> list[dict[str, Any]]:
    collection = _get_collection(collection_name)
    return list(collection.find(query, {"_id": 0}))


def _delete_rows(collection_name: str, query: dict[str, Any]) -> None:
    _get_collection(collection_name).delete_many(query)


def _upsert_rows(
    collection_name: str,
    rows: list[dict[str, Any]],
    *,
    key_fields: tuple[str, ...],
) -> int:
    collection = _get_collection(collection_name)
    for row in rows:
        query = {field: row.get(field) for field in key_fields}
        collection.update_one(query, {"$set": row}, upsert=True)
    return len(rows)


def _is_missing_namespace_error(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    if code == 26:
        return True
    message = _to_str(exc).lower()
    return "namespacenotfound" in message or "ns not found" in message


def _drop_index_if_exists(collection, index_name: str) -> None:
    try:
        existing_names = {
            _to_str(item.get("name")) if isinstance(item, dict) else _to_str(item.name)
            for item in collection.list_indexes()
        }
    except Exception as exc:
        if _is_missing_namespace_error(exc):
            return
        raise
    if index_name in existing_names:
        collection.drop_index(index_name)


def ensure_readmodel_indexes() -> None:
    _get_collection(COL_PLATE_REASON_DAILY).create_index(
        [("provider", 1), ("plate_key", 1), ("trade_date", 1)],
        unique=True,
    )
    _get_collection(COL_GANTT_PLATE_DAILY).create_index(
        [("provider", 1), ("plate_key", 1), ("trade_date", 1)],
        unique=True,
    )
    _get_collection(COL_GANTT_STOCK_DAILY).create_index(
        [("provider", 1), ("plate_key", 1), ("code6", 1), ("trade_date", 1)],
        unique=True,
    )
    _get_collection(COL_STOCK_HOT_REASON_DAILY).create_index(
        [("provider", 1), ("trade_date", 1), ("plate_key", 1), ("code6", 1)],
        unique=True,
    )
    _get_collection(COL_STOCK_HOT_REASON_DAILY).create_index(
        [("code6", 1), ("trade_date", -1), ("time", -1)]
    )
    shouban30_plates = _get_collection(COL_SHOUBAN30_PLATES)
    _drop_index_if_exists(shouban30_plates, LEGACY_SHOUBAN30_PLATES_INDEX)
    shouban30_plates.create_index(
        [
            ("provider", 1),
            ("plate_key", 1),
            ("as_of_date", 1),
            ("stock_window_days", 1),
        ],
        unique=True,
    )
    shouban30_stocks = _get_collection(COL_SHOUBAN30_STOCKS)
    _drop_index_if_exists(shouban30_stocks, LEGACY_SHOUBAN30_STOCKS_INDEX)
    shouban30_stocks.create_index(
        [
            ("provider", 1),
            ("plate_key", 1),
            ("code6", 1),
            ("as_of_date", 1),
            ("stock_window_days", 1),
        ],
        unique=True,
    )


def _resolve_trade_window(
    rows: list[dict[str, Any]],
    *,
    days: int,
    end_date: str | None,
    field_name: str,
) -> tuple[str, str] | None:
    normalized_end_date = _to_str(end_date)
    if not rows:
        return None
    if not normalized_end_date:
        normalized_end_date = max(_to_str(item.get(field_name)) for item in rows)
    if not normalized_end_date:
        return None
    normalized_days = max(_to_int(days, 30), 1)
    start_date = _calc_start_date(normalized_end_date, normalized_days)
    return start_date, normalized_end_date


def _resolve_recent_trade_dates(
    rows: list[dict[str, Any]],
    *,
    days: int,
    end_date: str,
    field_name: str,
) -> list[str]:
    target_end_date = _to_str(end_date)
    if not target_end_date:
        return []
    all_dates = sorted(
        {
            _to_str(item.get(field_name))
            for item in rows
            if _to_str(item.get(field_name))
            and _to_str(item.get(field_name)) <= target_end_date
        }
    )
    if not all_dates:
        return []
    target_days = max(_to_int(days, 1), 1)
    return all_dates[-target_days:]


def _filter_rows_by_window(
    rows: list[dict[str, Any]],
    *,
    days: int,
    end_date: str | None,
    field_name: str,
) -> list[dict[str, Any]]:
    window = _resolve_trade_window(
        rows,
        days=days,
        end_date=end_date,
        field_name=field_name,
    )
    if not window:
        return []

    start_date, resolved_end_date = window
    return [
        item
        for item in rows
        if start_date <= _to_str(item.get(field_name)) <= resolved_end_date
    ]


def _build_plate_reason_lookup(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {
        (
            _to_str(item.get("provider")),
            _to_str(item.get("plate_key")),
            _to_str(item.get("trade_date")),
        ): item
        for item in (rows or [])
    }


def _normalize_hit_time(value: Any) -> str | None:
    text = _to_str(value)
    if not text:
        return None

    if re.fullmatch(r"\d{10,13}", text):
        raw = int(text)
        seconds = raw / 1000 if len(text) == 13 else raw
        try:
            return datetime.fromtimestamp(seconds, tz=CN_TZ).strftime("%H:%M")
        except (OverflowError, OSError, ValueError):
            pass

    match = re.fullmatch(r"(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?", text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    if re.fullmatch(r"\d{3,4}", text):
        digits = text.zfill(4)
        hour = int(digits[:2])
        minute = int(digits[2:])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    return text or None


def build_stock_hot_reason_rows(
    *,
    gantt_stock_rows: list[dict[str, Any]],
    plate_reason_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reason_map = _build_plate_reason_lookup(plate_reason_rows)
    rows: list[dict[str, Any]] = []

    for item in gantt_stock_rows or []:
        provider = _to_str(item.get("provider"))
        trade_date = _to_str(item.get("trade_date"))
        plate_key = _to_str(item.get("plate_key"))
        code6 = _to_str(item.get("code6"))
        reason_row = reason_map.get((provider, plate_key, trade_date))
        if not reason_row:
            raise ValueError(
                f"missing stock hot reason for provider={provider} plate_key={plate_key} trade_date={trade_date}"
            )
        rows.append(
            {
                "trade_date": trade_date,
                "provider": provider,
                "code6": code6,
                "name": _to_str(item.get("name")) or code6,
                "plate_key": plate_key,
                "plate_name": _to_str(item.get("plate_name"))
                or _to_str(reason_row.get("plate_name"))
                or plate_key,
                "plate_reason": _to_str(reason_row.get("reason_text")) or None,
                "stock_reason": _to_str(item.get("stock_reason")) or None,
                "time": _normalize_hit_time(item.get("time")),
                "reason_ref": reason_row.get("source_ref"),
            }
        )

    rows.sort(
        key=lambda item: (
            _to_str(item.get("provider")),
            _to_str(item.get("plate_name")),
            _to_str(item.get("stock_reason")),
        )
    )
    rows.sort(key=lambda item: _to_str(item.get("time")), reverse=True)
    rows.sort(key=lambda item: _to_str(item.get("trade_date")), reverse=True)
    return rows


def _query_gantt_plate_rows(
    *,
    provider: str,
    days: int = 30,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    provider_key = _to_str(provider)
    rows = _find_rows(COL_GANTT_PLATE_DAILY, {"provider": provider_key})
    return _filter_rows_by_window(
        rows,
        days=days,
        end_date=end_date,
        field_name="trade_date",
    )


def query_gantt_plate_matrix(
    *,
    provider: str,
    days: int = 30,
    end_date: str | None = None,
) -> dict[str, list[Any]]:
    filtered = _query_gantt_plate_rows(
        provider=provider,
        days=days,
        end_date=end_date,
    )
    if not filtered:
        return {"dates": [], "y_axis": [], "series": []}
    return build_gantt_plate_matrix(filtered)


def query_gantt_plate_reason_map(
    *,
    provider: str,
    days: int = 30,
    end_date: str | None = None,
) -> dict[str, dict[str, Any]]:
    filtered = _query_gantt_plate_rows(
        provider=provider,
        days=days,
        end_date=end_date,
    )
    return build_gantt_plate_reason_map(filtered)


def query_gantt_stock_matrix(
    *,
    provider: str,
    plate_key: str,
    days: int = 30,
    end_date: str | None = None,
) -> dict[str, list[Any]]:
    provider_key = _to_str(provider)
    target_plate_key = _to_str(plate_key)
    rows = _find_rows(
        COL_GANTT_STOCK_DAILY,
        {"provider": provider_key, "plate_key": target_plate_key},
    )
    window = _resolve_trade_window(
        rows,
        days=days,
        end_date=end_date,
        field_name="trade_date",
    )
    if not window:
        return {"dates": [], "y_axis": [], "series": []}

    start_date, resolved_end_date = window
    filtered = [
        item
        for item in rows
        if start_date <= _to_str(item.get("trade_date")) <= resolved_end_date
    ]
    return build_gantt_stock_matrix(filtered, plate_key=target_plate_key)


def query_shouban30_plate_rows(
    *,
    provider: str,
    as_of_date: str | None = None,
    stock_window_days: int = 30,
) -> list[dict[str, Any]]:
    provider_key = _to_str(provider)
    target_window = _resolve_shouban30_stock_window_days(stock_window_days)
    rows = _find_rows(
        COL_SHOUBAN30_PLATES,
        {"provider": provider_key, "stock_window_days": target_window},
    )
    return _ensure_shouban30_chanlun_snapshot_ready(
        select_shouban30_plate_rows(
        rows,
        provider=provider_key,
        as_of_date=as_of_date,
        stock_window_days=target_window,
        )
    )


def query_shouban30_stock_rows(
    *,
    provider: str,
    plate_key: str,
    as_of_date: str | None = None,
    stock_window_days: int = 30,
) -> list[dict[str, Any]]:
    provider_key = _to_str(provider)
    target_plate_key = _to_str(plate_key)
    target_window = _resolve_shouban30_stock_window_days(stock_window_days)
    rows = _find_rows(
        COL_SHOUBAN30_STOCKS,
        {
            "provider": provider_key,
            "plate_key": target_plate_key,
            "stock_window_days": target_window,
        },
    )
    return _ensure_shouban30_chanlun_snapshot_ready(
        select_shouban30_stock_rows(
        rows,
        provider=provider_key,
        plate_key=target_plate_key,
        as_of_date=as_of_date,
        stock_window_days=target_window,
        )
    )


def build_plate_reason_daily(
    *,
    xgb_history_rows: list[dict[str, Any]],
    jygs_action_rows: list[dict[str, Any]],
    trade_date: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for raw in xgb_history_rows or []:
        normalized = normalize_xgb_history_row(raw)
        rows.append(
            {
                "provider": normalized["provider"],
                "trade_date": normalized["trade_date"],
                "plate_key": normalized["plate_key"],
                "plate_name": normalized["plate_name"],
                "reason_text": normalized["reason_text"],
                "reason_source": normalized["reason_source"],
                "source_ref": normalized["source_ref"],
            }
        )

    date_str = _to_str(trade_date)
    for raw in jygs_action_rows or []:
        normalized = normalize_jygs_action_field_row(date_str, raw)
        rows.append(
            {
                "provider": normalized["provider"],
                "trade_date": normalized["trade_date"],
                "plate_key": normalized["plate_key"],
                "plate_name": normalized["plate_name"],
                "reason_text": normalized["reason_text"],
                "reason_source": normalized["reason_source"],
                "source_ref": normalized["source_ref"],
            }
        )

    return rows


def persist_plate_reason_daily_for_date(trade_date: str) -> int:
    date_str = _to_str(trade_date)
    if not date_str:
        raise ValueError("trade_date is required")

    ensure_readmodel_indexes()
    xgb_history_rows = _find_rows(COL_XGB_TOP_GAINER_HISTORY, {"trade_date": date_str})
    jygs_action_rows = _find_rows(COL_JYGS_ACTION_FIELDS, {"date": date_str})
    rows = build_plate_reason_daily(
        xgb_history_rows=xgb_history_rows,
        jygs_action_rows=jygs_action_rows,
        trade_date=date_str,
    )
    _delete_rows(COL_PLATE_REASON_DAILY, {"trade_date": date_str})
    return _upsert_rows(
        COL_PLATE_REASON_DAILY,
        rows,
        key_fields=("provider", "plate_key", "trade_date"),
    )


def _build_xgb_gantt_rows(
    trade_date: str, rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    plate_rows: list[dict[str, Any]] = []
    stock_rows: list[dict[str, Any]] = []

    for row in rows:
        normalized = normalize_xgb_history_row(
            {
                "trade_date": trade_date,
                "plate_id": row.get("plate_id"),
                "plate_name": row.get("plate_name"),
                "description": row.get("description") or "__skip_reason_check__",
                "rank": row.get("rank"),
                "hot_stocks": row.get("hot_stocks"),
            }
        )
        normalized_trade_date = normalized["trade_date"]
        hot_stocks = list(row.get("hot_stocks") or [])
        stock_codes = [
            _normalize_code6(item.get("symbol") or item.get("code"))
            for item in hot_stocks
            if _normalize_code6(item.get("symbol") or item.get("code"))
        ]
        plate_rows.append(
            {
                "provider": normalized["provider"],
                "trade_date": normalized_trade_date,
                "plate_key": normalized["plate_key"],
                "plate_name": normalized["plate_name"],
                "rank": int(row.get("rank") or 0) or 1,
                "hot_stock_count": len(stock_codes),
                "limit_up_count": int(row.get("limit_up_count") or 0),
                "stock_codes": stock_codes,
            }
        )
        for item in hot_stocks:
            code6 = _normalize_code6(item.get("symbol") or item.get("code"))
            if not code6:
                continue
            stock_rows.append(
                {
                    "provider": normalized["provider"],
                    "trade_date": normalized_trade_date,
                    "plate_key": normalized["plate_key"],
                    "plate_name": normalized["plate_name"],
                    "code6": code6,
                    "name": _to_str(item.get("stock_name") or item.get("name"))
                    or code6,
                    "is_limit_up": int(item.get("up_limit") or 0),
                    "stock_reason": _to_str(item.get("description")) or None,
                    "time": _normalize_hit_time(
                        item.get("enter_time") or item.get("time_on_market")
                    ),
                }
            )

    return plate_rows, stock_rows


def _build_jygs_gantt_rows(
    trade_date: str, rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    plate_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    stock_rows: list[dict[str, Any]] = []

    for row in rows:
        code6 = _to_str(row.get("stock_code"))
        if not code6:
            continue
        stock_name = _to_str(row.get("stock_name")) or code6
        analysis = _to_str(row.get("analysis")) or None

        for board in list(row.get("boards") or []):
            board_key = _to_str(board.get("board_key")) or normalize_board_key(
                board.get("name")
            )
            if not board_key:
                continue
            key = ("jygs", board_key, trade_date)
            plate_entry = plate_map.setdefault(
                key,
                {
                    "provider": "jygs",
                    "trade_date": trade_date,
                    "plate_key": board_key,
                    "plate_name": _to_str(board.get("name")) or board_key,
                    "rank": 0,
                    "hot_stock_count": 0,
                    "limit_up_count": 0,
                    "stock_codes": [],
                },
            )
            if code6 not in plate_entry["stock_codes"]:
                plate_entry["stock_codes"].append(code6)
                plate_entry["hot_stock_count"] += 1

            stock_rows.append(
                {
                    "provider": "jygs",
                    "trade_date": trade_date,
                    "plate_key": board_key,
                    "plate_name": plate_entry["plate_name"],
                    "code6": code6,
                    "name": stock_name,
                    "is_limit_up": 0,
                    "stock_reason": analysis,
                    "time": _normalize_hit_time(row.get("limit_up_time")),
                }
            )

    plate_rows = sorted(
        plate_map.values(),
        key=lambda item: (-int(item["hot_stock_count"]), item["plate_name"]),
    )
    for index, row in enumerate(plate_rows, start=1):
        row["rank"] = index

    return plate_rows, stock_rows


def persist_gantt_daily_for_date(trade_date: str) -> dict[str, Any]:
    date_str = _to_str(trade_date)
    if not date_str:
        raise ValueError("trade_date is required")

    ensure_readmodel_indexes()
    xgb_rows = _find_rows(COL_XGB_TOP_GAINER_HISTORY, {"trade_date": date_str})
    jygs_rows = _find_rows(COL_JYGS_YIDONG, {"date": date_str})
    plate_reason_rows = _find_rows(COL_PLATE_REASON_DAILY, {"trade_date": date_str})
    plate_reason_lookup = _build_plate_reason_lookup(plate_reason_rows)

    xgb_plate_rows, xgb_stock_rows = _build_xgb_gantt_rows(date_str, xgb_rows)
    jygs_plate_rows, jygs_stock_rows = _build_jygs_gantt_rows(date_str, jygs_rows)

    plate_rows: list[dict[str, Any]] = []
    for row in xgb_plate_rows + jygs_plate_rows:
        provider = _to_str(row.get("provider"))
        plate_key = _to_str(row.get("plate_key"))
        reason_row = plate_reason_lookup.get((provider, plate_key, date_str))
        if not reason_row:
            raise ValueError(
                f"missing plate reason for provider={provider} plate_key={plate_key} trade_date={date_str}"
            )
        enriched_row = dict(row)
        enriched_row["reason_text"] = _to_str(reason_row.get("reason_text")) or None
        enriched_row["reason_ref"] = reason_row.get("source_ref")
        plate_rows.append(enriched_row)
    stock_rows = xgb_stock_rows + jygs_stock_rows

    _delete_rows(COL_GANTT_PLATE_DAILY, {"trade_date": date_str})
    _delete_rows(COL_GANTT_STOCK_DAILY, {"trade_date": date_str})
    _upsert_rows(
        COL_GANTT_PLATE_DAILY,
        plate_rows,
        key_fields=("provider", "plate_key", "trade_date"),
    )
    _upsert_rows(
        COL_GANTT_STOCK_DAILY,
        stock_rows,
        key_fields=("provider", "plate_key", "code6", "trade_date"),
    )
    return {
        "trade_date": date_str,
        "plates": len(plate_rows),
        "stocks": len(stock_rows),
    }


def persist_stock_hot_reason_daily_for_date(trade_date: str) -> int:
    date_str = _to_str(trade_date)
    if not date_str:
        raise ValueError("trade_date is required")

    ensure_readmodel_indexes()
    gantt_stock_rows = _find_rows(COL_GANTT_STOCK_DAILY, {"trade_date": date_str})
    plate_reason_rows = _find_rows(COL_PLATE_REASON_DAILY, {"trade_date": date_str})
    rows = build_stock_hot_reason_rows(
        gantt_stock_rows=gantt_stock_rows,
        plate_reason_rows=plate_reason_rows,
    )
    _delete_rows(COL_STOCK_HOT_REASON_DAILY, {"trade_date": date_str})
    return _upsert_rows(
        COL_STOCK_HOT_REASON_DAILY,
        rows,
        key_fields=("provider", "trade_date", "plate_key", "code6"),
    )


def query_stock_hot_reason_rows(
    *,
    code6: str,
    provider: str = "all",
    limit: int = 0,
) -> list[dict[str, Any]]:
    code = _to_str(code6)
    provider_key = _to_str(provider).lower() or "all"
    if provider_key not in {"all", "xgb", "jygs"}:
        raise ValueError("provider must be all|xgb|jygs")
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("code6 must be 6 digits")

    query: dict[str, Any] = {"code6": code}
    if provider_key != "all":
        query["provider"] = provider_key

    rows = _find_rows(COL_STOCK_HOT_REASON_DAILY, query)
    rows.sort(
        key=lambda item: (
            _to_str(item.get("provider")),
            _to_str(item.get("plate_name")),
            _to_str(item.get("stock_reason")),
        )
    )
    rows.sort(key=lambda item: _to_str(item.get("time")), reverse=True)
    rows.sort(key=lambda item: _to_str(item.get("trade_date")), reverse=True)
    normalized = [
        {
            "date": _to_str(item.get("trade_date")) or None,
            "time": _normalize_hit_time(item.get("time")),
            "provider": _to_str(item.get("provider")) or None,
            "plate_name": _to_str(item.get("plate_name")) or None,
            "plate_reason": _to_str(item.get("plate_reason")) or None,
            "stock_reason": _to_str(item.get("stock_reason")) or None,
        }
        for item in rows
    ]
    max_items = max(_to_int(limit, 0), 0)
    if max_items > 0:
        return normalized[:max_items]
    return normalized


def _group_shouban30_plate_candidates(
    rows: list[dict[str, Any]],
    *,
    as_of_date: str,
    trade_dates: list[str],
) -> list[dict[str, Any]]:
    date_index = {date_str: idx for idx, date_str in enumerate(trade_dates)}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(_to_str(row.get("provider")), _to_str(row.get("plate_key")))].append(
            row
        )

    candidates: list[dict[str, Any]] = []
    for (provider, plate_key), items in grouped.items():
        items.sort(key=lambda item: _to_str(item.get("trade_date")))
        unique_dates = sorted({_to_str(item.get("trade_date")) for item in items})
        if not unique_dates:
            continue
        date_indexes = [date_index.get(date_str, -1) for date_str in unique_dates]
        if any(idx < 0 for idx in date_indexes):
            continue
        if any(
            current_idx != previous_idx + 1
            for previous_idx, current_idx in zip(date_indexes, date_indexes[1:])
        ):
            continue
        seg_from = unique_dates[0]
        seg_to = unique_dates[-1]

        last_item = max(items, key=lambda item: _to_str(item.get("trade_date")))
        candidates.append(
            {
                "provider": provider,
                "plate_key": plate_key,
                "plate_name": _to_str(last_item.get("plate_name")) or plate_key,
                "appear_days_30": len(unique_dates),
                "seg_from": seg_from,
                "seg_to": seg_to,
                "hit_trade_dates_30": unique_dates,
            }
        )

    return candidates


def _filter_shouban30_plate_candidates(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        item
        for item in rows or []
        if _to_str(item.get("plate_name")) not in SHOUBAN30_EXCLUDED_PLATE_NAMES
    ]


def _build_shouban30_chanlun_cache_key(code6: Any, as_of_date: Any) -> str:
    return (
        f"{_normalize_code6(code6)}|{_to_str(as_of_date)}|{SHOUBAN30_CHANLUN_PERIOD}"
    )


def _get_segment_gain_multiple(segment: dict[str, Any] | None) -> float | None:
    start_price = _to_float((segment or {}).get("start_price"))
    end_price = _to_float((segment or {}).get("end_price"))
    if start_price is None or end_price is None or start_price <= 0:
        return None
    return round(end_price / start_price, 4)


def _build_default_shouban30_chanlun_result(
    response: dict[str, Any] | None,
) -> dict[str, Any]:
    structure = (response or {}).get("structure") or {}
    higher_multiple = _get_segment_gain_multiple(
        structure.get("higher_segment")
    )
    segment_multiple = _get_segment_gain_multiple(
        structure.get("segment")
    )
    bi = structure.get("bi") or {}
    bi_gain_percent = _to_float(bi.get("price_change_pct"))
    result = {
        "passed": False,
        "reason": "structure_unavailable",
        "higher_multiple": higher_multiple,
        "segment_multiple": segment_multiple,
        "bi_gain_percent": bi_gain_percent,
    }
    if not (response or {}).get("ok"):
        return result
    if higher_multiple is None:
        result["reason"] = "higher_multiple_unavailable"
        return result
    if segment_multiple is None:
        result["reason"] = "segment_multiple_unavailable"
        return result
    if bi_gain_percent is None:
        result["reason"] = "bi_gain_unavailable"
        return result
    if higher_multiple > 3.0:
        result["reason"] = "higher_multiple_exceed"
        return result
    if segment_multiple > 3.0:
        result["reason"] = "segment_multiple_exceed"
        return result
    if bi_gain_percent > 30:
        result["reason"] = "bi_gain_exceed"
        return result
    result["passed"] = True
    result["reason"] = "passed"
    return result


def _resolve_shouban30_chanlun_result(
    code6: Any,
    *,
    as_of_date: str,
    chanlun_result_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cache_key = _build_shouban30_chanlun_cache_key(code6, as_of_date)
    cached = chanlun_result_cache.get(cache_key)
    if cached is not None:
        return cached
    response = get_chanlun_structure(
        _normalize_code6(code6),
        SHOUBAN30_CHANLUN_PERIOD,
        as_of_date,
    )
    result = _build_default_shouban30_chanlun_result(response)
    chanlun_result_cache[cache_key] = result
    return result


def _build_shouban30_stock_rows(
    rows: list[dict[str, Any]],
    *,
    as_of_date: str,
    stock_window_days: int,
    allowed_plate_keys: set[tuple[str, str]] | None = None,
    hit_count_30_dates: set[str] | None = None,
    chanlun_result_cache: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    target_hit_count_30_dates = {item for item in (hit_count_30_dates or set()) if item}
    target_chanlun_result_cache = (
        chanlun_result_cache if chanlun_result_cache is not None else {}
    )
    for row in rows:
        provider = _to_str(row.get("provider"))
        plate_key = _to_str(row.get("plate_key"))
        code6 = _to_str(row.get("code6"))
        if not provider or not plate_key or not code6:
            continue
        if allowed_plate_keys and (provider, plate_key) not in allowed_plate_keys:
            continue
        grouped[(provider, plate_key, code6)].append(row)

    results: list[dict[str, Any]] = []
    for (provider, plate_key, code6), items in grouped.items():
        items.sort(
            key=lambda item: (
                _to_str(item.get("trade_date")),
                _to_str(item.get("time")),
            )
        )
        latest = items[-1]
        hit_trade_dates_window = _sorted_unique_texts(
            [_to_str(item.get("trade_date")) for item in items]
        )
        hit_count_window = len(hit_trade_dates_window)
        hit_trade_dates_30 = _sorted_unique_texts(
            [
                _to_str(item.get("trade_date"))
                for item in items
                if _to_str(item.get("trade_date")) in target_hit_count_30_dates
            ]
        )
        hit_count_30 = len(hit_trade_dates_30)
        chanlun = _resolve_shouban30_chanlun_result(
            code6,
            as_of_date=as_of_date,
            chanlun_result_cache=target_chanlun_result_cache,
        )
        results.append(
            {
                "provider": provider,
                "as_of_date": as_of_date,
                "stock_window_days": stock_window_days,
                "plate_key": plate_key,
                "plate_name": _to_str(latest.get("plate_name")) or plate_key,
                "code6": code6,
                "name": _to_str(latest.get("name")) or code6,
                "hit_count_30": hit_count_30,
                "hit_count_window": hit_count_window,
                "hit_trade_dates_30": hit_trade_dates_30,
                "hit_trade_dates_window": hit_trade_dates_window,
                "latest_trade_date": _to_str(latest.get("trade_date")),
                "latest_reason": _to_str(latest.get("stock_reason")) or None,
                "chanlun_passed": bool(chanlun.get("passed")),
                "chanlun_reason": _to_str(chanlun.get("reason"))
                or "structure_unavailable",
                "chanlun_higher_multiple": chanlun.get("higher_multiple"),
                "chanlun_segment_multiple": chanlun.get("segment_multiple"),
                "chanlun_bi_gain_percent": chanlun.get("bi_gain_percent"),
                "chanlun_filter_version": SHOUBAN30_CHANLUN_FILTER_VERSION,
            }
        )
    results.sort(key=lambda item: (item["provider"], item["plate_key"], item["code6"]))
    return results


def persist_shouban30_for_date(
    as_of_date: str,
    *,
    stock_window_days: int = 30,
    chanlun_result_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    date_str = _to_str(as_of_date)
    if not date_str:
        raise ValueError("as_of_date is required")

    ensure_readmodel_indexes()
    target_window = _resolve_shouban30_stock_window_days(stock_window_days)
    all_plate_rows = _find_rows(
        COL_GANTT_PLATE_DAILY, {"trade_date": {"$lte": date_str}}
    )
    plate_trade_dates = _resolve_recent_trade_dates(
        all_plate_rows,
        days=30,
        end_date=date_str,
        field_name="trade_date",
    )
    if not plate_trade_dates:
        _delete_rows(
            COL_SHOUBAN30_PLATES,
            {"as_of_date": date_str, "stock_window_days": target_window},
        )
        _delete_rows(
            COL_SHOUBAN30_STOCKS,
            {"as_of_date": date_str, "stock_window_days": target_window},
        )
        return {
            "as_of_date": date_str,
            "plates": 0,
            "stocks": 0,
            "stock_window_days": target_window,
        }
    plate_trade_date_set = set(plate_trade_dates)
    plate_window_rows = [
        item
        for item in all_plate_rows
        if _to_str(item.get("trade_date")) in plate_trade_date_set
    ]

    all_stock_rows = _find_rows(
        COL_GANTT_STOCK_DAILY, {"trade_date": {"$lte": date_str}}
    )
    stock_trade_dates = _resolve_recent_trade_dates(
        all_stock_rows,
        days=target_window,
        end_date=date_str,
        field_name="trade_date",
    )
    stock_trade_date_set = set(stock_trade_dates)
    stock_window_rows = [
        item
        for item in all_stock_rows
        if _to_str(item.get("trade_date")) in stock_trade_date_set
    ]
    reason_window_rows = _find_rows(
        COL_PLATE_REASON_DAILY,
        {"trade_date": {"$gte": plate_trade_dates[0], "$lte": date_str}},
    )

    plate_candidates = _filter_shouban30_plate_candidates(
        _group_shouban30_plate_candidates(
        plate_window_rows,
        as_of_date=date_str,
        trade_dates=plate_trade_dates,
        )
    )

    allowed_plate_keys = {
        (_to_str(item.get("provider")), _to_str(item.get("plate_key")))
        for item in plate_candidates
    }
    target_chanlun_result_cache = (
        chanlun_result_cache if chanlun_result_cache is not None else {}
    )
    stock_rows = _build_shouban30_stock_rows(
        stock_window_rows,
        as_of_date=date_str,
        stock_window_days=target_window,
        allowed_plate_keys=allowed_plate_keys,
        hit_count_30_dates=plate_trade_date_set,
        chanlun_result_cache=target_chanlun_result_cache,
    )

    plate_stock_rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in stock_rows:
        plate_stock_rows[
            (_to_str(row.get("provider")), _to_str(row.get("plate_key")))
        ].append(row)

    for item in plate_candidates:
        plate_key = (_to_str(item.get("provider")), _to_str(item.get("plate_key")))
        stock_items = plate_stock_rows.get(plate_key, [])
        item["stock_window_days"] = target_window
        item["stocks_count"] = sum(
            1 for stock_item in stock_items if stock_item.get("chanlun_passed")
        )
        item["candidate_stocks_count"] = len(stock_items)
        item["failed_stocks_count"] = sum(
            1 for stock_item in stock_items if not stock_item.get("chanlun_passed")
        )
        item["chanlun_filter_version"] = SHOUBAN30_CHANLUN_FILTER_VERSION
        item["stock_window_from"] = (
            stock_trade_dates[0] if stock_trade_dates else date_str
        )
        item["stock_window_to"] = date_str

    plate_rows = build_shouban30_plate_rows(
        plate_rows=plate_candidates,
        plate_reason_rows=reason_window_rows,
        as_of_date=date_str,
    )

    delete_query = {"as_of_date": date_str, "stock_window_days": target_window}
    _delete_rows(COL_SHOUBAN30_PLATES, delete_query)
    _delete_rows(COL_SHOUBAN30_STOCKS, delete_query)
    _upsert_rows(
        COL_SHOUBAN30_PLATES,
        plate_rows,
        key_fields=("provider", "plate_key", "as_of_date", "stock_window_days"),
    )
    _upsert_rows(
        COL_SHOUBAN30_STOCKS,
        stock_rows,
        key_fields=(
            "provider",
            "plate_key",
            "code6",
            "as_of_date",
            "stock_window_days",
        ),
    )
    return {
        "as_of_date": date_str,
        "plates": len(plate_rows),
        "stocks": len(stock_rows),
        "stock_window_days": target_window,
    }


def build_shouban30_plate_rows(
    *,
    plate_rows: list[dict[str, Any]],
    plate_reason_rows: list[dict[str, Any]],
    as_of_date: str,
) -> list[dict[str, Any]]:
    reason_map = {
        (
            _to_str(item.get("provider")),
            _to_str(item.get("plate_key")),
            _to_str(item.get("trade_date")),
        ): item
        for item in (plate_reason_rows or [])
    }

    results: list[dict[str, Any]] = []
    for item in plate_rows or []:
        provider = _to_str(item.get("provider"))
        plate_key = _to_str(item.get("plate_key"))
        seg_to = _to_str(item.get("seg_to")) or _to_str(as_of_date)
        reason_row = reason_map.get((provider, plate_key, seg_to))
        if not reason_row:
            raise ValueError(
                f"missing plate reason for provider={provider} plate_key={plate_key} trade_date={seg_to}"
            )

        results.append(
            {
                "provider": provider,
                "as_of_date": _to_str(as_of_date),
                "plate_key": plate_key,
                "plate_name": _to_str(item.get("plate_name")),
                "stock_window_days": _resolve_shouban30_stock_window_days(
                    item.get("stock_window_days")
                ),
                "appear_days_30": item.get("appear_days_30"),
                "seg_from": _to_str(item.get("seg_from")),
                "seg_to": seg_to,
                "hit_trade_dates_30": _sorted_unique_texts(
                    list(item.get("hit_trade_dates_30") or [])
                ),
                "stocks_count": _to_int(item.get("stocks_count"), 0),
                "candidate_stocks_count": _to_int(
                    item.get("candidate_stocks_count"), 0
                ),
                "failed_stocks_count": _to_int(item.get("failed_stocks_count"), 0),
                "chanlun_filter_version": _to_str(
                    item.get("chanlun_filter_version")
                )
                or SHOUBAN30_CHANLUN_FILTER_VERSION,
                "stock_window_from": _to_str(item.get("stock_window_from")) or None,
                "stock_window_to": _to_str(item.get("stock_window_to"))
                or _to_str(as_of_date),
                "reason_text": _to_str(reason_row.get("reason_text")),
                "reason_ref": reason_row.get("source_ref"),
            }
        )

    return results


def build_gantt_plate_reason_map(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    reason_map: dict[str, dict[str, Any]] = {}
    for item in rows or []:
        trade_date = _to_str(item.get("trade_date"))
        plate_key = _to_str(item.get("plate_key"))
        if not trade_date or not plate_key:
            continue
        reason_map[f"{trade_date}|{plate_key}"] = {
            "reason_text": _to_str(item.get("reason_text")) or None,
            "reason_ref": item.get("reason_ref"),
        }
    return reason_map


def build_gantt_plate_matrix(
    rows: list[dict[str, Any]],
) -> dict[str, list[Any]]:
    if not rows:
        return {"dates": [], "y_axis": [], "series": []}

    dates = sorted(
        {
            _to_str(item.get("trade_date"))
            for item in rows
            if _to_str(item.get("trade_date"))
        }
    )
    date_map = {date_str: idx for idx, date_str in enumerate(dates)}

    plate_stats: dict[str, dict[str, Any]] = {}
    points: list[dict[str, Any]] = []
    for item in rows:
        date_str = _to_str(item.get("trade_date"))
        plate_key = _to_str(item.get("plate_key"))
        if date_str not in date_map or not plate_key:
            continue

        d_idx = date_map[date_str]
        hot_stock_count = int(item.get("hot_stock_count") or 0)
        rank = int(item.get("rank") or 999)
        stat = plate_stats.setdefault(
            plate_key,
            {
                "id": plate_key,
                "name": _to_str(item.get("plate_name")) or plate_key,
                "last_seen_idx": -1,
                "hot_stock_count_at_last": 0,
                "rank_at_last": 999,
            },
        )
        if d_idx >= stat["last_seen_idx"]:
            stat["last_seen_idx"] = d_idx
            stat["hot_stock_count_at_last"] = hot_stock_count
            stat["rank_at_last"] = rank

        points.append(
            {
                "plate_key": plate_key,
                "value": [
                    d_idx,
                    0,
                    rank,
                    hot_stock_count,
                    int(item.get("limit_up_count") or 0),
                    list(item.get("stock_codes") or []),
                ],
            }
        )

    sorted_plates = sorted(
        plate_stats.values(),
        key=lambda item: (
            item["last_seen_idx"],
            item["hot_stock_count_at_last"],
            -item["rank_at_last"],
            item["name"],
        ),
        reverse=True,
    )
    plate_y_map = {item["id"]: idx for idx, item in enumerate(sorted_plates)}

    series: list[list[Any]] = []
    for point in points:
        y_idx = plate_y_map.get(point["plate_key"])
        if y_idx is None:
            continue
        value = point["value"]
        value[1] = y_idx
        series.append(value)

    series.sort(key=lambda item: (item[0], item[1]))
    return {
        "dates": dates,
        "y_axis": [{"id": item["id"], "name": item["name"]} for item in sorted_plates],
        "series": series,
    }


def build_gantt_stock_matrix(
    rows: list[dict[str, Any]],
    *,
    plate_key: str,
) -> dict[str, list[Any]]:
    target_plate_key = _to_str(plate_key)
    filtered = [
        item for item in rows if _to_str(item.get("plate_key")) == target_plate_key
    ]
    if not filtered:
        return {"dates": [], "y_axis": [], "series": []}

    dates = sorted(
        {
            _to_str(item.get("trade_date"))
            for item in filtered
            if _to_str(item.get("trade_date"))
        }
    )
    date_map = {date_str: idx for idx, date_str in enumerate(dates)}

    rows_by_date: dict[str, list[dict[str, Any]]] = {date_str: [] for date_str in dates}
    for item in filtered:
        date_str = _to_str(item.get("trade_date"))
        if date_str in rows_by_date:
            rows_by_date[date_str].append(item)

    stock_stats: dict[str, dict[str, Any]] = {}
    current_streaks: dict[str, int] = {}
    points: list[dict[str, Any]] = []

    for date_str in dates:
        d_idx = date_map[date_str]
        today_codes: set[str] = set()
        for item in rows_by_date[date_str]:
            code6 = _to_str(item.get("code6"))
            if not code6:
                continue
            today_codes.add(code6)

            stat = stock_stats.setdefault(
                code6,
                {
                    "symbol": code6,
                    "name": _to_str(item.get("name")) or code6,
                    "last_seen_idx": -1,
                    "total_count": 0,
                },
            )
            stat["last_seen_idx"] = d_idx
            stat["total_count"] += 1
            if _to_str(item.get("name")):
                stat["name"] = _to_str(item.get("name"))

            streak = current_streaks.get(code6, 0) + 1
            current_streaks[code6] = streak
            points.append(
                {
                    "code6": code6,
                    "value": [
                        d_idx,
                        0,
                        streak,
                        int(item.get("is_limit_up") or 0),
                        _to_str(item.get("stock_reason")) or None,
                    ],
                }
            )

        for code6 in list(current_streaks.keys()):
            if code6 not in today_codes:
                current_streaks[code6] = 0

    sorted_stocks = sorted(
        stock_stats.values(),
        key=lambda item: (item["last_seen_idx"], item["total_count"], item["symbol"]),
        reverse=True,
    )
    stock_y_map = {item["symbol"]: idx for idx, item in enumerate(sorted_stocks)}

    series: list[list[Any]] = []
    for point in points:
        y_idx = stock_y_map.get(point["code6"])
        if y_idx is None:
            continue
        value = point["value"]
        value[1] = y_idx
        series.append(value)

    series.sort(key=lambda item: (item[0], item[1]))
    return {
        "dates": dates,
        "y_axis": [
            {"symbol": item["symbol"], "name": item["name"]} for item in sorted_stocks
        ],
        "series": series,
    }


def select_shouban30_plate_rows(
    rows: list[dict[str, Any]],
    *,
    provider: str,
    as_of_date: str | None = None,
    stock_window_days: int = 30,
) -> list[dict[str, Any]]:
    provider_key = _to_str(provider)
    target_window = _resolve_shouban30_stock_window_days(stock_window_days)
    filtered = [
        item
        for item in rows
        if _to_str(item.get("provider")) == provider_key
        and _resolve_shouban30_stock_window_days(item.get("stock_window_days"))
        == target_window
    ]
    if not filtered:
        return []

    target_date = _to_str(as_of_date)
    if not target_date:
        target_date = max(_to_str(item.get("as_of_date")) for item in filtered)

    return [item for item in filtered if _to_str(item.get("as_of_date")) == target_date]


def _ensure_shouban30_chanlun_snapshot_ready(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not rows:
        return []
    for item in rows:
        if not _to_str(item.get("chanlun_filter_version")):
            raise ValueError("shouban30 chanlun snapshot not ready")
    return rows


def select_shouban30_stock_rows(
    rows: list[dict[str, Any]],
    *,
    provider: str,
    plate_key: str,
    as_of_date: str | None = None,
    stock_window_days: int = 30,
) -> list[dict[str, Any]]:
    provider_key = _to_str(provider)
    target_plate_key = _to_str(plate_key)
    target_window = _resolve_shouban30_stock_window_days(stock_window_days)
    filtered = [
        item
        for item in rows
        if _to_str(item.get("provider")) == provider_key
        and _to_str(item.get("plate_key")) == target_plate_key
        and _resolve_shouban30_stock_window_days(item.get("stock_window_days"))
        == target_window
    ]
    if not filtered:
        return []

    target_date = _to_str(as_of_date)
    if not target_date:
        target_date = max(_to_str(item.get("as_of_date")) for item in filtered)

    return [item for item in filtered if _to_str(item.get("as_of_date")) == target_date]
