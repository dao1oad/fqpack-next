import pandas as pd
from dagster import AutoMaterializePolicy, AutoMaterializeRule, asset
from loguru import logger

from freshquant.assets.stock_board_concept_name_em import (
    fetch_stock_board_concept_name_em,
)


@asset(
    auto_materialize_policy=AutoMaterializePolicy.eager().with_rules(
        # 基于时间的自动物化规则
        AutoMaterializeRule.materialize_on_cron(
            cron_schedule="30 15 * * 1-5",  # 周一到周五 15:30 运行
            timezone="Asia/Shanghai",
        )
    ),
)
def stock_board_concept_name_em() -> pd.DataFrame:
    """
    获取东方财富-概念板块数据
    数据包括：板块名称、代码、最新价、涨跌幅、总市值等
    """
    try:
        # 获取数据
        df = fetch_stock_board_concept_name_em()
        logger.info(f"成功获取东方财富概念板块数据，共 {len(df)} 条记录")
        return df

    except Exception as e:
        logger.error(f"获取东方财富概念板块数据失败: {str(e)}")
        raise
