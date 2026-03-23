# -*- coding: utf-8 -*-

from typing import List

from freshquant.database.cache import in_memory_cache
from freshquant.db import DBfreshquant
from freshquant.util.code import (
    fq_util_code_append_market_code,
    fq_util_code_append_market_code_suffix,
)


@in_memory_cache.memoize(expiration=3600)
def queryMustPoolCodes(
    instrumentTypes: List[str] = ["stock_cn", "etf_cn"]
) -> List[str]:
    records = list(
        DBfreshquant["must_pool"].find(
            {
                "instrument_type": {"$in": instrumentTypes},
                "disabled": {"$ne": True},
            }
        )
    )
    return [item["code"] for item in records]


@in_memory_cache.memoize(expiration=3600)
def queryMustPoolCodesWithMarketCodePrefix(
    instrumentTypes: List[str] = ["stock_cn", "etf_cn"]
) -> List[str]:
    records = list(
        DBfreshquant["must_pool"].find({"instrument_type": {"$in": instrumentTypes}})
    )
    return [fq_util_code_append_market_code(item["code"]) for item in records]


@in_memory_cache.memoize(expiration=3600)
def queryMustPoolCodesWithMarketCodeSuffix(
    instrumentTypes: List[str] = ["stock_cn", "etf_cn"]
) -> List[str]:
    records = list(
        DBfreshquant["must_pool"].find({"instrument_type": {"$in": instrumentTypes}})
    )
    return [fq_util_code_append_market_code_suffix(item["code"]) for item in records]


def cleanMustPool():
    positions = list(DBfreshquant["xt_positions"].find({}))
    codes = [item["stock_code"][:6] for item in positions]
    DBfreshquant["must_pool"].delete_many({"code": {"$in": codes}})


if __name__ == "__main__":
    cleanMustPool()
