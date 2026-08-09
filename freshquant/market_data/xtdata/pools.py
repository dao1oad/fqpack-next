# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from loguru import logger

from freshquant.db import DBfreshquant
from freshquant.market_data.xtdata.schema import normalize_prefixed_code

# 三条正交监控线（按用途命名，替代旧 mode 字符串枚举）。
LINE_1M_T = "line_1m_t"
LINE_5M_NEW_OPEN = "line_5m_new_open"
LINE_15_30_CLX = "line_15_30_clx"

# 并集装配优先级：高优先级集合先完整，低优先级可截断。
LINE_PRIORITY_ORDER = (LINE_1M_T, LINE_5M_NEW_OPEN, LINE_15_30_CLX)

# 旧枚举仅存活于一次性迁移函数（migrate_xtdata_mode）内部。
DEFAULT_XTDATA_MODE = "guardian_1m"
COMBINED_XTDATA_MODE = "guardian_and_clx_15_30"
CLX_ONLY_XTDATA_MODE = "clx_15_30_only"
LEGACY_CLX_XTDATA_MODE = "clx_15_30"
VALID_XTDATA_MODES = {
    DEFAULT_XTDATA_MODE,
    COMBINED_XTDATA_MODE,
    CLX_ONLY_XTDATA_MODE,
}
XTDATA_MODE_ALIASES = {
    LEGACY_CLX_XTDATA_MODE: COMBINED_XTDATA_MODE,
}


def normalize_xtdata_mode(mode: str | None) -> str:
    """一次性迁移辅助：把旧 mode 字符串归一为正式旧枚举值。"""

    m = str(mode or "").strip().lower()
    m = XTDATA_MODE_ALIASES.get(m, m)
    if m in VALID_XTDATA_MODES:
        return m
    return DEFAULT_XTDATA_MODE


def xtdata_mode_enables_guardian(mode: str | None) -> bool:
    """一次性迁移辅助：旧 mode 是否启用交易能力。"""

    return normalize_xtdata_mode(mode) in {
        DEFAULT_XTDATA_MODE,
        COMBINED_XTDATA_MODE,
    }


def xtdata_mode_enables_clx(mode: str | None) -> bool:
    """一次性迁移辅助：旧 mode 是否启用选股能力。"""

    return normalize_xtdata_mode(mode) in {
        COMBINED_XTDATA_MODE,
        CLX_ONLY_XTDATA_MODE,
    }


def migrate_xtdata_mode(mode: str | None) -> tuple[bool, bool]:
    """把旧 mode 字符串一次性迁移为 (trading_mode, screening_mode)。"""

    normalized = normalize_xtdata_mode(mode)
    if normalized == CLX_ONLY_XTDATA_MODE:
        return (False, True)
    if normalized == COMBINED_XTDATA_MODE:
        return (True, True)
    return (True, False)


def lines_for_modes(*, trading_mode: bool, screening_mode: bool) -> tuple[str, ...]:
    """模式 → 启用的监控线（保持设计文档的映射）。"""

    enabled: list[str] = []
    if trading_mode:
        enabled.extend((LINE_1M_T, LINE_5M_NEW_OPEN))
    if screening_mode:
        enabled.append(LINE_15_30_CLX)
    return tuple(line for line in LINE_PRIORITY_ORDER if line in enabled)


def load_line_codes(*, line: str, max_symbols: int) -> list[str]:
    """加载单条监控线的代码池（去重、按行内排序）。"""

    limit = _normalize_symbol_limit(max_symbols)
    if line == LINE_1M_T:
        return _load_holding_codes(limit)
    if line == LINE_5M_NEW_OPEN:
        return _load_must_pool_codes(limit)
    if line == LINE_15_30_CLX:
        return _load_clx_codes(limit)
    return []


def load_monitor_codes(
    *,
    trading_mode: bool,
    screening_mode: bool,
    max_symbols: int,
) -> list[str]:
    """
    装配实时监控代码列表。

    - 订阅并集：所有启用行的代码并集；
    - 优先级截断：line_1m_t > line_5m_new_open > line_15_30_clx，
      达到 max_symbols 上限时从低优先级末尾截断；
    - 触顶时写 runtime 事件（reason_code=line_codes_truncated）并记日志告警，不静默。
    """

    limit = _normalize_symbol_limit(max_symbols)
    enabled_lines = lines_for_modes(
        trading_mode=bool(trading_mode),
        screening_mode=bool(screening_mode),
    )
    merged: list[str] = []
    seen: set[str] = set()
    truncated_lines: list[dict[str, object]] = []

    for line in enabled_lines:
        raw_codes = load_line_codes(line=line, max_symbols=limit)
        line_codes: list[str] = []
        for raw_code in raw_codes:
            code = normalize_prefixed_code(str(raw_code or "")).lower()
            if not code or code in seen or len(code) < 8:
                continue
            seen.add(code)
            line_codes.append(code)
        remaining = limit - len(merged)
        if remaining <= 0:
            if line_codes:
                truncated_lines.append(
                    {"line": line, "truncated_count": len(line_codes)}
                )
            continue
        if len(line_codes) > remaining:
            truncated_lines.append(
                {"line": line, "truncated_count": len(line_codes) - remaining}
            )
            line_codes = line_codes[:remaining]
        merged.extend(line_codes)

    if truncated_lines:
        _emit_truncation_event(truncated_lines, limit)
    return merged


