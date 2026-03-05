"""
CLXS策略输入参数模型
"""

from freshquant.sim.base_strategy.input_param_models import InputParamModel


class ClxsInputParamModel(InputParamModel):
    """
    CLXS策略输入参数模型

    定义CLXS策略的运行参数，包括model_opt等
    """

    def __init__(
        self,
        var_model_opt: int = 10001,
        var_wave_opt: int = 1560,
        var_stretch_opt: int = 0,
        var_trend_opt: int = 1,
        var_atr_period: int = 20,
        var_atr_multiplier: float = 2.0,
        var_profit_loss_ratio: float = 1.0,
    ):
        """
        初始化CLXS策略参数

        参数:
        var_model_opt: 模型选项，可选值: 10000, 10001, 10002, 10003, 10004, 10005, 10006, 10007, 10008, 10009, 10010, 10011, 10012，默认10001
        var_wave_opt: 波浪选项，默认1560
        var_stretch_opt: 拉伸选项，默认0
        var_trend_opt: 趋势选项，默认1
        var_atr_period: ATR计算周期，默认20天
        var_atr_multiplier: ATR倍数，用于计算止损价，默认2.0
        var_profit_loss_ratio: 止盈止损比例，默认1.0（1:1）
        """
        super().__init__()

        # 设置参数并进行验证
        self.set_param(
            'var_model_opt',
            var_model_opt,
            int,
            [1, 10001, 10002, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            'CLXS模型选项，用于选择策略变体',
        )
        self.set_param(
            'var_wave_opt',
            var_wave_opt,
            int,
            (1, 10000),
            '波浪选项参数',
        )
        self.set_param(
            'var_stretch_opt',
            var_stretch_opt,
            int,
            (0, 100),
            '拉伸选项参数',
        )
        self.set_param(
            'var_trend_opt',
            var_trend_opt,
            int,
            (0, 10),
            '趋势选项参数',
        )
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
