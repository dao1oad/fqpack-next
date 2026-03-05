# coding=utf-8

import json

import click
import pendulum

import fqxtrade.xtquant.broker as broker
from fqxtrade import ORDER_QUEUE
from fqxtrade.database.redis import redis_db


@click.group()
def xtquant():
    pass


@xtquant.command(name="sync-deals")
@click.option("--force/--no-force", default=False)
def sync_deals(force):
    redis_db.lpush(
        ORDER_QUEUE,
        json.dumps(
            {
                "action": "sync-deals",
                "fire_time": pendulum.now().format("YYYY-MM-DD hh:mm:ss"),
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
                "fire_time": pendulum.now().format("YYYY-MM-DD hh:mm:ss"),
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
                "fire_time": pendulum.now().format("YYYY-MM-DD hh:mm:ss"),
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
                "fire_time": pendulum.now().format("YYYY-MM-DD hh:mm:ss"),
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
                "fire_time": pendulum.now().format("YYYY-MM-DD hh:mm:ss"),
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
    redis_db.lpush(
        ORDER_QUEUE,
        json.dumps(
            {
                "action": "buy",
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
                "fire_time": pendulum.now().format("YYYY-MM-DD hh:mm:ss"),
                "force": force,
            }
        ),
    )


@xtquant.command(name="sell")
@click.argument("symbol", type=str, required=True)
@click.option("-p", "--price", type=float, required=True)
@click.option("-q", "--quantity", type=int, default=100)
@click.option("-f", "--force/--no-force", default=False)
def sell(symbol: str, price: float, quantity: int, force: bool):
    redis_db.lpush(
        ORDER_QUEUE,
        json.dumps(
            {
                "action": "sell",
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
                "fire_time": pendulum.now().format("YYYY-MM-DD hh:mm:ss"),
                "force": force,
            }
        ),
    )


@xtquant.command(name="auto")
def auto():
    broker.main()
