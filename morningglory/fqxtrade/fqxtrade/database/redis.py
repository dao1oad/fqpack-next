import redis
from pydash import get

from fqxtrade.config import settings

try:
    from freshquant.bootstrap_config import bootstrap_config as _bootstrap_config
except Exception:  # pragma: no cover - fallback for standalone fqxtrade
    _bootstrap_config = None


def _resolve_redis_setting(key, default=None):
    if _bootstrap_config is not None:
        redis_settings = getattr(_bootstrap_config, "redis", None)
        if redis_settings is not None:
            value = getattr(redis_settings, key, None)
            if value is not None:
                return value
    return get(settings, f"redis.{key}", default)


host = _resolve_redis_setting("host", "127.0.0.1")
port = _resolve_redis_setting("port", 6379)
db = _resolve_redis_setting("db", 1)
password = _resolve_redis_setting("password")

redis_connection_pool = redis.ConnectionPool(host=host, port=port, db=db, password=password, decode_responses=True)
redis_db = redis.StrictRedis(connection_pool=redis_connection_pool)
