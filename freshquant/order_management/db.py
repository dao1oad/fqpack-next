# -*- coding: utf-8 -*-

from freshquant.bootstrap_config import bootstrap_config
from freshquant.db import DBfreshquant, MongoClient

order_management_db = (
    bootstrap_config.order_management.mongo_database or "freshquant_order_management"
)
projection_db = (
    bootstrap_config.order_management.projection_database or DBfreshquant.name
)

DBOrderManagement = MongoClient[order_management_db]
DBOrderProjection = MongoClient[projection_db]


def get_order_management_db():
    return DBOrderManagement


def get_projection_db():
    return DBOrderProjection
