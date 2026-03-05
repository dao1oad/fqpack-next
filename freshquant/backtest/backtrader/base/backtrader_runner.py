import backtrader as bt
import pandas as pd
from freshquant.backtest.backtrader.base.backtrader_adapter import BacktraderStrategyAdapter
from datetime import datetime, timedelta
from freshquant.data.stock import fq_data_stock_fetch_day

class BacktraderRunner:
    """
    Backtrader回测运行器

    提供便捷的方法来运行BaseStrategy的backtrader回测
    """

    def __init__(self, base_strategy_class: type, init_cash: float = 1000000):
        """
        初始化回测运行器

        参数:
        base_strategy_class: BaseStrategy的子类
        init_cash: 初始资金
        """
        self.base_strategy_class = base_strategy_class
        self.init_cash = init_cash
        self.cerebro = bt.Cerebro()
        self.cerebro.broker.set_coc(True)

    def get_real_stock_data(self, stock_code, start_date=None, end_date=None):
        """
        获取真实股票数据用于回测

        参数:
        stock_code: str, 股票代码，如 '000001', '600000'
        start_date: datetime, 开始日期
        end_date: datetime, 结束日期

        返回:
        pd.DataFrame: 包含OHLCV数据的DataFrame
        """
        if start_date is None:
            start_date = datetime.now() - timedelta(days=365)  # 默认获取一年数据
        if end_date is None:
            end_date = datetime.now()

        print(f"正在获取股票 {stock_code} 的历史数据...")
        print(f"数据范围: {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')}")

        try:
            # 使用项目内置的数据获取函数
            data = fq_data_stock_fetch_day(stock_code, start_date, end_date)

            if data is None or len(data) == 0:
                print(f"警告: 无法获取股票 {stock_code} 的数据")
                return None

            # 转换数据格式以适配backtrader
            # 确保数据包含必要的列
            required_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in required_columns:
                if col not in data.columns:
                    print(f"错误: 数据缺少必要列 {col}")
                    return None

            # 重新整理数据格式
            result_data = pd.DataFrame({
                'open': data['open'],
                'high': data['high'],
                'low': data['low'],
                'close': data['close'],
                'volume': data['volume']
            })

            # 使用datetime作为索引
            if 'datetime' in data.columns:
                result_data.index = pd.to_datetime(data['datetime'])
            else:
                result_data.index = data.index

            # 确保索引是datetime类型
            if not isinstance(result_data.index, pd.DatetimeIndex):
                result_data.index = pd.to_datetime(result_data.index)

            # 排序并去重
            result_data = result_data.sort_index()
            result_data = result_data[~result_data.index.duplicated(keep='first')]

            print(f"成功获取 {len(result_data)} 条数据记录")
            print(f"数据范围: {result_data.index[0]} 到 {result_data.index[-1]}")

            return result_data

        except Exception as e:
            print(f"获取股票数据时出错: {e}")
            return None

    def add_data(self, data_feed, name: str = None):
        """
        添加数据源

        参数:
        data_feed: backtrader数据源
        name: 数据源名称
        """

        if name:
            data_feed._name = name

        self.cerebro.adddata(data_feed)

    def add_data_from_dataframe(self, df: pd.DataFrame, name: str = None):
        """
        从DataFrame添加数据源

        参数:
        df: 包含OHLCV数据的DataFrame
        name: 数据源名称
        """
        # 确保DataFrame有正确的列名和索引
        if 'date' in df.columns:
            df = df.set_index('date')

        # 创建backtrader数据源
        data_feed = bt.feeds.PandasData(
            dataname=df,
            datetime=None,  # 使用索引作为日期
            open='open',
            high='high',
            low='low',
            close='close',
            volume='volume',
            openinterest=-1
        )

        self.add_data(data_feed, name)

    def run(self, strategy_name: str = None, strategy_id: str = None, lot_size: int = None, **strategy_kwargs):
        """
        运行回测

        参数:
        strategy_name: 策略名称
        strategy_id: 策略ID
        lot_size: 每次买入金额限制
        **strategy_kwargs: 传递给BaseStrategy的额外参数

        返回:
        list: 回测结果
        """
        if self.cerebro is None:
            raise ValueError("请先添加数据源")

        # 设置初始资金
        self.cerebro.broker.setcash(self.init_cash)

        # 设置手续费（万分之三）
        self.cerebro.broker.setcommission(commission=0.0003)

        # 准备策略参数
        adapter_params = {
            'strategy_class': self.base_strategy_class,
            'init_cash': self.init_cash,
            'lot_size': lot_size or 3000,
            'strategy_kwargs': strategy_kwargs,
            'nodatabase': True
        }

        # 添加策略
        self.cerebro.addstrategy(BacktraderStrategyAdapter, **adapter_params)

        # 添加分析器
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

        print(f'回测开始，初始资金: {self.init_cash:,.2f}')
        print(f'策略类: {self.base_strategy_class.__name__}')

        # 运行回测
        results = self.cerebro.run()

        print(f'回测结束，最终资金: {self.cerebro.broker.getvalue():,.2f}')

        # 打印分析结果
        self._print_analysis(results[0])

        return results

    def _print_analysis(self, result):
        """打印分析结果"""
        print("\n=== 回测分析结果 ===")

        # 夏普比率
        if hasattr(result.analyzers.sharpe, 'get_analysis'):
            sharpe = result.analyzers.sharpe.get_analysis()
            if 'sharperatio' in sharpe and sharpe['sharperatio'] is not None:
                print(f"夏普比率: {sharpe['sharperatio']:.4f}")

        # 最大回撤
        if hasattr(result.analyzers.drawdown, 'get_analysis'):
            drawdown = result.analyzers.drawdown.get_analysis()
            if 'max' in drawdown:
                print(f"最大回撤: {drawdown['max']['drawdown']:.2f}%")

        # 收益率
        if hasattr(result.analyzers.returns, 'get_analysis'):
            returns = result.analyzers.returns.get_analysis()
            if 'rtot' in returns:
                print(f"总收益率: {returns['rtot']:.2f}%")

        # 胜率
        if hasattr(result.analyzers.trades, 'get_analysis'):
            trades = result.analyzers.trades.get_analysis()
            if 'total' in trades and 'won' in trades['total']:
                total_trades = trades['total']['total']
                won_trades = trades['total']['won']
                if total_trades > 0:
                    win_rate = (won_trades / total_trades) * 100
                    print(f"胜率: {win_rate:.2f}% ({won_trades}/{total_trades})")
                else:
                    print("胜率: 无交易记录")

    def plot(self, portfolio_only=False, no_kline=True, **kwargs):
        """
        绘制回测结果图表

        参数:
        portfolio_only: 是否只显示资金曲线，不显示个股买卖点
        no_kline: 是否不显示K线图（默认为True，不显示K线）
        **kwargs: 传递给cerebro.plot()的其他参数
        """
        if self.cerebro:
            if portfolio_only or no_kline:
                # 只显示资金曲线，不显示K线图和买卖点
                plot_kwargs = {
                    'volume': False,      # 不显示成交量
                    'plotdist': 0.0,      # 图表间距为0
                    'plotdata': False,    # 不显示K线数据
                    **kwargs
                }
                self.cerebro.plot(**plot_kwargs)
            else:
                # 显示完整图表（包括K线图）
                self.cerebro.plot(**kwargs)
