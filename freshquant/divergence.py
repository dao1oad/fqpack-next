# -*- coding: utf-8 -*-

import datetime

import numpy as np
import pydash

from freshquant import Duan
from freshquant.basic.bi import CalcBiList

'''
     High 高级别 H
     Sell  顶 S
     Buy   底 B
     Xian   黄白线 X
     Ji     面积 J
'''
signalMap = {
    '高级别线底背': 'HXB',
    '线底背': 'XB',
    '笔内线底背': 'BI-XB',
    '高级别线顶背': 'HXT',
    '线顶背': 'XS',
    '笔内线顶背': 'BI-XS',
    '高级别积底背': 'HJB',
    '积底背': 'JB',
    '高级别积顶背': 'HJT',
    '积顶背': 'JS',
}


def calc_beichi_data(x_data, xx_data, ma5=None, ma20=None):
    divergence_down, divergence_up, above_big_macd = calc_divergence(x_data, xx_data)
    bi_list = list(x_data['bi'])
    duan_list = list(x_data['duan'])
    time_list = list(x_data['time_stamp'])
    high_list = list(x_data['high'])
    low_list = list(x_data['low'])
    open_list = list(x_data['open'])
    close_list = list(x_data['close'])
    diff_list = list(x_data['diff'])
    return note(
        divergence_down,
        divergence_up,
        bi_list,
        duan_list,
        time_list,
        high_list,
        low_list,
        open_list,
        close_list,
        diff_list,
        ma5,
        ma20,
        above_big_macd,
    )


