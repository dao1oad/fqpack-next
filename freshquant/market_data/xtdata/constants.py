# -*- coding: utf-8 -*-

from __future__ import annotations

import zlib

REDIS_BAR_QUEUE_PREFIX = "QUEUE:BAR_CLOSE"
REDIS_QUEUE_PREFIX = REDIS_BAR_QUEUE_PREFIX
REDIS_TICK_QUEUE_PREFIX = "QUEUE:TICK_QUOTE"
REDIS_QUEUE_SHARDS = 4


def shard_for_code(code: str, *, shards: int = REDIS_QUEUE_SHARDS) -> int:
    if shards <= 1:
        return 0
    text = (code or "").encode("utf-8", errors="ignore")
    return int(zlib.crc32(text) % shards)


def queue_key_for_code(code: str, *, prefix: str = REDIS_QUEUE_PREFIX) -> str:
    return f"{prefix}:{shard_for_code(code)}"


def tick_queue_key_for_code(code: str) -> str:
    return queue_key_for_code(code, prefix=REDIS_TICK_QUEUE_PREFIX)
