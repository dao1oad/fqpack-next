"""
CLXS策略模拟交易

基于CLXS信号的当日交易策略:
1. 每次下单买入限制金额由lot_size控制
2. 检测到CLXS信号时买入，除非资金不足
3. 持仓股票符合卖出条件时卖出

策略特点:
- 基于fq_clxs信号
- 当日信号当日处理
- 支持13种model_opt变体（10001-10012）
"""

import traceback
from typing import Dict

import pandas as pd
from fqcopilot import fq_clxs

from freshquant.quantaxis.qamarket.qaposition import QA_Position
from freshquant.sim.base_strategy.input_data_models import InputDataModel
from freshquant.sim.base_strategy.main import BaseStrategy
from freshquant.sim.clxs_strategy.input_param_models import ClxsInputParamModel


class ClxsStrategy(BaseStrategy):
    """
    CLXS策略类

    基于fq_clxs信号的股票交易策略
    """

    def __init__(
        self,
        init_cash=1000000,
        lot_size=3000,
        nodatabase=True,
        input_data_model=None,
        input_param_model=None,
    ):
        """
        初始化策略

        参数:
        init_cash: 初始资金
        lot_size: 每次买入金额限制
        nodatabase: 是否使用数据库
        input_data_model: 输入数据模型，如果不提供则使用默认的InputDataModel
        input_param_model: 输入参数模型，如果不提供则使用默认的ClxsInputParamModel
        """
        if input_data_model is None:
            input_data_model = InputDataModel(data_length={'1d': 3000})

        if input_param_model is None:
            input_param_model = ClxsInputParamModel()

        strategy_name = self._generate_strategy_name(input_param_model)
        strategy_id = BaseStrategy.generate_strategy_id(strategy_name)

        super().__init__(
            strategy_name=strategy_name,
            strategy_id=strategy_id,
            init_cash=init_cash,
            lot_size=lot_size,
            nodatabase=nodatabase,
            input_data_model=input_data_model,
            input_param_model=input_param_model,
        )
        self.min_data_length = 5

    @staticmethod
    def _generate_strategy_name(input_param_model: ClxsInputParamModel) -> str:
        """
        根据输入参数生成策略名称

        参数:
        input_param_model: 输入参数模型

        返回:
        str: 策略名称
        """
        model_opt = input_param_model.get_param('var_model_opt', 10001)
        return f"CLX{str(model_opt).zfill(5)}"

    def _calculate_clxs_signals(self, hist_data: pd.DataFrame) -> list:
        """
        计算CLXS信号

        参数:
        hist_data: 历史数据DataFrame

        返回:
        list: CLXS信号列表
        """
        highs = hist_data.high.to_list()
        lows = hist_data.low.to_list()
        opens = hist_data.open.to_list()
        closes = hist_data.close.to_list()
        volumes = hist_data.volume.to_list()
        length = len(highs)

        wave_opt = self.input_param_model.get_param('var_wave_opt', 1560)
        stretch_opt = self.input_param_model.get_param('var_stretch_opt', 0)
        trend_opt = self.input_param_model.get_param('var_trend_opt', 1)
        model_opt = self.input_param_model.get_param('var_model_opt', 10001)

        return fq_clxs(
            length,
            highs,
            lows,
            opens,
            closes,
            volumes,
            wave_opt,
            stretch_opt,
            trend_opt,
            model_opt,
        )

    def should_buy(self, pos, market_data: Dict[str, pd.DataFrame]):
        """
        判断是否应该买入 - 检测CLXS信号

        参数:
        pos: 持仓对象
        market_data: 市场数据字典，格式为 {'1d': DataFrame, ...}

        返回:
        bool: 是否应该买入
        """
        if '1d' not in market_data:
            return False

        hist_data = market_data['1d']
        current_idx = len(hist_data) - 1

        if current_idx < self.min_data_length - 1:
            return False

        try:
            sigs = self._calculate_clxs_signals(hist_data)
            return sigs[-1] > 0
        except Exception as e:
            print(f"计算CLXS信号时发生错误: {e}")
            traceback.print_exc()
            return False

    def should_sell(self, pos: QA_Position, market_data: Dict[str, pd.DataFrame]):
        """
        判断是否应该卖出

        参数:
        pos: 持仓对象
        market_data: 市场数据字典，格式为 {'1d': DataFrame, ...}

        返回:
        bool: 是否应该卖出
        """
        if '1d' not in market_data:
            return False

        hist_data = market_data['1d']
        current_idx = len(hist_data) - 1
        current_row = hist_data.iloc[current_idx]
        today_close = current_row['close']

        cost_price = pos.position_price_long

        atr_period = self.input_param_model.get_param('var_atr_period', 20)
        atr_multiplier = self.input_param_model.get_param('var_atr_multiplier', 2.0)

        take_profit_price = cost_price + atr_multiplier * self.calculate_atr(
            hist_data, period=atr_period
        )

        # 卖出条件：收盘价高于止盈价（止损功能已随 Issue #603 下线）
        if today_close > take_profit_price:
            return True

        return False

    def on_deal_callback(self, code, price, volume, dt, market_data):
        """
        处理成交回报

        参数:
        code: 股票代码
        price: 成交价格
        volume: 成交数量
        dt: 成交时间
        market_data: 市场数据字典，格式为 {'1d': DataFrame, ...}
        """
        print(f"成交回调 - 代码: {code}, 成交价: {price:.2f}, 成交量: {volume}")


def main():
    """主函数示例"""
    input_data_model = InputDataModel(data_length={'1d': 3000})

    input_param_model = ClxsInputParamModel(
        var_model_opt=10001,
        var_wave_opt=1560,
        var_stretch_opt=0,
        var_trend_opt=1,
        var_atr_period=20,
        var_atr_multiplier=2.0,
    )

    strategy = ClxsStrategy(
        init_cash=1000000,
        lot_size=3000,
        nodatabase=False,
        input_data_model=input_data_model,
        input_param_model=input_param_model,
    )
    strategy.run_strategy()


if __name__ == '__main__':
    main()
