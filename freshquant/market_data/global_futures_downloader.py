# -*- coding: utf-8 -*-
import datetime
import json
import re
import signal
import threading
import time
import traceback

import pandas as pd
import pytz
import requests
from loguru import logger
from pymongo import UpdateOne

from freshquant.config import config
from freshquant.db import DBfreshquant

tz = pytz.timezone('Asia/Shanghai')


symbol_list = config['global_future_symbol']
min_list = ['5', '15', '30', '60']

is_run = True
is_loop = True


def fetch_global_futures_mink():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:73.0) Gecko/20100101 Firefox/73.0"
    }
    while is_run:
        # 取分钟数据
        for minute in min_list:
            for symbol in symbol_list:
                try:
                    var = "_%s_%s_%s" % (
                        symbol,
                        minute,
                        datetime.datetime.now().timestamp(),
                    )
                    url = (
                        "https://gu.sina.cn/ft/api/jsonp.php/var %s=/GlobalService.getMink?symbol=%s&type=%s"
                        % (var, symbol, minute)
                    )
                    response = requests.get(url, headers=headers, timeout=(15, 15))
                    response_text = response.text
                    m = re.search(r'\((.*)\)', response.text)
                    content = m.group(1)
                    df = pd.DataFrame(json.loads(content))
                    df['d'] = df['d'].apply(
                        lambda x: datetime.datetime.strptime(x, '%Y-%m-%d %H:%M:%S')
                    )
                    df.set_index("d", inplace=True)
                    save_data_m(symbol, '%sm' % minute, df)
                    # 合成180F数据
                    if minute == '30':
                        ohlc_dict = {
                            'o': 'first',
                            'h': 'max',
                            'l': 'min',
                            'c': 'last',
                            'v': 'sum',
                        }
                        df180m = (
                            df.resample('180T', closed='right', label='right')
                            .agg(ohlc_dict)
                            .dropna(how='any')
                        )
                        save_data_m(symbol, '180m', df180m)
                    time.sleep(1)
                    if not is_run:
                        break
                except BaseException as e:
                    logger.error("Error Occurred: {0}".format(traceback.format_exc()))

            if not is_run:
                break
        # 取日线数据
        if is_run:
            for symbol in symbol_list:
                try:
                    d = datetime.datetime.now().strftime('%Y_%m_%d')
                    var = "_%s_%s" % (symbol, d)
                    url = (
                        "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var %s=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=%s&_=%s&source=web"
                        % (var, symbol, d)
                    )
                    response = requests.get(url, headers=headers, timeout=(15, 15))
                    response_text = response.text
                    m = re.search(r'\((.*)\)', response_text)
                    content = m.group(1)
                    df = pd.DataFrame(json.loads(content))
                    df['date'] = df['date'].apply(
                        lambda x: datetime.datetime.strptime(x, '%Y-%m-%d')
                    )
                    df.set_index('date', inplace=True)
                    save_data_d(symbol, '1d', df)
                    # 合成3d数据
                    ohlc_dict = {
                        'open': 'first',
                        'high': 'max',
                        'low': 'min',
                        'close': 'last',
                        'volume': 'sum',
                    }
                    df3d = (
                        df.resample('3D', closed='right', label='right')
                        .agg(ohlc_dict)
                        .dropna(how='any')
                    )
                    save_data_d(symbol, '3d', df3d)
                    time.sleep(1)
                    if not is_run:
                        break
                except BaseException as e:
                    logger.error("Error Occurred: {0}".format(traceback.format_exc()))
        time.sleep(300)
        if not is_loop:
            break
    logger.info("外盘分钟数据抓取程序已停止。")


def save_data_m(code, period, df):
    if not df.empty:
        logger.info("保存 %s %s %s" % (code, period, df.index.values[-1]))
    batch = []
    for idx, row in df.iterrows():
        batch.append(
            UpdateOne(
                {"_id": idx.replace(tzinfo=tz)},
                {
                    "$set": {
                        "open": float(row['o']),
                        "close": float(row['c']),
                        "high": float(row['h']),
                        "low": float(row['l']),
                        "volume": float(row['v']),
                    }
                },
                upsert=True,
            )
        )
        if len(batch) >= 100:
            DBfreshquant["%s_%s" % (code, period)].bulk_write(batch)
            batch = []
    if len(batch) > 0:
        DBfreshquant["%s_%s" % (code, period)].bulk_write(batch)
        batch = []


def save_data_d(code, period, df):
    if not df.empty:
        logger.info("保存 %s %s %s" % (code, period, df.index.values[-1]))
    batch = []
    for idx, row in df.iterrows():
        batch.append(
            UpdateOne(
                {"_id": idx.replace(tzinfo=tz)},
                {
                    "$set": {
                        "open": float(row['open']),
                        "close": float(row['close']),
                        "high": float(row['high']),
                        "low": float(row['low']),
                        "volume": float(row['volume']),
                    }
                },
                upsert=True,
            )
        )
        if len(batch) >= 100:
            DBfreshquant["%s_%s" % (code, period)].bulk_write(batch)
            batch = []
    if len(batch) > 0:
        DBfreshquant["%s_%s" % (code, period)].bulk_write(batch)
        batch = []


def signal_handler(signalnum, frame):
    logger.info("正在停止程序。")
    global is_run
    is_run = False


def run(**kwargs):
    signal.signal(signal.SIGINT, signal_handler)
    global is_loop
    is_loop = kwargs.get("loop")
    thread_list = [threading.Thread(target=fetch_global_futures_mink)]

    for thread in thread_list:
        thread.start()

    while True:
        for thread in thread_list:
            if thread.is_alive():
                break
        else:
            break


if __name__ == '__main__':
    run()
