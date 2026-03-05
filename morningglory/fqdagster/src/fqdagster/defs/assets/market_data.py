"""Market data assets using Dagster's asset-based approach.

This module replaces the traditional op/job pattern with assets that have clear dependencies.
Each data type (stock, future, etf, bond, index) has its own set of assets with proper dependencies.
"""

import pendulum
from blinker import signal
from dagster import AssetExecutionContext, asset
from QUANTAXIS.QASU.main import (
    QA_SU_save_bond_day,
    QA_SU_save_bond_list,
    QA_SU_save_bond_min,
    QA_SU_save_etf_day,
    QA_SU_save_etf_list,
    QA_SU_save_etf_min,
    QA_SU_save_future_day_all,
    QA_SU_save_future_list,
    QA_SU_save_future_min_all,
    QA_SU_save_index_day,
    QA_SU_save_index_list,
    QA_SU_save_index_min,
    QA_SU_save_stock_block,
    QA_SU_save_stock_day,
    QA_SU_save_stock_list,
    QA_SU_save_stock_min,
    QA_SU_save_stock_xdxr,
)
from freshquant.data.etf_adj_sync import sync_etf_adj_all, sync_etf_xdxr_all

market_data_alert = signal("market_data_alert")


# Stock Assets
@asset(group_name="stock_data")
def stock_list(context: AssetExecutionContext) -> str:
    """Download and save stock list data."""
    context.log.info("Saving stock list")
    QA_SU_save_stock_list("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "股票列表数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[stock_list], group_name="stock_data")
def stock_block(context: AssetExecutionContext, stock_list: str) -> str:
    """Download and save stock block data. Depends on stock_list."""
    context.log.info(
        f"Saving stock block data, triggered after stock_list at {stock_list}"
    )
    QA_SU_save_stock_block("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "股票板块数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[stock_list], group_name="stock_data")
def stock_day(context: AssetExecutionContext, stock_list: str) -> str:
    """Download and save stock daily data. Depends on stock_list."""
    context.log.info(
        f"Saving stock daily data, triggered after stock_list at {stock_list}"
    )
    QA_SU_save_stock_day("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "股票日线数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[stock_list], group_name="stock_data")
def stock_min(context: AssetExecutionContext, stock_list: str) -> str:
    """Download and save stock minute data. Depends on stock_list."""
    context.log.info(
        f"Saving stock minute data, triggered after stock_list at {stock_list}"
    )
    QA_SU_save_stock_min("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "股票分钟数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[stock_day], group_name="stock_data")
def stock_xdxr(context: AssetExecutionContext, stock_day: str) -> str:
    """Download and save stock dividend/adjustment data. Depends on stock_day."""
    context.log.info(
        f"Saving stock dividend data, triggered after stock_day at {stock_day}"
    )
    QA_SU_save_stock_xdxr("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "股票除权除息数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


# Future Assets
@asset(group_name="future_data")
def future_list(context: AssetExecutionContext) -> str:
    """Download and save future list data."""
    context.log.info("Saving future list")
    QA_SU_save_future_list("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "期货列表数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[future_list], group_name="future_data")
def future_day(context: AssetExecutionContext, future_list: str) -> str:
    """Download and save future daily data. Depends on future_list."""
    context.log.info(
        f"Saving future daily data, triggered after future_list at {future_list}"
    )
    QA_SU_save_future_day_all("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "期货日线数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[future_list], group_name="future_data")
def future_min(context: AssetExecutionContext, future_list: str) -> str:
    """Download and save future minute data. Depends on future_list."""
    context.log.info(
        f"Saving future minute data, triggered after future_list at {future_list}"
    )
    QA_SU_save_future_min_all("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "期货分钟数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


# ETF Assets
@asset(group_name="etf_data")
def etf_list(context: AssetExecutionContext) -> str:
    """Download and save ETF list data."""
    context.log.info("Saving ETF list")
    QA_SU_save_etf_list("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "ETF列表数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[etf_list], group_name="etf_data")
def etf_day(context: AssetExecutionContext, etf_list: str) -> str:
    """Download and save ETF daily data. Depends on etf_list."""
    context.log.info(f"Saving ETF daily data, triggered after etf_list at {etf_list}")
    QA_SU_save_etf_day("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "ETF日线数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[etf_list], group_name="etf_data")
def etf_min(context: AssetExecutionContext, etf_list: str) -> str:
    """Download and save ETF minute data. Depends on etf_list."""
    context.log.info(f"Saving ETF minute data, triggered after etf_list at {etf_list}")
    QA_SU_save_etf_min("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "ETF分钟数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[etf_list], group_name="etf_data")
def etf_xdxr(context: AssetExecutionContext, etf_list: str) -> str:
    """Download and save ETF xdxr(adjustment events) data. Depends on etf_list."""
    context.log.info(f"Saving ETF xdxr data, triggered after etf_list at {etf_list}")
    stats = sync_etf_xdxr_all()
    context.log.info(f"ETF xdxr sync stats: {stats}")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "ETF 除权除息/扩缩股(xdxr) 数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[etf_day, etf_xdxr], group_name="etf_data")
def etf_adj(context: AssetExecutionContext, etf_day: str, etf_xdxr: str) -> str:
    """Compute and save ETF qfq adjustment factors. Depends on etf_day + etf_xdxr."""
    context.log.info(
        f"Saving ETF adj(qfq) data, triggered after etf_day at {etf_day} and etf_xdxr at {etf_xdxr}"
    )
    stats = sync_etf_adj_all()
    context.log.info(f"ETF adj sync stats: {stats}")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "ETF 前复权因子(etf_adj) 数据已生成完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


# Bond Assets
@asset(group_name="bond_data")
def bond_list(context: AssetExecutionContext) -> str:
    """Download and save bond list data."""
    context.log.info("Saving bond list")
    QA_SU_save_bond_list("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "债券列表数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[bond_list], group_name="bond_data")
def bond_day(context: AssetExecutionContext, bond_list: str) -> str:
    """Download and save bond daily data. Depends on bond_list."""
    context.log.info(
        f"Saving bond daily data, triggered after bond_list at {bond_list}"
    )
    QA_SU_save_bond_day("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "债券日线数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[bond_list], group_name="bond_data")
def bond_min(context: AssetExecutionContext, bond_list: str) -> str:
    """Download and save bond minute data. Depends on bond_list."""
    context.log.info(
        f"Saving bond minute data, triggered after bond_list at {bond_list}"
    )
    QA_SU_save_bond_min("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "债券分钟数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


# Index Assets
@asset(group_name="index_data")
def index_list(context: AssetExecutionContext) -> str:
    """Download and save index list data."""
    context.log.info("Saving index list")
    QA_SU_save_index_list("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "指数列表数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[index_list], group_name="index_data")
def index_day(context: AssetExecutionContext, index_list: str) -> str:
    """Download and save index daily data. Depends on index_list."""
    context.log.info(
        f"Saving index daily data, triggered after index_list at {index_list}"
    )
    QA_SU_save_index_day("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "指数日线数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[index_list], group_name="index_data")
def index_min(context: AssetExecutionContext, index_list: str) -> str:
    """Download and save index minute data. Depends on index_list."""
    context.log.info(
        f"Saving index minute data, triggered after index_list at {index_list}"
    )
    QA_SU_save_index_min("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "指数分钟数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")
