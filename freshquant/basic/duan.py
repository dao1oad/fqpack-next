# -*- coding: utf-8 -*-

from datetime import datetime

import pydash
import pytz

from freshquant.basic.bi import adjust_bi, is_bi
from freshquant.basic.comm import FindNextEq, FindPrevEq

tz = pytz.timezone('Asia/Shanghai')


def CalcDuan(count, duan, bi, high, low):
    firstBiD = FindNextEq(bi, -1, 0, count)
    firstBiG = FindNextEq(bi, 1, 0, count)
    if firstBiD == -1 or firstBiG == -1:
        return
    duan[firstBiD] = -1
    duan[firstBiG] = 1
    i = max(firstBiD, firstBiG) + 1
    for i in range(i, count):
        if bi[i] != 1 and bi[i] != -1:
            continue
        G1 = FindPrevEq(duan, 1, i)
        D1 = FindPrevEq(duan, -1, i)
        if G1 > D1:
            # 最近已确认的线段是向上线段
            if bi[i] == 1:
                # 遇到笔的高点
                if high[i] > high[G1]:
                    # 笔高点创了新高，原线段继续延伸
                    duan[G1] = 0
                    duan[i] = 1
            elif bi[i] == -1:
                # 遇到笔的低点
                if low[i] < low[D1]:
                    # 笔低点反向直接破线段最低点了
                    duan[i] = -1
                else:
                    # i1 反向的第一个低点
                    i1 = FindNextEq(bi, -1, G1 + 1, i)
                    if 0 <= i1 < i:
                        # 前面已出现了反向的第一个低点
                        if low[i] < low[i1]:
                            # 破坏了反向的第一个低点，直接确认线段成立了。
                            duan[i] = -1
                        else:
                            # 没有破坏第一个低点的情况，如果最近的下上下符合线段条件，那么也确认线段的成立。
                            # 处理前面可能有笔可以升级成段的情况。
                            d1 = i
                            g1 = FindPrevEq(bi, 1, d1)
                            d2 = FindPrevEq(bi, -1, g1)
                            g2 = FindPrevEq(bi, 1, d2)
                            if low[d1] < low[d2] and high[g1] <= high[g2]:
                                i2 = i1
                                for x in range(i1, i + 1):
                                    if low[x] < low[i2]:
                                        i2 = x
                                duan[i2] = -1
                                if i2 < i:
                                    i = i2
        else:
            # 最近已确认的线段是向下线段
            if bi[i] == -1:
                # 遇到笔的低点
                if low[i] < low[D1]:
                    # 笔低点创新低，原来线段继续延伸
                    duan[D1] = 0
                    duan[i] = -1
            elif bi[i] == 1:
                # 遇到笔的高点
                if high[i] > high[G1]:
                    # 笔高点直接破前面段高点了，笔升级为段
                    duan[i] = 1
                else:
                    # i1 反向的第一个高点
                    i1 = FindNextEq(bi, 1, D1 + 1, i)
                    if 0 <= i1 < i:
                        if high[i] > high[i1]:
                            # 破坏反向的第一个高点。
                            duan[i] = 1
                        else:
                            # 没有破坏第一个高点的情况，如果最近的上下上符合线段条件，那么也确认线段的成立。
                            # 处理前面可能有笔可以升级成段的情况。
                            g1 = i
                            d1 = FindPrevEq(bi, -1, g1)
                            g2 = FindPrevEq(bi, 1, d1)
                            d2 = FindPrevEq(bi, -1, g2)
                            if high[g1] > high[g2] and low[d1] >= low[d2]:
                                i2 = i1
                                for x in range(i1, i + 1):
                                    if high[x] > high[i2]:
                                        i2 = x
                                duan[i2] = 1
                                if i2 < i:
                                    i = i2


