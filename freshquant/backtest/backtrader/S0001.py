import backtrader as bt
import pandas as pd
import argparse
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import base64
from io import BytesIO
from backtrader.analyzers import (SQN, TimeReturn, SharpeRatio)
from tqdm import tqdm
from freshquant.instrument.stock import fq_inst_fetch_stock_list
from fqchan04 import fq_recognise_bi # type: ignore
from datetime import datetime, timedelta
from fqcopilot import fq_calc_s0001 # type: ignore
from freshquant.quote.index import fq_quote_fetch_index_day_adv
from freshquant.quote.stock import fq_quote_QA_fetch_stock_day_adv

class S0001Strategy(bt.Strategy):
    params = (
        ("ror", 1),  # 默认盈亏比为1
    ) 

    def __init__(self):
        self.order = {}
        self.buy_price = {}
        self.stop_price = {}
        self.win_price = {}
        self.total_length = 0
        self.total_bars = 0
        self.trades = []

    def start(self):
        for i, data in enumerate(self.datas):
            if data.buflen() > self.total_length:
                self.total_length = data.buflen()
        self.progress_bar = tqdm(total=self.total_length, desc="Backtesting Progress")

    def prenext(self):
        self.next()

    def next(self):
        self.progress_bar.update(1)
        for i, data in enumerate(self.datas):
            if data.datetime[0] != self.data.datetime[0]:
                continue
            data_len = len(data)
            data_high = data.high.get(0, size=data_len)
            data_low = data.low.get(0, size=data_len)
            data_close = data.close.get(0, size=data_len)
            bi = fq_recognise_bi(data_len, data_high, data_low)
            sigs = fq_calc_s0001(data_len, data_high, data_low, data_close, 1560, 0, 1)
            if len(sigs) == 0:
                continue
            position = self.getposition(data)
            if sigs[-1] == 1:
                if position is None or position.size == 0:
                    size = int(self.broker.getcash() * 0.02 / data.close[0])
                    self.order[i] = self.buy(data=data, size=size)
                    self.buy_price[i] = data.close[0]
                    for s in range(len(bi), 0, -1):
                        if bi[s-1] == -1:
                            self.stop_price[i] = data_low[s-1]
                            self.win_price[i] = self.buy_price[i] + self.params.ror * (self.buy_price[i] - self.stop_price[i])
                            break
            if position is not None and position.size > 0:
                if self.stop_price.get(i) and data.close[0] < self.stop_price.get(i):
                    self.order[i] = self.close(data=data)
                    self.buy_price[i] = None
                    self.stop_price[i] = None
                    self.win_price[i] = None
                if self.win_price.get(i) and data.close[0] > self.win_price.get(i):
                    self.order[i] = self.close(data=data)
                    self.buy_price[i] = None
                    self.win_price[i] = None

    def notify_order(self, order):
        # 如果 order 为 submitted/accepted,返回空
        if order.status in [order.Submitted, order.Accepted]:
            return
        # 如果order为buy/sell executed,报告价格结果
        if order.status in [order.Completed]:
            if order.isbuy():
                print(
                    f"{bt.num2date(order.executed.dt)} {order.data._name} 买入: 价格:{order.executed.price:.2f}, 成本:{order.executed.value:.2f}, 手续费:{order.executed.comm:.2f}"
                )
                self.buyprice = order.executed.price
                self.buycomm = order.executed.comm
            else:
                print(
                    f"{bt.num2date(order.executed.dt)} {order.data._name} 卖出: 价格：{order.executed.price:.2f}, 成本: {order.executed.value:.2f}, 手续费{order.executed.comm:.2f}"
                )

            # 如果指令取消/交易失败, 报告结果
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            pass


    def notify_trade(self, trade):
        if not trade.isclosed:
            self.trades.append({
                'ref': trade.ref,
                'code': trade.data._name,
                'pnl': trade.pnl,
                'pnlcomm': trade.pnlcomm,
                'size': trade.size,
                'price': trade.price,
                'value': trade.value,
                'commission': trade.commission,
                'justopened': trade.justopened,
                'isopen': trade.isopen,
                'isclosed': trade.isclosed,
                'dtopen': bt.num2date(trade.dtopen),
                'dtclose': bt.num2date(trade.dtclose) if trade.isclosed else None,
            })
        else:
            for t in self.trades:
                if t['ref'] == trade.ref:
                    t.update({
                        'ref': trade.ref,
                        'code': trade.data._name,
                        'pnl': trade.pnl,
                        'pnlcomm': trade.pnlcomm,
                        'size': trade.size,
                        'price': trade.price,
                        'value': trade.value,
                        'commission': trade.commission,
                        'justopened': trade.justopened,
                        'isopen': trade.isopen,
                        'isclosed': trade.isclosed,
                        'dtopen': bt.num2date(trade.dtopen),
                        'dtclose': bt.num2date(trade.dtclose) if trade.isclosed else None,
                    })
                    break
            print(f"{bt.num2date(trade.dtclose)} {trade.data._name} 策略收益：毛收益 {trade.pnl:.2f}, 净收益 {trade.pnlcomm:.2f}")
    
    def stop(self):
        pass

