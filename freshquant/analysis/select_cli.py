import click

from loguru import logger

from freshquant.analysis import custom_stock_signal
from freshquant.screening.strategies.chanlun_service import ChanlunServiceStrategy


@click.group()
def select():
    pass


@select.command(name="stock")
@click.option('--code', type=str, help="股票代码（如 sh600000）")
@click.option('--period', type=str, help="周期（如 1d, 60m）")
@click.option('--infile', type=str, help="输入文件")
@click.option('--custom/--no-custom', default=False, help="使用自定义策略")
def select_stock(code, period, infile, custom):
    """股票选股命令

    不指定 code 时扫描预选池所有股票。
    """
    if custom:
        custom_stock_signal.run(code, period, infile)
    else:
        strategy = ChanlunServiceStrategy()
        import asyncio

        # 添加提示信息
        if not code:
            click.echo("未指定股票代码，将扫描预选池所有股票...")
            click.echo("提示: 使用 --code 参数扫描单个股票，如: --code sh600000")
            click.echo("")

        asyncio.run(strategy.screen(symbol=code, period=period))


if __name__ == "__main__":
    select()
