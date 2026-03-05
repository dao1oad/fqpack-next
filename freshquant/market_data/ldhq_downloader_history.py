# -*- coding: utf-8 -*-

import hashlib
import json
import logging
import re
import signal
import threading
import time
import traceback
from datetime import datetime, timedelta
from io import StringIO

import pandas as pd
import pytz
import requests
from pymongo import UpdateOne

from freshquant.config import config
from freshquant.db import DBfreshquant
from freshquant.DingMsg import DingMsg

tz = pytz.timezone('Asia/Shanghai')

"""
python freshquant\market_data\global_futures.py
"""

ohlc_dict = {'开盘价': 'first', '最高价': 'max', '最低价': 'min', '收盘价': 'last', '成交量': 'sum'}

stocks = config['global_stock_symbol']
# futures = config['global_future_symbol_origin']
futures = ['03NID', '@ZS0W', '@ZM0Y', '@ZL0W', 'CPO0W', 'CT0W']
# 转化成简称入库
global_future_alias = config['global_future_alias']
global_future_symbol = config['global_future_symbol']
is_run = True
pwd = hashlib.md5(b'chanlun123456').hexdigest()

#  美国股票以及  CL原油 GC 黄金 SI 白银  CT 棉花  时间比北京时间慢了 12小时;
#  YM 道琼斯指数  ZS ZM ZL 比北京时间慢了 13小时;
#  NID 伦镍 比北京时间少了5小时.
#  其他的不用转换

add_5_hours_symbol_origin = ['03NID']
add_12_hours_symbol_origin = ['@CL0W', '@GC0W', '@SI0W', 'CT0W']
add_13_hours_symbol_origin = ['@YM0Y,@ZS0W', '@ZM0Y', '@ZL0W']

# 需要增加12小时的品种
add_5_hours_symbol = ['NID']
add_12_hours_symbol = ['CL', 'GC', 'SI', 'CT']
add_13_hours_symbol = ['YM', 'ZS', 'ZM', 'ZL']

# 1、5、15、30、60、d、w、
'''
1分钟接口返回的数据格式：

日期
20200417
品种代码,时间,开盘价,最高价,最低价,收盘价,成交量,成交额
AAPL,12:41,280.575,280.83,280.548,280.818,76079,21355900

5分钟接口返回的数据格式：

品种代码,时间,开盘价,最高价,最低价,收盘价,成交量,成交额
AAPL,20200312 11:55,252.36,252.48,251,252.12,1153129,290429100

日线 周线 返回的数据格式：

品种代码,日期,开盘价,最高价,最低价,收盘价,成交量,成交额
AAPL,20180628,184.1,186.21,183.8,185.5,17365235,3215599000

三种情况兼容处理

'''
dingMsg = DingMsg()


