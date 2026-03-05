from typing import Any, Dict, List

import akshare as ak

from fqchan04 import (
    fq_recognise_bars,
    fq_recognise_bi,
    fq_recognise_duan,
    fq_recognise_pivots,
    fq_recognise_std_bars,
)


# 中枢结构定义
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

        self.stick_list = fq_recognise_bars(
            length, self.high_price_list, self.low_price_list
        )
        self.merged_stick_list = fq_recognise_std_bars(
            length, self.high_price_list, self.low_price_list
        )

        self.bi_signal_list = fq_recognise_bi(
            length, self.high_price_list, self.low_price_list
        )
        self.bi_data = self._signal_to_data(self.bi_signal_list)

        self.duan_signal_list = fq_recognise_duan(
            length, self.bi_signal_list, self.high_price_list, self.low_price_list
        )
        self.duan_data = self._signal_to_data(self.duan_signal_list)
        self.higher_duan_signal_list = fq_recognise_duan(
            length, self.duan_signal_list, self.high_price_list, self.low_price_list
        )
        self.higher_duan_data = self._signal_to_data(self.higher_duan_signal_list)

        self.pivot_list = fq_recognise_pivots(
            length,
            self.duan_signal_list,
            self.bi_signal_list,
            self.high_price_list,
            self.low_price_list,
        )
        self.high_pivot_list = fq_recognise_pivots(
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
                data['data'].append(round(self.high_price_list[i], 2))
                data['vertex_type'].append(1)
            elif signal[i] == -1:
                data['dt'].append(self.dt_list[i])
                data['data'].append(round(self.low_price_list[i], 2))
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
            e.zg = round(pivot["zg"], 2)
            e.zd = round(pivot["zd"], 2)
            e.gg = round(pivot["gg"], 2)
            e.dd = round(pivot["dd"], 2)
            e.direction = pivot["direction"]
            e.top = e.zg
            e.bottom = e.zd
            e_list.append(e)
        return e_list


if __name__ == "__main__":
    chanlun = Chanlun()
    stock_zh_index_daily_df = ak.stock_zh_index_daily(symbol="sh000001")
    print(stock_zh_index_daily_df)
    chanlun.analysis(
        dt_list=stock_zh_index_daily_df["date"].tolist(),
        open_price_list=stock_zh_index_daily_df["open"].tolist(),
        close_price_list=stock_zh_index_daily_df["close"].tolist(),
        low_price_list=stock_zh_index_daily_df["low"].tolist(),
        high_price_list=stock_zh_index_daily_df["high"].tolist(),
    )
    print("笔:")
    print(chanlun.bi_data)
    print("段:")
    print(chanlun.duan_data)
    print("中枢:")
    print(chanlun.pivot_list)
