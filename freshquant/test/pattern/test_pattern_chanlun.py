# coding: utf-8

from freshquant.analysis.chanlun_analysis import Chanlun
from freshquant.KlineDataTool import get_stock_data
from freshquant.pattern import pattern_chanlun


def test_la_hui():
    kline_data = get_stock_data("sh600000", "60m", None)
    kline_data["time_str"] = kline_data["datetime"].apply(
        lambda dt: dt.strftime("%Y-%m-%d %H:%M")
    )
    chanlun = Chanlun().analysis(
        kline_data.time_stamp.to_list(),
        kline_data.open.to_list(),
        kline_data.close.to_list(),
        kline_data.low.to_list(),
        kline_data.high.to_list(),
    )
    kline_data['bi'] = chanlun.bi_signal_list
    kline_data['duan'] = chanlun.duan_signal_list
    kline_data['duan2'] = chanlun.higher_duan_signal_list
    print(kline_data)
    la_hui = pattern_chanlun.la_hui(
        chanlun.entanglement_list,
        kline_data['datetime'].to_list(),
        kline_data.time_str.to_list(),
        kline_data.high.to_list(),
        kline_data.low.to_list(),
        kline_data.bi.to_list(),
        kline_data.duan.to_list(),
        kline_data.duan2.to_list(),
    )
    print(la_hui)


def test_tu_po():
    kline_data = get_stock_data("sh600000", "60m", None)
    kline_data["time_str"] = kline_data["datetime"].apply(
        lambda dt: dt.strftime("%Y-%m-%d %H:%M")
    )
    chanlun = Chanlun().analysis(
        kline_data.time_stamp.to_list(),
        kline_data.open.to_list(),
        kline_data.close.to_list(),
        kline_data.low.to_list(),
        kline_data.high.to_list(),
    )
    kline_data['bi'] = chanlun.bi_signal_list
    kline_data['duan'] = chanlun.duan_signal_list
    kline_data['duan2'] = chanlun.higher_duan_signal_list
    print(kline_data)
    tu_po = pattern_chanlun.tu_po(
        chanlun.entanglement_list,
        kline_data.datetime.to_list(),
        kline_data.time_str.to_list(),
        kline_data.high.to_list(),
        kline_data.low.to_list(),
        kline_data.open.to_list(),
        kline_data.close.to_list(),
        kline_data.bi.to_list(),
        kline_data.duan.to_list(),
        kline_data.duan2.to_list(),
    )
    print(tu_po)
