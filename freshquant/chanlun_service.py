# -*- coding: utf-8 -*-

import datetime
import re

import numpy as np
import pandas as pd
import pydash
import QUANTAXIS as QA

import freshquant.placeholder as placeholder
from freshquant import Duan
from freshquant.analysis.chanlun_analysis import Chanlun, calculate_trading_signals
from freshquant.basic.util import str_from_timestamp
from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.config import cfg, config
from freshquant.data.astock.holding import get_stock_fills
from freshquant.data.future.basic import fq_fetch_future_basic
from freshquant.instrument.etf import query_etf_map
from freshquant.instrument.general import query_instrument_type
from freshquant.instrument.stock import query_stock_map
from freshquant.KlineDataTool import (
    get_future_data_v2,
    get_stock_data,
    getFutureData,
    getGlobalFutureData,
)
from freshquant.pattern.chanlun.macd_divergence import locate_macd_divergence
from freshquant.position.cn_future import queryArrangedCnFutureFillList
from freshquant.quote.etf import queryEtfCandleSticks
from freshquant.signal.bei_chi import huang_bai_xian_di_bei_chi, mian_ji_di_bei_chi
from freshquant.signal.break_pivot import (
    rise_break_pivot_gg,
    rise_break_pivot_zd,
    rise_break_pivot_zg,
    rise_break_pivot_zm,
)
from freshquant.util.code import infer_cn_security_prefixed_code

ETF_CODE_PREFIXES = ("15", "16", "18", "50", "51", "56", "58")


def _resolve_security_symbol_and_type(symbol):
    normalized_symbol = infer_cn_security_prefixed_code(symbol)
    if not normalized_symbol:
        return symbol, None

    instrument_type = query_instrument_type(normalized_symbol.lower())
    if instrument_type is None:
        base_code = normalized_symbol[2:]
        if base_code.startswith(ETF_CODE_PREFIXES):
            instrument_type = InstrumentType.ETF_CN
        else:
            instrument_type = InstrumentType.STOCK_CN

    return normalized_symbol, instrument_type


