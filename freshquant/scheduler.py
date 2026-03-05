# -*- coding: utf-8 -*-

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import atexit
import logging
from logging.handlers import RotatingFileHandler

import pytz
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.blocking import BlockingScheduler

from freshquant.db import DBfreshquant
from freshquant.signal import MarketData, strategy3, strategy4

tz = pytz.timezone('Asia/Shanghai')


def app():
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(threadName)s %(levelname)s %(message)s',
    )
    logger = logging.getLogger()
    logfile = os.path.join(BASE_DIR, "logs\freshquant-scheduler.log")
    handler = RotatingFileHandler(
        filename=logfile, maxBytes=10 * 1024 * 1024, backupCount=5
    )
    formatter = logging.Formatter(
        '%(asctime)s %(threadName)s %(levelname)s %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    symbol_list = list(DBfreshquant['symbol'].find({"monitoring": True}))
    size = len(symbol_list)
    executors = {
        'default': ThreadPoolExecutor(size * 5),
    }
    scheduler = BlockingScheduler(executors=executors, timezone=tz)
    atexit.register(lambda: scheduler.shutdown(wait=False))

    for symbol in symbol_list:
        s = {'code': symbol['code'], 'backend': symbol['backend']}
        scheduler.add_job(MarketData.getMarketData, 'interval', [s], seconds=15)
        scheduler.add_job(strategy3.doCaculate, 'interval', [s], seconds=30)
        scheduler.add_job(strategy4.doCaculate, 'interval', [s], seconds=30)

    scheduler.start()


if __name__ == '__main__':
    app()
