# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import threading
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from freshquant.market_data.xtdata.constants import queue_key_for_code
from freshquant.market_data.xtdata.schema import normalize_prefixed_code
from freshquant.runtime_constants import TZ

try:
    from freshquant.database.redis import redis_db  # type: ignore
except Exception:  # pragma: no cover
    redis_db = None  # type: ignore


def _is_cn_a_trading_datetime(dt: datetime) -> bool:
    t = dt.time()
    return (
        t >= datetime(dt.year, dt.month, dt.day, 9, 30).time()
        and t <= datetime(dt.year, dt.month, dt.day, 11, 30).time()
    ) or (
        t >= datetime(dt.year, dt.month, dt.day, 13, 0).time()
        and t <= datetime(dt.year, dt.month, dt.day, 15, 0).time()
    )


def _is_noon_break(dt: datetime) -> bool:
    t = dt.time()
    return (
        t > datetime(dt.year, dt.month, dt.day, 11, 30).time()
        and t < datetime(dt.year, dt.month, dt.day, 13, 0).time()
    )


def _is_session_terminal_boundary(dt: datetime) -> bool:
    if dt.second != 0 or dt.microsecond != 0:
        return False
    return (dt.hour, dt.minute) in {(11, 30), (15, 0)}


def _ceil_minute_end(dt: datetime) -> datetime:
    dt0 = dt.replace(second=0, microsecond=0)
    if _is_session_terminal_boundary(dt):
        return dt0
    return dt0 + timedelta(minutes=1)


def _bucket_end(dt: datetime, period_min: int) -> datetime:
    dt0 = dt.replace(second=0, microsecond=0)
    if period_min <= 1:
        return dt0 + timedelta(minutes=1)
    delta = period_min - (dt0.minute % period_min)
    if delta == period_min:
        delta = 0
    return dt0 + timedelta(minutes=delta)


def _timer_close_cutoff(dt: datetime) -> int:
    if _is_cn_a_trading_datetime(dt):
        return int(_ceil_minute_end(dt).timestamp())
    if _is_noon_break(dt):
        return int(dt.replace(hour=13, minute=1, second=0, microsecond=0).timestamp())
    if dt.time() < datetime(dt.year, dt.month, dt.day, 9, 30).time():
        return int(dt.replace(hour=9, minute=31, second=0, microsecond=0).timestamp())
    return int(dt.replace(hour=15, minute=1, second=0, microsecond=0).timestamp())


def _should_scan_timer(dt: datetime) -> bool:
    if _is_cn_a_trading_datetime(dt):
        return True
    return (dt.hour, dt.minute) in {(11, 30), (15, 0)}


@dataclass(frozen=True)
class BarEvent:
    code: str
    period_min: int
    data: dict[str, Any]

    def to_queue_dict(self) -> dict[str, Any]:
        return {
            "event": "BAR_CLOSE",
            "code": self.code,
            "period": f"{int(self.period_min)}min",
            "data": self.data,
            "created_at": time.time(),
        }


