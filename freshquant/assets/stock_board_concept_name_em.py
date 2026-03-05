from loguru import logger
import pandas as pd
import akshare as ak
import pymongo
from freshquant.database.mongodb import DBfreshquant

def fetch_stock_board_concept_name_em() -> pd.DataFrame:
    """
    使用akshare获取东方财富-概念板块数据
    """
    try:
        # 获取数据
        df = ak.stock_board_concept_name_em()
        
        # 重命名列
        new_columns = {
            '排名': 'rank',
            '板块名称': 'board_name', 
            '板块代码': 'board_code',
            '最新价': 'latest_price',
            '涨跌额': 'change_amount',
            '涨跌幅': 'change_percentage',
            '总市值': 'total_market_value',
            '换手率': 'turnover_rate',
            '上涨家数': 'rise_count',
            '下跌家数': 'fall_count',
            '领涨股票': 'leading_stock',
            '领涨股票-涨跌幅': 'leading_stock_change_percentage'
        }
        df = df.rename(columns=new_columns)
        
        # 添加日期列
        df['date'] = pd.Timestamp.now(tz='Asia/Shanghai').strftime('%Y%m%d')
        
        logger.info(f"成功获取概念板块数据，共 {len(df)} 条记录")
        
        # 保存到MongoDB
        try:
            # 将DataFrame转换为字典列表
            records = df.to_dict('records')

            # 批量更新或插入到stock_board_concept_name_em集合
            operations = [
                pymongo.UpdateOne(
                    {'date': record['date'], 'board_code': record['board_code']},
                    {'$set': record},
                    upsert=True,
                )
                for record in records
            ]
            DBfreshquant.stock_board_concept_name_em.bulk_write(operations)

            logger.info(f"成功保存 {len(records)} 条概念板块数据到MongoDB")
        except Exception as e:
            logger.error(f"保存概念板块数据到MongoDB失败: {str(e)}")
            raise
            
        return df
        
    except Exception as e:
        logger.error(f"获取概念板块数据失败: {str(e)}")
        raise

def clean_stock_board_concept_name_em():
    """
    清除DBfreshquant.stock_board_concept_name_em中三年以前的数据
    """
    try:
        # 计算三年前的日期
        three_years_ago = pd.Timestamp.now(tz='Asia/Shanghai') - pd.DateOffset(years=3)
        three_years_ago_str = three_years_ago.strftime('%Y%m%d')
        
        # 删除三年以前的数据
        result = DBfreshquant.stock_board_concept_name_em.delete_many(
            {'date': {'$lt': three_years_ago_str}}
        )
        
        logger.info(f"成功删除 {result.deleted_count} 条三年以前的概念板块数据")
        return result.deleted_count
        
    except Exception as e:
        logger.error(f"删除三年以前的概念板块数据失败: {str(e)}")
        raise
    
if __name__ == '__main__':
    fetch_stock_board_concept_name_em()
    clean_stock_board_concept_name_em()
