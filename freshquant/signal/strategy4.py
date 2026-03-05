# -*- coding: utf-8 -*-

"""
策略4：回拉中枢或者突破中枢开仓
"""

import json
import logging
import time
import traceback
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pydash
import pymongo
import pytz
import rx
import talib as ta
from bson.codec_options import CodecOptions

from freshquant import Duan
from freshquant import divergence as divergence
from freshquant import pattern as pattern
from freshquant.basic.bi import CalcBi, CalcBiList
from freshquant.basic.duan import CalcDuan
from freshquant.db import DBfreshquant
from freshquant.funcat.api import *
from freshquant.funcat.data.HuobiDataBackend import HuobiDataBackend
from freshquant.funcat.utils import get_int_date

# from freshquant.Mail import Mail
from freshquant.signal.MarketData import is_data_feeding

tz = pytz.timezone('Asia/Shanghai')
# mail = Mail()


def doExecute(symbol, period, inspect_time=None, is_debug=False):
    logger = logging.getLogger()
    if not is_debug:
        if not is_data_feeding(symbol['code'], period):
            logger.info("%s 无数据更新 跳过%s监控" % (symbol['code'], period))
            return
    logger.info("策略4 %s %s" % (symbol['code'], period))
    raw_data = {}
    bars = (
        DBfreshquant['%s_%s' % (symbol['code'].lower(), period)]
        .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
        .find()
        .sort('_id', pymongo.DESCENDING)
        .limit(1000)
    )
    bars = list(bars)
    if len(bars) < 13:
        return
    time_series = []
    high_series = []
    low_series = []
    open_series = []
    close_series = []
    count = len(bars)
    for i in range(count - 1, -1, -1):
        time_series.append(bars[i]['_id'])
        high_series.append(bars[i]['high'])
        low_series.append(bars[i]['low'])
        open_series.append(bars[i]['open'])
        close_series.append(bars[i]['close'])

    # 笔信号
    bi_series = [0 for i in range(count)]
    CalcBi(count, bi_series, high_series, low_series, open_series, close_series)
    duan_series = [0 for i in range(count)]
    CalcDuan(count, duan_series, bi_series, high_series, low_series)

    higher_duan_series = [0 for i in range(count)]
    CalcDuan(count, higher_duan_series, duan_series, high_series, low_series)

    # 笔中枢的会拉和突破
    entanglement_list = pattern.CalcEntanglements(
        time_series, duan_series, bi_series, high_series, low_series
    )
    zs_huila = pattern.la_hui(
        entanglement_list, time_series, high_series, low_series, bi_series, duan_series
    )
    zs_tupo = pattern.tu_po(
        entanglement_list,
        time_series,
        high_series,
        low_series,
        open_series,
        close_series,
        bi_series,
        duan_series,
    )

    count = len(zs_huila['buy_zs_huila']['date'])
    for i in range(count):
        saveLog(
            symbol,
            period,
            raw_data,
            True,
            '拉回中枢确认底背',
            zs_huila['buy_zs_huila']['date'][i],
            zs_huila['buy_zs_huila']['data'][i],
            'BuyLong',
        )
    count = len(zs_huila['sell_zs_huila']['date'])
    for i in range(count):
        saveLog(
            symbol,
            period,
            raw_data,
            True,
            '拉回中枢确认顶背',
            zs_huila['sell_zs_huila']['date'][i],
            zs_huila['sell_zs_huila']['data'][i],
            'SellShort',
        )

    count = len(zs_tupo['buy_zs_tupo']['date'])
    for i in range(count):
        saveLog(
            symbol,
            period,
            raw_data,
            True,
            '突破中枢开多',
            zs_tupo['buy_zs_tupo']['date'][i],
            zs_tupo['buy_zs_tupo']['data'][i],
            'BuyLong',
        )
    count = len(zs_tupo['sell_zs_tupo']['date'])
    for i in range(count):
        saveLog(
            symbol,
            period,
            raw_data,
            True,
            '突破中枢开空',
            zs_tupo['sell_zs_tupo']['date'][i],
            zs_tupo['sell_zs_tupo']['data'][i],
            'SellShort',
        )

    # 段中枢的回拉和突破
    higher_entaglement_list = pattern.CalcEntanglements(
        time_series, higher_duan_series, duan_series, high_series, low_series
    )
    higher_zs_huila = pattern.la_hui(
        higher_entaglement_list,
        time_series,
        high_series,
        low_series,
        duan_series,
        higher_duan_series,
    )
    higher_zs_tupo = pattern.tu_po(
        higher_entaglement_list,
        time_series,
        high_series,
        low_series,
        open_series,
        close_series,
        duan_series,
        higher_duan_series,
    )

    count = len(higher_zs_huila['buy_zs_huila']['date'])
    for i in range(count):
        saveLog(
            symbol,
            period,
            raw_data,
            True,
            '拉回中枢确认底背',
            higher_zs_huila['buy_zs_huila']['date'][i],
            higher_zs_huila['buy_zs_huila']['data'][i],
            'BuyLong',
        )
    count = len(higher_zs_huila['sell_zs_huila']['date'])
    for i in range(count):
        saveLog(
            symbol,
            period,
            raw_data,
            True,
            '拉回中枢确认顶背',
            higher_zs_huila['sell_zs_huila']['date'][i],
            higher_zs_huila['sell_zs_huila']['data'][i],
            'SellShort',
        )

    count = len(higher_zs_tupo['buy_zs_tupo']['date'])
    for i in range(count):
        saveLog(
            symbol,
            period,
            raw_data,
            True,
            '突破中枢开多',
            higher_zs_tupo['buy_zs_tupo']['date'][i],
            higher_zs_tupo['buy_zs_tupo']['data'][i],
            'BuyLong',
        )
    count = len(higher_zs_tupo['sell_zs_tupo']['date'])
    for i in range(count):
        saveLog(
            symbol,
            period,
            raw_data,
            True,
            '突破中枢开空',
            higher_zs_tupo['sell_zs_tupo']['date'][i],
            higher_zs_tupo['sell_zs_tupo']['data'][i],
            'SellShort',
        )


