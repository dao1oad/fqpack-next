import pydash
from fqchan04 import fq_locate_pivots # type: ignore


def inspect_near_pattern(high, low, duan, trend, cur_idx) -> str:
    vertex = [None] * 4
    idx = 3
    x = trend
    for i in range(cur_idx, -1, -1):
        if x[i] == -1 or x[i] == 1:
            vertex[idx] = i
            idx -= 1
        if idx < 0:
            break
    if idx >= 0:
        x = duan
        for i in range(cur_idx, -1, -1):
            if x[i] == -1 or x[i] == 1:
                vertex[idx] = i
                idx -= 1
            if idx < 0:
                break
    if idx < 0:
        if x[vertex[-1]] == 1:
            if (
                high[vertex[-1]] > high[vertex[-3]]
                and low[vertex[-2]] >= low[vertex[-4]]
            ):
                return "上行"  # 上行
            elif (
                high[vertex[-1]] <= high[vertex[-3]]
                and low[vertex[-2]] < low[vertex[-4]]
            ):
                return "下行"  # 下行
            elif (
                high[vertex[-1]] > high[vertex[-3]]
                and low[vertex[-2]] < low[vertex[-4]]
            ):
                return "扩散"  # 扩散
            else:
                return "收敛"  # 收敛
        elif x[vertex[-1]] == -1:
            if (
                low[vertex[-1]] >= low[vertex[-3]]
                and high[vertex[-2]] > high[vertex[-4]]
            ):
                return "上行"  # 上行
            elif (
                low[vertex[-1]] < low[vertex[-3]]
                and high[vertex[-2]] <= high[vertex[-4]]
            ):
                return "下行"  # 下行
            elif (
                low[vertex[-1]] < low[vertex[-3]]
                and high[vertex[-2]] > high[vertex[-4]]
            ):
                return "扩散"  # 扩散
            else:
                return "收敛"  # 收敛
    return


