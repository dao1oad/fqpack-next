# -*- coding: utf-8 -*-
"""Issue #656：buy_line_armed 形状守卫 / CAS 归一 / fail-accurate coerce /
upsert_state 默认字段 回归测试。

分层：纯单测（coerce + 限频告警，无 DB）+ Mongo 集成（真实 Mongo，
CI mongo service / 本机 27027，不可达时跳过）。
"""

from __future__ import annotations

import sys
import types

sys.modules.setdefault("freshquant.message", types.ModuleType("freshquant.message"))

import pytest

from freshquant.strategy.guardian_buy_grid import GuardianBuyGridService
from freshquant.strategy.guardian_ladder import (
    DEFAULT_BUY_LINE_ARMED,
    GuardianLadderState,
    _coerce_buy_line_armed,
    _reset_armed_shape_alert_throttle,
)

sys.modules.pop("freshquant.message", None)

MONGO_URI = "mongodb://127.0.0.1:27027"


def _mongo_available() -> bool:
    try:
        import pymongo

        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=1200)
        client.admin.command("ping")
        client.close()
        return True
    except Exception:
        return False


MONGO_AVAILABLE = _mongo_available()


# ---------------------------------------------------------------------------
# 纯单测：coerce 归一 + 限频告警
# ---------------------------------------------------------------------------


def test_coerce_array_shape_passthrough():
    assert _coerce_buy_line_armed([True, False, True]) == [True, False, True]
    assert _coerce_buy_line_armed([False, False, False]) == [False, False, False]


def test_coerce_object_shape_normalizes_by_value():
    _reset_armed_shape_alert_throttle()
    # 512000 事故形状：{"0": false} → 保留现值，1/2 缺省 True
    assert _coerce_buy_line_armed({"0": False}) == [False, True, True]
    assert _coerce_buy_line_armed({"0": False, "1": False, "2": False}) == [
        False,
        False,
        False,
    ]
    assert _coerce_buy_line_armed({0: True, 1: True, 2: True}) == [True, True, True]


def test_coerce_missing_field_defaults_armed():
    _reset_armed_shape_alert_throttle()
    assert _coerce_buy_line_armed(None) == list(DEFAULT_BUY_LINE_ARMED)


def test_coerce_invalid_shape_defaults_armed():
    _reset_armed_shape_alert_throttle()
    assert _coerce_buy_line_armed("oops") == list(DEFAULT_BUY_LINE_ARMED)


def test_shape_alert_throttled_per_code_and_category(monkeypatch):
    _reset_armed_shape_alert_throttle()
    calls = []
    monkeypatch.setattr(
        "freshquant.strategy.guardian_ladder.logger.warning",
        lambda *args, **kwargs: calls.append(args),
    )
    _coerce_buy_line_armed(None, code="512000")  # 1
    _coerce_buy_line_armed(None, code="512000")  # 节流
    _coerce_buy_line_armed({"0": False}, code="512000")  # 2（不同类别）
    _coerce_buy_line_armed(None, code="600104")  # 3（不同 code）
    assert len(calls) == 3


# ---------------------------------------------------------------------------
# Mongo 集成：形状守卫 + CAS 归一 + 重开语义
# ---------------------------------------------------------------------------


@pytest.fixture()
def ladder_db():
    import pymongo

    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    db = client["fq_test_ladder_shape"]
    for name in (
        "guardian_buy_grid_states",
        "guardian_ladder_events",
        "om_takeprofit_states",
        "om_takeprofit_profiles",
    ):
        db[name].delete_many({})
    yield db
    for name in (
        "guardian_buy_grid_states",
        "guardian_ladder_events",
        "om_takeprofit_states",
        "om_takeprofit_profiles",
    ):
        db[name].delete_many({})
    client.close()


def _ladder(db) -> GuardianLadderState:
    return GuardianLadderState(
        buy_grid_database=db,
        tp_database=db,
        events_database=db,
    )


