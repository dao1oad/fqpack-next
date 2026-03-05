"""
五阳策略Backtrader回测主程序

使用BacktraderStrategyAdapter和BacktraderRunner来回测FiveYangStrategy
使用真实股票数据进行回测
"""

from freshquant.sim.five_yang_strategy.main import FiveYangStrategy

from freshquant.backtest.backtrader.base.backtrader_tester import BacktraderTester, run_tester


class FiveYangStrategyTester(BacktraderTester):

    def __init__(self):
        self.strategy_class = FiveYangStrategy


if __name__ == "__main__":
    run_tester(FiveYangStrategyTester())