def calc_duan_exp(
    bi_list,
    time_index_list,
    bi_list_big_level,
    time_index_list_big_level,
    high_list,
    low_list,
):
    count = len(bi_list)
    duan_list = [0 for i in range(count)]

    idx = 0
    for i in range(len(bi_list_big_level)):
        if i < len(time_index_list_big_level) - 1:
            big_t2 = time_index_list_big_level[i + 1]
        else:
            big_t2 = datetime.now(tz=tz).timestamp()
        if bi_list_big_level[i] == 1:
            h = high_list[idx]
            x = idx
            for x in range(idx, count):
                if time_index_list[x] < big_t2:
                    if high_list[x] >= h:
                        h = high_list[x]
                        idx = x
                else:
                    break
            duan_list[idx] = 1
            bi_list[idx] = 1
        elif bi_list_big_level[i] == -1:
            l = low_list[idx]
            x = idx
            for x in range(idx, count):
                if time_index_list[x] < big_t2:
                    if low_list[x] <= l:
                        l = low_list[x]
                        idx = x
                else:
                    break
            duan_list[idx] = -1
            bi_list[idx] = -1
    for x in range(len(duan_list)):
        if duan_list[x] == 1:
            g_idx = x
            d_idx = pydash.find_last_index(duan_list[:x], lambda v: v == -1)
            if d_idx >= 0:
                l_idx = 0
                direction = 0
                for y in range(d_idx, g_idx):
                    if bi_list[y] == 1:
                        if direction == 1:
                            if high_list[y] >= high_list[l_idx]:
                                bi_list[l_idx] = 0
                                l_idx = y
                            else:
                                bi_list[y] = 0
                        direction = 1
                    if bi_list[y] == -1:
                        if direction == -1:
                            if low_list[y] <= low_list[l_idx]:
                                bi_list[l_idx] = 0
                                l_idx = y
                            else:
                                bi_list[y] = 0
                        direction = -1
        elif duan_list[x] == -1:
            d_idx = x
            g_idx = pydash.find_last_index(duan_list[:x], lambda v: v == 1)
            if g_idx >= 0:
                l_idx = 0
                direction = 0
                for y in range(g_idx, d_idx):
                    if bi_list[y] == 1:
                        if direction == 1:
                            if high_list[y] >= high_list[l_idx]:
                                bi_list[l_idx] = 0
                                l_idx = y
                            else:
                                bi_list[y] = 0
                        direction = 1
                    if bi_list[y] == -1:
                        if direction == -1:
                            if low_list[y] <= low_list[l_idx]:
                                bi_list[l_idx] = 0
                                l_idx = y
                            else:
                                bi_list[y] = 0
                        direction = -1
    return duan_list


def calculate_duan(duan_list, time_list, bi_list2, time_list2, high_list, low_list):
    count = len(duan_list)
    idx = 0
    for i in range(len(bi_list2)):
        if i < len(time_list2) - 1:
            big_t2 = time_list2[i + 1]
        else:
            big_t2 = datetime.now(tz=tz).timestamp()
        if bi_list2[i] == 1:
            h = high_list[idx]
            x = idx
            for x in range(idx, count):
                if time_list[x] < big_t2:
                    if high_list[x] >= h:
                        h = high_list[x]
                        idx = x
                else:
                    break
            duan_list[idx] = 1
        elif bi_list2[i] == -1:
            l = low_list[idx]
            x = idx
            for x in range(idx, count):
                if time_list[x] < big_t2:
                    if low_list[x] <= l:
                        l = low_list[x]
                        idx = x
                else:
                    break
            duan_list[idx] = -1


def split_bi_in_duan(bi_list, duan_list, high_list, low_list, open_list, close_list):
    for i in range(len(bi_list)):
        d1 = pydash.find_last_index(bi_list[:i], lambda value: value == -1)
        g1 = pydash.find_last_index(bi_list[:i], lambda value: value == 1)
        if duan_list[i] == 1:
            if g1 > d1:
                bi_list[g1] = 0
            bi_list[i] = 1
        elif duan_list[i] == -1:
            if d1 > g1:
                bi_list[d1] = 0
            bi_list[i] = -1
        else:
            if d1 > g1:
                # 前面是向下笔
                if low_list[i] < low_list[d1]:
                    bi_list[d1] = 0
                    bi_list[i] = -1
                    i = adjust_bi(bi_list, high_list, low_list, g1, i)
                else:
                    max_high = max(high_list[d1:i])
                    if high_list[i] > max_high:
                        if is_bi(
                            bi_list,
                            high_list,
                            low_list,
                            open_list,
                            close_list,
                            d1,
                            i,
                            1,
                        ):
                            bi_list[i] = 1
            elif g1 > d1:
                # 前面是向上笔
                if high_list[i] > high_list[g1]:
                    bi_list[g1] = 0
                    bi_list[i] = 1
                    i = adjust_bi(bi_list, high_list, low_list, d1, i)
                else:
                    min_low = min(low_list[g1:i])
                    if low_list[i] < min_low:
                        if is_bi(
                            bi_list,
                            high_list,
                            low_list,
                            open_list,
                            close_list,
                            g1,
                            i,
                            -1,
                        ):
                            bi_list[i] = -1
