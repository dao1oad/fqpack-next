# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import threading
import time
import traceback

import click
from loguru import logger

from freshquant.carnation.param import queryParam
from freshquant.market_data.xtdata.bar_generator import OneMinuteBarGenerator
from freshquant.market_data.xtdata.pools import load_monitor_codes
from freshquant.market_data.xtdata.schema import normalize_prefixed_code


def _to_xt_symbol(code_prefixed: str) -> str:
    s = (code_prefixed or "").lower().strip()
    if len(s) >= 8 and s[:2] in {"sh", "sz", "bj"} and s[2:8].isdigit():
        base = s[2:8]
        mkt = s[:2].upper()
        return f"{base}.{mkt}"
    return s


class TickPump:
    def __init__(self, handler, *, flush_interval_s: float = 0.05):
        self._handler = handler
        self._flush_interval_s = max(0.01, float(flush_interval_s))
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}
        self._stop = threading.Event()
        self._evt = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="TickPump")

    def start(self) -> "TickPump":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._evt.set()
        try:
            self._thread.join(timeout=5)
        except Exception:
            pass

    def submit(self, datas: dict[str, dict]) -> None:
        if not datas:
            return
        with self._lock:
            for code, tick in datas.items():
                if code and tick:
                    self._pending[code] = tick
        self._evt.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._evt.wait(timeout=self._flush_interval_s)
            self._evt.clear()
            if self._stop.is_set():
                break
            with self._lock:
                if not self._pending:
                    continue
                batch = self._pending
                self._pending = {}
            try:
                self._handler(batch)
            except Exception:
                traceback.print_exc()


def start_producer():
    try:
        from xtquant import xtdata  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"xtquant/xtdata not installed: {e}")

    port = int(os.environ.get("XTQUANT_PORT", "58610"))
    xtdata.connect(port=port)

    mode = (
        str(queryParam("monitor.xtdata.mode", "clx_15_30") or "clx_15_30")
        .strip()
        .lower()
    )
    max_symbols = int(queryParam("monitor.xtdata.max_symbols", 50) or 50)
    if max_symbols <= 0:
        max_symbols = 50

    generator = OneMinuteBarGenerator(
        enable_synthetic=True,
        resample_periods_min=[5, 15, 30],
        push_1m=True,
    )

    def _tick_handler(datas):
        generator.on_tick(datas)

    pump = TickPump(_tick_handler, flush_interval_s=0.05).start()

    sub_seq = None
    sub_codes: set[str] = set()

    def _load_codes() -> list[str]:
        return load_monitor_codes(mode=mode, max_symbols=max_symbols)

    def _subscribe(codes_prefixed: list[str]):
        nonlocal sub_seq, sub_codes
        if not codes_prefixed:
            logger.warning("[Producer] empty pool; waiting ...")
            return
        xt_codes = [_to_xt_symbol(c) for c in codes_prefixed]

        def on_data(datas):
            # datas keys are xt symbols; normalize to prefixed for generator
            norm = {
                normalize_prefixed_code(k).lower(): v
                for k, v in (datas or {}).items()
                if k and v
            }
            pump.submit(norm)

        if sub_seq is not None:
            try:
                xtdata.unsubscribe_quote(sub_seq)
            except Exception:
                pass
        sub_seq = xtdata.subscribe_whole_quote(xt_codes, callback=on_data)
        sub_codes = set(codes_prefixed)
        logger.info(
            f"[Producer] subscribed: mode={mode} codes={len(sub_codes)} seq={sub_seq}"
        )

    _subscribe(_load_codes())

    def _pool_monitor_loop():
        while True:
            try:
                time.sleep(30)
                new_list = _load_codes()
                new_set = set(new_list)
                if new_set and new_set != sub_codes:
                    logger.info(
                        f"[Producer] pool changed: {len(sub_codes)} -> {len(new_set)}"
                    )
                    _subscribe(new_list)
            except Exception:
                logger.error(traceback.format_exc())

    t = threading.Thread(target=_pool_monitor_loop, daemon=True, name="PoolMonitor")
    t.start()

    logger.info("[Producer] running; Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("[Producer] stopping ...")
    finally:
        pump.stop()
        generator.stop()
        if sub_seq is not None:
            try:
                xtdata.unsubscribe_quote(sub_seq)
            except Exception:
                pass


@click.command()
def main():
    start_producer()


if __name__ == "__main__":
    main()