def get_data_v2(symbol, period, end_date=None, bar_count=0):
    stock_fills = None
    future_fills = None
    digitalcoin_fills = None
    name = None
    query_symbol, instrumentType = _resolve_security_symbol_and_type(symbol)
    if instrumentType is None:
        instrumentType = query_instrument_type((symbol or "").lower())
        query_symbol = symbol
    if instrumentType == InstrumentType.STOCK_CN:
        name = pydash.get(query_stock_map(), f"{query_symbol.lower()}.name")
        get_instrument_data = (
            lambda code, current_period, current_end_date: get_stock_data(
                code,
                current_period,
                current_end_date,
                bar_count=bar_count,
            )
        )
        stock_fills = get_stock_fills(query_symbol[2:])
        if stock_fills is not None and len(stock_fills) > 0:
            desired_columns = [
                "date",
                "time",
                "quantity",
                "price",
                "amount",
                "amount_adjust",
            ]
            existing_columns = [
                col for col in desired_columns if col in stock_fills.columns
            ]
            stock_fills = stock_fills[existing_columns].to_dict(orient="records")
        else:
            stock_fills = None
    elif instrumentType == InstrumentType.ETF_CN:
        name = pydash.get(query_etf_map(), f"{query_symbol.lower()}.name")
        get_instrument_data = (
            lambda code, current_period, current_end_date: queryEtfCandleSticks(
                code,
                current_period,
                current_end_date,
                bar_count=bar_count,
            )
        )
        stock_fills = get_stock_fills(query_symbol[2:])
        if stock_fills is not None and len(stock_fills) > 0:
            desired_columns = [
                "date",
                "time",
                "quantity",
                "price",
                "amount",
                "amount_adjust",
            ]
            existing_columns = [
                col for col in desired_columns if col in stock_fills.columns
            ]
            stock_fills = stock_fills[existing_columns].to_dict(orient="records")
        else:
            stock_fills = None
    else:
        future_obj = fq_fetch_future_basic(symbol)
        if future_obj is not None:
            name = future_obj["name"]
        get_instrument_data = get_future_data_v2
        future_fills = queryArrangedCnFutureFillList(symbol)

    kline_data = get_instrument_data(query_symbol, period, end_date)
    kline_data["time_str"] = kline_data["datetime"].apply(
        lambda dt: dt.strftime("%Y-%m-%d %H:%M")
    )

    # 计算买卖点信号
    trading_signals = calculate_trading_signals(kline_data)

    # daily_data = get_instrument_data(symbol, "1d", end_date)

    # ma5 = None
    # ma34 = None
    # if daily_data is not None and len(daily_data) > 0:
    #     daily_data = pd.DataFrame(daily_data)
    #     daily_data["time_str"] = daily_data["time_stamp"].apply(
    #         lambda value: datetime.datetime.fromtimestamp(value, tz=cfg.TZ).strftime(
    #             "%Y-%m-%d %H:%M"
    #         )
    #     )
    #     daily_data = daily_data.set_index("time_stamp")
    #     ma5 = np.round(pd.Series.rolling(daily_data["close"], window=5).mean(), 2)
    #     ma34 = np.round(pd.Series.rolling(daily_data["close"], window=34).mean(), 2)

    resp = {
        "symbol": symbol,
        "name": name,
        "instrumentType": instrumentType,
        "period": period,
        "endDate": end_date,
        "dateBigLevel": [],
        "date": kline_data.time_str.to_list(),
        "open": trading_signals["open"],
        "high": trading_signals["high"],
        "low": trading_signals["low"],
        "close": trading_signals["close"],
        "bidata": trading_signals["bi_data"],
        "duandata": trading_signals["duan_data"],
        "higherDuanData": trading_signals["higher_duan_data"],
        "higherHigherDuanData": trading_signals["higher_higher_duan_data"],
        "zsdata": trading_signals["zd_data"],
        "zsflag": trading_signals["zs_flag"],
        "duan_zsdata": trading_signals["duan_zs_data"],
        "duan_zsflag": trading_signals["duan_zs_flag"],
        "higher_duan_zsdata": trading_signals["high_duan_zs_data"],
        "higher_duan_zsflag": trading_signals["high_duan_zs_flag"],
        "buy_zs_huila": trading_signals["buy_zs_huila"],
        "sell_zs_huila": trading_signals["sell_zs_huila"],
        "buy_v_reverse": trading_signals["buy_v_reverse"],
        "sell_v_reverse": trading_signals["sell_v_reverse"],
        "macd_bullish_divergence": trading_signals["macd_bullish_divergence"],
        "macd_bearish_divergence": trading_signals["macd_bearish_divergence"],
        "fractal": placeholder.fractal,
        "entry_ledger": stock_fills,
        "stock_fills": stock_fills,
        "future_fills": future_fills,
        "digitalcoin_fills": digitalcoin_fills,
    }

    resp["notLower"] = calcNotLower(
        trading_signals["duan_signal_list"], kline_data.low.to_list()
    )
    resp["notHigher"] = calcNotHigher(
        trading_signals["duan_signal_list"], kline_data.high.to_list()
    )

    return resp


