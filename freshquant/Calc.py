# -*- coding: utf-8 -*-

import re
import time

import numpy as np
import pandas as pd
import talib as ta

from freshquant import Duan, KlineDataTool
from freshquant.basic.bi import CalcBi, FindLastFractalRegion
from freshquant.basic.duan import CalcDuan, calc_duan_exp
from freshquant.basic.pattern import DualEntangleForBuyLong, DualEntangleForSellShort
from freshquant.config import config
from freshquant.pattern import pattern_chanlun

# 币安的数据结构
# [
#     [
#         1499040000000,      # Open time
#         "0.01634790",       # Open
#         "0.80000000",       # High
#         "0.01575800",       # Low
#         "0.01577100",       # Close
#         "148976.11427815",  # Volume
#         1499644799999,      # Close time
#         "2434.19055334",    # Quote asset volume
#         308,                # Number of trades
#         "1756.87402397",    # Taker buy base asset volume
#         "28.46694368",      # Taker buy quote asset volume
#         "17928899.62484339" # Ignore.
#     ]
# ]
'''
火币数据结构
{
    amount: 133.9523230990729,
    close: 8858.25,
    count: 168,
    high: 8860.01,
    id: 1560609600,
    low: 8842.35,
    open: 8859.96,
    vol: 11862
}
'''


