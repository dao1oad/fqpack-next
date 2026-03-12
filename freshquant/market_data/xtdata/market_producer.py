# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import threading
import time
import traceback
from collections import deque

import click
from loguru import logger

from freshquant.carnation.param import queryParam
from freshquant.market_data.xtdata.bar_generator import OneMinuteBarGenerator
from freshquant.market_data.xtdata.constants import tick_queue_key_for_code
from freshquant.market_data.xtdata.pools import (
    load_monitor_codes,
    normalize_xtdata_mode,
)
from freshquant.market_data.xtdata.schema import TickQuoteEvent, normalize_prefixed_code
from freshquant.runtime_observability.logger import RuntimeEventLogger

try:
    from freshquant.database.redis import redis_db  # type: ignore
except Exception:  # pragma: no cover
    redis_db = None  # type: ignore


def _to_xt_symbol(code_prefixed: str) -> str:
    s = (code_prefixed or "").lower().strip()
    if len(s) >= 8 and s[:2] in {"sh", "sz", "bj"} and s[2:8].isdigit():
        base = s[2:8]
        mkt = s[:2].upper()
        return f"{base}.{mkt}"
    return s


def _load_subscription_codes(*, mode: str, max_symbols: int) -> list[str]:
    codes = {
        normalize_prefixed_code(code).lower()
        for code in (load_monitor_codes(mode=mode, max_symbols=max_symbols) or [])
        if code
    }
    codes.discard("")
    return sorted(codes)


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


def _extract_level_price(value) -> float:
    if isinstance(value, (list, tuple)):
        if not value:
            return 0.0
        value = value[0]
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _coerce_tick_time(raw_time) -> int:
    try:
        tick_time = int(raw_time or 0)
    except Exception:
        return 0
    if tick_time >= 1_000_000_000_000:
        return int(tick_time / 1000)
    return tick_time


def _build_tick_quote_event(code_prefixed: str, tick: dict) -> TickQuoteEvent | None:
    code = normalize_prefixed_code(code_prefixed).lower()
    if not code:
        return None
    last_price = _extract_level_price(tick.get("lastPrice"))
    bid1 = _extract_level_price(tick.get("bidPrice") or tick.get("bid1"))
    ask1 = _extract_level_price(tick.get("askPrice") or tick.get("ask1"))
    tick_time = _coerce_tick_time(tick.get("time"))
    if tick_time <= 0:
        return None
    return TickQuoteEvent(
        code=code,
        bid1=bid1,
        ask1=ask1,
        last_price=last_price,
        tick_time=tick_time,
        created_at=time.time(),
    )


def _push_tick_quote_events(datas: dict[str, dict], *, redis_client=redis_db) -> None:
    if not datas or redis_client is None:
        return
    try:
        pipe = redis_client.pipeline()
        pushed = 0
        for code, tick in datas.items():
            event = _build_tick_quote_event(code, tick)
            if event is None:
                continue
            pipe.rpush(
                tick_queue_key_for_code(event.code),
                json.dumps(event.to_dict(), ensure_ascii=False),
            )
            pushed += 1
        if pushed > 0:
            pipe.execute()
    except Exception:
        traceback.print_exc()


def emit_producer_heartbeat(*, runtime_logger=None, **metrics) -> bool:
    return _emit_runtime(
        runtime_logger or _get_runtime_logger(),
        {
            "component": "xt_producer",
            "node": "heartbeat",
            "event_type": "heartbeat",
            "status": "info",
            "metrics": dict(metrics),
            "payload": {},
        },
    )


class ProducerHeartbeatState:
    def __init__(self, *, window_s: float = 300.0):
        self.window_s = max(float(window_s or 300.0), 1.0)
        self._lock = threading.Lock()
        self._batches: deque[tuple[float, int]] = deque()
        self._last_tick_ts: float | None = None

    def record_tick_batch(self, *, tick_count: int, now_ts: float | None = None) -> None:
        count = max(int(tick_count or 0), 0)
        if count <= 0:
            return
        current_ts = float(now_ts if now_ts is not None else time.time())
        with self._lock:
            self._batches.append((current_ts, count))
            self._last_tick_ts = current_ts
            self._prune_locked(current_ts)

    def snapshot(
        self,
        *,
        now_ts: float | None = None,
        subscribed_codes: int = 0,
        connected: bool = True,
    ) -> dict:
        current_ts = float(now_ts if now_ts is not None else time.time())
        with self._lock:
            self._prune_locked(current_ts)
            tick_batches = len(self._batches)
            tick_count = sum(count for _, count in self._batches)
            last_tick_ts = self._last_tick_ts
        return {
            "connected": 1 if connected else 0,
            "subscribed_codes": max(int(subscribed_codes or 0), 0),
            "tick_batches_5m": tick_batches,
            "tick_count_5m": tick_count,
            "rx_age_s": None
            if last_tick_ts is None
            else round(max(current_ts - last_tick_ts, 0.0), 3),
        }

    def _prune_locked(self, now_ts: float) -> None:
        cutoff = float(now_ts) - self.window_s
        while self._batches and self._batches[0][0] < cutoff:
            self._batches.popleft()


