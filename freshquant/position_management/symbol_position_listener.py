# -*- coding: utf-8 -*-

from __future__ import annotations

import json

from freshquant.market_data.xtdata.constants import (
    REDIS_BAR_QUEUE_PREFIX,
    REDIS_QUEUE_SHARDS,
)
from freshquant.market_data.xtdata.schema import BarCloseEvent
from freshquant.position_management.symbol_position_service import (
    SingleSymbolPositionService,
)

try:
    from freshquant.database.redis import redis_db  # type: ignore
except Exception:  # pragma: no cover
    redis_db = None  # type: ignore


class SingleSymbolPositionListener:
    def __init__(self, *, service=None, redis_client=None, queue_keys=None, timeout=5):
        self.service = service or SingleSymbolPositionService()
        self.redis_client = redis_client or redis_db
        self.queue_keys = queue_keys or [
            f"{REDIS_BAR_QUEUE_PREFIX}:{index}"
            for index in range(int(REDIS_QUEUE_SHARDS))
        ]
        self.timeout = max(int(timeout or 0), 1)

    def listen_once(self):
        if self.redis_client is None:  # pragma: no cover
            raise RuntimeError("redis client unavailable")
        item = self.redis_client.blpop(self.queue_keys, timeout=self.timeout)
        if not item:
            return None
        _key, raw = item
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        payload = json.loads(raw)
        payload.setdefault("event", "BAR_CLOSE")
        event = BarCloseEvent.from_dict(payload)
        if event.period != "1min":
            return None
        return self.service.refresh_from_bar_close(event)

    def run_forever(self):
        self.service.refresh_all_from_positions()
        while True:
            self.listen_once()
