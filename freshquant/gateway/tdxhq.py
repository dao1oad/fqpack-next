# -*- coding:utf-8 -*-

import argparse
import asyncio
import datetime
import queue
import traceback
from concurrent.futures import ThreadPoolExecutor
from threading import Timer

import tornado.ioloop
import tornado.web
from loguru import logger
from pytdx.exhq import TdxExHq_API
from pytdx.hq import TdxHq_API
from QUANTAXIS.QAUtil.QASetting import future_ip_list, stock_ip_list
from tornado.escape import json_encode

from freshquant.basic.singleton_type import SingletonType


class TdxHqExecutor(metaclass=SingletonType):
    def __init__(self, thread_num=5, timeout=1, sleep_time=1, *args, **kwargs):
        self.executor = ThreadPoolExecutor(thread_num)
        self._queue = queue.Queue(maxsize=200)
        self.timeout = timeout
        self.sleep_time = sleep_time
        Timer(0, self.api_worker).start()

    def __getattr__(self, item):
        try:
            api = self.get_available()
            func = api.__getattribute__(item)

            def wrapper(*args, **kwargs):
                f = self.executor.submit(func, *args, **kwargs)
                try:
                    result = f.result()
                    if result is not None and len(result) > 0:
                        self._queue.put(api)
                    return result
                except Exception as e:
                    raise e

            return wrapper
        except Exception as e:
            logger.error("Error Occurred: {0}".format(traceback.format_exc()))
            raise e

    def _test_speed(self, ip, port=7709):
        api = TdxHq_API(raise_exception=True, auto_retry=False)
        _time = datetime.datetime.now()
        try:
            with api.connect(ip, port, time_out=1):
                if len(api.get_security_list(0, 1)) > 800:
                    return (datetime.datetime.now() - _time).total_seconds()
                else:
                    return datetime.timedelta(9, 9, 0).total_seconds()
        except Exception as e:
            return datetime.timedelta(9, 9, 0).total_seconds()

    def get_available(self):
        if self._queue.empty():
            Timer(0, self.api_worker).start()
            return self._queue.get()
        else:
            return self._queue.get_nowait()

    def api_worker(self):
        if self._queue.qsize() < 80:
            for item in stock_ip_list:
                if self._queue.full():
                    break
                _sec = self._test_speed(ip=item['ip'], port=item['port'])
                if _sec < self.timeout * 3:
                    try:
                        api = TdxHq_API(multithread=True, heartbeat=True)
                        api.connect(
                            ip=item['ip'], port=item['port'], time_out=self.timeout * 2
                        )
                        self._queue.put(api)
                    except:
                        pass


class TdxExHqExecutor(metaclass=SingletonType):
    def __init__(self, thread_num=5, timeout=1, sleep_time=1, *args, **kwargs):
        self.executor = ThreadPoolExecutor(thread_num)
        self._queue = queue.Queue(maxsize=200)
        self.timeout = timeout
        self.sleep_time = sleep_time
        Timer(0, self.api_worker).start()

    def __getattr__(self, item):
        try:
            api = self.get_available()
            func = api.__getattribute__(item)

            def wrapper(*args, **kwargs):
                f = self.executor.submit(func, *args, **kwargs)
                try:
                    result = f.result()
                    if result is not None and len(result) > 0:
                        self._queue.put(api)
                    return result
                except Exception as e:
                    raise e

            return wrapper
        except Exception as e:
            logger.error("Error Occurred: {0}".format(traceback.format_exc()))
            raise e

    def _test_speed(self, ip, port=7727):
        api = TdxExHq_API(raise_exception=True, auto_retry=False)
        _time = datetime.datetime.now()
        try:
            with api.connect(ip, port, time_out=1):
                if len(api.get_instrument_info(0)) > 0:
                    return (datetime.datetime.now() - _time).total_seconds()
                else:
                    return datetime.timedelta(9, 9, 0).total_seconds()
        except Exception as e:
            return datetime.timedelta(9, 9, 0).total_seconds()

    def get_available(self):
        if self._queue.empty():
            Timer(0, self.api_worker).start()
            return self._queue.get()
        else:
            return self._queue.get_nowait()

    def api_worker(self):
        if self._queue.qsize() < 80:
            for item in future_ip_list:
                if self._queue.full():
                    break
                _sec = self._test_speed(ip=item['ip'], port=item['port'])
                if _sec < self.timeout * 3:
                    try:
                        api = TdxExHq_API(multithread=True, heartbeat=True)
                        api.connect(
                            ip=item['ip'], port=item['port'], time_out=self.timeout * 2
                        )
                        self._queue.put(api)
                    except:
                        pass


def get_security_quotes(securities):
    return TdxHqExecutor().get_security_quotes(securities)


def get_security_bars(category: int, market: int, code: str, start: int, count: int):
    return TdxHqExecutor().get_security_bars(category, market, code, start, count)


def get_security_count(market: int):
    return TdxHqExecutor().get_security_count(market)


def get_security_list(market: int, start: int):
    return TdxHqExecutor().get_security_list(market, start)


