# -*- coding:utf-8 -*-

from collections import defaultdict
from typing import DefaultDict

try:
    from memoizit import Memoizer as _Memoizer
except ModuleNotFoundError:

    class _Memoizer:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            self._memoized_wrappers = []

        def memoize(self, expiration=None):
            def decorator(func):
                cache = {}

                def wrapper(*args, **kwargs):
                    key = repr((args, sorted(kwargs.items())))
                    if key not in cache:
                        cache[key] = func(*args, **kwargs)
                    return cache[key]

                wrapper._memoizit_cache = cache
                self._memoized_wrappers.append(wrapper)
                return wrapper

            return decorator


Memoizer = _Memoizer

from freshquant.bootstrap_config import bootstrap_config

host = bootstrap_config.redis.host
port = bootstrap_config.redis.port
db = bootstrap_config.redis.db
password = bootstrap_config.redis.password or None

redis_cache = Memoizer(backend="redis", host=host, port=port, db=db)
in_memory_cache = Memoizer()
_cache_versions: DefaultDict[str, int] = defaultdict(int)


def get_cache_version(cache_name: str) -> int:
    return _cache_versions[cache_name]


def bump_cache_version(cache_name: str) -> int:
    _cache_versions[cache_name] += 1
    return _cache_versions[cache_name]
