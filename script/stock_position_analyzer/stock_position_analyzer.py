#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
股票持仓盈亏分析脚本
"""

import json
import requests
from datetime import datetime
from typing import List, Dict, Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import track
from rich.table import Table

from freshquant.util.url import get_api_base_url
from freshquant.util.file_helper import write_file_with_mkdir


class StockPositionAnalyzer:
    def __init__(self, base_url: str | None = None):
        """初始化分析器

        Args:
            base_url: API 基础地址。如果为 None，则从配置文件或环境变量获取。
        """
        self.base_url = base_url if base_url is not None else get_api_base_url()

    def get_position_list(self, page: int = 1, size: int = 1000) -> List[Dict[str, Any]]:
        """获取持仓列表"""
        url = f"{self.base_url}/api/get_stock_position_list?page={page}&size={size}"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()

    def get_stock_detail(self, symbol: str) -> Dict[str, Any]:
        """获取股票详情，包括持仓成本和最新价格"""
        url = f"{self.base_url}/api/stock_data?period=1m&symbol={symbol}"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    
    def get_chanlun_signals(self, symbol: str, period: str) -> str:
        """获取缠论信号，返回'多'或'空'"""
        url = f"{self.base_url}/api/stock_data?period={period}&symbol={symbol}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            # 买点信号的key
            buy_signals = ['buy_zs_huila', 'buy_v_reverse', 'macd_bullish_divergence']
            # 卖点信号的key
            sell_signals = ['sell_zs_huila', 'sell_v_reverse', 'macd_bearish_divergence']
            
            latest_buy_idx = -1
            latest_sell_idx = -1
            
            # 找到最新的买点信号
            for signal_key in buy_signals:
                if signal_key in data and data[signal_key]['idx']:
                    idx_list = data[signal_key]['idx']
                    if idx_list:
                        latest_buy_idx = max(latest_buy_idx, max(idx_list))
            
            # 找到最新的卖点信号
            for signal_key in sell_signals:
                if signal_key in data and data[signal_key]['idx']:
                    idx_list = data[signal_key]['idx']
                    if idx_list:
                        latest_sell_idx = max(latest_sell_idx, max(idx_list))
            
            # 比较最新的买点和卖点信号
            if latest_buy_idx == -1 and latest_sell_idx == -1:
                return "-"
            elif latest_buy_idx > latest_sell_idx:
                return "多"
            else:
                return "空"
        except Exception as e:
            return "-"

    def calculate_cost_and_profit(self, position: Dict[str, Any], detail: Dict[str, Any]) -> Dict[str, Any]:
        """计算成本和盈亏"""
        stock_fills = detail.get('stock_fills', [])
        close_prices = detail.get('close', [])
        
        # 计算平均成本
        total_cost = 0
        total_quantity = 0
        for fill in stock_fills:
            total_cost += fill['amount']
            total_quantity += fill['quantity']
        
        avg_cost = total_cost / total_quantity if total_quantity > 0 else 0
        
        # 获取最新价格
        current_price = close_prices[-1] if close_prices else 0
        
        # 当前持仓数量
        current_quantity = position['quantity']
        
        # 计算盈亏
        current_value = current_quantity * current_price
        cost_value = current_quantity * avg_cost
        profit = current_value - cost_value
        profit_rate = (profit / cost_value * 100) if cost_value > 0 else 0
        
        # 获取最近一笔持仓时间并计算duration
        last_fill_time = "-"
        if stock_fills:
            # 假设stock_fills按时间排序，取最后一笔
            last_fill = stock_fills[-1]
            if 'date' in last_fill and 'time' in last_fill:
                try:
                    # 解析日期和时间 (date格式: 20250825, time格式: "09:48:05")
                    date_str = str(last_fill['date'])
                    time_str = last_fill['time']
                    datetime_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {time_str}"
                    
                    fill_datetime = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
                    now = datetime.now()
                    duration = now - fill_datetime
                    
                    # 计算天数和小时数
                    days = duration.days
                    hours = duration.seconds // 3600
                    
                    # 格式化输出
                    if days > 0:
                        last_fill_time = f"{days}天{hours}小时"
                    else:
                        last_fill_time = f"{hours}小时"
                except Exception:
                    last_fill_time = "-"
        
        # 计算网格盈亏
        grid_analysis = self.analyze_grid_profit(stock_fills, current_price)
        
        return {
            'symbol': position['symbol'],
            'stock_code': position['stock_code'],
            'name': position['name'],
            'quantity': current_quantity,
            'avg_cost': round(avg_cost, 2),
            'current_price': round(current_price, 2),
            'cost_value': round(cost_value, 2),
            'current_value': round(current_value, 2),
            'profit': round(profit, 2),
            'profit_rate': round(profit_rate, 2),
            'is_profitable': profit > 0,
            'fills': stock_fills,
            'grid_analysis': grid_analysis,
            'last_fill_time': last_fill_time
        }
    
    def analyze_grid_profit(self, stock_fills: List[Dict[str, Any]], current_price: float) -> Dict[str, Any]:
        """分析网格盈亏情况"""
        total_grids = len(stock_fills)
        profitable_grids = 0
        profitable_amount = 0
        profitable_quantity = 0
        profitable_cost = 0
        total_grid_cost = 0
        
        for fill in stock_fills:
            fill_price = fill['price']
            fill_quantity = fill['quantity']
            fill_cost = fill['amount']
            
            total_grid_cost += fill_cost
            
            # 判断该网格是否盈利
            if current_price > fill_price:
                profitable_grids += 1
                grid_profit = (current_price - fill_price) * fill_quantity
                profitable_amount += grid_profit
                profitable_quantity += fill_quantity
                profitable_cost += fill_cost
        
        profitable_ratio = (profitable_grids / total_grids * 100) if total_grids > 0 else 0
        profitable_amount_ratio = (profitable_amount / profitable_cost * 100) if profitable_cost > 0 else 0
        
        return {
            'total_grids': total_grids,
            'profitable_grids': profitable_grids,
            'losing_grids': total_grids - profitable_grids,
            'profitable_quantity': profitable_quantity,
            'profitable_amount': round(profitable_amount, 2),
            'profitable_amount_ratio': round(profitable_amount_ratio, 2),
            'profitable_ratio': round(profitable_ratio, 2)
        }

    def analyze_positions(self, console: Console) -> List[Dict[str, Any]]:
        """分析所有持仓"""
        positions = self.get_position_list()
        results = []
        
        console.print(f"\n[bold cyan]正在分析 {len(positions)} 个持仓...[/bold cyan]\n")
        
        for position in track(positions, description="[green]分析进度"):
            # 跳过已清仓的股票
            if position['quantity'] == 0:
                continue
            
            try:
                detail = self.get_stock_detail(position['symbol'])
                result = self.calculate_cost_and_profit(position, detail)
                
                # 获取缠论信号
                result['signal_15m'] = self.get_chanlun_signals(position['symbol'], '15m')
                result['signal_30m'] = self.get_chanlun_signals(position['symbol'], '30m')
                result['signal_60m'] = self.get_chanlun_signals(position['symbol'], '60m')
                result['signal_1d'] = self.get_chanlun_signals(position['symbol'], '1d')
                
                results.append(result)
            except Exception as e:
                console.print(f"[red]错误: {position['name']} - {str(e)}[/red]")
                continue
        
        return results

    def print_report(self, console: Console, results: List[Dict[str, Any]]):
        """打印综合报表"""
        if not results:
            console.print("\n[yellow]没有持仓数据[/yellow]")
            return
        
        # 分类统计
        profitable = [r for r in results if r['is_profitable']]
        losing = [r for r in results if not r['is_profitable']]
        
        # 排序
        results_sorted = sorted(results, key=lambda x: x['profit'], reverse=True)
        
        # 计算汇总
        total_cost = sum(r['cost_value'] for r in results)
        total_value = sum(r['current_value'] for r in results)
        total_profit = sum(r['profit'] for r in results)
        total_profit_rate = (total_profit / total_cost * 100) if total_cost > 0 else 0
        
        # 创建盈利股票表格
        if profitable:
            profit_table = Table(title="🔴 盈利股票", box=box.ROUNDED, show_header=True, header_style="bold red")
            profit_table.add_column("股票代码", width=12, header_style="bold red")
            profit_table.add_column("股票名称", width=10, header_style="bold red")
            profit_table.add_column("持仓", justify="right", width=8, header_style="bold red")
            profit_table.add_column("成本价", justify="right", width=10, header_style="bold red")
            profit_table.add_column("现价", justify="right", width=10, header_style="bold red")
            profit_table.add_column("成本", justify="right", width=12, header_style="bold red")
            profit_table.add_column("市值", justify="right", width=12, header_style="bold red")
            profit_table.add_column("盈亏", justify="right", style="red", width=12, header_style="bold red")
            profit_table.add_column("盈亏率", justify="right", style="red", width=10, header_style="bold red")
            profit_table.add_column("最近持仓时间", justify="right", width=16, header_style="bold red")
            profit_table.add_column("缠30M", justify="center", width=6, header_style="bold red")
            
            for r in [x for x in results_sorted if x['is_profitable']]:
                stock_link = f"[link={self.base_url}/kline-big?symbol={r['symbol']}&period=1m]{r['stock_code']}[/link]"
                signal_30m = r.get('signal_30m', '-')
                signal_30m_colored = f"[red]{signal_30m}[/red]" if signal_30m == "多" else f"[green]{signal_30m}[/green]" if signal_30m == "空" else signal_30m
                profit_table.add_row(
                    stock_link,
                    r['name'],
                    str(r['quantity']),
                    f"{r['avg_cost']:.2f}",
                    f"{r['current_price']:.2f}",
                    f"{r['cost_value']:,.2f}",
                    f"{r['current_value']:,.2f}",
                    f"+{r['profit']:,.2f}",
                    f"+{r['profit_rate']:.2f}%",
                    r.get('last_fill_time', '-'),
                    signal_30m_colored
                )
            
            console.print("\n")
            console.print(profit_table)
        
        # 创建亏损股票表格
        if losing:
            loss_table = Table(title="🟢 亏损股票", box=box.ROUNDED, show_header=True, header_style="bold green")
            loss_table.add_column("股票代码", width=12, header_style="bold green")
            loss_table.add_column("股票名称", width=10, header_style="bold green")
            loss_table.add_column("持仓", justify="right", width=8, header_style="bold green")
            loss_table.add_column("成本价", justify="right", width=10, header_style="bold green")
            loss_table.add_column("现价", justify="right", width=10, header_style="bold green")
            loss_table.add_column("成本", justify="right", width=12, header_style="bold green")
            loss_table.add_column("市值", justify="right", width=12, header_style="bold green")
            loss_table.add_column("盈亏", justify="right", style="green", width=12, header_style="bold green")
            loss_table.add_column("盈亏率", justify="right", style="green", width=10, header_style="bold green")
            loss_table.add_column("最近持仓时间", justify="right", width=16, header_style="bold green")
            loss_table.add_column("缠30M", justify="center", width=6, header_style="bold green")
            
            for r in [x for x in results_sorted if not x['is_profitable']]:
                stock_link = f"[link={self.base_url}/kline-big?symbol={r['symbol']}&period=1m]{r['stock_code']}[/link]"
                signal_30m = r.get('signal_30m', '-')
                signal_30m_colored = f"[red]{signal_30m}[/red]" if signal_30m == "多" else f"[green]{signal_30m}[/green]" if signal_30m == "空" else signal_30m
                loss_table.add_row(
                    stock_link,
                    r['name'],
                    str(r['quantity']),
                    f"{r['avg_cost']:.2f}",
                    f"{r['current_price']:.2f}",
                    f"{r['cost_value']:,.2f}",
                    f"{r['current_value']:,.2f}",
                    f"{r['profit']:,.2f}",
                    f"{r['profit_rate']:.2f}%",
                    r.get('last_fill_time', '-'),
                    signal_30m_colored
                )
            
            console.print("\n")
            console.print(loss_table)
        
        # 打印汇总统计
        summary_color = "green" if total_profit > 0 else "red"
        
        # 创建汇总统计表格，保持和其他表格一致的宽度
        summary_table = Table(title="📊 汇总统计", box=box.ROUNDED, show_header=False, border_style="cyan")
        summary_table.add_column("项目", style="bold", width=20)
        summary_table.add_column("数值", justify="right", width=76)
        
        summary_table.add_row("总持仓数", f"{len(results)} 只 ([green]盈利: {len(profitable)} 只[/green], [red]亏损: {len(losing)} 只[/red])")
        summary_table.add_row("总成本", f"{total_cost:,.2f} 元")
        summary_table.add_row("总市值", f"{total_value:,.2f} 元")
        summary_table.add_row("总盈亏", f"[{summary_color}]{total_profit:+,.2f} 元[/{summary_color}]")
        summary_table.add_row("总盈亏率", f"[{summary_color}]{total_profit_rate:+.2f}%[/{summary_color}]")
        
        console.print("\n")
        console.print(summary_table)
        
        # 打印盈利网格分析
        self.print_grid_analysis(console, results)
    
    def print_grid_analysis(self, console: Console, results: List[Dict[str, Any]]):
        """打印盈利网格分析"""
        grid_table = Table(title="📊 盈利网格分析", box=box.ROUNDED, show_header=True, header_style="bold cyan")
        grid_table.add_column("股票代码", style="cyan", width=11)
        grid_table.add_column("股票名称", style="white", width=8)
        grid_table.add_column("总网格", justify="right", width=7)
        grid_table.add_column("盈利网格", justify="right", style="red", width=8)
        grid_table.add_column("亏损网格", justify="right", style="green", width=8)
        grid_table.add_column("总股数", justify="right", width=7)
        grid_table.add_column("盈利股数", justify="right", style="red", width=8)
        grid_table.add_column("盈利金额", justify="right", style="red", width=12)
        grid_table.add_column("盈利率", justify="right", style="red", width=9)
        grid_table.add_column("网格占比", justify="right", style="red", width=9)
        grid_table.add_column("最近持仓时间", justify="right", width=16)
        grid_table.add_column("缠15M", justify="center", width=6)
        grid_table.add_column("缠30M", justify="center", width=6)
        grid_table.add_column("缠60M", justify="center", width=6)
        grid_table.add_column("缠1D", justify="center", width=6)
        
        # 过滤出有盈利网格的股票，并按盈利金额排序
        results_with_profit = [r for r in results if r['grid_analysis']['profitable_grids'] > 0]
        results_sorted = sorted(results_with_profit, key=lambda x: x['grid_analysis']['profitable_amount'], reverse=True)
        
        for r in results_sorted:
            grid = r['grid_analysis']
            # 根据盈利率设置颜色：达到1%用红色，有盈利用黄色，否则用绿色
            profit_rate = grid['profitable_amount_ratio']
            ratio_color = "red" if profit_rate >= 1 else "yellow" if profit_rate > 0 else "green"
            stock_link = f"[link={self.base_url}/kline-big?symbol={r['symbol']}&period=1m]{r['stock_code']}[/link]"
            
            # 信号颜色
            signal_15m = r.get('signal_15m', '-')
            signal_30m = r.get('signal_30m', '-')
            signal_60m = r.get('signal_60m', '-')
            signal_1d = r.get('signal_1d', '-')
            
            signal_15m_colored = f"[red]{signal_15m}[/red]" if signal_15m == "多" else f"[green]{signal_15m}[/green]" if signal_15m == "空" else signal_15m
            signal_30m_colored = f"[red]{signal_30m}[/red]" if signal_30m == "多" else f"[green]{signal_30m}[/green]" if signal_30m == "空" else signal_30m
            signal_60m_colored = f"[red]{signal_60m}[/red]" if signal_60m == "多" else f"[green]{signal_60m}[/green]" if signal_60m == "空" else signal_60m
            signal_1d_colored = f"[red]{signal_1d}[/red]" if signal_1d == "多" else f"[green]{signal_1d}[/green]" if signal_1d == "空" else signal_1d
            
            grid_table.add_row(
                stock_link,
                r['name'],
                str(grid['total_grids']),
                f"[{ratio_color}]{grid['profitable_grids']}[/{ratio_color}]",
                f"[{ratio_color}]{grid['losing_grids']}[/{ratio_color}]",
                str(r['quantity']),
                f"[{ratio_color}]{grid['profitable_quantity']}[/{ratio_color}]",
                f"[{ratio_color}]+{grid['profitable_amount']:,.2f}[/{ratio_color}]",
                f"[{ratio_color}]+{grid['profitable_amount_ratio']:.2f}%[/{ratio_color}]",
                f"[{ratio_color}]{grid['profitable_ratio']:.2f}%[/{ratio_color}]",
                r.get('last_fill_time', '-'),
                signal_15m_colored,
                signal_30m_colored,
                signal_60m_colored,
                signal_1d_colored
            )
        
        console.print("\n")
        console.print(grid_table)


    def generate_html_report(self, results: List[Dict[str, Any]]) -> str:
        """生成HTML报表"""
        profitable = [r for r in results if r['is_profitable']]
        losing = [r for r in results if not r['is_profitable']]
        results_sorted = sorted(results, key=lambda x: x['profit'], reverse=True)
        
        total_cost = sum(r['cost_value'] for r in results)
        total_value = sum(r['current_value'] for r in results)
        total_profit = sum(r['profit'] for r in results)
        total_profit_rate = (total_profit / total_cost * 100) if total_cost > 0 else 0
        
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>股票持仓盈亏分析报表</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: 'Microsoft YaHei', Arial, sans-serif; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            min-height: 100vh;
        }}
        .container {{ 
            max-width: 1400px; 
            margin: 0 auto; 
            background: white;
            border-radius: 15px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            overflow: hidden;
        }}
        .header {{ 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; 
            padding: 30px; 
            text-align: center;
        }}
        .header h1 {{ font-size: 32px; margin-bottom: 10px; }}
        .header .time {{ opacity: 0.9; font-size: 14px; }}
        .content {{ padding: 30px; }}
        .summary {{ 
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
            padding: 25px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }}
        .summary h2 {{ margin-bottom: 20px; font-size: 24px; }}
        .summary-grid {{ 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); 
            gap: 15px; 
        }}
        .summary-item {{ 
            background: rgba(255,255,255,0.2); 
            padding: 15px; 
            border-radius: 8px;
            backdrop-filter: blur(10px);
        }}
        .summary-item .label {{ font-size: 14px; opacity: 0.9; margin-bottom: 5px; }}
        .summary-item .value {{ font-size: 22px; font-weight: bold; }}
        table {{ 
            width: 100%; 
            border-collapse: collapse; 
            margin-bottom: 30px;
            background: white;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }}
        .table-title {{ 
            font-size: 20px; 
            font-weight: bold; 
            padding: 20px; 
            margin-bottom: 0;
            border-radius: 10px 10px 0 0;
        }}
        .table-title.profit {{ background: linear-gradient(135deg, #ee9ca7 0%, #ffdde1 100%); color: white; }}
        .table-title.loss {{ background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); color: white; }}
        .table-title.grid {{ background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); color: white; }}
        th {{ 
            background: #f8f9fa; 
            padding: 12px; 
            text-align: left; 
            font-weight: 600;
            color: #495057;
            border-bottom: 2px solid #dee2e6;
            font-size: 13px;
        }}
        td {{ 
            padding: 10px 12px; 
            border-bottom: 1px solid #f1f3f5;
            font-size: 12px;
        }}
        tr:hover {{ background: #f8f9fa; }}
        a {{ 
            color: #007bff; 
            text-decoration: none; 
            font-weight: 600;
        }}
        a:hover {{ 
            color: #0056b3; 
            text-decoration: underline; 
        }}
        .text-right {{ text-align: right; }}
        .text-red {{ color: #dc3545; font-weight: 600; }}
        .text-green {{ color: #28a745; font-weight: 600; }}
        .text-yellow {{ color: #ffc107; font-weight: 600; }}
        .section {{ margin-bottom: 40px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📈 股票持仓盈亏分析报表</h1>
            <div class="time">生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
        </div>
        
        <div class="content">
            <div class="summary">
                <h2>📊 汇总统计</h2>
                <div class="summary-grid">
                    <div class="summary-item">
                        <div class="label">总持仓数</div>
                        <div class="value">{len(results)} 只</div>
                    </div>
                    <div class="summary-item">
                        <div class="label">盈利 / 亏损</div>
                        <div class="value">{len(profitable)} / {len(losing)} 只</div>
                    </div>
                    <div class="summary-item">
                        <div class="label">总成本</div>
                        <div class="value">{total_cost:,.2f} 元</div>
                    </div>
                    <div class="summary-item">
                        <div class="label">总市值</div>
                        <div class="value">{total_value:,.2f} 元</div>
                    </div>
                    <div class="summary-item">
                        <div class="label">总盈亏</div>
                        <div class="value">{total_profit:+,.2f} 元</div>
                    </div>
                    <div class="summary-item">
                        <div class="label">总盈亏率</div>
                        <div class="value">{total_profit_rate:+.2f}%</div>
                    </div>
                </div>
            </div>
"""
        
        # 盈利股票表格
        if profitable:
            html += """
            <div class="section">
                <div class="table-title profit">🔴 盈利股票</div>
                <table>
                    <thead>
                        <tr>
                            <th>股票代码</th>
                            <th>股票名称</th>
                            <th class="text-right">持仓</th>
                            <th class="text-right">成本价</th>
                            <th class="text-right">现价</th>
                            <th class="text-right">成本</th>
                            <th class="text-right">市值</th>
                            <th class="text-right">盈亏</th>
                            <th class="text-right">盈亏率</th>
                            <th class="text-right">最近持仓时间</th>
                            <th class="text-right">缠30M</th>
                        </tr>
                    </thead>
                    <tbody>
"""
            for r in [x for x in results_sorted if x['is_profitable']]:
                signal_30m = r.get('signal_30m', '-')
                signal_30m_class = "text-red" if signal_30m == "多" else "text-green" if signal_30m == "空" else ""
                html += f"""
                        <tr>
                            <td><a href="{self.base_url}/kline-big?symbol={r['symbol']}&period=1m" target="_blank">{r['stock_code']}</a></td>
                            <td>{r['name']}</td>
                            <td class="text-right">{r['quantity']}</td>
                            <td class="text-right">{r['avg_cost']:.2f}</td>
                            <td class="text-right">{r['current_price']:.2f}</td>
                            <td class="text-right">{r['cost_value']:,.2f}</td>
                            <td class="text-right">{r['current_value']:,.2f}</td>
                            <td class="text-right text-red">+{r['profit']:,.2f}</td>
                            <td class="text-right text-red">+{r['profit_rate']:.2f}%</td>
                            <td class="text-right">{r.get('last_fill_time', '-')}</td>
                            <td class="text-right {signal_30m_class}">{signal_30m}</td>
                        </tr>
"""
            html += """
                    </tbody>
                </table>
            </div>
"""
        
        # 亏损股票表格
        if losing:
            html += """
            <div class="section">
                <div class="table-title loss">🟢 亏损股票</div>
                <table>
                    <thead>
                        <tr>
                            <th>股票代码</th>
                            <th>股票名称</th>
                            <th class="text-right">持仓</th>
                            <th class="text-right">成本价</th>
                            <th class="text-right">现价</th>
                            <th class="text-right">成本</th>
                            <th class="text-right">市值</th>
                            <th class="text-right">盈亏</th>
                            <th class="text-right">盈亏率</th>
                            <th class="text-right">最近持仓时间</th>
                            <th class="text-right">缠30M</th>
                        </tr>
                    </thead>
                    <tbody>
"""
            for r in [x for x in results_sorted if not x['is_profitable']]:
                signal_30m = r.get('signal_30m', '-')
                signal_30m_class = "text-red" if signal_30m == "多" else "text-green" if signal_30m == "空" else ""
                html += f"""
                        <tr>
                            <td><a href="{self.base_url}/kline-big?symbol={r['symbol']}&period=1m" target="_blank">{r['stock_code']}</a></td>
                            <td>{r['name']}</td>
                            <td class="text-right">{r['quantity']}</td>
                            <td class="text-right">{r['avg_cost']:.2f}</td>
                            <td class="text-right">{r['current_price']:.2f}</td>
                            <td class="text-right">{r['cost_value']:,.2f}</td>
                            <td class="text-right">{r['current_value']:,.2f}</td>
                            <td class="text-right text-green">{r['profit']:,.2f}</td>
                            <td class="text-right text-green">{r['profit_rate']:.2f}%</td>
                            <td class="text-right">{r.get('last_fill_time', '-')}</td>
                            <td class="text-right {signal_30m_class}">{signal_30m}</td>
                        </tr>
"""
            html += """
                    </tbody>
                </table>
            </div>
"""
        
        # 盈利网格分析（过滤出有盈利网格的股票，并按盈利金额排序）
        results_with_profit = [r for r in results if r['grid_analysis']['profitable_grids'] > 0]
        grid_sorted = sorted(results_with_profit, key=lambda x: x['grid_analysis']['profitable_amount'], reverse=True)
        html += """
            <div class="section">
                <div class="table-title grid">📊 盈利网格分析</div>
                <table>
                    <thead>
                        <tr>
                            <th>股票代码</th>
                            <th>股票名称</th>
                            <th class="text-right">总网格</th>
                            <th class="text-right">盈利网格</th>
                            <th class="text-right">亏损网格</th>
                            <th class="text-right">总股数</th>
                            <th class="text-right">盈利股数</th>
                            <th class="text-right">盈利金额</th>
                            <th class="text-right">盈利率</th>
                            <th class="text-right">网格占比</th>
                            <th class="text-right">最近持仓时间</th>
                            <th class="text-right">缠15M</th>
                            <th class="text-right">缠30M</th>
                            <th class="text-right">缠60M</th>
                            <th class="text-right">缠1D</th>
                        </tr>
                    </thead>
                    <tbody>
"""
        for r in grid_sorted:
            grid = r['grid_analysis']
            # 根据盈利率设置颜色：达到1%用红色，有盈利用黄色，否则用绿色
            profit_rate = grid['profitable_amount_ratio']
            ratio_class = "text-red" if profit_rate >= 1 else "text-yellow" if profit_rate > 0 else "text-green"
            
            # 信号样式
            signal_15m = r.get('signal_15m', '-')
            signal_30m = r.get('signal_30m', '-')
            signal_60m = r.get('signal_60m', '-')
            signal_1d = r.get('signal_1d', '-')
            
            signal_15m_class = "text-red" if signal_15m == "多" else "text-green" if signal_15m == "空" else ""
            signal_30m_class = "text-red" if signal_30m == "多" else "text-green" if signal_30m == "空" else ""
            signal_60m_class = "text-red" if signal_60m == "多" else "text-green" if signal_60m == "空" else ""
            signal_1d_class = "text-red" if signal_1d == "多" else "text-green" if signal_1d == "空" else ""
            
            html += f"""
                        <tr>
                            <td><a href="{self.base_url}/kline-big?symbol={r['symbol']}&period=1m" target="_blank">{r['stock_code']}</a></td>
                            <td>{r['name']}</td>
                            <td class="text-right">{grid['total_grids']}</td>
                            <td class="text-right {ratio_class}">{grid['profitable_grids']}</td>
                            <td class="text-right {ratio_class}">{grid['losing_grids']}</td>
                            <td class="text-right">{r['quantity']}</td>
                            <td class="text-right {ratio_class}">{grid['profitable_quantity']}</td>
                            <td class="text-right {ratio_class}">+{grid['profitable_amount']:,.2f}</td>
                            <td class="text-right {ratio_class}">+{grid['profitable_amount_ratio']:.2f}%</td>
                            <td class="text-right {ratio_class}">{grid['profitable_ratio']:.2f}%</td>
                            <td class="text-right">{r.get('last_fill_time', '-')}</td>
                            <td class="text-right {signal_15m_class}">{signal_15m}</td>
                            <td class="text-right {signal_30m_class}">{signal_30m}</td>
                            <td class="text-right {signal_60m_class}">{signal_60m}</td>
                            <td class="text-right {signal_1d_class}">{signal_1d}</td>
                        </tr>
"""
        html += """
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
"""
        return html


def main():
    import argparse

    # 获取配置的默认值
    default_base_url = get_api_base_url()

    parser = argparse.ArgumentParser(description='股票持仓盈亏分析工具')
    parser.add_argument(
        '--base-url',
        type=str,
        default=default_base_url,
        help=f'API服务地址 (默认: {default_base_url})，可通过环境变量 freshquant_API__BASE_URL 配置'
    )
    args = parser.parse_args()
    
    console = Console()
    analyzer = StockPositionAnalyzer(base_url=args.base_url)
    
    console.print(Panel.fit("📈 [bold cyan]股票持仓盈亏分析工具[/bold cyan] 📈", border_style="cyan"))
    console.print(f"[dim]API地址: {args.base_url}[/dim]\n")
    
    results = analyzer.analyze_positions(console)
    analyzer.print_report(console, results)
    
    # 生成HTML报表
    html_content = analyzer.generate_html_report(results)
    output_file = "report/stock_position_analyzer.html"
    write_file_with_mkdir(output_file, html_content)
    console.print(f"\n[dim]HTML报表已保存到: {output_file}[/dim]")


if __name__ == "__main__":
    main()
