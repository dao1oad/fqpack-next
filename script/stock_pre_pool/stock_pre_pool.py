"""股票预选池查询脚本"""
import argparse
from datetime import datetime

import requests
from rich.console import Console
from rich.table import Table


def get_stock_pre_pools(category: str, date: str | None = None) -> list[dict]:
    """获取股票预选池列表"""
    url = 'http://127.0.0.1/api/get_stock_pre_pools_list'
    params = {'page': 1, 'size': 1000, 'category': category}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if date:
        data = [item for item in data if item['datetime'].startswith(date)]

    return data


def print_stock_pool(data: list[dict], category: str, date: str | None = None):
    """用rich表格打印股票池"""
    console = Console()

    title = f'股票预选池 - {category}'
    if date:
        title += f' ({date})'

    table = Table(title=title, show_lines=False)
    table.add_column('序号', justify='right', style='cyan')
    table.add_column('代码', style='green')
    table.add_column('名称', style='yellow')
    table.add_column('入池时间', style='magenta')
    table.add_column('策略类型', style='white')

    for idx, item in enumerate(data, 1):
        strategy_type = item.get('extra', {}).get('strategy_type', '-')
        table.add_row(
            str(idx),
            item['code'],
            item['name'],
            item['datetime'],
            strategy_type,
        )

    console.print(table)
    console.print(f'\n共 [bold green]{len(data)}[/bold green] 只股票')


def main():
    parser = argparse.ArgumentParser(description='查询股票预选池')
    parser.add_argument('category', help='模型类别，如 CLX00001')
    parser.add_argument('-d', '--date', help='日期过滤，格式 YYYY-MM-DD')
    args = parser.parse_args()

    data = get_stock_pre_pools(args.category, args.date)
    print_stock_pool(data, args.category, args.date)


if __name__ == '__main__':
    main()
