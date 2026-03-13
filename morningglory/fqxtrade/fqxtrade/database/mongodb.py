import pymongo
from fqxtrade.config import cfg, settings
from pydash import get

host = get(settings, "mongodb.host", "127.0.0.1")
port = get(settings, "mongodb.port", 27027)
db = get(settings, "mongodb.db", "freshquant")

MongoClient = pymongo.MongoClient(
    host=host, port=port, connect=False, tz_aware=True, tzinfo=cfg.TZ
)
DBfreshquant = MongoClient[db]
