"""Market data schedules using asset-based approach.

This module defines schedules that trigger asset materialization.
Each schedule targets the root asset (list assets), and dependent assets are automatically triggered.
"""

from dagster import (
    AssetSelection,
    DefaultScheduleStatus,
    ScheduleDefinition,
    define_asset_job,
)

from freshquant.config import cfg

from fqdagster.defs.assets.market_data import (
    bond_list,
    etf_list,
    future_list,
    index_list,
    stock_list,
)

# Define asset jobs that will materialize the root assets and their dependencies
stock_data_job = define_asset_job(
    name="stock_data_job",
    description="Materialize stock data assets starting from stock_list",
    selection=AssetSelection.assets(stock_list).downstream(),
    tags={"dagster/max_concurrent_runs": "1"},
)

future_data_job = define_asset_job(
    name="future_data_job",
    description="Materialize future data assets starting from future_list",
    selection=AssetSelection.assets(future_list).downstream(),
    tags={"dagster/max_concurrent_runs": "1"},
)

etf_data_job = define_asset_job(
    name="etf_data_job",
    description="Materialize ETF data assets starting from etf_list",
    selection=AssetSelection.assets(etf_list).downstream(),
    tags={"dagster/max_concurrent_runs": "1"},
)

bond_data_job = define_asset_job(
    name="bond_data_job",
    description="Materialize bond data assets starting from bond_list",
    selection=AssetSelection.assets(bond_list).downstream(),
    tags={"dagster/max_concurrent_runs": "1"},
)

index_data_job = define_asset_job(
    name="index_data_job",
    description="Materialize index data assets starting from index_list",
    selection=AssetSelection.assets(index_list).downstream(),
    tags={"dagster/max_concurrent_runs": "1"},
)

# Schedule definitions
stock_data_schedule = ScheduleDefinition(
    name="stock_data_schedule",
    description="股票收盘作业保存行情数据定时任务",
    job=stock_data_job,
    cron_schedule="0 16 * * 1-5",
    execution_timezone=cfg.TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)

future_data_schedule = ScheduleDefinition(
    name="future_data_schedule",
    description="期货收盘数据保存定时任务",
    job=future_data_job,
    cron_schedule="30 8,16 * * 1-5",
    execution_timezone=cfg.TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)

etf_data_schedule = ScheduleDefinition(
    name="etf_data_schedule",
    description="ETF收盘数据保存定时任务",
    job=etf_data_job,
    cron_schedule="0 16 * * 1-5",
    execution_timezone=cfg.TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)

bond_data_schedule = ScheduleDefinition(
    name="bond_data_schedule",
    description="债券收盘数据保存定时任务",
    job=bond_data_job,
    cron_schedule="0 16 * * 1-5",
    execution_timezone=cfg.TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)

index_data_schedule = ScheduleDefinition(
    name="index_data_schedule",
    description="指数收盘数据保存定时任务",
    job=index_data_job,
    cron_schedule="0 16 * * 1-5",
    execution_timezone=cfg.TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)
