import pydash

from freshquant.basic.comm import FindNextEq, FindPrevEntanglement, FindPrevEq
from freshquant.basic.pivot import FindPivots


# 判断idx前面的形态是不是看多完备形态
def perfect_buy_long(signal_series, high_series, low_series, idx):
    d1 = FindPrevEq(signal_series, -1, idx)
    g1 = FindPrevEq(signal_series, 1, d1)
    d2 = FindPrevEq(signal_series, -1, g1)
    g2 = FindPrevEq(signal_series, 1, d2)
    d3 = FindPrevEq(signal_series, -1, g2)
    if d3 >= 0 and low_series[d2] > low_series[d3] and low_series[d1] > low_series[d3]:
        if low_series[d1] < low_series[idx] and low_series[d1] < min(
            high_series[g1], high_series[g2]
        ):
            return True
    return False


# 判断idx前面的形态是不是看跌完备形态
def perfect_sell_short(signal_series, high_series, low_series, idx):
    g1 = FindPrevEq(signal_series, 1, idx)
    d1 = FindPrevEq(signal_series, -1, g1)
    g2 = FindPrevEq(signal_series, 1, d1)
    d2 = FindPrevEq(signal_series, -1, g2)
    g3 = FindPrevEq(signal_series, 1, d2)
    if (
        g3 >= 0
        and high_series[g2] < high_series[g3]
        and high_series[g1] < high_series[g3]
    ):
        if high_series[g1] > high_series[idx] and high_series[g1] > max(
            low_series[d1], low_series[d2]
        ):
            return True
    return False


"""
判断是不是双盘结构，下跌中的双盘
"""


def DualEntangleForBuyLong(
    duan_series, entanglement_list, higher_entaglement_list, fire_time, fire_price
):
    # 当前级别的中枢
    ent = FindPrevEntanglement(entanglement_list, fire_time)
    # 中枢开始的段
    if ent and ent.direction == -1:
        duan_start = FindPrevEq(duan_series, 1, ent.start)
        duan_end = FindNextEq(duan_series, -1, duan_start, len(duan_series))
        # 段的开始如果在更大级别的中枢，就是双盘
        higher_ent = FindPrevEntanglement(higher_entaglement_list, fire_time)
        if higher_ent and higher_ent.direction == -1 and duan_start > 0:
            if (
                ent.zg >= higher_ent.zd
                and duan_start <= higher_ent.end
                and duan_start >= higher_ent.start
            ):
                if fire_price < (higher_ent.zg + higher_ent.zd) / 2:
                    return True
    return False


"""
判断是不是双盘结构，上涨中的双盘
"""


def DualEntangleForSellShort(
    duan_series, entanglement_list, higher_entaglement_list, fire_time, fire_price
):
    # 当前级别的中枢
    ent = FindPrevEntanglement(entanglement_list, fire_time)
    # 中枢开始的段
    if ent and ent.direction == 1:
        duan_start = FindPrevEq(duan_series, -1, ent.start)
        duan_end = FindNextEq(duan_series, 1, duan_start, len(duan_series))
        # 段的开始如果在更大级别的中枢，就是双盘
        higher_ent = FindPrevEntanglement(higher_entaglement_list, fire_time)
        if higher_ent and higher_ent.direction == 1 and duan_start > 0:
            if (
                ent.zd <= higher_ent.zg
                and duan_start <= higher_ent.end
                and duan_start >= higher_ent.start
            ):
                if fire_price > (higher_ent.zg + higher_ent.zd) / 2:
                    return True
    return False


# 买点的所在形态
def buy_category(higher_duan_series, duan_series, high_series, low_series, idx):
    category = ''
    d1 = FindPrevEq(duan_series, -1, idx)
    g1 = FindPrevEq(duan_series, 1, d1)
    d2 = FindPrevEq(duan_series, -1, g1)
    g2 = FindPrevEq(duan_series, 1, d2)
    d3 = FindPrevEq(duan_series, -1, g2)
    if (
        d3 >= 0
        and low_series[d1] > low_series[d2] > low_series[d3]
        and high_series[g1] > high_series[g2]
        and low_series[d1] > high_series[g2]
    ):
        category = '准三买'
        return category
    dd1 = pydash.find_last_index(
        higher_duan_series[: idx + 1], lambda x: x == -1
    )  # 走势低点
    gg1 = pydash.find_last_index(
        higher_duan_series[: idx + 1], lambda x: x == 1
    )  # 走势高点
    if dd1 > gg1 >= 0:
        # 最后一个确认的是下跌走势
        d1 = (
            dd1
            + 1
            + pydash.find_index(duan_series[dd1 + 1 : idx + 1], lambda x: x == -1)
        )
        c = len(pydash.filter_(duan_series[dd1 + 1 : idx + 1], lambda x: x == -1))
        # 下跌中枢
        pivots = FindPivots(gg1, dd1, duan_series, high_series, low_series, -1)
        if d1 == dd1:
            # 走势低点后面没有线段低点
            category = '一类买'
            for x in range(dd1, len(duan_series)):
                if duan_series[x] == 1:
                    if x < idx and low_series[idx] < high_series[x]:
                        category = '二类买'
                    break
        else:
            # 走势低点后还有线段低点，但是还没有形成新的走势
            if len(pivots) > 0 and low_series[d1] > pivots[-1]['zg']:
                category = '三类买'
            if c == 1:
                category = '二类买'

    elif gg1 > dd1 >= 0:
        # 最后一个确认的是上涨走势
        d1 = gg1 + pydash.find_index(duan_series[gg1 : idx + 1], lambda x: x == -1)
        # 上涨走势高点后面的第一个线段低点
        pivots = FindPivots(dd1, gg1, duan_series, high_series, low_series, 1)
        # 上涨中枢
        c = len(pydash.chain(duan_series[dd1:gg1]).filter(lambda x: x == 1).value())
        # 上涨走势中有几个反向线段
        c2 = len(
            pydash.chain(duan_series[gg1 : idx + 1]).filter(lambda x: x == -1).value()
        )
        # 上涨走势高点后面又几个反向线段
        if d1 > gg1:
            # 上涨走势高点后有线段低点
            if len(pivots) == 0 and c >= 1:
                # 没有中枢是三段及三段以上走势
                i = pydash.find_last_index(duan_series[:gg1], lambda x: x == 1)
                if (
                    low_series[d1] > high_series[i]
                    and len(pydash.filter_(duan_series[gg1:idx], lambda x: x == -1))
                    == 1
                ):
                    category = '准三买'
                else:
                    category = '完备买'
            elif len(pivots) == 0 and c2 == 2:
                category = '完备买'
            elif len(pivots) > 0:
                # 有中枢
                if low_series[d1] > pivots[-1]['gg']:
                    category = '三类买'
                elif len(pydash.filter_(duan_series[gg1:idx], lambda x: x == -1)) == 1:
                    category = '扩展完备买'
    return category