def saveLog(symbol, period, raw_data, signal, remark, fire_time, price, position):
    logger = logging.getLogger()
    last_fire = (
        DBfreshquant['strategy4_log']
        .find(
            {
                'symbol': symbol['code'],
                'period': period,
                'fire_time': fire_time,
                'position': position,
            }
        )
        .count()
    )
    if last_fire > 0:
        DBfreshquant['strategy4_log'].with_options(
            codec_options=CodecOptions(tz_aware=True, tzinfo=tz)
        ).find_one_and_update(
            {
                'symbol': symbol['code'],
                'period': period,
                'fire_time': fire_time,
                'position': position,
            },
            {
                '$set': {
                    'remark': remark,
                    'price': price,
                    'date_created': datetime.now(tz),
                },
                '$inc': {'update_count': 1},
            },
            upsert=True,
        )
    else:
        date_created = datetime.now(tz)
        DBfreshquant['strategy4_log'].insert_one(
            {
                'symbol': symbol['code'],
                'period': period,
                'raw_data': raw_data,
                'signal': True,
                'remark': remark,
                'date_created': date_created,  # 记录插入的时间
                'fire_time': fire_time,  # 背驰发生的时间
                'price': price,
                'position': position,
                'update_count': 1,  # 这条背驰记录的更新次数
            }
        )
        if (date_created - fire_time).total_seconds() < 600:
            # 在10分钟内的触发邮件通知
            msg = {
                "开仓策略": "策略4",
                "标的代码": symbol['code'],
                "触发周期": period,
                "触发时间": fire_time.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S'),
                "触发价格": price,
                "开仓方向": position,
                "备注": remark,
            }
            # mailResult = mail.send(json.dumps(msg, ensure_ascii=False, indent=4))
            # logger.info(mailResult)


def doCaculate(symbol, inspect_time=None, is_debug=False):
    logger = logging.getLogger()
    periods = ['3m', '5m', '15m', '30m', '1h', '180m', '1d']
    for period in periods:
        try:
            doExecute(symbol, period, inspect_time, is_debug)
        except BaseException as e:
            logger.info("Error Occurred: {0}".format(traceback.format_exc()))
    DBfreshquant['symbol'].update_one(
        {"code": symbol['code']}, {"$set": {"strategy_4_updated": datetime.now(tz)}}
    )
