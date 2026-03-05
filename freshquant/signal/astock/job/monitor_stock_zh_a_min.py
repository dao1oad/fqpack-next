import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from time import sleep

import click
import durationpy
import pydash
from et_stopwatch import Stopwatch
from loguru import logger

import freshquant.util.datetime_helper as datetime_helper
from freshquant.carnation.param import queryParam
from freshquant.chanlun_service import get_data_v2
from freshquant.config import cfg
from freshquant.data.astock.pool import get_stock_monitor_codes
from freshquant.data.trade_date_hist import tool_trade_date_seconds_to_start
from freshquant.instrument.general import query_instrument_type
from freshquant.signal.a_stock_common import save_a_stock_signal
from freshquant.strategy.guardian import StrategyGuardian
from freshquant.util.code import fq_util_code_append_market_code

strategy = StrategyGuardian()


def monitor_stock_zh_a_min(loop):
    periods = queryParam("monitor.stock.periods", ["1m"])
    executor = ThreadPoolExecutor()

    while True:
        try:
            if loop:
                seconds = tool_trade_date_seconds_to_start()
                if seconds > 0:
                    seconds = min(seconds, 900)
                    logger.info(
                        "%s from now on, %s sleep %s to resume"
                        % (
                            datetime.now().strftime(cfg.DT_FORMAT_FULL),
                            "监控持仓股票信号",
                            durationpy.to_str(timedelta(seconds=seconds)),
                        )
                    )
                    sleep(seconds)
                    if tool_trade_date_seconds_to_start() > 0:
                        continue
            stop_watch = Stopwatch("计算信号")
            codes = get_stock_monitor_codes()
            stocks = (
                pydash.chain(codes)
                .flat_map(
                    lambda code: [
                        {
                            "code": code,
                            "symbol": fq_util_code_append_market_code(
                                code, upper_case=False
                            ),
                            "period": period,
                        }
                        for period in periods
                    ]
                )
                .value()
            )
            tasks = [
                executor.submit(
                    calculate_and_notify,
                    stock["symbol"],
                    stock["code"],
                    stock["period"],
                )
                for stock in stocks
                if query_instrument_type(stock["code"])
            ]
            [task.result() for task in tasks]
            stop_watch.stop()
            logger.info("%d个股票%s" % (len(stocks), stop_watch))
        except (Exception, KeyboardInterrupt, SystemExit) as e:
            if isinstance(e, KeyboardInterrupt) or isinstance(e, SystemExit):
                break
            logger.error(traceback.format_exc())
        if loop:
            sleep(30)
        else:
            break


def calculate_and_notify(symbol, code, period):
    try:
        resp = get_data_v2(symbol, period, datetime.now().strftime("%Y-%m-%d"))

        # 监控的信号类型（保持不变）
        signal_map = {
            "buy_zs_huila": "回拉中枢上涨",
            "buy_v_reverse": "V反上涨",
            "macd_bullish_divergence": "看涨背驰",
            "sell_zs_huila": "回拉中枢下跌",
            "sell_v_reverse": "V反下跌",
            "macd_bearish_divergence": "看跌背驰",
        }
        # 修复：只保留 signal_map 中有的信号类型
        signal_dir_map = {
            "buy_zs_huila": "BUY_LONG",
            "buy_v_reverse": "BUY_LONG",
            "macd_bullish_divergence": "BUY_LONG",
            "sell_zs_huila": "SELL_SHORT",
            "sell_v_reverse": "SELL_SHORT",
            "macd_bearish_divergence": "SELL_SHORT",
        }

        all_signals = []
        for signal_type in signal_map:
            signals = resp[signal_type]
            for idx in range(len(signals["datetime"])):
                fire_time = cfg.TZ.localize(signals["datetime"][idx])
                tag = signals["tag"][idx]
                all_signals.append(
                    {
                        "fire_time": fire_time,
                        "discover_time": datetime_helper.now(),
                        "price": (signals.get('price') or signals.get('data'))[idx],
                        "stop_lose_price": signals["stop_lose_price"][idx],
                        "tags": [] if tag is None else tag.split(","),
                        "signal_type": signal_type,
                    }
                )
        all_signals.sort(key=lambda elem: elem["fire_time"])
        for idx in range(len(all_signals)):
            signal = all_signals[idx]
            fire_time = signal["fire_time"]
            price = signal["price"]
            stop_lose_price = signal["stop_lose_price"]
            tags = signal["tags"]
            signal_type = signal["signal_type"]
            save_a_stock_signal(
                symbol,
                code,
                period,
                signal_map[signal_type],
                fire_time,
                price,
                stop_lose_price,
                position=signal_dir_map[signal_type],
                tags=tags,
                strategy=strategy,
                zsdata=resp["zsdata"],
                fills=resp["stock_fills"],
            )
    except (Exception, KeyboardInterrupt, SystemExit):
        logger.error(traceback.format_exc())


def job(loop):
    monitor_stock_zh_a_min(loop)


@click.command()
@click.option("--loop/--no-loop", default=True)
def main(loop):
    job(loop)


if __name__ == "__main__":
    main()
