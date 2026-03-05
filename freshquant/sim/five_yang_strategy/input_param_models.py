"""
五阳策略输入参数模型
"""

from freshquant.sim.base_strategy.input_param_models import (
    InputParamModel,
    MarketDirection,
)


class FiveYangInputParamModel(InputParamModel):
    """
    五阳策略输入参数模型

    定义五阳策略的运行参数，包括止损止盈比例、ATR周期等
    """

    def __init__(
        self,
        var_chan_1d_market_direction: MarketDirection | None = None,
        var_chan_60m_market_direction: MarketDirection | None = None,
        var_chan_30m_market_direction: MarketDirection | None = None,
        var_atr_period: int = 20,
        var_atr_multiplier: float = 2.0,
        var_profit_loss_ratio: float = 1.0,
        var_min_volume_ratio: float = 0.7,
    ):
        """
        初始化五阳策略参数

        参数:
        var_chan_1d_market_direction: 日线趋势方向，默认多头
        var_chan_60m_market_direction: 60分钟趋势方向，默认多头
        var_chan_30m_market_direction: 30分钟趋势方向，默认空头
        var_atr_period: ATR计算周期，默认20天
        var_atr_multiplier: ATR倍数，用于计算止损价，默认2.0
        var_profit_loss_ratio: 止盈止损比例，默认1.0（1:1）
        var_min_volume_ratio: 最小成交量比例，用于判断成交量是否萎缩，默认0.7
        """
        # 调用父类初始化
        super().__init__()

        # 设置参数并进行验证
        self.set_param(
            'var_atr_period',
            var_atr_period,
            int,
            (1, 100),
            'ATR计算周期，用于计算止损价',
        )
        self.set_param(
            'var_atr_multiplier',
            var_atr_multiplier,
            float,
            (0.5, 5.0),
            'ATR倍数，用于计算止损价（止损价 = 成交价 - ATR * 倍数）',
        )
        self.set_param(
            'var_profit_loss_ratio',
            var_profit_loss_ratio,
            float,
            (0.5, 5.0),
            '止盈止损比例（止盈价 = 成本价 + (成本价 - 止损价) * 比例）',
        )
        self.set_param(
            'var_min_volume_ratio',
            var_min_volume_ratio,
            float,
            (0.1, 1.0),
            '最小成交量比例，用于判断成交量是否萎缩',
        )
        # 设置市场方向参数（允许None值）
        if var_chan_1d_market_direction is not None:
            self.set_param(
                'var_chan_1d_market_direction',
                var_chan_1d_market_direction,
                MarketDirection,
                None,
                '日线趋势方向',
            )
        else:
            self._params['var_chan_1d_market_direction'] = None
            self._param_descriptions['var_chan_1d_market_direction'] = '日线趋势方向'

        if var_chan_60m_market_direction is not None:
            self.set_param(
                'var_chan_60m_market_direction',
                var_chan_60m_market_direction,
                MarketDirection,
                None,
                '60分钟趋势方向',
            )
        else:
            self._params['var_chan_60m_market_direction'] = None
            self._param_descriptions['var_chan_60m_market_direction'] = '60分钟趋势方向'

        if var_chan_30m_market_direction is not None:
            self.set_param(
                'var_chan_30m_market_direction',
                var_chan_30m_market_direction,
                MarketDirection,
                None,
                '30分钟趋势方向',
            )
        else:
            self._params['var_chan_30m_market_direction'] = None
            self._param_descriptions['var_chan_30m_market_direction'] = '30分钟趋势方向'
