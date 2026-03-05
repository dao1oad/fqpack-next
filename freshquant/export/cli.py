# -*- coding: utf-8 -*-

import json

import click
import pandas as pd
import pydash
import pymongo
from bson.codec_options import CodecOptions
from loguru import logger

from freshquant.config import cfg, settings
from freshquant.db import DBfreshquant


@click.group()
def export_factors():
    pass


@click.group()
def export_signals():
    pass


@click.group()
def export_pools():
    pass


@export_factors.command(name="stock")
@click.option('--out', type=str)
def export_stock_factors(out):
    out = 'stock_factors.xlsx' if out is None else out
    periods = pydash.get(settings, 'stock.periods')
    factors = pydash.get(settings, 'stock.factors')
    factors = (
        pydash.chain(factors)
        .filter_(lambda r: r.get('period') in periods)
        .map(lambda r: r.name)
        .value()
    )
    stock_factors = (
        DBfreshquant["stock_factors"]
        .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=cfg.TZ))
        .find({}, {"_id": 0})
    )
    stock_factors = pd.DataFrame(stock_factors)
    stock_factors = stock_factors.sort_values(
        by=['datetime', 'code'], ascending=[False, False]
    )
    stock_factors["datetime"] = stock_factors["datetime"].apply(
        lambda x: x.strftime("%Y-%m-%d")
    )
    stock_factors["updated_at"] = stock_factors["updated_at"].apply(
        lambda x: x.strftime("%Y-%m-%d %H:%M:%S")
    )
    factors = (
        pydash.chain(factors).filter_(lambda r: r in stock_factors.columns).value()
    )
    stock_factors = stock_factors[['datetime', 'symbol', 'name'] + factors]
    stock_factors.to_excel(out, index=False)


@export_signals.command(name="stock")
@click.option('--out', type=str)
def export_stock_signals(out):
    out = 'stock_signals.xlsx' if out is None else out
    stock_signal = (
        DBfreshquant["stock_signals"]
        .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=cfg.TZ))
        .find({}, {"_id": 0})
        .sort("fire_time", pymongo.DESCENDING)
    )
    stock_signal = pd.DataFrame(stock_signal)
    stock_signal["fire_time"] = stock_signal["fire_time"].apply(
        lambda x: x.strftime("%Y-%m-%d %H:%M")
    )
    stock_signal.to_excel(out, index=False)


@export_pools.command(name="stock")
@click.option('--cond', type=str)
def export_stock_pools(cond):
    periods = pydash.get(settings, 'stock.periods')
    factors = pydash.get(settings, 'stock.factors')
    factors = (
        pydash.chain(factors)
        .filter_(lambda r: r.get('period') in periods)
        .map(lambda r: r.name)
        .value()
    )
    if cond is None:
        stock_pools = pydash.get(settings, 'stock.pools')
        for stock_pool in stock_pools:
            stock_pool_records = (
                DBfreshquant["stock_factors"]
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=cfg.TZ))
                .find(stock_pool.get('cond', {}), {"_id": 0})
            )
            stock_pool_records = pd.DataFrame(stock_pool_records)
            if len(stock_pool_records) > 0:
                stock_pool_records = stock_pool_records.sort_values(
                    by=['datetime', 'code'], ascending=[False, False]
                )
                stock_pool_records["datetime"] = stock_pool_records["datetime"].apply(
                    lambda x: x.strftime("%Y-%m-%d")
                )
                stock_pool_records["updated_at"] = stock_pool_records[
                    "updated_at"
                ].apply(lambda x: x.strftime("%Y-%m-%d %H:%M:%S"))
                factors = (
                    pydash.chain(factors)
                    .filter_(lambda r: r in stock_pool_records.columns)
                    .value()
                )
                stock_pool_records = stock_pool_records[
                    ['datetime', 'symbol', 'name'] + factors
                ]
                stock_pool_records.to_excel(
                    "%s.xlsx" % stock_pool.get('name'), index=False
                )
            else:
                logger.info("（无数据）%s" % stock_pool.get('name'))
    else:
        stock_pool_records = (
            DBfreshquant["stock_factors"]
            .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=cfg.TZ))
            .find(json.loads(cond), {"_id": 0})
        )
        stock_pool_records = pd.DataFrame(stock_pool_records)
        if len(stock_pool_records) > 0:
            stock_pool_records = stock_pool_records.sort_values(
                by=['datetime', 'code'], ascending=[False, False]
            )
            stock_pool_records["datetime"] = stock_pool_records["datetime"].apply(
                lambda x: x.strftime("%Y-%m-%d")
            )
            stock_pool_records["updated_at"] = stock_pool_records["updated_at"].apply(
                lambda x: x.strftime("%Y-%m-%d %H:%M:%S")
            )
            factors = (
                pydash.chain(factors)
                .filter_(lambda r: r in stock_pool_records.columns)
                .value()
            )
            stock_pool_records = stock_pool_records[
                ['datetime', 'symbol', 'name'] + factors
            ]
            stock_pool_records.to_excel("%s.xlsx" % "stock_pool", index=False)
        else:
            logger.info("无数据")
