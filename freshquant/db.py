# -*- coding: utf-8 -*-

import pymongo
from pydash import get

from freshquant.carnation.config import TZ
from freshquant.config import settings

host = get(settings, "mongodb.host", "127.0.0.1")
port = get(settings, "mongodb.port", 27017)
db = get(settings, "mongodb.db", "freshquant")

MongoClient = pymongo.MongoClient(
    host=host, port=port, connect=False, tz_aware=True, tzinfo=TZ
)
DBfreshquant = MongoClient[db]
DBQuantAxis = MongoClient["quantaxis"]
DBQA = MongoClient["qa"]


def get_db(dbName):
    if dbName == "freshquant":
        return DBfreshquant
    elif dbName == "quantaxis":
        return DBQuantAxis
    elif dbName == "qa":
        return DBQA
    else:
        return MongoClient[dbName]
