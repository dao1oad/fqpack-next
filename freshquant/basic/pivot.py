import pydash


def FindPivots(from_idx, to_idx, duan_series, high_series, low_series, direction):
    pivots = []
    if direction == -1:
        start = from_idx
        end = to_idx + 1
        sequence = []
        while True:
            d = pydash.find_index(duan_series[start:end], lambda x: x == -1)
            if d == -1:
                break
            d = start + d
            if d >= to_idx:
                break
            g = pydash.find_index(duan_series[d:end], lambda x: x == 1)
            if g == -1:
                break
            g = d + g
            sequence.append(
                {'start': d, 'end': g, 'low': low_series[d], 'high': high_series[g]}
            )
            start = g
        # 至少有2个特征序列才可能出现中枢
        if len(sequence) >= 2:
            pivot = {'sequence_count': 0}
            for idx in range(len(sequence)):
                if pivot['sequence_count'] == 0:
                    pivot['zg'] = sequence[idx]['high']
                    pivot['gg'] = sequence[idx]['high']
                    pivot['zd'] = sequence[idx]['low']
                    pivot['dd'] = sequence[idx]['low']
                    pivot['start'] = sequence[idx]['start']
                    pivot['end'] = sequence[idx]['end']
                    pivot['sequence_count'] = 1
                elif pivot['sequence_count'] == 1:
                    zg = min(sequence[idx]['high'], pivot['zg'])
                    zd = max(sequence[idx]['low'], pivot['zd'])
                    gg = max(sequence[idx]['high'], pivot['gg'])
                    dd = min(sequence[idx]['low'], pivot['dd'])
                    if zg >= zd:
                        pivot['zg'] = zg
                        pivot['zd'] = zd
                        pivot['gg'] = gg
                        pivot['dd'] = dd
                        pivot['end'] = sequence[idx]['end']
                        pivot['sequence_count'] = pivot['sequence_count'] + 1
                        # 成立中枢
                        pivots.append(pivot)
                    else:
                        pivot = {'sequence_count': 0}
                else:
                    if (
                        sequence[idx]['high'] >= pivot['zd']
                        and sequence[idx]['low'] <= pivot['zg']
                    ):
                        # 中枢继续延伸
                        pivot['end'] = sequence[idx]['end']
                        pivot['sequence_count'] = pivot['sequence_count'] + 1
                    else:
                        pivot = {'sequence_count': 0}
    elif direction == 1:
        start = from_idx
        end = to_idx + 1
        sequence = []
        while True:
            g = pydash.find_index(duan_series[start:end], lambda x: x == 1)
            if g == -1:
                break
            g = start + g
            if g >= to_idx:
                break
            d = pydash.find_index(duan_series[g:end], lambda x: x == -1)
            if d == -1:
                break
            d = g + d
            sequence.append(
                {'start': g, 'end': d, 'low': low_series[d], 'high': high_series[g]}
            )
            start = d
        # 至少有2个特征序列才可能出现中枢
        if len(sequence) >= 2:
            pivot = {'sequence_count': 0}
            for idx in range(len(sequence)):
                if pivot['sequence_count'] == 0:
                    pivot['zg'] = sequence[idx]['high']
                    pivot['gg'] = sequence[idx]['high']
                    pivot['zd'] = sequence[idx]['low']
                    pivot['dd'] = sequence[idx]['low']
                    pivot['start'] = sequence[idx]['start']
                    pivot['end'] = sequence[idx]['end']
                    pivot['sequence_count'] = pivot['sequence_count'] + 1
                elif pivot['sequence_count'] == 1:
                    zg = min(sequence[idx]['high'], pivot['zg'])
                    zd = max(sequence[idx]['low'], pivot['zd'])
                    gg = max(sequence[idx]['high'], pivot['gg'])
                    dd = min(sequence[idx]['low'], pivot['dd'])
                    if zg >= zd:
                        pivot['zg'] = zg
                        pivot['zd'] = zd
                        pivot['zd'] = zd
                        pivot['gg'] = gg
                        pivot['dd'] = dd
                        pivot['end'] = sequence[idx]['end']
                        pivot['sequence_count'] = pivot['sequence_count'] + 1
                        # 成立中枢
                        pivots.append(pivot)
                    else:
                        pivot = {'sequence_count': 0}
                else:
                    if (
                        sequence[idx]['high'] >= pivot['zd']
                        and sequence[idx]['low'] <= pivot['zg']
                    ):
                        # 中枢继续延伸
                        pivot['end'] = sequence[idx]['end']
                        pivot['sequence_count'] = pivot['sequence_count'] + 1
                    else:
                        pivot = {'sequence_count': 0}

    return pivots
