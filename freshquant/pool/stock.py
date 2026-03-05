# coding: utf-8

import os
from typing import Dict, List, Optional
from freshquant.data.astock.holding import get_stock_holding_codes
from freshquant.database.mongodb import DBfreshquant


def query_stock_pool_stocks() -> List[Dict]:
    """
    查询股票池中的股票，包含了债券和ETF
    code, name, pool_name, datetime, expire_at, instrument_type, exchange
    """
    records = list(DBfreshquant.stock_pools.find({}))
    return records


def query_stock_must_pool_stocks() -> List[Dict]:
    """
    查询必买股票池中的股票，包含了债券和ETF
    code, name, pool_name, datetime, forever, instrument_type, exchange
    """
    records = list(DBfreshquant.must_pool.find({}))
    return records

def sync_stock_pools_to_tdx(category: Optional[str] = None):
    """将股票池数据同步到通达信自选股
    
    Args:
        category: 可选，指定只同步特定分类的股票
        
    Returns:
        bool: 同步是否成功
    """
    try:
        # 获取通达信安装路径
        tdx_home = os.getenv('TDX_HOME')
        if not tdx_home:
            raise ValueError("环境变量 TDX_HOME 未设置")
            
        # 自选股文件路径
        tdx_stock_file = os.path.join(tdx_home, 'T0002', 'blocknew', 'ZXG.blk')
        
        # 默认固定的股票代码
        default_codes = [
            "1000001",  # 上证指数
            "0399001",  # 深圳成指
        ]

        codes = get_stock_holding_codes()
        
        must_stocks = query_stock_must_pool_stocks()
        for must_stock in must_stocks:
            if must_stock['code'] not in codes:
                codes.append(must_stock['code'])
        
        # 获取股票池数据
        stocks = query_stock_pool_stocks()
        if category:
            stocks = [stock for stock in stocks if category in stock.get('category', [])]
        for stock in stocks:
            if stock['code'] not in codes:
                codes.append(stock['code'])

        # 生成通达信格式的股票代码
        tdx_codes: List[str] = default_codes.copy()  # 从默认代码开始
        for code in codes:
            # 转换为通达信格式：上海股票前缀1，深圳股票前缀0
            if code.startswith(('600', '601', '603', '605', '688', '510')):
                tdx_codes.append(f"1{code}")
            elif code.startswith(('000', '002', '003', '300', '301', '588')):
                tdx_codes.append(f"0{code}")
        print(tdx_codes)
        # 写入通达信自选股文件
        with open(tdx_stock_file, 'w', encoding='gbk') as f:
            f.write('\n'.join(tdx_codes))
            
        return True
        
    except Exception as e:
        print(f"同步到通达信自选股失败: {str(e)}")
        return False

if __name__ == "__main__":
    # print(query_stock_must_pool_stocks())
    # print(query_stock_pool_stocks())
    print(sync_stock_pools_to_tdx())