class MultiPeriodResamplerFrom1m:
    def __init__(self, periods_min: list[int]):
        self.periods = sorted({int(p) for p in periods_min if int(p) > 1})
        self._aggs: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
        self._last_1m_end_ts: dict[str, int] = {}

    def reset(self) -> None:
        self._aggs.clear()
        self._last_1m_end_ts.clear()

    def on_1m_bar(self, code: str, bar_data: dict[str, Any]) -> list[BarEvent]:
        if not code or not bar_data:
            return []
        try:
            end_ts = int(bar_data.get("time") or 0)
        except Exception:
            return []
        if end_ts <= 0:
            return []

        last_ts = self._last_1m_end_ts.get(code)
        if last_ts is not None and end_ts <= last_ts:
            return []
        self._last_1m_end_ts[code] = end_ts

        dt_end = datetime.fromtimestamp(end_ts, tz=TZ)
        emitted: list[BarEvent] = []

        o_raw = bar_data.get("open")
        h_raw = bar_data.get("high")
        l_raw = bar_data.get("low")
        c_raw = bar_data.get("close")
        if o_raw is None or h_raw is None or l_raw is None or c_raw is None:
            return []
        try:
            o = float(o_raw)
            h = float(h_raw)
            l = float(l_raw)
            c = float(c_raw)
            v = float(bar_data.get("volume") or 0.0)
            a = float(bar_data.get("amount") or 0.0)
        except Exception:
            return []

        for p in self.periods:
            bucket_end_dt = _bucket_end(dt_end, p)
            bucket_end_ts = int(bucket_end_dt.timestamp())
            agg = self._aggs[code].get(p)
            if agg is None:
                agg = {
                    "bucket_end_ts": bucket_end_ts,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v,
                    "amount": a,
                }
                self._aggs[code][p] = agg
            elif int(agg.get("bucket_end_ts") or 0) != bucket_end_ts:
                emitted.append(
                    BarEvent(
                        code=code,
                        period_min=p,
                        data={
                            "time": int(agg["bucket_end_ts"]),
                            "open": float(agg["open"]),
                            "high": float(agg["high"]),
                            "low": float(agg["low"]),
                            "close": float(agg["close"]),
                            "volume": float(agg["volume"]),
                            "amount": float(agg["amount"]),
                        },
                    )
                )
                agg = {
                    "bucket_end_ts": bucket_end_ts,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v,
                    "amount": a,
                }
                self._aggs[code][p] = agg
            else:
                agg["high"] = max(float(agg.get("high") or h), h)
                agg["low"] = min(float(agg.get("low") or l), l)
                agg["close"] = c
                agg["volume"] = float(agg.get("volume") or 0.0) + v
                agg["amount"] = float(agg.get("amount") or 0.0) + a

            if end_ts >= int(agg.get("bucket_end_ts") or 0):
                emitted.append(
                    BarEvent(
                        code=code,
                        period_min=p,
                        data={
                            "time": int(agg["bucket_end_ts"]),
                            "open": float(agg["open"]),
                            "high": float(agg["high"]),
                            "low": float(agg["low"]),
                            "close": float(agg["close"]),
                            "volume": float(agg["volume"]),
                            "amount": float(agg["amount"]),
                        },
                    )
                )
                try:
                    del self._aggs[code][p]
                except Exception:
                    pass

        return emitted


