from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_PORTS = {"stock": 7709, "future": 7727}
_POOL_PATH = Path(__file__).with_name("tdx_ip_pool.json")


def load_tdx_ip_pool(
    kind: str, pool_path: str | Path | None = None
) -> list[dict] | None:
    path = Path(pool_path) if pool_path is not None else _POOL_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    default_port = _DEFAULT_PORTS.get(str(kind), 7709)
    hosts = []
    for item in payload.get(str(kind)) or []:
        if not isinstance(item, dict):
            continue
        ip = str(item.get("ip") or "").strip()
        if not ip:
            continue
        try:
            port = int(item.get("port") or default_port)
        except (TypeError, ValueError):
            port = default_port
        host = {"ip": ip, "port": port}
        name = str(item.get("name") or "").strip()
        if name:
            host["name"] = name
        hosts.append(host)
    return hosts or None