@pytest.mark.skipif(not MONGO_AVAILABLE, reason="需要本机 Mongo（CI mongo service）")
class TestLadderShapeGuardMongo:
    def test_close_on_missing_field_creates_array_and_closes(self, ladder_db):
        ladder_db["guardian_buy_grid_states"].insert_one(
            {"code": "512000", "buy_active": [True, True, True]}
        )
        ladder = _ladder(ladder_db)
        assert (
            ladder.on_buy_line_trigger(code="512000", level_index=0, event_key="evt-1")
            is True
        )
        doc = ladder_db["guardian_buy_grid_states"].find_one({"code": "512000"})
        assert doc["buy_line_armed"] == [False, True, True]

    def test_close_on_object_shape_preserves_closed_value(self, ladder_db):
        # 对象现值 0 已 False → CAS 归一保留现值，重试关闭不匹配
        # → ladder_conflict 语义（不重复提交），形状已修复为数组。
        ladder_db["guardian_buy_grid_states"].insert_one(
            {
                "code": "512000",
                "buy_active": [True, True, True],
                "buy_line_armed": {"0": False},
            }
        )
        ladder = _ladder(ladder_db)
        assert (
            ladder.on_buy_line_trigger(code="512000", level_index=0, event_key="evt-2")
            is False
        )
        doc = ladder_db["guardian_buy_grid_states"].find_one({"code": "512000"})
        assert doc["buy_line_armed"] == [False, True, True]

    def test_close_on_object_shape_armed_closes(self, ladder_db):
        ladder_db["guardian_buy_grid_states"].insert_one(
            {
                "code": "512000",
                "buy_active": [True, True, True],
                "buy_line_armed": {"0": True, "1": True, "2": True},
            }
        )
        ladder = _ladder(ladder_db)
        assert (
            ladder.on_buy_line_trigger(code="512000", level_index=0, event_key="evt-3")
            is True
        )
        doc = ladder_db["guardian_buy_grid_states"].find_one({"code": "512000"})
        assert doc["buy_line_armed"] == [False, True, True]

    def test_reopen_on_object_shape_must_set_true(self, ladder_db):
        # P0-①：对象 {"0": false} 重开 index 0 → 终态必须 armed=True
        ladder_db["guardian_buy_grid_states"].insert_one(
            {
                "code": "512000",
                "buy_active": [True, True, True],
                "buy_line_armed": {"0": False},
            }
        )
        ladder = _ladder(ladder_db)
        assert (
            ladder.on_buy_zero_fill_terminal(
                code="512000", level_index=0, event_key="evt-4"
            )
            is True
        )
        doc = ladder_db["guardian_buy_grid_states"].find_one({"code": "512000"})
        assert doc["buy_line_armed"] == [True, True, True]

    def test_reopen_on_missing_doc_creates_full_default(self, ladder_db):
        ladder = _ladder(ladder_db)
        assert (
            ladder.on_buy_zero_fill_terminal(
                code="600104", level_index=1, event_key="evt-5"
            )
            is True
        )
        doc = ladder_db["guardian_buy_grid_states"].find_one({"code": "600104"})
        assert doc["buy_line_armed"] == [True, True, True]
        assert doc["buy_active"] == [False, False, False]

    def test_close_after_close_returns_false(self, ladder_db):
        ladder_db["guardian_buy_grid_states"].insert_one(
            {
                "code": "512000",
                "buy_active": [True, True, True],
                "buy_line_armed": [False, True, True],
            }
        )
        ladder = _ladder(ladder_db)
        assert (
            ladder.on_buy_line_trigger(code="512000", level_index=0, event_key="evt-6")
            is False
        )
        doc = ladder_db["guardian_buy_grid_states"].find_one({"code": "512000"})
        assert doc["buy_line_armed"] == [False, True, True]

    def test_read_side_object_shape_returns_closed_view(self, ladder_db):
        # 读侧 fail-accurate：对象 {"0": false} 读为 [False, True, True]
        ladder_db["guardian_buy_grid_states"].insert_one(
            {
                "code": "512000",
                "buy_active": [True, True, True],
                "buy_line_armed": {"0": False},
            }
        )
        ladder = _ladder(ladder_db)
        assert ladder.get_state("512000")["buy_line_armed"] == [False, True, True]

    def test_rearm_all_buy_lines_fixes_object_shape(self, ladder_db):
        # 三形态×四操作：rearm（整数组写）对对象/缺失形状同样修复
        ladder_db["guardian_buy_grid_states"].insert_one(
            {
                "code": "512000",
                "buy_active": [True, True, True],
                "buy_line_armed": {"0": False},
            }
        )
        ladder = _ladder(ladder_db)
        assert ladder.rearm_all_buy_lines("512000") is True
        doc = ladder_db["guardian_buy_grid_states"].find_one({"code": "512000"})
        assert doc["buy_line_armed"] == [True, True, True]

    def test_set_buy_line_armed_on_missing_field_doc(self, ladder_db):
        # set（API 透传）在缺字段文档上写整数组，形状修复为数组
        ladder_db["guardian_buy_grid_states"].insert_one(
            {"code": "600271", "buy_active": [True, True, True]}
        )
        ladder = _ladder(ladder_db)
        result = ladder.set_buy_line_armed(code="600271", values=[False, True, True])
        assert result["buy_line_armed"] == [False, True, True]
        doc = ladder_db["guardian_buy_grid_states"].find_one({"code": "600271"})
        assert doc["buy_line_armed"] == [False, True, True]

    def test_cas_normalize_concurrent_only_one_wins(self, ladder_db):
        # P1-①：两"进程"（两个 ladder 实例）同时归一缺失字段文档，
        # 条件更新保证单写者，最终形状为数组且语义一致。
        import threading

        ladder_db["guardian_buy_grid_states"].insert_one(
            {"code": "512000", "buy_active": [True, True, True]}
        )
        first = _ladder(ladder_db)
        second = _ladder(ladder_db)
        barrier = threading.Barrier(2)
        results = []

        def _worker(instance):
            barrier.wait(timeout=5)
            results.append(instance._normalize_buy_line_armed_shape("512000"))

        threads = [
            threading.Thread(target=_worker, args=(first,)),
            threading.Thread(target=_worker, args=(second,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert results == [True, True]
        doc = ladder_db["guardian_buy_grid_states"].find_one({"code": "512000"})
        assert doc["buy_line_armed"] == [True, True, True]


@pytest.mark.skipif(not MONGO_AVAILABLE, reason="需要本机 Mongo（CI mongo service）")
class TestUpsertStateDefaultDocumentMongo:
    def test_upsert_state_creates_full_default_document(self, ladder_db):
        service = GuardianBuyGridService(database=ladder_db)
        # 模拟 disable_grid 路径：仅传 buy_active，创建文档必须带 buy_line_armed
        service.upsert_state(
            "512000",
            buy_active=[False, False, False],
            updated_by="xt_account_sync",
            audit=False,
        )
        doc = ladder_db["guardian_buy_grid_states"].find_one({"code": "512000"})
        assert doc["buy_line_armed"] == [True, True, True]
        assert doc["buy_active"] == [False, False, False]

    def test_upsert_state_no_conflicting_operators_on_existing_doc(self, ladder_db):
        # P0-②：已有文档时 $setOnInsert 不生效且不与 $set 冲突
        ladder_db["guardian_buy_grid_states"].insert_one(
            {"code": "512000", "buy_line_armed": [False, True, True]}
        )
        service = GuardianBuyGridService(database=ladder_db)
        service.upsert_state(
            "512000",
            buy_active=[True, True, True],
            updated_by="order_management",
            audit=False,
        )
        doc = ladder_db["guardian_buy_grid_states"].find_one({"code": "512000"})
        assert doc["buy_line_armed"] == [False, True, True]
        assert doc["buy_active"] == [True, True, True]
