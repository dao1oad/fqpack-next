# -*- coding: utf-8 -*-

from freshquant.bootstrap_config import bootstrap_config
from freshquant.db import MongoClient

DEFAULT_POSITION_MANAGEMENT_DB = "freshquant_position_management"

position_management_db = (
    bootstrap_config.position_management.mongo_database
    or DEFAULT_POSITION_MANAGEMENT_DB
)

DBPositionManagement = MongoClient[position_management_db]


def get_position_management_db():
    return DBPositionManagement
