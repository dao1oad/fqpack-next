# coding=utf-8

import json

import click
import fqxtrade.xtquant.broker as broker

from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.util.code import normalize_to_base_code
from freshquant.xt_account_sync.service import XtAccountSyncService


@click.group()
def xtquant():
    pass


def _get_order_submit_service():
    return OrderSubmitService()


def _get_xt_account_sync_service():
    return XtAccountSyncService.build_default()


def _echo_sync_result(result):
    click.echo(json.dumps(result, ensure_ascii=False))


@xtquant.command(name="sync-deals")
@click.option("--force/--no-force", default=False)
def sync_deals(force):
    del force
    _echo_sync_result(_get_xt_account_sync_service().sync_trades())


@xtquant.command(name="sync-trades")
@click.option("--force/--no-force", default=False)
def sync_trades(force):
    del force
    _echo_sync_result(_get_xt_account_sync_service().sync_trades())


@xtquant.command(name="sync-orders")
@click.option("--force/--no-force", default=False)
def sync_orders(force):
    del force
    _echo_sync_result(_get_xt_account_sync_service().sync_orders())


@xtquant.command(name="sync-summary")
@click.option("--force/--no-force", default=False)
def sync_summary(force):
    del force
    service = _get_xt_account_sync_service()
    _echo_sync_result(
        {
            "assets": service.sync_assets(),
            "credit_detail": service.sync_credit_detail(),
        }
    )


@xtquant.command(name="sync-positions")
@click.option("--force/--no-force", default=False)
def sync_positions(force):
    del force
    _echo_sync_result(_get_xt_account_sync_service().sync_positions())


@xtquant.command(name="buy")
@click.argument("symbol", type=str, required=True)
@click.option("-p", "--price", type=float, required=True)
@click.option("-q", "--quantity", type=int, default=100)
@click.option("-f", "--force/--no-force", default=False)
def buy(symbol: str, price: float, quantity: int, force: bool):
    result = _get_order_submit_service().submit_order(
        {
            "action": "buy",
            "symbol": normalize_to_base_code(symbol),
            "price": price,
            "quantity": quantity,
            "source": "cli",
            "force": force,
            "strategy_name": "XtQuantCli",
        }
    )
    click.echo(f"submitted {result['internal_order_id']} {result['request_id']}")


@xtquant.command(name="sell")
@click.argument("symbol", type=str, required=True)
@click.option("-p", "--price", type=float, required=True)
@click.option("-q", "--quantity", type=int, default=100)
@click.option("-f", "--force/--no-force", default=False)
def sell(symbol: str, price: float, quantity: int, force: bool):
    result = _get_order_submit_service().submit_order(
        {
            "action": "sell",
            "symbol": normalize_to_base_code(symbol),
            "price": price,
            "quantity": quantity,
            "source": "cli",
            "force": force,
            "strategy_name": "XtQuantCli",
        }
    )
    click.echo(f"submitted {result['internal_order_id']} {result['request_id']}")


@xtquant.command(name="cancel")
@click.option("--internal-order-id", type=str, required=True)
def cancel(internal_order_id: str):
    result = _get_order_submit_service().cancel_order(
        {
            "internal_order_id": internal_order_id,
            "source": "cli",
            "strategy_name": "XtQuantCli",
        }
    )
    click.echo(f"canceled {result['internal_order_id']} {result['request_id']}")


@xtquant.command(name="auto")
def auto():
    broker.main()
