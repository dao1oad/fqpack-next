from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytz

import freshquant.market_data.xtdata.strategy_consumer as sc
from freshquant import runtime_constants


def test_resolve_consumer_runtime_config_uses_system_settings():
    config = sc.resolve_consumer_runtime_config(
        settings_provider=SimpleNamespace(
            monitor=SimpleNamespace(
                xtdata_mode="guardian_1m",
                xtdata_max_symbols=66,
                xtdata_queue_backlog_threshold=345,
            )
        )
    )

    assert config == {
        "mode": "guardian_1m",
        "max_symbols": 66,
        "queue_backlog_threshold": 345,
    }


def test_strategy_consumer_datetime_coercion_uses_runtime_constants_timezone(
    monkeypatch,
):
    with monkeypatch.context() as patch:
        patch.setattr(runtime_constants, "TZ", pytz.timezone("UTC"))
        module = importlib.reload(sc)
        result = module._coerce_bar_datetime("2026-03-07 09:31:00")
        assert str(result.tzinfo) == "UTC"

    importlib.reload(sc)
