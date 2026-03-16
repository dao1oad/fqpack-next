from __future__ import annotations

import os
from threading import RLock
from contextlib import contextmanager
from typing import Iterator

PROXY_ENV_KEYS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "NO_PROXY",
    "no_proxy",
)

_PROXY_ENV_LOCK = RLock()


@contextmanager
def without_proxy_env(keys: tuple[str, ...] = PROXY_ENV_KEYS) -> Iterator[None]:
    with _PROXY_ENV_LOCK:
        original = [(key, os.environ.get(key)) for key in keys]
        for key, _ in original:
            os.environ.pop(key, None)
        try:
            yield
        finally:
            if os.name == "nt":
                restored: dict[str, str] = {}
                for key, value in original:
                    if value is not None:
                        restored[key.upper()] = value
                for key, _ in original:
                    os.environ.pop(key, None)
                for key, value in restored.items():
                    os.environ[key] = value
            else:
                for key, value in original:
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


def clear_proxy_env_for_current_process(keys: tuple[str, ...] = PROXY_ENV_KEYS) -> None:
    for key in keys:
        os.environ.pop(key, None)