def la_hui(
    e_list,
    datetime_list,
    time_str_array,
    high_array,
    low_array,
    bi_array,
    duan_array,
    trend=None,
):
    count = len(time_str_array)
    result = {
        "signal_array": [0 for i in range(count)],
        "buy_zs_huila": {
            "idx": [],
            "date": [],
            "datetime": [],
            "time_str": [],
            "data": [],
            "price": [],
            "stop_lose_price": [],
            "stop_win_price": [],
            "tag": [],
            "above_ma5": [],
            "above_ma20": [],
        },
        "sell_zs_huila": {
            "idx": [],
            "date": [],
            "datetime": [],
            "time_str": [],
            "data": [],
            "price": [],
            "stop_lose_price": [],
            "stop_win_price": [],
            "tag": [],
            "above_ma5": [],
            "above_ma20": [],
        },
    }
    for i in range(len(e_list)):
        e = e_list[i]
        e_next = e_list[i + 1] if i + 1 < len(e_list) else None
        if e.direction == 1:
            # 上涨中枢，找第一次的拉回
            # 离开中枢后的第一个笔结束
            leave = e.end
            for x in range(e.end + 1, len(high_array)):
                if high_array[x] > e.gg and bi_array[x] == 1:
                    leave = x
                    break
                if duan_array[x] == -1:
                    break
            if leave - e.end >= 5:
                r = -1
                k = len(low_array)
                if i < len(e_list) - 1:
                    k = e_list[i + 1].start
                for x in range(leave + 1, k):
                    if e_next is not None and x >= e_next.start:
                        break
                    if low_array[x] < e.zg and (
                        len(
                            pydash.chain(low_array[e.end + 1 : x])
                            .filter_(lambda a: a > e.zg)
                            .value()
                        )
                        > 0
                        or len(
                            pydash.chain(high_array[e.end + 1 : x])
                            .filter_(lambda a: a > e.gg)
                            .value()
                        )
                        > 0
                    ):
                        r = x
                        break
                    if low_array[x] < e.gg and (
                        len(
                            pydash.chain(low_array[e.end + 1 : x])
                            .filter_(lambda a: a > e.gg)
                            .value()
                        )
                        > 0
                    ):
                        r = x
                        break
                    if duan_array[x] == -1:
                        break
                if r >= 0:
                    # 判断是不是在向上走势中
                    effective = False
                    duan_start = -1
                    duan_end = -1
                    for pos in range(r, -1, -1):
                        if duan_array[pos] == -1:
                            duan_start = pos
                            break
                    for pos in range(r, -1, -1):
                        if duan_array[pos] == 1:
                            duan_end = pos
                            break
                    pivots = []
                    if duan_end > -1 and duan_start > -1 and duan_end > duan_start:
                        pivots = fq_locate_pivots(bi_array, high_array, low_array, 1, duan_start, duan_end)
                    if len(pivots) > 1:
                        effective = True
                    elif trend:
                        for pos in range(r, -1, -1):
                            if trend[pos] == 1 or trend[pos] == 2:
                                effective = True
                                break
                            if trend[pos] == -1 or trend[pos] == -2:
                                effective = False
                                break
                    if effective:
                        tags = []
                        near_pattern = inspect_near_pattern(
                            high_array, low_array, duan_array, trend, r
                        )
                        if near_pattern:
                            tags.append(near_pattern)
                        result["signal_array"][r] = -1
                        result["sell_zs_huila"]["idx"].append(r)
                        result["sell_zs_huila"]["date"].append(time_str_array[r])
                        result["sell_zs_huila"]["datetime"].append(datetime_list[r])
                        result["sell_zs_huila"]["time_str"].append(time_str_array[r])
                        result["sell_zs_huila"]["data"].append(low_array[r])
                        result["sell_zs_huila"]["price"].append(low_array[r])
                        top_index = pydash.find_last_index(
                            duan_array[: r + 1], lambda a: a == 1
                        )
                        if top_index > -1:
                            result["sell_zs_huila"]["stop_lose_price"].append(
                                high_array[top_index]
                            )
                            stop_win_price = e.top - (high_array[top_index] - e.top)
                            result["sell_zs_huila"]["stop_win_price"].append(
                                stop_win_price
                            )
                        else:
                            result["sell_zs_huila"]["stop_lose_price"].append(0)
                            result["sell_zs_huila"]["stop_win_price"].append(0)
                        result["sell_zs_huila"]["tag"].append(",".join(tags))
        if e.direction == -1:
            # 下跌中枢，找第一次的拉回
            leave = e.end
            for x in range(e.end + 1, len(low_array)):
                if low_array[x] < e.dd and bi_array[x] == -1:
                    leave = x
                    break
                if duan_array[x] == 1:
                    break
            if leave - e.end >= 5:
                r = -1
                for x in range(leave + 1, len(high_array)):
                    if e_next is not None and x >= e_next.start:
                        break
                    if high_array[x] > e.zd and (
                        len(
                            pydash.chain(high_array[e.end + 1 : x])
                            .filter_(lambda a: a < e.zd)
                            .value()
                        )
                        > 0
                        or len(
                            pydash.chain(low_array[e.end + 1 : x])
                            .filter_(lambda a: a < e.dd)
                            .value()
                        )
                        > 0
                    ):
                        r = x
                        break
                    if high_array[x] > e.dd and (
                        len(
                            pydash.chain(high_array[e.end + 1 : x])
                            .filter_(lambda a: a < e.dd)
                            .value()
                        )
                        > 0
                    ):
                        r = x
                        break
                    if duan_array[x] == 1:
                        break
                if r >= 0:
                    # 判断是不是在向下走势中
                    effective = False
                    duan_start = -1
                    duan_end = -1
                    for pos in range(r, -1, -1):
                        if duan_array[pos] == 1:
                            duan_start = pos
                            break
                    for pos in range(r, -1, -1):
                        if duan_array[pos] == -1:
                            duan_end = pos
                            break
                    pivots = []
                    if duan_end> -1 and duan_start > -1 and duan_end > duan_start:
                        pivots = fq_locate_pivots(bi_array, high_array, low_array, -1, duan_start, duan_end)
                    if len(pivots) > 1:
                        effective = True
                    elif trend:
                        for pos in range(r, -1, -1):
                            if trend[pos] == -1 or trend[pos] == -2:
                                effective = True
                                break
                            if trend[pos] == 1 or trend[pos] == 2:
                                effective = False
                                break
                    if effective:
                        tags = []
                        near_pattern = inspect_near_pattern(
                            high_array, low_array, duan_array, trend, r
                        )
                        if near_pattern:
                            tags.append(near_pattern)
                        result["signal_array"][r] = 1
                        result["buy_zs_huila"]["idx"].append(r)
                        result["buy_zs_huila"]["date"].append(time_str_array[r])
                        result["buy_zs_huila"]["datetime"].append(datetime_list[r])
                        result["buy_zs_huila"]["time_str"].append(time_str_array[r])
                        result["buy_zs_huila"]["data"].append(high_array[r])
                        result["buy_zs_huila"]["price"].append(high_array[r])
                        bottom_index = pydash.find_last_index(
                            duan_array[: r + 1], lambda a: a == -1
                        )
                        if bottom_index > -1:
                            result["buy_zs_huila"]["stop_lose_price"].append(
                                low_array[bottom_index]
                            )
                            stop_win_price = e.bottom + (
                                e.bottom - low_array[bottom_index]
                            )
                            result["buy_zs_huila"]["stop_win_price"].append(
                                stop_win_price
                            )
                        else:
                            result["buy_zs_huila"]["stop_lose_price"].append(0)
                            result["buy_zs_huila"]["stop_win_price"].append(0)
                        result["buy_zs_huila"]["tag"].append(",".join(tags))
    return result


