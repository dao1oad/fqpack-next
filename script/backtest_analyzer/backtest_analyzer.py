import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from datetime import datetime, timedelta

from freshquant.util.url import get_api_base_url


def fetch_account_data():
    """从API获取账户数据"""
    base_url = get_api_base_url()
    url = f'{base_url}/api/general/freshquant/backtest_account?page=1&size=500&project={{"account_cookie":1,"accounts":1,"trading_day":1}}'
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get('data', [])
    except requests.exceptions.RequestException as e:
        console = Console()
        console.print(f"[red]获取数据失败: {e}[/red]")
        return []

def fetch_account_history(account_cookie):
    """获取指定账户的历史记录"""
    base_url = get_api_base_url()
    url = f'{base_url}/api/general/freshquant/backtest_account_his?page=1&size=500&query={{"account_cookie":"{account_cookie}"}}&project={{"account_cookie":1,"accounts":1,"trading_day":1}}&sort={{"trading_day":-1}}'
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get('data', [])
    except requests.exceptions.RequestException as e:
        return []

def fetch_account_statistics(account_cookie):
    """获取指定账户的统计数据"""
    base_url = get_api_base_url()
    url = f'{base_url}/api/general/freshquant/backtest_statistics?page=1&size=1&query={{"account_cookie":"{account_cookie}"}}&sort={{"trading_day":-1}}'
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        items = data.get('data', [])
        if items:
            return items[0].get('statistics', {})
        return {}
    except requests.exceptions.RequestException as e:
        return {}

def parse_accounts(data):
    """解析账户数据"""
    accounts_info = []
    console = Console()
    
    for item in data:
        account_cookie = item.get('account_cookie', 'N/A')
        accounts = item.get('accounts', {})
        trading_day = item.get('trading_day', 'N/A')
        
        # 获取统计数据
        statistics = fetch_account_statistics(account_cookie)
        
        account_info = {
            'account_name': account_cookie,
            'balance': accounts.get('balance', 0),
            'available': accounts.get('available', 0),
            'trading_day': trading_day,
            'statistics': statistics
        }
        accounts_info.append(account_info)
    
    # 按账户余额从大到小排序
    accounts_info.sort(key=lambda x: x['balance'], reverse=True)
    
    return accounts_info

def display_accounts_table(accounts_info):
    """显示账户信息表格（7天对比）"""
    console = Console()
    
    if not accounts_info:
        console.print("[yellow]没有找到账户数据[/yellow]")
        return
    
    # 按7天盈利比例排序
    sorted_accounts = sorted(accounts_info, key=lambda x: (
        x.get('statistics', {}).get('7', {}).get('pnl_ratio', float('-inf'))
    ), reverse=True)
    
    # 创建7天对比表格
    table_7days = Table(
        title="💰 账户余额汇总表（7天数据）",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title_style="bold magenta"
    )
    
    # 添加列
    table_7days.add_column("账户名称", style="green", justify="center")
    table_7days.add_column("账户资产", style="yellow", justify="right")
    table_7days.add_column("可用资金", style="cyan", justify="right")
    table_7days.add_column("持仓比例", style="magenta", justify="right")
    table_7days.add_column("7天买入金额", style="bright_yellow", justify="right")
    table_7days.add_column("7天盈亏(率)", style="white", justify="right")
    table_7days.add_column("交易次数", style="bright_white", justify="right")
    table_7days.add_column("盈利次数", style="red", justify="right")
    table_7days.add_column("亏损次数", style="green", justify="right")
    table_7days.add_column("最后交易日期", style="blue", justify="center")
    
    # 添加数据行
    for account in sorted_accounts:
        balance = account['balance']
        available = account['available']
        statistics = account.get('statistics', {})
        stats_7 = statistics.get('7', {})
        
        # 计算持仓比例
        position_ratio = ((balance - available) / balance * 100) if balance > 0 else 0
        
        # 获取统计数据
        total_buy_amount = stats_7.get('total_buy_amount', 0)
        pnl_ratio = stats_7.get('pnl_ratio', 0)
        total_pnl = stats_7.get('total_pnl', 0)
        
        buy_amount_str = f"{total_buy_amount:,.2f}"
        
        # 根据涨跌设置颜色（盈利用红色，亏损用绿色）
        if total_pnl > 0:
            change_str = f"[red]+{total_pnl:,.2f} (+{pnl_ratio:.2f}%)[/red]"
        elif total_pnl < 0:
            change_str = f"[green]{total_pnl:,.2f} ({pnl_ratio:.2f}%)[/green]"
        else:
            change_str = f"{total_pnl:,.2f} ({pnl_ratio:.2f}%)"
        
        # 获取交易统计
        total_trades = stats_7.get('total_trades', 'N/A')
        winning_trades = stats_7.get('winning_trades', 'N/A')
        losing_trades = stats_7.get('losing_trades', 'N/A')
        
        table_7days.add_row(
            account['account_name'],
            f"{balance:,.2f}",
            f"{available:,.2f}",
            f"{position_ratio:.2f}%",
            buy_amount_str,
            change_str,
            str(total_trades),
            str(winning_trades),
            str(losing_trades),
            account['trading_day']
        )
    
    # 显示7天对比表格
    console.print()
    console.print(table_7days)
    console.print()

