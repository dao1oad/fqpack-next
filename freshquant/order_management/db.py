# -*- coding: utf-8 -*-

from pydash import get

from freshquant.config import settings
from freshquant.db import DBfreshquant, MongoClient

order_management_db = get(
    settings,
    "order_management.mongo_database",
    "freshquant_order_management",
)
projection_db = get(
    settings,
    "order_management.projection_database",
    DBfreshquant.name,
)

DBOrderManagement = MongoClient[order_management_db]
DBOrderProjection = MongoClient[projection_db]


def get_order_management_db():
    return DBOrderManagement


def get_projection_db():
    return DBOrderProjection