def plot_returns(returns, start_date, end_date):
    """生成收益率曲线图"""
    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei']  # 用来正常显示中文标签
    plt.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号
    
    plt.figure(figsize=(12, 6))
    
    # 计算累计收益率
    cumulative_returns = (1 + returns).cumprod() - 1
    
    # 绘制曲线
    plt.plot(cumulative_returns.index, cumulative_returns.values * 100, 'b-', label='累计收益率(%)')
    
    # 设置图表格式
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.title('策略累计收益率变化', pad=15, fontsize=12)
    plt.xlabel('日期', fontsize=10)
    plt.ylabel('收益率(%)', fontsize=10)
    
    # 设置x轴日期格式
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.gcf().autofmt_xdate()  # 自动旋转日期标签
    
    # 添加图例
    plt.legend(loc='best', fontsize=10)
    
    # 调整布局
    plt.tight_layout()
    
    # 保存图片到内存
    buffer = BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight', dpi=300)
    buffer.seek(0)
    image_png = buffer.getvalue()
    buffer.close()
    plt.close()
    
    # 转换为base64字符串
    graph_url = base64.b64encode(image_png).decode('utf-8')
    return graph_url

def plot_returns_comparison(returns_dict, index_data, start_date, end_date):
    """生成多个盈亏比的收益率对比曲线图"""
    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei']
    plt.rcParams['axes.unicode_minus'] = False
    
    plt.figure(figsize=(15, 8))
    
    # 设置更丰富的颜色方案
    colors = {
        1: '#FF6B6B',     # 红色
        30: '#4ECDC4',    # 青色
        46: '#45B7D1',    # 蓝色
        56: '#96CEB4',    # 绿色
        'index': '#FFD93D'  # 黄色（用于上证指数）
    }
    
    # 绘制每个盈亏比的曲线
    for ror, returns in returns_dict.items():
        # 计算累计收益率
        cumulative_returns = (1 + returns).cumprod() - 1
        # 绘制曲线
        plt.plot(cumulative_returns.index, cumulative_returns.values * 100, 
                color=colors[ror], label=f'盈亏比 {ror}:1', linewidth=2)
    
    # 处理并绘制上证指数
    index_returns = index_data['close'].pct_change()
    index_cumulative = (1 + index_returns).cumprod() - 1
    plt.plot(index_returns.index, index_cumulative * 100,
            color=colors['index'], label='上证指数', linewidth=2, linestyle='--')
    
    # 设置图表格式
    plt.grid(True, linestyle='--', alpha=0.3)
    plt.title('策略收益率与上证指数对比', pad=15, fontsize=14)
    plt.xlabel('日期', fontsize=12)
    plt.ylabel('收益率(%)', fontsize=12)
    
    # 设置x轴日期格式
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.gcf().autofmt_xdate()
    
    # 添加图例
    plt.legend(loc='best', fontsize=12, framealpha=0.8)
    
    # 添加网格
    plt.grid(True, linestyle='--', alpha=0.2)
    
    # 调整布局
    plt.tight_layout()
    
    # 保存图片到内存
    buffer = BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight', dpi=300)
    buffer.seek(0)
    image_png = buffer.getvalue()
    buffer.close()
    plt.close()
    
    return base64.b64encode(image_png).decode('utf-8')

