# -*- coding: utf-8 -*-

from freshquant.order_management.repository import OrderManagementRepository


def resolve_buy_lot_id(fill_id, repository=None):
    repository = repository or OrderManagementRepository()
    for buy_lot in repository.list_buy_lots():
        if str(buy_lot.get("legacy_fill_id")) == str(fill_id):
            return buy_lot["buy_lot_id"]
    return None
