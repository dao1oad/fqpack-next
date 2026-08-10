# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import logging
import time
import traceback

import click

from freshquant.database.dependency_retry import is_retryable_connection_error
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

logger = logging.getLogger(__name__)

DEFAULT_RECONNECT_DELAY_S = 5.0
DEFAULT_RECONNECT_DELAY_MAX_S = 60.0


class TickQuoteListener:
    def __init__(self, callback, *, redis_client=None, queue_keys=None, timeout=5):
        self.callback = callback
        self.redis_client = redis_client or redis_db
        self.queue_keys = queue_keys or [
            f"{REDIS_TICK_QUEUE_PREFIX}:{index}"
            for index in range(int(REDIS_QUEUE_SHARDS))
        ]
        self.timeout = max(int(timeout or 0), 1)

    def _handle_item(self, item):
        """消费单条 tick；解析/回调异常 log+skip（毒消息保护）。"""
        _key, raw = item
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        payload = json.loads(raw)
        payload.setdefault("event", "TICK_QUOTE")
        event = TickQuoteEvent.from_dict(payload)
        self.callback(event)
        return event

    def _rebuild_redis_client(self) -> None:
        """断开旧连接池并按 bootstrap 配置重建 client（退避重连）。"""
        try:
            if self.redis_client is not None:
                self.redis_client.connection_pool.disconnect()
        except Exception:  # pragma: no cover
            pass
        try:
            import redis as redis_lib  # type: ignore

            from freshquant.bootstrap_config import bootstrap_config

            pool = redis_lib.ConnectionPool(
                host=bootstrap_config.redis.host,
                port=bootstrap_config.redis.port,
                db=bootstrap_config.redis.db,
                password=(bootstrap_config.redis.password or None),
                decode_responses=True,
            )
            self.redis_client = redis_lib.StrictRedis(connection_pool=pool)
        except Exception as exc:  # pragma: no cover
            logger.error("tpsl redis client rebuild failed: %s", exc)
            self.redis_client = None

    def run_forever(self):
        reconnect_delay = DEFAULT_RECONNECT_DELAY_S
        while True:
            try:
                if self.redis_client is None:
                    self._rebuild_redis_client()
                    if self.redis_client is None:
                        raise RuntimeError("redis client unavailable")
                item = self.redis_client.blpop(self.queue_keys, timeout=self.timeout)
                reconnect_delay = DEFAULT_RECONNECT_DELAY_S
                if not item:
                    continue
                self._handle_item(item)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                if is_retryable_connection_error(exc):
                    logger.warning(
                        "tpsl redis connection error; reconnecting in %.1f seconds: %s",
                        reconnect_delay,
                        exc,
                    )
                    self._rebuild_redis_client()
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(
                        reconnect_delay * 2.0, DEFAULT_RECONNECT_DELAY_MAX_S
                    )
                else:
                    logger.error("tpsl listener loop error: %s", exc)
                    logger.debug(traceback.format_exc())
                    time.sleep(1.0)


@click.command()
def main():
    consumer = TpslTickConsumer()
    listener = TickQuoteListener(consumer.handle_tick)
    listener.run_forever()


if __name__ == "__main__":
    main()
