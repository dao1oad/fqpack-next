# -*- coding: utf-8 -*-

"""Wait for deploy-critical host dependencies to be application-ready.

The host runtime restart (EnsureServiceAndRestartSurfaces) starts supervisor
programs that read Mongo / Redis / XTData at process start.  When Docker
containers are rebuilt in the same deploy window, those dependencies can be
briefly unreachable, making producer/consumer exit immediately after start
and exhausting the settle-retry budget.  This script polls dependencies
before the host restart so programs start with dependencies ready.

Readiness semantics (P1-A):
- Mongo: TCP connect + ``ping`` command (pymongo available).
- Redis: TCP connect + SET/DEL writable probe (tpsl/producer are writers;
  plain ping cannot detect MISCONF / read-only / OOM).
- XTData: TCP connect + stable window (N consecutive successful polls).
- ``--port`` fallback: when explicit ports are supplied, degrade to pure
  TCP probing (backward compatible).

This probe reduces the race window; it is not a proof that application
consumers are fully ready (XTData subscribe failures are covered by the
producer-side unbounded backoff).
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from typing import Any, Iterable

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORTS = (27027, 6380, 58610)
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 2.0
DEFAULT_STABLE_WINDOW = 3
DEFAULT_MONGO_PORT = 27027
DEFAULT_REDIS_PORT = 6380
DEFAULT_REDIS_DB = 1
DEFAULT_XTDATA_PORT = 58610


def _port_ready(host: str, port: int, connect_timeout_seconds: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=connect_timeout_seconds):
            return True
    except OSError:
        return False


def wait_for_dependencies(
    *,
    host: str,
    ports: Iterable[int],
    timeout_seconds: float,
    poll_interval_seconds: float,
    connect_timeout_seconds: float,
) -> dict[str, object]:
    normalized_ports = [int(port) for port in ports]
    deadline = time.time() + float(timeout_seconds)
    last_unready = list(normalized_ports)
    while time.time() < deadline:
        unready = [
            port
            for port in normalized_ports
            if not _port_ready(host, port, connect_timeout_seconds)
        ]
        last_unready = unready
        if not unready:
            return {
                "ok": True,
                "host": host,
                "ports": normalized_ports,
                "ready": True,
                "elapsed_seconds": round(
                    float(timeout_seconds) - max(deadline - time.time(), 0.0),
                    2,
                ),
            }
        time.sleep(poll_interval_seconds)
    return {
        "ok": False,
        "host": host,
        "ports": normalized_ports,
        "ready": False,
        "unready_ports": last_unready,
        "timeout_seconds": float(timeout_seconds),
    }


def _mongo_ping_or_none(
    host: str, port: int, connect_timeout_seconds: float
) -> bool | None:
    """Mongo ping；pymongo 不可用时返回 None（由调用方回退 TCP）。"""
    try:
        from pymongo import MongoClient  # type: ignore
    except Exception:
        return None
    try:
        client = MongoClient(
            host=host,
            port=int(port),
            serverSelectionTimeoutMS=max(int(connect_timeout_seconds * 1000), 500),
        )
        try:
            return bool(client.admin.command("ping").get("ok") == 1.0)
        finally:
            client.close()
    except Exception:
        return False


def _redis_write_probe_or_none(
    host: str, port: int, connect_timeout_seconds: float, db: int = DEFAULT_REDIS_DB
) -> bool | None:
    """Redis 可写探针（SET + DEL）；redis 库不可用时返回 None（回退 TCP）。"""
    try:
        import redis as redis_lib  # type: ignore
    except Exception:
        return None
    try:
        client = redis_lib.Redis(
            host=host,
            port=int(port),
            db=int(db),
            socket_connect_timeout=connect_timeout_seconds,
            socket_timeout=connect_timeout_seconds,
            decode_responses=True,
        )
        probe_key = "fqnext:deploy-readiness-probe"
        try:
            return bool(client.set(probe_key, "1", ex=30)) and bool(
                client.delete(probe_key)
            )
        finally:
            client.close()
    except Exception:
        return False


def wait_for_app_ready(
    *,
    host: str,
    mongo_port: int = DEFAULT_MONGO_PORT,
    redis_port: int = DEFAULT_REDIS_PORT,
    xtdata_port: int = DEFAULT_XTDATA_PORT,
    redis_db: int = DEFAULT_REDIS_DB,
    enable_mongo_ping: bool = True,
    enable_redis_write: bool = True,
    stable_window: int = DEFAULT_STABLE_WINDOW,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """应用级就绪探测：Mongo ping / Redis 可写 / XTData TCP+稳定窗口。

    探测类型不可用（缺库）时自动回退到 TCP 端口级判定。
    """
    stable_window = max(int(stable_window or 0), 1)
    targets: list[dict[str, Any]] = [
        {
            "name": "mongo",
            "port": int(mongo_port),
            "probe": _mongo_ping_or_none if enable_mongo_ping else None,
            "probe_type": "mongo_ping" if enable_mongo_ping else "tcp",
            "stable_hits": 0,
        },
        {
            "name": "redis",
            "port": int(redis_port),
            "probe": (
                lambda h, p, t: (
                    _redis_write_probe_or_none(h, p, t, db=redis_db)
                    if enable_redis_write
                    else None
                )
            ),
            "probe_type": "redis_write" if enable_redis_write else "tcp",
            "stable_hits": 0,
        },
        {
            "name": "xtdata",
            "port": int(xtdata_port),
            "probe": None,
            "probe_type": f"tcp_stable_{stable_window}",
            "stable_hits": 0,
        },
    ]
    deadline = time.time() + float(timeout_seconds)
    last_unready: list[str] = []
    details: dict[str, dict[str, object]] = {}
    while time.time() < deadline:
        unready: list[str] = []
        for target in targets:
            name = str(target["name"])
            port = int(target["port"])
            tcp_ok = _port_ready(host, port, connect_timeout_seconds)
            probe = target["probe"]
            ok = tcp_ok
            probe_type = str(target["probe_type"])
            if tcp_ok and callable(probe):
                probe_result = probe(host, port, connect_timeout_seconds)
                if probe_result is not None:
                    ok = bool(probe_result)
                    probe_type = "mongo_ping" if name == "mongo" else "redis_write"
            if name == "xtdata":
                if ok:
                    target["stable_hits"] = int(target["stable_hits"]) + 1
                    ok = int(target["stable_hits"]) >= stable_window
                else:
                    target["stable_hits"] = 0
            if not ok:
                unready.append(name)
            details[name] = {
                "port": port,
                "probe": probe_type,
                "ready": bool(ok),
            }
        last_unready = unready
        if not unready:
            return {
                "ok": True,
                "host": host,
                "ready": True,
                "details": details,
                "elapsed_seconds": round(
                    float(timeout_seconds) - max(deadline - time.time(), 0.0),
                    2,
                ),
            }
        time.sleep(poll_interval_seconds)
    return {
        "ok": False,
        "host": host,
        "ready": False,
        "details": details,
        "unready": last_unready,
        "timeout_seconds": float(timeout_seconds),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wait for host deploy dependencies (Mongo / Redis / XTData)."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Dependency host.")
    parser.add_argument(
        "--port",
        action="append",
        type=int,
        default=[],
        help="TCP port to probe (repeatable).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Total wait budget in seconds.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help="Poll interval in seconds.",
    )
    parser.add_argument(
        "--connect-timeout-seconds",
        type=float,
        default=DEFAULT_CONNECT_TIMEOUT_SECONDS,
        help="Per-probe connect timeout in seconds.",
    )
    parser.add_argument(
        "--mongo-ping",
        action="store_true",
        default=True,
        help="Probe Mongo with ping command (default: on).",
    )
    parser.add_argument(
        "--no-mongo-ping",
        action="store_false",
        dest="mongo_ping",
        help="Disable Mongo ping; TCP only.",
    )
    parser.add_argument(
        "--redis-write",
        action="store_true",
        default=True,
        help="Probe Redis with SET/DEL writable probe (default: on).",
    )
    parser.add_argument(
        "--no-redis-write",
        action="store_false",
        dest="redis_write",
        help="Disable Redis writable probe; TCP only.",
    )
    parser.add_argument(
        "--redis-db",
        type=int,
        default=DEFAULT_REDIS_DB,
        help="Redis logical database for the writable probe.",
    )
    parser.add_argument(
        "--stable-window",
        type=int,
        default=DEFAULT_STABLE_WINDOW,
        help="Consecutive successful XTData TCP polls required.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ports = list(args.port) or list(DEFAULT_PORTS)
    if args.port:
        # 显式 --port 时退化为纯 TCP 探测（兜底路径）。
        result = wait_for_dependencies(
            host=args.host,
            ports=ports,
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            connect_timeout_seconds=args.connect_timeout_seconds,
        )
    else:
        result = wait_for_app_ready(
            host=args.host,
            mongo_port=DEFAULT_MONGO_PORT,
            redis_port=DEFAULT_REDIS_PORT,
            xtdata_port=DEFAULT_XTDATA_PORT,
            redis_db=args.redis_db,
            enable_mongo_ping=bool(args.mongo_ping),
            enable_redis_write=bool(args.redis_write),
            stable_window=args.stable_window,
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            connect_timeout_seconds=args.connect_timeout_seconds,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