def load_guardian_monitor_codes(*, max_symbols: int) -> list[str]:
    """兼容入口：交易模式（1m 持仓做T + 5m must_pool 开新仓）并集。"""

    return load_monitor_codes(
        trading_mode=True,
        screening_mode=False,
        max_symbols=max_symbols,
    )


def load_clx_monitor_codes(*, max_symbols: int) -> list[str]:
    """兼容入口：选股模式（15/30 CLX 选股）代码池。"""

    return load_line_codes(line=LINE_15_30_CLX, max_symbols=max_symbols)


def _normalize_symbol_limit(max_symbols: int) -> int:
    try:
        limit = int(max_symbols or 60)
    except Exception:
        limit = 60
    if limit <= 0:
        limit = 60
    return limit


def _load_holding_codes(limit: int) -> list[str]:
    """line_1m_t：仅持仓（xt_positions），1m 做T。"""

    codes: set[str] = set()
    for doc in DBfreshquant["xt_positions"].find(
        {}, {"stock_code": 1, "code": 1, "symbol": 1}
    ):
        raw = doc.get("stock_code") or doc.get("code") or doc.get("symbol") or ""
        norm = normalize_prefixed_code(str(raw)).lower()
        if norm:
            codes.add(norm)
    return sorted(c for c in codes if len(c) >= 8)[:limit]


def _load_must_pool_codes(limit: int) -> list[str]:
    """line_5m_new_open：must_pool 且未持仓，5m 开新仓。"""

    holding_codes = _load_holding_codes(limit)
    codes: set[str] = set()
    for doc in DBfreshquant["must_pool"].find(
        {"instrument_type": {"$in": ["stock_cn", "etf_cn"]}, "disabled": {"$ne": True}},
        {"code": 1},
    ):
        raw = doc.get("code") or ""
        norm = normalize_prefixed_code(str(raw)).lower()
        if norm and norm not in holding_codes:
            codes.add(norm)
    return sorted(c for c in codes if len(c) >= 8)[:limit]


def _load_clx_codes(limit: int) -> list[str]:
    """line_15_30_clx：未过期 stock_pools 且未持仓，15/30 CLX 选股。"""

    holding_codes = _load_holding_codes(limit)
    codes: set[str] = set()
    now = datetime.now()
    for doc in DBfreshquant["stock_pools"].find(
        {
            "$or": [
                {"expire_at": {"$exists": False}},
                {"expire_at": None},
                {"expire_at": {"$gt": now}},
            ]
        },
        {"code": 1},
    ):
        raw = doc.get("code") or ""
        norm = normalize_prefixed_code(str(raw)).lower()
        if norm and norm not in holding_codes:
            codes.add(norm)
    return sorted(c for c in codes if len(c) >= 8)[:limit]


def _emit_truncation_event(
    truncated_lines: Iterable[dict[str, object]],
    limit: int,
) -> None:
    try:
        from freshquant.runtime_observability.logger import RuntimeEventLogger

        logger.warning(
            "[Pools] monitor codes truncated at max_symbols=%d: %s",
            limit,
            ",".join(
                f"{item.get('line')}={item.get('truncated_count')}"
                for item in truncated_lines
            ),
        )
        RuntimeEventLogger("xt_pools").emit(
            {
                "component": "xt_pools",
                "node": "line_codes_truncated",
                "reason_code": "line_codes_truncated",
                "max_symbols": limit,
                "truncated_lines": [dict(item) for item in truncated_lines],
            }
        )
    except Exception:  # pragma: no cover - 告警路径失败不影响装配
        logger.exception("[Pools] failed to emit line_codes_truncated event")


__all__ = [
    "LINE_1M_T",
    "LINE_5M_NEW_OPEN",
    "LINE_15_30_CLX",
    "LINE_PRIORITY_ORDER",
    "lines_for_modes",
    "load_line_codes",
    "load_monitor_codes",
    "load_guardian_monitor_codes",
    "load_clx_monitor_codes",
    "migrate_xtdata_mode",
    "normalize_xtdata_mode",
    "xtdata_mode_enables_guardian",
    "xtdata_mode_enables_clx",
]
