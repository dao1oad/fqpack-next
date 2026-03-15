# -*- coding: utf-8 -*-

from datetime import datetime

import pandas as pd

from freshquant.basic.singleton_type import SingletonType
from freshquant.quantaxis.qafetch.qatdx_adv import QA_Tdx_Executor
from freshquant.runtime_constants import DT_FORMAT_M, TZ


class TdxExecutor(metaclass=SingletonType):
    def __init__(self):
        self._executor = QA_Tdx_Executor()

    def get_security_bars(self, code, _type, lens):
        return self._executor.get_security_bars(code, _type, lens)


if __name__ == "__main__":
    executor = TdxExecutor()
    data = executor.get_security_bars('600477', '5min', 800)
    df = pd.DataFrame(data=data)
    df.rename(columns={"vol": "volume"}, inplace=True)
    df = df[["datetime", "open", "close", "high", "low", "volume", "amount"]]
    df['datetime'] = df['datetime'].apply(
        lambda record: TZ.localize(datetime.strptime(record, DT_FORMAT_M))
    )
    df.set_index('datetime', inplace=True, drop=True)
    df['open'] = df['open'].astype('float64')
    df['close'] = df['close'].astype('float64')
    df['high'] = df['high'].astype('float64')
    df['low'] = df['low'].astype('float64')
    df['volume'] = df['volume'].astype('float64')
    df["frequence"] = "5min"
    df["source"] = "通达信"
    print(df)