def get_data_v3(symbol, period, end_date=None):
    match_stock = re.match("(sh|sz)(\\d{6})", symbol, re.I)
    if match_stock is not None:
        get_instrument_data = get_stock_data
    elif (
        symbol in config["global_future_symbol"]
        or symbol in config["global_stock_symbol"]
    ):
        get_instrument_data = getGlobalFutureData
    elif "USDT" in symbol:
        get_instrument_data = None
    else:
        get_instrument_data = getFutureData

    kline_data = get_instrument_data(
        symbol,
        period,
        end_date,
    )
    kline_data["time_str"] = kline_data["time_stamp"].apply(
        lambda value: datetime.datetime.fromtimestamp(value, tz=cfg.TZ).strftime(
            "%Y-%m-%d %H:%M"
        )
    )

    MACD = QA.MACD(kline_data["close"], 12, 26, 9)
    kline_data["diff"] = MACD["DIFF"].fillna(0)
    kline_data["dea"] = MACD["DEA"].fillna(0)
    kline_data["macd"] = MACD["MACD"].fillna(0)
    kline_data["jc"] = QA.CROSS(MACD["DIFF"], MACD["DEA"]).fillna(0)
    kline_data["sc"] = QA.CROSS(MACD["DEA"], MACD["DIFF"]).fillna(0)

    chanlun = Chanlun().analysis(
        kline_data.time_stamp.to_list(),
        kline_data.open.to_list(),
        kline_data.close.to_list(),
        kline_data.low.to_list(),
        kline_data.high.to_list(),
    )
    kline_data["bi"] = chanlun.bi_signal_list
    kline_data["duan"] = chanlun.duan_signal_list
    kline_data["duan2"] = chanlun.higher_duan_signal_list

    data = {
        "symbol": symbol,
        "period": period,
        "kline_data": kline_data,
        "chanlun_data": chanlun,
    }
    kline_data = data["kline_data"]

    bi_data = {
        "date": list(map(str_from_timestamp, chanlun.bi_data["dt"])),
        "data": chanlun.bi_data["data"],
    }
    duan_data = {
        "date": list(map(str_from_timestamp, chanlun.duan_data["dt"])),
        "data": chanlun.duan_data["data"],
    }
    higher_chanlun_data = {
        "date": list(map(str_from_timestamp, chanlun.higher_duan_data["dt"])),
        "data": chanlun.higher_duan_data["data"],
    }

    # 计算笔中枢
    entanglement_list = chanlun.entanglement_list

    daily_data = None
    entanglement_list_1d = None
    mian_ji_di_bei_chi_sg = None
    huang_bai_xian_di_bei_chi_sg = None
    if period != "1d":
        daily_data = get_instrument_data(symbol, "1d", end_date)

    if daily_data is not None and len(daily_data) > 0:
        daily_data = pd.DataFrame(daily_data)
        daily_data["time_str"] = daily_data["time_stamp"].apply(
            lambda value: datetime.datetime.fromtimestamp(value, tz=cfg.TZ).strftime(
                "%Y-%m-%d %H:%M"
            )
        )
        daily_data = daily_data.set_index("time_stamp", drop=False)
        chanlunData_1d = Chanlun().analysis(
            daily_data["time_stamp"].to_list(),
            daily_data["open"].to_list(),
            daily_data["close"].to_list(),
            daily_data["low"].to_list(),
            daily_data["high"].to_list(),
        )
        daily_data["bi"] = chanlunData_1d.bi_signal_list
        daily_data["duan"] = chanlunData_1d.duan_signal_list
        daily_data["duan2"] = chanlunData_1d.higher_duan_signal_list
        entanglement_list_1d = chanlunData_1d.pivot_list

    rise_break_pivot_gg_sg = rise_break_pivot_gg(
        kline_data["datetime"].to_list(),
        kline_data.time_str.to_list(),
        kline_data.high.to_list(),
        kline_data.duan.to_list(),
        entanglement_list,
        kline_data.duan2.to_list(),
    )
    rise_break_pivot_zg_sg = rise_break_pivot_zg(
        kline_data["datetime"].to_list(),
        kline_data.time_str.to_list(),
        kline_data.high.to_list(),
        kline_data.low.to_list(),
        kline_data.duan.to_list(),
        entanglement_list,
        kline_data.duan2.to_list(),
    )
    rise_break_pivot_zm_sg = rise_break_pivot_zm(
        kline_data["datetime"].to_list(),
        kline_data.time_str.to_list(),
        kline_data.high.to_list(),
        kline_data.low.to_list(),
        kline_data.duan.to_list(),
        entanglement_list,
        kline_data.duan2.to_list(),
    )
    rise_break_pivot_zd_sg = rise_break_pivot_zd(
        kline_data["datetime"].to_list(),
        kline_data.time_str.to_list(),
        kline_data.high.to_list(),
        kline_data.low.to_list(),
        kline_data.duan.to_list(),
        entanglement_list,
        kline_data.duan2.to_list(),
    )
    if entanglement_list_1d is not None:
        datetime_list = []
        time_str_list = []
        date_str_list = []
        zg_list = []
        zd_list = []
        direction_list = []
        daily_time_str_list = daily_data["time_str"].to_list()
        for i in range(len(entanglement_list_1d)):
            pivot = entanglement_list_1d[i]
            for j in range(pivot.start, pivot.end + 1):
                time_str = daily_time_str_list[j]
                datetime_list.append(
                    datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                )
                time_str_list.append(time_str)
                date_str_list.append(
                    datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M").strftime(
                        "%Y-%m-%d"
                    )
                )
                zg_list.append(pivot.zg)
                zd_list.append(pivot.zd)
                direction_list.append(pivot.direction)
        gao_ji_bie_data = pd.DataFrame(
            {
                "date_str": date_str_list,
                "zg": zg_list,
                "zd": zd_list,
                "direction": direction_list,
            }
        )
        mian_ji_di_bei_chi_sg = mian_ji_di_bei_chi(
            kline_data["datetime"].to_list(),
            kline_data["time_str"].to_list(),
            kline_data["high"].to_list(),
            kline_data["low"].to_list(),
            kline_data["bi"].to_list(),
            kline_data["duan"].to_list(),
            kline_data["diff"].to_list(),
            kline_data["macd"].to_list(),
            kline_data["jc"].to_list(),
            kline_data["duan2"].to_list(),
        )
        ben_ji_bie_data = pd.DataFrame(
            {
                "datetime": mian_ji_di_bei_chi_sg["datetime"],
                "time_str": mian_ji_di_bei_chi_sg["time_str"],
                "price": mian_ji_di_bei_chi_sg["price"],
                "stop_lose_price": mian_ji_di_bei_chi_sg["stop_lose_price"],
                "stop_win_price": mian_ji_di_bei_chi_sg["stop_win_price"],
            }
        )
        ben_ji_bie_data["date_str"] = ben_ji_bie_data["time_str"].apply(
            lambda v: datetime.datetime.strptime(v, "%Y-%m-%d %H:%M").strftime(
                "%Y-%m-%d"
            )
        )
        ben_ji_bie_data = ben_ji_bie_data.join(
            gao_ji_bie_data.set_index("date_str"), on="date_str", how="outer", sort=True
        )
        ben_ji_bie_data["zg"].fillna(method="ffill", inplace=True)
        ben_ji_bie_data["zd"].fillna(method="ffill", inplace=True)
        ben_ji_bie_data["direction"].fillna(method="ffill", inplace=True)
        ben_ji_bie_data.dropna(subset=["datetime"], inplace=True)
        ben_ji_bie_data = ben_ji_bie_data[
            (ben_ji_bie_data["price"] >= ben_ji_bie_data["zd"])
            & (ben_ji_bie_data["price"] < ben_ji_bie_data["zg"])
        ]
        mian_ji_di_bei_chi_sg = ben_ji_bie_data[
            [
                "datetime",
                "time_str",
                "price",
                "stop_lose_price",
                "stop_win_price",
                "zd",
                "zg",
            ]
        ].to_dict(orient="list")

        huang_bai_xian_di_bei_chi_sg = huang_bai_xian_di_bei_chi(
            kline_data["datetime"].to_list(),
            kline_data["time_str"].to_list(),
            kline_data["high"].to_list(),
            kline_data["low"].to_list(),
            kline_data["bi"].to_list(),
            kline_data["duan"].to_list(),
            kline_data["diff"].to_list(),
            kline_data["dea"].to_list(),
            kline_data["jc"].to_list(),
            kline_data["duan2"].to_list(),
        )

        ben_ji_bie_data = pd.DataFrame(
            {
                "datetime": huang_bai_xian_di_bei_chi_sg["datetime"],
                "time_str": huang_bai_xian_di_bei_chi_sg["time_str"],
                "price": huang_bai_xian_di_bei_chi_sg["price"],
                "stop_lose_price": huang_bai_xian_di_bei_chi_sg["stop_lose_price"],
                "stop_win_price": huang_bai_xian_di_bei_chi_sg["stop_win_price"],
            }
        )

        ben_ji_bie_data["date_str"] = ben_ji_bie_data["time_str"].apply(
            lambda v: datetime.datetime.strptime(v, "%Y-%m-%d %H:%M").strftime(
                "%Y-%m-%d"
            )
        )
        ben_ji_bie_data = ben_ji_bie_data.join(
            gao_ji_bie_data.set_index("date_str"), on="date_str", how="outer", sort=True
        )
        ben_ji_bie_data["zg"].fillna(method="ffill", inplace=True)
        ben_ji_bie_data["zd"].fillna(method="ffill", inplace=True)
        ben_ji_bie_data["direction"].fillna(method="ffill", inplace=True)
        ben_ji_bie_data.dropna(subset=["datetime"], inplace=True)
        ben_ji_bie_data = ben_ji_bie_data[
            (ben_ji_bie_data["price"] >= ben_ji_bie_data["zd"])
            & (ben_ji_bie_data["price"] < ben_ji_bie_data["zg"])
        ]
        huang_bai_xian_di_bei_chi_sg = ben_ji_bie_data[
            [
                "datetime",
                "time_str",
                "price",
                "stop_lose_price",
                "stop_win_price",
                "zd",
                "zg",
            ]
        ].to_dict(orient="list")
    # 计算MACD背离
    macd_divergence = locate_macd_divergence(
        kline_data["datetime"].to_list(),
        kline_data.high.to_list(),
        kline_data.low.to_list(),
        kline_data.open.to_list(),
        kline_data.close.to_list(),
        kline_data.bi.to_list(),
    )

    macd_bullish_divergence = macd_divergence["bullish"]
    macd_bearish_divergence = macd_divergence["bearish"]

    resp = {
        "symbol": symbol,
        "period": period,
        "endDate": end_date,
        "dateBigLevel": [],
        "date": kline_data.time_str.to_list(),
        "open": kline_data.open.to_list(),
        "high": kline_data.high.to_list(),
        "low": kline_data.low.to_list(),
        "close": kline_data.close.to_list(),
        "bidata": bi_data,
        "duandata": duan_data,
        "higherDuanData": higher_chanlun_data,
        "higherHigherDuanData": placeholder.higherHigherDuanData,
        "rise_break_pivot_gg_sg": rise_break_pivot_gg_sg,
        "rise_break_pivot_zg_sg": rise_break_pivot_zg_sg,
        "rise_break_pivot_zm_sg": rise_break_pivot_zm_sg,
        "rise_break_pivot_zd_sg": rise_break_pivot_zd_sg,
        "mian_ji_di_bei_chi_sg": mian_ji_di_bei_chi_sg,
        "huang_bai_xian_di_bei_chi_sg": huang_bai_xian_di_bei_chi_sg,
        "macd_bullish_divergence": macd_bullish_divergence,
        "macd_bearish_divergence": macd_bearish_divergence,
    }

    resp["notLower"] = calcNotLower(kline_data.duan.to_list(), kline_data.low.to_list())
    resp["notHigher"] = calcNotHigher(
        kline_data.duan.to_list(), kline_data.high.to_list()
    )

    return resp


