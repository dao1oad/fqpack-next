# -*- coding: utf-8 -*-
"""双账本归属判定唯一入口（Issue #571 根治方案 v4）。

``LedgerResolver`` 是订单、entry、slice、allocation 归属判定的单一事实源：

- 订单级归属：``base`` / ``t`` / ``mixed`` / ``-``。跨 base/t 的分摊卖单
  订单级必须返回 ``mixed``，逐笔账本真值由 ``om_exit_allocations.position_type``
  表达；
- ``om_order_requests.ledger_intent`` 是订单级账本意图的唯一字段：TPSL、
  Guardian、手动/网页、stoploss 全写入方在提交时显式声明，缺失或非法时
  fail-closed（``LedgerIntentMissingError`` / ``InvalidLedgerIntentError``），
  不提供隐式默认；
- broker-only 手动买入（无请求）显式归 ``base``（A8）；
- 旧字段（``guardian_sell_sources`` / ``guardian_buy_grid`` / ``buy_ledger``）
  不再参与任何归属判定。
"""

from __future__ import annotations

from typing import Any

LEDGER_BASE = "base"
LEDGER_T = "t"
LEDGER_MIXED = "mixed"
LEDGER_UNSPECIFIED = "-"

_ALLOWED_INTENTS = {
    LEDGER_BASE,
    LEDGER_T,
    LEDGER_MIXED,
    LEDGER_UNSPECIFIED,
}

_TAKEPROFIT_SOURCES = {"tpsl_takeprofit"}
_TAKEPROFIT_SCOPE_TYPES = {"takeprofit_batch"}


class LedgerIntentMissingError(ValueError):
    """订单请求缺少必填的 ``ledger_intent``（fail-closed）。"""


class InvalidLedgerIntentError(ValueError):
    """``ledger_intent`` 值非法或与订单方向不兼容。"""


class LedgerIntentConflictError(ValueError):
    """既有 entry/slice 账本与请求意图冲突（fail-closed）。"""


def normalize_ledger_intent(value: Any) -> str | None:
    """归一化 ``ledger_intent``；缺失或非法返回 ``None``。"""

    normalized = str(value or "").strip().lower()
    if normalized in _ALLOWED_INTENTS:
        return normalized
    return None


def is_takeprofit_request(request_row: dict[str, Any] | None) -> bool:
    """TPSL 止盈卖出请求识别（#5/#7 共用，不依赖旧字段）。"""

    row = dict(request_row or {})
    source = str(row.get("source") or "").strip().lower()
    scope_type = str(row.get("scope_type") or "").strip().lower()
    if source in _TAKEPROFIT_SOURCES:
        return True
    if scope_type in _TAKEPROFIT_SCOPE_TYPES or "takeprofit_batch" in scope_type:
        return True
    return False


def ledger_from_allocations(
    exit_allocations: list[dict[str, Any]] | None,
) -> str | None:
    """按逐笔 ``om_exit_allocations.position_type`` 归并订单级账本。

    - 同时含 base 与 t → ``mixed``（分摊卖单，C1）；
    - 只含 base → ``base``；只含 t → ``t``；
    - 无分配证据 → ``None``（不推断）。
    """

    seen: set[str] = set()
    for item in list(exit_allocations or []):
        position_type = str((item or {}).get("position_type") or "").strip().lower()
        if position_type in {LEDGER_BASE, LEDGER_T}:
            seen.add(position_type)
    if LEDGER_BASE in seen and LEDGER_T in seen:
        return LEDGER_MIXED
    if LEDGER_BASE in seen:
        return LEDGER_BASE
    if LEDGER_T in seen:
        return LEDGER_T
    return None


def _require_intent(request_row: dict[str, Any] | None) -> str:
    intent = normalize_ledger_intent((request_row or {}).get("ledger_intent"))
    if intent is None:
        raise LedgerIntentMissingError(
            "ledger_intent is required on om_order_requests (fail-closed); "
            "run script/maintenance/backfill_ledger_intent.py first"
        )
    return intent


def resolve_order_ledger(
    *,
    side: str | None,
    request_row: dict[str, Any] | None = None,
    broker_only: bool = False,
    exit_allocations: list[dict[str, Any]] | None = None,
) -> str:
    """订单级账本归属唯一入口。

    - 买（``buy``）：broker-only → ``base``；否则按 ``ledger_intent``
      （``base`` / ``t``），缺失或非法 fail-closed；
    - 卖（``sell``）：分摊卖单（分配证据跨 base/t）→ ``mixed``；broker-only
      → 分配证据或 ``-``；否则按 ``ledger_intent``（``base`` / ``t`` /
      ``-`` / ``mixed``），缺失 fail-closed；
    - 其余方向 → ``-``。
    """

    normalized_side = str(side or "").strip().lower()
    if normalized_side == "buy":
        if broker_only:
            return LEDGER_BASE
        intent = _require_intent(request_row)
        if intent == LEDGER_BASE:
            return LEDGER_BASE
        if intent == LEDGER_T:
            return LEDGER_T
        raise InvalidLedgerIntentError(
            f"buy ledger_intent must be base or t, got {intent!r}"
        )
    if normalized_side == "sell":
        alloc_ledger = ledger_from_allocations(exit_allocations)
        if alloc_ledger == LEDGER_MIXED:
            return LEDGER_MIXED
        if broker_only:
            return alloc_ledger or LEDGER_UNSPECIFIED
        intent = _require_intent(request_row)
        if intent == LEDGER_BASE:
            return LEDGER_BASE
        if intent == LEDGER_T:
            return LEDGER_T
        if intent == LEDGER_MIXED:
            return LEDGER_MIXED
        if intent == LEDGER_UNSPECIFIED:
            return alloc_ledger or LEDGER_UNSPECIFIED
        raise InvalidLedgerIntentError(f"sell ledger_intent is invalid: {intent!r}")
    return LEDGER_UNSPECIFIED


def resolve_buy_position_type(
    *,
    request_row: dict[str, Any] | None = None,
    broker_only: bool = False,
) -> str:
    """buy entry / slice 级 ``position_type`` 唯一入口（#2/#3/#8）。"""

    if broker_only:
        return LEDGER_BASE
    intent = _require_intent(request_row)
    if intent == LEDGER_BASE:
        return LEDGER_BASE
    if intent == LEDGER_T:
        return LEDGER_T
    raise InvalidLedgerIntentError(
        f"buy position_type requires base or t ledger_intent, got {intent!r}"
    )


__all__ = [
    "InvalidLedgerIntentError",
    "LEDGER_BASE",
    "LEDGER_MIXED",
    "LEDGER_T",
    "LEDGER_UNSPECIFIED",
    "LedgerIntentConflictError",
    "LedgerIntentMissingError",
    "is_takeprofit_request",
    "ledger_from_allocations",
    "normalize_ledger_intent",
    "resolve_buy_position_type",
    "resolve_order_ledger",
]
