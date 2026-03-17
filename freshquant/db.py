# -*- coding: utf-8 -*-

import pymongo

from freshquant.bootstrap_config import bootstrap_config
from freshquant.runtime_constants import TZ

host = bootstrap_config.mongodb.host
port = bootstrap_config.mongodb.port
db = bootstrap_config.mongodb.db
gantt_db = bootstrap_config.mongodb.gantt_db
screening_db = bootstrap_config.mongodb.screening_db
order_management_db = bootstrap_config.order_management.mongo_database

MongoClient = pymongo.MongoClient(
    host=host, port=port, connect=False, tz_aware=True, tzinfo=TZ
)
DBfreshquant = MongoClient[db]
DBGantt = MongoClient[gantt_db]
DBScreening = MongoClient[screening_db]
DBOrderManagement = MongoClient[order_management_db]
DBQuantAxis = MongoClient["quantaxis"]
DBQA = MongoClient["qa"]


def get_db(dbName):
    if dbName == "freshquant":
        return DBfreshquant
    elif dbName in {"gantt", gantt_db}:
        return DBGantt
    elif dbName in {"screening", screening_db}:
        return DBScreening
    elif dbName in {"order_management", order_management_db}:
        return DBOrderManagement
    elif dbName == "quantaxis":
        return DBQuantAxis
    elif dbName == "qa":
        return DBQA
    else:
        return MongoClient[dbName]
