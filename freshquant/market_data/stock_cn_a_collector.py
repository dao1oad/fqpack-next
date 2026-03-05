import multiprocessing
import os
import signal
import traceback
from datetime import datetime, timedelta
from time import sleep

import akshare as ak
import click
import durationpy
import pandas as pd
from loguru import logger

from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.config import cfg
from freshquant.data.astock.pool import get_stock_monitor_codes
from freshquant.data.tdx import TdxExecutor
from freshquant.data.trade_date_hist import tool_trade_date_seconds_to_start
from freshquant.database.redis import redis_db
from freshquant.instrument.general import query_instrument_type
from freshquant.log.exception import log_exception
from freshquant.util.code import fq_util_code_append_market_code
from freshquant.worker import process_hq_stock_realtime

STOCK_CN_A_COLLECTOR_QUEUE = "stock_cn_a_collector_queue"


def stock_zh_a_min_symbol_queue_x(stop_event, test: bool = False):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while True:
        if stop_event.is_set():
            break
        try:
            queue_length = redis_db.llen(STOCK_CN_A_COLLECTOR_QUEUE)
            if queue_length >= 1000:
                sleep(60)
                continue
            if not test:
                seconds = tool_trade_date_seconds_to_start()
                if seconds > 0:
                    seconds = min(seconds, 900)
                    logger.info(
                        "%s from now on, %s sleep %s to resume"
                        % (
                            datetime.now().strftime(cfg.DT_FORMAT_FULL),
                            "股票队列派发",
                            durationpy.to_str(timedelta(seconds=seconds)),
                        )
                    )
                    sleep(seconds)
                    if tool_trade_date_seconds_to_start() > 0:
                        continue
            symbols = get_stock_monitor_codes(holding_only=True)
            if len(symbols) > 0:
                redis_db.lpush(STOCK_CN_A_COLLECTOR_QUEUE, *symbols)
        except KeyboardInterrupt:
            logger.info("stock_zh_a_min_symbol_queue_x停止中...")
            break
        except Exception:
            log_exception("Error Occurred: {0}".format(traceback.format_exc()))
        sleep(60)
    logger.info("stock_zh_a_min_symbol_queue_x已停止")


def stock_zh_a_min_symbol_queue_y(stop_event, test: bool = False):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while True:
        try:
            if stop_event.is_set():
                break
            queue_length = redis_db.llen(STOCK_CN_A_COLLECTOR_QUEUE)
            if queue_length >= 1000:
                sleep(60)
                continue
            if not test:
                seconds = tool_trade_date_seconds_to_start()
                if seconds > 0:
                    seconds = min(seconds, 900)
                    logger.info(
                        "%s from now on, %s sleep %s to resume"
                        % (
                            datetime.now().strftime(cfg.DT_FORMAT_FULL),
                            "股票队列派发",
                            durationpy.to_str(timedelta(seconds=seconds)),
                        )
                    )
                    sleep(seconds)
                    if tool_trade_date_seconds_to_start() > 0:
                        continue
            symbols = get_stock_monitor_codes()
            if len(symbols) > 0:
                redis_db.lpush(STOCK_CN_A_COLLECTOR_QUEUE, *symbols)
        except KeyboardInterrupt:
            logger.info("stock_zh_a_min_symbol_queue_y停止中...")
            break
        except Exception:
            log_exception("Error Occurred: {0}".format(traceback.format_exc()))
        sleep(60)
    logger.info("stock_zh_a_min_symbol_queue_y已停止")


