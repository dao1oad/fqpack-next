# -*- coding:utf-8 -*-

from memoizit import Memoizer
from pydash import get

from freshquant.config import settings

host = get(settings, 'redis.host', '127.0.0.1')
port = get(settings, 'redis.port', 6379)
db = get(settings, 'redis.db', 1)
password = get(settings, 'redis.password')

redis_cache = Memoizer(backend="redis", host=host, port=port, db=db)
in_memory_cache = Memoizer()
