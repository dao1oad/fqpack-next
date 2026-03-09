from pathlib import Path

from freshquant.runtime_observability.logger import RuntimeEventLogger


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
