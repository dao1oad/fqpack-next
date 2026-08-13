# -*- coding: utf-8 -*-
"""根②失败语义契约测试：读不到/无效数据 = 不交易 + reason_code 运行事件。"""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

sys.modules.setdefault("freshquant.message", types.ModuleType("freshquant.message"))
from freshquant.strategy.guardian_buy_grid import GuardianBuyGridService  # noqa: E402

sys.modules.pop("freshquant.message", None)


class _FakeLogger:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)
        return True


class _FakeLock:
    def acquire(self, _key, *, ttl_seconds):
        return True


def _build_grid_service(database=None, runtime_logger=None):
    class _FakeDatabase(dict):
        def __getitem__(self, name):
            if name not in self:
                self[name] = _FakeCollection()
            return dict.__getitem__(self, name)

    return GuardianBuyGridService(
        database=database or _FakeDatabase(),
        get_trade_amount_fn=lambda _code: 50000,
        runtime_logger=runtime_logger,
    )


class _FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find_one(self, query, projection=None):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None


# ---------------------------------------------------------------- A4 guardian_buy_grid


def _grid_config_database():
    class _FakeDatabase(dict):
        def __getitem__(self, name):
            if name not in self:
                self[name] = _FakeCollection()
            return dict.__getitem__(self, name)

    db = _FakeDatabase()
    db["guardian_buy_grid_configs"] = _FakeCollection(
        [
            {
                "code": "000001",
                "BUY-1": 10.0,
                "BUY-2": 9.0,
                "BUY-3": 8.0,
                "max_position_amounts": [200000, 350000, 500000],
                "buy_enabled": [True, True, True],
                "enabled": True,
            }
        ]
    )
    return db


def test_a4_ledger_occupancy_read_failure_blocks_decision(monkeypatch):
    monkeypatch.setattr(
        "freshquant.strategy.guardian_buy_grid._get_buy_amount_exponent",
        lambda: 2.0,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian_buy_grid._get_min_buy_amount",
        lambda *_args, **_kwargs: 10000,
    )
    logger = _FakeLogger()
    service = _build_grid_service(_grid_config_database(), runtime_logger=logger)
    service._load_position_capacity = lambda _code: (100000.0, 800000.0)

    def _fail_list_slices(symbol, repository):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(
        "freshquant.order_management.entry_adapter.list_open_entry_slices_compat",
        _fail_list_slices,
    )

    decision = service.build_holding_add_decision("000001", 9.5)

    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "position_capacity_unavailable"
    emitted = [
        e for e in logger.events if e["reason_code"] == "ledger_occupancy_unavailable"
    ]
    assert len(emitted) == 1
    assert emitted[0]["node"] == "load_ledger_occupancy"


def test_a4_pending_buy_amount_read_failure_blocks_decision(monkeypatch):
    monkeypatch.setattr(
        "freshquant.strategy.guardian_buy_grid._get_buy_amount_exponent",
        lambda: 2.0,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian_buy_grid._get_min_buy_amount",
        lambda *_args, **_kwargs: 10000,
    )
    logger = _FakeLogger()
    service = _build_grid_service(_grid_config_database(), runtime_logger=logger)
    service._load_position_capacity = lambda _code: (100000.0, 800000.0)

    class _BrokenRepository:
        def list_broker_orders(self, **_kwargs):
            raise RuntimeError("mongo down")

    service.order_repository = _BrokenRepository()

    decision = service.build_holding_add_decision("000001", 9.5)

    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "position_capacity_unavailable"
    emitted = [
        e for e in logger.events if e["reason_code"] == "pending_buy_amount_unavailable"
    ]
    assert len(emitted) == 1