class Calc:
    def __init__(self):
        # 火币dm接口参数 本级别和大级别映射
        # 火币深度不够,无法容纳大资金
        self.levelMap = {
            '1m': '5m',
            '3m': '15m',
            '15m': '60m',
            '60m': '1d',
            '1d': '1w',
            '5m': '30m',
            '30m': '180m',
            '180m': '1w',
            '1w': '1w',
        }

        self.huobiPeriodMap = {
            '1m': '1min',
            # 火币没有提供3min的数据 需要合成
            '3m': '3m',
            '5m': '5min',
            '15m': '15min',
            '60m': '60min',
            '30m': '30min',
            '180m': '4hour',
            '1d': '1day',
            '1w': '1week',
        }
        self.okexPeriodMap = {
            '1m': '60',
            '3m': '180',
            '5m': '300',
            '15m': '900',
            '60m': '3600',
            '30m': '1800',
            '180m': '10800',
            '1d': '86400',
            '1w': '604800',
        }

        # bitmex 小级别大级别映射
        # self.levelMap = {
        #     '1min': '5min',
        #     '3min': '15min',
        #     '15min': '60min',
        #     '60min': '1day',
        #     '1day': '1week',
        #     '5min': '30min',
        #     '30min': '4hour',
        #     '4hour': '1week',
        #     '1week': '1week'
        # }
        #  bitmex 参数转换
        # self.bitmexPeriodMap = {
        #     '1min': '1m',
        #     '3min': '3m',
        #     '15min': '15m',
        #     '60min': '60m',
        #     '1day': '1d',
        #     '5min': '5m',
        #     '30min': '30m',
        #     '4hour': '180m',
        #     '1week': '7d'
        # }

        # 聚宽期货接口参数 本级别和大级别映射
        self.futureLevelMap = {
            '1m': '5m',
            '3m': '15m',
            '15m': '60m',
            '60m': '1d',
            '1d': '3d',
            '5m': '30m',
            '30m': '180m',
            '180m': '3d',
            '3d': '3d',  # 周线数量只有33根画不出macd 只好取3d了
        }
        #     period参数转换
        self.periodMap = {
            '1m': '1m',
            '3m': '3m',
            '15m': '15m',
            '60m': '60m',
            '1d': '1d',
            '5m': '5m',
            '30m': '30m',
            '180m': '180m',
            '3d': '3d',
            '1w': '1w',
        }

    def calcData(self, period, symbol, save=False, endDate=None):

        x_data = pd.DataFrame()
        xx_data = pd.DataFrame()

        cat = None
        bigLevelPeriod = None

        klineDataTool = KlineDataTool()
        match_stock = re.match("(sh|sz)(\\d{6})", symbol, re.I)
        if match_stock is not None:
            cat = "STOCK"
            klineData = klineDataTool.get_stock_data(symbol, period, endDate)
            bigLevelPeriod = self.futureLevelMap[period]
            klineDataBigLevel = klineDataTool.get_stock_data(
                symbol, bigLevelPeriod, endDate
            )
            klineDataBigLevel2 = []
        #    外盘期货和股票
        elif (
            symbol in config['global_future_symbol']
            or symbol in config['global_stock_symbol']
        ):
            cat = "GLOBAL_FUTURE"
            klineData = klineDataTool.getGlobalFutureData(symbol, period, endDate)
            bigLevelPeriod = self.futureLevelMap[period]
            klineDataBigLevel = klineDataTool.getGlobalFutureData(
                symbol, bigLevelPeriod, endDate
            )
            bigLevelPeriod2 = self.futureLevelMap[bigLevelPeriod]
            klineDataBigLevel2 = klineDataTool.getGlobalFutureData(
                symbol, bigLevelPeriod2, endDate
            )
        else:
            if 'BTC' in symbol:
                cat = "DIGIT_COIN"
                # 转换后的本级别
                currentPeriod = self.okexPeriodMap[period]

                klineData = klineDataTool.getDigitCoinData(
                    symbol, currentPeriod, endDate
                )
                # 转换后的高级别
                bigLevelPeriod = self.okexPeriodMap[self.levelMap[period]]
                klineDataBigLevel = klineDataTool.getDigitCoinData(
                    symbol, bigLevelPeriod, endDate
                )
                # 转换后的高高级别
                bigLevelPeriod2 = self.okexPeriodMap[
                    self.levelMap[self.levelMap[period]]
                ]
                klineDataBigLevel2 = klineDataTool.getDigitCoinData(
                    symbol, bigLevelPeriod2, endDate
                )
            else:
                # 期货
                cat = "FUTURE"
                currentPeriod = self.periodMap[period]
                klineData = klineDataTool.getFutureData(symbol, currentPeriod, endDate)
                bigLevelPeriod = self.futureLevelMap[currentPeriod]
                klineDataBigLevel = klineDataTool.getFutureData(
                    symbol, bigLevelPeriod, endDate
                )
                bigLevelPeriod2 = self.futureLevelMap[bigLevelPeriod]
                klineDataBigLevel2 = klineDataTool.getFutureData(
                    symbol, bigLevelPeriod2, endDate
                )

        jsonObj = klineData  # 本级别的K线数据
        jsonObjBigLevel = klineDataBigLevel  # 高级别的K线数据
        jsonObjBigLevel2 = klineDataBigLevel2  # 高高级别的K线数据

        # 本级别数据
        openPriceList = []
        highList = []
        lowList = []
        closePriceList = []
        timeList = []
        timeIndexList = []
        volumeList = []

        for i in range(len(jsonObj)):
            item = jsonObj[i]
            localTime = time.localtime(item['time'])
            strTime = time.strftime("%Y-%m-%d %H:%M", localTime)
            highList.append(round(float(item['high']), 2))
            lowList.append(round(float(item['low']), 2))

            openPriceList.append(round(float(item['open']), 2))
            closePriceList.append(round(float(item['close']), 2))
            timeList.append(strTime)
            volumeList.append(round(float(item['volume']), 2))
            timeIndexList.append(time.mktime(localTime))
        x_data['timestamp'] = timeIndexList
        x_data['open'] = openPriceList
        x_data['close'] = closePriceList
        x_data['high'] = highList
        x_data['low'] = lowList

        # 高级别数据
        openPriceListBigLevel = []
        highListBigLevel = []
        lowListBigLevel = []
        closePriceListBigLevel = []
        timeListBigLevel = []
        timeIndexListBigLevel = []
        if cat == "FUTURE" or cat == "DIGIT_COIN" or cat == "GLOBAL_FUTURE":
            for i in range(len(jsonObjBigLevel)):
                item = jsonObjBigLevel[i]
                localTime = time.localtime(item['time'])
                strTime = time.strftime("%Y-%m-%d %H:%M", localTime)
                timeListBigLevel.append(strTime)
                highListBigLevel.append(round(float(item['high']), 2))
                lowListBigLevel.append(round(float(item['low']), 2))
                openPriceListBigLevel.append(round(float(item['open']), 2))
                closePriceListBigLevel.append(round(float(item['close']), 2))
                timeIndexListBigLevel.append(time.mktime(localTime))
        xx_data['timestamp'] = timeIndexListBigLevel
        xx_data['open'] = openPriceListBigLevel
        xx_data['close'] = closePriceListBigLevel
        xx_data['high'] = highListBigLevel
        xx_data['low'] = lowListBigLevel

        # 高高级别数据
        openPriceListBigLevel2 = []
        highListBigLevel2 = []
        lowListBigLevel2 = []
        closePriceListBigLevel2 = []
        timeListBigLevel2 = []
        timeIndexListBigLevel2 = []
        if cat == "FUTURE" or cat == "DIGIT_COIN" or cat == "GLOBAL_FUTURE":
            for i in range(len(jsonObjBigLevel2)):
                item = jsonObjBigLevel2[i]
                localTime = time.localtime(item['time'])
                strTime = time.strftime("%Y-%m-%d %H:%M", localTime)
                timeListBigLevel2.append(strTime)
                highListBigLevel2.append(round(float(item['high']), 2))
                lowListBigLevel2.append(round(float(item['low']), 2))
                openPriceListBigLevel2.append(round(float(item['open']), 2))
                closePriceListBigLevel2.append(round(float(item['close']), 2))
                timeIndexListBigLevel2.append(time.mktime(localTime))

        count = len(timeList)
        # 本级别笔
        small_period_list = ['1m', '3m', '5m', '15m', '30m', '60m']
        biList = [0 for i in range(count)]
        CalcBi(
            count,
            biList,
            highList,
            lowList,
            openPriceList,
            closePriceList,
            True if period in small_period_list else False,
        )
        x_data['bi'] = biList

        # 高级别笔
        biListBigLevel = [0 for i in range(len(timeListBigLevel))]
        if cat == "FUTURE" or cat == "DIGIT_COIN" or cat == "GLOBAL_FUTURE":
            CalcBi(
                len(timeListBigLevel),
                biListBigLevel,
                highListBigLevel,
                lowListBigLevel,
                openPriceListBigLevel,
                closePriceListBigLevel,
                True if bigLevelPeriod in small_period_list else False,
            )
            fractialRegion = FindLastFractalRegion(
                len(timeListBigLevel),
                biListBigLevel,
                timeListBigLevel,
                highListBigLevel,
                lowListBigLevel,
                openPriceListBigLevel,
                closePriceListBigLevel,
            )
            if fractialRegion is not None:
                fractialRegion["period"] = bigLevelPeriod
            xx_data['bi'] = biListBigLevel

        # 高高级别笔
        biListBigLevel2 = [0 for i in range(len(timeListBigLevel2))]
        if cat == "FUTURE" or cat == "DIGIT_COIN" or cat == "GLOBAL_FUTURE":
            CalcBi(
                len(timeListBigLevel2),
                biListBigLevel2,
                highListBigLevel2,
                lowListBigLevel2,
                openPriceListBigLevel2,
                closePriceListBigLevel2,
                True if bigLevelPeriod2 in small_period_list else False,
            )
            fractialRegion2 = FindLastFractalRegion(
                len(timeListBigLevel2),
                biListBigLevel2,
                timeListBigLevel2,
                highListBigLevel2,
                lowListBigLevel2,
                openPriceListBigLevel2,
                closePriceListBigLevel2,
            )
            if fractialRegion2 is not None:
                fractialRegion2["period"] = bigLevelPeriod2

        # 高一级别段处理
        higherDuanList = [0 for i in range(count)]
        if cat == "FUTURE" or cat == "DIGIT_COIN" or cat == "GLOBAL_FUTURE":
            higherDuanList = calc_duan_exp(
                biListBigLevel,
                timeIndexListBigLevel,
                biListBigLevel2,
                timeIndexListBigLevel2,
                highListBigLevel,
                lowListBigLevel,
            )
            higherDuanList = calc_duan_exp(
                biList,
                timeIndexList,
                higherDuanList,
                timeIndexListBigLevel2,
                highList,
                lowList,
            )

        # 本级别段处理
        duanList = [0 for i in range(count)]
        if cat == "FUTURE" or cat == "DIGIT_COIN" or cat == "GLOBAL_FUTURE":
            duanList = calc_duan_exp(
                biList,
                timeIndexList,
                biListBigLevel,
                timeIndexListBigLevel,
                highList,
                lowList,
            )
        else:
            CalcDuan(count, duanList, biList, highList, lowList)
        x_data['duan'] = duanList

        if cat == "FUTURE" or cat == "DIGIT_COIN" or cat == "GLOBAL_FUTURE":
            pass
        else:
            CalcDuan(count, higherDuanList, duanList, highList, lowList)

        # 高高一级别段处理
        higherHigherDuanList = [0 for i in range(count)]
        CalcDuan(count, higherHigherDuanList, higherDuanList, highList, lowList)

        entanglementList = pattern.CalcEntanglements(
            timeList, duanList, biList, highList, lowList
        )
        huila = pattern.la_hui(
            entanglementList,
            timeList,
            highList,
            lowList,
            biList,
            duanList,
            higherDuanList,
        )
        tupo = pattern.tu_po(
            entanglementList,
            timeList,
            highList,
            lowList,
            openPriceList,
            closePriceList,
            biList,
            duanList,
            higherDuanList,
        )
        v_reverse = pattern.v_reverse(
            entanglementList,
            timeList,
            highList,
            lowList,
            openPriceList,
            closePriceList,
            biList,
            duanList,
            higherDuanList,
        )
        five_v_fan = pattern.five_v_fan(
            timeList, duanList, biList, highList, lowList, higherDuanList
        )
        duan_pohuai = pattern.po_huai(
            timeList,
            highList,
            lowList,
            openPriceList,
            closePriceList,
            biList,
            duanList,
            higherDuanList,
        )
        # 段中枢
        entanglementHigherList = pattern.CalcEntanglements(
            timeList, higherDuanList, duanList, highList, lowList
        )
        # huila_higher = entanglement.la_hui(entanglementHigherList, timeList, highList, lowList, openPriceList, closePriceList, duanList, higherDuanList)
        # tupo_higher = entanglement.tu_po(entanglementHigherList, timeList, highList, lowList, openPriceList, closePriceList, duanList, higherDuanList)
        # v_reverse_higher = entanglement.v_reverse(entanglementHigherList, timeList, highList, lowList, openPriceList, closePriceList, duanList, higherDuanList)

        # 计算是不是双盘结构
        for idx in range(len(huila["sell_zs_huila"]["date"])):
            fire_time = huila["sell_zs_huila"]["date"][idx]
            fire_price = huila["sell_zs_huila"]["data"][idx]
            if DualEntangleForSellShort(
                duanList,
                entanglementList,
                entanglementHigherList,
                fire_time,
                fire_price,
            ):
                huila["sell_zs_huila"]["tag"][idx] = "双盘"
        for idx in range(len(huila["buy_zs_huila"]["date"])):
            fire_time = huila["buy_zs_huila"]["date"][idx]
            fire_price = huila["buy_zs_huila"]["data"][idx]
            if DualEntangleForBuyLong(
                duanList,
                entanglementList,
                entanglementHigherList,
                fire_time,
                fire_price,
            ):
                huila["buy_zs_huila"]["tag"][idx] = "双盘"
        for idx in range(len(tupo["sell_zs_tupo"]["date"])):
            fire_time = tupo["sell_zs_tupo"]["date"][idx]
            fire_price = tupo["sell_zs_tupo"]["data"][idx]
            if DualEntangleForSellShort(
                duanList,
                entanglementList,
                entanglementHigherList,
                fire_time,
                fire_price,
            ):
                tupo["sell_zs_tupo"]["tag"][idx] = "双盘"
        for idx in range(len(tupo["buy_zs_tupo"]["date"])):
            fire_time = tupo["buy_zs_tupo"]["date"][idx]
            fire_price = tupo["buy_zs_tupo"]["data"][idx]
            if DualEntangleForBuyLong(
                duanList,
                entanglementList,
                entanglementHigherList,
                fire_time,
                fire_price,
            ):
                tupo["buy_zs_tupo"]["tag"][idx] = "双盘"
        for idx in range(len(v_reverse["sell_v_reverse"]["date"])):
            fire_time = v_reverse["sell_v_reverse"]["date"][idx]
            fire_price = v_reverse["sell_v_reverse"]["data"][idx]
            if DualEntangleForSellShort(
                duanList,
                entanglementList,
                entanglementHigherList,
                fire_time,
                fire_price,
            ):
                v_reverse["sell_v_reverse"]["tag"][idx] = "双盘"
        for idx in range(len(v_reverse["buy_v_reverse"]["date"])):
            fire_time = v_reverse["buy_v_reverse"]["date"][idx]
            fire_price = v_reverse["buy_v_reverse"]["data"][idx]
            if DualEntangleForBuyLong(
                duanList,
                entanglementList,
                entanglementHigherList,
                fire_time,
                fire_price,
            ):
                v_reverse["buy_v_reverse"]["tag"][idx] = "双盘"
        for idx in range(len(duan_pohuai["sell_duan_break"]["date"])):
            fire_time = duan_pohuai["sell_duan_break"]["date"][idx]
            fire_price = duan_pohuai["sell_duan_break"]["data"][idx]
            if DualEntangleForSellShort(
                duanList,
                entanglementList,
                entanglementHigherList,
                fire_time,
                fire_price,
            ):
                duan_pohuai["sell_duan_break"]["tag"][idx] = "双盘"
        for idx in range(len(duan_pohuai["buy_duan_break"]["date"])):
            fire_time = duan_pohuai["buy_duan_break"]["date"][idx]
            fire_price = duan_pohuai["buy_duan_break"]["data"][idx]
            if DualEntangleForBuyLong(
                duanList,
                entanglementList,
                entanglementHigherList,
                fire_time,
                fire_price,
            ):
                duan_pohuai["buy_duan_break"]["tag"][idx] = "双盘"

        # 高级别段中枢
        entanglementHigherHigherList = pattern_chanlun.CalcEntanglements(
            timeList, higherHigherDuanList, higherDuanList, highList, lowList
        )

        zsdata, zsflag = getZhongShuData(entanglementList)
        duan_zsdata, duan_zsflag = getZhongShuData(entanglementHigherList)
        higher_duan_zsdata, higher_duan_zsflag = getZhongShuData(
            entanglementHigherHigherList
        )

        # 拼接json数据
        resJson = {}
        # 时间
        resJson['date'] = timeList
        resJson['open'] = openPriceList
        resJson['high'] = highList
        resJson['low'] = lowList
        resJson['close'] = closePriceList

        resJson['bidata'] = getLineData(timeList, biList, highList, lowList)
        resJson['duandata'] = getLineData(timeList, duanList, highList, lowList)

        resJson['higherDuanData'] = getLineData(
            timeList, higherDuanList, highList, lowList
        )
        resJson['higherHigherDuanData'] = getLineData(
            timeList, higherHigherDuanList, highList, lowList
        )

        # 当前级别MACD
        # diff_array, dea_array, macd_array = calc_macd(closePriceList)
        # x_data['diff'] = diff_array
        # x_data['dea'] = dea_array
        # x_data['macd'] = macd_array
        # resJson['diff'] = diff_array.tolist()
        # resJson['dea'] = dea_array.tolist()
        # resJson['macd'] = macd_array.tolist()
        # resJson['macdAreaData'] = calcArea(resJson['diff'], resJson['macd'], timeList)
        # resJson['boll_up'] = getBoll(closePriceList)[0].tolist()
        # resJson['boll_middle'] = getBoll(closePriceList)[1].tolist()
        # resJson['boll_bottom'] = getBoll(closePriceList)[2].tolist()
        # resJson['ama'] = getAma(closePriceList).tolist()
        # 外盘 180m 成交量合成  有 Infinity的值，导致JSON解析异常，这里注释掉
        # resJson['volume'] = volumeList
        resJson['zsdata'] = zsdata
        resJson['zsflag'] = zsflag
        resJson['duan_zsdata'] = duan_zsdata
        resJson['duan_zsflag'] = duan_zsflag
        resJson['higher_duan_zsdata'] = higher_duan_zsdata
        resJson['higher_duan_zsflag'] = higher_duan_zsflag

        # 大级别MACD
        # big_diff_array, big_dea_array, big_macd_array = calc_macd(closePriceListBigLevel)
        # xx_data['diff'] = big_diff_array
        # xx_data['dea'] = big_dea_array
        # xx_data['macd'] = big_macd_array
        # resJson['diffBigLevel'] = big_diff_array.tolist()
        # resJson['deaBigLevel'] = big_dea_array.tolist()
        # resJson['macdBigLevel'] = big_macd_array.tolist()

        # 背驰计算
        time_array = np.array(timeList)
        high_array = np.array(highList)
        low_array = np.array(lowList)
        open_array = np.array(openPriceList)
        close_array = np.array(closePriceList)

        buyMACDBCData = {}
        buyMACDBCData['date'] = []
        buyMACDBCData['data'] = []
        buyMACDBCData['value'] = []
        sellMACDBCData = {}
        sellMACDBCData['date'] = []
        sellMACDBCData['data'] = []
        sellMACDBCData['value'] = []

        # beichiData = divergence.calc_beichi_data(x_data, xx_data)
        # buyMACDBCData = beichiData['buyMACDBCData']
        # sellMACDBCData = beichiData['sellMACDBCData']

        # beichiData2 = divergence.calcAndNote(
        #         time_array, high_array, low_array, open_array, close_array, macd_array, diff_array, dea_array,
        #         biList, higherDuanList, True)

        # buyMACDBCData2 = beichiData2['buyMACDBCData']
        # sellMACDBCData2 = beichiData2['sellMACDBCData']

        buyHigherMACDBCData = {}
        buyHigherMACDBCData['date'] = []
        buyHigherMACDBCData['data'] = []
        buyHigherMACDBCData['value'] = []
        #
        sellHigherMACDBCData = {}
        sellHigherMACDBCData['date'] = []
        sellHigherMACDBCData['data'] = []
        sellHigherMACDBCData['value'] = []

        # strategy3计算
        resJson['notLower'] = calcNotLower(duanList, lowList)
        resJson['notHigher'] = calcNotHigher(duanList, highList)
        # for x in range(len(buyMACDBCData2['date'])):
        #     if pydash.find_index(buyMACDBCData['date'], lambda t: t == buyMACDBCData2['date'][x]) == -1:
        #         buyHigherMACDBCData['date'].append(buyMACDBCData2['date'][x])
        #         buyHigherMACDBCData['data'].append(buyMACDBCData2['data'][x])
        #         buyHigherMACDBCData['value'].append(buyMACDBCData2['value'][x])
        # for x in range(len(sellMACDBCData2['date'])):
        #     if pydash.find_index(sellMACDBCData['date'], lambda t: t == sellMACDBCData2['date'][x]) == -1:
        #         sellHigherMACDBCData['date'].append(sellMACDBCData2['date'][x])
        #         sellHigherMACDBCData['data'].append(sellMACDBCData2['data'][x])
        #         sellHigherMACDBCData['value'].append(sellMACDBCData2['value'][x])
        resJson['buyMACDBCData'] = buyMACDBCData
        resJson['sellMACDBCData'] = sellMACDBCData

        # resJson['buyHigherMACDBCData'] = buyMACDBCData2
        # resJson['sellHigherMACDBCData'] = sellMACDBCData2

        resJson['buy_zs_huila'] = huila['buy_zs_huila']
        resJson['sell_zs_huila'] = huila['sell_zs_huila']
        # resJson['buy_zs_huila_higher'] = huila_higher['buy_zs_huila']
        # resJson['sell_zs_huila_higher'] =huila_higher['sell_zs_huila']

        resJson['buy_zs_tupo'] = tupo['buy_zs_tupo']
        resJson['sell_zs_tupo'] = tupo['sell_zs_tupo']
        # resJson['buy_zs_tupo_higher'] = tupo_higher['buy_zs_tupo']
        # resJson['sell_zs_tupo_higher'] = tupo_higher['sell_zs_tupo']

        resJson['buy_v_reverse'] = v_reverse['buy_v_reverse']
        resJson['sell_v_reverse'] = v_reverse['sell_v_reverse']
        # resJson['buy_v_reverse_higher'] = v_reverse_higher['buy_v_reverse']
        # resJson['sell_v_reverse_higher'] = v_reverse_higher['sell_v_reverse']

        resJson['buy_five_v_reverse'] = five_v_fan['buy_five_v_reverse']
        resJson['sell_five_v_reverse'] = five_v_fan['sell_five_v_reverse']

        resJson['buy_duan_break'] = duan_pohuai['buy_duan_break']
        resJson['sell_duan_break'] = duan_pohuai['sell_duan_break']
        # resJson['buy_duan_break_higher'] = duan_pohuai_higher['buy_duan_break']
        # resJson['sell_duan_break_higher'] = duan_pohuai_higher['sell_duan_break']
        resJson['symbol'] = symbol
        resJson['period'] = period
        resJson['endDate'] = endDate

        if cat == "FUTURE" or cat == "DIGIT_COIN" or cat == "GLOBAL_FUTURE":
            fractialRegion = {} if fractialRegion is None else fractialRegion
            fractialRegion2 = {} if fractialRegion2 is None else fractialRegion2
            resJson['fractal'] = [fractialRegion, fractialRegion2]

        return resJson


