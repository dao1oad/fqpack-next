import concurrent.futures
import os
import traceback
from datetime import datetime

import pandas as pd
import pydash
from loguru import logger
from tqdm import tqdm

from freshquant.chanlun_service import get_data_v3
from freshquant.config import settings
from freshquant.signal.a_stock_common import save_a_stock_signal


def run(symbol, input_period, infile):
    periods = ['1d', '120m', '90m', '60m', '30m', '5m']
    infile = "data_tdx.csv" if infile is None else infile
    stock_list = []
    code_period_list = []
    if symbol is None:
        if pydash.get(settings, "custom.data.dir") is not None:
            data_tdx = pd.read_csv(
                os.path.join(pydash.get(settings, "custom.data.dir"), infile)
            )
            for _, row in data_tdx.iterrows():
                stock_list.append(
                    {"sse": row["code"][:2].lower(), "code": row["code"][3:]}
                )
        for stock in stock_list:
            symbol = "%s%s" % (stock["sse"], stock["code"])
            if input_period is None:
                for period in periods:
                    code_period_list.append(
                        {
                            "sse": stock["sse"],
                            "symbol": symbol,
                            "code": stock["code"],
                            "period": period,
                        }
                    )
            else:
                code_period_list.append(
                    {
                        "sse": stock["sse"],
                        "symbol": symbol,
                        "code": stock["code"],
                        "period": input_period,
                    }
                )
    else:
        sse = symbol[:2]
        code = symbol[2:]
        if input_period is None:
            for period in periods:
                code_period_list.append(
                    {'sse': sse, 'symbol': symbol, 'code': code, 'period': period}
                )
        else:
            code_period_list.append(
                {'sse': sse, 'symbol': symbol, 'code': code, 'period': input_period}
            )
    thread_pool_executor = concurrent.futures.ThreadPoolExecutor()
    tasks = [
        thread_pool_executor.submit(calculate_chanlun_signal, code_period_obj)
        for code_period_obj in code_period_list
    ]
    [
        task.result()
        for task in tqdm(
            concurrent.futures.as_completed(tasks), desc="监控", total=len(tasks)
        )
    ]


def calculate_chanlun_signal(code_period_obj):
    try:
        symbol = code_period_obj["symbol"]
        code = code_period_obj["code"]
        period = code_period_obj["period"]
        resp = get_data_v3(symbol, period, datetime.now().strftime("%Y-%m-%d"))
        signal_map = {
            "rise_break_pivot_gg_sg": "向上突破中枢高高",
            "rise_break_pivot_zg_sg": "向上突破中枢高",
            "rise_break_pivot_zm_sg": "向上突破中枢中线",
            "rise_break_pivot_zd_sg": "向上突破中枢低",
            "mian_ji_di_bei_chi_sg": "MACD面积底背驰",
            "huang_bai_xian_di_bei_chi_sg": "黄白线底背驰",
        }
        signal_dir_map = {
            "buy_zs_huila": "BUY_LONG",
            "sell_zs_huila": "SELL_SHORT",
            "rise_break_pivot_gg_sg": "BUY_LONG",
            "rise_break_pivot_zg_sg": "BUY_LONG",
            "rise_break_pivot_zm_sg": "BUY_LONG",
            "rise_break_pivot_zd_sg": "BUY_LONG",
            "mian_ji_di_bei_chi_sg": "BUY_LONG",
            "huang_bai_xian_di_bei_chi_sg": "BUY_LONG",
            "buy_v_reverse": "BUY_LONG",
            "sell_v_reverse": "SELL_SHORT",
            "buy_five_v_reverse": "BUY_LONG",
            "sell_five_v_reverse": "SELL_SHORT",
            "buy_duan_break": "BUY_LONG",
            "sell_duan_break": "SELL_SHORT",
        }
        all_signals = []
        for signal_type in signal_map:
            signals = resp.get(signal_type)
            if signals is not None:
                for idx in range(len(signals["datetime"])):
                    fire_time = signals["datetime"][idx]
                    all_signals.append(
                        {
                            "fire_time": fire_time,
                            "price": signals["price"][idx],
                            "stop_lose_price": signals["stop_lose_price"][idx],
                            "signal_type": signal_type,
                        }
                    )
        all_signals.sort(key=lambda elem: elem["fire_time"])
        for idx in range(len(all_signals)):
            signal = all_signals[idx]
            fire_time = signal["fire_time"]
            price = signal["price"]
            stop_lose_price = signal["stop_lose_price"]
            signal_type = signal["signal_type"]
            save_a_stock_signal(
                symbol,
                code,
                period,
                signal_map[signal_type],
                fire_time,
                price,
                stop_lose_price,
                signal_dir_map[signal_type],
            )
    except BaseException as e:
        logger.error("Error Occurred: {0}".format(traceback.format_exc()))