def fetch_stocks_mink():
    while is_run:
        try:
            # 取分钟数据
            url = (
                "http://ldhqsj.com/us_pluralK.action?username=chanlun&password="
                + pwd
                + "&id="
                + ",".join(stocks)
                + "&jys=NA&period=1&num=-200"
            )
            print(url)
            resp = requests.get(url, timeout=(15, 15))
            content = resp.text
            f = StringIO(content)
            lines = f.readlines()
            date_str = None
            if lines[0].strip() == '日期':
                date_str = lines[1].strip()
                lines = lines[2:]
            df = pd.read_csv(StringIO("".join(lines)))
            if date_str is not None:
                df['时间'] = df['时间'].apply(lambda x: date_str + ' ' + x)

            if '时间' in df.columns.values:
                df['时间'] = df['时间'].apply(
                    lambda x: datetime.strptime(x, '%Y%m%d %H:%M') + timedelta(hours=12)
                )
                df.set_index('时间', inplace=True)
            elif '日期' in df.columns.values:
                df['日期'] = df['日期'].apply(
                    lambda x: datetime.strptime(str(x), '%Y%m%d') + timedelta(hours=12)
                )
                df.set_index('日期', inplace=True)

            for code in stocks:
                df1m = df[df['品种代码'] == code]
                # 将外盘期货转化成简称
                if code in futures:
                    code = global_future_alias[code]
                save_data_m(code, '1m', df1m)
                # 3m
                df3m = (
                    df1m.resample('3T', closed='right', label='right')
                    .agg(ohlc_dict)
                    .dropna(how='any')
                )
                save_data_m(code, '3m', df3m)
                # 5m
                df5m = (
                    df1m.resample('5T', closed='right', label='right')
                    .agg(ohlc_dict)
                    .dropna(how='any')
                )
                save_data_m(code, '5m', df5m)
                # 15m
                df15m = (
                    df1m.resample('15T', closed='right', label='right')
                    .agg(ohlc_dict)
                    .dropna(how='any')
                )
                save_data_m(code, '15m', df15m)
                # 30m
                df30m = (
                    df1m.resample('30T', closed='right', label='right')
                    .agg(ohlc_dict)
                    .dropna(how='any')
                )
                save_data_m(code, '30m', df30m)
                # 60mm
                df60m = (
                    df1m.resample('60T', closed='right', label='right')
                    .agg(ohlc_dict)
                    .dropna(how='any')
                )
                save_data_m(code, '60m', df60m)
                # 180m
                df180m = (
                    df1m.resample('180T', closed='right', label='right')
                    .agg(ohlc_dict)
                    .dropna(how='any')
                )
                save_data_m(code, '180m', df180m)
                # 1D
                df1d = (
                    df1m.resample('1D', closed='right', label='right')
                    .agg(ohlc_dict)
                    .dropna(how='any')
                )
                save_data_m(code, '1d', df1d)
                # 3D
                df3d = (
                    df1d.resample('3D', closed='right', label='right')
                    .agg(ohlc_dict)
                    .dropna(how='any')
                )
                save_data_m(code, '3d', df3d)
        except Exception:
            print("外盘股票采集出错", Exception)
            # dingMsg.send("remind外盘股票采集出错")
        if not is_run:
            break
        time.sleep(20)


