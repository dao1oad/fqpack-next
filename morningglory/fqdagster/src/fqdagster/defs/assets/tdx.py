# coding=utf-8

from dagster import AutoMaterializePolicy, asset
from loguru import logger

from freshquant.data.future.tdx import (
    fetchExMainContracts,
    fqFutureGetExtensionMarketList,
)


@asset(
    deps=["future_list", "future_day"],
    group_name="future_data"
)
def ex_markets(future_list: str, future_day: str):
    result = fqFutureGetExtensionMarketList()
    logger.info(result)
    return result


@asset(
    deps=["ex_markets"],
    group_name="future_data"
)
def ex_main_contracts(ex_markets) -> list:
    result = fetchExMainContracts()
    logger.info(result)
    return result
