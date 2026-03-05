"""
策略输入数据模型

定义策略输入数据的基类和各种自定义实现
"""

from datetime import timedelta, date, datetime
from typing import Dict, Optional, List

import pandas as pd

from freshquant.data.stock import fq_data_stock_fetch_day, fq_data_stock_fetch_min
from freshquant.instrument.stock import fq_inst_fetch_stock_list
from freshquant.sim.base_strategy.position import get_a_certain_day_positions


class InputDataModel:
    """
    策略输入数据模型，负责定义和加载策略所需的数据

    支持多周期数据加载，子类可以继承此类来定义自己的数据需求和加载逻辑
    """

    def __init__(self, data_length: Optional[Dict[str, int]] = None, stock_pool_account_cookies: Optional[List[str]] = None):
        """
        初始化输入模型

        参数:
        data_length: 各周期需要获取的K线数量字典，格式为 {'1d': 1500, '1w': 3000, '5m': 1000}
                    支持的周期格式：
                    - 分钟级: '1m', '3m', '5m', '15m', '30m', '60m', '90m', '120m', '180m'
                    - 日线: '1d'
                    - 周线: '1w'
                    如果为None，默认加载日线1500根K线
        """
        if data_length is None:
            self.data_length = {'1d': 1500}
        elif isinstance(data_length, dict):
            self.data_length = data_length
        else:
            raise TypeError(f"data_length必须是dict类型，当前类型: {type(data_length)}")
        
        self.stock_pool_account_cookies = stock_pool_account_cookies or []

    def get_data_length(
        self, period: Optional[str] = None
    ) -> Optional[int] | Dict[str, int]:
        """
        获取需要的历史K线数量

        参数:
        period: 周期标识，如 '1d', '1w', '5m' 等。如果为None，返回所有周期的配置字典

        返回:
        如果指定period，返回该周期的K线数量（int），如果不存在返回None
        如果不指定period，返回所有周期的配置字典（Dict[str, int]）
        """
        if period is None:
            return self.data_length
        return self.data_length.get(period)

    def load_data(self, code: str, today) -> Dict[str, pd.DataFrame]:
        """
        加载市场数据（支持多周期）

        根据data_length配置自动加载对应周期的数据

        参数:
        code: 股票代码
        today: 交易日期（datetime对象）

        返回:
        Dict[str, pd.DataFrame]: 市场数据字典，格式为 {'1d': DataFrame, '1w': DataFrame, ...}
        """
        result = {}

        for period, length in self.data_length.items():
            # 兼容旧格式
            if period in ('day', '1d'):
                data = self._load_day_data(code, today, length)
                if data is not None:
                    result['1d'] = data
            elif period in ('week', '1w'):
                data = self._load_week_data(code, today, length)
                if data is not None:
                    result['1w'] = data
            elif period.endswith('m'):
                # 加载分钟级数据
                data = self._load_min_data(code, today, length, period)
                if data is not None:
                    result[period] = data

        return result

    def _load_day_data(self, code: str, today, length: int) -> Optional[pd.DataFrame]:
        """
        加载日线数据（内部方法）

        参数:
        code: 股票代码
        today: 交易日期（datetime对象）
        length: 需要加载的K线数量

        返回:
        DataFrame: 日线历史数据
        """
        end_date = today
        start_date = end_date - timedelta(days=length + 10)
        return fq_data_stock_fetch_day(code=code, start=start_date, end=end_date)

    def _load_week_data(self, code: str, today, length: int) -> Optional[pd.DataFrame]:
        """
        加载周线数据（内部方法）

        参数:
        code: 股票代码
        today: 交易日期（datetime对象）
        length: 需要加载的周K线数量（会自动转换为所需的实际天数）

        返回:
        DataFrame: 周线历史数据
        """
        # 周线需要更长的时间范围（约7倍），额外加70天缓冲
        end_date = today
        start_date = end_date - timedelta(days=length * 7 + 70)

        # 从日线数据重采样得到周线
        day_data = fq_data_stock_fetch_day(code=code, start=start_date, end=end_date)
        if day_data is None or len(day_data) == 0:
            return None

        # 重采样为周线
        week_data = (
            day_data.resample('W')
            .agg(
                {
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum',
                }
            )
            .dropna()
        )

        return week_data

    def _load_min_data(
        self, code: str, today, length: int, period: str
    ) -> Optional[pd.DataFrame]:
        """
        加载分钟级数据（内部方法）

        参数:
        code: 股票代码
        today: 交易日期（datetime对象）
        length: 需要加载的K线数量
        period: 周期标识，如 '1m', '5m', '15m' 等

        返回:
        DataFrame: 分钟级历史数据
        """
        # 根据K线数量估算需要的天数
        # 每天交易时间4小时 = 240分钟
        minutes_per_period = int(period[:-1])  # 提取数字部分，如 '5m' -> 5
        bars_per_day = 240 // minutes_per_period  # 每天的K线数量
        days_needed = (length // bars_per_day) + 10  # 额外加10天作为缓冲

        end_date = today
        start_date = end_date - timedelta(days=days_needed)
        return fq_data_stock_fetch_min(
            code=code, frequence=period, start=start_date, end=end_date
        )

    def load_stock_pool_codes(self, today: date) -> List[str]:
        """
        加载股票池代码列表

        参数:
        today: 交易日期

        返回:
        List[str]: 股票代码列表
        """
        # 如果提供了stock_pool_account_cookies，从指定账户获取股票池
        if self.stock_pool_account_cookies:
            stock_codes = set()
            today_str = today.strftime('%Y-%m-%d')
            
            for account_cookie in self.stock_pool_account_cookies:
                positions_data = get_a_certain_day_positions(account_cookie, today_str)
                if positions_data and positions_data.get('positions'):
                    for position in positions_data['positions']:
                        code = position.get('instrument_id')
                        if code:
                            stock_codes.add(code)
            
            return list(stock_codes)
        
        # 如果没有提供stock_pool_account_cookies，使用默认逻辑获取所有股票（排除ST）
        stock_list = fq_inst_fetch_stock_list()
        stock_list = [stock for stock in stock_list if "ST" not in stock.get("name", "")]
        return [stock.get("code") for stock in stock_list]

if __name__ == "__main__":
    # model = InputDataModel(stock_pool_account_cookies=["五连阳动量跟随策略"])
    model = InputDataModel()
    print(model.load_stock_pool_codes((datetime.now() - timedelta(days=1)).date()))
