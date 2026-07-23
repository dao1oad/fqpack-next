"""Market data schedules using asset-based approach.

This module defines schedules that trigger asset materialization. Stock, ETF,
and Index jobs use explicit whitelists so unrelated downstream assets cannot
join a market-data run.
"""

from typing import cast

from dagster import (
    AssetSelection,
    DefaultScheduleStatus,
    ScheduleDefinition,
    define_asset_job,
)
from fqdagster.defs.assets.market_data import (
    bond_list,
    etf_adj,
    etf_day,
    etf_list,
    etf_min,
    etf_postclose_ready_asset,
    future_list,
    index_day,
    index_list,
    index_min,
    stock_adj,
    stock_block,
    stock_day,
    stock_list,
    stock_min,
    stock_postclose_ready_asset,
)
from fqdagster.defs.assets.postclose_ready import (
    refresh_quality_stock_universe_snapshot,
)

from freshquant.config import cfg

TIME_ZONE = cast(str, getattr(cfg, "TIME_ZONE", "Asia/Shanghai"))
MONGO_WRITER_TAG = {"freshquant/mongo_writer": "quantaxis_market_data"}
BOUNDED_MARKET_JOB_TAGS = {
    **MONGO_WRITER_TAG,
    "dagster/max_concurrent_runs": "1",
    "dagster/max_retries": "2",
    "dagster/max_runtime": "28800",
}

# Define market-data asset jobs.
stock_data_job = define_asset_job(
    name="stock_data_job",
    description="Materialize the explicit Stock market-data asset whitelist",
    selection=AssetSelection.assets(
        stock_list,
        stock_block,
        stock_day,
        stock_min,
        stock_adj,
        refresh_quality_stock_universe_snapshot,
        stock_postclose_ready_asset,
    ),
    tags=BOUNDED_MARKET_JOB_TAGS,
)

future_data_job = define_asset_job(
    name="future_data_job",
    description="Materialize future data assets starting from future_list",
    selection=AssetSelection.assets(future_list).downstream(),
    tags={"dagster/max_concurrent_runs": "1"},
)

etf_data_job = define_asset_job(
    name="etf_data_job",
    description="Materialize the explicit ETF market-data asset whitelist",
    selection=AssetSelection.assets(
        etf_list,
        etf_day,
        etf_min,
        etf_adj,
        etf_postclose_ready_asset,
    ),
    tags=BOUNDED_MARKET_JOB_TAGS,
)

bond_data_job = define_asset_job(
    name="bond_data_job",
    description="Materialize bond data assets starting from bond_list",
    selection=AssetSelection.assets(bond_list).downstream(),
    tags={"dagster/max_concurrent_runs": "1"},
)

index_data_job = define_asset_job(
    name="index_data_job",
    description="Materialize the explicit BFQ Index market-data asset whitelist",
    selection=AssetSelection.assets(index_list, index_day, index_min),
    tags=BOUNDED_MARKET_JOB_TAGS,
)

# Schedule definitions
stock_data_schedule = ScheduleDefinition(
    name="stock_data_schedule",
    description="股票收盘作业保存行情数据定时任务",
    job=stock_data_job,
    cron_schedule="0 16 * * 1-5",
    execution_timezone=TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)

future_data_schedule = ScheduleDefinition(
    name="future_data_schedule",
    description="期货收盘数据保存定时任务",
    job=future_data_job,
    cron_schedule="30 8,16 * * 1-5",
    execution_timezone=TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)

etf_data_schedule = ScheduleDefinition(
    name="etf_data_schedule",
    description="ETF收盘数据保存定时任务",
    job=etf_data_job,
    cron_schedule="0 16 * * 1-5",
    execution_timezone=TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)

bond_data_schedule = ScheduleDefinition(
    name="bond_data_schedule",
    description="债券收盘数据保存定时任务",
    job=bond_data_job,
    cron_schedule="0 16 * * 1-5",
    execution_timezone=TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)

index_data_schedule = ScheduleDefinition(
    name="index_data_schedule",
    description="指数收盘数据保存定时任务",
    job=index_data_job,
    cron_schedule="0 16 * * 1-5",
    execution_timezone=TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)
