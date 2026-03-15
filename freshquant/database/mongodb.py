# -*- coding: utf-8 -*-

import pymongo

from freshquant.bootstrap_config import bootstrap_config
from freshquant.runtime_constants import TZ

host = bootstrap_config.mongodb.host
port = bootstrap_config.mongodb.port
db = bootstrap_config.mongodb.db
order_management_db = bootstrap_config.order_management.mongo_database

MongoClient = pymongo.MongoClient(
    host=host, port=port, connect=False, tz_aware=True, tzinfo=TZ
)

DBfreshquant = MongoClient[db]
DBOrderManagement = MongoClient[order_management_db]
DBQuantAxis = MongoClient.quantaxis
DBQA = MongoClient.qa
