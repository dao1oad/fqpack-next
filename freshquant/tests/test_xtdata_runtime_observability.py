import os
import subprocess
import sys
import textwrap
import threading
from datetime import datetime
from pathlib import Path

from freshquant.market_data.xtdata.market_producer import (
    AsyncBatchQueue,
    ProducerHeartbeatState,
    ProducerRecoveryGuard,
    emit_producer_heartbeat,
)
from freshquant.market_data.xtdata.strategy_consumer import (
    ConsumerHeartbeatState,
    StrategyConsumer,
)
from freshquant.runtime_constants import TZ

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FakeRuntimeLogger:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(dict(event))
        return True


def test_producer_heartbeat_emits_runtime_event():
    runtime_logger = FakeRuntimeLogger()

    emit_producer_heartbeat(runtime_logger=runtime_logger, rx_age_s=1.2, codes=20)

    assert runtime_logger.events == [
        {
            "component": "xt_producer",
            "node": "heartbeat",
            "event_type": "heartbeat",
            "status": "info",
            "metrics": {"rx_age_s": 1.2, "codes": 20},
            "payload": {},
        }
    ]


def test_consumer_heartbeat_emits_runtime_event():
    runtime_logger = FakeRuntimeLogger()
    consumer = StrategyConsumer.__new__(StrategyConsumer)
    consumer.runtime_logger = runtime_logger

    consumer.emit_runtime_heartbeat(backlog_sum=8, batches=3, max_lag_s=2.5)

    assert runtime_logger.events == [
        {
            "component": "xt_consumer",
            "node": "heartbeat",
            "event_type": "heartbeat",
            "status": "info",
            "metrics": {"backlog_sum": 8, "batches": 3, "max_lag_s": 2.5},
            "payload": {},
        }
    ]


def test_producer_heartbeat_state_tracks_recent_tick_activity_over_five_minutes():
    state = ProducerHeartbeatState(window_s=300)

    state.record_tick_batch(tick_count=4, now_ts=100.0)
    state.record_tick_batch(tick_count=6, now_ts=250.0)

    assert state.snapshot(now_ts=400.0, subscribed_codes=12, connected=True) == {
        "connected": 1,
        "subscribed_codes": 12,
        "tick_batches_5m": 2,
        "tick_count_5m": 10,
        "rx_age_s": 150.0,
    }


def test_async_batch_queue_runs_handler_on_background_thread():
    handled = []
    done = threading.Event()

    def handler(batch):
        handled.append((threading.get_ident(), batch))
        done.set()

    queue = AsyncBatchQueue(
        handler,
        max_pending_batches=4,
        name="TestAsyncBatchQueue",
    ).start()
    submit_thread_id = threading.get_ident()
    queue.submit([("QUEUE:TICK_QUOTE:1", '{"event":"TICK_QUOTE"}')])

    assert done.wait(timeout=1.0) is True
    assert handled == [
        (
            handled[0][0],
            [("QUEUE:TICK_QUOTE:1", '{"event":"TICK_QUOTE"}')],
        )
    ]
    assert handled[0][0] != submit_thread_id

    queue.stop()


def test_async_batch_queue_drops_oldest_batch_when_pending_queue_is_full():
    queue = AsyncBatchQueue(
        lambda batch: None,
        max_pending_batches=2,
        name="TestAsyncBatchQueueDropOldest",
    )

    queue.submit(["batch-1"])
    queue.submit(["batch-2"])
    queue.submit(["batch-3"])

    assert queue.snapshot() == {
        "pending_batches": 2,
        "dropped_batches": 1,
    }


def test_producer_recovery_guard_escalates_from_resubscribe_to_reconnect():
    guard = ProducerRecoveryGuard(
        stale_after_s=120.0,
        retry_interval_s=30.0,
        reconnect_every=2,
    )
    trading_dt = datetime(2026, 4, 8, 10, 0, tzinfo=TZ)
    stale_snapshot = {
        "connected": 1,
        "subscribed_codes": 14,
        "rx_age_s": 180.0,
    }

    assert (
        guard.next_action(now_ts=180.0, now_dt=trading_dt, snapshot=stale_snapshot)
        == "resubscribe"
    )
    assert (
        guard.next_action(now_ts=200.0, now_dt=trading_dt, snapshot=stale_snapshot)
        is None
    )
    assert (
        guard.next_action(now_ts=211.0, now_dt=trading_dt, snapshot=stale_snapshot)
        == "reconnect"
    )


