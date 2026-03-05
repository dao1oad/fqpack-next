from datetime import datetime, timedelta

import pandas as pd
import pymongo
from loguru import logger
from pywencai import get

from freshquant.carnation.config import TZ
from freshquant.database.mongodb import DBfreshquant


def fetch_opening_amounts() -> pd.DataFrame:
    """
    通过pywencai获取开盘金额数据
    """
    try:
        # 查询条件：开盘金额，按金额从大到小排序
        query = f"{datetime.now().strftime('%Y年%m月%d日')}09点25分的成交额"

        # 获取第一页数据
        df = get(
            query=query,
            loop=False,  # 只获取第一页
            query_type='stock',  # 股票类型
            sort_key='分时成交额',  # 按分时成交额排序
            sort_order='desc',  # 降序排列
            page=1,  # 只获取第一页
        )
        # 重命名列
        # 创建新的列名映射
        new_columns = {}
        for col in df.columns:
            if '股票代码' in col:
                new_columns[col] = 'stock_code'
            elif '股票简称' in col:
                new_columns[col] = 'name'
            elif '分时成交额' in col:
                new_columns[col] = 'amount'
            elif '分时成交量' in col:
                new_columns[col] = 'volume'
            elif '分时换手率' in col:
                new_columns[col] = 'turnover_rate'
            elif '分时涨跌幅' in col:
                new_columns[col] = 'price_change_percentage'
            elif '分时收盘价' in col:
                new_columns[col] = 'open_price'
            else:
                new_columns[col] = col  # 保持原列名

        df = df.rename(columns=new_columns)

        # 只保留需要的列
        df = df[
            [
                'stock_code',
                'name',
                'amount',
                'volume',
                'turnover_rate',
                'price_change_percentage',
                'open_price',
                'market_code',
                'code',
            ]
        ]

        # 添加日期列
        df['date'] = f"{datetime.now().strftime('%Y%m%d')}"

        logger.info(f"成功获取开盘金额数据，共 {len(df)} 条记录")

        # 保存到MongoDB
        try:
            # 将DataFrame转换为字典列表
            records = df.to_dict('records')

            # 批量更新或插入到opening_amounts集合
            operations = [
                pymongo.UpdateOne(
                    {'date': record['date'], 'stock_code': record['stock_code']},
                    {'$set': record},
                    upsert=True,
                )
                for record in records
            ]
            DBfreshquant.opening_amounts.bulk_write(operations)

            logger.info(f"成功保存 {len(records)} 条开盘金额数据到MongoDB")
        except Exception as e:
            logger.error(f"保存开盘金额数据到MongoDB失败: {str(e)}")
            raise

        return df
    except Exception as e:
        logger.error(f"获取开盘金额数据失败: {str(e)}")
        raise


def clean_old_opening_amounts() -> int:
    """清理opening_amounts集合中3年以前的数据

    Returns:
        int: 被删除的记录数量
    """
    try:
        # 计算3年前的日期（考虑时区）
        cutoff_date = datetime.now(TZ) - timedelta(days=3 * 365)
        cutoff_str = cutoff_date.strftime('%Y%m%d')

        # 执行删除操作
        result = DBfreshquant.opening_amounts.delete_many({'date': {'$lt': cutoff_str}})

        logger.info(f"成功清理 {result.deleted_count} 条历史开盘数据")
        return result.deleted_count

    except Exception as e:
        logger.error(f"数据清理失败: {str(e)}")
        raise


if __name__ == "__main__":
    # 测试代码
    data = fetch_opening_amounts()
    print(data)