def getLineData(timeList, signalList, highList, lowList):
    res = {'data': [], 'date': []}
    for i in range(0, len(timeList), 1):
        if signalList[i] == 1:
            res['data'].append(highList[i])
            res['date'].append(timeList[i])
        elif signalList[i] == -1:
            res['data'].append(lowList[i])
            res['date'].append(timeList[i])
    return res


def getZhongShuData(entanglementList):
    zsdata = []
    zsflag = []
    for i in range(len(entanglementList)):
        e = entanglementList[i]
        if e.direction == -1:
            zsflag.append(-1)
            zsdata.append([[e.startTime, e.top], [e.endTime, e.bottom]])
        else:
            zsflag.append(1)
            zsdata.append([[e.startTime, e.bottom], [e.endTime, e.top]])
    return zsdata, zsflag


# def getZhongShuData(zhongShuHigh, zhongShuLow, zhongShuStartEnd, timeList):
#     zsdata = []
#     zsStart = []
#     zsEnd = []
#     zsflag = []
#     for i in range(len(zhongShuStartEnd)):
#         item = zhongShuStartEnd[i]
#         if item == 0:
#             continue
#         if item == 1:
#             # print("中枢起点:", i, zhongShuHigh[i], zhongShuLow[i], zhongShuStartEnd[i])
#             zsStart = [timeList[i], zhongShuLow[i]]
#         elif item == 2:
#             # print("中枢终点:", i, zhongShuHigh[i], zhongShuLow[i], zhongShuStartEnd[i])
#             zsEnd = [timeList[i], zhongShuHigh[i]]
#         if len(zsStart) and len(zsEnd):
#             zsItem = [copy.copy(zsStart), copy.copy(zsEnd)]
#             # print("中枢拼接:", zsItem)
#             zsdata.append(copy.copy(zsItem))
#             if zsStart[1] > zsEnd[1]:
#                 zsflag.append(-1)
#             else:
#                 zsflag.append(1)
#             zsStart.clear()
#             zsEnd.clear()
#             zsItem.clear()

