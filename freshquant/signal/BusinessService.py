# -*- coding: utf-8 -*-

import copy
import json
import re
import string
import time
import traceback
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pydash
import pymongo
import pytz
import QUANTAXIS as QA
import requests
from bson import ObjectId
from bson.codec_options import CodecOptions

from freshquant.basic.singleton_type import SingletonType
from freshquant.config import config
from freshquant.database.cache import in_memory_cache
from freshquant.db import DBfreshquant
from freshquant.instrument.future import query_cn_future_product_table
from freshquant.position.cn_future import queryCnFuturePositionCodes

tz = pytz.timezone('Asia/Shanghai')

# periodList = ['3min', '5min', '15min', '30min', '60min', '4hour', '1day']
periodList = ['1m', '3m', '5m', '15m', '30m', '180m', '1d']
# 主力合约列表
dominantSymbolList = []
# 主力合约详细信息
dominantSymbolInfoList = []
# CL:原油; GC:黄金;SI:白银; CT:棉花;S:大豆;SM：豆粕; BO:豆油;NID:伦镍; ZSD:伦锌;
# 马棕 日胶
global_future_symbol = config['global_future_symbol']
global_stock_symbol = config['global_stock_symbol']
digit_coin_symbol = config['digit_coin_symbol']


class BusinessService(metaclass=SingletonType):
    def __init__(self):
        pass

    # okex数字货币部分涨跌幅
    def getBTCTicker(self):
        okexUrl = "https://www.okex.me/api/swap/v3/instruments/BTC-USDT-SWAP/ticker"
        r = requests.get(okexUrl, timeout=(15, 15))
        ticker = json.loads(r.text)
        # print("BTC实时价格",ticker)
        okexUrl2 = "https://www.okex.me/api/swap/v3/instruments/BTC-USDT-SWAP/candles?granularity=86400"
        r = requests.get(okexUrl2, timeout=(15, 15))
        data_list = json.loads(r.text)
        dayOpenPrice = data_list[0][1]
        change = round(
            (float(ticker['last']) - float(dayOpenPrice)) / float(dayOpenPrice), 4
        )
        changeAndPrice = {'change': change, 'price': ticker['last']}
        return changeAndPrice

    def getStatisticList(self, dateRange):
        statisticList = {}
        split = dateRange.split(",")
        startDate = split[0]
        endDate = split[1]
        print("dateRange", split)
        # test
        # startDate = '2020-03-29'
        # endDate = '2020-03-31'
        end = datetime.strptime(endDate, "%Y-%m-%d")
        end = end.replace(hour=23, minute=59, second=59, microsecond=999, tzinfo=tz)
        start = datetime.strptime(startDate, "%Y-%m-%d")
        start = start.replace(hour=23, minute=59, second=59, microsecond=999, tzinfo=tz)
        data_list = (
            DBfreshquant['future_auto_position']
            .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
            .find(
                {
                    "date_created": {"$gte": start, "$lte": end},
                    "status": {'$ne': 'exception'},
                }
            )
            .sort("_id", pymongo.ASCENDING)
        )
        df = pd.DataFrame(list(data_list))
        # 当持仓表中没有 单子止盈过的的时候 win_end_money字段为空
        if (
            len(df) == 0
            or 'win_end_money' not in df.columns.values
            or 'lose_end_money' not in df.columns.values
        ):
            return {
                'date': [],
                'win_end_list': [],
                'lose_end_list': [],
                'net_profit_list': [],
                'total_margin': [],
                'win_money_list': [],
                'lose_money_list': [],
                'win_symbol_list': [],
                'lose_symbol_list': [],
                'signal_result': [],
                'win_end_count_list': [],
                'lose_end_count_list': [],
                'win_lose_count_rate': [],
                'win_lose_money_rate': [],
                'win_end_holding_day_list': [],
                'lose_end_holding_day_list': [],
            }

        for idx, row in df.iterrows():
            # 根据日期分组
            date_created = df.loc[idx, 'date_created']
            date_created_str = self.formatTime2(date_created)
            df.loc[idx, 'new_date_created'] = date_created_str
            # 根据symbol分组 查询盈利品种排行和亏损品种排行
            symbol = df.loc[idx, 'symbol']
            # RB2010 -> RB
            simple_symbol = symbol.rstrip(string.digits)
            df.loc[idx, 'simple_symbol'] = simple_symbol

        win_end_group_by_date = df['win_end_money'].groupby(df['new_date_created'])
        lose_end_group_by_date = df['lose_end_money'].groupby(df['new_date_created'])
        win_end_group_by_symbol = df['win_end_money'].groupby(df['simple_symbol'])
        lose_end_group_by_symbol = df['lose_end_money'].groupby(df['simple_symbol'])

        per_order_margin_group_by_date = df['per_order_margin'].groupby(
            df['new_date_created']
        )
        per_order_amount_group_by_date = df['amount'].groupby(df['new_date_created'])

        # 查询 动止列表不为空的记录
        win_end_group_by_date_dynamic = (
            df['dynamicPositionList'][(df.status != 'exception')].groupby(
                df['new_date_created']
            )
            if 'dynamicPositionList' in df
            else []
        )
        # 转化为list
        win_end_group_by_date_dynamic_list = list(win_end_group_by_date_dynamic)
        # 按日期记录每天的动止盈利
        dynamic_win_list = []
        for i in range(len(win_end_group_by_date_dynamic_list)):
            dynamic_win_sum = 0
            item = list(win_end_group_by_date_dynamic_list[i][1])
            for j in range(len(item)):
                if isinstance(item[j], list):
                    for k in range(len(item[j])):
                        dynamic_win_sum = dynamic_win_sum + item[j][k]['stop_win_money']
            dynamic_win_list.append(int(dynamic_win_sum))
        print(dynamic_win_list)

        # 总保证金
        total_margin_list = []
        per_order_margin_group_by_date_list = list(per_order_margin_group_by_date)
        per_order_amount_group_by_date_list = list(per_order_amount_group_by_date)
        for i in range(len(per_order_margin_group_by_date_list)):
            item_margin = per_order_margin_group_by_date_list[i][1]
            item_amount = per_order_amount_group_by_date_list[i][1]
            total_margin_sum = item_margin * item_amount
            # print("保证金\n",item_margin,"数量\n" ,item_amount,"总保证金\n",total_margin_sum.sum())
            total_margin_list.append(int(total_margin_sum.sum()))
        print(total_margin_list)

        # print(win_end_group_by_symbol.sum())
        # print(lose_end_group_by_symbol.sum())
        # print(win_end_group_by_date.sum())
        # print(lose_end_group_by_date.sum())
        # 日期列表
        dateList = []
        # 当日盈利累加
        win_end_list = []
        # 每天亏损累加
        lose_end_list = []
        # 净盈亏
        net_profit_list = []

        # 盈利次数 列表
        win_end_count_list = []
        # 亏损次数 列表
        lose_end_count_list = []
        # 胜率 列表
        win_lose_count_rate = []
        # 盈亏比 列表
        win_lose_money_rate = []

        # 盈利单持仓天数
        win_end_holding_day_list = []
        # 亏损单持仓天数
        lose_end_holding_day_list = []

        # 保存日期
        for name, group in win_end_group_by_date:
            dateList.append(name)
        # 保存品种简称
        for i in range(len(win_end_group_by_date.sum())):
            # 止盈的盈利和 动止的盈利 累加

            dynamic_win_money = 0
            if len(dynamic_win_list) > 0:
                dynamic_win_money = dynamic_win_list[i]

            win_end_list.append(int(win_end_group_by_date.sum()[i]) + dynamic_win_money)
            lose_end_list.append(int(lose_end_group_by_date.sum()[i]))
            net_profit_list.append(
                int(win_end_group_by_date.sum()[i])
                + dynamic_win_money
                + int(lose_end_group_by_date.sum()[i])
            )

            win_lose_money_rate.append(
                abs(
                    round(
                        (int(win_end_group_by_date.sum()[i]) + dynamic_win_money)
                        / (int(lose_end_group_by_date.sum()[i])),
                        2,
                    )
                )
                if lose_end_group_by_date.sum()[i] != 0
                else 0
            )

            win_end_count_list.append(int(win_end_group_by_date.count()[i]))
            lose_end_count_list.append(int(lose_end_group_by_date.count()[i]))
            if int(win_end_group_by_date.count()[i]) != 0:
                win_lose_count_rate.append(
                    round(
                        int(win_end_group_by_date.count()[i])
                        / (
                            int(lose_end_group_by_date.count()[i])
                            + int(win_end_group_by_date.count()[i])
                        ),
                        2,
                    )
                )

        sorted_win_money_list = (
            win_end_group_by_symbol.max().sort_values(ascending=False).dropna(axis=0)
        )
        sorted_lose_money_list = (
            lose_end_group_by_symbol.max().sort_values(ascending=True).dropna(axis=0)
        )

        win_symbol_list = list(sorted_win_money_list.index)
        lose_symbol_list = list(sorted_lose_money_list.index)

        for i in range(len(win_symbol_list)):
            item_list = df[
                (df['simple_symbol'] == win_symbol_list[i]) & (df['status'] == 'winEnd')
            ]
            count = 0
            for idx, row in item_list.iterrows():
                # 保存前一个 如果下一个 品种相同 就累加持仓天数
                start_date = row['date_created']
                end_date = row['win_end_time']
                delta_days = abs((end_date - start_date).days)
                if count == 0:
                    win_end_holding_day_list.append(delta_days)
                else:
                    win_end_holding_day_list[i] = (
                        win_end_holding_day_list[i] + delta_days
                    )
                count = count + 1

        for i in range(len(lose_symbol_list)):
            # print(win_symbol_list[i])
            item_list = df[
                (df['simple_symbol'] == lose_symbol_list[i])
                & (df['status'] == 'loseEnd')
            ]
            count = 0
            for idx, row in item_list.iterrows():
                start_date = row['date_created']
                end_date = row['lose_end_time']
                delta_days = abs((end_date - start_date).days)
                if count == 0:
                    lose_end_holding_day_list.append(delta_days)
                else:
                    lose_end_holding_day_list[i] = (
                        lose_end_holding_day_list[i] + delta_days
                    )
                count = count + 1
        print(win_end_holding_day_list, lose_end_holding_day_list)

        # 取整数
        win_money_list = list(sorted_win_money_list.dropna(axis=0))
        lose_money_list = list(sorted_lose_money_list.dropna(axis=0))
        for i in range(len(win_money_list)):
            win_money_list[i] = int(win_money_list[i])
        for i in range(len(lose_money_list)):
            lose_money_list[i] = int(lose_money_list[i])

        # print(win_symbol_list, win_money_list)
        # print(lose_symbol_list, lose_money_list)

        # print(win_symbol_list, win_money_list)
        # print(lose_symbol_list, lose_money_list)

        df_beichi_win = pd.DataFrame(
            list(
                DBfreshquant['future_auto_position']
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
                .find(
                    {
                        "date_created": {"$gte": start, "$lte": end},
                        "status": "winEnd",
                        "signal": "beichi",
                    }
                )
                .sort("_id", pymongo.ASCENDING)
            )
        )

        df_beichi_lose = pd.DataFrame(
            list(
                DBfreshquant['future_auto_position']
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
                .find(
                    {
                        "date_created": {"$gte": start, "$lte": end},
                        "status": "loseEnd",
                        "signal": "beichi",
                    }
                )
                .sort("_id", pymongo.ASCENDING)
            )
        )

        df_break_win = pd.DataFrame(
            list(
                DBfreshquant['future_auto_position']
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
                .find(
                    {
                        "date_created": {"$gte": start, "$lte": end},
                        "status": "winEnd",
                        "signal": "break",
                    }
                )
                .sort("_id", pymongo.ASCENDING)
            )
        )
        df_break_lose = pd.DataFrame(
            list(
                DBfreshquant['future_auto_position']
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
                .find(
                    {
                        "date_created": {"$gte": start, "$lte": end},
                        "status": "loseEnd",
                        "signal": "break",
                    }
                )
                .sort("_id", pymongo.ASCENDING)
            )
        )

        df_huila_win = pd.DataFrame(
            list(
                DBfreshquant['future_auto_position']
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
                .find(
                    {
                        "date_created": {"$gte": start, "$lte": end},
                        "status": "winEnd",
                        "signal": "huila",
                    }
                )
                .sort("_id", pymongo.ASCENDING)
            )
        )
        df_huila_lose = pd.DataFrame(
            list(
                DBfreshquant['future_auto_position']
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
                .find(
                    {
                        "date_created": {"$gte": start, "$lte": end},
                        "status": "loseEnd",
                        "signal": "huila",
                    }
                )
                .sort("_id", pymongo.ASCENDING)
            )
        )

        df_tupo_win = pd.DataFrame(
            list(
                DBfreshquant['future_auto_position']
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
                .find(
                    {
                        "date_created": {"$gte": start, "$lte": end},
                        "status": "winEnd",
                        "signal": "tupo",
                    }
                )
                .sort("_id", pymongo.ASCENDING)
            )
        )
        df_tupo_lose = pd.DataFrame(
            list(
                DBfreshquant['future_auto_position']
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
                .find(
                    {
                        "date_created": {"$gte": start, "$lte": end},
                        "status": "loseEnd",
                        "signal": "tupo",
                    }
                )
                .sort("_id", pymongo.ASCENDING)
            )
        )

        # df_v_reverse_win = pd.DataFrame(list(DBfreshquant['future_auto_position'].with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz)).find({
        #     "date_created": {"$gte": start, "$lte": end}, "status": "winEnd", "signal": "v_reverse"
        # }).sort("_id", pymongo.ASCENDING)))
        # df_v_reverse_lose = pd.DataFrame(list(DBfreshquant['future_auto_position'].with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz)).find({
        #     "date_created": {"$gte": start, "$lte": end}, "status": "loseEnd", "signal": "v_reverse"
        # }).sort("_id", pymongo.ASCENDING)))

        df_five_v_reverse_win = pd.DataFrame(
            list(
                DBfreshquant['future_auto_position']
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
                .find(
                    {
                        "date_created": {"$gte": start, "$lte": end},
                        "status": "winEnd",
                        "signal": "five_v_reverse",
                    }
                )
                .sort("_id", pymongo.ASCENDING)
            )
        )
        df_five_v_reverse_lose = pd.DataFrame(
            list(
                DBfreshquant['future_auto_position']
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
                .find(
                    {
                        "date_created": {"$gte": start, "$lte": end},
                        "status": "loseEnd",
                        "signal": "five_v_reverse",
                    }
                )
                .sort("_id", pymongo.ASCENDING)
            )
        )

        signal_result = {
            "beichi_win_count": len(df_beichi_win),
            "beichi_lose_count": len(df_beichi_lose),
            "beichi_win_money": int(df_beichi_win['win_end_money'].sum())
            if 'win_end_money' in df_beichi_win
            else 0,
            "beichi_lose_money": int(df_beichi_win['lose_end_money'].sum())
            if 'lose_end_money' in df_beichi_win
            else 0,
            #
            "huila_win_count": len(df_huila_win),
            "huila_lose_count": len(df_huila_lose),
            #
            "huila_win_money": int(df_huila_win['win_end_money'].sum()),
            "huila_lose_money": int(df_huila_win['lose_end_money'].sum())
            if 'lose_end_money' in df_huila_win
            else 0,
            "break_win_count": len(df_break_win),
            "break_lose_count": len(df_break_lose),
            "break_win_money": int(df_break_win['win_end_money'].sum())
            if 'win_end_money' in df_break_win
            else 0,
            "break_lose_money": int(df_break_win['lose_end_money'].sum())
            if 'lose_end_money' in df_break_win
            else 0,
            "tupo_win_count": len(df_tupo_win),
            "tupo_lose_count": len(df_tupo_lose),
            "tupo_win_money": int(df_tupo_win['win_end_money'].sum())
            if 'win_end_money' in df_tupo_win
            else 0,
            "tupo_lose_money": int(df_tupo_win['lose_end_money'].sum())
            if 'lose_end_money' in df_tupo_win
            else 0,
            # "v_reverse_win_count": len(df_v_reverse_win),
            # "v_reverse_lose_count": len(df_v_reverse_lose),
            "five_v_reverse_win_count": len(df_five_v_reverse_win),
            "five_v_reverse_lose_count": len(df_five_v_reverse_lose),
            "five_v_reverse_win_money": int(
                df_five_v_reverse_win['win_end_money'].sum()
            )
            if 'win_end_money' in df_five_v_reverse_win
            else 0,
            "five_v_reverse_lose_money": int(
                df_five_v_reverse_win['lose_end_money'].sum()
            )
            if 'lose_end_money' in df_five_v_reverse_win
            else 0,
            "beichi_win_lose_count_rate": round(
                len(df_beichi_win) / (len(df_beichi_lose) + len(df_beichi_win)), 2
            )
            if len(df_beichi_lose) != 0
            else 1,
            "beichi_win_lose_money_rate": abs(
                round(
                    df_beichi_win['win_end_money'].sum()
                    / df_beichi_lose['lose_end_money'].sum(),
                    2,
                )
            )
            if 'lose_end_money' in df_beichi_lose
            and df_beichi_lose['lose_end_money'].sum() != 0
            else 1,
            "huila_win_lose_count_rate": round(
                len(df_huila_win) / (len(df_huila_lose) + len(df_huila_win)), 2
            )
            if len(df_huila_lose) != 0
            else 1,
            "huila_win_lose_money_rate": abs(
                round(
                    df_huila_win['win_end_money'].sum()
                    / df_huila_lose['lose_end_money'].sum(),
                    2,
                )
            )
            if df_huila_lose['lose_end_money'].sum() != 0
            else 1,
            "break_win_lose_count_rate": round(
                len(df_break_win) / (len(df_break_lose) + len(df_break_win)), 2
            )
            if len(df_break_lose) != 0
            else 1,
            "break_win_lose_money_rate": abs(
                round(
                    df_break_win['win_end_money'].sum()
                    / df_break_lose['lose_end_money'].sum(),
                    2,
                )
            )
            if ('lose_end_money' in df_break_lose)
            and df_break_lose['lose_end_money'].sum() != 0
            else 1,
            "tupo_win_lose_count_rate": round(
                len(df_tupo_win) / (len(df_tupo_lose) + len(df_tupo_win)), 2
            )
            if len(df_tupo_lose) != 0
            else 1,
            "tupo_win_lose_money_rate": abs(
                round(
                    df_tupo_win['win_end_money'].sum()
                    / df_tupo_lose['lose_end_money'].sum(),
                    2,
                )
            )
            if 'win_end_money' in df_tupo_win
            and 'lose_end_money' in df_tupo_lose
            and df_tupo_lose['lose_end_money'].sum() != 0
            else 1,
            # "v_reverse_win_lose_count_rate": round(len(df_v_reverse_win) / len(df_v_reverse_lose),2) if len(df_v_reverse_lose) != 0 else 1,
            # "v_reverse_win_lose_money_rate": round(df_v_reverse_win['win_end_money'].sum() / df_v_reverse_lose['lose_end_money'].sum(), 2) if df_v_reverse_lose['lose_end_money'].sum() != 0 else 1,
            #
            "five_v_reverse_win_lose_count_rate": round(
                len(df_five_v_reverse_win)
                / (len(df_five_v_reverse_lose) + len(df_five_v_reverse_win)),
                2,
            )
            if len(df_five_v_reverse_lose) != 0
            else 1,
            "five_v_reverse_win_lose_money_rate": abs(
                round(
                    df_five_v_reverse_win['win_end_money'].sum()
                    / df_five_v_reverse_lose['lose_end_money'].sum(),
                    2,
                )
            )
            if 'lose_end_money' in df_five_v_reverse_lose
            and 'win_end_money' in df_five_v_reverse_win
            and df_five_v_reverse_lose['lose_end_money'].sum() != 0
            else 1,
        }
        # print(signal_result)
        statisticList = {
            'date': dateList,
            'win_end_list': win_end_list,
            'lose_end_list': lose_end_list,
            'net_profit_list': net_profit_list,
            'total_margin': total_margin_list,
            'win_money_list': win_money_list,
            'lose_money_list': lose_money_list,
            'win_symbol_list': win_symbol_list,
            'lose_symbol_list': lose_symbol_list,
            'signal_result': signal_result,
            'win_end_count_list': win_end_count_list,
            'lose_end_count_list': lose_end_count_list,
            'win_lose_count_rate': win_lose_count_rate,
            'win_lose_money_rate': win_lose_money_rate,
            'win_end_holding_day_list': win_end_holding_day_list,
            'lose_end_holding_day_list': lose_end_holding_day_list,
        }
        return statisticList

    def getGlobalFutureChangeList(self):
        global_future_symbol = config['global_future_symbol']
        # global_stock_symbol = config['global_stock_symbol']
        combinSymbol = copy.deepcopy(global_future_symbol)
        # combinSymbol.extend(global_stock_symbol)
        changeList = {}
        for i in range(len(combinSymbol)):
            item = combinSymbol[i]
            # 查日线开盘价
            code = "%s_%s" % (item, '1d')
            data_list = list(
                DBfreshquant[code]
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
                .find()
                .sort("_id", pymongo.DESCENDING)
            )
            if len(data_list) == 0:
                continue
            dayOpenPrice = data_list[0]['open']
            code = "%s_%s" % (item, '5m')

            # 差5分钟收盘价
            data_list = list(
                DBfreshquant[code]
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
                .find()
                .sort("_id", pymongo.DESCENDING)
            )
            if len(data_list) == 0:
                continue
            minClosePrice = data_list[0]['open']

            change = round((minClosePrice - dayOpenPrice) / dayOpenPrice, 4)
            changeItem = {'change': change, 'price': minClosePrice}
            # print(item, '-> ', dayOpenPrice, ' -> ', minClosePrice)
            changeList[item] = changeItem
        return changeList

    def initDoinantSynmbol(self):
        try:
            symbolList = config['symbolList']
            # 主力合约详细信息
            # print("当前主力合约列表:", dominantSymbolList)
            # print("当前主力合约详细信息:", dominantSymbolInfoList)
        except Exception as e:
            print("Error Occurred: {0}".format(traceback.format_exc()))

    def getDoinantSynmbol(self):
        conbinSymbolInfo = copy.deepcopy(dominantSymbolInfoList)
        #  把外盘 数字货币加进去
        conbinSymbolInfo.extend(config['global_future_symbol_info'])
        conbinSymbolInfo.extend(config['digit_coin_symbol_info'])
        return conbinSymbolInfo

    @in_memory_cache.memoize(expiration=864000)
    def get_dominant_symbol_list(self):
        mainContracts = list(DBfreshquant["tdx_ex_main_contracts"].find({}))
        codes = queryCnFuturePositionCodes()
        mainContracts = pydash.uniq_by(
            [{"code": code} for code in codes] + mainContracts, "code"
        )
        productTable: pd.DataFrame = query_cn_future_product_table()
        result = []
        for i in range(len(mainContracts)):
            mainContract = mainContracts[i]
            code = mainContract["code"]
            # 提取code开头的字母
            code = re.sub(r"\d", "", code)
            product = productTable[productTable["tdx_product_code"] == code]
            if product is None:
                continue
            margin_rate = 0.1
            # 判断是否有margin_rate列
            if "margin_rate" in product.columns:
                margin_rate = product["margin_rate"].values[0]
            contract_multiplier = 10
            # 判断是否有contract_multiplier列
            if "contract_multiplier" in product.columns:
                contract_multiplier = product["contract_multiplier"].values[0]
            result.append(
                {
                    "name": product["name"].values[0],
                    "product_code": product["tdx_product_code"].values[0],
                    "order_book_code": mainContract["code"],
                    "order_book_id": mainContract["code"],
                    "margin_rate": margin_rate,
                    "contract_multiplier": contract_multiplier,
                }
            )
        return result

    def getFutureSignalList(self):
        symbolList = copy.deepcopy(dominantSymbolList)
        #  把外盘加进去
        # symbolList.extend(global_future_symbol)
        # symbolList.extend(global_stock_symbol)
        # symbolList.extend(digit_coin_symbol)
        symbolListMap = {}
        for i in range(len(symbolList)):
            symbol = symbolList[i]
            symbolListMap[symbol] = {}
            for j in range(len(periodList)):
                period = periodList[j]
                symbolListMap[symbol][period] = {}
                symbolListMap[symbol][period]["direction"] = ""
                symbolListMap[symbol][period]["signal"] = ""

        future_signal_list = (
            DBfreshquant['future_signal'].find().sort("fire_time", pymongo.ASCENDING)
        )
        for signalItem in future_signal_list:
            # print("信号item:", signalItem)
            # utc 转本地时间
            date_created = signalItem['date_created'] + timedelta(hours=8)
            date_created_str = date_created.strftime("%m-%d %H:%M")
            fire_time = signalItem['fire_time'] + timedelta(hours=8)
            fire_time_str = fire_time.strftime("%m-%d %H:%M")
            # str(round(signalItem['price'], 2))
            if 'level_direction' in signalItem:
                level_direction = signalItem['level_direction']
            else:
                level_direction = ""
            # msg = "%s %s %s %s %s" % (level_direction, str(signalItem['signal']), str(signalItem['direction']), fire_time_str,
            #                           str(signalItem.get('tag', '')))
            msg = "%s %s" % (str(signalItem['signal']), str(signalItem['direction']))
            if signalItem['symbol'] in symbolListMap:
                if signalItem['period'] == '60m':
                    continue
                symbolListMap[signalItem['symbol']][signalItem['period']][
                    "direction"
                ] = level_direction
                symbolListMap[signalItem['symbol']][signalItem['period']][
                    "signal"
                ] = msg
        # print("期货信号列表", symbolListMap)
        return symbolListMap

    # 获取涨跌幅数据
    def getChangeList(self):
        return None

    def calc_ma(self, close_list, day):
        ma = QA.MA(pd.Series(close_list), day)
        result = np.nan_to_num(ma).round(decimals=2)
        return result

    # 获取内盘 20日 均线
    def get_day_ma_list(self):
        return None

    # 获取外盘20日均线
    def get_global_day_ma_list(self):
        global_future_symbol = config['global_future_symbol']
        combinSymbol = copy.deepcopy(global_future_symbol)
        aboveList = {}
        for i in range(len(combinSymbol)):
            item = combinSymbol[i]
            # 查日线开盘价
            code = "%s_%s" % (item, '1d')
            data_list = list(
                DBfreshquant[code]
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
                .find()
                .limit(31)
                .sort("_id", pymongo.DESCENDING)
            )
            if len(data_list) == 0:
                continue
            data_list.reverse()
            day_close_price_list = list(pd.DataFrame(data_list)['close'])
            day_ma_20 = self.calc_ma(day_close_price_list, 20)
            code = "%s_%s" % (item, '1m')

            # 查1分钟收盘价
            data_list = list(
                DBfreshquant[code]
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=tz))
                .find()
                .sort("_id", pymongo.DESCENDING)
            )
            if len(data_list) == 0:
                continue
            min_close_price = list(pd.DataFrame(data_list)['close'])[0]
            # todo  这里用 True 和 False  无法序列化
            above_item = {'above_ma_20': 1 if min_close_price >= day_ma_20[-1] else -1}
            # print(item, '-> ', above_item)
            aboveList[item] = above_item
        return aboveList

    def getLevelDirectionList(self):
        symbolList = copy.deepcopy(dominantSymbolList)
        #  把外盘加进去
        symbolList.extend(global_future_symbol)
        # symbolList.extend(global_stock_symbol)
        symbolList.extend(digit_coin_symbol)
        symbolListMap = {}
        for i in range(len(symbolList)):
            symbol = symbolList[i]
            symbolListMap[symbol] = {}
            for j in range(len(periodList)):
                period = periodList[j]
                symbolListMap[symbol][period] = ""
        future_direction_list = DBfreshquant['future_direction'].find()
        for directionItem in future_direction_list:
            # utc 转本地时间
            # date_created = directionItem['date_created'] + timedelta(hours=8)
            # date_created_str = date_created.strftime("%m-%d %H:%M")
            if directionItem['symbol'] in symbolListMap:
                symbolListMap[directionItem['symbol']][
                    directionItem['period']
                ] = directionItem['direction']
        # print("级别多空列表", symbolListMap)
        return symbolListMap

    # --------------------期货部份----------------------------------------------
    # 为了兼容老合约 保证金率不再从主力合约中取了， 直接拿配置信息
    def getFutureConfig(self):
        return config['futureConfig']

    def getPosition(self, symbol, period, status, direction):
        if period == 'all':
            query = {'symbol': symbol, 'status': status, 'direction': direction}
        else:
            query = {
                'symbol': symbol,
                'period': period,
                'status': status,
                'direction': direction,
            }
        # 当多空双开锁仓的时候，获取最新持仓的那个
        result = (
            DBfreshquant["future_auto_position"]
            .find(query)
            .sort("fire_time", pymongo.ASCENDING)
        )
        if result.count() > 0:
            for x in result:
                x['_id'] = str(x['_id'])
                x['fire_time'] = self.formatTime(x['fire_time'])
                x['date_created'] = self.formatTime(x['date_created'])
                if 'last_update_time' in x and x['last_update_time'] != '':
                    x['last_update_time'] = self.formatTime(x['last_update_time'])
                else:
                    x['last_update_time'] = ''
                if 'win_end_time' in x and x['win_end_time'] != '':
                    x['win_end_time'] = self.formatTime(x['win_end_time'])
                else:
                    x['win_end_time'] = ''
                if 'lose_end_time' in x and x['lose_end_time'] != '':
                    x['lose_end_time'] = self.formatTime(x['lose_end_time'])
                else:
                    x['lose_end_time'] = ''

                if 'dynamicPositionList' in x:
                    for y in x['dynamicPositionList']:
                        y['date_created'] = self.formatTime(y['date_created'])

            return x
        else:
            return -1

    def formatTime(self, localTime):
        localTimeStamp = time.localtime(
            int(time.mktime(localTime.timetuple()) + 8 * 3600)
        )
        localTimeStampStr = time.strftime("%Y-%m-%d %H:%M:%S", localTimeStamp)
        return localTimeStampStr

    def formatTime2(self, localTime):
        date_created_stamp = int(time.mktime(localTime.timetuple()))
        timeArray = time.localtime(date_created_stamp)
        return time.strftime("%Y-%m-%d", timeArray)

    # 持仓列表改成自动录入
    def getPositionList(self, status, page, size, endDate):
        end = datetime.strptime(endDate, "%Y-%m-%d")
        end = end.replace(hour=23, minute=59, second=59, microsecond=999, tzinfo=tz)
        start_date = end + timedelta(-1)
        positionList = []
        collection = DBfreshquant["future_auto_position"]
        # 查询总记录数
        if status == 'all':
            query_filter = {'date_created': {"$gte": start_date, "$lte": end}}
            total = collection.count_documents(query_filter)
            result = (
                collection.find(query_filter)
                .skip((page - 1) * size)
                .limit(size)
                .sort("fire_time", pymongo.DESCENDING)
            )
        # 有的单子需要长线拿住，因此持仓单不限制时间
        elif status == 'holding':
            query_filter = {'status': status}
            total = collection.count_documents(query_filter)
            result = (
                collection.find(query_filter)
                .skip((page - 1) * size)
                .limit(size)
                .sort("fire_time", pymongo.DESCENDING)
            )
        else:
            query_filter = {
                'status': status,
                'date_created': {"$gte": start_date, "$lte": end},
            }
            total = collection.count_documents(query_filter)
            result = (
                collection.find(query_filter)
                .skip((page - 1) * size)
                .limit(size)
                .sort("fire_time", pymongo.DESCENDING)
            )
        for x in result:
            x['_id'] = str(x['_id'])
            if 'fire_time' in x and x['fire_time'] != '':
                x['fire_time'] = self.formatTime(x['fire_time'])
            else:
                x['fire_time'] = ''

            if 'date_created' in x and x['date_created'] != '':
                x['date_created'] = self.formatTime(x['date_created'])
            else:
                x['date_created'] = ''

            if 'last_update_time' in x and x['last_update_time'] != '':
                x['last_update_time'] = self.formatTime(x['last_update_time'])
            else:
                x['last_update_time'] = ''
            if 'lose_end_time' in x and x['lose_end_time'] != '':
                x['lose_end_time'] = self.formatTime(x['lose_end_time'])
            else:
                x['lose_end_time'] = ''
            if 'win_end_time' in x and x['win_end_time'] != '':
                x['win_end_time'] = self.formatTime(x['win_end_time'])
            else:
                x['win_end_time'] = ''
            # 兼容老数据
            if 'total_margin' not in x or x['total_margin'] != '':
                if 'per_order_margin' in x and x['per_order_margin'] != '':
                    x['total_margin'] = round(x['per_order_margin'] * x['amount'], 2)

            if 'dynamicPositionList' in x:
                for y in x['dynamicPositionList']:
                    y['date_created'] = self.formatTime(y['date_created'])

            # 占用保证金
            positionList.append(x)
        positionListResult = {'records': positionList, 'total': total}
        return positionListResult

    def createPosition(self, position):
        result = DBfreshquant['position_record'].insert_one(
            {
                'enterTime': position['enterTime'],
                'symbol': position['symbol'],
                'period': position['period'],
                'signal': position['signal'],
                'status': position['status'],
                'direction': position['direction'],
                'price': position['price'],
                'amount': position['amount'],
                'stopLosePrice': position['stopLosePrice'],
                'margin_rate': position['margin_rate'],
                # 'nestLevel': position['nestLevel'],
                'enterReason': position['enterReason'],
                'holdReason': position['holdReason'],
                # 'importance': position['importance'],
                'dynamicPositionList': position['dynamicPositionList'],
            }
        )
        return result.inserted_id

    def updatePosition(self, position):
        DBfreshquant['position_record'].update_one(
            {'_id': ObjectId(position['_id'])},
            {
                "$set": {
                    'enterTime': position['enterTime'],
                    'symbol': position['symbol'],
                    'period': position['period'],
                    'signal': position['signal'],
                    'status': position['status'],
                    'direction': position['direction'],
                    'price': position['price'],
                    'amount': position['amount'],
                    'stopLosePrice': position['stopLosePrice'],
                    'margin_rate': position['margin_rate'],
                    # 'nestLevel': position['nestLevel'],
                    'enterReason': position['enterReason'],
                    'holdReason': position['holdReason'],
                    # 'importance': position['importance'],
                    'dynamicPositionList': position['dynamicPositionList'],
                }
            },
        )

    # close_price 最新收盘价 手动进行止盈止损操作
    '''
     status :
      holding 持仓
      loseEnd 止损
      winEnd  止盈
      exception 异常
    '''

    def updatePositionStatus(self, id, status, close_price):
        date_created = datetime.utcnow()
        item = DBfreshquant['future_auto_position'].find_one({'_id': ObjectId(id)})
        if item['symbol'] == 'BTC':
            marginLevel = 1 / (item['margin_rate'])
        else:
            print(item['symbol'], item)
            marginLevel = 1 / (item['margin_rate'] + config['margin_rate_company'])
        if status == 'winEnd':
            winEndPercent = round(
                ((float(close_price) - item['price']) / item['price']) * marginLevel, 2
            )
            # 止盈已实现盈亏
            win_end_money = round(
                item['per_order_margin'] * item['amount'] * winEndPercent, 2
            )
            # 止盈比率
            win_end_rate = round(winEndPercent, 2)
            DBfreshquant['future_auto_position'].update_one(
                {'_id': ObjectId(id)},
                {
                    "$set": {
                        'status': status,
                        'win_end_price': float(close_price),
                        'win_end_money': abs(win_end_money),
                        'win_end_rate': abs(win_end_rate),
                        'win_end_time': date_created,
                    }
                },
            )
        elif status == 'loseEnd':
            loseEndPercent = round(
                ((float(close_price) - item['price']) / item['price']) * marginLevel, 2
            )
            # 止损已实现盈亏
            lose_end_money = round(
                item['per_order_margin'] * item['amount'] * loseEndPercent, 2
            )
            lose_end_rate = round(loseEndPercent, 2)
            DBfreshquant['future_auto_position'].update_one(
                {'_id': ObjectId(id)},
                {
                    "$set": {
                        'status': status,
                        'lose_end_price': float(close_price),
                        'lose_end_money': -abs(lose_end_money),
                        'lose_end_rate': -abs(lose_end_rate),
                        'lose_end_time': date_created,
                    }
                },
            )
        else:
            DBfreshquant['future_auto_position'].update_one(
                {'_id': ObjectId(id)},
                {
                    "$set": {
                        'status': status,
                    }
                },
            )

    # 创建预判信息
    def createFuturePrejudgeList(self, endDate, prejudgeList):
        result = DBfreshquant['prejudge_record'].insert_one(
            {'endDate': endDate, 'prejudgeList': prejudgeList}
        )
        return result.inserted_id

    # 获取预判信息
    def getFuturePrejudgeList(self, endDate):
        result = DBfreshquant['prejudge_record'].find_one({'endDate': endDate})
        if result:
            result['_id'] = str(result['_id'])
            return result
        return -1

    #  更新预判信息
    def updateFuturePrejudgeList(self, id, prejudgeList):
        # print("更新预判参数", id, prejudgeList)
        DBfreshquant['prejudge_record'].update_one(
            {'_id': ObjectId(id)}, {"$set": {'prejudgeList': prejudgeList}}
        )

    # --------------------股票部份----------------------------------------------

    def getStockPositionList(self, status, page, size):
        positionList = []
        collection = DBfreshquant["stock_position_record"]
        # 查询总记录数
        if status == 'all':
            result = (
                collection.find()
                .skip((page - 1) * size)
                .limit(size)
                .sort("enterTime", pymongo.DESCENDING)
            )
            total = result.count()
        else:
            result = (
                collection.find({'status': status})
                .skip((page - 1) * size)
                .limit(size)
                .sort("enterTime", pymongo.DESCENDING)
            )
            total = result.count()
        for x in result:
            x['_id'] = str(x['_id'])
            positionList.append(x)
        positionListResult = {'records': positionList, 'total': total}
        return positionListResult

    def getStockPosition(self, symbol, period, status):
        if period == 'all':
            query = {'symbol': symbol, 'status': status}
        else:
            query = {'symbol': symbol, 'period': period, 'status': status}
        result = DBfreshquant["stock_position_record"].find(query)
        if result.count() > 0:
            for x in result:
                x['_id'] = str(x['_id'])
            return x
        else:
            return -1

    # 新增股票持仓
    def createStockPosition(self, position):
        result = DBfreshquant['stock_position_record'].insert_one(
            {
                'enterTime': position['enterTime'],
                'symbol': position['symbol'],
                'period': position['period'],
                'signal': position['signal'],
                'status': position['status'],
                'direction': position['direction'],
                'positionPercent': position['positionPercent'],
                'price': position['price'],
                'amount': position['amount'],
                'stopLosePrice': position['stopLosePrice'],
                # 'nestLevel': position['nestLevel'],
                'enterReason': position['enterReason'],
                'holdReason': position['holdReason'],
                # 'importance': position['importance'],
                'dynamicPositionList': position['dynamicPositionList'],
            }
        )
        return result.inserted_id

    def updateStockPosition(self, position):
        print("传给后端的positionPercent", position['positionPercent'])
        DBfreshquant['stock_position_record'].update_one(
            {'_id': ObjectId(position['_id'])},
            {
                "$set": {
                    'enterTime': position['enterTime'],
                    'symbol': position['symbol'],
                    'period': position['period'],
                    'signal': position['signal'],
                    'status': position['status'],
                    'direction': position['direction'],
                    'positionPercent': position['positionPercent'],
                    'price': position['price'],
                    'amount': position['amount'],
                    'stopLosePrice': position['stopLosePrice'],
                    # 'nestLevel': position['nestLevel'],
                    'enterReason': position['enterReason'],
                    'holdReason': position['holdReason'],
                    # 'importance': position['importance'],
                    'dynamicPositionList': position['dynamicPositionList'],
                }
            },
        )

    def updateStockPositionStatus(self, id, status):
        DBfreshquant['stock_position_record'].update_one(
            {'_id': ObjectId(id)},
            {
                "$set": {
                    'status': status,
                }
            },
        )