def test_a4_takeprofit_prices_read_failure_skips_corridor(monkeypatch):
    monkeypatch.setattr(
        "freshquant.strategy.guardian_buy_grid._get_buy_amount_exponent",
        lambda: 2.0,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian_buy_grid._get_min_buy_amount",
        lambda *_args, **_kwargs: 10000,
    )
    logger = _FakeLogger()
    service = _build_grid_service(_grid_config_database(), runtime_logger=logger)

    class _BoomCollection:
        def find_one(self, _query):
            raise RuntimeError("mongo down")

    class _BoomDB:
        def __getitem__(self, _name):
            return _BoomCollection()

    try:
        import freshquant.order_management.db as om_db
    except ImportError:
        om_db = types.ModuleType("freshquant.order_management.db")
        monkeypatch.setitem(sys.modules, "freshquant.order_management.db", om_db)
    monkeypatch.setattr(om_db, "DBOrderManagement", _BoomDB())

    decision = service.build_holding_add_decision("000001", 11.0)

    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "takeprofit_prices_unavailable"
    emitted = [
        e for e in logger.events if e["reason_code"] == "takeprofit_prices_unavailable"
    ]
    assert len(emitted) == 1


def test_a4_position_capacity_read_failure_emits_event(monkeypatch):
    logger = _FakeLogger()
    service = _build_grid_service(runtime_logger=logger)

    class _BrokenPositionRepository:
        def get_symbol_snapshot(self, _code):
            raise RuntimeError("position snapshot read failed")

    service.position_repository = _BrokenPositionRepository()
    result = service._load_position_capacity("000001")

    assert result == (None, None)
    emitted = [
        e for e in logger.events if e["reason_code"] == "position_capacity_read_failed"
    ]
    assert len(emitted) == 1


# ---------------------------------------------------------------- B2/S2 tpsl submit


def _build_tpsl_service(runtime_logger):
    from freshquant.tpsl.service import TpslService

    return TpslService(runtime_logger=runtime_logger, lock_client=_FakeLock())


def _base_buy_decision(**overrides):
    decision = {
        "symbol": "000001",
        "quantity": 100,
        "price": 10.0,
        "grid_level": "BUY-1",
        "effective_stage_cap": 800000.0,
    }
    decision.update(overrides)
    return decision


