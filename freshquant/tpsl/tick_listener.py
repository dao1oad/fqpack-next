# -*- coding: utf-8 -*-

from __future__ import annotations

import json

import click

from freshquant.market_data.xtdata.constants import (
    REDIS_QUEUE_SHARDS,
    REDIS_TICK_QUEUE_PREFIX,
)
from freshquant.market_data.xtdata.schema import TickQuoteEvent
from freshquant.tpsl.consumer import TpslTickConsumer

try:
    from freshquant.database.redis import redis_db  # type: ignore
except Exception:  # pragma: no cover
    redis_db = None  # type: ignore


class TickQuoteListener:
    def __init__(self, callback, *, redis_client=None, queue_keys=None, timeout=5):
        self.callback = callback
        self.redis_client = redis_client or redis_db
        self.queue_keys = queue_keys or [
            f"{REDIS_TICK_QUEUE_PREFIX}:{index}"
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
        payload.setdefault("event", "TICK_QUOTE")
        event = TickQuoteEvent.from_dict(payload)
        self.callback(event)
        return event

    def run_forever(self):
        while True:
            self.listen_once()


@click.command()
def main():
    consumer = TpslTickConsumer()
    listener = TickQuoteListener(consumer.handle_tick)
    listener.run_forever()


if __name__ == "__main__":
    main()
