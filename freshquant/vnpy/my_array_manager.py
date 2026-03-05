# -*- coding: utf-8 -*-

import numpy as np
from vnpy.trader.object import BarData
from vnpy.trader.utility import ArrayManager


class MyArrayManager(ArrayManager):
    def __init__(self, size: int = 100):
        super().__init__(size)
        self.time_array: np.ndarray = np.zeros(size)

    def update_bar(self, bar: BarData) -> None:
        super().update_bar(bar)
        self.time_array[:-1] = self.time_array[1:]
        self.time_array[-1] = bar.datetime.timestamp()

    @property
    def time(self) -> np.ndarray:
        return self.time_array
