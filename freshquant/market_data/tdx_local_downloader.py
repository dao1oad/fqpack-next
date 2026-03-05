# -*- coding: utf-8 -*-

import logging
import os
import re
import traceback
from datetime import datetime, time, timedelta

import pandas as pd
import pytz
from pymongo import UpdateOne
from pytdx.reader import TdxDailyBarReader, TdxLCMinBarReader

from freshquant.db import DBfreshquant

tz = pytz.timezone('Asia/Shanghai')


def run(**kwargs):
    TDX_HOME = os.environ.get("TDX_HOME")
    if TDX_HOME is None:
        logging.error("没有指定通达信安装目录环境遍历（TDX_HOME）")
        return

    days = kwargs.get("days", 3)

    codes = []
    for subdir in ["sh", "sz"]:
        path = os.path.join(TDX_HOME, "vipdoc\\%s\\minline" % subdir)
        files = os.listdir(path)
        for filename in files:
            code = None
            if subdir == "sh":
                match = re.match("(sh)(\\d{6})", filename, re.I)
                if match is not None:
                    code = match.group()
                    code_head = code[2:4]
                    if code_head not in [
                        "60",
                        "68",
                        "50",
                        "51",
                        "01",
                        "10",
                        "11",
                        "12",
                        "13",
                        "14",
                        "20",
                    ]:
                        continue
            elif subdir == "sz":
                match = re.match("(sz)(\\d{6})", filename, re.I)
                if match is not None:
                    code = match.group()
                    code_head2 = code[2:4]
                    code_head4 = code[2:5]
                    if code_head2 not in [
                        "00",
                        "30",
                        "15",
                        "16",
                        "10",
                        "11",
                        "12",
                        "13",
                        "14",
                    ]:
                        continue
                    if code_head4 in ['1318']:
                        continue
            filepath = os.path.join(path, filename)
            if code is not None:
                codes.append({"code": code, "filepath": filepath, "days": days})
    for idx in range(len(codes)):
        info = codes[idx]
        logging.info(
            "%s/%s code=%s filepath=%s",
            idx + 1,
            len(codes),
            info["code"],
            info["filepath"],
        )
        parse_and_save_1m(info)

    codes = []
    for subdir in ["sh", "sz"]:
        path = os.path.join(TDX_HOME, "vipdoc\\%s\\fzline" % subdir)
        files = os.listdir(path)
        for filename in files:
            code = None
            if subdir == "sh":
                match = re.match("(sh)(\\d{6})", filename, re.I)
                if match is not None:
                    code = match.group()
                    code_head = code[2:4]
                    if code_head not in [
                        "60",
                        "68",
                        "50",
                        "51",
                        "01",
                        "10",
                        "11",
                        "12",
                        "13",
                        "14",
                        "20",
                    ]:
                        continue
            elif subdir == "sz":
                match = re.match("(sz)(\\d{6})", filename, re.I)
                if match is not None:
                    code = match.group()
                    code_head2 = code[2:4]
                    code_head4 = code[2:4]
                    if code_head2 not in [
                        "00",
                        "30",
                        "15",
                        "16",
                        "10",
                        "11",
                        "12",
                        "13",
                        "14",
                    ]:
                        continue
                    if code_head4 in ['1318']:
                        continue
            filepath = os.path.join(path, filename)
            if code is not None:
                codes.append({"code": code, "filepath": filepath, "days": days})
    for idx in range(len(codes)):
        info = codes[idx]
        logging.info(
            "%s/%s code=%s filepath=%s",
            idx + 1,
            len(codes),
            info["code"],
            info["filepath"],
        )
        parse_and_save_5m(info)

    codes = []
    for subdir in ["sh", "sz"]:
        path = os.path.join(TDX_HOME, "vipdoc\\%s\\lday" % subdir)
        files = os.listdir(path)
        for filename in files:
            code = None
            if subdir == "sh":
                match = re.match("(sh)(\\d{6})", filename, re.I)
                if match is not None:
                    code = match.group()
                    code_head = code[2:4]
                    if code_head not in [
                        "60",
                        "68",
                        "50",
                        "51",
                        "01",
                        "10",
                        "11",
                        "12",
                        "13",
                        "14",
                        "20",
                    ]:
                        continue
            elif subdir == "sz":
                match = re.match("(sz)(\\d{6})", filename, re.I)
                if match is not None:
                    code = match.group()
                    code_head2 = code[2:4]
                    code_head4 = code[2:5]
                    if code_head2 not in [
                        "00",
                        "30",
                        "15",
                        "16",
                        "10",
                        "11",
                        "12",
                        "13",
                        "14",
                    ]:
                        continue
                    if code_head4 in ['1318']:
                        continue
            filepath = os.path.join(path, filename)
            if code is not None:
                codes.append({"code": code, "filepath": filepath, "days": days})
    for idx in range(len(codes)):
        info = codes[idx]
        logging.info(
            "%s/%s code=%s filepath=%s",
            idx + 1,
            len(codes),
            info["code"],
            info["filepath"],
        )
        parse_and_save_day(info)


