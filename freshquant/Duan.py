# -*- coding: utf-8 -*-

import pydash


def notHigher(duan_s, high_s):
    """
    不破前高
    """
    i1 = pydash.find_last_index(duan_s, lambda d: d == 1)
    i2 = pydash.find_last_index(duan_s[:i1], lambda d: d == 1)
    if i1 > i2 > -1:
        if high_s[i1] <= high_s[i2]:
            return True
    return False


def notLower(duan_s, low_s):
    """
    不破前低
    """
    i1 = pydash.find_last_index(duan_s, lambda d: d == -1)
    i2 = pydash.find_last_index(duan_s[:i1], lambda d: d == -1)
    if i1 > i2 > -1:
        if low_s[i1] >= low_s[i2]:
            return True
    return False


def inspect(
    duan_series,
    high_series,
    low_series,
    close_series,
    diff_series,
    dea_series,
    inspect_index,
):
    """
    前高前低和线段类型
    """
    i1 = pydash.find_last_index(duan_series[: (inspect_index + 1)], lambda x: x == -1)
    i2 = pydash.find_last_index(duan_series[: (inspect_index + 1)], lambda x: x == 1)
    if i1 < 0 or i2 < 0:
        return None
    duan_low = low_series[i1]
    duan_high = high_series[i2]
    duan_type = 1 if i2 > i1 else -1
    inspect_price = close_series[inspect_index]
    rtn = {
        'duan_start': i1 if i1 < i2 else i2,
        'duan_end': i2 if i2 > i1 else i1,
        'duan_high': duan_high,
        'duan_low': duan_low,
        'duan_type': duan_type,
        'inspect_index': inspect_index,
        'inspect_price': inspect_price,
    }
    return rtn
