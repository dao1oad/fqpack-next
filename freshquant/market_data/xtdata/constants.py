# -*- coding: utf-8 -*-

from __future__ import annotations

import zlib


REDIS_QUEUE_PREFIX = "QUEUE:BAR_CLOSE"
REDIS_QUEUE_SHARDS = 4


def shard_for_code(code: str, *, shards: int = REDIS_QUEUE_SHARDS) -> int:
    if shards <= 1:
        return 0
    text = (code or "").encode("utf-8", errors="ignore")
    return int(zlib.crc32(text) % shards)


def queue_key_for_code(code: str) -> str:
    return f"{REDIS_QUEUE_PREFIX}:{shard_for_code(code)}"

