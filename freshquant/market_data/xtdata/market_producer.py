# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import threading
import time
import traceback
from collections import deque
from datetime import datetime

import click
from loguru import logger

from freshquant.bootstrap_config import bootstrap_config
from freshquant.market_data.xtdata.bar_generator import OneMinuteBarGenerator
from freshquant.market_data.xtdata.constants import tick_queue_key_for_code
from freshquant.market_data.xtdata.pools import (
    load_monitor_codes,
    normalize_xtdata_mode,
)
from freshquant.market_data.xtdata.schema import TickQuoteEvent, normalize_prefixed_code
from freshquant.runtime_constants import TZ
from freshquant.runtime_observability.logger import RuntimeEventLogger
from freshquant.system_settings import system_settings

try:
    from freshquant.database.redis import redis_db  # type: ignore
except Exception:  # pragma: no cover
    redis_db = None  # type: ignore

PRODUCER_HEARTBEAT_INTERVAL_S = 300.0
PRODUCER_POOL_REFRESH_INTERVAL_S = 30.0
PRODUCER_STALE_RX_THRESHOLD_S = 120.0
PRODUCER_STALE_RETRY_INTERVAL_S = 30.0
PRODUCER_STALE_RECONNECT_EVERY = 2
PRODUCER_TICK_QUOTE_MAX_PENDING_BATCHES = 2048
PRODUCER_XTDATA_RETRY_DELAY_S = 5.0
PRODUCER_XTDATA_RETRY_DELAY_MAX_S = 60.0


def _to_xt_symbol(code_prefixed: str) -> str:
    s = (code_prefixed or "").lower().strip()
    if len(s) >= 8 and s[:2] in {"sh", "sz", "bj"} and s[2:8].isdigit():
        base = s[2:8]
        mkt = s[:2].upper()
        return f"{base}.{mkt}"
    return s


def _load_subscription_codes(*, mode: str, max_symbols: int) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for raw_code in load_monitor_codes(mode=mode, max_symbols=max_symbols) or []:
        code = normalize_prefixed_code(raw_code).lower()
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


def resolve_producer_runtime_config(
    *, settings_provider=None, bootstrap_provider=None
) -> dict[str, int | str]:
    settings_provider = settings_provider or system_settings
    bootstrap_provider = bootstrap_provider or bootstrap_config
    mode = normalize_xtdata_mode(
        getattr(settings_provider.monitor, "xtdata_mode", None)
    )
    try:
        max_symbols = int(
            getattr(settings_provider.monitor, "xtdata_max_symbols", 50) or 50
        )
    except (TypeError, ValueError):
        max_symbols = 50
    if max_symbols <= 0:
        max_symbols = 50
    try:
        port = int(getattr(bootstrap_provider.xtdata, "port", 58610) or 58610)
    except (TypeError, ValueError):
        port = 58610
    return {
        "port": port,
        "mode": mode,
        "max_symbols": max_symbols,
    }


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


class AsyncBatchQueue:
    def __init__(self, handler, *, max_pending_batches: int = 2048, name: str):
        self._handler = handler
        self._max_pending_batches = max(int(max_pending_batches or 0), 1)
        self._lock = threading.Lock()
        self._pending: deque[object] = deque()
        self._stop = threading.Event()
        self._evt = threading.Event()
        self._dropped_batches = 0
        self._thread = threading.Thread(target=self._run, daemon=True, name=name)

    def start(self) -> "AsyncBatchQueue":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._evt.set()
        try:
            self._thread.join(timeout=5)
        except Exception:
            pass

    def submit(self, batch) -> None:
        if not batch:
            return
        with self._lock:
            if len(self._pending) >= self._max_pending_batches:
                self._pending.popleft()
                self._dropped_batches += 1
            self._pending.append(batch)
        self._evt.set()

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "pending_batches": len(self._pending),
                "dropped_batches": self._dropped_batches,
            }

    def _pop_next(self):
        with self._lock:
            if not self._pending:
                return None
            return self._pending.popleft()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._evt.wait(timeout=0.2)
            self._evt.clear()
            if self._stop.is_set():
                break
            while True:
                batch = self._pop_next()
                if batch is None:
                    break
                try:
                    self._handler(batch)
                except Exception:
                    traceback.print_exc()

        while True:
            batch = self._pop_next()
            if batch is None:
                break
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


def _build_tick_quote_payloads(datas: dict[str, dict]) -> list[tuple[str, str]]:
    payloads: list[tuple[str, str]] = []
    for code, tick in (datas or {}).items():
        event = _build_tick_quote_event(code, tick)
        if event is None:
            continue
        payloads.append(
            (
                tick_queue_key_for_code(event.code),
                json.dumps(event.to_dict(), ensure_ascii=False),
            )
        )
    return payloads


