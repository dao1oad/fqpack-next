# -*- coding: utf-8 -*-
"""本机 quantaxis 日线行情获取（零网络，全市场覆盖）。

读取本机 MongoDB `quantaxis.stock_day`，为给定标的列表生成 as-of 行情快照：
当日 OHLCV/量额、涨跌幅、52 周高低。产出与第三方行情无关，证据可追溯。
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
from typing import Any

import pymongo

MONGO_URI = "mongodb://127.0.0.1:27027"
DB_NAME = "quantaxis"
COLLECTION = "stock_day"


def _client() -> pymongo.MongoClient:
    return pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)


def local_quote(symbol: str, as_of: str, col=None) -> dict[str, Any] | None:
    """取单只标的 as-of 行情快照；无当日 bar 时回退最近交易日。"""
    if col is None:
        col = _client()[DB_NAME][COLLECTION]
    bar = col.find_one({"code": symbol, "date": as_of})
    if not bar:
        bar = col.find_one(
            {"code": symbol, "date": {"$lte": as_of}}, sort=[("date", -1)]
        )
    if not bar:
        return None
    prev = col.find_one(
        {"code": symbol, "date": {"$lt": as_of}}, sort=[("date", -1)]
    )
    wk_ago = (
        _dt.date.fromisoformat(as_of) - _dt.timedelta(days=365)
    ).isoformat()
    rows = list(
        col.find(
            {"code": symbol, "date": {"$gte": wk_ago, "$lte": as_of}},
            {"high": 1, "low": 1, "close": 1},
        )
    )
    return {
        "schemaVersion": "clx-quotes-local.v1",
        "symbol": symbol,
        "source": "local.quantaxis.stock_day",
        "quoteDate": bar["date"],
        "open": bar.get("open"),
        "high": bar.get("high"),
        "low": bar.get("low"),
        "close": bar.get("close"),
        "volume": bar.get("vol"),
        "amount": bar.get("amount"),
        "prevClose": prev["close"] if prev else None,
        "pctChgPct": round((bar["close"] / prev["close"] - 1) * 100, 2)
        if prev and prev.get("close") else None,
        "high52w": max((r["high"] for r in rows), default=None),
        "low52w": min((r["low"] for r in rows), default=None),
        "barCount52w": len(rows),
    }


def build_local_quotes_payload(
    symbols: list[str], as_of: str
) -> dict[str, dict[str, Any]]:
    col = _client()[DB_NAME][COLLECTION]
    return {
        symbol: local_quote(symbol, as_of, col=col) for symbol in symbols
    }


def write_quotes_file(
    run_dir: pathlib.Path, payload: dict[str, dict[str, Any]], as_of: str
) -> pathlib.Path:
    out = run_dir / "data" / f"quotes_local_{as_of}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    return out