# 卖点的所在形态
def sell_category(higher_duan_series, duan_series, high_series, low_series, idx):
    category = ''
    g1 = FindPrevEq(duan_series, 1, idx)
    d1 = FindPrevEq(duan_series, -1, g1)
    g2 = FindPrevEq(duan_series, 1, d1)
    d2 = FindPrevEq(duan_series, -1, g2)
    g3 = FindPrevEq(duan_series, 1, d2)
    if (
        g3 >= 0
        and high_series[g1] < high_series[g2] > high_series[g3]
        and low_series[d1] < low_series[d2]
        and high_series[g1] < low_series[d2]
    ):
        category = '准三卖'
    # 走势低点
    dd1 = pydash.find_last_index(higher_duan_series[: idx + 1], lambda x: x == -1)
    # 走势高点
    gg1 = pydash.find_last_index(higher_duan_series[: idx + 1], lambda x: x == 1)
    if gg1 > dd1 >= 0:
        # 最后一个确认的是上涨走势
        g1 = (
            gg1
            + 1
            + pydash.find_index(duan_series[gg1 + 1 : idx + 1], lambda x: x == 1)
        )
        c = len(pydash.filter_(duan_series[dd1 + 1 : idx + 1], lambda x: x == 1))
        # 上涨
        pivots = FindPivots(dd1, gg1, duan_series, high_series, low_series, 1)
        if g1 == gg1:
            # 走势高点后面没有线段高点
            category = '一类卖'
            for x in range(gg1, len(duan_series)):
                if duan_series[x] == -1:
                    if x < idx and high_series[idx] > low_series[x]:
                        category = '二类卖'
                    break
        else:
            # 走势高点后还有线段高点，但是还没有形成新的走势
            if len(pivots) > 0 and high_series[g1] < pivots[-1]['zd']:
                category = '三类卖'
            if c == 1:
                category = '二类卖'

    elif dd1 > gg1 >= 0:
        # 最后一个确认的是下跌走势
        # 下跌走势低点后面的第一个线段高点
        g1 = dd1 + pydash.find_index(duan_series[dd1 : idx + 1], lambda x: x == 1)
        # 下涨中枢
        pivots = FindPivots(gg1, dd1, duan_series, high_series, low_series, -1)
        # 下跌走势中有几个反向线段
        c = len(pydash.chain(duan_series[gg1:dd1]).filter(lambda x: x == -1).value())
        # 下跌走势低点后面又几个反向线段
        c2 = len(
            pydash.chain(duan_series[dd1 : idx + 1]).filter(lambda x: x == 1).value()
        )
        if g1 > dd1:
            # 下跌走势低点后有线段高点
            if len(pivots) == 0 and c >= 1:
                # 没有中枢是三段及三段以上走势
                i = pydash.find_last_index(duan_series[:dd1], lambda x: x == -1)
                if (
                    high_series[g1] < low_series[i]
                    and len(pydash.filter_(duan_series[dd1:idx], lambda x: x == 1)) == 1
                ):
                    # 反弹高点连下端走势的最后一个低点也没到，为准三买
                    category = '准三卖'
                else:
                    # 否则是完备卖
                    category = '完备卖'
            elif len(pivots) == 0 and c2 == 2:
                category = '完备卖'
            elif len(pivots) > 0:
                # 有中枢
                if high_series[g1] < pivots[-1]['dd']:
                    category = '三类卖'
                elif len(pydash.filter_(duan_series[dd1:idx], lambda x: x == 1)) == 1:
                    category = '扩展完备卖'
    return category
