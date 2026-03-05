import pymongo
from pydash import get
from fqxtrade.config import settings, cfg

host = get(settings, "mongodb.host", "127.0.0.1")
port = get(settings, "mongodb.port", 27017)
db = get(settings, "mongodb.db", "freshquant")

MongoClient = pymongo.MongoClient(
    host=host, port=port, connect=False, tz_aware=True, tzinfo=cfg.TZ
)
DBfreshquant = MongoClient[db]
