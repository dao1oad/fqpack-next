import pandas as pd
from dagster import AutoMaterializePolicy, AutoMaterializeRule, asset
from loguru import logger

from freshquant.assets.opening_amounts import fetch_opening_amounts


@asset(
    auto_materialize_policy=AutoMaterializePolicy.eager().with_rules(
        # 基于时间的自动物化规则
        AutoMaterializeRule.materialize_on_cron(
            cron_schedule="23-28 9 * * 1-5",  # 周一到周五 9:23-9:28 每分钟运行
            timezone="Asia/Shanghai",
        )
    ),
)
def opening_amounts() -> pd.DataFrame:
    """
    获取每天9点25分的开盘金额数据
    """
    try:
        # 获取数据
        df = fetch_opening_amounts()
        logger.info(f"成功获取开盘金额数据，共 {len(df)} 条记录")
        return df

    except Exception as e:
        logger.error(f"获取开盘金额数据失败: {str(e)}")
        raise
