from dagster import AssetSelection, define_asset_job

from ..assets.daily_screening import daily_screening_context

daily_screening_postclose_job = define_asset_job(
    name="daily_screening_postclose_job",
    description="盘后物化每日筛选资产依赖图",
    selection=AssetSelection.assets(daily_screening_context).downstream(),
    tags={"dagster/max_concurrent_runs": "1"},
)
