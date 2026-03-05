# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass


PUBSUB_CHANNEL = "CHANNEL:BAR_UPDATE"

CACHE_KLINE_PREFIX = "CACHE:KLINE"


def to_backend_period(period: str) -> str:
    """
    Normalize period to backend format:
    - frontend: 1m/5m/15m/30m
    - backend:  1min/5min/15min/30min
    """
    p = (period or "").strip().lower()
    if not p:
        return p
    if p.endswith("min"):
        return p
    if p.endswith("m"):
        return f"{p[:-1]}min"
    if p == "1minute":
        return "1min"
    return p


def to_frontend_period(period: str) -> str:
    """
    Normalize period to frontend format:
    - backend:  1min/5min/15min/30min
    - frontend: 1m/5m/15m/30m
    """
    p = (period or "").strip().lower()
    if not p:
        return p
    if p.endswith("m") and not p.endswith("min"):
        return p
    if p.endswith("min"):
        return f"{p[:-3]}m"
    return p


def is_supported_realtime_period(period: str) -> bool:
    p = to_backend_period(period)
    return p in {"1min", "5min", "15min", "30min"}


def get_redis_cache_key(code: str, period_backend: str) -> str:
    return f"{CACHE_KLINE_PREFIX}:{(code or '').lower()}:{to_backend_period(period_backend)}"


def get_redis_queue_key(prefix: str, shard: int) -> str:
    return f"{prefix}:{int(shard)}"


@dataclass(frozen=True)
class PeriodSpec:
    backend: str

    @property
    def frontend(self) -> str:
        return to_frontend_period(self.backend)

    @property
    def seconds(self) -> int:
        p = to_backend_period(self.backend)
        if p.endswith("min"):
            try:
                return int(p[:-3]) * 60
            except Exception:
                return 0
        return 0

