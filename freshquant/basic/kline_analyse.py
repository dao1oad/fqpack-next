# -*- coding: utf-8 -*-

from freshquant.basic.bi import calculate_bi
from freshquant.basic.duan import calculate_duan, split_bi_in_duan


def calculate_bi_duan(data_list):
    for idx in range(len(data_list)):
        if idx == 0:
            data = data_list[idx]
            count = len(data["kline_data"])
            bi_list = [0 for i in range(count)]
            duan_list = [0 for i in range(count)]
            duan_list2 = [0 for i in range(count)]
            calculate_bi(
                bi_list,
                list(data["kline_data"]["high"]),
                list(data["kline_data"]["low"]),
                list(data["kline_data"]["open"]),
                data["kline_data"]["close"],
            )
            data["kline_data"]["bi"] = bi_list
            data["kline_data"]["duan"] = duan_list
            data["kline_data"]["duan2"] = duan_list2
        elif idx == 1:
            data2 = data_list[idx - 1]
            data = data_list[idx]
            count = len(data["kline_data"])
            bi_list = [0 for i in range(count)]
            duan_list = [0 for i in range(count)]
            duan_list2 = [0 for i in range(count)]
            calculate_duan(
                duan_list,
                list(data["kline_data"]["time_stamp"]),
                list(data2["kline_data"]["bi"]),
                list(data2["kline_data"]["time_stamp"]),
                list(data["kline_data"]["high"]),
                list(data["kline_data"]["low"]),
            )
            split_bi_in_duan(
                bi_list,
                duan_list,
                list(data["kline_data"]["high"]),
                list(data["kline_data"]["low"]),
                list(data["kline_data"]["open"]),
                list(data["kline_data"]["close"]),
            )
            data["kline_data"]["bi"] = bi_list
            data["kline_data"]["duan"] = duan_list
            data["kline_data"]["duan2"] = duan_list2
        else:
            data3 = data_list[idx - 2]
            data2 = data_list[idx - 1]
            data = data_list[idx]
            count = len(data["kline_data"])
            bi_list = [0 for i in range(count)]
            duan_list = [0 for i in range(count)]
            duan_list2 = [0 for i in range(count)]
            calculate_duan(
                duan_list,
                list(data["kline_data"]["time_stamp"]),
                list(data2["kline_data"]["bi"]),
                list(data2["kline_data"]["time_stamp"]),
                list(data["kline_data"]["high"]),
                list(data["kline_data"]["low"]),
            )
            calculate_duan(
                duan_list2,
                list(data["kline_data"]["time_stamp"]),
                list(data3["kline_data"]["bi"]),
                list(data3["kline_data"]["time_stamp"]),
                list(data["kline_data"]["high"]),
                list(data["kline_data"]["low"]),
            )
            split_bi_in_duan(
                bi_list,
                duan_list,
                list(data["kline_data"]["high"]),
                list(data["kline_data"]["low"]),
                list(data["kline_data"]["open"]),
                list(data["kline_data"]["close"]),
            )
            data["kline_data"]["bi"] = bi_list
            data["kline_data"]["duan"] = duan_list
            data["kline_data"]["duan2"] = duan_list2
    return data_list