def stock_zh_a_min_tdx(stop_event, test: bool = False):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    tdx_executor = TdxExecutor()
    sleep_time = 0.1
    while True:
        symbol = None
        try:
            if not test:
                if redis_db.llen(STOCK_CN_A_COLLECTOR_QUEUE) == 0:
                    seconds = tool_trade_date_seconds_to_start()
                    if seconds > 0:
                        seconds = min(seconds, 900)
                        logger.info(
                            "%s from now on, %s sleep %s to resume"
                            % (
                                datetime.now().strftime(cfg.DT_FORMAT_FULL),
                                "收集通达信分钟数据",
                                durationpy.to_str(timedelta(seconds=seconds)),
                            )
                        )
                        sleep(seconds)
                        if tool_trade_date_seconds_to_start() > 0:
                            continue
            symbol = redis_db.rpop(STOCK_CN_A_COLLECTOR_QUEUE)
            if symbol is None:
                if not stop_event.is_set():
                    continue
                else:
                    break
            instrumentType = query_instrument_type(symbol)
            collection = None
            if instrumentType == InstrumentType.STOCK_CN:
                collection = "stock_realtime"
            elif instrumentType == InstrumentType.ETF_CN:
                collection = "index_realtime"
            data = tdx_executor.get_security_bars(symbol, '1min', 800)
            if data is None or len(data) <= 0:
                redis_db.lpush(STOCK_CN_A_COLLECTOR_QUEUE, symbol)
                continue
            df = pd.DataFrame(data=data)
            df.rename(columns={"vol": "volume"}, inplace=True)
            code = fq_util_code_append_market_code(symbol, upper_case=False)
            df = df[["datetime", "open", "close", "high", "low", "volume", "amount"]]
            df['datetime'] = df['datetime'].apply(
                lambda record: cfg.TZ.localize(
                    datetime.strptime(record, cfg.DT_FORMAT_M)
                )
            )
            df.set_index('datetime', inplace=True, drop=True)
            df['open'] = df['open'].astype('float64')
            df['close'] = df['close'].astype('float64')
            df['high'] = df['high'].astype('float64')
            df['low'] = df['low'].astype('float64')
            df['amount'] = df['close'] * df['volume']
            df["code"] = code
            df["frequence"] = "1min"
            df["source"] = "通达信"
            logger.info("%s 通达信" % symbol)
            process_hq_stock_realtime(df, collection)
            sleep_time = sleep_time / 2 if sleep_time > 0.1 else sleep_time
        except KeyboardInterrupt:
            logger.info("stock_zh_a_min_tdx停止中...")
        except Exception:
            sleep_time = sleep_time * 2 if sleep_time < 900 else sleep_time
            log_exception("Error Occurred: {0}".format(traceback.format_exc()))
        sleep(sleep_time)
    logger.info("stock_zh_a_min_tdx已停止")
    # 这里是临时处理，因为TdxExecutor有线程不会退出，导致进程不会退出。
    # 以后再优化
    os.kill(os.getpid(), signal.SIGTERM)


def stock_zh_a_min_em(stop_event, test: bool = False):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    sleep_time = 0.1
    while True:
        symbol = None
        try:
            if not test:
                if redis_db.llen(STOCK_CN_A_COLLECTOR_QUEUE) == 0:
                    seconds = tool_trade_date_seconds_to_start()
                    if seconds > 0:
                        seconds = min(seconds, 900)
                        logger.info(
                            "%s from now on, %s sleep %s to resume"
                            % (
                                datetime.now().strftime(cfg.DT_FORMAT_FULL),
                                "收集东财分钟数据",
                                durationpy.to_str(timedelta(seconds=seconds)),
                            )
                        )
                        sleep(seconds)
                        if tool_trade_date_seconds_to_start() > 0:
                            continue
            symbol = redis_db.rpop(STOCK_CN_A_COLLECTOR_QUEUE)
            if symbol is None:
                if not stop_event.is_set():
                    continue
                else:
                    break
            instrumentType = query_instrument_type(symbol)
            collection = None
            if instrumentType == InstrumentType.STOCK_CN:
                df = ak.stock_zh_a_hist_min_em(symbol=symbol, period='1')
                collection = "stock_realtime"
            elif instrumentType == InstrumentType.ETF_CN:
                df = ak.fund_etf_hist_min_em(symbol=symbol, period='1')
                collection = "index_realtime"
            df.rename(
                columns={
                    "时间": "datetime",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume",
                    "成交额": "amount",
                },
                inplace=True,
            )
            df = df[["datetime", "open", "close", "high", "low", "volume", "amount"]]
            code = fq_util_code_append_market_code(symbol, upper_case=False)
            df['datetime'] = df['datetime'].apply(
                lambda record: cfg.TZ.localize(
                    datetime.strptime(record, cfg.DT_FORMAT_FULL)
                )
            )
            df.set_index('datetime', inplace=True, drop=True)
            df['open'] = df['open'].astype('float64')
            df['close'] = df['close'].astype('float64')
            df['high'] = df['high'].astype('float64')
            df['low'] = df['low'].astype('float64')
            df['volume'] = df['volume'].astype('float64')
            df['amount'] = df['amount'].astype('float64')
            df["code"] = code
            df["frequence"] = "1min"
            df["source"] = "东财"
            logger.info("%s 东财" % symbol)
            process_hq_stock_realtime(df, collection)
            sleep_time = sleep_time / 2 if sleep_time > 0.1 else sleep_time
        except KeyboardInterrupt:
            logger.info("stock_zh_a_min_em停止中...")
        except Exception:
            sleep_time = sleep_time * 2 if sleep_time < 900 else sleep_time
            log_exception("Error Occurred: {0}".format(traceback.format_exc()))
        sleep(1)
    logger.info("stock_zh_a_min_em已停止")


