# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import threading
import time
import traceback
from collections import deque
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

import click
import pandas as pd
from loguru import logger

from freshquant.analysis.fullcalc_wrapper import run_fullcalc
from freshquant.data.adj_intraday import (
    apply_qfq_with_intraday_override,
    fetch_intraday_override,
    fetch_qfq_adj_df,
)
from freshquant.db import DBfreshquant, DBQuantAxis
from freshquant.market_data.xtdata.chanlun_payload import build_chanlun_payload
from freshquant.market_data.xtdata.coalesce import CoalescingScheduler
from freshquant.market_data.xtdata.constants import (
    REDIS_QUEUE_PREFIX,
    REDIS_QUEUE_SHARDS,
)
from freshquant.market_data.xtdata.pools import (
    load_clx_monitor_codes,
    load_monitor_codes,
    normalize_xtdata_mode,
    xtdata_mode_enables_clx,
)
from freshquant.market_data.xtdata.realtime_store import upsert_realtime_bars
from freshquant.market_data.xtdata.schema import BarCloseEvent
from freshquant.runtime_constants import TZ
from freshquant.runtime_observability.logger import RuntimeEventLogger
from freshquant.system_settings import system_settings
from freshquant.util.period import (
    PUBSUB_CHANNEL,
    get_redis_cache_key,
    to_backend_period,
)

try:
    from freshquant.database.redis import redis_db  # type: ignore
except Exception as e:  # pragma: no cover
    redis_db = None  # type: ignore
    _REDIS_IMPORT_ERR = e


def resolve_consumer_runtime_config(*, settings_provider=None) -> dict[str, int | str]:
    settings_provider = settings_provider or system_settings
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
        queue_backlog_threshold = int(
            getattr(
                settings_provider.monitor,
                "xtdata_queue_backlog_threshold",
                200,
            )
            or 200
        )
    except (TypeError, ValueError):
        queue_backlog_threshold = 200
    if queue_backlog_threshold <= 0:
        queue_backlog_threshold = 200
    return {
        "mode": mode,
        "max_symbols": max_symbols,
        "queue_backlog_threshold": queue_backlog_threshold,
    }


def _base_code(code_prefixed: str) -> str:
    s = str(code_prefixed or "").lower().strip()
    if len(s) >= 8 and s[:2] in {"sh", "sz", "bj"} and s[2:8].isdigit():
        return s[2:8]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits


def _is_etf(base_code6: str) -> bool:
    # 常见 ETF：15xxxx/16xxxx/51xxxx/52xxxx/53xxxx/56xxxx/58xxxx/159xxx 等
    s = str(base_code6 or "")
    return s.startswith(("15", "16", "51", "52", "53", "56", "58", "159"))


def _is_cn_a_trading_bar_end(dt: datetime) -> bool:
    """
    dt is bar end time (e.g. 09:31, 11:30, 13:01, 15:00).
    """
    t = dt.time()
    return (
        t >= datetime(dt.year, dt.month, dt.day, 9, 31).time()
        and t <= datetime(dt.year, dt.month, dt.day, 11, 30).time()
    ) or (
        t >= datetime(dt.year, dt.month, dt.day, 13, 1).time()
        and t <= datetime(dt.year, dt.month, dt.day, 15, 0).time()
    )


def _is_noon_break(last_dt: datetime, cur_dt: datetime) -> bool:
    if last_dt.date() != cur_dt.date():
        return False
    # common noon break boundary: 11:30 -> 13:00
    t_last = last_dt.time()
    t_cur = cur_dt.time()
    return (
        t_last == datetime(last_dt.year, last_dt.month, last_dt.day, 11, 30).time()
        and t_cur >= datetime(cur_dt.year, cur_dt.month, cur_dt.day, 13, 0).time()
    )


def _estimate_history_window_days(period_backend: str, *, max_bars: int) -> int:
    """
    Rough estimate to fetch enough history for tail(max_bars), avoiding "fetch from 1990".
    """
    p = to_backend_period(period_backend)
    try:
        minutes = int(p.replace("min", ""))
    except Exception:
        minutes = 1
    if minutes <= 0:
        minutes = 1
    # CN A: 240 minutes/day
    bars_per_day = max(1, int(240 / minutes))
    days = int((max(1, int(max_bars)) / bars_per_day) + 60)
    # cushion for non-trading days
    return int(days * 1.35)


def _empty_bar_window_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["datetime", "open", "high", "low", "close", "volume", "amount"]
    )


def _coerce_bar_datetime(value: Any) -> pd.Timestamp | pd.NaT:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NaT
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return pd.NaT
    if pd.isna(ts):
        return pd.NaT
    if ts.tzinfo is None:
        return ts.tz_localize(TZ)
    return ts.tz_convert(TZ)


