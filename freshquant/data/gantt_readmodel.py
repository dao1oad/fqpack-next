from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from freshquant.db import DBGantt
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


COL_PLATE_REASON_DAILY = "plate_reason_daily"
COL_GANTT_PLATE_DAILY = "gantt_plate_daily"
COL_GANTT_STOCK_DAILY = "gantt_stock_daily"
COL_SHOUBAN30_PLATES = "shouban30_plates"
COL_SHOUBAN30_STOCKS = "shouban30_stocks"


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _calc_start_date(end_date: str, days: int) -> str:
    if days <= 1:
        return end_date
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    return (end_dt - timedelta(days=days - 1)).strftime("%Y-%m-%d")


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
    _get_collection(COL_SHOUBAN30_PLATES).create_index(
        [("provider", 1), ("plate_key", 1), ("as_of_date", 1)],
        unique=True,
    )
    _get_collection(COL_SHOUBAN30_STOCKS).create_index(
        [("provider", 1), ("plate_key", 1), ("code6", 1), ("as_of_date", 1)],
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


def query_gantt_plate_matrix(
    *,
    provider: str,
    days: int = 30,
    end_date: str | None = None,
) -> dict[str, list[Any]]:
    provider_key = _to_str(provider)
    rows = _find_rows(COL_GANTT_PLATE_DAILY, {"provider": provider_key})
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
    return build_gantt_plate_matrix(filtered)


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
) -> list[dict[str, Any]]:
    provider_key = _to_str(provider)
    rows = _find_rows(COL_SHOUBAN30_PLATES, {"provider": provider_key})
    return select_shouban30_plate_rows(
        rows,
        provider=provider_key,
        as_of_date=as_of_date,
    )