def get_index_bars(category: int, market: int, code: str, start: int, count: int):
    return TdxHqExecutor().get_index_bars(category, market, code, start, count)


def get_minute_time_data(market: int, code: str):
    return TdxHqExecutor().get_minute_time_data(market, code)


def get_history_minute_time_data(market: int, code: str, date: int):
    return TdxHqExecutor().get_history_minute_time_data(market, code, date)


def get_transaction_data(market: int, code: str, start: int, count: int):
    return TdxHqExecutor().get_transaction_data(market, code, start, count)


def get_history_transaction_data(
    market: int, code: str, start: int, count: int, date: int
):
    return TdxHqExecutor().get_history_transaction_data(
        market, code, start, count, date
    )


def get_company_info_category(market: int, code: str):
    return TdxHqExecutor().get_company_info_category(market, code)


def get_company_info_content(
    market: int, code: str, filename: str, start: int, count: int
):
    return TdxHqExecutor().get_company_info_content(
        market, code, filename, start, count
    )


def get_xdxr_info(market: int, code: str):
    return TdxHqExecutor().get_xdxr_info(market, code)


def get_finance_info(market: int, code: str):
    return TdxHqExecutor().get_finance_info(market, code)


def get_k_data(code: str, start: str, end: str):
    return TdxHqExecutor().get_k_data(code, start, end)


def get_and_parse_block_info(block: str):
    return TdxHqExecutor().get_and_parse_block_info(block)


def ex_get_markets():
    return TdxExHqExecutor().get_markets()


def ex_get_instrument_count():
    return TdxExHqExecutor().get_instrument_count()


def ex_get_instrument_quote(market: int, code: str):
    return TdxExHqExecutor().get_instrument_quote(market, code)


def ex_get_instrument_bars(
    category: int, market: int, code: str, start: int = 0, count: int = 700
):
    return TdxExHqExecutor().get_instrument_bars(category, market, code, start, count)


def ex_get_minute_time_data(market: int, code: str):
    return TdxExHqExecutor().get_minute_time_data(market, code)


def ex_get_history_minute_time_data(market: int, code: str, date: int):
    return TdxExHqExecutor().get_history_minute_time_data(market, code, date)


def ex_get_transaction_data(market: int, code: str, start: int = 0, count: int = 1800):
    return TdxExHqExecutor().get_transaction_data(market, code, start, count)


def ex_get_history_transaction_data(
    market: int, code: str, date: int, start: int = 0, count: int = 1800
):
    return TdxExHqExecutor().get_history_transaction_data(
        market, code, date, start, count
    )


def ex_get_history_instrument_bars_range(market: int, code: str, start: int, end: int):
    return TdxExHqExecutor().get_history_instrument_bars_range(market, code, start, end)


def ex_get_instrument_info(start: int, count: int = 100):
    return TdxExHqExecutor().get_instrument_info(start, count)


def ex_get_instrument_quote_list(
    market: int, category: int, start: int = 0, count: int = 80
):
    return TdxExHqExecutor().get_instrument_quote_list(market, category, start, count)


class GetSecurityQuotesHandler(tornado.web.RequestHandler):
    async def get(self):
        codes = self.get_argument("codes")
        result = get_security_quotes(
            [(int(code[0:1]), code[1:]) for code in codes.split(",")]
        )
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class GetSecurityBarsHandler(tornado.web.RequestHandler):
    async def get(self):
        category = int(self.get_argument("category"))
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        start = int(self.get_argument("start"))
        count = int(self.get_argument("count"))
        result = get_security_bars(category, market, code, start, count)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class GetSecurityCountHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        result = get_security_count(market)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class GetSecurityListHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        start = int(self.get_argument("start"))
        result = get_security_list(market, start)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class GetIndexBarsHandler(tornado.web.RequestHandler):
    async def get(self):
        category = int(self.get_argument("category"))
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        start = int(self.get_argument("start"))
        count = int(self.get_argument("count"))
        result = get_index_bars(category, market, code, start, count)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class GetMinuteTimeDataHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        result = get_minute_time_data(market, code)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class GetHistoryMinuteTimeDataHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        date = int(self.get_argument("date"))
        result = get_history_minute_time_data(market, code, date)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class GetTransactionDataHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        start = int(self.get_argument("start"))
        count = int(self.get_argument("count"))
        result = get_transaction_data(market, code, start, count)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class GetHistoryTransactionDataHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        start = int(self.get_argument("start"))
        count = int(self.get_argument("count"))
        date = int(self.get_argument("date"))
        result = get_history_transaction_data(market, code, start, count, date)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class GetCompanyInfoCategoryHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        result = get_company_info_category(market, code)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class GetCompanyInfoContentHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        filename = self.get_argument("filename")
        start = int(self.get_argument("start"))
        count = int(self.get_argument("count"))
        result = get_company_info_content(market, code, filename, start, count)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class GetXdxrInfoHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        result = get_xdxr_info(market, code)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class GetKDataHandler(tornado.web.RequestHandler):
    async def get(self):
        code = self.get_argument("code")
        start = self.get_argument("start")
        end = self.get_argument("end")
        result = get_k_data(code, start, end)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class GetFinanceInfoHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        result = get_finance_info(market, code)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class GetAndParseBlockInfoHandler(tornado.web.RequestHandler):
    async def get(self):
        block = self.get_argument("block")
        result = get_and_parse_block_info(block)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class ExGetMarketsHandler(tornado.web.RequestHandler):
    async def get(self):
        result = ex_get_markets()
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class ExGetInstrumentCountHandler(tornado.web.RequestHandler):
    async def get(self):
        result = ex_get_instrument_count()
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class ExGetInstrumentBarsHandler(tornado.web.RequestHandler):
    async def get(self):
        category = int(self.get_argument("category"))
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        start = int(self.get_argument("start", 0))
        count = int(self.get_argument("count", 700))
        result = ex_get_instrument_bars(category, market, code, start, count)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class ExGetInstrumentQuoteHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        result = ex_get_instrument_quote(market, code)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class ExGetMinuteTimeDataHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        result = ex_get_minute_time_data(market, code)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class ExGetHistoryMinuteTimeDataHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        date = int(self.get_argument("date"))
        result = ex_get_history_minute_time_data(market, code, date)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class ExGetTransactionDataHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        start = int(self.get_argument("start", 0))
        count = int(self.get_argument("count", 1800))
        result = ex_get_transaction_data(market, code, start, count)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class ExGetHistoryTransactionDataHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        date = int(self.get_argument("date"))
        start = int(self.get_argument("start", 0))
        count = int(self.get_argument("count", 1800))
        result = ex_get_history_transaction_data(market, code, date, start, count)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class ExGetHistoryInstrumentBarsRangeHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        code = self.get_argument("code")
        start = int(self.get_argument("start"))
        end = int(self.get_argument("end"))
        result = ex_get_history_instrument_bars_range(market, code, start, end)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class ExGetInstrumentInfoHandler(tornado.web.RequestHandler):
    async def get(self):
        start = int(self.get_argument("start"))
        count = int(self.get_argument("count", 100))
        result = ex_get_instrument_info(start, count)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


