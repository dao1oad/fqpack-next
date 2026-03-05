# -*- coding: utf-8 -*-

from datetime import datetime

import pydash


def rise_hui_la(
    datetime_list,
    time_str_list,
    high_list,
    low_list,
    a0_bi_list,
    a0_duan_list,
    a0_e_list,
):
    '''
    向上回啦最后一个中枢
    '''
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    for i in range(len(a0_e_list)):
        e = a0_e_list[i]
        e_next = a0_e_list[i + 1] if i + 1 < len(a0_e_list) else None
        if e.direction == -1:
            # 下跌中枢，找第一次的拉回
            leave = e.end
            for x in range(e.end + 1, len(low_list)):
                if low_list[x] < e.zd and a0_bi_list[x] == -1:
                    leave = x
                    break
                if a0_duan_list[x] == 1:
                    break
            if leave - e.end >= 5:
                r = -1
                for x in range(leave + 1, len(high_list)):
                    if e_next is not None and x >= e_next.start:
                        break
                    if high_list[x] > e.bottom and (
                        len(
                            pydash.chain(high_list[e.end + 1 : x])
                            .filter_(lambda a: a < e.bottom)
                            .value()
                        )
                        > 0
                        or len(
                            pydash.chain(low_list[e.end + 1 : x])
                            .filter_(lambda a: a < e.dd)
                            .value()
                        )
                        > 0
                    ):
                        r = x
                        break
                    if a0_duan_list[x] == 1:
                        break
                if r >= 0:
                    result['idx'].append(r)
                    result['datetime'].append(datetime_list[r])
                    result['time_str'].append(time_str_list[r])
                    result['price'].append(e.bottom)
                    bottom_index = pydash.find_last_index(
                        a0_duan_list[: r + 1], lambda a: a == -1
                    )
                    if bottom_index > -1:
                        result['stop_lose_price'].append(low_list[bottom_index])
                        stop_win_price = e.bottom + (e.bottom - low_list[bottom_index])
                        result['stop_win_price'].append(stop_win_price)
                    else:
                        result['stop_lose_price'].append(0)
                        result['stop_win_price'].append(0)
    return result


def rise_five_v_fan(datetime_list, time_str_list, a0_bi_list, high_list, low_list):
    '''
    5浪V反
    '''
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    for i in range(len(a0_bi_list)):
        if a0_bi_list[i] == -1:
            d1 = i
            g1 = pydash.find_last_index(a0_bi_list[:d1], lambda x: x == 1)
            d2 = pydash.find_last_index(a0_bi_list[:g1], lambda x: x == -1)
            g2 = pydash.find_last_index(a0_bi_list[:d2], lambda x: x == 1)
            d3 = pydash.find_last_index(a0_bi_list[:g2], lambda x: x == -1)
            g3 = pydash.find_last_index(a0_bi_list[:d3], lambda x: x == 1)
            if (
                g3 >= 0
                and high_list[g1] < high_list[g2] < high_list[g3]
                and low_list[d1] < low_list[d2] < low_list[d3]
                and high_list[g1] < low_list[d3]
            ):
                for k in range(i + 1, len(a0_bi_list)):
                    if high_list[k] > high_list[g1]:
                        if (
                            pydash.find_last_index(
                                result['time_str'], lambda x: x == time_str_list[k]
                            )
                            == -1
                        ):
                            result['idx'].append(k)
                            result['datetime'].append(datetime_list[k])
                            result['time_str'].append(time_str_list[k])
                            result['price'].append(high_list[g1])
                            result['stop_lose_price'].append(low_list[d1])
                        break
                    if a0_bi_list[k] == -1:
                        break
    return result


def rise_v_reverse(
    datetime_list,
    time_str_list,
    high_list,
    low_list,
    a0_bi_list,
    a0_duan_list,
    a0_pivots,
):
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    count = len(time_str_list)
    for i in range(len(a0_pivots)):
        e = a0_pivots[i]
        next_e = a0_pivots[i + 1] if i < len(a0_pivots) - 1 else None
        if e.direction == -1:
            # 离开中枢后的第一段结束
            leave_end_index = -1
            for x in range(e.end + 1, count):
                if a0_duan_list[x] == -1:
                    leave_end_index = x
                    break
                if next_e is not None and x >= next_e.start:
                    break
            if leave_end_index >= 0:
                # 存在3卖
                sell3 = False
                resist_index = -1
                resist_price = 0
                for j in range(e.end + 1, leave_end_index):
                    if a0_bi_list[j] == 1 and high_list[j] > e.dd:
                        sell3 = True
                        resist_index = j
                        resist_price = high_list[resist_index]
                        break
                if sell3:
                    for k in range(leave_end_index + 1, len(high_list)):
                        if a0_bi_list[k] == 1:
                            break
                        if high_list[k] > resist_price:
                            if (
                                pydash.find_last_index(
                                    result['time_str'], lambda x: x == time_str_list[k]
                                )
                                == -1
                            ):
                                result['idx'].append(k)
                                result['datetime'].append(datetime_list[k])
                                result['time_str'].append(time_str_list[k])
                                result['price'].append(resist_price)
                                result['stop_lose_price'].append(
                                    low_list[leave_end_index]
                                )
                            break
    return result


