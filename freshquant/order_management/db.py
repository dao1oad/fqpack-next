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

# V2 主账本集合边界；后续读写默认应围绕这组集合收敛。
ORDER_LEDGER_V2_COLLECTIONS = (
    "om_order_requests",
    "om_broker_orders",
    "om_order_events",
    "om_execution_fills",
    "om_reconciliation_gaps",
    "om_reconciliation_resolutions",
    "om_position_entries",
    "om_entry_slices",
    "om_exit_allocations",
    "om_entry_stoploss_bindings",
    "om_takeprofit_profiles",
    "om_takeprofit_states",
    "om_exit_trigger_events",
    "om_ingest_rejections",
    "om_credit_subjects",
)

# 迁移期只读集合；保留给 legacy adapter / 历史排障，避免继续新增主链写入。
ORDER_LEDGER_LEGACY_COLLECTIONS = (
    "om_orders",
    "om_trade_facts",
    "om_buy_lots",
    "om_lot_slices",
    "om_sell_allocations",
    "om_external_candidates",
    "om_stoploss_bindings",
)


def get_order_management_db():
    return DBOrderManagement


def get_projection_db():
    return DBOrderProjection
