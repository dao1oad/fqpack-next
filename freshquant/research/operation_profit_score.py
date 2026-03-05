# -*- coding: utf-8 -*-

import codecs
import os

import pydash
import QUANTAXIS as QA


def main():
    dir = "E:/freshquant_data/jibenmian"
    out = "D:/freshquant_data/jibenmian_out"
    files = os.listdir(dir)
    for filename in files:
        with codecs.open(os.path.join(dir, filename), encoding='utf-8') as f:
            lines = f.readlines()
        codes = pydash.chain(lines).map(lambda line: line.strip()[4:]).value()
        data = QA.QA_fetch_financial_report(codes, ['2021-06-30'])
        data = data[
            [
                'code',
                'report_date',
                'operatingProfit',
                'operatingRevenue',
                'totalCapital',
            ]
        ]
        hq = QA.QA_fetch_stock_day_adv(codes, start='2021-10-11', end='2021-10-11').data
        hq.reset_index(inplace=True)
        hq = hq[['code', 'close']]
        data = data.join(hq, hq.set_index('code', inplace=True))
        data['rate'] = data['operatingProfit'] / data['operatingRevenue']
        data['rate'] = data['rate'].apply(lambda r: rate(r))
        data['totalValue'] = data['totalCapital'] * data['close']
        data['score'] = data['operatingRevenue'] / data['totalValue'] * data['rate']
        data = data.sort_values('score', ascending=False)
        data.reset_index(inplace=True, drop=True)
        data['report_date'] = data['report_date'].apply(
            lambda x: x.strftime('%Y-%m-%d')
        )
        data = data.rename(
            columns={
                'code': '股票代码',
                'report_date': '报表日期',
                'operatingProfit': '营业利润',
                'operatingRevenue': '营业收入',
                'totalCapital': '总股本',
                'close': '收盘价',
                'rate': '系数',
                'totalValue': '总市值',
                'score': '得分',
            }
        )
        data = data[['股票代码', '报表日期', '营业利润', '营业收入', '总股本', '收盘价', '总市值', '系数', '得分']]
        data.to_excel(os.path.join(out, filename.rstrip('.txt') + '.xlsx'), index=False)


def rate(r):
    if r > 0.1:
        return 1.5
    elif r > 0.05:
        return 1.2
    elif r > 0:
        return 1.0
    else:
        return -1.0


if __name__ == '__main__':
    main()