def _normalize_bar_window_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return _empty_bar_window_df()

    bars = df.copy()
    if "vol" in bars.columns and "volume" not in bars.columns:
        bars["volume"] = bars["vol"]
    for col in ["datetime", "open", "high", "low", "close", "volume", "amount"]:
        if col not in bars.columns:
            bars[col] = None

    bars = bars[["datetime", "open", "high", "low", "close", "volume", "amount"]]
    bars["datetime"] = bars["datetime"].apply(_coerce_bar_datetime)
    bars = bars.dropna(subset=["datetime"])
    if bars.empty:
        return _empty_bar_window_df()
    bars["datetime"] = pd.DatetimeIndex(bars["datetime"])

    return bars.sort_values("datetime").reset_index(drop=True)


def _load_minute_history_from_quantaxis_db(
    *,
    base_code6: str,
    period_backend: str,
    start_dt: datetime,
    end_dt: datetime,
    coll_name: str,
) -> pd.DataFrame:
    date_query = {
        "code": str(base_code6),
        "type": to_backend_period(period_backend),
        "date": {
            "$gte": start_dt.strftime("%Y-%m-%d"),
            "$lte": end_dt.strftime("%Y-%m-%d"),
        },
    }
    cursor = (
        DBQuantAxis[coll_name]
        .find(
            date_query,
            {
                "_id": 0,
                "datetime": 1,
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "vol": 1,
                "volume": 1,
                "amount": 1,
                "time_stamp": 1,
            },
        )
        .sort("time_stamp", 1)
    )
    raw_df = pd.DataFrame(list(cursor))
    if "time_stamp" in raw_df.columns and raw_df["time_stamp"].notna().any():
        raw_df = raw_df.copy()
        raw_df["datetime"] = pd.to_datetime(
            pd.to_numeric(raw_df["time_stamp"], errors="coerce"),
            unit="s",
            utc=True,
        ).dt.tz_convert(TZ)
    hist_df = _normalize_bar_window_df(raw_df)
    if hist_df.empty:
        return hist_df
    hist_df = hist_df[
        (hist_df["datetime"] >= start_dt) & (hist_df["datetime"] <= end_dt)
    ]
    return hist_df.reset_index(drop=True)


def _worker_fullcalc(df: pd.DataFrame, model_ids: list[int]) -> dict[str, Any]:
    return run_fullcalc(df, model_ids=model_ids)


class ConsumerHeartbeatState:
    def __init__(self, *, window_s: float = 300.0):
        self.window_s = max(float(window_s or 300.0), 1.0)
        self._lock = threading.Lock()
        self._processed_bars: deque[float] = deque()
        self._last_bar_ts: float | None = None

    def record_processed_bar(self, *, now_ts: float | None = None) -> None:
        current_ts = float(now_ts if now_ts is not None else time.time())
        with self._lock:
            self._processed_bars.append(current_ts)
            self._last_bar_ts = current_ts
            self._prune_locked(current_ts)

    def snapshot(
        self,
        *,
        now_ts: float | None = None,
        backlog_sum: int = 0,
        scheduler_pending: int = 0,
        catchup_mode: bool = False,
    ) -> dict:
        current_ts = float(now_ts if now_ts is not None else time.time())
        with self._lock:
            self._prune_locked(current_ts)
            processed_bars = len(self._processed_bars)
            last_bar_ts = self._last_bar_ts
        return {
            "backlog_sum": max(int(backlog_sum or 0), 0),
            "scheduler_pending": max(int(scheduler_pending or 0), 0),
            "processed_bars_5m": processed_bars,
            "last_bar_age_s": (
                None
                if last_bar_ts is None
                else round(max(current_ts - last_bar_ts, 0.0), 3)
            ),
            "catchup_mode": 1 if catchup_mode else 0,
        }

    def _prune_locked(self, now_ts: float) -> None:
        cutoff = float(now_ts) - self.window_s
        while self._processed_bars and self._processed_bars[0] < cutoff:
            self._processed_bars.popleft()