def calc_60m(df):
    bars = []
    rows = []
    for index, row in df.iterrows():
        rows.append(row)
        if index.time() == time(hour=10, minute=30, second=0, microsecond=0):
            g = pd.DataFrame(rows)
            bar = {
                "date": index,
                "open": rows[0]["open"],
                "close": rows[-1]["close"],
                "high": g.high.max(),
                "low": g.low.min(),
                "volume": g.volume.sum(),
                "amount": g.amount.sum(),
            }
            bars.append(bar)
            rows = []
        elif index.time() == time(hour=11, minute=30, second=0, microsecond=0):
            g = pd.DataFrame(rows)
            bar = {
                "date": index,
                "open": rows[0]["open"],
                "close": rows[-1]["close"],
                "high": g.high.max(),
                "low": g.low.min(),
                "volume": g.volume.sum(),
                "amount": g.amount.sum(),
            }
            bars.append(bar)
            rows = []
        elif index.time() == time(hour=14, minute=0, second=0, microsecond=0):
            g = pd.DataFrame(rows)
            bar = {
                "date": index,
                "open": rows[0]["open"],
                "close": rows[-1]["close"],
                "high": g.high.max(),
                "low": g.low.min(),
                "volume": g.volume.sum(),
                "amount": g.amount.sum(),
            }
            bars.append(bar)
            rows = []
        elif index.time() == time(hour=15, minute=0, second=0, microsecond=0):
            g = pd.DataFrame(rows)
            bar = {
                "date": index,
                "open": rows[0]["open"],
                "close": rows[-1]["close"],
                "high": g.high.max(),
                "low": g.low.min(),
                "volume": g.volume.sum(),
                "amount": g.amount.sum(),
            }
            bars.append(bar)
            rows = []
    if len(bars) > 0:
        df60m = pd.DataFrame(bars)
        df60m.set_index("date", inplace=True)
        return df60m
    else:
        return None


def parse_and_save_1m(info):
    start_time = datetime.now() - timedelta(days=info["days"])
    reader = TdxLCMinBarReader()
    df = reader.get_df(info["filepath"])
    df = df[df.index >= start_time]

    ohlc = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'amount': 'sum',
    }
    # 合成3分钟数据
    df3m = df.resample('3T', closed='right', label='right').agg(ohlc).dropna(how='any')
    save_data(info["code"], "3m", df3m)
    return True


def parse_and_save_5m(info):
    start_time = datetime.now() - timedelta(days=info["days"])
    reader = TdxLCMinBarReader()
    df = reader.get_df(info["filepath"])
    df = df[df.index >= start_time]
    save_data(info["code"], "5m", df)

    ohlc = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'amount': 'sum',
    }
    # 合成15分钟数据
    df15m = (
        df.resample('15T', closed='right', label='right').agg(ohlc).dropna(how='any')
    )
    save_data(info["code"], "15m", df15m)
    df30m = (
        df.resample('30T', closed='right', label='right').agg(ohlc).dropna(how='any')
    )
    save_data(info["code"], "30m", df30m)
    df60m = calc_60m(df30m)
    if df60m is not None:
        save_data(info["code"], "60m", df60m)
    return True


def parse_and_save_day(info):
    # noinspection PyBroadException
    try:
        start_time = datetime.now() - timedelta(days=info["days"])
        reader = TdxDailyBarReader()
        df = reader.get_df(info["filepath"])
        df = df[df.index >= start_time]
        save_data(info["code"], "1d", df)
        # 把日线数据当成180m和240m数据个存一份
        save_data(info["code"], "180m", df)
        save_data(info["code"], "240m", df)
    except Exception as e:
        logging.info("Error Occurred: {0}".format(traceback.format_exc()))
    return True


def save_data(code, period, df):
    batch = []
    for t, row in df.iterrows():
        batch.append(
            UpdateOne(
                {"_id": t.replace(tzinfo=tz)},
                {
                    "$set": {
                        "open": round(row["open"], 2),
                        "close": round(row["close"], 2),
                        "high": round(row["high"], 2),
                        "low": round(row["low"], 2),
                        "volume": round(row["volume"], 2),
                        "amount": round(row["amount"], 2),
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