def display_accounts_table_14days(accounts_info):
    """显示账户信息表格（14天对比）"""
    console = Console()
    
    if not accounts_info:
        console.print("[yellow]没有找到账户数据[/yellow]")
        return
    
    # 按14天盈利比例排序
    sorted_accounts = sorted(accounts_info, key=lambda x: (
        x.get('statistics', {}).get('14', {}).get('pnl_ratio', float('-inf'))
    ), reverse=True)
    
    # 创建14天对比表格
    table_14days = Table(
        title="📊 账户余额汇总表（14天数据）",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title_style="bold magenta"
    )
    
    # 添加列
    table_14days.add_column("账户名称", style="green", justify="center")
    table_14days.add_column("账户资产", style="yellow", justify="right")
    table_14days.add_column("可用资金", style="cyan", justify="right")
    table_14days.add_column("持仓比例", style="magenta", justify="right")
    table_14days.add_column("14天买入金额", style="bright_yellow", justify="right")
    table_14days.add_column("14天盈亏(率)", style="white", justify="right")
    table_14days.add_column("交易次数", style="bright_white", justify="right")
    table_14days.add_column("盈利次数", style="red", justify="right")
    table_14days.add_column("亏损次数", style="green", justify="right")
    table_14days.add_column("最后交易日期", style="blue", justify="center")
    
    # 添加数据行
    for account in sorted_accounts:
        balance = account['balance']
        available = account['available']
        statistics = account.get('statistics', {})
        stats_14 = statistics.get('14', {})
        
        # 计算持仓比例
        position_ratio = ((balance - available) / balance * 100) if balance > 0 else 0
        
        # 获取统计数据
        total_buy_amount = stats_14.get('total_buy_amount', 0)
        pnl_ratio = stats_14.get('pnl_ratio', 0)
        total_pnl = stats_14.get('total_pnl', 0)
        
        buy_amount_str = f"{total_buy_amount:,.2f}"
            
        # 根据涨跌设置颜色（盈利用红色，亏损用绿色）
        if total_pnl > 0:
            change_str = f"[red]+{total_pnl:,.2f} (+{pnl_ratio:.2f}%)[/red]"
        elif total_pnl < 0:
            change_str = f"[green]{total_pnl:,.2f} ({pnl_ratio:.2f}%)[/green]"
        else:
            change_str = f"{total_pnl:,.2f} ({pnl_ratio:.2f}%)"
        
        # 获取交易统计
        total_trades = stats_14.get('total_trades', 'N/A')
        winning_trades = stats_14.get('winning_trades', 'N/A')
        losing_trades = stats_14.get('losing_trades', 'N/A')
        
        table_14days.add_row(
            account['account_name'],
            f"{balance:,.2f}",
            f"{available:,.2f}",
            f"{position_ratio:.2f}%",
            buy_amount_str,
            change_str,
            str(total_trades),
            str(winning_trades),
            str(losing_trades),
            account['trading_day']
        )
    
    # 显示14天对比表格
    console.print()
    console.print(table_14days)
    console.print()

