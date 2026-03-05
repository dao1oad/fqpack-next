import datetime
import queue
from concurrent.futures import ThreadPoolExecutor
from threading import Thread, Timer

import pandas as pd
from pytdx.hq import TdxHq_API
from QUANTAXIS.QAUtil.QASetting import stock_ip_list


class QA_Tdx_Executor:
    def __init__(self, thread_num=2, timeout=1, sleep_time=1, *args, **kwargs):
        self.thread_num = thread_num
        self._queue = queue.Queue(maxsize=200)
        self.api_no_connection = TdxHq_API()
        self._api_worker = Thread(target=self.api_worker, args=(), name='API Worker')
        self._api_worker.start()
        self.timeout = timeout
        self.executor = ThreadPoolExecutor(self.thread_num)
        self.sleep_time = sleep_time

    def __getattr__(self, item):
        try:
            api = self.get_available()
            func = api.__getattribute__(item)

            def wrapper(*args, **kwargs):
                res = self.executor.submit(func, *args, **kwargs)
                self._queue.put(api)
                return res

            return wrapper
        except Exception as e:
            raise e

    def _queue_clean(self):
        self._queue = queue.Queue(maxsize=200)

    def _test_speed(self, ip, port=7709):

        api = TdxHq_API(raise_exception=True, auto_retry=False)
        _time = datetime.datetime.now()
        try:
            with api.connect(ip, port, time_out=1):
                res = api.get_security_list(0, 1)
                if len(api.get_security_list(0, 1)) > 800:
                    return (datetime.datetime.now() - _time).total_seconds()
                else:
                    return datetime.timedelta(9, 9, 0).total_seconds()
        except Exception as e:
            return datetime.timedelta(9, 9, 0).total_seconds()

    def get_market(self, code):
        code = str(code)
        if code[0] in ['5', '6', '9'] or code[:3] in [
            "009",
            "126",
            "110",
            "201",
            "202",
            "203",
            "204",
        ]:
            return 1
        return 0

    def get_frequence(self, frequence):
        if frequence in ['day', 'd', 'D', 'DAY', 'Day']:
            frequence = 9
        elif frequence in ['w', 'W', 'Week', 'week']:
            frequence = 5
        elif frequence in ['month', 'M', 'm', 'Month']:
            frequence = 6
        elif frequence in ['Q', 'Quarter', 'q']:
            frequence = 10
        elif frequence in ['y', 'Y', 'year', 'Year']:
            frequence = 11
        elif str(frequence) in ['5', '5m', '5min', 'five']:
            frequence = 0
        elif str(frequence) in ['1', '1m', '1min', 'one']:
            frequence = 8
        elif str(frequence) in ['15', '15m', '15min', 'fifteen']:
            frequence = 1
        elif str(frequence) in ['30', '30m', '30min', 'half']:
            frequence = 2
        elif str(frequence) in ['60', '60m', '60min', '1h']:
            frequence = 3

        return frequence

    @property
    def ipsize(self):
        return len(self._queue.qsize())

    @property
    def api(self):
        return self.get_available()

    def get_available(self):

        if self._queue.empty() is False:
            return self._queue.get_nowait()
        else:
            Timer(0, self.api_worker).start()
            return self._queue.get()

    def api_worker(self):
        if self._queue.qsize() < 80:
            for item in stock_ip_list:
                if self._queue.full():
                    break
                _sec = self._test_speed(ip=item['ip'], port=item['port'])
                if _sec < self.timeout * 3:
                    try:
                        self._queue.put(
                            TdxHq_API(heartbeat=True).connect(
                                ip=item['ip'],
                                port=item['port'],
                                time_out=self.timeout * 2,
                            )
                        )
                    except:
                        pass

    def get_realtime_concurrent(self, code):
        code = [code] if isinstance(code, str) is str else code

        try:
            data = {
                self.get_security_quotes(
                    [(self.get_market(x), x) for x in code[80 * pos : 80 * (pos + 1)]]
                )
                for pos in range(int(len(code) / 80) + 1)
            }
            return (
                pd.concat([self.api_no_connection.to_df(i.result()) for i in data]),
                datetime.datetime.now(),
            )
        except:
            pass

    def get_security_bar_concurrent(self, code, _type, lens):
        try:

            data = {
                self.get_security_bars(
                    self.get_frequence(_type),
                    self.get_market(str(code)),
                    str(code),
                    0,
                    lens,
                )
                for code in code
            }

            return [i.result() for i in data]

        except Exception as e:
            raise e

    def _get_security_bars(self, context, code, _type, lens):
        try:
            _api = self.get_available()
            x = int(lens / 800)
            y = lens % 800
            for i in range(x + (1 if y > 0 else 0)):
                data = _api.get_security_bars(
                    self.get_frequence(_type),
                    self.get_market(str(code)),
                    str(code),
                    i * 800,
                    800,
                )
                if data is not None:
                    context.extend(data)
            if len(context) > 0:
                self._queue.put(_api)
            return context
        except Exception as e:
            raise e

    def get_security_bars(self, code, _type, lens):
        context = []
        try:
            context = self._get_security_bars(context, code, _type, lens)
            return context
        except Exception as e:
            raise e
