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
from freshquant.chanlun_service import get_data_v2
from freshquant.data.astock.pool import get_stock_monitor_codes
from freshquant.data.trade_date_hist import tool_trade_date_seconds_to_start
from freshquant.instrument.general import query_instrument_type
from freshquant.market_data.xtdata.pools import (
    load_monitor_codes,
    normalize_xtdata_mode,
)
from freshquant.runtime_constants import DT_FORMAT_FULL, TZ
from freshquant.signal.a_stock_common import save_a_stock_signal
from freshquant.signal.astock.job.bar_event_listener import BarEventListener
from freshquant.signal.astock.job.monitor_helpers_event import (
    calculate_guardian_signals_latest,
)
from freshquant.strategy.guardian import StrategyGuardian
from freshquant.system_settings import system_settings
from freshquant.util.code import fq_util_code_append_market_code, normalize_to_base_code
from freshquant.util.period import to_backend_period, to_frontend_period

strategy = StrategyGuardian()


def monitor_stock_zh_a_min(loop):
    periods = ["1m"]
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
                            datetime.now().strftime(DT_FORMAT_FULL),
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


def monitor_stock_zh_a_min_event_driven() -> None:
    """
    Mode A: Guardian-1m

    Subscribe `CHANNEL:BAR_UPDATE` and calculate Guardian signals on 1min updates.
    """
    xt_mode = normalize_xtdata_mode(system_settings.monitor.xtdata_mode)
    if xt_mode != "guardian_1m":
        logger.warning(
            f"[Event] monitor.xtdata.mode={xt_mode}; expected guardian_1m. Exiting."
        )
        return

    max_symbols = int(system_settings.monitor.xtdata_max_symbols or 50)

    signal_map = {
        "buy_zs_huila": "回拉中枢上涨",
        "buy_v_reverse": "V反上涨",
        "macd_bullish_divergence": "看涨背驰",
        "sell_zs_huila": "回拉中枢下跌",
        "sell_v_reverse": "V反下跌",
        "macd_bearish_divergence": "看跌背驰",
    }
    signal_dir_map = {
        "buy_zs_huila": "BUY_LONG",
        "buy_v_reverse": "BUY_LONG",
        "macd_bullish_divergence": "BUY_LONG",
        "sell_zs_huila": "SELL_SHORT",
        "sell_v_reverse": "SELL_SHORT",
        "macd_bearish_divergence": "SELL_SHORT",
    }

    filter_periods = {to_backend_period("1m")}

    def _load_codes() -> set[str]:
        codes = load_monitor_codes(mode="guardian_1m", max_symbols=max_symbols)
        return {c.lower() for c in codes if c}

    codes_lock = {"codes": _load_codes()}

    def _refresh_codes_loop(listener: BarEventListener) -> None:
        while True:
            try:
                sleep(30)
                new_codes = _load_codes()
                old_codes = codes_lock.get("codes") or set()
                if new_codes != old_codes:
                    codes_lock["codes"] = new_codes
                    listener.update_filter_codes(new_codes)
                    logger.info(
                        f"[Event] pool changed: {len(old_codes)} -> {len(new_codes)}"
                    )
            except Exception:
                logger.error(traceback.format_exc())

    def on_bar_update(code: str, period_backend: str, data: dict) -> None:
        try:
            period_backend = to_backend_period(period_backend)
            if period_backend != "1min":
                return

            bar_ts = int(data.get("_bar_time") or 0)
            if bar_ts <= 0:
                return
            fire_time = datetime.fromtimestamp(bar_ts, tz=TZ)
            period_front = to_frontend_period(period_backend)

            base_code = normalize_to_base_code(code)
            if not base_code or not base_code.isdigit():
                return

            signals = calculate_guardian_signals_latest(data=data, fire_time=fire_time)
            if not signals:
                return

            for s in signals:
                save_a_stock_signal(
                    code,
                    base_code,
                    period_front,
                    signal_map.get(s.signal_type, s.signal_type),
                    s.fire_time,
                    s.price,
                    s.stop_lose_price,
                    position=signal_dir_map.get(s.signal_type, ""),
                    tags=s.tags,
                    strategy=strategy,
                    zsdata=data.get("zsdata"),
                    fills=None,
                )
        except Exception:
            logger.error(traceback.format_exc())

    listener = BarEventListener(
        callback=on_bar_update,
        filter_codes=codes_lock.get("codes"),
        filter_periods=filter_periods,
        task_timeout=2.0,
    )
    listener.start()
    logger.info(
        f"[Event] Guardian monitor started: codes={len(codes_lock.get('codes') or [])} periods={sorted(filter_periods)}"
    )

    import threading

    t = threading.Thread(
        target=_refresh_codes_loop,
        args=(listener,),
        daemon=True,
        name="GuardianPoolRefresh",
    )
    t.start()

    try:
        while True:
            sleep(60)
            st = listener.get_stats()
            logger.info(
                "[Event] stats: "
                f"rx={st.get('received')} enq={st.get('enqueued')} ok={st.get('processed')} "
                f"filtered={st.get('filtered')} dropped={st.get('dropped')} err={st.get('errors')} "
                f"q={st.get('queue_depth')}/{st.get('queue_size')} max_q={st.get('queue_max_depth')}"
            )
    except KeyboardInterrupt:
        listener.stop()


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
                fire_time = TZ.localize(signals["datetime"][idx])
                tag = signals["tag"][idx]
                all_signals.append(
                    {
                        "fire_time": fire_time,
                        "discover_time": datetime_helper.now(),
                        "price": (signals.get("price") or signals.get("data"))[idx],
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
@click.option("--mode", type=click.Choice(["poll", "event"]), default="event")
def main(loop, mode):
    if mode == "event":
        monitor_stock_zh_a_min_event_driven()
    else:
        job(loop)


if __name__ == "__main__":
    main()