def tu_po(
    e_list,
    datetime_list,
    time_series,
    high_series,
    low_series,
    open_series,
    close_series,
    bi_series,
    duan_series,
    trend,
):
    result = {
        "buy_zs_tupo": {
            "idx": [],
            "date": [],
            "datetime": [],
            "time_str": [],
            "data": [],
            "price": [],
            "stop_lose_price": [],
            "stop_win_price": [],
            "tag": [],
            "above_ma5": [],
            "above_ma20": [],
        },
        "sell_zs_tupo": {
            "idx": [],
            "date": [],
            "datetime": [],
            "time_str": [],
            "data": [],
            "price": [],
            "stop_lose_price": [],
            "stop_win_price": [],
            "tag": [],
            "above_ma5": [],
            "above_ma20": [],
        },
    }
    for i in range(len(e_list)):
        e = e_list[i]
        e_pre = e_list[i - 1] if i > 0 else None
        if e.direction == 1:
            duan_start = pydash.find_last_index(
                duan_series[: e.start], lambda t: t == -1
            )
            if duan_start >= 0:
                pre_duan_start = pydash.find_last_index(
                    duan_series[:duan_start], lambda t: t == 1
                )
                if pre_duan_start >= 0:
                    middle_price = (
                        high_series[pre_duan_start] + low_series[duan_start]
                    ) / 2
                    if e.gg > middle_price:
                        continue
            if e_pre is not None and 0 <= duan_start < e_pre.start:
                continue
            r = -1
            for x in range(e.end + 1, len(high_series)):
                if high_series[x] > e.gg:
                    r = x
                    break
                if duan_series[x] == 1:
                    break
            if r > 0:
                effective = True
                if trend:
                    for pos in range(r, -1, -1):
                        if trend[pos] == 1 or trend[pos] == 2:
                            effective = False
                            break
                        if trend[pos] == -1 or trend[pos] == -2:
                            break
                if effective:
                    tags = []
                    near_pattern = inspect_near_pattern(
                        high_series, low_series, duan_series, trend, r
                    )
                    if near_pattern:
                        tags.append(near_pattern)
                    result["buy_zs_tupo"]["idx"].append(r)
                    result["buy_zs_tupo"]["date"].append(time_series[r])
                    result["buy_zs_tupo"]["datetime"].append(datetime_list[r])
                    result["buy_zs_tupo"]["time_str"].append(time_series[r])
                    result["buy_zs_tupo"]["data"].append(e.gg)
                    result["buy_zs_tupo"]["price"].append(e.gg)
                    result["buy_zs_tupo"]["stop_lose_price"].append(e.zg)
                    result["buy_zs_tupo"]["tag"].append(",".join(tags))
        if e.direction == -1:
            duan_start = pydash.find_last_index(
                duan_series[: e.start], lambda t: t == 1
            )
            if duan_start >= 0:
                pre_duan_start = pydash.find_last_index(
                    duan_series[:duan_start], lambda t: t == -1
                )
                if pre_duan_start >= 0:
                    middle_price = (
                        low_series[pre_duan_start] + high_series[duan_start]
                    ) / 2
                    if e.gg < middle_price:
                        continue
            if e_pre is not None and 0 <= duan_start < e_pre.start:
                continue
            r = -1
            for x in range(e.end + 1, len(low_series)):
                if low_series[x] < e.dd:
                    r = x
                    break
                if duan_series[x] == -1:
                    break
            if r > 0:
                effective = True
                if trend:
                    for pos in range(r, -1, -1):
                        if trend[pos] == -1 or trend[pos] == -2:
                            effective = False
                            break
                        if trend[pos] == 1 or trend[pos] == 2:
                            break
                tags = []
                near_pattern = inspect_near_pattern(
                    high_series, low_series, duan_series, trend, r
                )
                if near_pattern:
                    tags.append(near_pattern)
                result["sell_zs_tupo"]["idx"].append(r)
                result["sell_zs_tupo"]["date"].append(time_series[r])
                result["sell_zs_tupo"]["datetime"].append(datetime_list[r])
                result["sell_zs_tupo"]["time_str"].append(time_series[r])
                result["sell_zs_tupo"]["data"].append(e.dd)
                result["sell_zs_tupo"]["price"].append(e.dd)
                result["sell_zs_tupo"]["stop_lose_price"].append(e.zd)
                result["sell_zs_tupo"]["tag"].append(",".join(tags))
    return result


