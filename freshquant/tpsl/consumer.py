# -*- coding: utf-8 -*-

from __future__ import annotations

import time

from freshquant.market_data.xtdata.schema import TickQuoteEvent, normalize_prefixed_code
from freshquant.tpsl.pools import load_active_tpsl_codes
from freshquant.tpsl.service import TpslService
from freshquant.util.code import normalize_to_base_code


class TpslTickConsumer:
    def __init__(
        self,
        *,
        service=None,
        universe_loader=None,
        refresh_interval_s=30,
    ):
        self.service = service or TpslService()
        self.universe_loader = universe_loader or load_active_tpsl_codes
        self.refresh_interval_s = max(float(refresh_interval_s or 0), 0.0)
        self.active_codes = set()
        self._last_refresh_at = 0.0

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
        self._last_refresh_at = now
        return self.active_codes

    def handle_tick(self, raw):
        event = _coerce_tick_event(raw)
        if event is None:
            return None

        active_codes = self.refresh_universe()
        if event.code not in active_codes:
            return None

        symbol = normalize_to_base_code(event.code)
        takeprofit_batch = self.service.evaluate_takeprofit(
            symbol=symbol,
            code=event.code,
            ask1=event.ask1,
            bid1=event.bid1,
            last_price=event.last_price,
            tick_time=event.tick_time,
        )
        if takeprofit_batch:
            if takeprofit_batch.get("status") == "blocked":
                return takeprofit_batch
            return self.service.submit_takeprofit_batch(takeprofit_batch)

        stoploss_batch = self.service.evaluate_stoploss(
            symbol=symbol,
            code=event.code,
            bid1=event.bid1,
            ask1=event.ask1,
            last_price=event.last_price,
            tick_time=event.tick_time,
        )
        if stoploss_batch:
            if stoploss_batch.get("status") == "blocked":
                return stoploss_batch
            return self.service.submit_stoploss_batch(stoploss_batch)
        return None


def _coerce_tick_event(raw):
    if isinstance(raw, TickQuoteEvent):
        return raw
    if not isinstance(raw, dict):
        return None
    payload = dict(raw)
    payload.setdefault("event", "TICK_QUOTE")
    return TickQuoteEvent.from_dict(payload)