def display_accounts_table_30days(accounts_info):
    """显示账户信息表格（30天对比）"""
    console = Console()
    
    if not accounts_info:
        return
    
    # 按30天盈利比例排序
    sorted_accounts = sorted(accounts_info, key=lambda x: (
        x.get('statistics', {}).get('30', {}).get('pnl_ratio', float('-inf'))
    ), reverse=True)
    
    table = Table(
        title="📈 账户余额汇总表（30天数据）",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title_style="bold magenta"
    )
    
    table.add_column("账户名称", style="green", justify="center")
    table.add_column("账户资产", style="yellow", justify="right")
    table.add_column("可用资金", style="cyan", justify="right")
    table.add_column("持仓比例", style="magenta", justify="right")
    table.add_column("30天买入金额", style="bright_yellow", justify="right")
    table.add_column("30天盈亏(率)", style="white", justify="right")
    table.add_column("交易次数", style="bright_white", justify="right")
    table.add_column("盈利次数", style="red", justify="right")
    table.add_column("亏损次数", style="green", justify="right")
    table.add_column("最后交易日期", style="blue", justify="center")
    
    for account in sorted_accounts:
        balance = account['balance']
        available = account['available']
        statistics = account.get('statistics', {})
        stats_30 = statistics.get('30', {})
        
        position_ratio = ((balance - available) / balance * 100) if balance > 0 else 0
        
        # 获取统计数据
        total_buy_amount = stats_30.get('total_buy_amount', 0)
        pnl_ratio = stats_30.get('pnl_ratio', 0)
        total_pnl = stats_30.get('total_pnl', 0)
        
        buy_amount_str = f"{total_buy_amount:,.2f}"
            
        # 根据涨跌设置颜色（盈利用红色，亏损用绿色）
        if total_pnl > 0:
            change_str = f"[red]+{total_pnl:,.2f} (+{pnl_ratio:.2f}%)[/red]"
        elif total_pnl < 0:
            change_str = f"[green]{total_pnl:,.2f} ({pnl_ratio:.2f}%)[/green]"
        else:
            change_str = f"{total_pnl:,.2f} ({pnl_ratio:.2f}%)"
        
        # 获取交易统计
        total_trades = stats_30.get('total_trades', 'N/A')
        winning_trades = stats_30.get('winning_trades', 'N/A')
        losing_trades = stats_30.get('losing_trades', 'N/A')
        
        table.add_row(
            account['account_name'],
            f"{balance:,.2f}",
            f"{available:,.2f}",
            f"{position_ratio:.2f}%",
            buy_amount_str,
            change_str,
            str(total_trades),
            str(winning_trades),
            str(losing_trades),
            account['trading_day']
        )
    
    console.print()
    console.print(table)
    console.print()

def display_accounts_table_90days(accounts_info):
    """显示账户信息表格（90天对比）"""
    console = Console()
    
    if not accounts_info:
        return
    
    # 按90天盈利比例排序
    sorted_accounts = sorted(accounts_info, key=lambda x: (
        x.get('statistics', {}).get('90', {}).get('pnl_ratio', float('-inf'))
    ), reverse=True)
    
    table = Table(
        title="📉 账户余额汇总表（90天数据）",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title_style="bold magenta"
    )
    
    table.add_column("账户名称", style="green", justify="center")
    table.add_column("账户资产", style="yellow", justify="right")
    table.add_column("可用资金", style="cyan", justify="right")
    table.add_column("持仓比例", style="magenta", justify="right")
    table.add_column("90天买入金额", style="bright_yellow", justify="right")
    table.add_column("90天盈亏(率)", style="white", justify="right")
    table.add_column("交易次数", style="bright_white", justify="right")
    table.add_column("盈利次数", style="red", justify="right")
    table.add_column("亏损次数", style="green", justify="right")
    table.add_column("最后交易日期", style="blue", justify="center")
    
    for account in sorted_accounts:
        balance = account['balance']
        available = account['available']
        statistics = account.get('statistics', {})
        stats_90 = statistics.get('90', {})
        
        position_ratio = ((balance - available) / balance * 100) if balance > 0 else 0
        
        # 获取统计数据
        total_buy_amount = stats_90.get('total_buy_amount', 0)
        pnl_ratio = stats_90.get('pnl_ratio', 0)
        total_pnl = stats_90.get('total_pnl', 0)
        
        buy_amount_str = f"{total_buy_amount:,.2f}"
            
        # 根据涨跌设置颜色（盈利用红色，亏损用绿色）
        if total_pnl > 0:
            change_str = f"[red]+{total_pnl:,.2f} (+{pnl_ratio:.2f}%)[/red]"
        elif total_pnl < 0:
            change_str = f"[green]{total_pnl:,.2f} ({pnl_ratio:.2f}%)[/green]"
        else:
            change_str = f"{total_pnl:,.2f} ({pnl_ratio:.2f}%)"
        
        # 获取交易统计
        total_trades = stats_90.get('total_trades', 'N/A')
        winning_trades = stats_90.get('winning_trades', 'N/A')
        losing_trades = stats_90.get('losing_trades', 'N/A')
        
        table.add_row(
            account['account_name'],
            f"{balance:,.2f}",
            f"{available:,.2f}",
            f"{position_ratio:.2f}%",
            buy_amount_str,
            change_str,
            str(total_trades),
            str(winning_trades),
            str(losing_trades),
            account['trading_day']
        )
    
    console.print()
    console.print(table)
    console.print()