def test_b2_missing_cap_blocks_base_buy_with_reason(monkeypatch):
    logger = _FakeLogger()
    service = _build_tpsl_service(logger)

    result = service.submit_base_buy_batch(
        _base_buy_decision(effective_stage_cap=None),
        trace_id="t1",
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "base_buy_cap_missing"
    assert any(e["reason_code"] == "base_buy_cap_missing" for e in logger.events)


def test_b2_capacity_recheck_exception_blocks_base_buy(monkeypatch):
    from freshquant.tpsl import service as tpsl_service

    logger = _FakeLogger()
    service = _build_tpsl_service(logger)

    class _BoomService:
        def _resolve_remaining_capacity(self, *_args, **_kwargs):
            raise RuntimeError("ledger read failed")

    monkeypatch.setattr(
        tpsl_service,
        "_get_ladder_state",
        lambda: None,
        raising=False,
    )
    import freshquant.strategy.guardian_buy_grid as grid_module

    monkeypatch.setattr(
        grid_module,
        "get_guardian_buy_grid_service",
        lambda: _BoomService(),
    )

    result = service.submit_base_buy_batch(
        _base_buy_decision(),
        trace_id="t1",
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "capacity_recheck_failed"
    assert any(e["reason_code"] == "capacity_recheck_failed" for e in logger.events)


def test_b2_capacity_none_blocks_base_buy(monkeypatch):
    from freshquant.tpsl import service as tpsl_service

    logger = _FakeLogger()
    service = _build_tpsl_service(logger)

    class _NoneCapacityService:
        def _resolve_remaining_capacity(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        tpsl_service,
        "_get_ladder_state",
        lambda: None,
        raising=False,
    )
    import freshquant.strategy.guardian_buy_grid as grid_module

    monkeypatch.setattr(
        grid_module,
        "get_guardian_buy_grid_service",
        lambda: _NoneCapacityService(),
    )

    result = service.submit_base_buy_batch(
        _base_buy_decision(),
        trace_id="t1",
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "position_capacity_unavailable"


# ---------------------------------------------------------------- 有效 tick 门槛


def test_tick_gate_rejects_zero_bid1_without_trading(monkeypatch):
    from freshquant.tpsl.consumer import TpslTickConsumer

    class _FakeService:
        def __init__(self):
            self.calls = []

        def evaluate_base_buyline(self, **_kwargs):
            self.calls.append("buy_line")
            return None

        def evaluate_takeprofit(self, **_kwargs):
            self.calls.append("tp")
            return None

    logger = _FakeLogger()
    service = _FakeService()
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sz000001"],
        buy_line_universe_loader=lambda: [],
        refresh_interval_s=999,
        runtime_logger=logger,
        now_provider=lambda: 1744000000,
    )

    result = consumer.handle_tick(
        {
            "code": "sz000001",
            "ask1": 10.8,
            "bid1": 0.0,
            "last_price": 10.0,
            "tick_time": 1744000000,
        }
    )

    assert result is None
    assert service.calls == []
    assert any(e["reason_code"] == "invalid_tick_quote" for e in logger.events)


def test_tick_gate_rejects_invalid_tick_time():
    from freshquant.tpsl.consumer import TpslTickConsumer

    class _FakeService:
        def __init__(self):
            self.calls = []

        def evaluate_base_buyline(self, **_kwargs):
            self.calls.append("buy_line")
            return None

        def evaluate_takeprofit(self, **_kwargs):
            self.calls.append("tp")
            return None

    logger = _FakeLogger()
    service = _FakeService()
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sz000001"],
        buy_line_universe_loader=lambda: [],
        refresh_interval_s=999,
        runtime_logger=logger,
        now_provider=lambda: 1744000000,
    )

    result = consumer.handle_tick(
        {
            "code": "sz000001",
            "ask1": 10.8,
            "bid1": 10.0,
            "last_price": 10.0,
            "tick_time": 0,
        }
    )

    assert result is None
    assert service.calls == []
    assert any(e["reason_code"] == "invalid_tick_time" for e in logger.events)


def test_tick_gate_allows_valid_tick():
    from freshquant.tpsl.consumer import TpslTickConsumer

    class _FakeService:
        def __init__(self):
            self.calls = []

        def evaluate_base_buyline(self, **_kwargs):
            self.calls.append("buy_line")
            return None

        def evaluate_takeprofit(self, **_kwargs):
            self.calls.append("tp")
            return None

    logger = _FakeLogger()
    service = _FakeService()
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sz000001"],
        buy_line_universe_loader=lambda: [],
        refresh_interval_s=999,
        runtime_logger=logger,
        now_provider=lambda: 1744000000,
    )

    result = consumer.handle_tick(
        {
            "code": "sz000001",
            "ask1": 10.8,
            "bid1": 10.0,
            "last_price": 10.2,
            "tick_time": 1744000000,
        }
    )

    assert result is None
    assert service.calls == ["tp"]


# ---------------------------------------------------------------- A8/D3 monitor


def _signal(signal_type: str, *, tags=None):
    import pendulum

    from freshquant.signal.astock.job.monitor_helpers_event import GuardianSignal

    return GuardianSignal(
        signal_type=signal_type,
        fire_time=pendulum.now(),
        price=10.0,
        stop_lose_price=9.0,
        tags=list(tags or []),
    )


