# -*- coding:utf-8 -*-

import pandas as pd
import pendulum
import QUANTAXIS as QA
from QUANTAXIS.QAMarket.QAOrder import ORDER_DIRECTION

from freshquant.quantaxis.qifi.qifiaccount import QIFI_Account


def get_trade_day_bar(unit='W', n=1, start_date=None, end_date=None, count=None):
    """
    unit: 频率 , "W"代表周 或者 "M"代表月
    n: 第几个交易日, 每月第一个交易日: n=1, 每月最后一个交易日: n=-1, 每月倒数第三个交易日: n=-3, 如果不足abs(n)个交易日, 则返回符合条件的最近的一个交易日
    start_date: 开始时间
    end_date: 结束时间
    count: 返回数据条数, 指定start_date及count时返回start_date向后count条数据, 指定end_date及count时返回end_date向前count条数据

    返回的数据会在 get_all_trade_days 以内
    返回: 一个dataframe ,具体列含义见源码, date列就是需要获取的交易日了(datetime格式)
    """
    df = pd.DataFrame(pd.to_datetime(QA.trade_date_sse), columns=['date'])
    week_stamp = 24 * 60 * 60 * 7
    day_stamp = 24 * 60 * 60
    df['timestamp'] = df.date.apply(
        lambda x: x.timestamp() - day_stamp * 3
    )  # 基于1970-01-01偏移三天
    df['mkweek'] = (
        df.timestamp // week_stamp
    )  # 1970-01-01 至今的第几周, 直接取每年的第几周再换年时会有问题
    df['month'] = df.date.apply(lambda x: x.month)  # 月
    df['year'] = df.date.apply(lambda x: x.year)  # 年
    if unit == "W":
        group_list = ['mkweek']
    elif unit == "M":
        group_list = ["year", "month"]
    else:
        raise ValueError('只支持M参数为 "M"或"W" ')

    if not isinstance(n, int):
        raise ValueError('n 参数应该是一个int')
    elif n > 0:
        res = (
            df.groupby(group_list, as_index=False)
            .head(n)
            .groupby(group_list, as_index=False)
            .last()
        )
    elif n < 0:
        res = (
            df.groupby(group_list, as_index=False)
            .tail(-n)
            .groupby(group_list, as_index=False)
            .first()
        )
    else:
        raise ValueError('n 参数错误: n={}'.format(n))

    if start_date and end_date and count:
        raise ValueError('start_date ,end_date ,count 必须三选二')

    elif start_date and count:
        return res[res.date >= start_date].head(count)
    elif end_date and count:
        return res[res.date <= end_date].tail(count)
    elif start_date and end_date:
        return res[(res.date <= end_date) & (res.date >= start_date)]
    elif not start_date and not end_date and not count:
        return res
    else:
        raise ValueError('start_date, end_date, count 必须三选二')


def change_vol_positions(acc, R):
    balance = acc.balance
    change = []
    for i in R.keys():
        pos = acc.get_position(i)
        pos_market_value = pos.volume_long * pos.last_price  # 持仓市值
        end_ratio = int(balance * R.get(i) / pos.last_price // 100 * 100)  # 调仓目标
        if end_ratio - pos.volume_long > 0:
            print('{}：调仓买入{}股'.format(i, end_ratio - pos.volume_long))
        elif end_ratio - pos.volume_long < 0:
            print('{}：调仓卖出{}股'.format(i, abs(end_ratio - pos.volume_long)))
        change.append(
            {
                'code': i,
                'price': pos.last_price,
                '原持仓数量': pos.volume_long,
                '原持仓市值': pos_market_value,
                '调仓目标': end_ratio,
                '调仓数量': end_ratio - pos.volume_long,
            }
        )
    return change


def main():
    codes = ['510300', '518880', '511260']
    start = pendulum.today().subtract(years=3).to_date_string()
    end = pendulum.today().to_date_string()
    trade_day = [i for i in QA.trade_date_sse if i >= start and i <= end]
    change_day = (
        get_trade_day_bar(unit='M', n=-1, start_date=start, end_date=end)
        .date.astype('str')
        .tolist()
    )
    data = QA.QA_fetch_index_day_adv(code=codes, start=start, end=end)
    R = {'510300': 0.3, '518880': 0.3, '511260': 0.3}
    acc = QIFI_Account(
        'FOF',
        'FOF',
        model='BACKTEST',
        trade_host='freshquant.mshome.net',
        nodatabase=False,
    )
    acc.initial()
    for code in R.keys():
        acc.get_position(code)
    for day in trade_day:
        hq_data = data.data.loc[(day, slice(None)), :]
        for i in range(len(hq_data)):
            bar = hq_data.iloc[i]
            acc.on_price_change(
                code=bar.name[1],
                price=bar.close,
                datetime=str(bar.name[0])[:10] + ' ' + '15:00:00',
            )
        if day in change_day:
            change = change_vol_positions(acc, R)
            change_df = pd.DataFrame(change).sort_values(by='调仓数量', ascending=False)
            print('账户市值：', acc.balance)
            print('账户可用资金：', acc.available)
            for i in range(len(change_df)):
                ord = change_df.iloc[i]
                if ord['调仓数量'] > 0:
                    od = acc.send_order(
                        code=ord['code'],
                        amount=ord['调仓数量'],
                        price=ord['price'],
                        towards=ORDER_DIRECTION.BUY_OPEN,
                    )
                    acc.make_deal(od)
                elif ord['调仓数量'] < 0:
                    od = acc.send_order(
                        code=ord['code'],
                        amount=abs(ord['调仓数量']),
                        price=ord['price'],
                        towards=ORDER_DIRECTION.SELL_CLOSE,
                    )
                    acc.make_deal(od)
        acc.settle()
    print(acc.account_msg)


if __name__ == "__main__":
    main()
