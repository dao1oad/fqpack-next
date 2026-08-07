# -*- coding: utf-8 -*-

import json

import click

from freshquant.order_management.guardian.slice_evaluation import (
    evaluate_guardian_sell_slices,
    normalize_price_to_tick,
    resolve_sell_threshold_config,
)
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.strategy.toolkit.threshold import eval_stock_threshold_price
from freshquant.util.code import normalize_to_base_code


def _echo_json(payload):
    click.echo(json.dumps(payload, ensure_ascii=False, default=str))


@click.group(name="guardian")
def guardian_command_group():
    pass


@click.group(name="guardian.sell")
def guardian_sell_command_group():
    pass


@guardian_sell_command_group.command(name="simulate")
@click.option("--code", type=str, required=True, help="6 位 base code")
@click.option("--signal-price", type=float, required=True)
@click.option("--account", type=str, default=None)
def guardian_sell_simulate_command(code, signal_price, account):
    """只读模拟 Guardian 卖出信号（零写库）。

    路径只包含只读 ``find()``（om_entry_slices 显式稳定排序）+ 统一逐切片
    判定函数 ``evaluate_guardian_sell_slices``；不写 order/request/trace 集合。
    """

    symbol = normalize_to_base_code(code)
    repository = OrderManagementRepository()
    open_slices = repository.list_open_entry_slices(symbol=symbol)

    if account not in {None, ""}:
        entries = repository.list_position_entries(symbol=symbol)
        account = str(account).strip()
        account_entry_ids = {
            str(item.get("entry_id") or "")
            for item in entries
            if str(item.get("account_id") or "").strip() == account
        }
        if account_entry_ids:
            open_slices = [
                item
                for item in open_slices
                if str(item.get("entry_id") or "") in account_entry_ids
            ]

    threshold_config = {"mode": "percent", "percent": 1}
    threshold_config_degraded = False
    if open_slices:
        lowest_price = min(
            (float(item.get("guardian_price") or 0.0) for item in open_slices),
            default=0.0,
        )
        if lowest_price > 0:
            try:
                threshold_result = eval_stock_threshold_price(
                    symbol,
                    lowest_price,
                )
                threshold_config = resolve_sell_threshold_config(threshold_result)
            except Exception:
                threshold_config_degraded = True

    result = evaluate_guardian_sell_slices(
        open_slices,
        signal_price=signal_price,
        threshold_config=threshold_config,
    )
    result.update(
        {
            "symbol": symbol,
            "account": account,
            "open_slice_count": len(open_slices),
            "threshold_config": threshold_config,
            "threshold_config_degraded": bool(threshold_config_degraded),
            "zero_write": True,
        }
    )
    _echo_json(result)


__all__ = [
    "guardian_command_group",
    "guardian_sell_command_group",
    "guardian_sell_simulate_command",
]