def start_producer():
    try:
        from xtquant import xtdata  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"xtquant/xtdata not installed: {e}")

    port = int(os.environ.get("XTQUANT_PORT", "58610"))
    _emit_runtime(
        _get_runtime_logger(),
        {
            "component": "xt_producer",
            "node": "bootstrap",
            "payload": {"port": port},
        },
    )
    xtdata.connect(port=port)

    mode = normalize_xtdata_mode(queryParam("monitor.xtdata.mode", None))
    max_symbols = int(queryParam("monitor.xtdata.max_symbols", 50) or 50)
    if max_symbols <= 0:
        max_symbols = 50
    _emit_runtime(
        _get_runtime_logger(),
        {
            "component": "xt_producer",
            "node": "config_resolve",
            "payload": {"mode": mode, "max_symbols": max_symbols},
        },
    )

    generator = OneMinuteBarGenerator(
        enable_synthetic=True,
        resample_periods_min=[5, 15, 30],
        push_1m=True,
    )

    def _tick_handler(datas):
        generator.on_tick(datas)

    pump = TickPump(_tick_handler, flush_interval_s=0.05).start()
    heartbeat_state = ProducerHeartbeatState(window_s=300.0)

    sub_seq = None
    sub_codes: set[str] = set()
    subscribed_codes = 0

    def _subscribe(codes_prefixed: list[str]):
        nonlocal sub_seq, sub_codes, subscribed_codes
        if not codes_prefixed:
            logger.warning("[Producer] empty pool; waiting ...")
            return
        xt_codes = [_to_xt_symbol(c) for c in codes_prefixed]

        def on_data(datas):
            norm = {
                normalize_prefixed_code(k).lower(): v
                for k, v in (datas or {}).items()
                if k and v
            }
            heartbeat_state.record_tick_batch(tick_count=len(norm))
            _push_tick_quote_events(norm)
            pump.submit(norm)

        if sub_seq is not None:
            try:
                xtdata.unsubscribe_quote(sub_seq)
            except Exception:
                pass
        sub_seq = xtdata.subscribe_whole_quote(xt_codes, callback=on_data)
        sub_codes = set(codes_prefixed)
        subscribed_codes = len(sub_codes)
        _emit_runtime(
            _get_runtime_logger(),
            {
                "component": "xt_producer",
                "node": "subscription_load",
                "payload": {"mode": mode, "codes": len(sub_codes), "seq": sub_seq},
            },
        )
        logger.info(
            f"[Producer] subscribed: mode={mode} codes={len(sub_codes)} seq={sub_seq}"
        )

    _subscribe(_load_subscription_codes(mode=mode, max_symbols=max_symbols))

    heartbeat_stop = threading.Event()

    def _emit_current_heartbeat(now_ts: float | None = None):
        emit_producer_heartbeat(
            runtime_logger=_get_runtime_logger(),
            **heartbeat_state.snapshot(
                now_ts=now_ts,
                subscribed_codes=subscribed_codes,
                connected=True,
            ),
        )

    def _heartbeat_loop():
        last_emit_at = time.time()
        while not heartbeat_stop.wait(timeout=1.0):
            now_ts = time.time()
            if (now_ts - last_emit_at) < 300.0:
                continue
            _emit_current_heartbeat(now_ts)
            last_emit_at = now_ts

    _emit_current_heartbeat()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        daemon=True,
        name="ProducerHeartbeat",
    )
    heartbeat_thread.start()

    def _pool_monitor_loop():
        while True:
            try:
                time.sleep(30)
                new_list = _load_subscription_codes(mode=mode, max_symbols=max_symbols)
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
        heartbeat_stop.set()
        try:
            heartbeat_thread.join(timeout=2)
        except Exception:
            pass
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


def _emit_runtime(runtime_logger, event) -> bool:
    try:
        return bool(runtime_logger.emit(event))
    except Exception:
        return False


_runtime_logger = None


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        _runtime_logger = RuntimeEventLogger("xt_producer")
    return _runtime_logger


if __name__ == "__main__":
    main()