def test_a8_arranged_fills_read_failure_skips_1m_signal(monkeypatch):
    import freshquant.signal.astock.job.monitor_stock_zh_a_min as monitor

    saved = []
    gate_events = []
    listeners = []

    class FakeListener:
        def __init__(self, callback, **kwargs):
            self.callback = callback
            self.filter_codes = kwargs["filter_codes"]
            self.filter_periods = kwargs["filter_periods"]
            listeners.append(self)

        def start(self):
            self.callback(
                "sz000001",
                "1min",
                {
                    "_bar_time": 1744000000,
                    "_signals": [_signal("buy_v_reverse")],
                },
            )

        def update_filter_codes(self, _codes):
            pass

        def get_stats(self):
            raise KeyboardInterrupt

        def stop(self):
            pass

    class FakeThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

    def fake_save(*args, **kwargs):
        saved.append((args[0], kwargs.get("fills")))

    def fake_gate_event(**kwargs):
        gate_events.append(kwargs)
        return True

    def fail_fills(_code):
        raise RuntimeError("ledger read failed")

    monkeypatch.setattr(
        monitor,
        "system_settings",
        SimpleNamespace(
            monitor=SimpleNamespace(
                xtdata_trading_mode=True,
                xtdata_screening_mode=True,
                xtdata_max_symbols=1,
            )
        ),
    )
    monkeypatch.setattr(
        monitor, "get_stock_holding_codes", lambda: ["000001"], raising=False
    )
    monkeypatch.setattr(monitor, "queryMustPoolCodes", lambda: [], raising=False)
    monkeypatch.setattr(
        monitor, "get_arranged_stock_fill_list", fail_fills, raising=False
    )
    monkeypatch.setattr(
        monitor,
        "calculate_guardian_signals_latest",
        lambda *, data, fire_time: data["_signals"],
    )
    monkeypatch.setattr(monitor, "save_a_stock_signal", fake_save)
    monkeypatch.setattr(monitor, "BarEventListener", FakeListener)
    monkeypatch.setattr(monitor, "sleep", lambda _seconds: None)
    monkeypatch.setattr(monitor, "_emit_guardian_signal_gate_event", fake_gate_event)
    import threading

    monkeypatch.setattr(threading, "Thread", FakeThread)

    monitor.monitor_stock_zh_a_min_event_driven()

    assert saved == []
    assert any(e["reason_code"] == "structure_context_unavailable" for e in gate_events)


def test_d3_invalid_bar_time_counted_and_emitted(monkeypatch):
    import freshquant.signal.astock.job.monitor_stock_zh_a_min as monitor

    monitor._invalid_bar_time_counter["count"] = 0
    monitor._invalid_bar_time_counter["last_emitted"] = 0
    saved = []
    gate_events = []
    listeners = []

    class FakeListener:
        def __init__(self, callback, **kwargs):
            self.callback = callback
            self.filter_codes = kwargs["filter_codes"]
            self.filter_periods = kwargs["filter_periods"]
            listeners.append(self)

        def start(self):
            self.callback("sz000001", "1min", {"_bar_time": 0, "_signals": []})

        def update_filter_codes(self, _codes):
            pass

        def get_stats(self):
            return {
                "received": 1,
                "enqueued": 1,
                "processed": 0,
                "filtered": 0,
                "dropped": 0,
                "errors": 0,
                "queue_depth": 0,
                "queue_size": 1,
                "queue_max_depth": 0,
            }

        def stop(self):
            pass

    class FakeThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

    def fake_save(*args, **kwargs):
        saved.append(args)

    def fake_gate_event(**kwargs):
        gate_events.append(kwargs)
        return True

    sleep_calls = {"count": 0}

    def fake_sleep(_seconds):
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(
        monitor,
        "system_settings",
        SimpleNamespace(
            monitor=SimpleNamespace(
                xtdata_trading_mode=True,
                xtdata_screening_mode=True,
                xtdata_max_symbols=1,
            )
        ),
    )
    monkeypatch.setattr(
        monitor, "get_stock_holding_codes", lambda: ["000001"], raising=False
    )
    monkeypatch.setattr(monitor, "queryMustPoolCodes", lambda: [], raising=False)
    monkeypatch.setattr(monitor, "save_a_stock_signal", fake_save)
    monkeypatch.setattr(monitor, "BarEventListener", FakeListener)
    monkeypatch.setattr(monitor, "sleep", fake_sleep)
    monkeypatch.setattr(monitor, "_emit_guardian_signal_gate_event", fake_gate_event)
    import threading

    monkeypatch.setattr(threading, "Thread", FakeThread)

    monitor.monitor_stock_zh_a_min_event_driven()

    assert monitor._invalid_bar_time_counter["count"] >= 1
    assert saved == []
    assert any(e["reason_code"] == "invalid_bar_time_dropped" for e in gate_events)


# ---------------------------------------------------------------- 信号计算失败语义


