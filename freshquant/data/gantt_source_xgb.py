from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import requests  # type: ignore[import-untyped]

from freshquant.db import DBGantt

COL_XGB_TOP_GAINER_HISTORY = "xgb_top_gainer_history"
BASE_URL = "https://flash-api.xuangubao.cn/api"
XGB_EXCLUDE_PLATE_IDS = {-1}
XGB_EXCLUDE_PLATE_NAMES = {"其他"}


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_xgb_history_row(raw: dict[str, Any]) -> dict[str, Any]:
    trade_date = _to_str(raw.get("trade_date"))
    plate_name = _to_str(raw.get("plate_name"))
    reason_text = _to_str(raw.get("description"))
    plate_id = raw.get("plate_id")

    if not trade_date:
        raise ValueError("trade_date is required")
    if plate_id is None:
        raise ValueError("plate_id is required")
    if not plate_name:
        raise ValueError("plate_name is required")
    if not reason_text:
        raise ValueError("reason_text is required")

    return {
        "provider": "xgb",
        "trade_date": trade_date,
        "plate_id": int(plate_id),
        "plate_key": str(int(plate_id)),
        "plate_name": plate_name,
        "reason_text": reason_text,
        "reason_source": f"{COL_XGB_TOP_GAINER_HISTORY}.description",
        "source_ref": {
            "trade_date": trade_date,
            "plate_id": int(plate_id),
        },
        "rank": raw.get("rank"),
        "hot_stocks": list(raw.get("hot_stocks") or []),
    }


def _fetch_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected xgb payload type: {type(payload)!r}")
    return payload


def ensure_xgb_history_indexes() -> None:
    collection = DBGantt[COL_XGB_TOP_GAINER_HISTORY]
    collection.create_index([("trade_date", 1), ("plate_id", 1)], unique=True)
    collection.create_index([("trade_date", -1), ("rank", 1)])


def _fetch_plate_set_detail(plate_id: int) -> dict[str, Any]:
    payload = _fetch_json(f"{BASE_URL}/plate/plate_set", params={"id": int(plate_id)})
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return {}
    return data


def _build_xgb_hot_stock_map(
    payload: dict[str, Any],
) -> dict[int, list[dict[str, Any]]]:
    fields = list((payload.get("data") or {}).get("fields") or [])
    items = list((payload.get("data") or {}).get("items") or [])
    hot_map: dict[int, list[dict[str, Any]]] = {}

    for item in items:
        if not isinstance(item, list):
            continue
        row = {}
        for index, key in enumerate(fields):
            row[key] = item[index] if index < len(item) else None

        plates = row.get("plates")
        if not isinstance(plates, list):
            plates = []
        stock: dict[str, Any] = {
            "symbol": _to_str(row.get("code")),
            "stock_name": _to_str(row.get("prod_name")),
            "description": _to_str(row.get("description")),
            "up_limit": row.get("up_limit"),
            "enter_time": row.get("enter_time"),
            "time_on_market": row.get("time_on_market"),
            "plates": plates,
        }
        if not stock["symbol"]:
            continue

        for plate in stock["plates"]:
            if not isinstance(plate, dict):
                continue
            plate_id = plate.get("id") or plate.get("plate_id")
            if plate_id is None:
                continue
            hot_map.setdefault(int(plate_id), []).append(stock)

    return hot_map


def sync_xgb_history_for_date(trade_date: str) -> int:
    date_str = _to_str(trade_date)
    if not date_str:
        raise ValueError("trade_date is required")

    ensure_xgb_history_indexes()

    timestamp = int(time.mktime(datetime.strptime(date_str, "%Y-%m-%d").timetuple()))
    plate_payload = _fetch_json(
        f"{BASE_URL}/surge_stock/plates", params={"date": timestamp}
    )
    plates = list((plate_payload.get("data") or {}).get("items") or [])
    if not plates:
        return 0

    plate_ids = [str(item.get("id")) for item in plates if item.get("id") is not None]
    detail_map: dict[str, dict[str, Any]] = {}
    if plate_ids:
        detail_payload = _fetch_json(
            f"{BASE_URL}/plate/data",
            params={
                "plates": ",".join(plate_ids),
                "fields": "plate_id,plate_name,limit_up_count",
                "date": timestamp,
            },
        )
        detail_map = dict(detail_payload.get("data") or {})

    stock_payload = _fetch_json(
        f"{BASE_URL}/surge_stock/stocks",
        params={
            "normal": "true",
            "uplimit": "true",
            "date": date_str.replace("-", ""),
        },
    )
    hot_stock_map = _build_xgb_hot_stock_map(stock_payload)

    collection = DBGantt[COL_XGB_TOP_GAINER_HISTORY]
    collection.delete_many({"trade_date": date_str})
    count = 0
    plate_set_cache: dict[int, dict[str, Any]] = {}
    for rank, plate in enumerate(plates, start=1):
        plate_id = plate.get("id")
        if plate_id is None:
            continue
        plate_id_int = int(plate_id)
        if plate_id_int in XGB_EXCLUDE_PLATE_IDS:
            continue

        detail = detail_map.get(str(plate_id_int), {})
        plate_name = _to_str(detail.get("plate_name")) or _to_str(plate.get("name"))
        if plate_name in XGB_EXCLUDE_PLATE_NAMES:
            continue

        description = _to_str(plate.get("description"))
        if not description:
            cached_detail = plate_set_cache.get(plate_id_int)
            if cached_detail is None:
                cached_detail = _fetch_plate_set_detail(plate_id_int)
                plate_set_cache[plate_id_int] = cached_detail
            description = _to_str(cached_detail.get("desc"))

        document = {
            "trade_date": date_str,
            "plate_id": plate_id_int,
            "plate_name": plate_name,
            "description": description,
            "limit_up_count": detail.get("limit_up_count"),
            "rank": rank,
            "hot_stocks": hot_stock_map.get(plate_id_int, []),
            "provider": "xgb",
        }
        collection.update_one(
            {"trade_date": date_str, "plate_id": plate_id_int},
            {"$set": document},
            upsert=True,
        )
        count += 1

    return count