def five_v_fan(
    datetime_list, time_series, duan_series, bi_series, high_series, low_series, trend
):
    result = {
        "sell_five_v_reverse": {
            "idx": [],
            "date": [],
            "datetime": [],
            "time_str": [],
            "data": [],
            "price": [],
            "stop_lose_price": [],
            "stop_win_price": [],
            "tag": [],
            "above_ma5": [],
            "above_ma20": [],
        },
        "buy_five_v_reverse": {
            "idx": [],
            "date": [],
            "datetime": [],
            "time_str": [],
            "data": [],
            "price": [],
            "stop_lose_price": [],
            "stop_win_price": [],
            "tag": [],
            "above_ma5": [],
            "above_ma20": [],
        },
    }
    for i in range(len(bi_series)):
        if bi_series[i] == 1:
            g1 = i
            d1 = pydash.find_last_index(bi_series[:g1], lambda x: x == -1)
            g2 = pydash.find_last_index(bi_series[:d1], lambda x: x == 1)
            d2 = pydash.find_last_index(bi_series[:g2], lambda x: x == -1)
            g3 = pydash.find_last_index(bi_series[:d2], lambda x: x == 1)
            d3 = pydash.find_last_index(bi_series[:g3], lambda x: x == -1)
            if (
                d3 >= 0
                and high_series[g1] > high_series[g2] > high_series[g3]
                and low_series[d1] > low_series[d2] > low_series[d3]
                and low_series[d1] > high_series[g3]
            ):
                for k in range(i + 1, len(bi_series)):
                    if low_series[k] < low_series[d1]:
                        # v fan
                        if (
                            pydash.find_last_index(
                                result["sell_five_v_reverse"]["date"],
                                lambda x: x == time_series[k],
                            )
                            == -1
                        ):
                            effective = True
                            if trend:
                                for pos in range(k, -1, -1):
                                    if trend[pos] == -1 or trend[pos] == -2:
                                        effective = False
                                        break
                                    if trend[pos] == 1 or trend[pos] == 2:
                                        break
                            if effective:
                                tags = []
                                near_pattern = inspect_near_pattern(
                                    high_series, low_series, duan_series, trend, k
                                )
                                if near_pattern:
                                    tags.append(near_pattern)
                                result["sell_five_v_reverse"]["idx"].append(k)
                                result["sell_five_v_reverse"]["date"].append(
                                    time_series[k]
                                )
                                result["sell_five_v_reverse"]["datetime"].append(
                                    datetime_list[k]
                                )
                                result["sell_five_v_reverse"]["time_str"].append(
                                    time_series[k]
                                )
                                result["sell_five_v_reverse"]["data"].append(
                                    low_series[d1]
                                )
                                result["sell_five_v_reverse"]["price"].append(
                                    low_series[d1]
                                )
                                result["sell_five_v_reverse"]["stop_lose_price"].append(
                                    high_series[g1]
                                )
                                result["sell_five_v_reverse"]["tag"].append(
                                    ",".join(tags)
                                )
                        break
                    if bi_series[k] == -1:
                        break

        elif bi_series[i] == -1:
            d1 = i
            g1 = pydash.find_last_index(bi_series[:d1], lambda x: x == 1)
            d2 = pydash.find_last_index(bi_series[:g1], lambda x: x == -1)
            g2 = pydash.find_last_index(bi_series[:d2], lambda x: x == 1)
            d3 = pydash.find_last_index(bi_series[:g2], lambda x: x == -1)
            g3 = pydash.find_last_index(bi_series[:d3], lambda x: x == 1)
            if (
                g3 >= 0
                and high_series[g1] < high_series[g2] < high_series[g3]
                and low_series[d1] < low_series[d2] < low_series[d3]
                and high_series[g1] < low_series[d3]
            ):
                for k in range(i + 1, len(bi_series)):
                    if high_series[k] > high_series[g1]:
                        # v fan
                        if (
                            pydash.find_last_index(
                                result["buy_five_v_reverse"]["date"],
                                lambda x: x == time_series[k],
                            )
                            == -1
                        ):
                            effective = True
                            if trend:
                                for pos in range(k, -1, -1):
                                    if trend[pos] == 1 or trend[pos] == 2:
                                        effective = False
                                        break
                                    if trend[pos] == -1 or trend[pos] == -2:
                                        break
                            if effective:
                                tags = []
                                near_pattern = inspect_near_pattern(
                                    high_series, low_series, duan_series, trend, k
                                )
                                if near_pattern:
                                    tags.append(near_pattern)
                                result["buy_five_v_reverse"]["idx"].append(k)
                                result["buy_five_v_reverse"]["date"].append(
                                    time_series[k]
                                )
                                result["buy_five_v_reverse"]["datetime"].append(
                                    datetime_list[k]
                                )
                                result["buy_five_v_reverse"]["time_str"].append(
                                    time_series[k]
                                )
                                result["buy_five_v_reverse"]["data"].append(
                                    high_series[g1]
                                )
                                result["buy_five_v_reverse"]["price"].append(
                                    high_series[g1]
                                )
                                result["buy_five_v_reverse"]["stop_lose_price"].append(
                                    low_series[d1]
                                )
                                result["buy_five_v_reverse"]["tag"].append(
                                    ",".join(tags)
                                )
                        break
                    if bi_series[k] == -1:
                        break
    return result