def calc_divergence(x_data, xx_data):
    length = len(x_data)
    bi_list = CalcBiList(length, x_data['bi'], x_data['high'], x_data['low'])
    # 底背驰信号
    divergence_down = np.zeros(length)
    # 顶背驰信号
    divergence_up = np.zeros(length)
    above_big_macd = [False for i in range(length)]
    bi_signal_list = list(x_data['bi'])
    gold_cross = list(x_data['jc'])
    dead_cross = list(x_data['sc'])
    time_list = list(x_data['time_stamp'])
    diff_list = list(x_data['diff'])
    dea_list = list(x_data['dea'])
    duan_list = list(x_data['duan'])
    high_list = list(x_data['high'])
    low_list = list(x_data['low'])
    close_list = list(x_data['close'])

    time_list_big = list(xx_data['time_stamp'])
    diff_list_big = list(xx_data['diff'])
    dea_list_big = list(xx_data['dea'])
    big_idx = 0
    for i in range(len(gold_cross)):
        if gold_cross[i] and diff_list[i] < 0:
            k = pydash.find_index(
                time_list_big[big_idx:], lambda value: value >= time_list[i]
            )
            big_idx = big_idx + k
            if big_idx > 0 and (
                diff_list_big[big_idx] < 0 or dea_list_big[big_idx] < 0
            ):
                big_direction = -1
                above_big_macd[i] = False
            else:
                big_direction = 1
                above_big_macd[i] = True
            info = Duan.inspect(
                duan_list, high_list, low_list, close_list, diff_list, dea_list, i
            )
            if info is not None:
                if info['duan_type'] == -1:
                    duan_start = info['duan_start']
                    duan_end = info['duan_end']
                    if duan_end - duan_start < 96 or duan_end - duan_start > 240:
                        break
                    down_bi_list = pydash.filter_(
                        bi_list,
                        lambda bi: bi["direction"] == -1
                        and bi["start"] <= duan_end
                        and bi["end"] >= duan_start,
                    )
                    # 要创新低的向下笔
                    target_bi_list = []
                    for k in range(len(down_bi_list)):
                        if len(target_bi_list) == 0:
                            target_bi_list.append(down_bi_list[k])
                        elif (
                            low_list[down_bi_list[k]['end']]
                            < low_list[target_bi_list[-1]['end']]
                        ):
                            target_bi_list.append(down_bi_list[k])
                    down_bi_list = target_bi_list
                    if len(down_bi_list) > 1:
                        if big_direction == 1:
                            # 大级别在0轴上，2笔就可以
                            if len(down_bi_list) < 2:
                                continue
                            down_bi_list = down_bi_list[-2:]
                        else:
                            # 大级别在0轴下，要3笔
                            if len(down_bi_list) < 3:
                                continue
                            down_bi_list = down_bi_list[-3:]
                        diff1 = np.amin(diff_list[down_bi_list[-1]['start'] : i + 1])
                        x = down_bi_list[-2]['end']
                        for y in range(
                            down_bi_list[-2]['end'], down_bi_list[-1]['start']
                        ):
                            if gold_cross[y]:
                                x = y
                        diff2 = np.amin(diff_list[down_bi_list[-2]['start'] : x + 1])
                        if diff1 > diff2:
                            # 前面是向下段，才是背驰点
                            # 要向下段后的第一次金叉
                            if info['duan_end'] == i:
                                divergence_down[i] = 1
                            elif (
                                len(
                                    pydash.filter_(
                                        gold_cross[info['duan_end'] : i],
                                        lambda value: value == 1,
                                    )
                                )
                                == 0
                            ):
                                divergence_down[i] = 1
            # 查看有没有笔内背驰
            if divergence_down[i] != 1:
                if big_direction == 1:
                    bi_e = pydash.find_last_index(
                        bi_signal_list[: i + 1], lambda value: value == -1 or value == 1
                    )
                    if bi_e > 0 and bi_signal_list[bi_e] == -1:
                        if (
                            len(
                                pydash.filter_(
                                    gold_cross[bi_e:i], lambda value: value == 1
                                )
                            )
                            == 0
                        ):
                            bi_s = pydash.find_last_index(
                                bi_signal_list[:bi_e], lambda value: value == 1
                            )
                            if bi_s >= 0 and 96 < bi_e - bi_s < 240:
                                temp_idx = bi_e
                                while temp_idx >= bi_s:
                                    k = pydash.find_last_index(
                                        gold_cross[bi_s:temp_idx],
                                        lambda value: value == 1,
                                    )
                                    if k >= 0 and diff_list[bi_s + k] < diff_list[i]:
                                        divergence_down[i] = 1
                                        break
                                    temp_idx = bi_s + k
    big_idx = 0
    for i in range(len(dead_cross)):
        if dead_cross[i] and diff_list[i] > 0:
            k = pydash.find_index(
                time_list_big[big_idx:], lambda value: value >= time_list[i]
            )
            big_idx = big_idx + k
            if big_idx > 0 and (
                diff_list_big[big_idx] < 0 or dea_list_big[big_idx] < 0
            ):
                big_direction = -1
                above_big_macd[i] = False
            else:
                big_direction = 1
                above_big_macd[i] = True
            info = Duan.inspect(
                duan_list, high_list, low_list, close_list, diff_list, dea_list, i
            )
            if info is not None:
                if info['duan_type'] == 1:
                    duan_start = info['duan_start']
                    duan_end = info['duan_end']
                    if duan_end - duan_start < 96 or duan_end - duan_start > 240:
                        break
                    up_bi_list = pydash.filter_(
                        bi_list,
                        lambda bi: bi["direction"] == 1
                        and bi["start"] <= duan_end
                        and bi["end"] >= duan_start,
                    )
                    target_bi_list = []
                    for k in range(len(up_bi_list)):
                        if len(target_bi_list) == 0:
                            target_bi_list.append(up_bi_list[k])
                        elif (
                            high_list[up_bi_list[k]['end']]
                            > high_list[target_bi_list[-1]['end']]
                        ):
                            target_bi_list.append(up_bi_list[k])
                    up_bi_list = target_bi_list
                    if len(up_bi_list) > 1:
                        if big_direction == -1:
                            # 大级别在0轴下，2笔就可以
                            if len(up_bi_list) < 2:
                                continue
                            up_bi_list = up_bi_list[-2:]
                        else:
                            # 大级别在0轴上，要3笔
                            if len(up_bi_list) < 3:
                                continue
                            up_bi_list = up_bi_list[-3:]
                        diff1 = np.amax(diff_list[up_bi_list[-1]['start'] : i + 1])
                        x = up_bi_list[-2]['end']
                        for y in range(up_bi_list[-2]['end'], up_bi_list[-1]['start']):
                            if dead_cross[y]:
                                x = y
                        diff2 = np.amax(diff_list[up_bi_list[-2]['start'] : x + 1])
                        if diff1 < diff2:
                            # 前面是向上段，才是背驰点
                            # 要向上段后的第一次死叉
                            if info['duan_end'] == i:
                                divergence_up[i] = 1
                            elif (
                                len(
                                    pydash.filter_(
                                        dead_cross[info['duan_end'] : i],
                                        lambda value: value == 1,
                                    )
                                )
                                == 0
                            ):
                                divergence_up[i] = 1
            # 查看有没有笔内背驰
            if divergence_up[i] != 1:
                if big_direction == -1:
                    bi_e = pydash.find_last_index(
                        bi_signal_list[: i + 1], lambda value: value == -1 or value == 1
                    )
                    if bi_e > 0 and bi_signal_list[bi_e] == 1:
                        if (
                            len(
                                pydash.filter_(
                                    dead_cross[bi_e:i], lambda value: value == 1
                                )
                            )
                            == 0
                        ):
                            bi_s = pydash.find_last_index(
                                bi_signal_list[:bi_e], lambda value: value == -1
                            )
                            if bi_s >= 0 and 96 < bi_e - bi_s < 240:
                                temp_idx = bi_e
                                while temp_idx >= bi_s:
                                    k = pydash.find_last_index(
                                        dead_cross[bi_s:temp_idx],
                                        lambda value: value == 1,
                                    )
                                    if k >= 0 and diff_list[bi_s + k] > diff_list[i]:
                                        divergence_up[i] = 1
                                        break
                                    temp_idx = bi_s + k
    return divergence_down, divergence_up, above_big_macd


