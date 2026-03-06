from __future__ import annotations

import hashlib
import re
import time
from typing import Any

import requests

from freshquant.db import DBGantt

COL_JYGS_YIDONG = "jygs_yidong"
COL_JYGS_ACTION_FIELDS = "jygs_action_fields"
BASE_URL = "https://app.jiuyangongshe.com/jystock-app"
ACTION_COUNT_PATH = "/api/v1/action/count-pc"
ACTION_FIELD_PATH = "/api/v1/action/field"
ACTION_LIST_PATH = "/api/v1/action/list"

_BOARD_SUFFIX_PATTERNS = (
    re.compile(r"[\*xX]\s*\d+\s*$"),
    re.compile(r"[\(（]\s*\d+\s*[\)）]\s*$"),
    re.compile(r"\s+\d+\s*$"),
)


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_board_key(name: Any) -> str:
    text = _to_str(name)
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text).strip()
    for pattern in _BOARD_SUFFIX_PATTERNS:
        next_text = pattern.sub("", text).strip()
        if next_text:
            text = next_text
    text = re.sub(r"[\*xX]\s*$", "", text).strip()
    return text


def _extract_reason_text(raw: dict[str, Any]) -> str:
    for key in ("reason", "desc", "description", "tagline", "title", "content"):
        text = _to_str(raw.get(key))
        if text:
            return text
    return ""


def normalize_jygs_action_field_row(
    trade_date: str, raw: dict[str, Any]
) -> dict[str, Any]:
    date_str = _to_str(trade_date)
    if not date_str:
        raise ValueError("trade_date is required")

    plate_name = _to_str(raw.get("name"))
    action_field_id = _to_str(raw.get("action_field_id"))
    plate_key = normalize_board_key(plate_name)
    reason_text = _extract_reason_text(raw)

    if not plate_name:
        raise ValueError("plate_name is required")
    if not plate_key:
        raise ValueError("plate_key is required")
    if not reason_text:
        raise ValueError("reason_text is required")

    return {
        "provider": "jygs",
        "trade_date": date_str,
        "plate_key": plate_key,
        "plate_name": plate_key,
        "action_field_id": action_field_id,
        "reason_text": reason_text,
        "reason_source": f"{COL_JYGS_ACTION_FIELDS}.reason",
        "source_ref": {
            "trade_date": date_str,
            "board_key": plate_key,
            "action_field_id": action_field_id,
        },
        "count": raw.get("count"),
    }


def _build_headers() -> dict[str, str]:
    timestamp_ms = int(time.time() * 1000)
    token = hashlib.md5(f"Uu0KfOB8iUP69d3c:{timestamp_ms}".encode("utf-8")).hexdigest()
    return {
        "Content-Type": "application/json",
        "platform": "3",
        "timestamp": str(timestamp_ms),
        "token": token,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.jiuyangongshe.com/action",
        "Origin": "https://www.jiuyangongshe.com",
        "Accept": "application/json, text/plain, */*",
    }


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        f"{BASE_URL}{path}",
        json=payload,
        headers=_build_headers(),
        timeout=15,
    )
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise RuntimeError(f"unexpected jygs payload type: {type(result)!r}")
    if result.get("errCode") not in (None, "0", 0):
        raise RuntimeError(f"jygs api error: {result}")
    return result


def fetch_action_count(trade_date: str) -> dict[str, Any]:
    return _post_json(ACTION_COUNT_PATH, {"date": _to_str(trade_date)})


def fetch_action_field(trade_date: str) -> dict[str, Any]:
    return _post_json(ACTION_FIELD_PATH, {"date": _to_str(trade_date), "pc": 1})


def fetch_action_list(params: dict[str, Any]) -> dict[str, Any]:
    return _post_json(ACTION_LIST_PATH, params)


def ensure_jygs_indexes() -> None:
    DBGantt[COL_JYGS_ACTION_FIELDS].create_index([("date", 1), ("board_key", 1)], unique=True)
    DBGantt[COL_JYGS_YIDONG].create_index([("date", 1), ("stock_code", 1)], unique=True)


def _extract_stock_code(value: Any) -> str:
    text = _to_str(value)
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", text)
    return match.group(1) if match else text


def _extract_analysis(item: dict[str, Any]) -> str:
    article = item.get("article") or {}
    action_info = article.get("action_info") or {}
    return (
        _to_str(action_info.get("expound"))
        or _to_str(action_info.get("reason"))
        or _to_str(article.get("title"))
        or _to_str(item.get("reason"))
    )


def sync_jygs_action_for_date(trade_date: str) -> dict[str, Any]:
    date_str = _to_str(trade_date)
    if not date_str:
        raise ValueError("trade_date is required")

    ensure_jygs_indexes()

    action_count = fetch_action_count(date_str)
    resolved_date = _to_str((action_count.get("data") or {}).get("date")) or date_str
    fields_payload = fetch_action_field(resolved_date)
    fields = list(fields_payload.get("data") or [])

    action_collection = DBGantt[COL_JYGS_ACTION_FIELDS]
    yidong_collection = DBGantt[COL_JYGS_YIDONG]

    yidong_records: dict[str, dict[str, Any]] = {}
    action_field_count = 0

    for field in fields:
        normalized = normalize_jygs_action_field_row(resolved_date, field)
        action_document = {
            "date": resolved_date,
            "board_key": normalized["plate_key"],
            "action_field_id": normalized["action_field_id"],
            "name": _to_str(field.get("name")),
            "count": field.get("count"),
            "reason": normalized["reason_text"],
        }
        action_collection.update_one(
            {"date": resolved_date, "board_key": normalized["plate_key"]},
            {"$set": action_document},
            upsert=True,
        )
        action_field_count += 1

        board = {
            "field_id": normalized["action_field_id"],
            "name": _to_str(field.get("name")),
            "board_key": normalized["plate_key"],
            "count": field.get("count"),
        }
        list_payload = fetch_action_list(
            {
                "action_field_id": normalized["action_field_id"],
                "pc": 1,
                "start": 1,
                "limit": 999,
                "sort_price": 0,
                "sort_range": 0,
                "sort_time": 0,
            }
        )
        for item in list(list_payload.get("data") or []):
            stock_code = _extract_stock_code(item.get("code"))
            if not stock_code:
                continue

            existing = yidong_records.get(stock_code)
            if existing is None:
                existing = {
                    "date": resolved_date,
                    "stock_code": stock_code,
                    "stock_name": _to_str(item.get("name")),
                    "analysis": _extract_analysis(item),
                    "boards": [],
                }
                yidong_records[stock_code] = existing

            if not existing.get("analysis"):
                existing["analysis"] = _extract_analysis(item)
            if not existing.get("stock_name"):
                existing["stock_name"] = _to_str(item.get("name"))

            existing_boards = existing.setdefault("boards", [])
            if board["board_key"] not in {
                _to_str(entry.get("board_key")) for entry in existing_boards
            }:
                existing_boards.append(dict(board))

    for stock_code, record in yidong_records.items():
        yidong_collection.update_one(
            {"date": resolved_date, "stock_code": stock_code},
            {"$set": record},
            upsert=True,
        )

    return {
        "trade_date": resolved_date,
        "action_fields": action_field_count,
        "yidong": len(yidong_records),
    }