#     return zsdata, zsflag


def calc_macd(close_list):
    macd = ta.MACD(np.array(close_list), fastperiod=12, slowperiod=26, signalperiod=9)
    result = np.nan_to_num(macd).round(decimals=2)
    return result


def getBoll(closePriceList):
    close = array(closePriceList)
    boll = ta.BBANDS(close, 20, 2)
    result = np.nan_to_num(boll)
    return result


def getAma(closePriceList):
    close = array(closePriceList)
    ama = ta.KAMA(close)
    result = np.nan_to_num(ama)
    return result


def calcNotLower(duanList, lowList):
    if Duan.notLower(duanList, lowList):
        macdPos = ""
        # if macd15m[-1] >= 0:
        #     macdPos = "大级别MACD零轴上"
        # else:
        #     macdPos = "大级别MACD零轴下"
        # msg = 'XB-3', symbol, period
        return True
    else:
        return False


def calcNotHigher(duanList, highList):
    if Duan.notHigher(duanList, highList):
        macdPos = ""
        # if macd15m[-1] >= 0:
        #     macdPos = "大级别MACD零轴上"
        # else:
        #     macdPos = "大级别MACD零轴下"
        # msg = 'XB-3', symbol, period
        return True
    else:
        return False


#     计算macd面积
def calcArea(diff, macd, timeList):
    # 1 : 0轴上方 -1 零轴下方
    currentFlag = 1
    upSum = 0
    downSum = 0

    macdAreaList = {
        # 保存面积的值
        'date': [],
        # 保存dif
        'data': [],
        # 保存时间
        'value': [],
    }

    for i in range(len(macd)):
        # 如果少于33根 的值
        if i < 33:
            continue
        # 0轴上方
        if macd[i] > 0:
            if currentFlag == -1:
                macdAreaList['value'].append(downSum)
                macdAreaList['data'].append(round(diff[i], 2))
                macdAreaList['date'].append(timeList[i])
                downSum = 0
                currentFlag = 1
            upSum = round(upSum + macd[i] * 100)
        else:
            if currentFlag == 1:
                macdAreaList['value'].append(upSum)
                macdAreaList['data'].append(round(diff[i], 2))
                macdAreaList['date'].append(timeList[i])
                upSum = 0
                currentFlag = -1
            downSum = round(downSum + macd[i] * 100)
    return macdAreaList
