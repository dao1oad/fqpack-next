# -*- coding: utf-8 -*-

from typing import Any, Dict, List

import fqchan01
import fqchan02
import fqchan03
import fqchan04
import pandas as pd

from freshquant.basic.util import get_zhong_shu_data, str_from_timestamp
from freshquant.pattern.chanlun.macd_divergence import locate_macd_divergence
from freshquant.pattern.chanlun.pullback import locate_pullback
from freshquant.pattern.chanlun.v_reversal import locate_v_reversal

imps = {'cl1': fqchan01, 'cl2': fqchan02, 'cl3': fqchan03, 'cl4': fqchan04}


class Entanglement:
    def __init__(self):
        self.start = 0
        self.end = 0
        self.startTime = 0
        self.endTime = 0
        # 中枢高
        self.top = 0
        # 中枢高
        self.zg = 0
        # 中枢低
        self.bottom = 0
        # 中枢低
        self.zd = 0
        # 中枢高高
        self.gg = 0
        # 中枢低低
        self.dd = 0
        self.direction = 0
        self.formal = False


class Chanlun:

    imp: str
    dt_list: List[int]
    open_price_list: List[float]
    close_price_list: List[float]
    low_price_list: List[float]
    high_price_list: List[float]
    stick_list: List[Any]
    merged_stick_list: List[Any]
    bi_signal_list: List[float]
    bi_data: Dict
    duan_signal_list: List[float]
    duan_data: Dict
    higher_duan_signal_list: List[float]
    higher_duan_data: Dict
    pivot_list: List[Any]
    high_pivot_list: List[Any]
    entanglement_list: List[Any]
    high_entanglement_list: List[Any]

    def __init__(self, imp="cl4"):
        self.imp = imp

    def analysis(
        self,
        dt_list: List[int],
        open_price_list: List[float],
        close_price_list: List[float],
        low_price_list: List[float],
        high_price_list: List[float],
    ):
        length = len(dt_list)
        assert (
            len(open_price_list) == length
            and len(close_price_list) == length
            and len(low_price_list) == length
            and len(high_price_list) == length
        ), "数据长度不一致"
        self.dt_list = dt_list

        self.open_price_list = open_price_list
        self.close_price_list = close_price_list
        self.low_price_list = low_price_list
        self.high_price_list = high_price_list

        self.stick_list = imps[self.imp].fq_recognise_bars(
            length, self.high_price_list, self.low_price_list
        )
        self.merged_stick_list = imps[self.imp].fq_recognise_std_bars(
            length, self.high_price_list, self.low_price_list
        )

        self.bi_signal_list = imps[self.imp].fq_recognise_bi(
            length, self.high_price_list, self.low_price_list
        )
        self.bi_data = self._signal_to_data(self.bi_signal_list)

        self.duan_signal_list = imps[self.imp].fq_recognise_duan(
            length, self.bi_signal_list, self.high_price_list, self.low_price_list
        )
        self.duan_data = self._signal_to_data(self.duan_signal_list)
        self.higher_duan_signal_list = imps[self.imp].fq_recognise_duan(
            length, self.duan_signal_list, self.high_price_list, self.low_price_list
        )
        self.higher_duan_data = self._signal_to_data(self.higher_duan_signal_list)

        self.pivot_list = imps[self.imp].fq_recognise_pivots(
            length,
            self.duan_signal_list,
            self.bi_signal_list,
            self.high_price_list,
            self.low_price_list,
        )
        self.high_pivot_list = imps[self.imp].fq_recognise_pivots(
            length,
            self.higher_duan_signal_list,
            self.duan_signal_list,
            self.high_price_list,
            self.low_price_list,
        )

        self.entanglement_list = self._convert_to_entanglement_list(self.pivot_list)
        self.high_entanglement_list = self._convert_to_entanglement_list(
            self.high_pivot_list
        )
        return self

    def _signal_to_data(self, signal):
        data = {"dt": [], "data": [], "vertex_type": []}
        for i in range(len(signal)):
            if signal[i] == 1:
                data['dt'].append(self.dt_list[i])
                data['data'].append(self.high_price_list[i])
                data['vertex_type'].append(1)
            elif signal[i] == -1:
                data['dt'].append(self.dt_list[i])
                data['data'].append(self.low_price_list[i])
                data['vertex_type'].append(-1)
        return data

    def _convert_to_entanglement_list(self, pivot_list):
        e_list = []
        for i in range(len(pivot_list)):
            pivot = pivot_list[i]
            e = Entanglement()
            e.start = pivot["start"]
            e.startTime = self.dt_list[e.start]
            e.end = pivot["end"]
            e.endTime = self.dt_list[e.end]
            e.zg = pivot["zg"]
            e.zd = pivot["zd"]
            e.gg = pivot["gg"]
            e.dd = pivot["dd"]
            e.direction = pivot["direction"]
            e.top = e.zg
            e.bottom = e.zd
            e_list.append(e)
        return e_list


