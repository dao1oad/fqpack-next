# -*- coding: utf-8 -*-

import click

from freshquant.command.asset import xt_asset_command_group
from freshquant.command.bond import (
    bond_command_group,
    bond_day_command_group,
    bond_list_command_group,
    bond_min_command_group,
)
from freshquant.command.channel import channel_command_group
from freshquant.command.digital import digital_fill_command_group
from freshquant.command.etf import (
    etf_command_group,
    etf_day_command_group,
    etf_list_command_group,
    etf_min_command_group,
)
from freshquant.command.future import (
    future_command_group,
    future_day_command_group,
    future_fill_command_group,
    future_list_command_group,
    future_min_command_group,
)
from freshquant.command.index import (
    index_command_group,
    index_day_command_group,
    index_list_command_group,
    index_min_command_group,
)
from freshquant.command.om_order import om_order_command_group
from freshquant.command.order import xt_order_command_group
from freshquant.command.position import xt_position_command_group

# from freshquant.analysis.select_cli import select
# from freshquant.export.cli import export_factors, export_pools, export_signals
# from freshquant.rear.cli import run
# from freshquant.signal.cli import monitor
from freshquant.command.stock import (
    stock_block_command_group,
    stock_command_group,
    stock_day_command_group,
    stock_fill_command_group,
    stock_list_command_group,
    stock_min_command_group,
    stock_must_pool_command_group,
    stock_pool_command_group,
    stock_pre_pool_command_group,
    stock_xdxr_command_group,
)
from freshquant.command.trade import xt_trade_command_group


@click.group()
def commands():
    pass


def main():
    # commands.add_command(monitor)
    # commands.add_command(select)
    # commands.add_command(run)
    # commands.add_command(export_factors)
    # commands.add_command(export_signals)
    # commands.add_command(export_pools)

    commands.add_command(stock_command_group)
    commands.add_command(stock_list_command_group)
    commands.add_command(stock_block_command_group)
    commands.add_command(stock_day_command_group)
    commands.add_command(stock_min_command_group)
    commands.add_command(stock_xdxr_command_group)

    commands.add_command(stock_must_pool_command_group)
    commands.add_command(stock_pool_command_group)
    commands.add_command(stock_pre_pool_command_group)

    commands.add_command(stock_fill_command_group)

    commands.add_command(etf_command_group)
    commands.add_command(etf_list_command_group)
    commands.add_command(etf_day_command_group)
    commands.add_command(etf_min_command_group)

    commands.add_command(index_command_group)
    commands.add_command(index_list_command_group)
    commands.add_command(index_day_command_group)
    commands.add_command(index_min_command_group)

    commands.add_command(bond_command_group)
    commands.add_command(bond_list_command_group)
    commands.add_command(bond_day_command_group)
    commands.add_command(bond_min_command_group)

    commands.add_command(future_command_group)
    commands.add_command(future_list_command_group)
    commands.add_command(future_day_command_group)
    commands.add_command(future_min_command_group)

    commands.add_command(future_fill_command_group)

    commands.add_command(digital_fill_command_group)

    commands.add_command(xt_asset_command_group)
    commands.add_command(xt_trade_command_group)
    commands.add_command(xt_order_command_group)
    commands.add_command(xt_position_command_group)

    commands.add_command(channel_command_group)
    commands.add_command(om_order_command_group)

    commands()


if __name__ == '__main__':
    main()