def rise_po_huai(
    datetime_list, time_list, high_list, low_list, a0_bi_list, a0_duan_list
):
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    for i in range(len(a0_duan_list)):
        if a0_duan_list[i] == -1:
            anchor = 0
            for j in range(i + 1, len(time_list)):
                if a0_duan_list[j] == 1:
                    break
                if a0_bi_list[j] == 1:
                    anchor = j
                    break
            if anchor > 0:
                for k in range(anchor + 1, len(time_list)):
                    if a0_duan_list[k] == 1:
                        break
                    if high_list[k] > high_list[anchor]:
                        result['idx'].append(k)
                        result['datetime'].append(datetime_list[k])
                        result['time_str'].append(time_list[k])
                        result['price'].append(high_list[anchor])
                        result['stop_lose_price'].append(low_list[i])
                        break
    return result


def rise_tu_po(datetime_list, time_str_list, high_list, duan_list, a0_e_list):
    '''
    向上突破中枢
    '''
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    for i in range(len(a0_e_list)):
        e = a0_e_list[i]
        e_pre = a0_e_list[i - 1] if i > 0 else None
        if e.direction == 1:
            duan_start = pydash.find_last_index(duan_list[: e.start], lambda t: t == -1)
            if e_pre is not None and 0 <= duan_start < e_pre.start:
                continue
            r = -1
            for x in range(e.end + 1, len(high_list)):
                if high_list[x] > e.gg:
                    r = x
                    break
                if duan_list[x] == 1:
                    break
            if r > 0:
                result['idx'].append(r)
                result['datetime'].append(datetime_list[r])
                result['time_str'].append(time_str_list[r])
                result['price'].append(e.gg)
                result['stop_lose_price'].append(e.zg)
    return result


def down_hui_la(
    datetime_list,
    time_str_list,
    high_list,
    low_list,
    a0_bi_list,
    a0_duan_list,
    a0_pivots,
):
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    for i in range(len(a0_pivots)):
        e = a0_pivots[i]
        e_next = a0_pivots[i + 1] if i + 1 < len(a0_pivots) else None
        if e.direction == 1:
            # 上涨中枢，找第一次的拉回
            # 离开中枢后的第一个笔结束
            leave = e.end
            for x in range(e.end + 1, len(high_list)):
                if high_list[x] > e.zg and a0_bi_list[x] == 1:
                    leave = x
                    break
                if a0_duan_list[x] == -1:
                    break
            if leave - e.end >= 5:
                r = -1
                k = len(low_list)
                if i < len(a0_pivots) - 1:
                    k = a0_pivots[i + 1].start
                for x in range(leave + 1, k):
                    if e_next is not None and x >= e_next.start:
                        break
                    if low_list[x] < e.top and (
                        len(
                            pydash.chain(low_list[e.end + 1 : x])
                            .filter_(lambda a: a > e.top)
                            .value()
                        )
                        > 0
                        or len(
                            pydash.chain(high_list[e.end + 1 : x])
                            .filter_(lambda a: a > e.gg)
                            .value()
                        )
                        > 0
                    ):
                        r = x
                        break
                    if a0_duan_list[x] == -1:
                        break
                if r >= 0:
                    result['idx'].append(r)
                    result['datetime'].append(datetime_list[r])
                    result['time_str'].append(time_str_list[r])
                    result['price'].append(e.top)
                    top_index = pydash.find_last_index(
                        a0_duan_list[: r + 1], lambda a: a == 1
                    )
                    if top_index > -1:
                        result['stop_lose_price'].append(high_list[top_index])
                        stop_win_price = e.top - (high_list[top_index] - e.top)
                        result['stop_win_price'].append(stop_win_price)
                    else:
                        result['stop_lose_price'].append(0)
                        result['stop_win_price'].append(0)
    return result


