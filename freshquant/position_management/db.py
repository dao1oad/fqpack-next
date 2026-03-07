# -*- coding: utf-8 -*-

from pydash import get

from freshquant.config import settings
from freshquant.db import MongoClient

DEFAULT_POSITION_MANAGEMENT_DB = "freshquant_position_management"

position_management_db = get(
    settings,
    "position_management.mongo_database",
    DEFAULT_POSITION_MANAGEMENT_DB,
)

DBPositionManagement = MongoClient[position_management_db]


def get_position_management_db():
    return DBPositionManagement