class OneMinuteBarGenerator:
    def __init__(
        self,
        *,
        enable_synthetic: bool = True,
        resample_periods_min: Optional[list[int]] = None,
        push_1m: bool = True,
        redis_client=redis_db,
    ):
        self.enable_synthetic = bool(enable_synthetic)
        self.push_1m = bool(push_1m)
        self.redis_client = redis_client

        self._lock = threading.Lock()
        self._bars: dict[str, dict[str, Any]] = defaultdict(dict)
        self._tick_cache: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "last_vol": 0.0,
                "last_amt": 0.0,
                "last_tick_ms": 0,
                "trading_day": None,
            }
        )
        self._last_close: dict[str, float] = {}

        self._resampler = None
        if resample_periods_min:
            self._resampler = MultiPeriodResamplerFrom1m(resample_periods_min)

        self._timer_stop = threading.Event()
        self._timer_thread = threading.Thread(
            target=self._timer_loop, daemon=True, name="OneMinuteBarTimer"
        )
        self._timer_thread.start()

    def stop(self) -> None:
        self._timer_stop.set()
        try:
            self._timer_thread.join(timeout=5)
        except Exception:
            pass

    def on_tick(self, datas: dict[str, dict[str, Any]]) -> None:
        if not datas:
            return
        to_push: list[BarEvent] = []
        with self._lock:
            for raw_code, tick in datas.items():
                code = normalize_prefixed_code(raw_code).lower()
                evs = self._process_single_tick(code, tick)
                if evs:
                    to_push.extend(evs)
        self._push_events(to_push)

    def _timer_loop(self) -> None:
        while not self._timer_stop.is_set():
            try:
                now = datetime.now(tz=TZ)
                if not _should_scan_timer(now):
                    time.sleep(1)
                    continue
                end_ts = _timer_close_cutoff(now)
                to_push: list[BarEvent] = []
                with self._lock:
                    for code in list(self._bars.keys()):
                        bar = self._bars.get(code) or {}
                        cur_end = int(bar.get("time") or 0)
                        if cur_end > 0 and cur_end < end_ts:
                            to_push.extend(self._close_until(code, end_ts))
                self._push_events(to_push)
            except Exception:
                traceback.print_exc()
            time.sleep(0.5)

    def _update_tick_baseline(
        self,
        code: str,
        *,
        cum_vol: float,
        cum_amt: float,
        tick_time_ms: int,
        trading_day: str,
    ) -> None:
        prev = self._tick_cache[code]
        prev["last_vol"] = float(cum_vol)
        prev["last_amt"] = float(cum_amt)
        prev["last_tick_ms"] = int(tick_time_ms)
        prev["trading_day"] = trading_day

    def _ensure_bar(
        self, code: str, *, end_ts: int, price: float, mark_tick: bool
    ) -> dict[str, Any]:
        bar = self._bars.get(code) or {}
        if not bar or int(bar.get("time") or 0) != end_ts:
            self._bars[code] = {
                "time": end_ts,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0.0,
                "amount": 0.0,
                "_had_tick": bool(mark_tick),
            }
            return self._bars[code]
        if mark_tick and not bar.get("_had_tick"):
            bar["open"] = price
            bar["high"] = price
            bar["low"] = price
            bar["close"] = price
            bar["_had_tick"] = True
        return bar

    def _close_until(self, code: str, before_end_ts: int) -> list[BarEvent]:
        events: list[BarEvent] = []
        while True:
            bar = self._bars.get(code) or {}
            cur_end = int(bar.get("time") or 0)
            if not bar or cur_end <= 0 or cur_end >= int(before_end_ts):
                break
            if bar.get("_had_tick") or self.enable_synthetic:
                events.extend(self._close_bar(code))
                continue
            self._bars.pop(code, None)
            break
        return events

    def _close_bar(self, code: str) -> list[BarEvent]:
        bar = self._bars.get(code) or {}
        end_ts = int(bar.get("time") or 0)
        if not bar or end_ts <= 0:
            return []
        end_dt = datetime.fromtimestamp(end_ts, tz=TZ)
        if not _is_cn_a_trading_datetime(end_dt) or _is_noon_break(end_dt):
            self._bars.pop(code, None)
            return []
        evs: list[BarEvent] = []
        data = {
            "time": end_ts,
            "open": float(bar["open"]),
            "high": float(bar["high"]),
            "low": float(bar["low"]),
            "close": float(bar["close"]),
            "volume": float(bar.get("volume") or 0.0),
            "amount": float(bar.get("amount") or 0.0),
        }
        if self.push_1m:
            evs.append(BarEvent(code=code, period_min=1, data=data))
        if self._resampler is not None:
            evs.extend(self._resampler.on_1m_bar(code, data))

        # init next synthetic bar
        last_close = float(bar.get("close") or 0.0)
        self._last_close[code] = last_close
        next_end_dt = end_dt + timedelta(minutes=1)
        if _is_noon_break(next_end_dt):
            # skip noon break: jump to 13:01 end
            next_end_dt = next_end_dt.replace(
                hour=13, minute=1, second=0, microsecond=0
            )
        if _is_cn_a_trading_datetime(next_end_dt):
            self._bars[code] = {
                "time": int(next_end_dt.timestamp()),
                "open": last_close,
                "high": last_close,
                "low": last_close,
                "close": last_close,
                "volume": 0.0,
                "amount": 0.0,
                "_had_tick": False,
            }
        else:
            self._bars.pop(code, None)
        return evs

    def _process_single_tick(self, code: str, tick: dict[str, Any]) -> list[BarEvent]:
        try:
            tick_time_ms = int(tick.get("time") or 0)
        except Exception:
            return []
        if tick_time_ms <= 0:
            return []
        price = float(tick.get("lastPrice") or 0.0)
        cum_vol = float(tick.get("volume") or 0.0)
        cum_amt = float(tick.get("amount") or 0.0)

        dt = datetime.fromtimestamp(tick_time_ms / 1000, tz=TZ)
        if not _is_cn_a_trading_datetime(dt):
            return []
        end_dt = _ceil_minute_end(dt)
        if _is_noon_break(end_dt):
            return []
        end_ts = int(end_dt.timestamp())

        events: list[BarEvent] = []
        bar = self._bars.get(code) or {}
        if bar and int(bar.get("time") or 0) < end_ts:
            events.extend(self._close_until(code, end_ts))

        prev = self._tick_cache[code]
        last_vol = float(prev.get("last_vol") or 0.0)
        last_amt = float(prev.get("last_amt") or 0.0)
        last_tick_ms = int(prev.get("last_tick_ms") or 0)
        trading_day = dt.date().isoformat()
        same_day = (
            last_tick_ms > 0 and str(prev.get("trading_day") or "") == trading_day
        )
        last_vol_usable = same_day and last_vol > 0.0
        last_amt_usable = same_day and last_amt > 0.0

        if not same_day or (not last_vol_usable and not last_amt_usable):
            self._update_tick_baseline(
                code,
                cum_vol=cum_vol,
                cum_amt=cum_amt,
                tick_time_ms=tick_time_ms,
                trading_day=trading_day,
            )
            if price > 0.0 and (cum_vol > 0.0 or cum_amt > 0.0):
                self._ensure_bar(code, end_ts=end_ts, price=price, mark_tick=True)
                self._last_close[code] = float(price)
            return events

        vol_delta = 0.0 if not last_vol_usable else (cum_vol - last_vol)
        amt_delta = 0.0 if not last_amt_usable else (cum_amt - last_amt)
        if vol_delta < 0.0 or amt_delta < 0.0:
            if cum_vol <= 0.0 and cum_amt <= 0.0:
                return events
            self._update_tick_baseline(
                code,
                cum_vol=cum_vol,
                cum_amt=cum_amt,
                tick_time_ms=tick_time_ms,
                trading_day=trading_day,
            )
            return events
        if vol_delta <= 0.0 and amt_delta <= 0.0:
            if not last_vol_usable and cum_vol > 0.0:
                prev["last_vol"] = float(cum_vol)
            if not last_amt_usable and cum_amt > 0.0:
                prev["last_amt"] = float(cum_amt)
            prev["last_tick_ms"] = int(tick_time_ms)
            prev["trading_day"] = trading_day
            return events

        self._update_tick_baseline(
            code,
            cum_vol=cum_vol,
            cum_amt=cum_amt,
            tick_time_ms=tick_time_ms,
            trading_day=trading_day,
        )
        bar = self._ensure_bar(code, end_ts=end_ts, price=price, mark_tick=True)
        bar["high"] = max(float(bar["high"]), price)
        bar["low"] = min(float(bar["low"]), price)
        bar["close"] = price
        bar["volume"] = float(bar.get("volume") or 0.0) + float(vol_delta)
        bar["amount"] = float(bar.get("amount") or 0.0) + float(amt_delta)
        self._last_close[code] = float(price)
        return events

    def _push_events(self, events: list[BarEvent]) -> None:
        if not events or self.redis_client is None:
            return
        try:
            pipe = self.redis_client.pipeline()
            for ev in events:
                q = queue_key_for_code(ev.code)
                pipe.rpush(q, json.dumps(ev.to_queue_dict(), ensure_ascii=False))
            pipe.execute()
        except Exception:
            traceback.print_exc()
