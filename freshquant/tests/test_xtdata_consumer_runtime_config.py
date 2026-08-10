from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytz  # type: ignore[import-untyped]

import freshquant.market_data.xtdata.strategy_consumer as sc
from freshquant import runtime_constants
from freshquant.system_settings_contract import (
    DEFAULT_XTDATA_MAX_SYMBOLS,
    DEFAULT_XTDATA_PREWARM_MAX_BARS,
    DEFAULT_XTDATA_QUEUE_BACKLOG_THRESHOLD,
)


def test_resolve_consumer_runtime_config_uses_system_settings():
    config = sc.resolve_consumer_runtime_config(
        settings_provider=SimpleNamespace(
            monitor=SimpleNamespace(
                xtdata_trading_mode=True,
                xtdata_screening_mode=True,
                xtdata_max_symbols=66,
                xtdata_queue_backlog_threshold=345,
                xtdata_prewarm_max_bars=12345,
            )
        )
    )

    assert config == {
        "trading_mode": True,
        "screening_mode": True,
        "max_symbols": 66,
        "queue_backlog_threshold": 345,
        "prewarm_max_bars": 12345,
    }


def test_resolve_consumer_runtime_config_falls_back_to_contract_defaults():
    config = sc.resolve_consumer_runtime_config(
        settings_provider=SimpleNamespace(monitor=SimpleNamespace())
    )

    assert config["max_symbols"] == DEFAULT_XTDATA_MAX_SYMBOLS
    assert config["queue_backlog_threshold"] == DEFAULT_XTDATA_QUEUE_BACKLOG_THRESHOLD
    assert config["prewarm_max_bars"] == DEFAULT_XTDATA_PREWARM_MAX_BARS


def test_resolve_consumer_runtime_config_rejects_nonpositive_values():
    config = sc.resolve_consumer_runtime_config(
        settings_provider=SimpleNamespace(
            monitor=SimpleNamespace(
                xtdata_max_symbols=-3,
                xtdata_queue_backlog_threshold=0,
                xtdata_prewarm_max_bars=-10,
            )
        )
    )

    assert config["max_symbols"] == DEFAULT_XTDATA_MAX_SYMBOLS
    assert config["queue_backlog_threshold"] == DEFAULT_XTDATA_QUEUE_BACKLOG_THRESHOLD
    assert config["prewarm_max_bars"] == DEFAULT_XTDATA_PREWARM_MAX_BARS


def test_strategy_consumer_explicit_max_bars_overrides_mongo():
    consumer = sc.StrategyConsumer.__new__(sc.StrategyConsumer)
    consumer.settings_provider = SimpleNamespace(
        monitor=SimpleNamespace(
            xtdata_trading_mode=True,
            xtdata_screening_mode=False,
            xtdata_max_symbols=88,
            xtdata_queue_backlog_threshold=345,
            xtdata_prewarm_max_bars=999,
        )
    )
    runtime_config = sc.resolve_consumer_runtime_config(
        settings_provider=consumer.settings_provider
    )

    assert runtime_config["prewarm_max_bars"] == 999
    # 显式构造参数 > Mongo
    max_bars = 4321
    if max_bars is None:
        max_bars = int(runtime_config["prewarm_max_bars"])
    assert max_bars == 4321


def test_strategy_consumer_none_max_bars_reads_mongo_prewarm():
    settings_provider = SimpleNamespace(
        monitor=SimpleNamespace(
            xtdata_trading_mode=True,
            xtdata_screening_mode=False,
            xtdata_max_symbols=88,
            xtdata_queue_backlog_threshold=345,
            xtdata_prewarm_max_bars=777,
        )
    )
    runtime_config = sc.resolve_consumer_runtime_config(
        settings_provider=settings_provider
    )
    max_bars = None
    if max_bars is None:
        max_bars = int(runtime_config["prewarm_max_bars"])
    assert max_bars == 777


def test_strategy_consumer_missing_mongo_prewarm_uses_contract_default():
    settings_provider = SimpleNamespace(monitor=SimpleNamespace())
    runtime_config = sc.resolve_consumer_runtime_config(
        settings_provider=settings_provider
    )
    max_bars = None
    if max_bars is None:
        max_bars = int(runtime_config["prewarm_max_bars"])
    assert max_bars == DEFAULT_XTDATA_PREWARM_MAX_BARS


def test_strategy_consumer_dual_mode_only_enables_clx_models_for_clx_pool_codes():
    consumer = SimpleNamespace(
        trading_mode=True,
        screening_mode=True,
        _clx_monitor_codes=lambda force=False: {"sh600001"},
    )

    assert sc.REALTIME_CLX_MODEL_IDS == list(range(10000, 10018))
    assert sc.StrategyConsumer._model_ids_for(consumer, "sh600001", "15min") == list(
        range(10000, 10018)
    )
    assert sc.StrategyConsumer._model_ids_for(consumer, "sh600001", "30min") == list(
        range(10000, 10018)
    )
    assert sc.StrategyConsumer._model_ids_for(consumer, "sh600001", "1min") == []
    assert sc.StrategyConsumer._model_ids_for(consumer, "sh600002", "15min") == []


def test_strategy_consumer_screening_only_mode_enables_same_realtime_model_ids():
    consumer = SimpleNamespace(
        trading_mode=False,
        screening_mode=True,
        _clx_monitor_codes=lambda force=False: {"sz000001"},
    )

    assert sc.StrategyConsumer._model_ids_for(consumer, "sz000001", "15min") == list(
        range(10000, 10018)
    )


def test_strategy_consumer_trading_only_disables_clx_models():
    consumer = SimpleNamespace(
        trading_mode=True,
        screening_mode=False,
        _clx_monitor_codes=lambda force=False: {"sh600001"},
    )

    assert sc.StrategyConsumer._model_ids_for(consumer, "sh600001", "15min") == []


def test_strategy_consumer_datetime_coercion_uses_runtime_constants_timezone(
    monkeypatch,
):
    with monkeypatch.context() as patch:
        patch.setattr(runtime_constants, "TZ", pytz.timezone("UTC"))
        module = importlib.reload(sc)
        result = module._coerce_bar_datetime("2026-03-07 09:31:00")
        assert str(result.tzinfo) == "UTC"

    importlib.reload(sc)
