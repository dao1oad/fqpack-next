# -*- coding: utf-8 -*-

from freshquant.database.cache import bump_cache_version

STOCK_HOLDINGS_CACHE = "stock_holdings"


def mark_stock_holdings_projection_updated() -> int:
    return bump_cache_version(STOCK_HOLDINGS_CACHE)
