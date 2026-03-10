import os
import subprocess
import sys
import textwrap
from pathlib import Path

from freshquant.market_data.xtdata.market_producer import emit_producer_heartbeat
from freshquant.market_data.xtdata.strategy_consumer import StrategyConsumer

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