def test_producer_recovery_guard_resets_after_tick_flow_returns():
    guard = ProducerRecoveryGuard(
        stale_after_s=120.0,
        retry_interval_s=30.0,
        reconnect_every=2,
    )
    trading_dt = datetime(2026, 4, 8, 10, 0, tzinfo=TZ)
    stale_snapshot = {
        "connected": 1,
        "subscribed_codes": 14,
        "rx_age_s": 180.0,
    }
    healthy_snapshot = {
        "connected": 1,
        "subscribed_codes": 14,
        "rx_age_s": 5.0,
    }

    assert (
        guard.next_action(now_ts=180.0, now_dt=trading_dt, snapshot=stale_snapshot)
        == "resubscribe"
    )
    assert (
        guard.next_action(now_ts=181.0, now_dt=trading_dt, snapshot=healthy_snapshot)
        is None
    )
    assert (
        guard.next_action(now_ts=220.0, now_dt=trading_dt, snapshot=stale_snapshot)
        == "resubscribe"
    )


def test_producer_recovery_guard_skips_recovery_outside_trading_session():
    guard = ProducerRecoveryGuard(
        stale_after_s=120.0,
        retry_interval_s=30.0,
        reconnect_every=2,
    )
    stale_snapshot = {
        "connected": 1,
        "subscribed_codes": 14,
        "rx_age_s": 600.0,
    }

    assert (
        guard.next_action(
            now_ts=600.0,
            now_dt=datetime(2026, 4, 8, 12, 0, tzinfo=TZ),
            snapshot=stale_snapshot,
        )
        is None
    )


def test_consumer_heartbeat_state_tracks_recent_processing_activity_over_five_minutes():
    state = ConsumerHeartbeatState(window_s=300)

    state.record_processed_bar(now_ts=100.0)
    state.record_processed_bar(now_ts=260.0)

    assert state.snapshot(
        now_ts=400.0,
        backlog_sum=8,
        scheduler_pending=3,
        catchup_mode=True,
    ) == {
        "backlog_sum": 8,
        "scheduler_pending": 3,
        "processed_bars_5m": 2,
        "last_bar_age_s": 140.0,
        "catchup_mode": 1,
    }


def _run_entrypoint(script: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(PROJECT_ROOT)
        if not pythonpath
        else str(PROJECT_ROOT) + os.pathsep + pythonpath
    )
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_market_producer_module_entry_reaches_xt_connect():
    result = _run_entrypoint(
        """
        import runpy
        import sys
        import types

        runtime_module = types.ModuleType("freshquant.runtime_observability.logger")

        class FakeRuntimeEventLogger:
            def __init__(self, component):
                self.component = component

            def emit(self, event):
                return True

        runtime_module.RuntimeEventLogger = FakeRuntimeEventLogger
        sys.modules["freshquant.runtime_observability.logger"] = runtime_module

        xtdata_module = types.SimpleNamespace(
            connect=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("XT_CONNECT_STOP")),
            subscribe_whole_quote=lambda *args, **kwargs: 1,
            unsubscribe_quote=lambda *args, **kwargs: None,
        )
        xtquant_module = types.ModuleType("xtquant")
        xtquant_module.xtdata = xtdata_module
        sys.modules["xtquant"] = xtquant_module
        sys.modules["xtquant.xtdata"] = xtdata_module
        sys.argv = ["market_producer"]
        runpy.run_module("freshquant.market_data.xtdata.market_producer", run_name="__main__")
        """
    )

    assert result.returncode != 0
    assert "XT_CONNECT_STOP" in (result.stderr or "")


def test_strategy_consumer_module_entry_reaches_executor_setup():
    result = _run_entrypoint(
        """
        import concurrent.futures
        import runpy
        import sys
        import types

        runtime_module = types.ModuleType("freshquant.runtime_observability.logger")

        class FakeRuntimeEventLogger:
            def __init__(self, component):
                self.component = component

            def emit(self, event):
                return True

        runtime_module.RuntimeEventLogger = FakeRuntimeEventLogger
        sys.modules["freshquant.runtime_observability.logger"] = runtime_module

        redis_module = types.ModuleType("freshquant.database.redis")
        redis_module.redis_db = object()
        sys.modules["freshquant.database.redis"] = redis_module

        param_module = types.ModuleType("freshquant.carnation.param")
        param_module.queryParam = lambda key, default=None: default
        sys.modules["freshquant.carnation.param"] = param_module

        class StopExecutor:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("CONSUMER_EXECUTOR_STOP")

        concurrent.futures.ProcessPoolExecutor = StopExecutor
        sys.argv = ["strategy_consumer", "--no-prewarm"]
        runpy.run_module("freshquant.market_data.xtdata.strategy_consumer", run_name="__main__")
        """
    )

    assert result.returncode != 0
    assert "CONSUMER_EXECUTOR_STOP" in (result.stderr or "")
