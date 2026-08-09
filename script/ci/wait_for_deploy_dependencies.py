# -*- coding: utf-8 -*-

"""Wait for deploy-critical host dependencies to accept TCP connections.

The host runtime restart (EnsureServiceAndRestartSurfaces) starts supervisor
programs that read Mongo / Redis / XTData at process start.  When Docker
containers are rebuilt in the same deploy window, those dependencies can be
briefly unreachable, making producer/consumer exit immediately after start
and exhausting the settle-retry budget.  This script polls the dependency
TCP ports before the host restart so programs start with dependencies ready.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from typing import Iterable

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORTS = (27027, 6380, 58610)
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 2.0


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ports = list(args.port) or list(DEFAULT_PORTS)
    result = wait_for_dependencies(
        host=args.host,
        ports=ports,
        timeout_seconds=args.timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
        connect_timeout_seconds=args.connect_timeout_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