def run_backtest(start_cash, stake, commission_fee, ror, start_date, end_date):
    """运行单个回测"""
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(start_cash)
    cerebro.broker.setcommission(commission=commission_fee)
    cerebro.addsizer(bt.sizers.FixedSize, stake=stake)

    # 获取上证指数数据
    data_index = fq_quote_fetch_index_day_adv('000001', start_date, end_date)
    data_index = data_index.reset_index(level=1, drop=True, inplace=False)
    data_index = data_index.rename_axis('datetime')
    data_index_bt = bt.feeds.PandasData(
        dataname=data_index, fromdate=start_date, todate=end_date
    )
    cerebro.adddata(data_index_bt, name="上证指数")

    stock_list = fq_inst_fetch_stock_list()
    total_stocks = len(stock_list)
    stock_count = 0
    for stock in tqdm(stock_list, desc=f"Loading Data (ROR={ror})", total=total_stocks):
        data_df = fq_quote_QA_fetch_stock_day_adv(stock["code"], start_date, end_date)
        if data_df is not None and len(data_df) > 0:
            data_df = data_df.reset_index(level=1, drop=True, inplace=False)
            data_df = data_df.rename_axis('datetime')
            data = bt.feeds.PandasData(
                dataname=data_df, fromdate=start_date, todate=end_date
            )
            cerebro.adddata(data, name=stock["code"])
            stock_count += 1

    cerebro.addstrategy(S0001Strategy, ror=ror)
    cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')

    result = cerebro.run(maxcpus=None)
    strat = result[0]
    
    # 获取回测结果
    port_value = cerebro.broker.getvalue()
    pnl = port_value - start_cash
    
    # 获取收益率数据
    pyfoliozer = strat.analyzers.getbyname('pyfolio')
    returns, _, _, _ = pyfoliozer.get_pf_items()
    
    if not isinstance(returns, pd.Series):
        returns = pd.Series(returns)
    returns.index = pd.to_datetime(returns.index).date
    returns.index = pd.to_datetime(returns.index)
    returns = returns.astype(float)
    
    return returns, port_value, pnl, stock_count, data_index

def main(start_cash=1000000, stake=100, commission_fee=0.001):
    start_date = datetime.now() - timedelta(days=5000)
    end_date = datetime.now()
    
    # 定义要测试的盈亏比
    ror_list = [1, 30, 46, 56]
    returns_dict = {}
    results = []
    index_data = None
    
    # 运行每个盈亏比的回测
    for ror in ror_list:
        print(f"\n开始运行盈亏比 {ror}:1 的回测...")
        returns, port_value, pnl, stock_count, data_index = run_backtest(
            start_cash, stake, commission_fee, ror, start_date, end_date
        )
        returns_dict[ror] = returns
        results.append({
            'ror': ror,
            'port_value': port_value,
            'pnl': pnl,
            'stock_count': stock_count
        })
        if index_data is None:
            index_data = data_index
        print(f"盈亏比 {ror}:1 回测完成")
        print(f"总资金: {round(port_value, 2)}")
        print(f"净收益: {round(pnl, 2)}")
    
    # 生成对比图
    graph_url = plot_returns_comparison(returns_dict, index_data, start_date, end_date)
    
    # 生成HTML报告
    html_content = [
        '<html><head><title>S0001回测报告-盈亏比对比</title>',
        '<style>',
        'body { font-family: Arial, sans-serif; margin: 20px; }',
        '.summary { margin-bottom: 20px; }',
        '.chart { margin: 20px 0; text-align: center; }',
        '.chart img { max-width: 100%; height: auto; }',
        'table { border-collapse: collapse; width: 100%; margin: 20px 0; }',
        'th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }',
        'th { background-color: #f5f5f5; }',
        '</style></head><body>',
        '<h1>S0001回测报告-盈亏比对比</h1>',
        '<div class="summary">',
        f'<p>初始资金: {start_cash:,.2f}</p>',
        f'<p>回测期间：{start_date.strftime("%Y%m%d")}:{end_date.strftime("%Y%m%d")}</p>',
        '</div>',
        '<table>',
        '<tr><th>盈亏比</th><th>总资金</th><th>净收益</th><th>股票数量</th></tr>'
    ]
    
    for result in results:
        html_content.append(
            f'<tr><td>{result["ror"]}:1</td>'
            f'<td>{result["port_value"]:,.2f}</td>'
            f'<td>{result["pnl"]:,.2f}</td>'
            f'<td>{result["stock_count"]}</td></tr>'
        )
    
    html_content.extend([
        '</table>',
        '<div class="chart">',
        f'<img src="data:image/png;base64,{graph_url}" alt="收益率对比曲线">',
        '</div>',
        '</body></html>'
    ])
    
    # 保存HTML报告
    with open('S0001_STATS_COMPARISON.html', 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_content))
    print("\n已生成对比报告")

if __name__ == '__main__':
    main(start_cash=1000000, stake=100, commission_fee=0.001)
