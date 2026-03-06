# coding=utf-8

import json
from datetime import datetime

import click

import fqxtrade.xtquant.broker as broker
from fqxtrade import ORDER_QUEUE
from fqxtrade.database.redis import redis_db
from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.util.code import normalize_to_base_code


@click.group()
def xtquant():
    pass


def _get_order_submit_service():
    return OrderSubmitService()


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@xtquant.command(name="sync-deals")
@click.option("--force/--no-force", default=False)
def sync_deals(force):
    redis_db.lpush(
        ORDER_QUEUE,
        json.dumps(
            {
                "action": "sync-deals",
                "fire_time": _now_str(),
                "force": force,
            }
        ),
    )


@xtquant.command(name="sync-trades")
@click.option("--force/--no-force", default=False)
def sync_trades(force):
    redis_db.lpush(
        ORDER_QUEUE,
        json.dumps(
            {
                "action": "sync-trades",
                "fire_time": _now_str(),
                "force": force,
            }
        ),
    )


@xtquant.command(name="sync-orders")
@click.option("--force/--no-force", default=False)
def sync_orders(force):
    redis_db.lpush(
        ORDER_QUEUE,
        json.dumps(
            {
                "action": "sync-orders",
                "fire_time": _now_str(),
                "force": force,
            }
        ),
    )


@xtquant.command(name="sync-summary")
@click.option("--force/--no-force", default=False)
def sync_summary(force):
    redis_db.lpush(
        ORDER_QUEUE,
        json.dumps(
            {
                "action": "sync-summary",
                "fire_time": _now_str(),
                "force": force,
            }
        ),
    )


@xtquant.command(name="sync-positions")
@click.option("--force/--no-force", default=False)
def sync_positions(force):
    redis_db.lpush(
        ORDER_QUEUE,
        json.dumps(
            {
                "action": "sync-positions",
                "fire_time": _now_str(),
                "force": force,
            }
        ),
    )


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
