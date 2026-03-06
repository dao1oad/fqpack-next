# -*- coding: utf-8 -*-

from importlib import import_module

import click


LAZY_COMMANDS: dict[str, tuple[str, str, str]] = {
    "stock": ("freshquant.command.stock", "stock_command_group", "股票主命令"),
    "stock.list": ("freshquant.command.stock", "stock_list_command_group", "股票列表"),
    "stock.block": ("freshquant.command.stock", "stock_block_command_group", "股票板块"),
    "stock.day": ("freshquant.command.stock", "stock_day_command_group", "股票日线"),
    "stock.min": ("freshquant.command.stock", "stock_min_command_group", "股票分钟线"),
    "stock.xdxr": ("freshquant.command.stock", "stock_xdxr_command_group", "股票除权除息"),
    "stock.must-pool": (
        "freshquant.command.stock",
        "stock_must_pool_command_group",
        "股票必选池",
    ),
    "stock.pool": ("freshquant.command.stock", "stock_pool_command_group", "股票池"),
    "stock.pre-pool": (
        "freshquant.command.stock",
        "stock_pre_pool_command_group",
        "股票预选池",
    ),
    "stock.fill": ("freshquant.command.stock", "stock_fill_command_group", "股票成交"),
    "etf": ("freshquant.command.etf", "etf_command_group", "ETF 主命令"),
    "etf.list": ("freshquant.command.etf", "etf_list_command_group", "ETF 列表"),
    "etf.day": ("freshquant.command.etf", "etf_day_command_group", "ETF 日线"),
    "etf.min": ("freshquant.command.etf", "etf_min_command_group", "ETF 分钟线"),
    "index": ("freshquant.command.index", "index_command_group", "指数主命令"),
    "index.list": ("freshquant.command.index", "index_list_command_group", "指数列表"),
    "index.day": ("freshquant.command.index", "index_day_command_group", "指数日线"),
    "index.min": ("freshquant.command.index", "index_min_command_group", "指数分钟线"),
    "bond": ("freshquant.command.bond", "bond_command_group", "债券主命令"),
    "bond.list": ("freshquant.command.bond", "bond_list_command_group", "债券列表"),
    "bond.day": ("freshquant.command.bond", "bond_day_command_group", "债券日线"),
    "bond.min": ("freshquant.command.bond", "bond_min_command_group", "债券分钟线"),
    "future": ("freshquant.command.future", "future_command_group", "期货主命令"),
    "future.list": ("freshquant.command.future", "future_list_command_group", "期货列表"),
    "future.day": ("freshquant.command.future", "future_day_command_group", "期货日线"),
    "future.min": ("freshquant.command.future", "future_min_command_group", "期货分钟线"),
    "future.fill": (
        "freshquant.command.future",
        "future_fill_command_group",
        "期货成交",
    ),
    "digital.fill": (
        "freshquant.command.digital",
        "digital_fill_command_group",
        "数字货币成交",
    ),
    "xt-asset": ("freshquant.command.asset", "xt_asset_command_group", "XT 资产"),
    "xt-trade": ("freshquant.command.trade", "xt_trade_command_group", "XT 成交"),
    "xt-order": ("freshquant.command.order", "xt_order_command_group", "XT 委托"),
    "xt-position": (
        "freshquant.command.position",
        "xt_position_command_group",
        "XT 持仓",
    ),
    "channel": ("freshquant.command.channel", "channel_command_group", "缠论频道"),
    "om-order": (
        "freshquant.command.om_order",
        "om_order_command_group",
        "订单管理",
    ),
}


class LazyGroup(click.Group):
    def __init__(self, *args, lazy_subcommands=None, **kwargs):
        self.lazy_subcommands = lazy_subcommands or {}
        super().__init__(*args, **kwargs)

    def list_commands(self, ctx):
        return list(self.lazy_subcommands.keys())

    def get_command(self, ctx, cmd_name):
        command_spec = self.lazy_subcommands.get(cmd_name)
        if not command_spec:
            return super().get_command(ctx, cmd_name)

        module_path, attr_name, _ = command_spec
        module = import_module(module_path)
        return getattr(module, attr_name)

    def format_commands(self, ctx, formatter):
        rows = [
            (name, help_text)
            for name, (_, _, help_text) in self.lazy_subcommands.items()
        ]
        if rows:
            with formatter.section("Commands"):
                formatter.write_dl(rows)


@click.group(cls=LazyGroup, lazy_subcommands=LAZY_COMMANDS)
def commands():
    pass


def main():
    commands()


if __name__ == "__main__":
    main()
