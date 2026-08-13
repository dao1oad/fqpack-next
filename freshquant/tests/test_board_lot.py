# -*- coding: utf-8 -*-
"""步骤 7 契约测试：board lot helper（根⑤/S3）+ D1/S4 must_pool 活跃成员。"""
from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from freshquant.trading.board_lot import (
    floor_to_board_lot,
    is_board_lot_quantity,
    quantity_for_amount,
    resolve_board_lot,
)

# ---------------------------------------------------------------- board lot helper


def test_resolve_board_lot_default_100():
    assert resolve_board_lot() == 100
    assert resolve_board_lot("000001") == 100
    assert resolve_board_lot("sz000001") == 100


def test_resolve_board_lot_star_200_by_code_prefix():
    assert resolve_board_lot("688001") == 200
    assert resolve_board_lot("sh688001") == 200
    assert resolve_board_lot("689009") == 200
    assert resolve_board_lot("600000") == 100
    assert resolve_board_lot("300001") == 100


def test_resolve_board_lot_star_200_by_board_or_security_type():
    assert resolve_board_lot("000001", board="科创板") == 200
    assert resolve_board_lot("000001", board="STAR") == 200
    assert resolve_board_lot("000001", security_type="科创") == 200
    assert resolve_board_lot("000001", exchange="SH", board="主板") == 100
    assert resolve_board_lot("000001", board="非科创") == 100


def test_is_board_lot_quantity_normal_and_star():
    assert is_board_lot_quantity(100) is True
    assert is_board_lot_quantity(300) is True
    assert is_board_lot_quantity(150) is False
    assert is_board_lot_quantity(0) is False
    assert is_board_lot_quantity(-100) is False
    assert is_board_lot_quantity(200, code="688001") is True
    assert is_board_lot_quantity(300, code="688001") is True
    assert is_board_lot_quantity(201, code="688001") is True
    assert is_board_lot_quantity(100, code="688001") is False
    assert is_board_lot_quantity(150, code="000001") is False


def test_floor_to_board_lot_normal_and_star():
    assert floor_to_board_lot(150) == 100
    assert floor_to_board_lot(250) == 200
    assert floor_to_board_lot(50) == 0
    assert floor_to_board_lot(250, code="688001") == 250
    assert floor_to_board_lot(201, code="688001") == 201
    assert floor_to_board_lot(150, code="688001") == 0
    assert floor_to_board_lot(None) == 0


def test_quantity_for_amount_normal_and_star():
    assert quantity_for_amount(10000, 10.0) == 1000
    assert quantity_for_amount(100500, 10.0) == 10000
    assert quantity_for_amount(15000, 10.0, code="688001") == 1500
    assert quantity_for_amount(40000, 10.0, code="688001") == 4000
    assert quantity_for_amount(1500, 10.0, code="688001") == 0
    assert quantity_for_amount(-1, 10.0) == 0
    assert quantity_for_amount(100, 0.0) == 0


# ---------------------------------------------------------------- D1/S4 must_pool 活跃成员


def _load_pool_general_with(monkeypatch, records):
    class FakeCollection:
        def __init__(self):
            self.queries = []

        def find(self, query):
            self.queries.append(query)
            instrument_types = query.get("instrument_type", {}).get("$in", [])
            return [
                item
                for item in records
                if item.get("instrument_type") in instrument_types
            ]

    class FakeDb:
        def __getitem__(self, _name):
            return FakeCollection()

    cache_stub = types.ModuleType("freshquant.database.cache")
    cache_stub.in_memory_cache = types.SimpleNamespace(
        memoize=lambda *a, **k: (lambda f: f)
    )
    db_stub = types.ModuleType("freshquant.db")
    db_stub.DBfreshquant = FakeDb()
    code_stub = types.ModuleType("freshquant.util.code")
    code_stub.fq_util_code_append_market_code = lambda code: f"SH{code}"
    code_stub.fq_util_code_append_market_code_suffix = lambda code: f"{code}.SH"
    monkeypatch.setitem(sys.modules, "freshquant.database.cache", cache_stub)
    monkeypatch.setitem(sys.modules, "freshquant.db", db_stub)
    monkeypatch.setitem(sys.modules, "freshquant.util.code", code_stub)

    module_path = Path("freshquant/pool/general.py").resolve()
    spec = importlib.util.spec_from_file_location("test_pool_general_d1", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_query_must_pool_codes_excludes_expired_and_disabled(monkeypatch):
    now = datetime.now()
    records = [
        {"code": "600001", "instrument_type": "stock_cn", "forever": True},
        {"code": "600002", "instrument_type": "stock_cn"},
        {
            "code": "600003",
            "instrument_type": "stock_cn",
            "memberships": [{"expire_at": now + timedelta(days=3)}],
        },
        {
            "code": "600004",
            "instrument_type": "stock_cn",
            "memberships": [{"expire_at": now - timedelta(days=1)}],
        },
        {
            "code": "600005",
            "instrument_type": "stock_cn",
            "expire_at": now - timedelta(days=1),
        },
        {
            "code": "600006",
            "instrument_type": "stock_cn",
            "expire_at": now + timedelta(days=1),
        },
        {"code": "600007", "instrument_type": "stock_cn", "disabled": True},
    ]
    module = _load_pool_general_with(monkeypatch, records)

    result = module.queryMustPoolCodes()

    assert sorted(result) == ["600001", "600002", "600003", "600006"]


def test_query_must_pool_codes_prefix_suffix_share_active_filter(monkeypatch):
    now = datetime.now()
    records = [
        {"code": "600001", "instrument_type": "stock_cn", "forever": True},
        {
            "code": "600002",
            "instrument_type": "stock_cn",
            "memberships": [{"expire_at": now - timedelta(days=1)}],
        },
        {"code": "600003", "instrument_type": "stock_cn", "disabled": True},
    ]
    module = _load_pool_general_with(monkeypatch, records)

    assert module.queryMustPoolCodesWithMarketCodePrefix() == ["SH600001"]
    assert module.queryMustPoolCodesWithMarketCodeSuffix() == ["600001.SH"]


def test_is_active_member_handles_tz_aware_and_naive_expire(monkeypatch):
    """Mongo tz_aware 客户端读出 aware datetime：与 tz-aware now 比较不抛错。"""

    from datetime import timedelta, timezone

    module = _load_pool_general_with(monkeypatch, [])
    _is_active_member = module._is_active_member

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    assert (
        _is_active_member(
            {"expire_at": now - timedelta(days=1), "memberships": []}, now=now
        )
        is False
    )
    assert (
        _is_active_member(
            {"expire_at": now + timedelta(days=1), "memberships": []}, now=now
        )
        is True
    )
    assert (
        _is_active_member(
            {
                "memberships": [
                    {"expire_at": now - timedelta(days=1)},
                    {"expire_at": now + timedelta(days=2)},
                ]
            },
            now=now,
        )
        is True
    )
    assert (
        _is_active_member(
            {"memberships": [{"expire_at": now - timedelta(days=1)}]}, now=now
        )
        is False
    )
    # naive datetime 输入归一化后同样成立
    naive_now = datetime.now()
    assert (
        _is_active_member(
            {"memberships": [{"expire_at": naive_now + timedelta(days=1)}]},
            now=naive_now,
        )
        is True
    )
