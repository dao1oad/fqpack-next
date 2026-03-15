# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime

from freshquant.db import DBfreshquant
from freshquant.market_data.xtdata.schema import normalize_prefixed_code

DEFAULT_XTDATA_MODE = "guardian_1m"
COMBINED_XTDATA_MODE = "guardian_and_clx_15_30"
LEGACY_CLX_XTDATA_MODE = "clx_15_30"
VALID_XTDATA_MODES = {DEFAULT_XTDATA_MODE, COMBINED_XTDATA_MODE}
XTDATA_MODE_ALIASES = {
    LEGACY_CLX_XTDATA_MODE: COMBINED_XTDATA_MODE,
}


def normalize_xtdata_mode(mode: str | None) -> str:
    m = str(mode or "").strip().lower()
    m = XTDATA_MODE_ALIASES.get(m, m)
    if m in VALID_XTDATA_MODES:
        return m
    return DEFAULT_XTDATA_MODE


def xtdata_mode_enables_guardian(mode: str | None) -> bool:
    return normalize_xtdata_mode(mode) in {
        DEFAULT_XTDATA_MODE,
        COMBINED_XTDATA_MODE,
    }


def xtdata_mode_enables_clx(mode: str | None) -> bool:
    return normalize_xtdata_mode(mode) == COMBINED_XTDATA_MODE


def load_monitor_codes(*, mode: str, max_symbols: int) -> list[str]:
    """
    Load realtime monitor code list by mode.

    - guardian_1m: holdings (xt_positions) + must_pool
    - guardian_and_clx_15_30:
      guardian pool first, then stock_pools supplement
    """
    m = normalize_xtdata_mode(mode)
    limit = _normalize_symbol_limit(max_symbols)

    if xtdata_mode_enables_guardian(m) and xtdata_mode_enables_clx(m):
        return _merge_priority_codes(
            load_guardian_monitor_codes(max_symbols=limit),
            load_clx_monitor_codes(max_symbols=limit),
            limit=limit,
        )
    if xtdata_mode_enables_guardian(m):
        return load_guardian_monitor_codes(max_symbols=limit)
    return load_clx_monitor_codes(max_symbols=limit)


def load_guardian_monitor_codes(*, max_symbols: int) -> list[str]:
    return _load_guardian_codes(_normalize_symbol_limit(max_symbols))


def load_clx_monitor_codes(*, max_symbols: int) -> list[str]:
    return _load_clx_codes(_normalize_symbol_limit(max_symbols))


def _normalize_symbol_limit(max_symbols: int) -> int:
    try:
        limit = int(max_symbols or 50)
    except Exception:
        limit = 50
    if limit <= 0:
        limit = 50
    return limit


def _merge_priority_codes(
    primary_codes: list[str], secondary_codes: list[str], *, limit: int
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    for raw_code in list(primary_codes or []) + list(secondary_codes or []):
        code = normalize_prefixed_code(str(raw_code or "")).lower()
        if not code or code in seen or len(code) < 8:
            continue
        seen.add(code)
        merged.append(code)
        if len(merged) >= limit:
            break

    return merged


def _load_guardian_codes(limit: int) -> list[str]:
    codes: set[str] = set()

    for doc in DBfreshquant["xt_positions"].find(
        {}, {"stock_code": 1, "code": 1, "symbol": 1}
    ):
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