def v_reverse(
    e_list,
    datetime_list,
    time_series,
    high_series,
    low_series,
    open_series,
    close_series,
    bi_series,
    duan_series,
    trend,
):
    result = {
        "buy_v_reverse": {
            "idx": [],
            "date": [],
            "datetime": [],
            "time_str": [],
            "data": [],
            "price": [],
            "stop_lose_price": [],
            "stop_win_price": [],
            "tag": [],
            "above_ma5": [],
            "above_ma20": [],
        },
        "sell_v_reverse": {
            "idx": [],
            "date": [],
            "datetime": [],
            "time_str": [],
            "data": [],
            "price": [],
            "stop_lose_price": [],
            "stop_win_price": [],
            "tag": [],
            "above_ma5": [],
            "above_ma20": [],
        },
    }
    count = len(time_series)
    for i in range(len(e_list)):
        e = e_list[i]
        next_e = e_list[i + 1] if i < len(e_list) - 1 else None
        if e.direction == 1:
            # 离开中枢后的第一段结束
            leave_end_index = -1
            for x in range(e.end + 1, count):
                if duan_series[x] == 1:
                    leave_end_index = x
                    break
                if next_e is not None and x >= next_e.start:
                    break
            if leave_end_index >= 0:
                # 存在强3买
                buy3 = False
                resist_index = -1
                resist_price = 0
                for j in range(leave_end_index, e.end + 1, -1):
                    if bi_series[j] == -1 and low_series[j] > e.zg:
                        buy3 = True
                        resist_index = j
                        resist_price = low_series[resist_index]
                        break
                if buy3:
                    for k in range(leave_end_index + 1, count):
                        if bi_series[k] == -1:
                            break
                        if low_series[k] < resist_price:
                            if (
                                pydash.find_last_index(
                                    result["sell_v_reverse"]["date"],
                                    lambda x: x == time_series[k],
                                )
                                == -1
                            ):
                                effective = True
                                if trend:
                                    for pos in range(k, -1, -1):
                                        if trend[pos] == -1 or trend[pos] == -2:
                                            effective = False
                                            break
                                        if trend[pos] == 1 or trend[pos] == 2:
                                            break
                                if effective:
                                    tags = []
                                    near_pattern = inspect_near_pattern(
                                        high_series, low_series, duan_series, trend, k
                                    )
                                    if near_pattern:
                                        tags.append(near_pattern)
                                    result["sell_v_reverse"]["idx"].append(k)
                                    result["sell_v_reverse"]["date"].append(
                                        time_series[k]
                                    )
                                    result["sell_v_reverse"]["datetime"].append(
                                        datetime_list[k]
                                    )
                                    result["sell_v_reverse"]["time_str"].append(
                                        time_series[k]
                                    )
                                    result["sell_v_reverse"]["data"].append(
                                        resist_price
                                    )
                                    result["sell_v_reverse"]["price"].append(
                                        resist_price
                                    )
                                    result["sell_v_reverse"]["stop_lose_price"].append(
                                        high_series[leave_end_index]
                                    )
                                    result["sell_v_reverse"]["tag"].append(
                                        ",".join(tags)
                                    )
                            break
        if e.direction == -1:
            # 离开中枢后的第一段结束
            leave_end_index = -1
            for x in range(e.end + 1, count):
                if duan_series[x] == -1:
                    leave_end_index = x
                    break
                if next_e is not None and x >= next_e.start:
                    break
            if leave_end_index >= 0:
                # 存在3卖
                sell3 = False
                resist_index = -1
                resist_price = 0
                for j in range(leave_end_index, e.end, -1):
                    if bi_series[j] == 1 and high_series[j] < e.zd:
                        sell3 = True
                        resist_index = j
                        resist_price = high_series[resist_index]
                        break
                if sell3:
                    for k in range(leave_end_index + 1, count):
                        if bi_series[k] == 1:
                            break
                        if high_series[k] > resist_price:
                            if (
                                pydash.find_last_index(
                                    result["buy_v_reverse"]["date"],
                                    lambda x: x == time_series[k],
                                )
                                == -1
                            ):
                                effective = True
                                if trend:
                                    for pos in range(k, -1, -1):
                                        if trend[pos] == 1 or trend[pos] == 2:
                                            effective = False
                                            break
                                        if trend[pos] == -1 or trend[pos] == -2:
                                            break
                                if effective:
                                    tags = []
                                    near_pattern = inspect_near_pattern(
                                        high_series, low_series, duan_series, trend, k
                                    )
                                    if near_pattern:
                                        tags.append(near_pattern)
                                    result["buy_v_reverse"]["idx"].append(k)
                                    result["buy_v_reverse"]["date"].append(
                                        time_series[k]
                                    )
                                    result["buy_v_reverse"]["datetime"].append(
                                        datetime_list[k]
                                    )
                                    result["buy_v_reverse"]["time_str"].append(
                                        time_series[k]
                                    )
                                    result["buy_v_reverse"]["data"].append(resist_price)
                                    result["buy_v_reverse"]["price"].append(
                                        resist_price
                                    )
                                    result["buy_v_reverse"]["stop_lose_price"].append(
                                        low_series[leave_end_index]
                                    )
                                    result["buy_v_reverse"]["tag"].append(
                                        ",".join(tags)
                                    )
                            break
    return result


