# -*- coding: utf-8 -*-
"""双账本 #549 核心行为测试：对称阶梯状态机 / 买入线决策 / TPSL base 过滤 /
consumer 双集合 / ingest 打标 / 三段分桶分摊 / 零成交终态重开。
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass

import pymongo.errors

sys.modules.setdefault("freshquant.message", types.ModuleType("freshquant.message"))

import pytest

from freshquant.strategy.guardian_buy_grid import (
    BUY_LEVELS,
    GuardianBuyGridService,
    validate_tp_buy_config,
)
from freshquant.strategy.guardian_ladder import GuardianLadderState

sys.modules.pop("freshquant.message", None)


@dataclass
class _UpdateResult:
    matched_count: int
    modified_count: int
    upserted_id: str | None = None


class _DuplicateKey(pymongo.errors.DuplicateKeyError):
    pass


def _get_path(document, path):
    node = document
    for part in str(path).split("."):
        if isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError, TypeError):
                return None
            continue
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _set_path(document, path, value):
    parts = str(path).split(".")
    node = document
    for part in parts[:-1]:
        if isinstance(node, list):
            node = node[int(part)]
        else:
            node = node.setdefault(part, {})
    if isinstance(node, list):
        node[int(parts[-1])] = value
    else:
        node[parts[-1]] = value


def _matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, branch) for branch in expected):
                return False
            continue
        if key == "$and":
            if not all(_matches(document, branch) for branch in expected):
                return False
            continue
        if isinstance(expected, dict) and "$exists" in expected:
            actual = _get_path(document, key)
            if bool(expected["$exists"]) != (actual is not None):
                return False
            continue
        if isinstance(expected, dict) and "$ne" in expected:
            if _get_path(document, key) == expected["$ne"]:
                return False
            continue
        if _get_path(document, key) != expected:
            return False
    return True


def _apply_update(document, update):
    for operator, fields in update.items():
        if operator == "$set":
            for path, value in fields.items():
                _set_path(document, path, value)
        elif operator == "$setOnInsert":
            for path, value in fields.items():
                _set_path(document, path, value)
        elif operator == "$inc":
            for path, value in fields.items():
                current = _get_path(document, path)
                _set_path(
                    document,
                    path,
                    int(current or 0) + int(value),
                )
    return document


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(item) for item in docs or []]

    def find_one(self, query, projection=None):
        for doc in self.docs:
            if _matches(doc, query):
                return dict(doc)
        return None

    def find(self, query=None):
        query = query or {}
        return [dict(doc) for doc in self.docs if _matches(doc, query)]

    def insert_one(self, document):
        for doc in self.docs:
            if doc.get("_id") == document.get("_id"):
                raise _DuplicateKey("duplicate")
        self.docs.append(dict(document))
        return _UpdateResult(matched_count=1, modified_count=1)

    def update_one(self, query, update, upsert=False):
        for index, doc in enumerate(self.docs):
            if _matches(doc, query):
                # $setOnInsert 只在 upsert 插入时生效（与 Mongo 语义一致）
                applied = {
                    operator: fields
                    for operator, fields in update.items()
                    if operator != "$setOnInsert"
                }
                _apply_update(self.docs[index], applied)
                return _UpdateResult(matched_count=1, modified_count=1)
        if not upsert:
            return _UpdateResult(matched_count=0, modified_count=0)
        new_doc = dict(query)
        _apply_update(new_doc, update)
        self.docs.append(new_doc)
        return _UpdateResult(
            matched_count=0,
            modified_count=0,
            upserted_id=str(len(self.docs)),
        )


class FakeDatabase(dict):
    def __bool__(self):
        return True

    def __getitem__(self, name):
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def _build_ladder(
    *,
    buy_grid_docs=None,
    tp_state_docs=None,
    tp_profile_docs=None,
):
    return GuardianLadderState(
        buy_grid_database=FakeDatabase(
            {"guardian_buy_grid_states": FakeCollection(buy_grid_docs or [])}
        ),
        tp_database=FakeDatabase(
            {
                "om_takeprofit_states": FakeCollection(tp_state_docs or []),
                "om_takeprofit_profiles": FakeCollection(tp_profile_docs or []),
            }
        ),
        events_database=FakeDatabase(),
    )


def _profile_docs(code="000001"):
    return [
        {
            "symbol": code,
            "tiers": [
                {"level": 1, "price": 10.0, "manual_enabled": True},
                {"level": 2, "price": 11.0, "manual_enabled": True},
                {"level": 3, "price": 12.0, "manual_enabled": True},
            ],
        }
    ]


# ---------------------------------------------------------------------------
# LadderState 对称阶梯状态机
# ---------------------------------------------------------------------------


def test_ladder_default_state_has_all_buy_lines_armed():
    ladder = _build_ladder()
    state = ladder.get_state("000001")
    assert state["buy_line_armed"] == [True, True, True]
    assert state["armed_levels"] == {}


def test_buy_line_trigger_closes_trigger_and_above_and_rearms_tp():
    ladder = _build_ladder(
        buy_grid_docs=[{"code": "000001", "buy_line_armed": [True, True, True]}],
        tp_state_docs=[
            {"symbol": "000001", "armed_levels": {"1": False, "2": False, "3": False}}
        ],
        tp_profile_docs=_profile_docs(),
    )
    ok = ladder.on_buy_line_trigger(
        code="000001",
        level_index=1,
        event_key="ord_buy_1",
    )
    assert ok is True
    state = ladder.get_state("000001")
    # BUY-2 触发：关 BUY-1、BUY-2（索引 0..1），BUY-3 保持
    assert state["buy_line_armed"] == [False, False, True]
    # 全开止盈档
    assert state["armed_levels"] == {1: True, 2: True, 3: True}


def test_buy_line_trigger_is_idempotent_by_event_key():
    ladder = _build_ladder(
        buy_grid_docs=[{"code": "000001", "buy_line_armed": [True, True, True]}],
        tp_profile_docs=_profile_docs(),
    )
    assert (
        ladder.on_buy_line_trigger(code="000001", level_index=1, event_key="ord_buy_1")
        is True
    )
    assert (
        ladder.on_buy_line_trigger(code="000001", level_index=1, event_key="ord_buy_1")
        is False
    )
    state = ladder.get_state("000001")
    assert state["buy_line_armed"] == [False, False, True]


def test_buy_line_trigger_conflict_when_already_closed_by_other_process():
    ladder = _build_ladder(
        buy_grid_docs=[{"code": "000001", "buy_line_armed": [True, False, True]}],
        tp_profile_docs=_profile_docs(),
    )
    assert (
        ladder.on_buy_line_trigger(
            code="000001", level_index=1, event_key="ord_buy_other"
        )
        is False
    )


def test_takeprofit_fill_closes_levels_up_to_n_and_rearms_buy_lines():
    ladder = _build_ladder(
        buy_grid_docs=[{"code": "000001", "buy_line_armed": [False, False, False]}],
        tp_state_docs=[
            {"symbol": "000001", "armed_levels": {"1": True, "2": True, "3": True}}
        ],
        tp_profile_docs=_profile_docs(),
    )
    ok = ladder.on_takeprofit_fill(
        code="000001",
        level=2,
        event_key="ord_tp_1",
    )
    assert ok is True
    state = ladder.get_state("000001")
    assert state["armed_levels"] == {1: False, 2: False, 3: True}
    assert state["buy_line_armed"] == [True, True, True]


def test_zero_fill_terminal_reopens_matching_line():
    ladder = _build_ladder(
        buy_grid_docs=[{"code": "000001", "buy_line_armed": [False, False, True]}],
        tp_profile_docs=_profile_docs(),
    )
    assert (
        ladder.on_buy_zero_fill_terminal(
            code="000001", level_index=1, event_key="ord_buy_1"
        )
        is True
    )
    assert ladder.get_state("000001")["buy_line_armed"] == [False, True, True]
    assert (
        ladder.on_takeprofit_zero_fill_terminal(
            code="000001", level=3, event_key="ord_tp_1"
        )
        is True
    )
    assert ladder.get_state("000001")["armed_levels"] == {3: True}


def test_activate_takeprofit_is_idempotent_and_repeatable():
    ladder = _build_ladder(
        tp_state_docs=[
            {"symbol": "000001", "armed_levels": {"1": False, "2": False, "3": False}}
        ],
        tp_profile_docs=_profile_docs(),
    )
    assert ladder.activate_takeprofit("000001") is True
    assert ladder.get_state("000001")["armed_levels"] == {1: True, 2: True, 3: True}
    assert ladder.activate_takeprofit("000001") is True
    assert ladder.get_state("000001")["armed_levels"] == {1: True, 2: True, 3: True}


def test_tp_buy_config_validation_rejects_inversion():
    errors = validate_tp_buy_config([10.0, 9.0, 8.0])
    assert errors == []
    # 无 profile 时只校验 BUY 线序
    assert validate_tp_buy_config([8.0, 9.0, 10.0]) != []
    assert validate_tp_buy_config([0.0, 9.0, 8.0]) != []


# ---------------------------------------------------------------------------
# build_base_line_decision（买入线决策）
# ---------------------------------------------------------------------------


def _build_grid_service(database):
    service = GuardianBuyGridService(database=database)
    service._load_position_capacity = lambda _code: (500000.0, 2000000.0)
    service._load_ledger_occupancy = lambda _code, _price: {
        "base_quantity": 0,
        "t_quantity": 0,
        "d_plus_c": 0.0,
    }
    service._load_pending_buy_amount = lambda _code: 0.0
    return service


def _grid_config_docs(**overrides):
    doc = {
        "code": "000001",
        "BUY-1": 10.0,
        "BUY-2": 9.0,
        "BUY-3": 8.0,
        "buy_enabled": [True, True, True],
        "max_position_amounts": [200000, 350000, 500000],
        "enabled": True,
    }
    doc.update(overrides)
    return [doc]


def test_base_line_decision_uses_cap_minus_max_dc_mv_minus_pending(monkeypatch):
    monkeypatch.setattr(
        "freshquant.strategy.guardian_buy_grid._get_min_buy_amount",
        lambda *_args, **_kwargs: 10000,
    )
    service = _build_grid_service(
        FakeDatabase(
            {
                "guardian_buy_grid_configs": FakeCollection(_grid_config_docs()),
                "guardian_buy_grid_states": FakeCollection(
                    [{"code": "000001", "buy_line_armed": [True, True, True]}]
                ),
            }
        )
    )
    service._load_ledger_occupancy = lambda _code, _price: {
        "base_quantity": 1000,
        "t_quantity": 500,
        "d_plus_c": 1500 * 8.5,
    }
    service._load_pending_buy_amount = lambda _code: 10000.0
    decision = service.build_base_line_decision("000001", 8.5)
    # 触发 BUY-1（8.5 ≤ 10.0，最高档优先），cap1=200000
    # R = 350000 − max(12750, 500000) − 10000 = 0 → 无剩余
    assert decision["grid_level"] == "BUY-1"
    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "below_min_buy_amount"


def test_base_line_decision_skips_disarmed_and_disabled_lines(monkeypatch):
    monkeypatch.setattr(
        "freshquant.strategy.guardian_buy_grid._get_min_buy_amount",
        lambda *_args, **_kwargs: 10000,
    )
    service = _build_grid_service(
        FakeDatabase(
            {
                "guardian_buy_grid_configs": FakeCollection(
                    _grid_config_docs(buy_enabled=[False, False, True])
                ),
                "guardian_buy_grid_states": FakeCollection(
                    [{"code": "000001", "buy_line_armed": [False, False, True]}]
                ),
            }
        )
    )
    decision = service.build_base_line_decision("000001", 8.5)
    # BUY-2 disabled & disarmed → no hit
    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "no_armed_buy_line"


def test_base_line_decision_fails_closed_when_mv_missing(monkeypatch):
    monkeypatch.setattr(
        "freshquant.strategy.guardian_buy_grid._get_min_buy_amount",
        lambda *_args, **_kwargs: 10000,
    )
    service = _build_grid_service(
        FakeDatabase(
            {
                "guardian_buy_grid_configs": FakeCollection(_grid_config_docs()),
                "guardian_buy_grid_states": FakeCollection(
                    [{"code": "000001", "buy_line_armed": [True, True, True]}]
                ),
            }
        )
    )
    service._load_position_capacity = lambda _code: (None, None)
    decision = service.build_base_line_decision("000001", 8.5)
    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "position_capacity_unavailable"


def test_base_line_decision_quantity_and_config_invalid():
    service = _build_grid_service(
        FakeDatabase(
            {
                "guardian_buy_grid_configs": FakeCollection(
                    [
                        {
                            "code": "000001",
                            "BUY-1": 10.0,
                            "BUY-2": 9.0,
                            "BUY-3": 8.0,
                            "buy_enabled": [True, True, True],
                            "enabled": True,
                        }
                    ]
                ),
                "guardian_buy_grid_states": FakeCollection(
                    [{"code": "000001", "buy_line_armed": [True, True, True]}]
                ),
            }
        )
    )
    decision = service.build_base_line_decision("000001", 8.5)
    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "grid_position_cap_unconfigured"


def test_holding_add_break_zone_uses_global_cap_half_convergence(monkeypatch):
    monkeypatch.setattr(
        "freshquant.strategy.guardian_buy_grid._get_min_buy_amount",
        lambda *_args, **_kwargs: 10000,
    )
    service = _build_grid_service(
        FakeDatabase(
            {
                "guardian_buy_grid_configs": FakeCollection(_grid_config_docs()),
                "guardian_buy_grid_states": FakeCollection(
                    [{"code": "000001", "buy_active": [False, False, False]}]
                ),
            }
        )
    )
    service._load_position_capacity = lambda _code: (750000.0, 800000.0)
    decision = service.build_holding_add_decision("000001", 7.5)
    assert decision["stage"] == "BUY-3_BELOW"
    assert decision["effective_stage_cap"] == 800000.0
    assert decision["remaining_amount"] == 50000
    assert decision["capacity_ratio"] == 0.5
    assert decision["quantity"] == 3300


def test_holding_add_corridor_uses_t_squared_with_min_buy_gate(monkeypatch):
    monkeypatch.setattr(
        "freshquant.strategy.guardian_buy_grid._get_min_buy_amount",
        lambda *_args, **_kwargs: 10000,
    )
    service = _build_grid_service(
        FakeDatabase(
            {
                "guardian_buy_grid_configs": FakeCollection(_grid_config_docs()),
                "guardian_buy_grid_states": FakeCollection(
                    [{"code": "000001", "buy_active": [False, False, False]}]
                ),
            }
        )
    )
    service._load_position_capacity = lambda _code: (200000.0, 800000.0)
    decision = service.build_holding_add_decision("000001", 9.5)
    assert decision["stage"] == "BUY-1_TO_BUY-2"
    assert decision["remaining_amount"] == 150000
    assert decision["capacity_ratio"] == 0.25
    assert decision["quantity"] == 3900


def test_holding_add_above_tp_zone_does_not_buy(monkeypatch):
    monkeypatch.setattr(
        "freshquant.strategy.guardian_buy_grid._get_min_buy_amount",
        lambda *_args, **_kwargs: 10000,
    )
    service = _build_grid_service(
        FakeDatabase(
            {
                "guardian_buy_grid_configs": FakeCollection(_grid_config_docs()),
                "guardian_buy_grid_states": FakeCollection(
                    [{"code": "000001", "buy_active": [False, False, False]}]
                ),
            }
        )
    )
    service._load_takeprofit_prices = lambda _code: [11.0, 12.0, 13.0]
    decision = service.build_holding_add_decision("000001", 14.0)
    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "above_takeprofit_zone"


# ---------------------------------------------------------------------------
# TPSL：base 过滤 + 基数 = Σ base remaining
# ---------------------------------------------------------------------------


class _FakeTpslRepo:
    def __init__(self):
        self.profiles = {}
        self.states = {}
        self.events = []

    def find_takeprofit_profile(self, symbol):
        return self.profiles.get(symbol)

    def upsert_takeprofit_profile(self, document):
        self.profiles[document["symbol"]] = document
        return document

    def find_takeprofit_state(self, symbol):
        return self.states.get(symbol)

    def upsert_takeprofit_state(self, document):
        self.states[document["symbol"]] = document
        return document

    def insert_exit_trigger_event(self, document):
        self.events.append(document)
        return document


class _FakeLadder:
    def __init__(self, repo):
        self.repo = repo

    def _ensure(self, symbol):
        if self.repo.find_takeprofit_state(symbol) is None:
            self.repo.upsert_takeprofit_state(
                {"symbol": symbol, "armed_levels": {}, "version": 0}
            )

    def on_takeprofit_trigger(
        self,
        *,
        code,
        level,
        event_key,
        last_triggered_batch_id=None,
        trigger_price=None,
    ):
        self._ensure(code)
        state = self.repo.find_takeprofit_state(code)
        state["armed_levels"] = dict(state["armed_levels"])
        state["armed_levels"][int(level)] = False
        self.repo.upsert_takeprofit_state(state)
        return True

    def rearm_all_levels(self, code, *, updated_by="system", reason="manual"):
        self._ensure(code)
        state = self.repo.find_takeprofit_state(code)
        state["armed_levels"] = dict(state["armed_levels"])
        profile = self.repo.find_takeprofit_profile(code) or {}
        for tier in profile.get("tiers") or []:
            state["armed_levels"][int(tier["level"])] = bool(
                tier.get("manual_enabled", True)
            )
        self.repo.upsert_takeprofit_state(state)
        return True

    def set_armed_levels(self, *, code, values):
        self._ensure(code)
        state = self.repo.find_takeprofit_state(code)
        state["armed_levels"] = dict(state["armed_levels"])
        for raw_level, raw_enabled in dict(values or {}).items():
            state["armed_levels"][int(raw_level)] = bool(raw_enabled)
        self.repo.upsert_takeprofit_state(state)
        return state


class _FakeOrderRepoForTpsl:
    def __init__(self, open_entry_slices=None):
        self._open_entry_slices = list(open_entry_slices or [])
        self._open_slices = []

    def list_open_entry_slices(self, *, symbol=None, entry_ids=None):
        rows = list(self._open_entry_slices)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if entry_ids:
            allowed = set(entry_ids)
            rows = [item for item in rows if item.get("entry_id") in allowed]
        return rows

    def list_open_slices(self, symbol=None):
        return list(self._open_slices)


def test_evaluate_takeprofit_only_sells_base_and_uses_base_total(monkeypatch):
    from freshquant.tpsl.service import TpslService
    from freshquant.tpsl.takeprofit_service import TakeprofitService

    repo = _FakeTpslRepo()
    tp_service = TakeprofitService(
        repository=repo,
        ladder_state=_FakeLadder(repo),
    )
    tp_service.save_profile(
        "000001",
        tiers=[
            {"level": 1, "price": 10.0, "manual_enabled": True},
        ],
        updated_by="api",
    )
    tp_service.rearm_all_levels("000001", updated_by="test")

    class _PositionReader:
        def get_position_volumes(self, symbol):
            return {"volume": 900, "can_use_volume": 900}

    order_repo = _FakeOrderRepoForTpsl(
        open_entry_slices=[
            {
                "entry_id": "entry_base",
                "entry_slice_id": "slice_base",
                "symbol": "000001",
                "position_type": "base",
                "guardian_price": 9.0,
                "remaining_quantity": 600,
                "slice_seq": 1,
                "sort_key": 9.0,
            },
            {
                "entry_id": "entry_t",
                "entry_slice_id": "slice_t",
                "symbol": "000001",
                "position_type": "t",
                "guardian_price": 9.2,
                "remaining_quantity": 300,
                "slice_seq": 1,
                "sort_key": 9.2,
            },
        ]
    )
    service = TpslService(
        takeprofit_service=tp_service,
        order_repository=order_repo,
        position_reader=_PositionReader(),
    )
    batch = service.evaluate_takeprofit(symbol="000001", ask1=10.5)

    # L1 = 1/3 × base 总量 600 = 200（不能按券商全仓 900 卖出 300）
    assert batch["status"] == "ready"
    assert batch["quantity"] == 200
    assert batch["entry_quantities"] == {"entry_base": 200}


def test_evaluate_takeprofit_skips_when_only_t_slices():
    from freshquant.tpsl.service import TpslService
    from freshquant.tpsl.takeprofit_service import TakeprofitService

    repo = _FakeTpslRepo()
    tp_service = TakeprofitService(
        repository=repo,
        ladder_state=_FakeLadder(repo),
    )
    tp_service.save_profile(
        "000001",
        tiers=[{"level": 1, "price": 10.0, "manual_enabled": True}],
        updated_by="api",
    )
    tp_service.rearm_all_levels("000001", updated_by="test")

    class _PositionReader:
        def get_position_volumes(self, symbol):
            return {"volume": 300, "can_use_volume": 300}

    order_repo = _FakeOrderRepoForTpsl(
        open_entry_slices=[
            {
                "entry_id": "entry_t",
                "entry_slice_id": "slice_t",
                "symbol": "000001",
                "position_type": "t",
                "guardian_price": 9.2,
                "remaining_quantity": 300,
                "slice_seq": 1,
                "sort_key": 9.2,
            }
        ]
    )
    service = TpslService(
        takeprofit_service=tp_service,
        order_repository=order_repo,
        position_reader=_PositionReader(),
    )
    assert service.evaluate_takeprofit(symbol="000001", ask1=10.5) is None


def test_on_new_buy_trade_t_does_not_trigger_ladder():
    from freshquant.tpsl.service import TpslService
    from freshquant.tpsl.takeprofit_service import TakeprofitService

    repo = _FakeTpslRepo()
    tp_service = TakeprofitService(
        repository=repo,
        ladder_state=_FakeLadder(repo),
    )
    tp_service.save_profile(
        "000001",
        tiers=[
            {"level": 1, "price": 10.0, "manual_enabled": True},
            {"level": 2, "price": 11.0, "manual_enabled": True},
        ],
        updated_by="api",
    )
    service = TpslService(takeprofit_service=tp_service)
    assert (
        service.on_new_buy_trade(
            symbol="000001",
            buy_price=9.0,
            position_type="t",
        )
        is None
    )
    state = tp_service.get_state("000001")
    assert state["armed_levels"] == {1: False, 2: False}
    # base 买入 → 全开止盈档
    service.on_new_buy_trade(symbol="000001", buy_price=9.0, position_type="base")
    assert tp_service.get_state("000001")["armed_levels"] == {1: True, 2: True}


# ---------------------------------------------------------------------------
# Consumer 双集合
# ---------------------------------------------------------------------------


def test_tpsl_consumer_dual_universe_buy_line_before_takeprofit(monkeypatch):
    from freshquant.tpsl.consumer import TpslTickConsumer

    calls = []

    class _FakeService:
        def evaluate_base_buyline(self, **kwargs):
            calls.append(("buy_line", kwargs.get("symbol")))
            return {"status": "ready", "symbol": kwargs.get("symbol"), "quantity": 100}

        def submit_base_buy_batch(self, decision, trace_id=None):
            calls.append(("submit_buy_line", decision.get("symbol")))
            return {"request_id": "req_bl_1"}

        def evaluate_takeprofit(self, **kwargs):
            calls.append(("takeprofit", kwargs.get("symbol")))
            return None

        def evaluate_stoploss(self, **kwargs):
            calls.append(("stoploss", kwargs.get("symbol")))
            return None

    consumer = TpslTickConsumer(
        service=_FakeService(),
        universe_loader=lambda: ["sh000001"],
        buy_line_universe_loader=lambda: ["sh000001"],
        refresh_interval_s=0,
    )
    consumer.refresh_universe(force=True)
    consumer.handle_tick(
        {
            "event": "TICK_QUOTE",
            "code": "sh000001",
            "ask1": 10.5,
            "bid1": 10.4,
            "last_price": 10.45,
            "tick_time": 1744000000,
        }
    )
    # 买入线评估在 TP 之前，且命中后提交、不再评估 TP
    assert calls[0] == ("buy_line", "000001")
    assert calls[1] == ("submit_buy_line", "000001")
    assert "takeprofit" not in [item[0] for item in calls]


def test_tpsl_consumer_buy_line_only_symbol_still_evaluates():
    from freshquant.tpsl.consumer import TpslTickConsumer

    calls = []

    class _FakeService:
        def evaluate_base_buyline(self, **kwargs):
            calls.append(("buy_line", kwargs.get("symbol")))
            return {"status": "skipped", "symbol": kwargs.get("symbol")}

        def evaluate_takeprofit(self, **kwargs):
            calls.append(("takeprofit", kwargs.get("symbol")))
            return None

        def evaluate_stoploss(self, **kwargs):
            calls.append(("stoploss", kwargs.get("symbol")))
            return None

    consumer = TpslTickConsumer(
        service=_FakeService(),
        universe_loader=lambda: [],
        buy_line_universe_loader=lambda: ["sz000002"],
        refresh_interval_s=0,
    )
    consumer.refresh_universe(force=True)
    consumer.handle_tick(
        {
            "event": "TICK_QUOTE",
            "code": "sz000002",
            "ask1": 10.5,
            "bid1": 10.4,
            "last_price": 10.45,
            "tick_time": 1744000000,
        }
    )
    assert calls[0][0] == "buy_line"


# ---------------------------------------------------------------------------
# 无 source plan 三段分桶分摊
# ---------------------------------------------------------------------------


def test_allocate_sell_no_plan_three_bucket_order(monkeypatch):
    from freshquant.order_management.guardian.allocation_policy import (
        allocate_sell_to_entry_slices_with_budget,
    )

    monkeypatch.setattr(
        "freshquant.order_management.guardian.allocation_policy._resolve_sell_percent",
        lambda _fact: 1.0,
    )
    entries = [
        {"entry_id": "e_base", "remaining_quantity": 100, "status": "OPEN"},
        {"entry_id": "e_t_profit", "remaining_quantity": 100, "status": "OPEN"},
        {"entry_id": "e_t_loss", "remaining_quantity": 100, "status": "OPEN"},
    ]
    open_slices = [
        {
            "entry_slice_id": "s_base",
            "entry_id": "e_base",
            "guardian_price": 9.0,
            "remaining_quantity": 100,
            "trade_time": 1,
            "slice_seq": 1,
            "position_type": "base",
        },
        {
            "entry_slice_id": "s_t_profit",
            "entry_id": "e_t_profit",
            "guardian_price": 8.0,
            "remaining_quantity": 100,
            "trade_time": 1,
            "slice_seq": 1,
            "position_type": "t",
        },
        {
            "entry_slice_id": "s_t_loss",
            "entry_id": "e_t_loss",
            "guardian_price": 11.0,
            "remaining_quantity": 100,
            "trade_time": 1,
            "slice_seq": 1,
            "position_type": "t",
        },
    ]
    # 卖单 avg 9.5：T 盈利低成本（guardian_price 8.0 ≤ 9.5/1.01）优先，
    # 再底仓（9.0），最后 T 非盈利（11.0）。
    allocations = allocate_sell_to_entry_slices_with_budget(
        entries=entries,
        open_slices=open_slices,
        sell_trade_fact={
            "trade_fact_id": "sell_1",
            "symbol": "000001",
            "quantity": 250,
            "price": 9.5,
        },
    )
    order = [item["entry_slice_id"] for item in allocations]
    assert order == ["s_t_profit", "s_base", "s_t_loss"]
    assert [item["position_type"] for item in allocations] == [
        "t",
        "base",
        "t",
    ]
