from __future__ import annotations

import sys

import pytest

_RUNTIME_LOGGER_MODULES = (
    "freshquant.order_management.submit.service",
    "freshquant.order_management.ingest.xt_reports",
    "freshquant.order_management.reconcile.service",
    "freshquant.position_management.service",
    "freshquant.strategy.guardian",
    "freshquant.tpsl.service",
    "freshquant.tpsl.consumer",
    "freshquant.market_data.xtdata.market_producer",
    "freshquant.market_data.xtdata.strategy_consumer",
    "morningglory.fqxtrade.fqxtrade.xtquant.broker",
    "morningglory.fqxtrade.fqxtrade.xtquant.puppet",
)


def _reset_runtime_logger_cache() -> None:
    for module_name in _RUNTIME_LOGGER_MODULES:
        module = sys.modules.get(module_name)
        if module is None or not hasattr(module, "_runtime_logger"):
            continue
        logger = getattr(module, "_runtime_logger", None)
        if logger is not None and hasattr(logger, "close"):
            try:
                logger.close()
            except Exception:
                pass
        setattr(module, "_runtime_logger", None)


@pytest.fixture(autouse=True)
def isolate_runtime_logs(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _reset_runtime_logger_cache()
    monkeypatch.setenv("FQ_RUNTIME_LOG_DIR", str(tmp_path / "runtime"))
    yield
    _reset_runtime_logger_cache()
