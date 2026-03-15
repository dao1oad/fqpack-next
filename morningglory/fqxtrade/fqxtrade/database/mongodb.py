import pymongo
from typing import Any

from fqxtrade.config import cfg, settings
from pydash import get

try:
    from freshquant.bootstrap_config import bootstrap_config as _bootstrap_config
except Exception:  # pragma: no cover - fallback for standalone fqxtrade
    _bootstrap_config: Any | None = None


def _resolve_mongodb_setting(key, default=None):
    if _bootstrap_config is not None:
        mongodb_settings = getattr(_bootstrap_config, "mongodb", None)
        if mongodb_settings is not None:
            value = getattr(mongodb_settings, key, None)
            if value is not None:
                return value
    return get(settings, f"mongodb.{key}", default)


host = _resolve_mongodb_setting("host", "127.0.0.1")
port = _resolve_mongodb_setting("port", 27027)
db = _resolve_mongodb_setting("db", "freshquant")

MongoClient = pymongo.MongoClient(
    host=host, port=port, connect=False, tz_aware=True, tzinfo=cfg.TZ
)
DBfreshquant = MongoClient[db]
