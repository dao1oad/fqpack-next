import importlib
from pathlib import Path

from freshquant.runtime_observability.logger import RuntimeEventLogger
from freshquant.runtime_observability.runtime_node import resolve_runtime_node


def test_emit_drops_when_queue_full(tmp_path):
    logger = RuntimeEventLogger(
        "guardian_strategy",
        root_dir=tmp_path,
        queue_maxsize=1,
    )
    logger._queue.put_nowait({"node": "occupied"})

    assert logger.emit({"node": "timing_check"}) is False

    snapshot = logger.snapshot()
    assert snapshot["dropped"] == 1


def test_close_flushes_events_and_reports_output_path(tmp_path):
    logger = RuntimeEventLogger("guardian_strategy", root_dir=tmp_path)

    assert logger.emit({"node": "receive_signal"}) is True

    logger.close()

    snapshot = logger.snapshot()
    assert snapshot["written"] >= 1
    assert snapshot["path"] is not None
    assert Path(snapshot["path"]).exists()


def test_emit_uses_component_runtime_node_when_not_explicit(tmp_path):
    logger = RuntimeEventLogger("guardian_strategy", root_dir=tmp_path)
    logger._stop.set()

    assert logger.emit({"node": "receive_signal"}) is True

    record = logger._queue.get_nowait()

    assert record["runtime_node"] == resolve_runtime_node("guardian_strategy")


def test_explicit_runtime_node_overrides_component_runtime_node(tmp_path):
    logger = RuntimeEventLogger(
        "guardian_strategy",
        root_dir=tmp_path,
        runtime_node="docker:manual",
    )
    logger._stop.set()

    assert logger.emit({"node": "receive_signal"}) is True

    record = logger._queue.get_nowait()

    assert record["runtime_node"] == "docker:manual"


def test_get_runtime_log_root_falls_back_to_bootstrap_file(tmp_path, monkeypatch):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "runtime:\n  log_dir: D:/fqpack/runtime/test-logs\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))
    monkeypatch.delenv("FQ_RUNTIME_LOG_DIR", raising=False)

    import freshquant.bootstrap_config as bootstrap_module
    import freshquant.runtime_observability.logger as logger_module

    bootstrap_module = importlib.reload(bootstrap_module)
    logger_module = importlib.reload(logger_module)

    assert bootstrap_module.bootstrap_config.runtime.log_dir == "D:/fqpack/runtime/test-logs"
    assert logger_module.get_runtime_log_root() == Path("D:/fqpack/runtime/test-logs")