def query_shouban30_stock_rows(
    *,
    provider: str,
    plate_key: str,
    as_of_date: str | None = None,
) -> list[dict[str, Any]]:
    provider_key = _to_str(provider)
    target_plate_key = _to_str(plate_key)
    rows = _find_rows(
        COL_SHOUBAN30_STOCKS,
        {"provider": provider_key, "plate_key": target_plate_key},
    )
    return select_shouban30_stock_rows(
        rows,
        provider=provider_key,
        plate_key=target_plate_key,
        as_of_date=as_of_date,
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


def _build_xgb_gantt_rows(trade_date: str, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
            _to_str(item.get("symbol") or item.get("code"))
            for item in hot_stocks
            if _to_str(item.get("symbol") or item.get("code"))
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
            code6 = _to_str(item.get("symbol") or item.get("code"))
            if not code6:
                continue
            stock_rows.append(
                {
                    "provider": normalized["provider"],
                    "trade_date": normalized_trade_date,
                    "plate_key": normalized["plate_key"],
                    "plate_name": normalized["plate_name"],
                    "code6": code6,
                    "name": _to_str(item.get("stock_name") or item.get("name")) or code6,
                    "is_limit_up": int(item.get("up_limit") or 0),
                    "stock_reason": _to_str(item.get("description")) or None,
                }
            )

    return plate_rows, stock_rows


def _build_jygs_gantt_rows(trade_date: str, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    plate_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    stock_rows: list[dict[str, Any]] = []

    for row in rows:
        code6 = _to_str(row.get("stock_code"))
        if not code6:
            continue
        stock_name = _to_str(row.get("stock_name")) or code6
        analysis = _to_str(row.get("analysis")) or None

        for board in list(row.get("boards") or []):
            board_key = _to_str(board.get("board_key")) or normalize_board_key(board.get("name"))
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

    xgb_plate_rows, xgb_stock_rows = _build_xgb_gantt_rows(date_str, xgb_rows)
    jygs_plate_rows, jygs_stock_rows = _build_jygs_gantt_rows(date_str, jygs_rows)

    plate_rows = xgb_plate_rows + jygs_plate_rows
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


def _group_shouban30_plate_candidates(
    rows: list[dict[str, Any]],
    *,
    as_of_date: str,
) -> list[dict[str, Any]]:
    all_dates = sorted({_to_str(item.get("trade_date")) for item in rows if _to_str(item.get("trade_date"))})
    date_index = {date_str: idx for idx, date_str in enumerate(all_dates)}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(_to_str(row.get("provider")), _to_str(row.get("plate_key")))].append(row)

    candidates: list[dict[str, Any]] = []
    for (provider, plate_key), items in grouped.items():
        items.sort(key=lambda item: _to_str(item.get("trade_date")))
        unique_dates = sorted({_to_str(item.get("trade_date")) for item in items})
        if not unique_dates:
            continue
        seg_from = unique_dates[0]
        seg_to = unique_dates[0]
        previous_idx = date_index.get(seg_to, -1)
        for current_date in unique_dates[1:]:
            current_idx = date_index.get(current_date, -1)
            if current_idx == previous_idx + 1:
                seg_to = current_date
            else:
                seg_from = current_date
                seg_to = current_date
            previous_idx = current_idx

        last_item = max(items, key=lambda item: _to_str(item.get("trade_date")))
        candidates.append(
            {
                "provider": provider,
                "plate_key": plate_key,
                "plate_name": _to_str(last_item.get("plate_name")) or plate_key,
                "appear_days_30": len(unique_dates),
                "seg_from": seg_from,
                "seg_to": seg_to,
            }
        )

    return candidates


def _build_shouban30_stock_rows(
    rows: list[dict[str, Any]],
    *,
    as_of_date: str,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        provider = _to_str(row.get("provider"))
        plate_key = _to_str(row.get("plate_key"))
        code6 = _to_str(row.get("code6"))
        if not provider or not plate_key or not code6:
            continue
        grouped[(provider, plate_key, code6)].append(row)

    results: list[dict[str, Any]] = []
    for (provider, plate_key, code6), items in grouped.items():
        items.sort(key=lambda item: _to_str(item.get("trade_date")))
        latest = items[-1]
        appear_days = len({_to_str(item.get("trade_date")) for item in items})
        results.append(
            {
                "provider": provider,
                "as_of_date": as_of_date,
                "plate_key": plate_key,
                "plate_name": _to_str(latest.get("plate_name")) or plate_key,
                "code6": code6,
                "name": _to_str(latest.get("name")) or code6,
                "appear_days_90": appear_days,
                "latest_trade_date": _to_str(latest.get("trade_date")),
                "stock_reason": _to_str(latest.get("stock_reason")) or None,
            }
        )
    results.sort(key=lambda item: (item["provider"], item["plate_key"], item["code6"]))
    return results


def persist_shouban30_for_date(as_of_date: str) -> dict[str, Any]:
    date_str = _to_str(as_of_date)
    if not date_str:
        raise ValueError("as_of_date is required")

    ensure_readmodel_indexes()
    start_30 = _calc_start_date(date_str, 30)
    start_90 = _calc_start_date(date_str, 90)

    plate_window_rows = _find_rows(
        COL_GANTT_PLATE_DAILY,
        {"trade_date": {"$gte": start_30, "$lte": date_str}},
    )
    stock_window_rows = _find_rows(
        COL_GANTT_STOCK_DAILY,
        {"trade_date": {"$gte": start_90, "$lte": date_str}},
    )
    reason_window_rows = _find_rows(
        COL_PLATE_REASON_DAILY,
        {"trade_date": {"$gte": start_30, "$lte": date_str}},
    )

    plate_candidates = _group_shouban30_plate_candidates(
        plate_window_rows,
        as_of_date=date_str,
    )

    stock_counts: dict[tuple[str, str], int] = defaultdict(int)
    grouped_stocks = defaultdict(set)
    for row in stock_window_rows:
        key = (_to_str(row.get("provider")), _to_str(row.get("plate_key")))
        code6 = _to_str(row.get("code6"))
        if key[0] and key[1] and code6:
            grouped_stocks[key].add(code6)
    for key, codes in grouped_stocks.items():
        stock_counts[key] = len(codes)

    for item in plate_candidates:
        item["stocks_count_90"] = stock_counts.get(
            (_to_str(item.get("provider")), _to_str(item.get("plate_key"))),
            0,
        )

    plate_rows = build_shouban30_plate_rows(
        plate_rows=plate_candidates,
        plate_reason_rows=reason_window_rows,
        as_of_date=date_str,
    )
    stock_rows = _build_shouban30_stock_rows(stock_window_rows, as_of_date=date_str)

    _delete_rows(COL_SHOUBAN30_PLATES, {"as_of_date": date_str})
    _delete_rows(COL_SHOUBAN30_STOCKS, {"as_of_date": date_str})
    _upsert_rows(
        COL_SHOUBAN30_PLATES,
        plate_rows,
        key_fields=("provider", "plate_key", "as_of_date"),
    )
    _upsert_rows(
        COL_SHOUBAN30_STOCKS,
        stock_rows,
        key_fields=("provider", "plate_key", "code6", "as_of_date"),
    )
    return {
        "as_of_date": date_str,
        "plates": len(plate_rows),
        "stocks": len(stock_rows),
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
                "appear_days_30": item.get("appear_days_30"),
                "seg_from": _to_str(item.get("seg_from")),
                "seg_to": seg_to,
                "stocks_count_90": item.get("stocks_count_90"),
                "reason_text": _to_str(reason_row.get("reason_text")),
                "reason_ref": reason_row.get("source_ref"),
            }
        )

    return results


def build_gantt_plate_matrix(
    rows: list[dict[str, Any]],
) -> dict[str, list[Any]]:
    if not rows:
        return {"dates": [], "y_axis": [], "series": []}

    dates = sorted({_to_str(item.get("trade_date")) for item in rows if _to_str(item.get("trade_date"))})
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
    filtered = [item for item in rows if _to_str(item.get("plate_key")) == target_plate_key]
    if not filtered:
        return {"dates": [], "y_axis": [], "series": []}

    dates = sorted({_to_str(item.get("trade_date")) for item in filtered if _to_str(item.get("trade_date"))})
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
        "y_axis": [{"symbol": item["symbol"], "name": item["name"]} for item in sorted_stocks],
        "series": series,
    }


def select_shouban30_plate_rows(
    rows: list[dict[str, Any]],
    *,
    provider: str,
    as_of_date: str | None = None,
) -> list[dict[str, Any]]:
    provider_key = _to_str(provider)
    filtered = [item for item in rows if _to_str(item.get("provider")) == provider_key]
    if not filtered:
        return []

    target_date = _to_str(as_of_date)
    if not target_date:
        target_date = max(_to_str(item.get("as_of_date")) for item in filtered)

    return [item for item in filtered if _to_str(item.get("as_of_date")) == target_date]


def select_shouban30_stock_rows(
    rows: list[dict[str, Any]],
    *,
    provider: str,
    plate_key: str,
    as_of_date: str | None = None,
) -> list[dict[str, Any]]:
    provider_key = _to_str(provider)
    target_plate_key = _to_str(plate_key)
    filtered = [
        item
        for item in rows
        if _to_str(item.get("provider")) == provider_key
        and _to_str(item.get("plate_key")) == target_plate_key
    ]
    if not filtered:
        return []

    target_date = _to_str(as_of_date)
    if not target_date:
        target_date = max(_to_str(item.get("as_of_date")) for item in filtered)

    return [item for item in filtered if _to_str(item.get("as_of_date")) == target_date]
