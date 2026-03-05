"""
BaseStrategy到Backtrader的适配器

使用适配器模式，将BaseStrategy适配到backtrader的策略接口，
使得BaseStrategy可以在backtrader环境中运行回测。
"""

import backtrader as bt
import pandas as pd
from typing import Dict

from freshquant.sim.base_strategy.main import BaseStrategy


class BacktraderStrategyAdapter(bt.Strategy):
    """
    BaseStrategy到Backtrader的通用适配器类

    这个适配器类继承自backtrader.Strategy，可以适配任何BaseStrategy的子类，
    将backtrader的回测框架与BaseStrategy的交易逻辑连接起来。
    """

    # 策略参数
    params = (
        ('strategy_class', None),    # BaseStrategy子类
        ('stock_pool_codes', []),    # 股票池代码列表
        ('init_cash', 1000000),      # 初始资金
        ('lot_size', 3000),          # 每次买入金额限制
        ('min_data_length', 5),      # 最小数据长度
        ('his_data_length', 30),     # 历史数据长度
        ('strategy_kwargs', {}),     # 传递给策略的额外参数
        ('nodatabase', True),
    )

    def __init__(self):
        """初始化适配器"""
        super().__init__()

        # 检查必要参数
        if self.params.strategy_class is None:
            raise ValueError("必须提供strategy_class参数")

        # 创建被适配的BaseStrategy实例
        self.base_strategy = self._create_base_strategy()

        # 存储历史数据的字典，key为股票代码，value为DataFrame
        self.historical_data: Dict[str, pd.DataFrame] = {}

        # 存储当前处理的股票代码
        self.current_stock_code = None

        # 记录交易日志
        self.trade_log = []

    def _create_base_strategy(self) -> BaseStrategy:
        """
        创建BaseStrategy实例

        返回:
        BaseStrategy: BaseStrategy的具体实现实例
        """
        strategy_kwargs = {
            'init_cash': self.params.init_cash,
            'lot_size': self.params.lot_size,
            'nodatabase': True,
        }

        # 合并额外的参数
        strategy_kwargs.update(self.params.strategy_kwargs)

        self.strategy = self.params.strategy_class(**strategy_kwargs)

        return self.strategy

    def log(self, txt, dt=None):
        """记录日志"""
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()}: {txt}')
        self.trade_log.append(f'{dt.isoformat()}: {txt}')

    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            stock_code = order.data._name
            if hasattr(stock_code, 'split'):
                stock_code = stock_code.split('.')[0]

            trade_price = order.executed.price
            trade_size = order.executed.size
            trade_dt = self.datas[0].datetime.datetime(0).strftime('%Y-%m-%d %H:%M:%S')

            if order.isbuy():
                self.log(f'买入执行: {order.executed.price:.2f}, '
                         f'数量: {order.executed.size}, '
                         f'手续费: {order.executed.comm:.2f}')
                # 将成交信息同步到BaseStrategy
                hist_data = self.historical_data[stock_code]
                current_idx = len(hist_data) - 1
                self.base_strategy._execute_buy_order(stock_code, trade_dt, trade_price, quantity=abs(trade_size), hist_data=hist_data, current_idx=current_idx)
            else:
                self.log(f'卖出执行: {order.executed.price:.2f}, '
                         f'数量: {order.executed.size}, '
                         f'手续费: {order.executed.comm:.2f}')
                # 将成交信息同步到BaseStrategy
                hist_data = self.historical_data[stock_code]
                current_idx = len(hist_data) - 1
                self.base_strategy._execute_sell_order(stock_code, trade_dt, trade_price, quantity=abs(trade_size), hist_data=hist_data, current_idx=current_idx)
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'订单取消/拒绝: {order.status}')

    def notify_trade(self, trade):
        """交易通知"""
        if not trade.isclosed:
            return

        self.log(f'交易盈亏: 毛利润 {trade.pnl:.2f}, 净利润 {trade.pnlcomm:.2f}')

    def next(self):
        """
        backtrader的主要策略逻辑入口点

        这个方法会在每个交易日被调用，我们在这里适配BaseStrategy的逻辑
        """

        # 更新历史数据
        self._update_historical_data()

        # 获取当前数据
        current_data = self.datas[0]
        current_price = current_data.close[0]

        # 构造股票代码（这里需要根据实际情况调整）
        stock_code = getattr(current_data, '_name', 'UNKNOWN')
        if hasattr(stock_code, 'split'):
            stock_code = stock_code.split('.')[0]
        self.current_stock_code = stock_code

        # 检查数据长度是否足够
        if len(self.historical_data.get(stock_code, [])) < self.params.min_data_length:
            return

        hist_data = self.historical_data[stock_code]
        current_idx = len(hist_data) - 1

        # 检查当前持仓 - 通过BaseStrategy的get_position方法获取
        pos = self.base_strategy.get_position(stock_code)
        position_size = pos.volume_long if pos else 0

        if position_size > 0:
            # 已有持仓，检查卖出条件
            if self.base_strategy.should_sell(pos, hist_data, current_idx):
                self.log(f'卖出信号: {stock_code} @{current_price:.2f}')
                self.sell(size=position_size)
        else:
            # 无持仓，检查买入条件
            if self.base_strategy.should_buy(hist_data, current_idx):
                # 计算买入数量
                available_cash = self.broker.get_cash()
                quantity = self.base_strategy.calculate_buy_quantity(current_price, available_cash)

                if quantity >= 100:  # 确保至少买入一手
                    self.log(f'买入信号: {stock_code} @{current_price:.2f}, 数量: {quantity}')
                    self.buy(size=quantity)

    def _update_historical_data(self):
        """更新历史数据"""
        current_data = self.datas[0]
        stock_code = getattr(current_data, '_name', 'UNKNOWN')
        if hasattr(stock_code, 'split'):
            stock_code = stock_code.split('.')[0]

        # 获取当前K线数据
        current_bar = {
            'open': current_data.open[0],
            'high': current_data.high[0],
            'low': current_data.low[0],
            'close': current_data.close[0],
            'volume': current_data.volume[0],
            'date': self.datas[0].datetime.date(0)
        }

        # 初始化或更新历史数据
        if stock_code not in self.historical_data:
            self.historical_data[stock_code] = pd.DataFrame()

        # 将当前K线添加到历史数据中
        new_row = pd.DataFrame([current_bar])
        self.historical_data[stock_code] = pd.concat([self.historical_data[stock_code], new_row], ignore_index=True)

        # 保持数据长度在合理范围内（例如最多保留100根K线）
        if len(self.historical_data[stock_code]) > self.params.his_data_length:
            self.historical_data[stock_code] = self.historical_data[stock_code].tail(self.params.his_data_length).reset_index(drop=True)


    def stop(self):
        """策略结束时的清理工作"""
        self.log(f'策略结束，最终资产: {self.broker.get_value():.2f}')

        # 打印交易总结
        print(f"\n=== {self.strategy.strategy_name} 回测结果 ===")
        print(f"初始资金: {self.params.init_cash:,.2f}")
        print(f"最终资产: {self.broker.get_value():,.2f}")
        print(f"总收益: {self.broker.get_value() - self.params.init_cash:,.2f}")
        print(f"收益率: {(self.broker.get_value() / self.params.init_cash - 1) * 100:.2f}%")
