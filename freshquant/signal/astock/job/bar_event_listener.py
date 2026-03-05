# -*- coding: utf-8 -*-
"""
Redis Pub/Sub 实时 K 线结构事件监听器。

Consumer（fullcalc）会向 `CHANNEL:BAR_UPDATE` 推送结构数据，payload 形如：

{
  "code": "sz000001",
  "period": "1m" | "1min" | ...,
  "data": { ... chanlun_data ... }
}

本模块负责：
- 订阅 channel
- 解析/归一化 code/period
- 过滤（可选）
- 通过 worker pool 调用回调，避免阻塞 pubsub listen loop
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from loguru import logger

from freshquant.market_data.xtdata.schema import normalize_prefixed_code
from freshquant.util.period import PUBSUB_CHANNEL, to_backend_period

try:
    from freshquant.database.redis import redis_db  # type: ignore
except Exception:  # pragma: no cover
    redis_db = None  # type: ignore


@dataclass(frozen=True)
class BarUpdate:
    code: str
    period: str  # backend period, e.g. 1min/5min/15min/30min
    data: dict[str, Any]


def parse_bar_update_message(raw: str | bytes) -> BarUpdate | None:
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    code = payload.get("code") or payload.get("symbol") or ""
    period = payload.get("period") or ""
    data = payload.get("data") or {}
    if not code or not period or not isinstance(data, dict):
        return None
    return BarUpdate(
        code=normalize_prefixed_code(str(code)).lower(),
        period=to_backend_period(str(period)),
        data=data,
    )


class BarEventListener:
    def __init__(
        self,
        callback: Callable[[str, str, dict[str, Any]], None],
        *,
        filter_codes: Optional[set[str]] = None,
        filter_periods: Optional[set[str]] = None,
        channel: str = PUBSUB_CHANNEL,
        worker_num: Optional[int] = None,
        queue_size: int = 20000,
        enqueue_timeout: float = 3.0,
        task_timeout: Optional[float] = None,
    ):
        self.callback = callback
        self.filter_codes = (
            {normalize_prefixed_code(c).lower() for c in (filter_codes or set()) if c}
            if filter_codes is not None
            else None
        )
        self.filter_periods = (
            {to_backend_period(p) for p in (filter_periods or set()) if p}
            if filter_periods is not None
            else None
        )
        self.channel = channel
        cpu_cnt = os.cpu_count() or 8
        self.worker_num = worker_num if worker_num is not None else min(32, max(8, cpu_cnt))
        self.queue_size = max(1000, int(queue_size))
        self.enqueue_timeout = max(0.0, float(enqueue_timeout))
        self.task_timeout = task_timeout

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pubsub = None
        self._queue: queue.Queue = queue.Queue(maxsize=self.queue_size)
        self._workers: list[threading.Thread] = []
        self._reconnect_interval_s = 5

        self._stats_lock = threading.Lock()
        self._stats: dict[str, int] = {
            "received": 0,
            "enqueued": 0,
            "filtered": 0,
            "processed": 0,
            "dropped": 0,
            "errors": 0,
        }
        self._queue_max_depth = 0

    def start(self) -> None:
        if self._running:
            logger.warning("BarEventListener already running")
            return
        self._running = True

        for idx in range(self.worker_num):
            t = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name=f"BarEventWorker-{idx}",
            )
            t.start()
            self._workers.append(t)
        self._thread = threading.Thread(target=self._listen_loop, daemon=True, name="BarEventListener")
        self._thread.start()
        logger.info(f"BarEventListener started: channel={self.channel} workers={self.worker_num} queue={self.queue_size}")

    def stop(self) -> None:
        self._running = False
        if self._pubsub is not None:
            try:
                self._pubsub.unsubscribe()
                self._pubsub.close()
            except Exception:
                pass

        for _ in self._workers:
            try:
                self._queue.put_nowait(None)
            except Exception:
                break

        t = self._thread
        if t is not None:
            t.join(timeout=5)
        for w in self._workers:
            w.join(timeout=5)
        logger.info(f"BarEventListener stopped: {self.get_stats()}")

    def get_stats(self) -> dict[str, int]:
        with self._stats_lock:
            stats = dict(self._stats)
        stats.update(
            {
                "queue_depth": self._queue.qsize(),
                "queue_max_depth": int(self._queue_max_depth),
                "queue_size": int(self.queue_size),
                "worker_num": int(self.worker_num),
            }
        )
        return stats

    def update_filter_codes(self, codes: Optional[set[str]]) -> None:
        self.filter_codes = {normalize_prefixed_code(c).lower() for c in (codes or set()) if c} if codes is not None else None

    def update_filter_periods(self, periods: Optional[set[str]]) -> None:
        self.filter_periods = {to_backend_period(p) for p in (periods or set()) if p} if periods is not None else None

    def _inc(self, key: str) -> None:
        with self._stats_lock:
            self._stats[key] = int(self._stats.get(key, 0)) + 1

    def _listen_loop(self) -> None:
        if redis_db is None:  # pragma: no cover
            raise RuntimeError("redis client unavailable: please install redis-py and configure redis")
        while self._running:
            try:
                self._pubsub = redis_db.pubsub()
                self._pubsub.subscribe(self.channel)
                logger.info(f"Subscribed Redis channel: {self.channel}")
                for msg in self._pubsub.listen():
                    if not self._running:
                        break
                    if (msg or {}).get("type") != "message":
                        continue
                    self._inc("received")
                    self._enqueue(msg)
            except Exception as e:
                if not self._running:
                    break
                self._inc("errors")
                logger.error(f"BarEventListener listen error: {e}; reconnecting in {self._reconnect_interval_s}s")
                time.sleep(self._reconnect_interval_s)

    def _enqueue(self, msg: dict[str, Any]) -> None:
        try:
            self._queue.put(msg, timeout=self.enqueue_timeout)
            self._inc("enqueued")
            depth = self._queue.qsize()
            if depth > self._queue_max_depth:
                self._queue_max_depth = depth
        except queue.Full:
            self._inc("dropped")

    def _worker_loop(self) -> None:
        while self._running or not self._queue.empty():
            try:
                msg = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if msg is None:
                    return
                self._process(msg)
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    def _process(self, msg: dict[str, Any]) -> None:
        try:
            upd = parse_bar_update_message((msg or {}).get("data"))
            if upd is None:
                return
            if self.filter_codes is not None and upd.code not in self.filter_codes:
                self._inc("filtered")
                return
            if self.filter_periods is not None and upd.period not in self.filter_periods:
                self._inc("filtered")
                return

            start_ts = time.time()
            self.callback(upd.code, upd.period, upd.data)
            self._inc("processed")
            if self.task_timeout is not None:
                cost = time.time() - start_ts
                if cost > self.task_timeout:
                    logger.warning(f"BarEventListener callback slow: {upd.code} {upd.period} cost={cost:.3f}s")
        except Exception as e:
            self._inc("errors")
            logger.error(f"BarEventListener process error: {e}")
