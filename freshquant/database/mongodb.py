# -*- coding: utf-8 -*-

import pymongo
from pydash import get

from freshquant.carnation.config import TZ
from freshquant.config import cfg, settings

host = get(settings, "mongodb.host", "127.0.0.1")
port = get(settings, "mongodb.port", 27017)
db = get(settings, "mongodb.db", "freshquant")
order_management_db = get(
    settings,
    "order_management.mongo_database",
    "freshquant_order_management",
)

MongoClient = pymongo.MongoClient(
    host=host, port=port, connect=False, tz_aware=True, tzinfo=TZ
)

DBfreshquant = MongoClient[db]
DBOrderManagement = MongoClient[order_management_db]
DBQuantAxis = MongoClient.quantaxis
DBQA = MongoClient.qa
