# -*- coding: utf-8 -*-


def find_index(series, func, start=0, stop=None):
    if stop is None:
        stop = len(series)
    for i in range(start, stop):
        if func(series[i]):
            return i
    return -1
