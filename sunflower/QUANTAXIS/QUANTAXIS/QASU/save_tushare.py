# coding:utf-8
#
# The MIT License (MIT)
#
# Copyright (c) 2016-2021 yutiansut/QUANTAXIS
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import datetime
import json
import re
import time
import pymongo

import tushare as ts

from QUANTAXIS.QAFetch.QATushare import (
    QA_fetch_get_stock_day,
    QA_fetch_get_stock_info,
    QA_fetch_get_stock_list,
    QA_fetch_get_stock_block,
    QA_fetch_get_trade_date,
    QA_fetch_get_lhb,
)
from QUANTAXIS.QAUtil import (
    QA_util_date_stamp,
    QA_util_log_info,
    QA_util_time_stamp,
    QA_util_to_json_from_pandas,
    trade_date_sse,
    QA_util_get_real_date,
    QA_util_get_next_day
)
from QUANTAXIS.QAUtil.QASetting import DATABASE

import tushare as QATs


def date_conver_to_new_format(date_str):
    time_now = time.strptime(date_str[0:10], '%Y-%m-%d')
    return '{:0004}{:02}{:02}'.format(
        int(time_now.tm_year),
        int(time_now.tm_mon),
        int(time_now.tm_mday)
    )


# TODO: 和sav_tdx.py中的now_time一起提取成公共函数
def now_time():
    real_date = str(QA_util_get_real_date(str(datetime.date.today() -
                                          datetime.timedelta(days=1)),
                                          trade_date_sse, -1))
    str_now = real_date + ' 17:00:00' if datetime.datetime.now().hour < 15 \
        else str(QA_util_get_real_date(str(datetime.date.today()),
                                       trade_date_sse, -1)) + ' 15:00:00'

    return date_conver_to_new_format(str_now)


def QA_save_stock_day_all(client=DATABASE):
    df = ts.get_stock_basics()
    __coll = client.stock_day
    __coll.ensure_index('code')

    def saving_work(i):
        QA_util_log_info('Now Saving ==== %s' % (i))
        try:
            data_json = QA_fetch_get_stock_day(i, start='1990-01-01')

            __coll.insert_many(data_json)
        except Exception as e:
            print(e)
            QA_util_log_info('error in saving ==== %s' % str(i))

    for i_ in range(len(df.index)):
        QA_util_log_info('The %s of Total %s' % (i_, len(df.index)))
        QA_util_log_info(
            'DOWNLOAD PROGRESS %s ' %
            str(float(i_ / len(df.index) * 100))[0:4] + '%'
        )
        saving_work(df.index[i_])

    saving_work('hs300')
    saving_work('sz50')


def QA_SU_save_stock_list(client=DATABASE):
    data = QA_fetch_get_stock_list()
    date = str(datetime.date.today())
    date_stamp = QA_util_date_stamp(date)
    coll = client.stock_info_tushare
    coll.insert(
        {
            'date': date,
            'date_stamp': date_stamp,
            'stock': {
                'code': data
            }
        }
    )


def QA_SU_save_stock_terminated(client=DATABASE):
    '''
    获取已经被终止上市的股票列表，数据从上交所获取，目前只有在上海证券交易所交易被终止的股票。
    collection：
        code：股票代码 name：股票名称 oDate:上市日期 tDate:终止上市日期
    :param client:
    :return: None
    '''

    # 🛠todo 已经失效从wind 资讯里获取
    # 这个函数已经失效
    print("！！！ tushare 这个函数已经失效！！！")
    df = QATs.get_terminated()
    #df = QATs.get_suspended()
    print(
        " Get stock terminated from tushare,stock count is %d  (终止上市股票列表)" %
        len(df)
    )
    coll = client.stock_terminated
    client.drop_collection(coll)
    json_data = json.loads(df.reset_index().to_json(orient='records'))
    coll.insert(json_data)
    print(" 保存终止上市股票列表 到 stock_terminated collection， OK")