def calculate_trading_signals(kline_data: pd.DataFrame) -> Dict[str, Any]:
    """
    计算缠论买卖点信号

    Args:
        kline_data: K线数据DataFrame，必须包含以下列：
            - datetime: 时间
            - high: 最高价
            - low: 最低价
            - open: 开盘价
            - close: 收盘价
            - time_stamp: 时间戳
            - time_str: 时间字符串

    Returns:
        包含以下字段的字典：
            - open, high, low, close: 价格列表
            - bi_signal_list: 笔信号列表
            - duan_signal_list: 段信号列表
            - higher_duan_signal_list: 高级别段信号列表
            - bi_data: 笔数据
            - duan_data: 段数据
            - higher_duan_data: 高级别段数据
            - higher_higher_duan_data: 更高级别段数据（占位）
            - zd_data: 中枢数据
            - zs_flag: 中枢标志
            - duan_zs_data: 段中枢数据
            - duan_zs_flag: 段中枢标志
            - high_duan_zs_data: 高级别段中枢数据
            - high_duan_zs_flag: 高级别段中枢标志
            - buy_zs_huila: 买点回拉信号
            - sell_zs_huila: 卖点回拉信号
            - buy_v_reverse: 买点V反信号
            - sell_v_reverse: 卖点V反信号
            - macd_bullish_divergence: MACD底背离
            - macd_bearish_divergence: MACD顶背离
    """
    # 执行缠论分析
    chanlun = Chanlun().analysis(
        kline_data.time_stamp.to_list(),
        kline_data.open.to_list(),
        kline_data.close.to_list(),
        kline_data.low.to_list(),
        kline_data.high.to_list(),
    )

    # 构建笔、段、高级别段数据
    bi_data = {
        'date': list(map(str_from_timestamp, chanlun.bi_data['dt'])),
        'data': chanlun.bi_data['data'],
    }
    duan_data = {
        'date': list(map(str_from_timestamp, chanlun.duan_data['dt'])),
        'data': chanlun.duan_data['data'],
    }
    higher_duan_data = {
        'date': list(map(str_from_timestamp, chanlun.higher_duan_data['dt'])),
        'data': chanlun.higher_duan_data['data'],
    }

    # 计算笔中枢
    zd_data, zs_flag = get_zhong_shu_data(chanlun.entanglement_list)

    # 计算段中枢
    duan_zs_data, duan_zs_flag = get_zhong_shu_data(chanlun.high_entanglement_list)

    # 计算回拉信号
    hui_la = locate_pullback(
        kline_data['datetime'].to_list(),
        kline_data.high.to_list(),
        kline_data.low.to_list(),
        kline_data.open.to_list(),
        kline_data.close.to_list(),
        chanlun.bi_signal_list,
    )
    buy_zs_huila = hui_la['buy_zs_huila']
    sell_zs_huila = hui_la['sell_zs_huila']

    # 计算V反信号
    v_reverse = locate_v_reversal(
        kline_data['datetime'].to_list(),
        kline_data.high.to_list(),
        kline_data.low.to_list(),
        kline_data.open.to_list(),
        kline_data.close.to_list(),
        chanlun.bi_signal_list,
    )
    buy_v_reverse = v_reverse['buy_v_reverse']
    sell_v_reverse = v_reverse['sell_v_reverse']

    # 计算MACD背离
    macd_divergence = locate_macd_divergence(
        kline_data['datetime'].to_list(),
        kline_data.high.to_list(),
        kline_data.low.to_list(),
        kline_data.open.to_list(),
        kline_data.close.to_list(),
        chanlun.bi_signal_list,
    )
    macd_bullish_divergence = macd_divergence['bullish']
    macd_bearish_divergence = macd_divergence['bearish']

    return {
        'open': kline_data.open.to_list(),
        'high': kline_data.high.to_list(),
        'low': kline_data.low.to_list(),
        'close': kline_data.close.to_list(),
        'bi_signal_list': chanlun.bi_signal_list,
        'duan_signal_list': chanlun.duan_signal_list,
        'higher_duan_signal_list': chanlun.higher_duan_signal_list,
        'bi_data': bi_data,
        'duan_data': duan_data,
        'higher_duan_data': higher_duan_data,
        'higher_higher_duan_data': [],
        'zd_data': zd_data,
        'zs_flag': zs_flag,
        'duan_zs_data': duan_zs_data,
        'duan_zs_flag': duan_zs_flag,
        'high_duan_zs_data': [],
        'high_duan_zs_flag': [],
        'buy_zs_huila': buy_zs_huila,
        'sell_zs_huila': sell_zs_huila,
        'buy_v_reverse': buy_v_reverse,
        'sell_v_reverse': sell_v_reverse,
        'macd_bullish_divergence': macd_bullish_divergence,
        'macd_bearish_divergence': macd_bearish_divergence,
    }
