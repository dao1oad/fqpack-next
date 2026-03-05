# -*- coding: utf-8 -*-

import pydash


def mian_ji_di_bei_chi(
    datetime_list,
    time_str_list,
    high_list,
    low_list,
    bi_list,
    duan_list,
    diff_list,
    macd_list,
    jc_list,
    higher_duan_list,
):
    '''
    面积底背驰
    '''
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    for i in range(len(jc_list)):
        if jc_list[i] == 1 and diff_list[i] < 0:
            j = pydash.find_last_index(duan_list[: i + 1], lambda v: v == 1 or v == -1)
            if j > -1 and duan_list[j] == -1:
                duan_e = j
                k = pydash.find_last_index(duan_list[:j], lambda v: v == 1)
                if k > -1:
                    duan_s = k
                    mian_ji_list = []
                    bi_e = duan_e
                    while True:
                        bi_s = pydash.find_last_index(bi_list[:bi_e], lambda v: v == 1)
                        if bi_s >= duan_s:
                            mian_ji = (
                                pydash.chain(macd_list[bi_s : bi_e + 1])
                                .filter_(lambda v: v > 0)
                                .map_(abs)
                                .sum_()
                                .value()
                            )
                            mian_ji_list.append(mian_ji)
                            bi_e = pydash.find_last_index(
                                bi_list[:bi_s], lambda v: v == -1
                            )
                            if bi_e < duan_s:
                                break
                        else:
                            break
                    if (
                        len(mian_ji_list) > 1
                        and pydash.max_(mian_ji_list) > mian_ji_list[-1]
                    ):
                        peak = 0
                        peak1 = 0
                        peak2 = 0
                        peak1_index = pydash.find_last_index(
                            higher_duan_list[:i], lambda v: v == 1
                        )
                        peak2_index = pydash.find_last_index(
                            duan_list[:i], lambda v: v == 1
                        )
                        if peak1_index >= 0:
                            peak1 = high_list[peak1_index]
                        if peak2_index >= 0:
                            peak2 = high_list[peak2_index]
                        peak = max(peak1, peak2)
                        if peak <= 0:
                            peak = pydash.max_(high_list[:i])
                        if peak * 0.7 > high_list[i]:
                            result['idx'].append(i)
                            result['datetime'].append(datetime_list[i])
                            result['time_str'].append(time_str_list[i])
                            result['price'].append(high_list[i])
                            result['stop_lose_price'].append(low_list[duan_e])
                            result['stop_win_price'].append(high_list[duan_s])
    return result


def huang_bai_xian_di_bei_chi(
    datetime_list,
    time_str_list,
    high_list,
    low_list,
    bi_list,
    duan_list,
    diff_list,
    dea_list,
    jc_list,
    higher_duan_list,
):
    '''
    黄白线底背驰
    '''
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    for i in range(len(jc_list)):
        if jc_list[i] == 1 and diff_list[i] < 0 and dea_list[i] < 0:
            j = pydash.find_last_index(duan_list[: i + 1], lambda v: v == 1 or v == -1)
            if j > -1 and duan_list[j] == -1:
                duan_e = j
                k = pydash.find_last_index(duan_list[:j], lambda v: v == 1)
                if k > -1:
                    duan_s = k
                    min_list = []
                    bi_e = duan_e
                    while True:
                        bi_s = pydash.find_last_index(bi_list[:bi_e], lambda v: v == 1)
                        if bi_s >= duan_s:
                            a = pydash.chain(diff_list[bi_s : bi_e + 1]).min_().value()
                            b = pydash.chain(dea_list[bi_s : bi_e + 1]).min_().value()
                            min_list.append(min(a, b))
                            bi_e = pydash.find_last_index(
                                bi_list[:bi_s], lambda v: v == -1
                            )
                            if bi_e < duan_s:
                                break
                        else:
                            break
                    if len(min_list) > 1 and pydash.min_(min_list) < min_list[-1]:
                        peak = 0
                        peak1 = 0
                        peak2 = 0
                        peak1_index = pydash.find_last_index(
                            higher_duan_list[:i], lambda v: v == 1
                        )
                        peak2_index = pydash.find_last_index(
                            duan_list[:i], lambda v: v == 1
                        )
                        if peak1_index >= 0:
                            peak1 = high_list[peak1_index]
                        if peak2_index >= 0:
                            peak2 = high_list[peak2_index]
                        peak = max(peak1, peak2)
                        if peak <= 0:
                            peak = pydash.max_(high_list[:i])
                        if peak * 0.7 > high_list[i]:
                            result['idx'].append(i)
                            result['datetime'].append(datetime_list[i])
                            result['time_str'].append(time_str_list[i])
                            result['price'].append(high_list[i])
                            result['stop_lose_price'].append(low_list[duan_e])
                            result['stop_win_price'].append(high_list[duan_s])
    return result
