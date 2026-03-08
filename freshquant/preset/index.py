# -*- coding: utf-8 -*-

from typing import List, Tuple

import pymongo
from pymongo.collection import Collection

from freshquant.database.mongodb import DBfreshquant
from freshquant.order_management.db import DBOrderManagement


def _create_index_if_not_exists(
    collection: Collection,
    index_name: str,
    fields: List[Tuple[str, int]],
    unique: bool = True,
) -> None:
    """Helper function to create an index if it doesn't exist"""
    indexes = collection.index_information()
    if index_name not in indexes:
        collection.create_index(fields, unique=unique, name=index_name)


def init_indexes():
    # Create indexes for various collections
    _create_index_if_not_exists(
        DBfreshquant.params, "unique_code", [("code", pymongo.ASCENDING)]
    )

    _create_index_if_not_exists(
        DBfreshquant.strategies, "unique_code", [("code", pymongo.ASCENDING)]
    )

    _create_index_if_not_exists(
        DBfreshquant.subscribe_instruments,
        "unique_code",
        [("code", pymongo.ASCENDING), ("exchange", pymongo.ASCENDING)],
    )

    _create_index_if_not_exists(
        DBfreshquant.stock_realtime,
        "code_datetime_frequence",
        [
            ("code", pymongo.ASCENDING),
            ("datetime", pymongo.ASCENDING),
            ("frequence", pymongo.ASCENDING),
        ],
    )

    _create_index_if_not_exists(
        DBfreshquant.gnhy_index_list, "idx_code", [("code", pymongo.ASCENDING)]
    )

    _create_index_if_not_exists(
        DBfreshquant.opening_amounts,
        "idx_stock_code_date",
        [("stock_code", pymongo.ASCENDING), ("date", pymongo.ASCENDING)],
    )
    _create_index_if_not_exists(
        DBfreshquant.stock_board_concept_name_em,
        "idx_boards_code_date",
        [("board_code", pymongo.ASCENDING), ("date", pymongo.ASCENDING)],
    )

    _create_index_if_not_exists(
        DBOrderManagement["om_credit_subjects"],
        "uniq_account_instrument",
        [
            ("account_id", pymongo.ASCENDING),
            ("instrument_id", pymongo.ASCENDING),
        ],
    )

    _create_index_if_not_exists(
        DBOrderManagement["om_credit_subjects"],
        "idx_symbol",
        [("symbol", pymongo.ASCENDING)],
        unique=False,
    )

    _create_index_if_not_exists(
        DBOrderManagement["om_credit_subjects"],
        "idx_fin_status",
        [("fin_status", pymongo.ASCENDING)],
        unique=False,
    )

    _create_index_if_not_exists(
        DBOrderManagement["om_credit_subjects"],
        "idx_updated_at",
        [("updated_at", pymongo.DESCENDING)],
        unique=False,
    )