def po_huai(
    datetime_list,
    time_series,
    high_series,
    low_series,
    open_series,
    close_series,
    bi_series,
    duan_series,
    trend,
):
    result = {
        "buy_duan_break": {
            "idx": [],
            "date": [],
            "datetime": [],
            "time_str": [],
            "data": [],
            "price": [],
            "stop_lose_price": [],
            "stop_win_price": [],
            "tag": [],
            "above_ma5": [],
            "above_ma20": [],
        },
        "sell_duan_break": {
            "idx": [],
            "date": [],
            "datetime": [],
            "time_str": [],
            "data": [],
            "price": [],
            "stop_lose_price": [],
            "stop_win_price": [],
            "tag": [],
            "above_ma5": [],
            "above_ma20": [],
        },
    }
    for i in range(len(duan_series)):
        if duan_series[i] == 1:
            anchor = 0
            for j in range(i + 1, len(time_series)):
                if duan_series[j] == -1:
                    break
                if bi_series[j] == -1:
                    anchor = j
                    break
            if anchor > 0:
                bi_num = 0
                for k in range(anchor + 1, len(time_series)):
                    if low_series[k] < low_series[anchor]:
                        effective = False
                        duan_start = -1
                        duan_end = i
                        for pos in range(i, -1, -1):
                            if duan_series[pos] == -1:
                                duan_start = pos
                                break
                        pivots = []
                        if duan_start > -1 and duan_end > duan_start:
                            pivots = fq_locate_pivots(bi_series, high_series, low_series, 1, duan_start, duan_end)
                        if len(pivots) > 1:
                            effective = True
                        elif trend:
                            for pos in range(k, -1, -1):
                                if trend[pos] == 1 or trend[pos] == 2:
                                    effective = True
                                    break
                                if trend[pos] == -1 or trend[pos] == -2:
                                    effective = False
                                    break
                        if effective:
                            tags = []
                            near_pattern = inspect_near_pattern(
                                high_series, low_series, duan_series, trend, k
                            )
                            if near_pattern:
                                tags.append(near_pattern)
                            result["sell_duan_break"]["idx"].append(k)
                            result["sell_duan_break"]["date"].append(time_series[k])
                            result["sell_duan_break"]["datetime"].append(
                                datetime_list[k]
                            )
                            result["sell_duan_break"]["time_str"].append(time_series[k])
                            result["sell_duan_break"]["data"].append(low_series[anchor])
                            result["sell_duan_break"]["price"].append(
                                low_series[anchor]
                            )
                            result["sell_duan_break"]["stop_lose_price"].append(
                                high_series[i]
                            )
                            result["sell_duan_break"]["tag"].append(",".join(tags))
                        break
                    if bi_series[k] == -1:
                        bi_num += 1
                        if bi_num >= 1:
                            break
                    if duan_series[k] == -1:
                        break
        elif duan_series[i] == -1:
            anchor = 0
            for j in range(i + 1, len(time_series)):
                if duan_series[j] == 1:
                    break
                if bi_series[j] == 1:
                    anchor = j
                    break
            if anchor > 0:
                bi_num = 0
                for k in range(anchor + 1, len(time_series)):
                    if high_series[k] > high_series[anchor]:
                        effective = False
                        duan_start = -1
                        duan_end = i
                        for pos in range(i, -1, -1):
                            if duan_series[pos] == 1:
                                duan_start = pos
                                break
                        pivots = []
                        if duan_start > -1 and duan_end > duan_start:
                            pivots = fq_locate_pivots(bi_series, high_series, low_series, -1, duan_start, duan_end)
                        if len(pivots) > 1:
                            effective = True
                        elif trend:
                            for pos in range(k, -1, -1):
                                if trend[pos] == -1 or trend[pos] == -2:
                                    effective = True
                                    break
                                if trend[pos] == 1 or trend[pos] == 2:
                                    effective = False
                                    break
                        if effective:
                            tags = []
                            near_pattern = inspect_near_pattern(
                                high_series, low_series, duan_series, trend, k
                            )
                            if near_pattern:
                                tags.append(near_pattern)
                            result["buy_duan_break"]["idx"].append(k)
                            result["buy_duan_break"]["date"].append(time_series[k])
                            result["buy_duan_break"]["datetime"].append(
                                datetime_list[k]
                            )
                            result["buy_duan_break"]["time_str"].append(time_series[k])
                            result["buy_duan_break"]["data"].append(high_series[anchor])
                            result["buy_duan_break"]["price"].append(
                                high_series[anchor]
                            )
                            result["buy_duan_break"]["stop_lose_price"].append(
                                low_series[i]
                            )
                            result["buy_duan_break"]["tag"].append(",".join(tags))
                        break
                    if bi_series[k] == 1:
                        bi_num += 1
                        if bi_num >= 1:
                            break
                    if duan_series[k] == 1:
                        break
    return result

if __name__ == "__main__":
    pass