def test_signal_calc_failure_emits_event_and_produces_no_signal(monkeypatch):
    import freshquant.signal.astock.job.monitor_helpers_event as helpers

    logger = _FakeLogger()
    monkeypatch.setattr(helpers, "_get_runtime_logger", lambda: logger)

    def _fail_clxs(*_args, **_kwargs):
        raise RuntimeError("clx engine failure")

    try:
        import fqcopilot as fqcopilot_module
    except ImportError:
        fqcopilot_module = types.ModuleType("fqcopilot")
        monkeypatch.setitem(sys.modules, "fqcopilot", fqcopilot_module)
    monkeypatch.setattr(fqcopilot_module, "fq_clxs", _fail_clxs)

    result = helpers._clxs_last_signal(
        open_list=[1.0, 2.0],
        high_list=[2.0, 3.0],
        low_list=[0.5, 1.0],
        close_list=[1.5, 2.5],
        model_opt=9,
        trend_opt=0,
    )

    assert result == 0
    assert any(e["reason_code"] == "signal_calc_unavailable" for e in logger.events)


def test_bi_list_unavailable_blocks_signal_calculation(monkeypatch):
    import freshquant.signal.astock.job.monitor_helpers_event as helpers

    logger = _FakeLogger()
    monkeypatch.setattr(helpers, "_get_runtime_logger", lambda: logger)

    def _fail_recognise_bi(*_args, **_kwargs):
        raise RuntimeError("bi engine failure")

    try:
        import fqchan04 as fqchan04_module
    except ImportError:
        fqchan04_module = types.ModuleType("fqchan04")
        monkeypatch.setitem(sys.modules, "fqchan04", fqchan04_module)
    monkeypatch.setattr(fqchan04_module, "fq_recognise_bi", _fail_recognise_bi)

    data = {
        "open": [1.0, 2.0],
        "high": [2.0, 3.0],
        "low": [0.5, 1.0],
        "close": [1.5, 2.5],
    }
    import pendulum

    signals = helpers.calculate_guardian_signals_latest(
        data=data,
        fire_time=pendulum.now(),
    )

    assert signals == []
    assert any(e["reason_code"] == "bi_list_unavailable" for e in logger.events)


# ---------------------------------------------------------------- C7 reconcile 降级告警


def test_c7_mongo_unavailable_emits_degradation_event(monkeypatch):
    from freshquant.order_management.reconcile import service as reconcile

    events = []

    def fake_emit(symbol, *, reason_code, detail=""):
        events.append((symbol, reason_code))
        return None

    monkeypatch.setattr(reconcile, "_emit_price_snapshot_degraded_event", fake_emit)
    monkeypatch.setattr(reconcile, "_can_query_mongo", lambda _client: False)

    fake_mongodb = types.ModuleType("fqxtrade.database.mongodb")
    fake_mongodb.DBfreshquant = SimpleNamespace(client=object())
    monkeypatch.setitem(sys.modules, "fqxtrade.database.mongodb", fake_mongodb)
    monkeypatch.setitem(
        sys.modules, "fqxtrade.database", types.ModuleType("fqxtrade.database")
    )

    result = reconcile._load_latest_realtime_price_snapshot(
        "000001", {"stock_code": "000001.SZ"}
    )

    assert result is None
    assert events == [("000001", "price_snapshot_mongo_unavailable")]


# ---------------------------------------------------------------- guardian 成交参照读失败


def test_holding_buy_fill_reference_unavailable_skips_with_reason(monkeypatch):
    from freshquant.strategy.guardian import StrategyGuardian

    logger = _FakeLogger()
    strategy = StrategyGuardian()
    strategy.runtime_logger = logger
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.queryMustPoolCodes",
        lambda: [],
    )

    def _fail_ref(_code):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(
        "freshquant.strategy.guardian._resolve_guardian_buy_fill_reference",
        _fail_ref,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    import pendulum

    now = pendulum.now()
    strategy.on_signal(
        {
            "symbol": "000001",
            "code": "000001",
            "name": "Ping An Bank",
            "period": "1m",
            "fire_time": now,
            "discover_time": now,
            "price": 9.5,
            "stop_lose_price": 9.0,
            "position": "BUY_LONG",
            "remark": "contract-test",
            "tags": [],
            "zsdata": None,
            "fills": [],
        }
    )

    skipped = [
        e for e in logger.events if e["reason_code"] == "fill_reference_unavailable"
    ]
    assert len(skipped) >= 1
    assert skipped[0]["status"] == "skipped"