def display_accounts_table_180days(accounts_info):
    """显示账户信息表格（180天对比）"""
    console = Console()
    
    if not accounts_info:
        return
    
    # 按180天盈利比例排序
    sorted_accounts = sorted(accounts_info, key=lambda x: (
        x.get('statistics', {}).get('180', {}).get('pnl_ratio', float('-inf'))
    ), reverse=True)
    
    table = Table(
        title="📊 账户余额汇总表（180天数据）",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title_style="bold magenta"
    )
    
    table.add_column("账户名称", style="green", justify="center")
    table.add_column("账户资产", style="yellow", justify="right")
    table.add_column("可用资金", style="cyan", justify="right")
    table.add_column("持仓比例", style="magenta", justify="right")
    table.add_column("180天买入金额", style="bright_yellow", justify="right")
    table.add_column("180天盈亏(率)", style="white", justify="right")
    table.add_column("交易次数", style="bright_white", justify="right")
    table.add_column("盈利次数", style="red", justify="right")
    table.add_column("亏损次数", style="green", justify="right")
    table.add_column("最后交易日期", style="blue", justify="center")
    
    for account in sorted_accounts:
        balance = account['balance']
        available = account['available']
        statistics = account.get('statistics', {})
        stats_180 = statistics.get('180', {})
        
        position_ratio = ((balance - available) / balance * 100) if balance > 0 else 0
        
        # 获取统计数据
        total_buy_amount = stats_180.get('total_buy_amount', 0)
        pnl_ratio = stats_180.get('pnl_ratio', 0)
        total_pnl = stats_180.get('total_pnl', 0)
        
        buy_amount_str = f"{total_buy_amount:,.2f}"
            
        # 根据涨跌设置颜色（盈利用红色，亏损用绿色）
        if total_pnl > 0:
            change_str = f"[red]+{total_pnl:,.2f} (+{pnl_ratio:.2f}%)[/red]"
        elif total_pnl < 0:
            change_str = f"[green]{total_pnl:,.2f} ({pnl_ratio:.2f}%)[/green]"
        else:
            change_str = f"{total_pnl:,.2f} ({pnl_ratio:.2f}%)"
        
        # 获取交易统计
        total_trades = stats_180.get('total_trades', 'N/A')
        winning_trades = stats_180.get('winning_trades', 'N/A')
        losing_trades = stats_180.get('losing_trades', 'N/A')
        
        table.add_row(
            account['account_name'],
            f"{balance:,.2f}",
            f"{available:,.2f}",
            f"{position_ratio:.2f}%",
            buy_amount_str,
            change_str,
            str(total_trades),
            str(winning_trades),
            str(losing_trades),
            account['trading_day']
        )
    
    console.print()
    console.print(table)
    console.print()

def display_accounts_table_360days(accounts_info):
    """显示账户信息表格（360天对比）"""
    console = Console()
    
    if not accounts_info:
        return
    
    # 按360天盈利比例排序
    sorted_accounts = sorted(accounts_info, key=lambda x: (
        x.get('statistics', {}).get('360', {}).get('pnl_ratio', float('-inf'))
    ), reverse=True)
    
    table = Table(
        title="🎯 账户余额汇总表（360天数据）",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title_style="bold magenta"
    )
    
    table.add_column("账户名称", style="green", justify="center")
    table.add_column("账户资产", style="yellow", justify="right")
    table.add_column("可用资金", style="cyan", justify="right")
    table.add_column("持仓比例", style="magenta", justify="right")
    table.add_column("360天买入金额", style="bright_yellow", justify="right")
    table.add_column("360天盈亏(率)", style="white", justify="right")
    table.add_column("交易次数", style="bright_white", justify="right")
    table.add_column("盈利次数", style="red", justify="right")
    table.add_column("亏损次数", style="green", justify="right")
    table.add_column("最后交易日期", style="blue", justify="center")
    
    for account in sorted_accounts:
        balance = account['balance']
        available = account['available']
        statistics = account.get('statistics', {})
        stats_360 = statistics.get('360', {})
        
        position_ratio = ((balance - available) / balance * 100) if balance > 0 else 0
        
        # 获取统计数据
        total_buy_amount = stats_360.get('total_buy_amount', 0)
        pnl_ratio = stats_360.get('pnl_ratio', 0)
        total_pnl = stats_360.get('total_pnl', 0)
        
        buy_amount_str = f"{total_buy_amount:,.2f}"
            
        # 根据涨跌设置颜色（盈利用红色，亏损用绿色）
        if total_pnl > 0:
            change_str = f"[red]+{total_pnl:,.2f} (+{pnl_ratio:.2f}%)[/red]"
        elif total_pnl < 0:
            change_str = f"[green]{total_pnl:,.2f} ({pnl_ratio:.2f}%)[/green]"
        else:
            change_str = f"{total_pnl:,.2f} ({pnl_ratio:.2f}%)"
        
        # 获取交易统计
        total_trades = stats_360.get('total_trades', 'N/A')
        winning_trades = stats_360.get('winning_trades', 'N/A')
        losing_trades = stats_360.get('losing_trades', 'N/A')
        
        table.add_row(
            account['account_name'],
            f"{balance:,.2f}",
            f"{available:,.2f}",
            f"{position_ratio:.2f}%",
            buy_amount_str,
            change_str,
            str(total_trades),
            str(winning_trades),
            str(losing_trades),
            account['trading_day']
        )
    
    console.print()
    console.print(table)
    console.print()