class ExGetInstrumentQuoteListHandler(tornado.web.RequestHandler):
    async def get(self):
        market = int(self.get_argument("market"))
        category = int(self.get_argument("category"))
        start = int(self.get_argument("start", 0))
        count = int(self.get_argument("count", 80))
        result = ex_get_instrument_quote_list(market, category, start, count)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json_encode(result))


def make_app():
    handlers = [
        (r"/get_security_bars", GetSecurityBarsHandler),
        (r"/get_security_quotes", GetSecurityQuotesHandler),
        (r"/get_security_count", GetSecurityCountHandler),
        (r"/get_security_list", GetSecurityListHandler),
        (r"/get_index_bars", GetIndexBarsHandler),
        (r"/get_minute_time_data", GetMinuteTimeDataHandler),
        (r"/get_history_minute_time_data", GetHistoryMinuteTimeDataHandler),
        (r"/get_transaction_data", GetTransactionDataHandler),
        (r"/get_history_transaction_data", GetHistoryTransactionDataHandler),
        (r"/get_company_info_category", GetCompanyInfoCategoryHandler),
        (r"/get_company_info_content", GetCompanyInfoContentHandler),
        (r"/get_xdxr_info", GetXdxrInfoHandler),
        (r"/get_k_data", GetKDataHandler),
        (r"/get_finance_info", GetFinanceInfoHandler),
        (r"/get_and_parse_block_info", GetAndParseBlockInfoHandler),
        (r"/ex/get_markets", ExGetMarketsHandler),
        (r"/ex/get_instrument_count", ExGetInstrumentCountHandler),
        (r"/ex/get_instrument_bars", ExGetInstrumentBarsHandler),
        (r"/ex/get_instrument_quote", ExGetInstrumentQuoteHandler),
        (r"/ex/get_minute_time_data", ExGetMinuteTimeDataHandler),
        (r"/ex/get_history_minute_time_data", ExGetHistoryMinuteTimeDataHandler),
        (r"/ex/get_transaction_data", ExGetTransactionDataHandler),
        (r"/ex/get_history_transaction_data", ExGetHistoryTransactionDataHandler),
        (
            r"/ex/get_history_instrument_bars_range",
            ExGetHistoryInstrumentBarsRangeHandler,
        ),
        (r"/ex/get_instrument_info", ExGetInstrumentInfoHandler),
        (r"/ex/get_instrument_quote_list", ExGetInstrumentQuoteListHandler),
    ]
    return tornado.web.Application(handlers, autoreload=True, compress_response=True)


def run(port: int = 5001, address: str = "0.0.0.0"):
    asyncio.set_event_loop(asyncio.new_event_loop())
    app = make_app()
    http_server = tornado.httpserver.HTTPServer(app)
    http_server.bind(port=port, address=address)
    http_server.start(1)
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="通达信行情网关")
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        required=False,
        help="端口",
    )
    parser.add_argument(
        "-a",
        "--address",
        type=str,
        required=False,
        help="监听地址",
    )
    args = parser.parse_args()
    run(port=args.port, address=args.address)
