# coding: utf-8

from typing import Dict, List

from pydash import chain

from freshquant.instrument.general import query_instrument_info
from freshquant.pool.stock import query_stock_must_pool_stocks, query_stock_pool_stocks
from freshquant.position.stock import query_stock_positions


def query_subscribe_stocks() -> List[Dict]:
    """
    获取需要订阅行情的股票，包含ETF和债券。
    """
    subscribe_stocks = []
    # 获取持仓的股票
    stock_positions = query_stock_positions()
    for stock_position in stock_positions:
        subscribe_stocks.append(
            {
                "stock_code": stock_position.get('stock_code'),
                "name": stock_position.get('name'),
                "instrument_type": stock_position.get('instrument_type'),
                "exchange": stock_position.get('exchange'),
            }
        )
    # 获取必买股票池的股票
    stock_must_pool_stocks = query_stock_must_pool_stocks()
    stock_must_pool_stocks = chain(stock_must_pool_stocks).uniq_by('code').value()
    for stock_must_pool_stock in stock_must_pool_stocks:
        stock_code = stock_must_pool_stock.get('code')
        instrument_info = query_instrument_info(stock_code)
        if instrument_info is None:
            continue
        stock_code = (
            f'{instrument_info.get("code")}.{instrument_info.get("sse")}'.upper()
        )
        subscribe_stocks.append(
            {
                "stock_code": stock_code,
                "name": stock_must_pool_stock.get('name'),
                "instrument_type": instrument_info.get('sec'),
                "exchange": instrument_info.get('sse'),
            }
        )
    # 获取股票池的股票
    stock_pool_stocks = query_stock_pool_stocks()
    stock_pool_stocks = chain(stock_pool_stocks).uniq_by('code').value()
    for stock_pool_stock in stock_pool_stocks:
        stock_code = stock_pool_stock.get('code')
        instrument_info = query_instrument_info(stock_code)
        if instrument_info is None:
            continue
        stock_code = (
            f'{instrument_info.get("code")}.{instrument_info.get("sse")}'.upper()
        )
        subscribe_stocks.append(
            {
                "stock_code": stock_code,
                "name": stock_pool_stock.get('name'),
                "instrument_type": instrument_info.get('sec'),
                "exchange": instrument_info.get('sse'),
            }
        )

    return chain(subscribe_stocks).uniq_by('stock_code').value()


if __name__ == '__main__':
    subscribe_stocks = query_subscribe_stocks()
    print(query_subscribe_stocks())
    print(len(subscribe_stocks))