def _push_tick_quote_payloads(
    payloads: list[tuple[str, str]], *, redis_client=redis_db
) -> None:
    if not payloads or redis_client is None:
        return
    try:
        pipe = redis_client.pipeline()
        for queue_key, payload in payloads:
            pipe.rpush(queue_key, payload)
        pipe.execute()
    except Exception:
        traceback.print_exc()


def _push_tick_quote_events(datas: dict[str, dict], *, redis_client=redis_db) -> None:
    _push_tick_quote_payloads(
        _build_tick_quote_payloads(datas), redis_client=redis_client
    )


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

    def record_tick_batch(
        self, *, tick_count: int, now_ts: float | None = None
    ) -> None:
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
            "rx_age_s": (
                None
                if last_tick_ts is None
                else round(max(current_ts - last_tick_ts, 0.0), 3)
            ),
        }

    def _prune_locked(self, now_ts: float) -> None:
        cutoff = float(now_ts) - self.window_s
        while self._batches and self._batches[0][0] < cutoff:
            self._batches.popleft()


def _is_cn_trading_session(now_dt: datetime | None = None) -> bool:
    dt = now_dt or datetime.now(tz=TZ)
    if dt.weekday() >= 5:
        return False
    t = dt.time()
    return (
        (t >= datetime(dt.year, dt.month, dt.day, 9, 30).time())
        and (t <= datetime(dt.year, dt.month, dt.day, 11, 30).time())
        or (t >= datetime(dt.year, dt.month, dt.day, 13, 0).time())
        and (t <= datetime(dt.year, dt.month, dt.day, 15, 0).time())
    )


class ProducerRecoveryGuard:
    def __init__(
        self,
        *,
        stale_after_s: float = PRODUCER_STALE_RX_THRESHOLD_S,
        retry_interval_s: float = PRODUCER_STALE_RETRY_INTERVAL_S,
        reconnect_every: int = PRODUCER_STALE_RECONNECT_EVERY,
    ):
        self.stale_after_s = max(float(stale_after_s or 0.0), 1.0)
        self.retry_interval_s = max(float(retry_interval_s or 0.0), 1.0)
        self.reconnect_every = max(int(reconnect_every or 0), 1)
        self._last_attempt_at = 0.0
        self._stale_attempts = 0

    def next_action(
        self, *, now_ts: float, now_dt: datetime, snapshot: dict
    ) -> str | None:
        if not self._is_stale_snapshot(now_dt=now_dt, snapshot=snapshot):
            self._stale_attempts = 0
            return None

        current_ts = float(now_ts)
        if (current_ts - self._last_attempt_at) < self.retry_interval_s:
            return None

        self._last_attempt_at = current_ts
        self._stale_attempts += 1
        if (self._stale_attempts % self.reconnect_every) == 0:
            return "reconnect"
        return "resubscribe"

    def _is_stale_snapshot(self, *, now_dt: datetime, snapshot: dict) -> bool:
        if not _is_cn_trading_session(now_dt):
            return False
        if int(snapshot.get("connected") or 0) <= 0:
            return False
        if int(snapshot.get("subscribed_codes") or 0) <= 0:
            return False
        rx_age_s = snapshot.get("rx_age_s")
        if rx_age_s is None:
            return False
        try:
            return float(rx_age_s) >= self.stale_after_s
        except Exception:
            return False