def display_comprehensive_profitable_table(accounts_info):
    """显示综合盈利表格（所有周期都盈利的策略）"""
    console = Console()
    
    if not accounts_info:
        return
    
    # 筛选所有周期都盈利的账户
    profitable_accounts = []
    for account in accounts_info:
        statistics = account.get('statistics', {})
        
        # 检查所有周期是否都有数据且都盈利
        all_profitable = True
        
        periods = ['7', '14', '30', '90', '180', '360']
        returns = {}
        
        for period in periods:
            stats = statistics.get(period, {})
            pnl_ratio = stats.get('pnl_ratio', 0)
            total_buy_amount = stats.get('total_buy_amount', 0)
            
            if total_buy_amount <= 0 or pnl_ratio <= 0:
                all_profitable = False
                break
            
            returns[f'{period}days'] = pnl_ratio
        
        if all_profitable:
            account_with_returns = account.copy()
            account_with_returns['returns'] = returns
            profitable_accounts.append(account_with_returns)
    
    if not profitable_accounts:
        console.print()
        console.print(Panel(
            "[yellow]没有找到在所有周期都盈利的策略[/yellow]",
            title="🎯 综合盈利分析",
            border_style="yellow"
        ))
        return
    
    # 按7天收益率排序
    profitable_accounts.sort(key=lambda x: x['returns']['7days'], reverse=True)
    
    # 创建综合表格
    table = Table(
        title="🏆 综合盈利表格（所有周期都盈利的策略）",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title_style="bold magenta"
    )
    
    table.add_column("账户名称", style="green", justify="center")
    table.add_column("账户资产", style="yellow", justify="right")
    table.add_column("7天收益率", style="bright_green", justify="right")
    table.add_column("14天收益率", style="bright_green", justify="right")
    table.add_column("30天收益率", style="bright_green", justify="right")
    table.add_column("90天收益率", style="bright_green", justify="right")
    table.add_column("180天收益率", style="bright_green", justify="right")
    table.add_column("360天收益率", style="bright_green", justify="right")
    table.add_column("最后交易日期", style="blue", justify="center")
    
    for account in profitable_accounts:
        returns = account['returns']
        
        table.add_row(
            account['account_name'],
            f"{account['balance']:,.2f}",
            f"[red]+{returns['7days']:.2f}%[/red]",
            f"[red]+{returns['14days']:.2f}%[/red]",
            f"[red]+{returns['30days']:.2f}%[/red]",
            f"[red]+{returns['90days']:.2f}%[/red]",
            f"[red]+{returns['180days']:.2f}%[/red]",
            f"[red]+{returns['360days']:.2f}%[/red]",
            account['trading_day']
        )
    
    console.print()
    console.print(table)
    console.print()

def main():
    console = Console()
    console.print("[bold blue]正在获取账户数据...[/bold blue]")
    
    data = fetch_account_data()
    
    if data:
        accounts_info = parse_accounts(data)
        display_accounts_table(accounts_info)
        display_accounts_table_14days(accounts_info)
        display_accounts_table_30days(accounts_info)
        display_accounts_table_90days(accounts_info)
        display_accounts_table_180days(accounts_info)
        display_accounts_table_360days(accounts_info)
        display_comprehensive_profitable_table(accounts_info)
    else:
        console.print("[red]未能获取到账户数据[/red]")

if __name__ == "__main__":
    main()