def calcNotLower(duanList, lowList):
    if Duan.notLower(duanList, lowList):
        return True
    else:
        return False


def calcNotHigher(duanList, highList):
    if Duan.notHigher(duanList, highList):
        return True
    else:
        return False


if __name__ == "__main__":
    codes = [
        "588060",
        "515220",
        "513330",
        "513180",
        "513130",
        "513090",
        "588000",
        "512050",
        "588200",
        "513060",
        "159361",
        "159338",
        "513050",
        "512480",
        "159352",
        "513120",
        "563800",
        "159915",
        "159740",
        "159949",
        "563360",
        "563880",
        "512010",
        "512170",
        "588080",
        "510300",
        "159351",
        "513010",
        "159605",
        "512880",
        "159755",
        "510050",
        "560610",
        "513310",
        "512100",
        "563220",
        "512690",
        "159892",
        "159792",
        "159529",
        "159920",
        "513400",
        "159353",
        "159869",
        "560530",
        "159995",
        "159339",
        "513980",
        "512000",
        "159360",
        "159357",
        "512710",
        "512760",
        "159819",
        "588220",
        "588030",
        "512660",
        "510900",
        "513730",
        "159813",
        "159607",
        "159941",
        "159851",
        "515790",
        "513360",
        "563300",
        "588050",
        "159992",
        "588800",
        "588190",
        "518880",
        "159682",
        "588290",
        "510210",
        "159742",
        "513770",
        "513380",
        "513100",
        "560510",
        "515030",
    ]
    for code in codes:
        print(code)
        data = get_data_v2(code, "1m")
        print(data)
