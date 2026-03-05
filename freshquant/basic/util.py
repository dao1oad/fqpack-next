import datetime

import pydash
import pytz  # type: ignore

PERIODS = ["1m", "3m", "5m", "15m", "30m", "60m", "180m", "1d", "3d"]
TZ = pytz.timezone('Asia/Shanghai')


def get_required_period_list(period):
    x = pydash.find_index(PERIODS, lambda value: value == period)
    return pydash.chain(PERIODS[x:]).filter_(lambda _, i: i % 2 == 0).value()


def get_Line_data(time_list, signal_list, high_list, low_list):
    resp = {'data': [], 'date': []}
    for i in range(0, len(time_list), 1):
        if signal_list[i] == 1:
            resp['data'].append(high_list[i])
            resp['date'].append(time_list[i])
        elif signal_list[i] == -1:
            resp['data'].append(low_list[i])
            resp['date'].append(time_list[i])
    return resp


def get_zhong_shu_data(entanglement_list):
    zs_data = []
    zs_flag = []
    for i in range(len(entanglement_list)):
        e = entanglement_list[i]
        if e.direction == -1:
            zs_flag.append(-1)
            zs_data.append(
                [
                    [str_from_timestamp(e.startTime), e.top],
                    [str_from_timestamp(e.endTime), e.bottom],
                ]
            )
        else:
            zs_flag.append(1)
            zs_data.append(
                [
                    [str_from_timestamp(e.startTime), e.bottom],
                    [str_from_timestamp(e.endTime), e.top],
                ]
            )
    return zs_data, zs_flag


def str_from_timestamp(t):
    return datetime.datetime.fromtimestamp(t, tz=TZ).strftime("%Y-%m-%d %H:%M")


def get_period_cache_stamp(period):
    if period == '1m':
        return int(int(datetime.datetime.now().timestamp()) / 10)
    elif period == '3m':
        return int(int(datetime.datetime.now().timestamp()) / 15)
    elif period == '5m':
        return int(int(datetime.datetime.now().timestamp()) / 30)
    elif period == '15m':
        return int(int(datetime.datetime.now().timestamp()) / 60)
    elif period == '30m':
        return int(int(datetime.datetime.now().timestamp()) / 60)
    elif period == '60m':
        return int(int(datetime.datetime.now().timestamp()) / 180)
    else:
        return int(int(datetime.datetime.now().timestamp()) / 3600)