def QA_SU_save_stock_info_tushare(client=DATABASE):
    '''
        获取 股票的 基本信息，包含股票的如下信息

        code,代码
        name,名称
        industry,所属行业
        area,地区
        pe,市盈率
        outstanding,流通股本(亿)
        totals,总股本(亿)
        totalAssets,总资产(万)
        liquidAssets,流动资产
        fixedAssets,固定资产
        reserved,公积金
        reservedPerShare,每股公积金
        esp,每股收益
        bvps,每股净资
        pb,市净率
        timeToMarket,上市日期
        undp,未分利润
        perundp, 每股未分配
        rev,收入同比(%)
        profit,利润同比(%)
        gpr,毛利率(%)
        npr,净利润率(%)
        holders,股东人数

        add by tauruswang

    在命令行工具 quantaxis 中输入 save stock_info_tushare 中的命令
    :param client:
    :return:
    '''
    df = QATs.get_stock_basics()
    print(" Get stock info from tushare,stock count is %d" % len(df))
    coll = client.stock_info_tushare
    client.drop_collection(coll)
    json_data = json.loads(df.reset_index().to_json(orient='records'))
    coll.insert(json_data)
    print(" Save data to stock_info_tushare collection， OK")


def QA_SU_save_trade_date_all(client=DATABASE):
    data = QA_fetch_get_trade_date('', '')
    coll = client.trade_date
    coll.insert_many(data)


def QA_SU_save_stock_info(client=DATABASE):
    data = QA_fetch_get_stock_info('')
    client.drop_collection('stock_info')
    coll = client.stock_info
    coll.create_index('code')
    coll.insert_many(QA_util_to_json_from_pandas(data.reset_index()))


def QA_save_stock_day_all_bfq(client=DATABASE):
    df = ts.get_stock_basics()

    __coll = client.stock_day_bfq
    __coll.ensure_index('code')

    def saving_work(i):
        QA_util_log_info('Now Saving ==== %s' % (i))
        try:
            df = QA_fetch_get_stock_day(i, start='1990-01-01', if_fq='bfq')

            __coll.insert_many(json.loads(df.to_json(orient='records')))
        except Exception as e:
            print(e)
            QA_util_log_info('error in saving ==== %s' % str(i))

    for i_ in range(len(df.index)):
        QA_util_log_info('The %s of Total %s' % (i_, len(df.index)))
        QA_util_log_info(
            'DOWNLOAD PROGRESS %s ' %
            str(float(i_ / len(df.index) * 100))[0:4] + '%'
        )
        saving_work(df.index[i_])

    saving_work('hs300')
    saving_work('sz50')


def QA_save_stock_day_with_fqfactor(client=DATABASE):
    df = ts.get_stock_basics()

    __coll = client.stock_day
    __coll.ensure_index('code')

    def saving_work(i):
        QA_util_log_info('Now Saving ==== %s' % (i))
        try:
            data_hfq = QA_fetch_get_stock_day(
                i,
                start='1990-01-01',
                if_fq='02',
                type_='pd'
            )
            data_json = QA_util_to_json_from_pandas(data_hfq)
            __coll.insert_many(data_json)
        except Exception as e:
            print(e)
            QA_util_log_info('error in saving ==== %s' % str(i))

    for i_ in range(len(df.index)):
        QA_util_log_info('The %s of Total %s' % (i_, len(df.index)))
        QA_util_log_info(
            'DOWNLOAD PROGRESS %s ' %
            str(float(i_ / len(df.index) * 100))[0:4] + '%'
        )
        saving_work(df.index[i_])

    saving_work('hs300')
    saving_work('sz50')

    QA_util_log_info('Saving Process has been done !')
    return 0


def QA_save_lhb(client=DATABASE):
    __coll = client.lhb
    __coll.ensure_index('code')

    start = datetime.datetime.strptime("2006-07-01", "%Y-%m-%d").date()
    end = datetime.date.today()
    i = 0
    while start < end:
        i = i + 1
        start = start + datetime.timedelta(days=1)
        try:
            pd = QA_fetch_get_lhb(start.isoformat())
            if pd is None:
                continue
            data = pd\
                .assign(pchange=pd.pchange.apply(float))\
                .assign(amount=pd.amount.apply(float))\
                .assign(bratio=pd.bratio.apply(float))\
                .assign(sratio=pd.sratio.apply(float))\
                .assign(buy=pd.buy.apply(float))\
                .assign(sell=pd.sell.apply(float))
            # __coll.insert_many(QA_util_to_json_from_pandas(data))
            for i in range(0, len(data)):
                __coll.update(
                    {
                        "code": data.iloc[i]['code'],
                        "date": data.iloc[i]['date']
                    },
                    {"$set": QA_util_to_json_from_pandas(data)[i]},
                    upsert=True
                )
            time.sleep(2)
            if i % 10 == 0:
                time.sleep(60)
        except Exception as e:
            print("error codes:")
            time.sleep(2)
            continue