def note(
    divergence_down,
    divergence_up,
    bi_list,
    duan_list,
    time_list,
    high_list,
    low_list,
    open_list,
    close_list,
    diff_list,
    ma5,
    ma20,
    above_big_macd,
):
    data = {
        'buyMACDBCData': {
            'date': [],
            'data': [],
            'value': [],
            'stop_lose_price': [],
            'diff': [],
            'stop_win_price': [],
            'tag': [],
            'above_ma5': [],
            'above_ma20': [],
            'above_big_macd': [],
        },
        'sellMACDBCData': {
            'date': [],
            'data': [],
            'value': [],
            'stop_lose_price': [],
            'diff': [],
            'stop_win_price': [],
            'tag': [],
            'above_ma5': [],
            'above_ma20': [],
            'above_big_macd': [],
        },
    }
    for i in range(len(divergence_down)):
        if divergence_down[i] == 1:
            data['buyMACDBCData']['date'].append(
                datetime.datetime.fromtimestamp(time_list[i]).strftime('%Y-%m-%d %H:%M')
            )
            # data属性保持和其他信号统一使用触发背驰的价格 便于前端统一标出开仓横线
            data['buyMACDBCData']['data'].append(open_list[i])
            data['buyMACDBCData']['value'].append(signalMap['线底背'])
            bottom_index = pydash.find_last_index(bi_list[: i + 1], lambda x: x == -1)
            if bottom_index > -1:
                data['buyMACDBCData']['stop_lose_price'].append(low_list[bottom_index])
            else:
                data['buyMACDBCData']['stop_lose_price'].append(0)
            data['buyMACDBCData']['diff'].append(diff_list[i])

            # 底背驰，往后找第一次成笔的位置
            bi_index = pydash.find_index(bi_list[i:], lambda x: x == 1)
            if bi_index > -1:
                data['buyMACDBCData']['stop_win_price'].append(high_list[bi_index])
            else:
                data['buyMACDBCData']['stop_win_price'].append(0)
            data['buyMACDBCData']['tag'].append('')
            above_ma5 = False
            if ma5 is not None:
                t = datetime.datetime.fromtimestamp(time_list[i])
                t = t.replace(hour=0, minute=0).timestamp()
                if t in ma5 and close_list[i] > ma5[t]:
                    above_ma5 = True
            data['buyMACDBCData']['above_ma5'].append(above_ma5)
            above_ma20 = False
            if ma20 is not None:
                t = datetime.datetime.fromtimestamp(time_list[i])
                t = t.replace(hour=0, minute=0).timestamp()
                if t in ma20 and close_list[i] > ma20[t]:
                    above_ma20 = True
            data['buyMACDBCData']['above_ma20'].append(above_ma20)
            data['buyMACDBCData']['above_big_macd'].append(above_big_macd[i])
    for i in range(len(divergence_up)):
        if divergence_up[i] == 1:
            data['sellMACDBCData']['date'].append(
                datetime.datetime.fromtimestamp(time_list[i]).strftime('%Y-%m-%d %H:%M')
            )
            data['sellMACDBCData']['data'].append(open_list[i])
            data['sellMACDBCData']['value'].append(signalMap['线顶背'])
            top_index = pydash.find_last_index(bi_list[: i + 1], lambda x: x == 1)
            if top_index > -1:
                data['sellMACDBCData']['stop_lose_price'].append(high_list[top_index])
            else:
                data['sellMACDBCData']['stop_lose_price'].append(0)
            data['sellMACDBCData']['diff'].append(diff_list[i])

            # 顶背驰，往后找第一次成笔的位置
            bi_index = pydash.find_index(bi_list[i:], lambda x: x == -1)
            if bi_index > -1:
                data['sellMACDBCData']['stop_win_price'].append(low_list[bi_index])
            else:
                data['sellMACDBCData']['stop_win_price'].append(0)
            data['sellMACDBCData']['tag'].append('')
            above_ma5 = True
            if ma5 is not None:
                t = datetime.datetime.fromtimestamp(time_list[i])
                t = t.replace(hour=0, minute=0).timestamp()
                if t in ma5 and close_list[i] < ma5[t]:
                    above_ma5 = False
            data['sellMACDBCData']['above_ma5'].append(above_ma5)
            above_ma20 = True
            if ma20 is not None:
                t = datetime.datetime.fromtimestamp(time_list[i])
                t = t.replace(hour=0, minute=0).timestamp()
                if t in ma20 and close_list[i] < ma20[t]:
                    above_ma5 = False
            data['sellMACDBCData']['above_ma20'].append(above_ma20)
            data['sellMACDBCData']['above_big_macd'].append(above_big_macd[i])
    return data