def stock_zh_a_min_sina(stop_event, test: bool = False):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    sleep_time = 0.1
    while True:
        symbol = None
        try:
            if not test:
                if redis_db.llen(STOCK_CN_A_COLLECTOR_QUEUE) == 0:
                    seconds = tool_trade_date_seconds_to_start()
                    if seconds > 0:
                        seconds = min(seconds, 900)
                        logger.info(
                            "%s from now on, %s sleep %s to resume"
                            % (
                                datetime.now().strftime(cfg.DT_FORMAT_FULL),
                                "收集新浪分钟数据",
                                durationpy.to_str(timedelta(seconds=seconds)),
                            )
                        )
                        sleep(seconds)
                        if tool_trade_date_seconds_to_start() > 0:
                            continue
            symbol = redis_db.rpop(STOCK_CN_A_COLLECTOR_QUEUE)
            if symbol is None:
                if not stop_event.is_set():
                    continue
                else:
                    break
            instrumentType = query_instrument_type(symbol)
            collection = None
            source = None
            if instrumentType == InstrumentType.STOCK_CN:
                df = ak.stock_zh_a_minute(
                    symbol=fq_util_code_append_market_code(symbol, upper_case=False),
                    period=1,
                )
                collection = "stock_realtime"
                source = "新浪"
            elif instrumentType == InstrumentType.ETF_CN:
                # 新浪没有，借用东财的
                df = ak.fund_etf_hist_min_em(symbol=symbol, period='1')
                collection = "index_realtime"
                source = "东财"
                df.rename(
                    columns={
                        "时间": "datetime",
                        "开盘": "open",
                        "收盘": "close",
                        "最高": "high",
                        "最低": "low",
                        "成交量": "volume",
                        "成交额": "amount",
                    },
                    inplace=True,
                )
            df.rename(columns={"day": "datetime"}, inplace=True)
            code = fq_util_code_append_market_code(symbol, upper_case=False)

            df = df[["datetime", "open", "close", "high", "low", "volume"]]
            df['datetime'] = df['datetime'].apply(
                lambda record: cfg.TZ.localize(
                    datetime.strptime(record, cfg.DT_FORMAT_FULL)
                )
            )
            df.set_index('datetime', inplace=True, drop=True)
            df['open'] = df['open'].astype('float64')
            df['close'] = df['close'].astype('float64')
            df['high'] = df['high'].astype('float64')
            df['low'] = df['low'].astype('float64')
            df['volume'] = df['volume'].astype('float64')
            df['amount'] = df['close'] * df['volume']
            df["code"] = code
            df["frequence"] = "1min"
            df["source"] = source
            logger.info("%s 新浪" % symbol)
            process_hq_stock_realtime(df, collection)
            sleep_time = sleep_time / 2 if sleep_time > 0.1 else sleep_time
        except KeyboardInterrupt:
            logger.info("stock_zh_a_min_sina停止中...")
        except Exception:
            sleep_time = sleep_time * 2 if sleep_time < 900 else sleep_time
            log_exception("Error Occurred: {0}".format(traceback.format_exc()))
        sleep(1)
    logger.info("stock_zh_a_min_sina已停止")


@click.command()
@click.option("--test/--no-test", default=False)
def main(test: bool):
    stop_event = multiprocessing.Event()

    def handle_sigint(signo, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, handle_sigint)

    processes = [
        multiprocessing.Process(
            target=stock_zh_a_min_em,
            args=(
                stop_event,
                test,
            ),
        ),
        multiprocessing.Process(
            target=stock_zh_a_min_sina,
            args=(
                stop_event,
                test,
            ),
        ),
        multiprocessing.Process(
            target=stock_zh_a_min_tdx,
            args=(
                stop_event,
                test,
            ),
        ),
        multiprocessing.Process(
            target=stock_zh_a_min_symbol_queue_x,
            args=(
                stop_event,
                test,
            ),
        ),
        multiprocessing.Process(
            target=stock_zh_a_min_symbol_queue_y,
            args=(
                stop_event,
                test,
            ),
        ),
    ]
    for process in processes:
        process.start()
    while not stop_event.is_set():
        sleep(1)
    logger.info("行情采集程序停止中...")
    for process in processes:
        process.join()

    logger.info("行情采集已停止")


if __name__ == "__main__":
    main()
