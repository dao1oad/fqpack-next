import pydash


def rise_break_pivot_gg(
    datetime_list, time_str_list, high_list, duan_list, pivot_list, higher_duan_list
):
    '''
    向上突破中枢高高
    '''
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    for i in range(len(pivot_list)):
        pivot = pivot_list[i]
        pre_pivot = pivot_list[i - 1] if i > 0 else None
        duan_start = pydash.find_last_index(duan_list[: pivot.start], lambda v: v == -1)
        if pre_pivot is not None and 0 <= duan_start < pre_pivot.start:
            continue
        r = -1
        for x in range(pivot.end + 1, len(high_list)):
            if high_list[x] > pivot.gg:
                r = x
                break
            if duan_list[x] == 1:
                break
        if r > 0:
            peak = 0
            peak1 = 0
            peak2 = 0
            peak1_index = pydash.find_last_index(higher_duan_list[:r], lambda v: v == 1)
            peak2_index = pydash.find_last_index(duan_list[:r], lambda v: v == 1)
            if peak1_index >= 0:
                peak1 = high_list[peak1_index]
            if peak2_index >= 0:
                peak2 = high_list[peak2_index]
            peak = max(peak1, peak2)
            if peak <= 0:
                peak = pydash.max_(high_list[:r])
            if peak * 0.7 > high_list[r]:
                result['idx'].append(r)
                result['datetime'].append(datetime_list[r])
                result['time_str'].append(time_str_list[r])
                result['price'].append(pivot.gg)
                result['stop_lose_price'].append(pivot.zg)
    return result


def rise_break_pivot_zg(
    datetime_list,
    time_str_list,
    high_list,
    low_list,
    duan_list,
    pivot_list,
    higher_duan_list,
):
    '''
    向上突破中枢高
    '''
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    for i in range(len(pivot_list)):
        pivot = pivot_list[i]
        pre_pivot = pivot_list[i - 1] if i > 0 else None
        duan_start = pydash.find_last_index(duan_list[: pivot.start], lambda v: v == -1)
        if pre_pivot is not None and 0 <= duan_start < pre_pivot.start:
            continue
        r = -1
        state = 0
        for x in range(pivot.end + 1, len(high_list)):
            if state == 0 and low_list[x] <= pivot.zg:
                state = 1
            if state == 1 and high_list[x] > pivot.zg:
                r = x
                break
            if duan_list[x] == 1:
                break
        if r > 0:
            peak = 0
            peak1 = 0
            peak2 = 0
            peak1_index = pydash.find_last_index(higher_duan_list[:r], lambda v: v == 1)
            peak2_index = pydash.find_last_index(duan_list[:r], lambda v: v == 1)
            if peak1_index >= 0:
                peak1 = high_list[peak1_index]
            if peak2_index >= 0:
                peak2 = high_list[peak2_index]
            peak = max(peak1, peak2)
            if peak <= 0:
                peak = pydash.max_(high_list[:r])
            if peak * 0.7 > high_list[r]:
                result['idx'].append(r)
                result['datetime'].append(datetime_list[r])
                result['time_str'].append(time_str_list[r])
                result['price'].append(pivot.gg)
                result['stop_lose_price'].append(pivot.zg)
    return result


def rise_break_pivot_zm(
    datetime_list,
    time_str_list,
    high_list,
    low_list,
    duan_list,
    pivot_list,
    higher_duan_list,
):
    '''
    向上突破中枢中线
    '''
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    for i in range(len(pivot_list)):
        pivot = pivot_list[i]
        pre_pivot = pivot_list[i - 1] if i > 0 else None
        duan_start = pydash.find_last_index(duan_list[: pivot.start], lambda v: v == -1)
        if pre_pivot is not None and 0 <= duan_start < pre_pivot.start:
            continue
        r = -1
        state = 0
        for x in range(pivot.end + 1, len(high_list)):
            if state == 0 and low_list[x] <= (pivot.zg + pivot.zd) / 2:
                state = 1
            if state == 1 and high_list[x] > (pivot.zg + pivot.zd) / 2:
                r = x
                break
            if duan_list[x] == 1:
                break
        if r > 0:
            peak = 0
            peak1 = 0
            peak2 = 0
            peak1_index = pydash.find_last_index(higher_duan_list[:r], lambda v: v == 1)
            peak2_index = pydash.find_last_index(duan_list[:r], lambda v: v == 1)
            if peak1_index >= 0:
                peak1 = high_list[peak1_index]
            if peak2_index >= 0:
                peak2 = high_list[peak2_index]
            peak = max(peak1, peak2)
            if peak <= 0:
                peak = pydash.max_(high_list[:r])
            if peak * 0.7 > high_list[r]:
                result['idx'].append(r)
                result['datetime'].append(datetime_list[r])
                result['time_str'].append(time_str_list[r])
                result['price'].append(pivot.gg)
                result['stop_lose_price'].append(pivot.zg)
    return result


def rise_break_pivot_zd(
    datetime_list,
    time_str_list,
    high_list,
    low_list,
    duan_list,
    pivot_list,
    higher_duan_list,
):
    '''
    向上突破中枢低
    '''
    result = {
        'idx': [],
        'datetime': [],
        'time_str': [],
        'price': [],
        'stop_lose_price': [],
        'stop_win_price': [],
    }
    for i in range(len(pivot_list)):
        pivot = pivot_list[i]
        pre_pivot = pivot_list[i - 1] if i > 0 else None
        duan_start = pydash.find_last_index(duan_list[: pivot.start], lambda v: v == -1)
        if pre_pivot is not None and 0 <= duan_start < pre_pivot.start:
            continue
        r = -1
        state = 0
        for x in range(pivot.end + 1, len(high_list)):
            if state == 0 and low_list[x] <= pivot.zd:
                state = 1
            if state == 1 and high_list[x] > pivot.zd:
                r = x
                break
            if duan_list[x] == 1:
                break
        if r > 0:
            peak = 0
            peak1 = 0
            peak2 = 0
            peak1_index = pydash.find_last_index(higher_duan_list[:r], lambda v: v == 1)
            peak2_index = pydash.find_last_index(duan_list[:r], lambda v: v == 1)
            if peak1_index >= 0:
                peak1 = high_list[peak1_index]
            if peak2_index >= 0:
                peak2 = high_list[peak2_index]
            peak = max(peak1, peak2)
            if peak <= 0:
                peak = pydash.max_(high_list[:r])
            if peak * 0.7 > high_list[r]:
                result['idx'].append(r)
                result['datetime'].append(datetime_list[r])
                result['time_str'].append(time_str_list[r])
                result['price'].append(pivot.gg)
                result['stop_lose_price'].append(pivot.zg)
    return result