def _saving_work(code, coll_stock_day, ui_log=None, err=[]):
    try:
        QA_util_log_info(
            '##JOB01 Now Saving STOCK_DAY==== {}'.format(str(code)),
            ui_log
        )

        # 首选查找数据库 是否 有 这个代码的数据
        ref = coll_stock_day.find_one({'code': str(code)[0:6]}, sort=[('date', -1)])
        end_date = now_time()

        # 当前数据库已经包含了这个代码的数据， 继续增量更新
        # 加入这个判断的原因是因为如果股票是刚上市的 数据库会没有数据 所以会有负索引问题出现
        if ref:

            # 接着上次获取的日期继续更新
            start_date_new_format = ref['trade_date']
            start_date = ref['date']

            QA_util_log_info(
                'UPDATE_STOCK_DAY \n Trying updating {} from {} to {}'
                .format(code,
                        start_date_new_format,
                        end_date),
                ui_log
            )
            if start_date_new_format != end_date:
                coll_stock_day.insert_many(
                    QA_util_to_json_from_pandas(
                        QA_fetch_get_stock_day(
                            str(code),
                            date_conver_to_new_format(
                                QA_util_get_next_day(start_date)
                            ),
                            end_date,
                            'bfq'
                        )
                    )
                )

        # 当前数据库中没有这个代码的股票数据， 从1990-01-01 开始下载所有的数据
        else:
            start_date = '19900101'
            QA_util_log_info(
                'UPDATE_STOCK_DAY \n Trying updating {} from {} to {}'
                .format(code,
                        start_date,
                        end_date),
                ui_log
            )
            if start_date != end_date:
                coll_stock_day.insert_many(
                    QA_util_to_json_from_pandas(
                        QA_fetch_get_stock_day(
                            str(code),
                            start_date,
                            end_date,
                            'bfq'
                        )
                    )
                )
    except Exception as e:
        print(e)
        err.append(str(code))


def QA_SU_save_stock_day(client=DATABASE, ui_log=None, ui_progress=None):
    '''
     save stock_day
    保存日线数据
    :param client:
    :param ui_log:  给GUI qt 界面使用
    :param ui_progress: 给GUI qt 界面使用
    :param ui_progress_int_value: 给GUI qt 界面使用
    '''
    stock_list = QA_fetch_get_stock_list()
    # TODO: 重命名stock_day_ts
    coll_stock_day = client.stock_day_ts
    coll_stock_day.create_index(
        [("code",
          pymongo.ASCENDING),
         ("date_stamp",
          pymongo.ASCENDING)]
    )

    err = []
    num_stocks = len(stock_list)
    for index, ts_code in enumerate(stock_list):
        QA_util_log_info('The {} of Total {}'.format(index, num_stocks))

        strProgressToLog = 'DOWNLOAD PROGRESS {} {}'.format(
            str(float(index / num_stocks * 100))[0:4] + '%',
            ui_log
        )
        intProgressToLog = int(float(index / num_stocks * 100))
        QA_util_log_info(
            strProgressToLog,
            ui_log=ui_log,
            ui_progress=ui_progress,
            ui_progress_int_value=intProgressToLog
        )
        _saving_work(ts_code,
                     coll_stock_day,
                     ui_log=ui_log,
                     err=err)
        # 日线行情每分钟内最多调取200次，超过5000积分无限制
        time.sleep(0.005)

    if len(err) < 1:
        QA_util_log_info('SUCCESS save stock day ^_^', ui_log)
    else:
        QA_util_log_info('ERROR CODE \n ', ui_log)
        QA_util_log_info(err, ui_log)


def QA_SU_save_stock_block(client=DATABASE, ui_log=None, ui_progress=None):
    """
    Tushare的版块数据
    
    Returns:
        [type] -- [description]
    """
    coll = client.stock_block
    coll.create_index('code')
    try:
        # 暂时先只有中证500
        csindex500 = QA_fetch_get_stock_block()
        coll.insert_many(
            QA_util_to_json_from_pandas(csindex500))
        QA_util_log_info('SUCCESS save stock block ^_^', ui_log)
    except Exception as e:
        QA_util_log_info('ERROR CODE \n ', ui_log)
        QA_util_log_info(e, ui_log)


if __name__ == '__main__':
    from pymongo import MongoClient
    client = MongoClient('localhost', 27017)
    db = client['quantaxis']
    QA_SU_save_stock_day(client=db)
