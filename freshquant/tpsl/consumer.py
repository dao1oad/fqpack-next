# -*- coding: utf-8 -*-

from __future__ import annotations

import time
from datetime import datetime
from datetime import time as time_of_day
from datetime import timezone
from zoneinfo import ZoneInfo

from freshquant.market_data.xtdata.schema import TickQuoteEvent, normalize_prefixed_code
from freshquant.runtime_observability.failures import (
    build_exception_payload,
    is_exception_emitted,
    mark_exception_emitted,
)
from freshquant.runtime_observability.logger import RuntimeEventLogger
from freshquant.tpsl.pools import load_active_buy_line_codes, load_active_tpsl_codes
from freshquant.tpsl.service import TpslService
from freshquant.util.code import normalize_to_base_code

_BEIJING_TZ = ZoneInfo("Asia/Shanghai")
_CONTINUOUS_AUCTION_START = time_of_day(9, 30)


class TpslTickConsumer:
    def __init__(
        self,
        *,
        service=None,
        universe_loader=None,
        buy_line_universe_loader=None,
        refresh_interval_s=30,
        runtime_logger=None,
        now_provider=None,
    ):
        self.service = service or TpslService()
        self.universe_loader = universe_loader or load_active_tpsl_codes
        self.buy_line_universe_loader = (
            buy_line_universe_loader or load_active_buy_line_codes
        )
        self.refresh_interval_s = max(float(refresh_interval_s or 0), 0.0)
        self.active_codes = set()
        self.active_buy_line_codes = set()
        self._last_refresh_at = 0.0
        self.runtime_logger = runtime_logger or _get_runtime_logger()
        self.now_provider = now_provider or time.time

    def refresh_universe(self, *, force=False):
        now = time.time()
        if (
            not force
            and self.refresh_interval_s > 0
            and self._last_refresh_at > 0
            and (now - self._last_refresh_at) < self.refresh_interval_s
        ):
            return self.active_codes
        self.active_codes = {
            normalize_prefixed_code(code).lower()
            for code in (self.universe_loader() or [])
            if code
        }
        self.active_buy_line_codes = {
            normalize_prefixed_code(code).lower()
            for code in (self.buy_line_universe_loader() or [])
            if code
        }
        self._last_refresh_at = now
        return self.active_codes

    def handle_tick(self, raw):
        event = _coerce_tick_event(raw)
        if event is None:
            return None

        symbol = normalize_to_base_code(event.code)
        try:
            if _is_before_continuous_auction(event, now_provider=self.now_provider):
                return None
            active_codes = self.refresh_universe()
            # #549 双集合：买入线 universe 与止盈 universe 隔离，
            # 任一集合命中即可进入对应评估。
            if (
                event.code not in active_codes
                and event.code not in self.active_buy_line_codes
            ):
                return None
            invalid_reason = _invalid_tick_reason(event)
            if invalid_reason is not None:
                # 失败语义契约（根②）：有效 tick = 时间合法 + bid1/ask1/last 均 >0；
                # 不满足不进交易链（止损路径已随 #603 下线，门槛保留给
                # TP/买入线评估与事件层通用卫生）。门槛置于 universe 匹配之后，
                # 避免对非关注标的的无效 tick 逐条落事件。
                self._emit_runtime(
                    "tick_gate",
                    symbol=symbol,
                    status="skipped",
                    reason_code=invalid_reason,
                    payload={
                        "bid1": event.bid1,
                        "ask1": event.ask1,
                        "last_price": event.last_price,
                        "tick_time": event.tick_time,
                    },
                )
                return None
            # #549：买入线评估插入点在 TP 评估之前。买入线不是本 tick 的终态——
            # 仅返回 ready 才提交买单并终止本 tick；skipped 时双集合标的
            # （同时命中止盈 universe active_codes）继续评估止盈，
            # buy-line-only 标的本 tick 终止（保持双集合隔离）。
            if event.code in self.active_buy_line_codes:
                buy_line_batch = self.service.evaluate_base_buyline(
                    symbol=symbol,
                    code=event.code,
                    bid1=event.bid1,
                    last_price=event.last_price,
                    tick_time=event.tick_time,
                )
                if buy_line_batch and buy_line_batch.get("status") == "ready":
                    return self.service.submit_base_buy_batch(
                        buy_line_batch,
                        trace_id=None,
                    )
                if event.code not in self.active_codes:
                    return None
            takeprofit_batch = self.service.evaluate_takeprofit(
                symbol=symbol,
                code=event.code,
                ask1=event.ask1,
                bid1=event.bid1,
                last_price=event.last_price,
                tick_time=event.tick_time,
            )
            if takeprofit_batch:
                if takeprofit_batch.get("status") != "ready":
                    return takeprofit_batch
                return self.service.submit_takeprofit_batch(takeprofit_batch)

            return None
        except Exception as exc:
            if not is_exception_emitted(exc):
                self._emit_runtime(
                    "tick_match",
                    symbol=symbol,
                    status="error",
                    payload=build_exception_payload(exc),
                )
                mark_exception_emitted(exc)
            raise

    def _emit_runtime(
        self,
        node,
        *,
        symbol,
        trace_id=None,
        status="info",
        reason_code="",
        payload=None,
    ):
        event = {
            "component": "tpsl_worker",
            "node": node,
            "trace_id": trace_id,
            "symbol": symbol,
            "status": status,
            "reason_code": reason_code,
            "payload": dict(payload or {}),
        }
        try:
            self.runtime_logger.emit(event)
        except Exception:
            return


def _coerce_tick_event(raw):
    if isinstance(raw, TickQuoteEvent):
        return raw
    if not isinstance(raw, dict):
        return None
    payload = dict(raw)
    payload.setdefault("event", "TICK_QUOTE")
    return TickQuoteEvent.from_dict(payload)


def _is_before_continuous_auction(event, *, now_provider) -> bool:
    event_time = _resolve_event_time(event, now_provider=now_provider)
    return event_time.time() < _CONTINUOUS_AUCTION_START


def _invalid_tick_reason(event) -> str | None:
    """返回无效 tick 的 reason_code；有效 tick 返回 None。"""

    if _coerce_timestamp(getattr(event, "tick_time", None)) is None:
        return "invalid_tick_time"
    for field_name, value in (
        ("bid1", event.bid1),
        ("ask1", event.ask1),
        ("last_price", event.last_price),
    ):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "invalid_tick_quote"
        if not (numeric > 0):
            return "invalid_tick_quote"
    return None


def _resolve_event_time(event, *, now_provider) -> datetime:
    for raw in (getattr(event, "tick_time", None), getattr(event, "created_at", None)):
        dt = _coerce_timestamp(raw)
        if dt is not None:
            return dt
    return _coerce_timestamp(now_provider()) or datetime.now(_BEIJING_TZ)


def _coerce_timestamp(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw if raw.tzinfo is not None else raw.replace(tzinfo=_BEIJING_TZ)
        return dt.astimezone(_BEIJING_TZ)
    try:
        timestamp = float(raw)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    if timestamp >= 1_000_000_000_000:
        timestamp = timestamp / 1000.0
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(_BEIJING_TZ)


_runtime_logger = None


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        _runtime_logger = RuntimeEventLogger("tpsl_worker")
    return _runtime_logger
