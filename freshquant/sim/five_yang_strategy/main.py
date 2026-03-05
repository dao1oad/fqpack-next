import traceback
from datetime import timedelta
from typing import Dict, Optional

import pandas as pd

from freshquant.analysis.chanlun_analysis import calculate_trading_signals
from freshquant.data.stock import fq_data_stock_fetch_day
from freshquant.quantaxis.qamarket.qaposition import QA_Position
from freshquant.sim.base_strategy.input_data_models import InputDataModel
from freshquant.sim.base_strategy.input_param_models import MarketDirection
from freshquant.sim.base_strategy.main import BaseStrategy
from freshquant.sim.five_yang_strategy.input_param_models import FiveYangInputParamModel

"""
五阳策略模拟交易 - 使用QIFI Account方式

基于五阳上阵策略的当日交易:
1. 每次下单买入限制金额2000元，超过2000元的最低买一手
2. 检测到五阳形态时买入，除非资金不足
3. 持仓股票符合卖出条件时卖出

策略特点:
- 基于五阳上阵技术形态
- 当日信号当日处理
- 适合震荡和上涨市场，熊市风险较大
"""


class FiveYangStrategy(BaseStrategy):
    """
    五连阳动量跟随策略类

    基于五阳上阵技术形态的股票交易策略，适合震荡和上涨市场。
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
        input_param_model: 输入参数模型，如果不提供则使用默认的FiveYangInputParamModel
        """
        # 如果没有提供input_data_model，使用默认的InputDataModel
        if input_data_model is None:
            input_data_model = InputDataModel(data_length={'1d': 30})

        # 如果没有提供input_param_model，使用默认的FiveYangInputParamModel
        if input_param_model is None:
            input_param_model = FiveYangInputParamModel()

        # 生成策略名称和ID
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
        self.min_data_length = 5  # 至少需要5根K线

    @staticmethod
    def _generate_strategy_name(input_param_model: FiveYangInputParamModel) -> str:
        """
        根据输入参数生成策略名称

        参数:
        input_param_model: 输入参数模型

        返回:
        str: 策略名称
        """
        base_name = "五连阳动量跟随策略"

        # 获取三个周期的市场方向参数
        direction_1d = input_param_model.get_param('var_chan_1d_market_direction')
        direction_60m = input_param_model.get_param('var_chan_60m_market_direction')
        direction_30m = input_param_model.get_param('var_chan_30m_market_direction')

        # 如果所有方向参数都是None，返回基础名称
        if direction_1d is None and direction_60m is None and direction_30m is None:
            return base_name

        # 方向映射
        direction_map = {
            MarketDirection.LONG: "多",
            MarketDirection.SHORT: "空",
            MarketDirection.NEUTRAL: "中",
        }

        # 构建方向后缀
        direction_parts = []
        if direction_1d is not None:
            direction_parts.append(f"日{direction_map[direction_1d]}")
        if direction_60m is not None:
            direction_parts.append(f"60{direction_map[direction_60m]}")
        if direction_30m is not None:
            direction_parts.append(f"30{direction_map[direction_30m]}")

        # 组合完整名称
        if direction_parts:
            return f"{base_name}-{''.join(direction_parts)}"
        return base_name

    def _get_market_direction_from_signals(self, signals: Dict) -> MarketDirection:
        """
        根据缠论信号判断市场方向

        参数:
        signals: calculate_trading_signals返回的信号字典

        返回:
        MarketDirection: 市场方向
        """
        # 获取所有买点和卖点信号的索引
        buy_indices = []
        sell_indices = []

        # 收集买点信号索引
        # buy_zs_huila, buy_v_reverse, macd_bullish_divergence 都是字典，包含 'idx' 列表
        buy_zs_huila = signals.get('buy_zs_huila', {})
        if isinstance(buy_zs_huila, dict) and 'idx' in buy_zs_huila:
            buy_indices.extend(buy_zs_huila['idx'])

        buy_v_reverse = signals.get('buy_v_reverse', {})
        if isinstance(buy_v_reverse, dict) and 'idx' in buy_v_reverse:
            buy_indices.extend(buy_v_reverse['idx'])

        macd_bullish = signals.get('macd_bullish_divergence', {})
        if isinstance(macd_bullish, dict) and 'idx' in macd_bullish:
            buy_indices.extend(macd_bullish['idx'])

        # 收集卖点信号索引
        sell_zs_huila = signals.get('sell_zs_huila', {})
        if isinstance(sell_zs_huila, dict) and 'idx' in sell_zs_huila:
            sell_indices.extend(sell_zs_huila['idx'])

        sell_v_reverse = signals.get('sell_v_reverse', {})
        if isinstance(sell_v_reverse, dict) and 'idx' in sell_v_reverse:
            sell_indices.extend(sell_v_reverse['idx'])

        macd_bearish = signals.get('macd_bearish_divergence', {})
        if isinstance(macd_bearish, dict) and 'idx' in macd_bearish:
            sell_indices.extend(macd_bearish['idx'])

        # 如果没有任何信号，返回中性
        if not buy_indices and not sell_indices:
            return MarketDirection.NEUTRAL

        # 找到最后出现的信号索引
        last_buy_idx = max(buy_indices) if buy_indices else -1
        last_sell_idx = max(sell_indices) if sell_indices else -1

        # 比较最后的买点和卖点
        if last_buy_idx > last_sell_idx:
            return MarketDirection.LONG
        elif last_sell_idx > last_buy_idx:
            return MarketDirection.SHORT
        else:
            return MarketDirection.NEUTRAL

    def should_buy(self, pos, market_data):
        """
        判断是否应该买入 - 检测五阳形态并验证多周期缠论状态

        参数:
        pos: 持仓对象
        market_data: 市场数据字典，格式为 {'1d': DataFrame, '60m': DataFrame, '30m': DataFrame, ...}

        返回:
        bool: 是否应该买入
        """
        # 获取日线数据
        if '1d' not in market_data:
            return False

        hist_data = market_data['1d']
        current_idx = len(hist_data) - 1

        # 需要至少5根K线
        if current_idx < 4:
            return False

        # 如果有6根及以上K线，检查五连阳第一天的前一天不是阳线
        if current_idx >= 5:  # 有6根及以上K线时才检查前一天
            pre_five_yang_idx = current_idx - 5  # 五连阳第一天的前一天
            pre_row = hist_data.iloc[pre_five_yang_idx]
            # 判断前一天是否为阳线
            is_pre_yang = pre_row['close'] > pre_row['open']
            if pre_five_yang_idx > 0:
                prev_prev_close = hist_data.iloc[pre_five_yang_idx - 1]['close']
                is_pre_yang = is_pre_yang or (pre_row['close'] > prev_prev_close)

            # 如果前一天是阳线，则不符合条件
            if is_pre_yang:
                return False

        # 检查最近5根K线是否都是阳线
        for i in range(5):
            current_k_idx = current_idx - 4 + i
            if current_k_idx < 0 or current_k_idx >= len(hist_data):
                return False

            row = hist_data.iloc[current_k_idx]
            # 阳线判断：收盘价>开盘价 或 收盘价>前一日收盘价
            is_yang = row['close'] > row['open']
            if current_k_idx > 0 and current_k_idx - 1 >= 0:
                prev_close = hist_data.iloc[current_k_idx - 1]['close']
                is_yang = is_yang or (row['close'] > prev_close)

            if not is_yang:  # 不是阳线
                return False

        # 检查成交量是否逐步放大（可选条件）
        volumes = []
        for i in range(5):
            current_k_idx = current_idx - 4 + i
            volumes.append(hist_data.iloc[current_k_idx]['volume'])

        # 至少最后一天成交量不能显著萎缩
        min_volume_ratio = self.input_param_model.get_param('min_volume_ratio', 0.7)
        if volumes[-1] < sum(volumes[:-1]) / 4 * min_volume_ratio:
            return False

        # 检查多周期缠论状态
        try:
            # 检查日线周期状态
            expected_1d_direction = self.input_param_model.get_param(
                'var_chan_1d_market_direction'
            )
            if expected_1d_direction and '1d' in market_data:
                signals_1d = calculate_trading_signals(market_data['1d'])
                actual_1d_direction = self._get_market_direction_from_signals(
                    signals_1d
                )
                if actual_1d_direction != expected_1d_direction:
                    return False

            # 检查60分钟周期状态
            expected_60m_direction = self.input_param_model.get_param(
                'var_chan_60m_market_direction'
            )
            if expected_60m_direction and '60m' in market_data:
                signals_60m = calculate_trading_signals(market_data['60m'])
                actual_60m_direction = self._get_market_direction_from_signals(
                    signals_60m
                )
                if actual_60m_direction != expected_60m_direction:
                    return False

            # 检查30分钟周期状态
            expected_30m_direction = self.input_param_model.get_param(
                'var_chan_30m_market_direction'
            )
            if expected_30m_direction and '30m' in market_data:
                signals_30m = calculate_trading_signals(market_data['30m'])
                actual_30m_direction = self._get_market_direction_from_signals(
                    signals_30m
                )
                if actual_30m_direction != expected_30m_direction:
                    return False

        except Exception as e:
            print(f"检查缠论状态时发生错误: {e}")
            traceback.print_exc()
            # 如果缠论分析出错，继续使用五阳形态判断
            pass

        return True

    def should_sell(self, pos: QA_Position, market_data):
        """
        判断是否应该卖出

        参数:
        pos: 持仓对象
        market_data: 市场数据字典，格式为 {'1d': DataFrame, '1w': DataFrame, ...}

        返回:
        True/False: 是否应该卖出
        """
        # 获取日线数据
        if '1d' not in market_data:
            return False

        hist_data = market_data['1d']
        current_idx = len(hist_data) - 1
        current_row = hist_data.iloc[current_idx]
        today_close = current_row['close']

        # 获取持仓成本价
        cost_price = pos.position_price_long

        # 获取参数
        atr_period = self.input_param_model.get_param('atr_period', 20)
        atr_multiplier = self.input_param_model.get_param('atr_multiplier', 2.0)
        profit_loss_ratio = self.input_param_model.get_param('profit_loss_ratio', 1.0)

        stop_loss_price = self.get_volume_long_stop_loss_price(pos.code)
        if not stop_loss_price:
            stop_loss_price = cost_price - atr_multiplier * self.calculate_atr(
                hist_data, period=atr_period
            )

        take_profit_price = (
            cost_price + (cost_price - stop_loss_price) * profit_loss_ratio
        )

        # 卖出条件：收盘价低于止损价或高于止盈价
        if today_close < stop_loss_price:
            return True
        elif today_close > take_profit_price:
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
        market_data: 市场数据字典，格式为 {'1d': DataFrame, '1w': DataFrame, ...}
        """
        try:
            # 获取日线数据
            if '1d' not in market_data:
                return

            hist_data = market_data['1d']
            current_idx = len(hist_data) - 1

            # 确保有足够的历史数据
            if current_idx < 4:
                return

            # 获取最近5天的数据
            recent_data = hist_data.iloc[current_idx - 4 : current_idx + 1]

            # 计算5天最高价和最低价的中间价格作为止损价1
            high_5d = recent_data['high'].max()
            low_5d = recent_data['low'].min()
            stop_loss_1 = (high_5d + low_5d) / 2

            # 获取参数
            atr_period = self.input_param_model.get_param('atr_period', 20)
            atr_multiplier = self.input_param_model.get_param('atr_multiplier', 2.0)

            # 使用BaseStrategy中的ATR计算函数
            atr = self.calculate_atr(hist_data, period=atr_period)

            # 计算price - atr_multiplier*atr作为止损价2
            stop_loss_2 = price - atr_multiplier * atr

            # 选择较低的价格作为最终止损价
            final_stop_loss = min(stop_loss_1, stop_loss_2)

            # 记录止损价信息
            print(f"成交回调 - 代码: {code}, 成交价: {price:.2f}, 成交量: {volume}")
            print(f"5天高低价中间价(止损价1): {stop_loss_1:.2f}")
            print(f"ATR止损价(止损价2): {stop_loss_2:.2f} (ATR: {atr:.2f})")
            print(f"最终止损价: {final_stop_loss:.2f}")

            self.set_volume_long_stop_loss_price(code, final_stop_loss)

        except Exception as e:
            print(f"设置止损价时发生错误: {e}")
            traceback.print_exc()


def main():
    # 创建输入数据模型
    input_data_model = InputDataModel(data_length={'1d': 1000})

    # 创建输入参数模型
    input_param_model = FiveYangInputParamModel(
        var_chan_1d_market_direction=None,
        var_chan_60m_market_direction=None,
        var_chan_30m_market_direction=None,
        var_atr_period=20,
        var_atr_multiplier=2.0,
        var_profit_loss_ratio=1.0,
        var_min_volume_ratio=0.7,
    )

    strategy = FiveYangStrategy(
        init_cash=1000000,
        lot_size=3000,
        nodatabase=False,
        input_data_model=input_data_model,
        input_param_model=input_param_model,
    )
    strategy.run_strategy()


if __name__ == '__main__':
    main()
