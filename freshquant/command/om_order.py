# -*- coding: utf-8 -*-

import click

from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.util.code import normalize_to_base_code


def _get_order_submit_service():
    return OrderSubmitService()


@click.group(name="om-order")
def om_order_command_group():
    pass


@om_order_command_group.command(name="submit")
@click.option("--action", type=click.Choice(["buy", "sell"]), required=True)
@click.option("--symbol", required=True)
@click.option("--price", type=float, required=True)
@click.option("--quantity", type=int, required=True)
@click.option("--source", default="cli", show_default=True)
@click.option("--strategy-name", default=None)
@click.option("--remark", default=None)
def submit_command(action, symbol, price, quantity, source, strategy_name, remark):
    result = _get_order_submit_service().submit_order(
        {
            "action": action,
            "symbol": normalize_to_base_code(symbol),
            "price": price,
            "quantity": quantity,
            "source": source,
            "strategy_name": strategy_name,
            "remark": remark,
        }
    )
    click.echo(f"submitted {result['internal_order_id']} {result['request_id']}")


@om_order_command_group.command(name="cancel")
@click.option("--internal-order-id", required=True)
@click.option("--source", default="cli", show_default=True)
@click.option("--strategy-name", default=None)
@click.option("--remark", default=None)
def cancel_command(internal_order_id, source, strategy_name, remark):
    result = _get_order_submit_service().cancel_order(
        {
            "internal_order_id": internal_order_id,
            "source": source,
            "strategy_name": strategy_name,
            "remark": remark,
        }
    )
    click.echo(f"canceled {result['internal_order_id']} {result['request_id']}")
