# -*- coding:utf-8 -*-
"""
TDX 行情服务器 IP 池：从权威 JSON 加载，弃用 connect.cfg。

IP 池由人工维护，见 freshquant/gateway/tdx_ip_pool.json。
路径优先级：settings.tdx.ip_pool > FRESHQUANT_TDX_IP_POOL > 包内默认。
"""

import json
import os
from functools import lru_cache
from importlib.resources import files

import pydash

from freshquant.config import settings

__all__ = ["get_stock_hosts", "get_future_hosts"]

_DEFAULT_POOL = files("freshquant.gateway").joinpath("tdx_ip_pool.json")
_DEFAULT_PORT = {"stock": 7709, "future": 7727}


def _resolve_pool_path() -> str:
    """权威 JSON 路径：settings.tdx.ip_pool > env > 包内默认。"""
    return (
        pydash.get(settings, "tdx.ip_pool")
        or os.getenv("FRESHQUANT_TDX_IP_POOL")
        or str(_DEFAULT_POOL)
    )


@lru_cache(maxsize=1)
def _load_pool() -> dict:
    with open(_resolve_pool_path(), "r", encoding="utf-8") as f:
        return json.load(f)


def _hosts(key: str) -> list[dict]:
    return [
        {
            "ip": h["ip"],
            "port": int(h.get("port", _DEFAULT_PORT[key])),
            "name": h.get("name", ""),
        }
        for h in _load_pool().get(key, [])
    ]


@lru_cache(maxsize=1)
def get_stock_hosts() -> list[dict]:
    """标准行情服务器（A股/指数/ETF）。"""
    return _hosts("stock")


@lru_cache(maxsize=1)
def get_future_hosts() -> list[dict]:
    """扩展市场服务器（期货/期权）。"""
    return _hosts("future")
