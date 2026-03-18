from __future__ import annotations

import sys
from collections.abc import Generator

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
def isolate_runtime_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> Generator[None, None, None]:
    _reset_runtime_logger_cache()
    monkeypatch.setenv("FQ_RUNTIME_LOG_DIR", str(tmp_path / "runtime"))
    yield
    _reset_runtime_logger_cache()


@pytest.fixture(autouse=True)
def isolate_runtime_observability_external_dependencies(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    module_name = getattr(getattr(request, "module", None), "__name__", "")
    if "runtime_observability" not in module_name:
        yield
        return

    import freshquant.runtime_observability.assembler as assembler_module
    import freshquant.runtime_observability.logger as logger_module

    assembler_module._lookup_symbol_name_cached.cache_clear()
    monkeypatch.setattr(
        assembler_module,
        "query_instrument_info",
        lambda symbol: (_ for _ in ()).throw(
            AssertionError(f"unexpected runtime observability symbol lookup: {symbol}")
        ),
    )
    monkeypatch.setattr(
        logger_module,
        "tool_trade_date_hist_sina",
        lambda: ["2026-03-07", "2026-03-10", "2026-03-11"],
    )
    yield
    assembler_module._lookup_symbol_name_cached.cache_clear()
