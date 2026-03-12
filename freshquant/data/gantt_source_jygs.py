from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
from typing import Any

import requests  # type: ignore[import-untyped]

from freshquant.db import DBGantt

COL_JYGS_YIDONG = "jygs_yidong"
COL_JYGS_ACTION_FIELDS = "jygs_action_fields"
BASE_URL = "https://app.jiuyangongshe.com/jystock-app"
ACTION_COUNT_PATH = "/api/v1/action/count-pc"
ACTION_FIELD_PATH = "/api/v1/action/field"
ACTION_LIST_PATH = "/api/v1/action/list"
JYGS_EXCLUDE_PLATE_NAMES = {"公告", "其他", "新股", "ST板块"}
EMPTY_RESULT_FLAG = "is_empty_result"
EMPTY_RESULT_REASON_FIELD = "empty_reason"
EMPTY_RESULT_REASON_UPSTREAM_TRADE_DATE_MISMATCH = "upstream_trade_date_mismatch"
EMPTY_RESULT_REASON_NO_THEME_FIELDS = "no_theme_fields"
EMPTY_RESULT_BOARD_KEY = "__empty__"
EMPTY_RESULT_STOCK_CODE = "__empty__"

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


def should_sync_action_field(raw: dict[str, Any]) -> bool:
    action_field_id = _to_str(raw.get("action_field_id"))
    if not action_field_id:
        return False

    plate_name = _to_str(raw.get("name"))
    normalized_plate_name = normalize_board_key(plate_name)
    if plate_name in JYGS_EXCLUDE_PLATE_NAMES:
        return False
    if normalized_plate_name in JYGS_EXCLUDE_PLATE_NAMES:
        return False
    return True


def _build_headers() -> dict[str, str]:
    return _build_action_headers("application/json")