def fetch_futures_mink():
    while is_run:
        try:
            # 取分钟数据
            url = (
                "http://ldhqsj.com/foreign_pluralK.action?username=chanlun&password="
                + pwd
                + "&id="
                + ",".join(futures)
                + "&period=60&num=-1000"
            )
            print(url)
            resp = requests.get(url, timeout=(15, 15))
            content = resp.text
            f = StringIO(content)
            lines = f.readlines()
            date_str = None
            if lines[0].strip() == '日期':
                date_str = lines[1].strip()
                lines = lines[2:]
            df = pd.read_csv(StringIO("".join(lines)))
            if date_str is not None:
                df['时间'] = df['时间'].apply(lambda x: date_str + ' ' + x)
            # if '时间' in df.columns.values:
            #     df.set_index('时间', inplace=False)
            # elif '日期' in df.columns.values:
            #     df.set_index('日期', inplace=False)
            for code in futures:
                df1m = df[df['品种代码'] == code]
                if code in futures:
                    code = global_future_alias[code]
                if '时间' in df.columns.values:
                    if code in add_5_hours_symbol:
                        df1m['时间'] = df1m['时间'].apply(
                            lambda x: datetime.strptime(x, '%Y%m%d %H:%M')
                            + timedelta(hours=5)
                        )
                    elif code in add_12_hours_symbol:
                        df1m['时间'] = df1m['时间'].apply(
                            lambda x: datetime.strptime(x, '%Y%m%d %H:%M')
                            + timedelta(hours=12)
                        )
                    elif code in add_13_hours_symbol:
                        df1m['时间'] = df1m['时间'].apply(
                            lambda x: datetime.strptime(x, '%Y%m%d %H:%M')
                            + timedelta(hours=13)
                        )
                    else:
                        df1m['时间'] = df1m['时间'].apply(
                            lambda x: datetime.strptime(x, '%Y%m%d %H:%M')
                        )
                    df1m.set_index('时间', inplace=True)
                elif '日期' in df.columns.values:
                    if code in add_5_hours_symbol:
                        df1m['日期'] = df1m['日期'].apply(
                            lambda x: datetime.strptime(str(x), '%Y%m%d')
                            + timedelta(hours=5)
                        )
                    elif code in add_12_hours_symbol:
                        df1m['日期'] = df1m['日期'].apply(
                            lambda x: datetime.strptime(str(x), '%Y%m%d')
                            + timedelta(hours=12)
                        )
                    elif code in add_13_hours_symbol:
                        df1m['日期'] = df1m['日期'].apply(
                            lambda x: datetime.strptime(str(x), '%Y%m%d')
                            + timedelta(hours=13)
                        )
                    else:
                        df1m['日期'] = df1m['日期'].apply(
                            lambda x: datetime.strptime(str(x), '%Y%m%d')
                        )
                    df1m.set_index('日期', inplace=True)

                save_data_m(code, '60m', df1m)
                # 3m
                # df3m = df1m.resample('3T', closed='right', label='right').agg(ohlc_dict).dropna(how='any')
                # save_data_m(code, '3m', df3m)
                # 5m
                # df5m = df1m.resample('5T', closed='right', label='right').agg(ohlc_dict).dropna(how='any')
                # save_data_m(code, '5m', df5m)
                # # 15m
                # df15m = df1m.resample('15T', closed='right', label='right').agg(ohlc_dict).dropna(how='any')
                # save_data_m(code, '15m', df15m)
                # # 30m
                # df30m = df1m.resample('30T', closed='right', label='right').agg(ohlc_dict).dropna(how='any')
                # save_data_m(code, '30m', df30m)
                # # 60mm
                # df60m = df1m.resample('60T', closed='right', label='right').agg(ohlc_dict).dropna(how='any')
                # save_data_m(code, '60m', df60m)
                # # 180m
                df180m = (
                    df1m.resample('180T', closed='right', label='right')
                    .agg(ohlc_dict)
                    .dropna(how='any')
                )
                save_data_m(code, '180m', df180m)
                # # 1D
                # df1d = df1m.resample('1D', closed='right', label='right').agg(ohlc_dict).dropna(how='any')
                # save_data_m(code, '1d', df1d)
                # # 3D
                # df3d = df1d.resample('3D', closed='right', label='right').agg(ohlc_dict).dropna(how='any')
                # save_data_m(code, '3d', df3d)
            if not is_run:
                break
        except Exception as e:
            print("外盘期货采集出错", Exception, e)
            # dingMsg.send("remind外盘期货采集出错")
        time.sleep(20)


def save_data_m(code, period, df):
    if not df.empty:
        logging.info("保存 %s %s %s" % (code, period, df.index.values[-1]))
    batch = []
    for idx, row in df.iterrows():
        batch.append(
            UpdateOne(
                {"_id": idx.replace(tzinfo=tz)},
                {
                    "$set": {
                        "open": float(row['开盘价']),
                        "close": float(row['收盘价']),
                        "high": float(row['最高价']),
                        "low": float(row['最低价']),
                        "volume": float(row['成交量']),
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


def signal_hanlder(signalnum, frame):
    logging.info("正在停止程序。")
    global is_run
    is_run = False


def run(**kwargs):
    signal.signal(signal.SIGINT, signal_hanlder)
    thread_list = []
    # thread_list.append(threading.Thread(target=fetch_stocks_mink))
    thread_list.append(threading.Thread(target=fetch_futures_mink))
    for thread in thread_list:
        thread.start()

    while True:
        for thread in thread_list:
            if thread.isAlive():
                break
        else:
            break


if __name__ == '__main__':
    run()
