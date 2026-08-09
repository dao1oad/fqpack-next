import traceback
from datetime import datetime
from time import sleep

import click
from loguru import logger

from freshquant.data.astock.holding import get_stock_holding_codes
from freshquant.market_data.xtdata.pools import (
    LINE_1M_T,
    LINE_5M_NEW_OPEN,
    lines_for_modes,
)
from freshquant.market_data.xtdata.schema import normalize_prefixed_code
from freshquant.pool.general import queryMustPoolCodes
from freshquant.runtime_constants import TZ
from freshquant.signal.a_stock_common import save_a_stock_signal
from freshquant.signal.astock.job.bar_event_listener import BarEventListener
from freshquant.signal.astock.job.monitor_helpers_event import (
    calculate_guardian_signals_latest,
)
from freshquant.strategy.guardian import (
    MUST_POOL_5M_NEW_OPEN_TAG,
    StrategyGuardian,
)
from freshquant.system_settings import system_settings
from freshquant.util.code import normalize_to_base_code
from freshquant.util.period import to_backend_period, to_frontend_period

strategy = StrategyGuardian()
DISABLED_GUARDIAN_SIGNAL_TYPES = {"buy_zs_huila"}
MUST_POOL_5M_NEW_OPEN_SIGNAL_TYPES = {
    "buy_v_reverse",
    "macd_bullish_divergence",
}


def _log_pool_change(old_codes, new_codes):
    removed_codes = set(old_codes) - set(new_codes)
    if removed_codes:
        logger.warning(
            "[Event] pool changed: %d -> %d removed=[%s]",
            len(old_codes),
            len(new_codes),
            ",".join(sorted(removed_codes)),
        )
    else:
        logger.info(
            "[Event] pool changed: %d -> %d",
            len(old_codes),
            len(new_codes),
        )


def monitor_stock_zh_a_min_event_driven() -> None:
    """
    Mode A: Guardian event monitor.

    Subscribe `CHANNEL:BAR_UPDATE` and calculate Guardian signals for current
    holdings on 1-minute bars and enabled must-pool new opens on 5-minute bars.
    """
    trading_mode = bool(getattr(system_settings.monitor, "xtdata_trading_mode", True))
    screening_mode = bool(
        getattr(system_settings.monitor, "xtdata_screening_mode", False)
    )
    enabled_lines = set(
        lines_for_modes(
            trading_mode=trading_mode,
            screening_mode=screening_mode,
        )
    )
    _emit_guardian_bootstrap_event(
        trading_mode=trading_mode,
        screening_mode=screening_mode,
        enabled_lines=sorted(enabled_lines),
    )
    if LINE_1M_T not in enabled_lines and LINE_5M_NEW_OPEN not in enabled_lines:
        logger.warning(
            f"[Event] monitor.xtdata trading_mode={trading_mode}; "
            "trading lines disabled. Exiting."
        )
        return

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

    filter_periods = {
        to_backend_period("1m"),
        to_backend_period("5m"),
    }

    def _load_scope() -> dict[str, set[str]]:
        holding_codes = {
            normalize_to_base_code(code) for code in get_stock_holding_codes() if code
        }
        must_pool_codes = {
            normalize_to_base_code(code) for code in queryMustPoolCodes() if code
        }
        return {
            "holding_codes": {code for code in holding_codes if code.isdigit()},
            "must_pool_codes": {code for code in must_pool_codes if code.isdigit()},
        }

    def _load_codes(scope: dict[str, set[str]]) -> set[str]:
        base_codes = (scope.get("holding_codes") or set()) | (
            scope.get("must_pool_codes") or set()
        )
        return {normalize_prefixed_code(code).lower() for code in base_codes}

    initial_scope = _load_scope()
    codes_lock = {"codes": _load_codes(initial_scope)}
    scope_lock = {"scope": initial_scope}

    def _refresh_codes_loop(listener: BarEventListener) -> None:
        while True:
            try:
                sleep(30)
                new_scope = _load_scope()
                new_codes = _load_codes(new_scope)
                old_codes = codes_lock.get("codes") or set()
                scope_lock["scope"] = new_scope
                if new_codes != old_codes:
                    codes_lock["codes"] = new_codes
                    listener.update_filter_codes(new_codes)
                    _log_pool_change(old_codes, new_codes)
            except Exception:
                logger.error(traceback.format_exc())

    def on_bar_update(code: str, period_backend: str, data: dict) -> None:
        try:
            period_backend = to_backend_period(period_backend)
            if period_backend not in filter_periods:
                return

            bar_ts = int(data.get("_bar_time") or 0)
            if bar_ts <= 0:
                return
            fire_time = datetime.fromtimestamp(bar_ts, tz=TZ)
            period_front = to_frontend_period(period_backend)

            base_code = normalize_to_base_code(code)
            if not base_code or not base_code.isdigit():
                return

            scope = scope_lock.get("scope") or {}
            in_holding = base_code in (scope.get("holding_codes") or set())
            in_must_pool = base_code in (scope.get("must_pool_codes") or set())
            if period_backend == "1min" and LINE_1M_T not in enabled_lines:
                return
            if period_backend == "1min" and not in_holding:
                return
            if period_backend == "5min" and LINE_5M_NEW_OPEN not in enabled_lines:
                return
            if period_backend == "5min" and (in_holding or not in_must_pool):
                return

            signals = calculate_guardian_signals_latest(data=data, fire_time=fire_time)
            if not signals:
                return

            for s in signals:
                tags = list(s.tags or [])
                if period_backend == "1min":
                    if s.signal_type in DISABLED_GUARDIAN_SIGNAL_TYPES:
                        continue
                else:
                    if s.signal_type not in MUST_POOL_5M_NEW_OPEN_SIGNAL_TYPES:
                        continue
                    if MUST_POOL_5M_NEW_OPEN_TAG not in tags:
                        tags.append(MUST_POOL_5M_NEW_OPEN_TAG)
                save_a_stock_signal(
                    code,
                    base_code,
                    period_front,
                    signal_map.get(s.signal_type, s.signal_type),
                    s.fire_time,
                    s.price,
                    s.stop_lose_price,
                    position=signal_dir_map.get(s.signal_type, ""),
                    tags=tags,
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


@click.command()
@click.option(
    "--mode", type=click.Choice(["event"]), default="event", show_default=True
)
def main(mode: str):
    monitor_stock_zh_a_min_event_driven()


def _emit_guardian_bootstrap_event(
    *,
    trading_mode: bool,
    screening_mode: bool,
    enabled_lines: list[str],
) -> bool:
    """启动时记录非敏感有效配置（trading / screening / enabled lines）。"""

    try:
        from freshquant.runtime_observability.logger import RuntimeEventLogger

        return bool(
            RuntimeEventLogger("guardian_event").emit(
                {
                    "component": "guardian_event",
                    "node": "bootstrap",
                    "payload": {
                        "trading_mode": bool(trading_mode),
                        "screening_mode": bool(screening_mode),
                        "enabled_lines": list(enabled_lines or []),
                    },
                }
            )
        )
    except Exception:  # pragma: no cover - 观测路径失败不影响主链
        return False


if __name__ == "__main__":
    main()
