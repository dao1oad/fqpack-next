# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime

from freshquant.db import DBfreshquant
from freshquant.market_data.xtdata.schema import normalize_prefixed_code


def load_monitor_codes(*, mode: str, max_symbols: int) -> list[str]:
    """
    Load realtime monitor code list by mode.

    - guardian_1m: holdings (xt_positions) + must_pool
    - clx_15_30:   stock_pools (non-expired)
    """
    m = str(mode or "").strip().lower()
    try:
        limit = int(max_symbols or 50)
    except Exception:
        limit = 50
    if limit <= 0:
        limit = 50

    if m == "guardian_1m":
        return _load_guardian_codes(limit)
    return _load_clx_codes(limit)


def _load_guardian_codes(limit: int) -> list[str]:
    codes: set[str] = set()

    for doc in DBfreshquant["xt_positions"].find({}, {"stock_code": 1, "code": 1, "symbol": 1}):
        raw = doc.get("stock_code") or doc.get("code") or doc.get("symbol") or ""
        norm = normalize_prefixed_code(str(raw)).lower()
        if norm:
            codes.add(norm)

    for doc in DBfreshquant["must_pool"].find(
        {"instrument_type": {"$in": ["stock_cn", "etf_cn"]}, "disabled": {"$ne": True}},
        {"code": 1},
    ):
        raw = doc.get("code") or ""
        norm = normalize_prefixed_code(str(raw)).lower()
        if norm:
            codes.add(norm)

    out = sorted(c for c in codes if len(c) >= 8)[:limit]
    return out


def _load_clx_codes(limit: int) -> list[str]:
    codes: set[str] = set()
    now = datetime.now()
    for doc in DBfreshquant["stock_pools"].find(
        {"$or": [{"expire_at": {"$exists": False}}, {"expire_at": {"$gt": now}}]},
        {"code": 1},
    ):
        raw = doc.get("code") or ""
        norm = normalize_prefixed_code(str(raw)).lower()
        if norm:
            codes.add(norm)
    out = sorted(c for c in codes if len(c) >= 8)[:limit]
    return out