def start_producer():
    try:
        from xtquant import xtdata  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"xtquant/xtdata not installed: {e}")

    runtime_config = resolve_producer_runtime_config()
    port = int(runtime_config["port"])
    _emit_runtime(
        _get_runtime_logger(),
        {
            "component": "xt_producer",
            "node": "bootstrap",
            "payload": {"port": port},
        },
    )
    xtdata.connect(port=port)

    mode = str(runtime_config["mode"])
    max_symbols = int(runtime_config["max_symbols"])
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
    tick_quote_queue = AsyncBatchQueue(
        _push_tick_quote_payloads,
        max_pending_batches=PRODUCER_TICK_QUOTE_MAX_PENDING_BATCHES,
        name="TickQuoteWriter",
    ).start()
    heartbeat_state = ProducerHeartbeatState(window_s=300.0)
    recovery_guard = ProducerRecoveryGuard()

    sub_seq = None
    sub_codes: set[str] = set()
    subscribed_codes = 0
    sub_lock = threading.RLock()

    def _subscribe(codes_prefixed: list[str]):
        nonlocal sub_seq, sub_codes, subscribed_codes
        with sub_lock:
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
                tick_quote_queue.submit(_build_tick_quote_payloads(norm))
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
        with sub_lock:
            current_subscribed_codes = subscribed_codes
        queue_snapshot = tick_quote_queue.snapshot()
        emit_producer_heartbeat(
            runtime_logger=_get_runtime_logger(),
            **heartbeat_state.snapshot(
                now_ts=now_ts,
                subscribed_codes=current_subscribed_codes,
                connected=True,
            ),
            tick_quote_pending_batches=queue_snapshot["pending_batches"],
            tick_quote_dropped_batches=queue_snapshot["dropped_batches"],
        )

    def _emit_recovery_event(*, action: str, status: str, rx_age_s, message: str):
        _emit_runtime(
            _get_runtime_logger(),
            {
                "component": "xt_producer",
                "node": "subscription_guard",
                "event_type": "trace_step",
                "status": status,
                "reason_code": "stale_rx",
                "message": message,
                "metrics": {
                    "rx_age_s": rx_age_s,
                },
                "payload": {
                    "action": action,
                },
            },
        )

    def _attempt_recovery(*, action: str, rx_age_s):
        try:
            with sub_lock:
                current_codes = sorted(sub_codes)
            if not current_codes:
                current_codes = _load_subscription_codes(
                    mode=mode, max_symbols=max_symbols
                )
            if not current_codes:
                _emit_recovery_event(
                    action=action,
                    status="warning",
                    rx_age_s=rx_age_s,
                    message="[Producer] stale subscription recovery skipped: empty pool",
                )
                return
            if action == "reconnect":
                xtdata.connect(port=port)
            _subscribe(current_codes)
            _emit_recovery_event(
                action=action,
                status="warning",
                rx_age_s=rx_age_s,
                message=(
                    f"[Producer] stale subscription recovery triggered: action={action}"
                ),
            )
        except Exception:
            logger.error(traceback.format_exc())
            _emit_recovery_event(
                action=action,
                status="error",
                rx_age_s=rx_age_s,
                message=f"[Producer] stale subscription recovery failed: action={action}",
            )

    def _heartbeat_loop():
        last_emit_at = time.time()
        while not heartbeat_stop.wait(timeout=1.0):
            now_ts = time.time()
            now_dt = datetime.now(tz=TZ)
            with sub_lock:
                current_subscribed_codes = subscribed_codes
            snapshot = heartbeat_state.snapshot(
                now_ts=now_ts,
                subscribed_codes=current_subscribed_codes,
                connected=True,
            )
            action = recovery_guard.next_action(
                now_ts=now_ts,
                now_dt=now_dt,
                snapshot=snapshot,
            )
            if action is not None:
                _attempt_recovery(
                    action=action,
                    rx_age_s=snapshot.get("rx_age_s"),
                )
            if (now_ts - last_emit_at) >= PRODUCER_HEARTBEAT_INTERVAL_S:
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
                time.sleep(PRODUCER_POOL_REFRESH_INTERVAL_S)
                new_list = _load_subscription_codes(mode=mode, max_symbols=max_symbols)
                new_set = set(new_list)
                with sub_lock:
                    current_sub_codes = set(sub_codes)
                if new_set and new_set != current_sub_codes:
                    logger.info(
                        f"[Producer] pool changed: {len(current_sub_codes)} -> {len(new_set)}"
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
        tick_quote_queue.stop()
        pump.stop()
        generator.stop()
        if sub_seq is not None:
            try:
                xtdata.unsubscribe_quote(sub_seq)
            except Exception:
                pass


@click.command()
def main():
    run_producer_with_xtdata_retry()


def run_producer_with_xtdata_retry(
    *,
    start_fn=None,
    sleep_fn=time.sleep,
    retry_delay_seconds: float = PRODUCER_XTDATA_RETRY_DELAY_S,
    retry_delay_max_seconds: float = PRODUCER_XTDATA_RETRY_DELAY_MAX_S,
):
    start_fn = start_fn or start_producer
    delay_seconds = retry_delay_seconds
    while True:
        try:
            return start_fn()
        except Exception as error:
            if not _is_retryable_xtdata_error(error):
                raise
            logger.warning(
                "[Producer] XTData unavailable; retrying in %.1f seconds: %s",
                delay_seconds,
                error,
            )
            sleep_fn(delay_seconds)
            delay_seconds = min(delay_seconds * 2, retry_delay_max_seconds)


def _is_retryable_xtdata_error(error: Exception) -> bool:
    message = str(error or "")
    normalized = message.lower()
    if normalized.startswith("xtquant connect failed:") or normalized.startswith(
        "xtquant subscribe failed:"
    ):
        return True
    if "无法连接xtquant" in message or "鏃犳硶杩炴帴xtquant" in message:
        return True
    return "xtquant" in normalized and "qmt" in normalized


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
