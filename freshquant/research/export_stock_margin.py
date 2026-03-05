# -*- coding:utf-8 -*-

import os

from pydash import chain, get

from freshquant.config import settings
from freshquant.data.astock.stock_margin import fq_fetch_stock_margin_detail


def run():
    data = fq_fetch_stock_margin_detail()
    data = data[["dai_ma", "ming_cheng", "ri_qi", "rong_quan_yu_liang"]]
    count_data = data.groupby('dai_ma')['ri_qi'].count()
    count_data = count_data.rename('天数')
    data['pct_change'] = data.groupby('dai_ma')['rong_quan_yu_liang'].pct_change(
        periods=1
    )
    data.rename(
        columns={
            "ri_qi": "日期",
            "dai_ma": "代码",
            "ming_cheng": "名称",
            "rong_quan_yu_liang": "融券余量",
            "pct_change": "变动幅度",
        },
        inplace=True,
    )
    days = data['日期'].to_list()
    days = chain(days).uniq().sort().take_right(10).value()
    for day in days:
        data[data['日期'] == day]
        df = data[data['日期'] == day]
        if df.empty:
            continue
        df.dropna(how='any', inplace=True)
        df.sort_values(by='变动幅度', inplace=True)
        df.set_index('代码', inplace=True)
        df = df.join(count_data)
        output_dir = get(settings, "output.dir", "")
        df.to_excel(os.path.join(output_dir, f"融券余量变动排行{day}.xlsx"))


if __name__ == "__main__":
    run()
