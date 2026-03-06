# -*- coding:utf-8 -*-

from collections import defaultdict

try:
    from memoizit import Memoizer
except ModuleNotFoundError:
    class Memoizer:
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

from pydash import get

from freshquant.config import settings

host = get(settings, 'redis.host', '127.0.0.1')
port = get(settings, 'redis.port', 6379)
db = get(settings, 'redis.db', 1)
password = get(settings, 'redis.password')

redis_cache = Memoizer(backend="redis", host=host, port=port, db=db)
in_memory_cache = Memoizer()
_cache_versions = defaultdict(int)


def get_cache_version(cache_name: str) -> int:
    return _cache_versions[cache_name]


def bump_cache_version(cache_name: str) -> int:
    _cache_versions[cache_name] += 1
    return _cache_versions[cache_name]