class StrategyConsumer:
    def __init__(
        self,
        *,
        max_bars: int = 20000,
        fullcalc_workers: int | None = None,
        fullcalc_max_inflight: int | None = None,
        cache_ttl_seconds: int = 3600 * 24,
        queue_backlog_threshold: int | None = None,
        runtime_logger=None,
        settings_provider=None,
    ):
        if redis_db is None:  # pragma: no cover
            raise RuntimeError(f"redis client unavailable: {_REDIS_IMPORT_ERR}")

        self.max_bars = max(1000, int(max_bars))
        self.cache_ttl_seconds = max(60, int(cache_ttl_seconds))

        cpu_cnt = os.cpu_count() or 4
        self.fullcalc_workers = int(fullcalc_workers or min(8, max(2, cpu_cnt // 2)))
        self.fullcalc_max_inflight = int(
            fullcalc_max_inflight or (self.fullcalc_workers * 2)
        )

        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], pd.DataFrame] = {}
        self._futures: dict[tuple[str, str], Any] = {}
        self._last_bar_ts: dict[tuple[str, str], int] = {}
        self._known_codes: set[str] = set()

        self._backfill_executor = ThreadPoolExecutor(max_workers=2)
        self._backfill_lock = threading.Lock()
        self._backfilling_codes: set[str] = set()
        self._clx_codes_lock = threading.Lock()
        self._clx_codes_cache: set[str] = set()
        self._clx_codes_loaded_at = 0.0
        self._clx_codes_refresh_interval_s = 60.0

        self._catchup_mode = False
        self._dirty_latest: dict[tuple[str, str], dict[str, Any]] = {}
        self.settings_provider = settings_provider or system_settings
        runtime_config = resolve_consumer_runtime_config(
            settings_provider=self.settings_provider
        )
        self.queue_backlog_threshold = int(
            queue_backlog_threshold or runtime_config["queue_backlog_threshold"]
        )
        self.runtime_logger = runtime_logger or _get_runtime_logger()
        self._heartbeat_state = ConsumerHeartbeatState(window_s=300.0)
        self._last_runtime_heartbeat_at = 0.0
        self._runtime_heartbeat_interval_s = 300.0
        self._symbol_position_service: Any = None

        self._executor = ProcessPoolExecutor(max_workers=self.fullcalc_workers)
        self._scheduler = CoalescingScheduler(
            max_inflight=self.fullcalc_max_inflight,
            submit_fn=self._submit_fullcalc,
        )

        self.mode = str(runtime_config["mode"])
        self.max_symbols = int(runtime_config["max_symbols"])

        logger.info(
            f"[Consumer] init mode={self.mode} max_bars={self.max_bars} "
            f"workers={self.fullcalc_workers} max_inflight={self.fullcalc_max_inflight} "
            f"queue_backlog_threshold={self.queue_backlog_threshold}"
        )
        self._emit_runtime(
            {
                "component": "xt_consumer",
                "node": "bootstrap",
                "payload": {
                    "mode": self.mode,
                    "max_bars": self.max_bars,
                    "workers": self.fullcalc_workers,
                    "max_inflight": self.fullcalc_max_inflight,
                },
            }
        )

    def emit_runtime_heartbeat(self, **metrics) -> bool:
        return self._emit_runtime(
            {
                "component": "xt_consumer",
                "node": "heartbeat",
                "event_type": "heartbeat",
                "status": "info",
                "metrics": dict(metrics),
                "payload": {},
            }
        )

    def _queue_depth(self, queue_keys: list[str]) -> int:
        try:
            pipe = redis_db.pipeline()
            for k in queue_keys:
                pipe.llen(k)
            vals = pipe.execute()
            return int(sum(int(v or 0) for v in (vals or [])))
        except Exception:
            return 0

    def _flush_dirty_latest(self) -> int:
        with self._lock:
            items = list(self._dirty_latest.items())
            self._dirty_latest.clear()
        for k, meta in items:
            self._scheduler.update(k, meta)
        return len(items)

    def prewarm(self) -> None:
        """
        prewarm: load up to max_bars per (code,period) and run fullcalc once.
        """
        codes = load_monitor_codes(mode=self.mode, max_symbols=self.max_symbols)
        periods = ["1min", "5min", "15min", "30min"]
        logger.info(
            f"[Consumer] prewarm start: codes={len(codes)} periods={periods} max_bars={self.max_bars}"
        )
        for code in codes:
            with self._lock:
                self._known_codes.add(code)
            for period in periods:
                try:
                    df = self._load_window_from_db(code=code, period_backend=period)
                except Exception as e:
                    logger.warning(
                        f"[Consumer] prewarm load failed {code} {period}: {e}"
                    )
                    continue
                if df is None or df.empty:
                    continue
                key = (code, period)
                try:
                    bar_time = int(pd.to_datetime(df["datetime"].iloc[-1]).timestamp())
                except Exception:
                    bar_time = 0
                meta = {
                    "code": code,
                    "period": period,
                    "bar_time": bar_time,
                    "df": df[
                        ["datetime", "open", "high", "low", "close", "volume", "amount"]
                    ].copy(),
                    "model_ids": self._model_ids_for(code, period),
                }
                with self._lock:
                    self._windows[key] = df
                    if bar_time > 0:
                        self._last_bar_ts[key] = bar_time
                self._scheduler.update(key, meta)

        logger.info(
            "[Consumer] prewarm submitted; waiting fullcalc tasks in background"
        )

    def _clx_monitor_codes(self, *, force: bool = False) -> set[str]:
        if not xtdata_mode_enables_clx(self.mode):
            return set()
        now_ts = time.time()
        with self._clx_codes_lock:
            if (
                not force
                and self._clx_codes_cache
                and (now_ts - float(self._clx_codes_loaded_at or 0.0))
                < self._clx_codes_refresh_interval_s
            ):
                return set(self._clx_codes_cache)
            codes = {
                str(code or "").strip().lower()
                for code in load_clx_monitor_codes(max_symbols=self.max_symbols)
                if str(code or "").strip()
            }
            self._clx_codes_cache = codes
            self._clx_codes_loaded_at = now_ts
            return set(self._clx_codes_cache)

    def _model_ids_for(self, code_prefixed: str, period_backend: str) -> list[int]:
        period_backend = to_backend_period(period_backend)
        if not xtdata_mode_enables_clx(self.mode):
            return []
        if period_backend not in {"15min", "30min"}:
            return []
        code = str(code_prefixed or "").strip().lower()
        if not code or code not in self._clx_monitor_codes():
            return []
        return list(range(10001, 10013))

    def _get_qfq_factor(self, *, kind: str, base_code6: str, date_str: str) -> float:
        """
        kind: "stock" | "etf"
        """
        coll = "stock_adj" if kind == "stock" else "etf_adj"
        override_coll = "stock_adj_intraday" if kind == "stock" else "etf_adj_intraday"
        try:
            override = fetch_intraday_override(
                coll_name=override_coll,
                code=base_code6,
                trade_date=date_str,
                db=DBQuantAxis,
            )
            if override is not None:
                return 1.0
        except Exception:
            pass

        factor = 1.0
        try:
            doc = DBQuantAxis[coll].find_one(
                {"code": str(base_code6), "date": {"$lte": str(date_str)}},
                sort=[("date", -1)],
                projection={"_id": 0, "date": 1, "adj": 1},
            )
            if doc and doc.get("adj") is not None:
                factor = float(doc["adj"])
        except Exception:
            factor = 1.0

        return float(factor)

    def _apply_qfq_to_bar(
        self, *, kind: str, code_prefixed: str, bar: dict[str, Any]
    ) -> dict[str, Any]:
        dt: datetime | None = bar.get("datetime")
        if not isinstance(dt, datetime):
            return bar
        base = _base_code(code_prefixed)
        date_str = dt.strftime("%Y-%m-%d")
        factor = self._get_qfq_factor(kind=kind, base_code6=base, date_str=date_str)
        if abs(float(factor) - 1.0) < 1e-9:
            return bar
        out = dict(bar)
        for col in ("open", "high", "low", "close"):
            try:
                out[col] = float(out.get(col) or 0.0) * float(factor)
            except Exception:
                continue
        return out

    def _is_index_like(self, code_prefixed: str) -> bool:
        try:
            from freshquant.carnation.enum_instrument import InstrumentType
            from freshquant.instrument.general import query_instrument_type

            t = query_instrument_type(code_prefixed)
            if t in {InstrumentType.ETF_CN, InstrumentType.INDEX_CN}:
                return True
            if t == InstrumentType.STOCK_CN:
                return False
        except Exception:
            pass
        return _is_etf(_base_code(code_prefixed))

    def _load_window_from_db(self, *, code: str, period_backend: str) -> pd.DataFrame:
        """
        Load a max_bars window:
        - history: quantaxis minute DB via project-configured Mongo
        - realtime: DBfreshquant.<stock_realtime/index_realtime>
        - return: DataFrame with tz-aware `datetime` and columns open/high/low/close/volume/amount
        """
        period_backend = to_backend_period(period_backend)
        end_dt = datetime.now(tz=TZ)
        start_dt = end_dt - timedelta(
            days=_estimate_history_window_days(period_backend, max_bars=self.max_bars)
        )

        base6 = _base_code(code)
        is_index_like = self._is_index_like(code)

        hist_coll = "index_min" if is_index_like else "stock_min"
        hist_df = _empty_bar_window_df()
        try:
            hist_df = _load_minute_history_from_quantaxis_db(
                base_code6=base6,
                period_backend=period_backend,
                start_dt=start_dt,
                end_dt=end_dt,
                coll_name=hist_coll,
            )
        except Exception as e:
            logger.warning(
                f"[Consumer] quantaxis history query failed; history window is empty: {e}"
            )
            hist_df = _empty_bar_window_df()

        # realtime bars (may be empty)
        coll = "index_realtime" if is_index_like else "stock_realtime"
        rt_cur = (
            DBfreshquant[coll]
            .find(
                {
                    "code": code,
                    "frequence": period_backend,
                    "datetime": {"$gte": start_dt, "$lte": end_dt},
                },
                {
                    "_id": 0,
                    "datetime": 1,
                    "open": 1,
                    "high": 1,
                    "low": 1,
                    "close": 1,
                    "volume": 1,
                    "amount": 1,
                },
            )
            .sort("datetime", 1)
        )
        rt_df = pd.DataFrame(list(rt_cur))

        start_date = start_dt.strftime("%Y-%m-%d")
        end_date = end_dt.strftime("%Y-%m-%d")
        adj_coll = "etf_adj" if is_index_like else "stock_adj"
        override_coll = "etf_adj_intraday" if is_index_like else "stock_adj_intraday"
        adj_df = fetch_qfq_adj_df(
            coll_name=adj_coll,
            code=base6,
            start_date=start_date,
            end_date=end_date,
            db=DBQuantAxis,
        )
        override = fetch_intraday_override(
            coll_name=override_coll,
            code=base6,
            trade_date=end_date,
            db=DBQuantAxis,
        )

        merged = _normalize_bar_window_df(
            pd.concat([hist_df, rt_df], ignore_index=True)
        )
        if merged.empty:
            return merged

        merged = merged.drop_duplicates(subset=["datetime"], keep="last")
        merged = merged.sort_values("datetime")
        merged = apply_qfq_with_intraday_override(
            merged,
            adj_df,
            override=override,
            datetime_col="datetime",
        )

        if len(merged) > self.max_bars:
            merged = merged.iloc[-self.max_bars :]
        merged = merged.reset_index(drop=True)
        return merged

    def _submit_fullcalc(self, key: tuple[str, str], meta: dict[str, Any]) -> None:
        df: pd.DataFrame = meta["df"]
        model_ids: list[int] = meta["model_ids"]
        fut = self._executor.submit(_worker_fullcalc, df, model_ids)
        self._futures[key] = fut

        def _done(_f):
            self._on_fullcalc_done(key, meta, _f)

        fut.add_done_callback(_done)

    def _on_fullcalc_done(
        self, key: tuple[str, str], meta: dict[str, Any], fut
    ) -> None:
        try:
            fc_res = fut.result()
        except Exception as e:
            logger.error(f"[Consumer] fullcalc failed {key}: {e}")
            logger.debug(traceback.format_exc())
            with self._lock:
                self._futures.pop(key, None)
                self._scheduler.mark_done(key)
            return

        try:
            self._process_clx_signals(meta, fc_res)
            payload = build_chanlun_payload(
                code=meta["code"],
                period_backend=meta["period"],
                merged_df=meta["df"],
                fc_res=fc_res,
                bar_time_ts=meta.get("bar_time"),
            )

            cache_key = get_redis_cache_key(payload.code, payload.period_backend)
            redis_db.set(
                cache_key,
                json.dumps(payload.data, ensure_ascii=False),
                ex=self.cache_ttl_seconds,
            )
            redis_db.publish(
                PUBSUB_CHANNEL,
                json.dumps(
                    {
                        "code": payload.code,
                        "period": payload.data.get("period"),
                        "data": payload.data,
                    },
                    ensure_ascii=False,
                ),
            )
        except Exception as e:
            logger.error(f"[Consumer] cache/pub failed {key}: {e}")
            logger.debug(traceback.format_exc())
        finally:
            with self._lock:
                self._futures.pop(key, None)
                self._scheduler.mark_done(key)

    def _process_clx_signals(
        self, meta: dict[str, Any], fc_res: dict[str, Any]
    ) -> None:
        model_ids = meta.get("model_ids") or []
        if not model_ids:
            return
        signals = fc_res.get("signals") or []
        if not signals:
            return

        code = meta.get("code") or ""
        period = meta.get("period") or ""
        ts = int(meta.get("bar_time") or 0)
        if ts <= 0:
            return
        dt = datetime.fromtimestamp(ts, tz=TZ)
        time_key = dt.strftime("%Y%m%d%H%M%S")

        docs = []
        for s in signals:
            try:
                if int(s.get("signal") or 0) <= 0:
                    continue
                model = int(s.get("model") or 0)
                close = float(s.get("close") or 0.0)
                stop_loss = float(s.get("stop_loss") or 0.0)
            except Exception:
                continue

            lock_key = f"FQ:LOCK:CLX:{time_key}:{code}:{period}:{model}"
            if not redis_db.set(lock_key, "1", ex=3600, nx=True):
                continue

            inst = None
            try:
                from freshquant.instrument.general import query_instrument_info

                inst = query_instrument_info(code)
            except Exception:
                inst = None

            doc = {
                "datetime": dt,
                "created_at": datetime.now(tz=TZ),
                "code": code,
                "name": (inst or {}).get("name") or "",
                "period": period,
                "model": f"CLX{model}",
                "close": close,
                "stop_loss_price": stop_loss or None,
                "source": "XTData_Realtime",
            }
            docs.append(doc)

        if not docs:
            return

        try:
            DBfreshquant["realtime_screen_multi_period"].insert_many(
                docs, ordered=False
            )
        except Exception as e:
            logger.error(f"[Consumer] insert clx docs failed: {e}")

        # DingTalk: minimal aggregation
        try:
            from freshquant.message.dingtalk import send_private_message

            title = f"CLX信号 {period} {dt.strftime('%m-%d %H:%M')}"
            lines = [f"### {title}"]
            for d in docs:
                lines.append(
                    f"- {d.get('code')} {d.get('name','')} {d.get('model')} close={d.get('close')} stop={d.get('stop_loss_price') or ''}"
                )
            send_private_message(title, "  \n".join(lines))
        except Exception:
            # notification is best-effort
            pass

    def _update_window(
        self, key: tuple[str, str], bar_row: dict[str, Any]
    ) -> pd.DataFrame:
        df = self._windows.get(key)
        row_df = pd.DataFrame([bar_row])
        if df is None or df.empty:
            df = row_df
        else:
            df = pd.concat([df, row_df], ignore_index=True)
            df = df.drop_duplicates(subset=["datetime"], keep="last")
        df = df.sort_values("datetime")
        if len(df) > self.max_bars:
            df = df.iloc[-self.max_bars :]
        self._windows[key] = df
        return df

    def _maybe_trigger_backfill(
        self,
        *,
        code: str,
        last_dt: datetime | None,
        cur_dt: datetime,
        period_backend: str,
    ) -> bool:
        """
        Best-effort gap/backfill.
        - returns True if backfill task submitted (skip fullcalc for current bar)
        """
        if not _is_cn_a_trading_bar_end(cur_dt):
            return False

        # init backfill: no history for today
        if last_dt is None or last_dt.date() != cur_dt.date():
            start_dt = cur_dt.replace(hour=9, minute=30, second=0, microsecond=0)
        else:
            if _is_noon_break(last_dt, cur_dt):
                return False
            start_dt = last_dt

        if cur_dt <= start_dt:
            return False

        with self._backfill_lock:
            if code in self._backfilling_codes:
                return True
            self._backfilling_codes.add(code)

        logger.warning(
            f"[Consumer] backfill submit: {code} {period_backend} {start_dt} -> {cur_dt}"
        )
        self._backfill_executor.submit(
            self._backfill_code_window, code, start_dt, cur_dt
        )
        return True

    def _backfill_code_window(
        self, code: str, start_dt: datetime, end_dt: datetime
    ) -> None:
        try:
            self._backfill_from_xtdata(code=code, start_dt=start_dt, end_dt=end_dt)
        except Exception as e:
            logger.error(f"[Consumer] backfill failed {code}: {e}")
            logger.debug(traceback.format_exc())
        finally:
            with self._backfill_lock:
                self._backfilling_codes.discard(code)

        # after backfill: reload windows and schedule one fullcalc per period
        periods = ["1min", "5min", "15min", "30min"]
        with self._lock:
            self._known_codes.add(code)
        for period in periods:
            key = (code, period)
            try:
                df = self._load_window_from_db(code=code, period_backend=period)
            except Exception:
                continue
            if df is None or df.empty:
                continue
            try:
                bar_time = int(pd.to_datetime(df["datetime"].iloc[-1]).timestamp())
            except Exception:
                bar_time = 0
            meta = {
                "code": code,
                "period": period,
                "bar_time": bar_time,
                "df": df[
                    ["datetime", "open", "high", "low", "close", "volume", "amount"]
                ].copy(),
                "model_ids": self._model_ids_for(code, period),
            }
            with self._lock:
                self._windows[key] = df
                if bar_time > 0:
                    self._last_bar_ts[key] = bar_time
            self._scheduler.update(key, meta)

    def _warm_code_from_db(self, *, code: str) -> None:
        periods = ["1min", "5min", "15min", "30min"]
        with self._lock:
            self._known_codes.add(code)
        for period in periods:
            key = (code, period)
            df = self._load_window_from_db(code=code, period_backend=period)
            if df is None or df.empty:
                continue
            try:
                bar_time = int(pd.to_datetime(df["datetime"].iloc[-1]).timestamp())
            except Exception:
                bar_time = 0
            meta = {
                "code": code,
                "period": period,
                "bar_time": bar_time,
                "df": df[
                    ["datetime", "open", "high", "low", "close", "volume", "amount"]
                ].copy(),
                "model_ids": self._model_ids_for(code, period),
            }
            with self._lock:
                self._windows[key] = df
                if bar_time > 0:
                    self._last_bar_ts[key] = bar_time
            self._scheduler.update(key, meta)

    def _to_xt_code(self, code_prefixed: str) -> str:
        s = (code_prefixed or "").lower().strip()
        if len(s) >= 8 and s[:2] in {"sh", "sz", "bj"} and s[2:8].isdigit():
            base = s[2:8]
            mkt = s[:2].upper()
            return f"{base}.{mkt}"
        return s

    def _backfill_from_xtdata(
        self, *, code: str, start_dt: datetime, end_dt: datetime
    ) -> None:
        """
        Fetch 1m bars from XTData and resample to 5/15/30 for DB continuity.
        Does NOT run fullcalc here.
        """
        try:
            from xtquant import xtdata  # type: ignore
        except Exception as e:  # pragma: no cover
            logger.warning(
                f"[Consumer] xtquant/xtdata not installed; skip backfill: {e}"
            )
            return

        try:
            port = int(os.environ.get("XTQUANT_PORT", "58610"))
            xtdata.connect(port=port)
        except Exception as e:
            logger.warning(f"[Consumer] xtdata connect failed; skip backfill: {e}")
            return

        xt_code = self._to_xt_code(code)
        t_start = start_dt.strftime("%Y%m%d%H%M%S")
        t_end = end_dt.strftime("%Y%m%d%H%M%S")

        try:
            xtdata.download_history_data(xt_code, "1m", t_start, t_end)
        except Exception:
            # best-effort: still try read
            pass

        data_1m = None
        last_err: Exception | None = None
        for _ in range(10):
            try:
                data_1m = xtdata.get_market_data(
                    stock_list=[xt_code],
                    period="1m",
                    start_time=t_start,
                    end_time=t_end,
                )
                if (
                    data_1m
                    and "time" in data_1m
                    and getattr(data_1m["time"], "empty", True) is False
                ):
                    break
            except Exception as e:
                last_err = e
            time.sleep(1)

        if (
            not data_1m
            or "time" not in data_1m
            or getattr(data_1m["time"], "empty", True)
        ):
            if last_err is not None:
                raise last_err
            return

        sample_df = None
        for k in ("open", "close", "high", "low"):
            v = data_1m.get(k)
            if isinstance(v, pd.DataFrame):
                sample_df = v
                break
        if sample_df is None or len(sample_df.index) == 0:
            return

        row_key = None
        for cand in (
            xt_code,
            xt_code.upper(),
            xt_code.lower(),
            code,
            code.upper(),
            code.lower(),
            _base_code(code),
        ):
            if cand in sample_df.index:
                row_key = cand
                break
        if row_key is None and len(sample_df.index) == 1:
            row_key = sample_df.index[0]
        if row_key is None:
            return

        times = list(getattr(data_1m["time"], "columns", []))
        if not times:
            return

        fs: dict[str, pd.Series] = {}
        for f in ("open", "high", "low", "close", "volume", "amount"):
            df_f = data_1m.get(f)
            if not isinstance(df_f, pd.DataFrame) or row_key not in df_f.index:
                return
            fs[f] = df_f.loc[row_key]

        records_1m: list[dict[str, Any]] = []
        for t in times:
            try:
                dt0 = datetime.strptime(str(t), "%Y%m%d%H%M%S")
            except Exception:
                continue
            dt0 = TZ.localize(dt0) if dt0.tzinfo is None else dt0.astimezone(TZ)
            if not _is_cn_a_trading_bar_end(dt0):
                continue
            try:
                records_1m.append(
                    {
                        "datetime": dt0,
                        "open": float(fs["open"].get(t)),
                        "high": float(fs["high"].get(t)),
                        "low": float(fs["low"].get(t)),
                        "close": float(fs["close"].get(t)),
                        "volume": float(fs["volume"].get(t) or 0.0),
                        "amount": float(fs["amount"].get(t) or 0.0),
                        "source": "xtdata_backfill",
                    }
                )
            except Exception:
                continue

        if not records_1m:
            return

        df_1m = pd.DataFrame(records_1m).set_index("datetime").sort_index()

        def _resample(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
            if minutes <= 1:
                return df.copy()
            rule = f"{int(minutes)}T"
            agg = {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
                "amount": "sum",
            }
            out = df.resample(rule, closed="right", label="right").agg(agg).dropna()
            return out

        is_index_like = self._is_index_like(code)
        periods_min = [1, 5, 15, 30]
        for pm in periods_min:
            df_p = _resample(df_1m, pm)
            if df_p.empty:
                continue
            rows = []
            for dt0, row in df_p.iterrows():
                dt0 = dt0.to_pydatetime() if hasattr(dt0, "to_pydatetime") else dt0
                dt0 = (
                    TZ.localize(dt0)
                    if getattr(dt0, "tzinfo", None) is None
                    else dt0.astimezone(TZ)
                )
                if not _is_cn_a_trading_bar_end(dt0):
                    continue
                rec = {
                    "datetime": dt0,
                    "code": code,
                    "frequence": f"{pm}min",
                    "open": float(row.get("open") or 0.0),
                    "high": float(row.get("high") or 0.0),
                    "low": float(row.get("low") or 0.0),
                    "close": float(row.get("close") or 0.0),
                    "volume": float(row.get("volume") or 0.0),
                    "amount": float(row.get("amount") or 0.0),
                    "source": "xtdata_backfill",
                }
                rows.append(rec)
            if not rows:
                continue
            coll = "index_realtime" if is_index_like else "stock_realtime"
            upsert_realtime_bars(
                collection=coll, code=code, frequence=f"{pm}min", records=rows
            )

    def handle_bar_close(self, ev: BarCloseEvent) -> None:
        code = ev.code
        period = to_backend_period(ev.period)
        data = ev.data or {}
        try:
            ts = int(data.get("time") or 0)
        except Exception:
            ts = 0
        if ts <= 0:
            return

        dt = datetime.fromtimestamp(ts, tz=TZ)
        bar_raw = {
            "datetime": dt,
            "code": code,
            "frequence": period,
            "open": float(data.get("open") or 0.0),
            "high": float(data.get("high") or 0.0),
            "low": float(data.get("low") or 0.0),
            "close": float(data.get("close") or 0.0),
            "volume": float(data.get("volume") or 0.0),
            "amount": float(data.get("amount") or 0.0),
            "source": "xtdata",
        }

        is_index_like = self._is_index_like(code)
        kind = "etf" if is_index_like else "stock"
        coll = "index_realtime" if is_index_like else "stock_realtime"
        bar_store = bar_raw
        bar_calc = self._apply_qfq_to_bar(kind=kind, code_prefixed=code, bar=bar_raw)

        try:
            upsert_realtime_bars(
                collection=coll, code=code, frequence=period, records=[bar_store]
            )
        except Exception as e:
            logger.error(f"[Consumer] save realtime failed {code} {period}: {e}")

        key = (code, period)

        with self._backfill_lock:
            if code in self._backfilling_codes:
                with self._lock:
                    self._last_bar_ts[key] = ts
                return

        with self._lock:
            known = code in self._known_codes
        if not known:
            if self._maybe_trigger_backfill(
                code=code, last_dt=None, cur_dt=dt, period_backend=period
            ):
                with self._lock:
                    self._last_bar_ts[key] = ts
                return
            try:
                self._warm_code_from_db(code=code)
            except Exception as e:
                logger.warning(f"[Consumer] warm new code failed {code}: {e}")
            return

        last_ts = self._last_bar_ts.get(key)
        last_dt = datetime.fromtimestamp(int(last_ts), tz=TZ) if last_ts else None
        if last_dt is not None:
            # ignore duplicates/old bars
            if ts <= int(last_ts or 0):
                return
            # noon break is normal, do not trigger backfill
            if not _is_noon_break(last_dt, dt):
                try:
                    period_s = int(period.replace("min", "")) * 60
                except Exception:
                    period_s = 60
                if (ts - int(last_ts or 0)) > int(period_s * 2.2):
                    if self._maybe_trigger_backfill(
                        code=code, last_dt=last_dt, cur_dt=dt, period_backend=period
                    ):
                        with self._lock:
                            self._last_bar_ts[key] = ts
                        return
        else:
            if self._maybe_trigger_backfill(
                code=code, last_dt=last_dt, cur_dt=dt, period_backend=period
            ):
                with self._lock:
                    self._last_bar_ts[key] = ts
                return

        model_ids = self._model_ids_for(code, period)
        with self._lock:
            self._last_bar_ts[key] = ts
            df = self._update_window(key, bar_calc)
            meta = {
                "code": code,
                "period": period,
                "bar_time": ts,
                "df": df[
                    ["datetime", "open", "high", "low", "close", "volume", "amount"]
                ].copy(),
                "model_ids": model_ids,
            }
            if self._catchup_mode:
                self._dirty_latest[key] = meta
            else:
                self._scheduler.update(key, meta)
        self._heartbeat_state.record_processed_bar()

    def _refresh_symbol_position_snapshot(self, ev: BarCloseEvent) -> None:
        if to_backend_period(ev.period) != "1min":
            return
        service = getattr(self, "_symbol_position_service", None)
        if service is False:
            return
        if service is None:
            try:
                from freshquant.position_management.symbol_position_service import (
                    SingleSymbolPositionService,
                )

                service = SingleSymbolPositionService()
                self._symbol_position_service = service
            except Exception as exc:
                self._symbol_position_service = False
                logger.warning(f"[Consumer] init symbol position service failed: {exc}")
                return
        try:
            service.refresh_from_bar_close(ev)
        except Exception as exc:
            logger.warning(
                f"[Consumer] refresh symbol position snapshot failed {ev.code}: {exc}"
            )

    def run_forever(self) -> None:
        queue_keys = [
            f"{REDIS_QUEUE_PREFIX}:{i}" for i in range(int(REDIS_QUEUE_SHARDS))
        ]
        logger.info(f"[Consumer] start blpop keys={queue_keys}")
        last_depth_check_at = 0.0
        while True:
            try:
                now_ts = time.time()
                if (now_ts - last_depth_check_at) >= 1.0:
                    last_depth_check_at = now_ts
                    depth = self._queue_depth(queue_keys)
                    if (
                        now_ts - float(self._last_runtime_heartbeat_at or 0.0)
                    ) >= self._runtime_heartbeat_interval_s:
                        self._last_runtime_heartbeat_at = now_ts
                        self.emit_runtime_heartbeat(
                            **self._heartbeat_state.snapshot(
                                now_ts=now_ts,
                                backlog_sum=depth,
                                scheduler_pending=self._scheduler.snapshot().get(
                                    "pending", 0
                                ),
                                catchup_mode=self._catchup_mode,
                            )
                        )
                    if (
                        not self._catchup_mode
                    ) and depth >= self.queue_backlog_threshold:
                        self._catchup_mode = True
                        logger.warning(
                            f"[Consumer] queue backlog detected depth={depth}; enter catchup mode (skip fullcalc)"
                        )

                item = redis_db.blpop(queue_keys, timeout=5)
                if not item:
                    if self._catchup_mode:
                        flushed = self._flush_dirty_latest()
                        self._catchup_mode = False
                        logger.warning(
                            f"[Consumer] catchup done; flushed={flushed}; resume fullcalc"
                        )
                    continue
                _key, raw = item
                ev = BarCloseEvent.from_dict(json.loads(raw))
                self.handle_bar_close(ev)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                logger.error(f"[Consumer] loop error: {e}")
                logger.debug(traceback.format_exc())

    def _emit_runtime(self, event) -> bool:
        try:
            return bool(self.runtime_logger.emit(event))
        except Exception:
            return False


@click.command()
@click.option("--max-bars", default=20000, type=int)
@click.option("--workers", default=None, type=int)
@click.option("--max-inflight", default=None, type=int)
@click.option(
    "--prewarm/--no-prewarm", default=True, help="启动时预热历史窗口并推送结构"
)
def main(max_bars: int, workers: int | None, max_inflight: int | None, prewarm: bool):
    consumer = StrategyConsumer(
        max_bars=max_bars,
        fullcalc_workers=workers,
        fullcalc_max_inflight=max_inflight,
    )
    if prewarm:
        consumer.prewarm()
    consumer.run_forever()


_runtime_logger = None


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        _runtime_logger = RuntimeEventLogger("xt_consumer")
    return _runtime_logger


if __name__ == "__main__":
    main()