def down_tu_po(datetime_list, time_str_list, low_list, duan_list, a0_pivots):
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    for i in range(len(a0_pivots)):
        e = a0_pivots[i]
        e_pre = a0_pivots[i - 1] if i > 0 else None
        if e.direction == -1:
            duan_start = pydash.find_last_index(duan_list[: e.start], lambda t: t == 1)
            if e_pre is not None and 0 <= duan_start < e_pre.start:
                continue
            r = -1
            for x in range(e.end + 1, len(low_list)):
                if low_list[x] < e.dd:
                    r = x
                    break
                if duan_list[x] == -1:
                    break
            if r > 0:
                result['idx'].append(r)
                result['datetime'].append(datetime_list[r])
                result['time_str'].append(time_str_list[r])
                result['price'].append(e.dd)
                result['stop_lose_price'].append(e.zd)
    return result


def down_five_v_fan(datetime_list, time_str_list, high_list, low_list, a0_bi_list):
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    for i in range(len(a0_bi_list)):
        if a0_bi_list[i] == 1:
            g1 = i
            d1 = pydash.find_last_index(a0_bi_list[:g1], lambda x: x == -1)
            g2 = pydash.find_last_index(a0_bi_list[:d1], lambda x: x == 1)
            d2 = pydash.find_last_index(a0_bi_list[:g2], lambda x: x == -1)
            g3 = pydash.find_last_index(a0_bi_list[:d2], lambda x: x == 1)
            d3 = pydash.find_last_index(a0_bi_list[:g3], lambda x: x == -1)
            if (
                d3 >= 0
                and high_list[g1] > high_list[g2] > high_list[g3]
                and low_list[d1] > low_list[d2] > low_list[d3]
                and low_list[d1] > high_list[g3]
            ):
                for k in range(i + 1, len(a0_bi_list)):
                    if low_list[k] < low_list[d1]:
                        if (
                            pydash.find_last_index(
                                result['time_str'], lambda x: x == time_str_list[k]
                            )
                            == -1
                        ):
                            result['idx'].append(k)
                            result['datetime'].append(datetime_list[k])
                            result['time_str'].append(time_str_list[k])
                            result['price'].append(low_list[d1])
                            result['stop_lose_price'].append(high_list[g1])
                        break
                    if a0_bi_list[k] == -1:
                        break
    return result


def down_v_reverse(
    datetime_list,
    time_str_list,
    high_list,
    low_list,
    a0_bi_list,
    a0_duan_list,
    a0_pivots,
):
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    count = len(time_str_list)
    for i in range(len(a0_pivots)):
        e = a0_pivots[i]
        next_e = a0_pivots[i + 1] if i < len(a0_pivots) - 1 else None
        if e.direction == 1:
            # 离开中枢后的第一段结束
            leave_end_index = -1
            for x in range(e.end + 1, count):
                if a0_duan_list[x] == 1:
                    leave_end_index = x
                    break
                if next_e is not None and x >= next_e.start:
                    break
            if leave_end_index >= 0:
                # 存在强3买
                buy3 = False
                resist_index = -1
                resist_price = 0
                for j in range(e.end + 1, leave_end_index):
                    if a0_bi_list[j] == -1 and low_list[j] > e.gg:
                        buy3 = True
                        resist_index = j
                        resist_price = low_list[resist_index]
                        break
                if buy3:
                    for k in range(leave_end_index + 1, len(low_list)):
                        if a0_bi_list[k] == -1:
                            break
                        if low_list[k] < resist_price:
                            if (
                                pydash.find_last_index(
                                    result['time_str'], lambda x: x == time_str_list[k]
                                )
                                == -1
                            ):
                                result['idx'].append(k)
                                result['datetime'].append(datetime_list[k])
                                result['time_str'].append(time_str_list[k])
                                result['price'].append(resist_price)
                                result['stop_lose_price'].append(
                                    high_list[leave_end_index]
                                )
                            break
    return result


def down_po_huai(
    datetime_list, time_str_list, high_list, low_list, a0_bi_list, a0_duan_list
):
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    for i in range(len(a0_duan_list)):
        if a0_duan_list[i] == 1:
            anchor = 0
            for j in range(i + 1, len(time_str_list)):
                if a0_duan_list[j] == -1:
                    break
                if a0_bi_list[j] == -1:
                    anchor = j
                    break
            if anchor > 0:
                for k in range(anchor + 1, len(time_str_list)):
                    if a0_duan_list[k] == -1:
                        break
                    if low_list[k] < low_list[anchor]:
                        result['idx'].append(k)
                        result['datetime'].append(datetime_list[k])
                        result['time_str'].append(time_str_list[k])
                        result['price'].append(low_list[anchor])
                        result['stop_lose_price'].append(high_list[i])
                        break
    return result