def _build_action_headers(content_type: str) -> dict[str, str]:
    timestamp_ms = int(time.time() * 1000)
    token = hashlib.md5(f"Uu0KfOB8iUP69d3c:{timestamp_ms}".encode("utf-8")).hexdigest()
    return {
        "Content-Type": content_type,
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


def _parse_cookie_header(cookie_str: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in (cookie_str or "").split(";"):
        if not part.strip() or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            cookies[key] = value
    return cookies


def _extract_session_from_admin_cookie(admin_value: str) -> str:
    if not admin_value:
        return ""
    try:
        decoded = urllib.parse.unquote(admin_value)
        payload = json.loads(decoded)
    except Exception:
        return ""
    return _to_str(payload.get("sessionToken"))


def _load_envs_from_file() -> dict[str, str]:
    env_path = _to_str(os.getenv("JYGS_ENV_FILE")) or r"D:\fqpack\config\envs.conf"
    if not env_path or not os.path.exists(env_path):
        return {}

    values: dict[str, str] = {}
    with open(env_path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            normalized_value = value.strip()
            if (
                len(normalized_value) >= 2
                and normalized_value[0] == normalized_value[-1]
                and normalized_value[0] in {'"', "'"}
            ):
                normalized_value = normalized_value[1:-1]
            values[key.strip()] = normalized_value
    return values


def get_auth_cookies() -> dict[str, str]:
    cookie_str = _to_str(os.getenv("JYGS_COOKIE"))
    session = _to_str(os.getenv("JYGS_SESSION"))
    if not cookie_str or not session:
        env_values = _load_envs_from_file()
        if not cookie_str:
            cookie_str = _to_str(env_values.get("JYGS_COOKIE"))
        if not session:
            session = _to_str(env_values.get("JYGS_SESSION"))

    cookies = _parse_cookie_header(cookie_str)
    if session and "SESSION" not in cookies:
        cookies["SESSION"] = session
    if "SESSION" not in cookies and "admin" in cookies:
        admin_session = _extract_session_from_admin_cookie(cookies.get("admin", ""))
        if admin_session:
            cookies["SESSION"] = admin_session
    return cookies


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    cookies = get_auth_cookies() or None
    response = requests.post(
        f"{BASE_URL}{path}",
        json=payload,
        headers=_build_action_headers("application/json"),
        cookies=cookies,
        timeout=15,
    )
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise RuntimeError(f"unexpected jygs payload type: {type(result)!r}")
    if result.get("errCode") in {"1", "9", 1, 9}:
        response = requests.post(
            f"{BASE_URL}{path}",
            data=payload,
            headers=_build_action_headers(
                "application/x-www-form-urlencoded;charset=utf-8"
            ),
            cookies=cookies,
            timeout=15,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError(f"unexpected jygs payload type: {type(result)!r}")
    if result.get("errCode") not in (None, "0", 0):
        raise RuntimeError(
            "jygs api error: "
            f"{result}; missing/expired JYGS_SESSION or JYGS_COOKIE for this environment"
        )
    return result


def fetch_action_count(trade_date: str) -> dict[str, Any]:
    return _post_json(ACTION_COUNT_PATH, {"date": _to_str(trade_date)})


def fetch_action_field(trade_date: str) -> dict[str, Any]:
    return _post_json(ACTION_FIELD_PATH, {"date": _to_str(trade_date), "pc": 1})


def fetch_action_list(params: dict[str, Any]) -> dict[str, Any]:
    return _post_json(ACTION_LIST_PATH, params)


def ensure_jygs_indexes() -> None:
    DBGantt[COL_JYGS_ACTION_FIELDS].create_index(
        [("date", 1), ("board_key", 1)], unique=True
    )
    DBGantt[COL_JYGS_YIDONG].create_index([("date", 1), ("stock_code", 1)], unique=True)


def _write_empty_sync_result(
    action_collection,
    yidong_collection,
    trade_date: str,
    *,
    reason: str,
) -> dict[str, Any]:
    action_collection.delete_many({"date": trade_date})
    yidong_collection.delete_many({"date": trade_date})
    action_collection.update_one(
        {"date": trade_date, "board_key": EMPTY_RESULT_BOARD_KEY},
        {
            "$set": {
                "date": trade_date,
                "board_key": EMPTY_RESULT_BOARD_KEY,
                "action_field_id": EMPTY_RESULT_BOARD_KEY,
                "name": EMPTY_RESULT_BOARD_KEY,
                "count": 0,
                EMPTY_RESULT_FLAG: True,
                EMPTY_RESULT_REASON_FIELD: reason,
            }
        },
        upsert=True,
    )
    yidong_collection.update_one(
        {"date": trade_date, "stock_code": EMPTY_RESULT_STOCK_CODE},
        {
            "$set": {
                "date": trade_date,
                "stock_code": EMPTY_RESULT_STOCK_CODE,
                "stock_name": EMPTY_RESULT_STOCK_CODE,
                "boards": [],
                EMPTY_RESULT_FLAG: True,
                EMPTY_RESULT_REASON_FIELD: reason,
            }
        },
        upsert=True,
    )
    return {"trade_date": trade_date, "action_fields": 0, "yidong": 0}


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
    action_collection = DBGantt[COL_JYGS_ACTION_FIELDS]
    yidong_collection = DBGantt[COL_JYGS_YIDONG]

    action_count = fetch_action_count(date_str)
    resolved_date = _to_str((action_count.get("data") or {}).get("date")) or date_str
    if resolved_date != date_str:
        return _write_empty_sync_result(
            action_collection,
            yidong_collection,
            date_str,
            reason=EMPTY_RESULT_REASON_UPSTREAM_TRADE_DATE_MISMATCH,
        )

    fields_payload = fetch_action_field(date_str)
    fields = [
        field
        for field in list(fields_payload.get("data") or [])
        if should_sync_action_field(field)
    ]
    if not fields:
        return _write_empty_sync_result(
            action_collection,
            yidong_collection,
            date_str,
            reason=EMPTY_RESULT_REASON_NO_THEME_FIELDS,
        )

    action_collection.delete_many({"date": date_str})
    yidong_collection.delete_many({"date": date_str})

    yidong_records: dict[str, dict[str, Any]] = {}
    action_field_count = 0

    for field in fields:
        normalized = normalize_jygs_action_field_row(date_str, field)
        action_document = {
            "date": date_str,
            "board_key": normalized["plate_key"],
            "action_field_id": normalized["action_field_id"],
            "name": _to_str(field.get("name")),
            "count": field.get("count"),
            "reason": normalized["reason_text"],
        }
        action_collection.update_one(
            {"date": date_str, "board_key": normalized["plate_key"]},
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
                    "date": date_str,
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
            {"date": date_str, "stock_code": stock_code},
            {"$set": record},
            upsert=True,
        )

    return {
        "trade_date": date_str,
        "action_fields": action_field_count,
        "yidong": len(yidong_records),
    }
