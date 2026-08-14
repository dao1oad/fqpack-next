# -*- coding: utf-8 -*-
"""总收口 PR4：读侧 stock_code 消费统一 6 位归一（normalize_to_base_code）。"""

import importlib
import sys

import pytest


def _reimport(request, monkeypatch, dotted):
    parent_name, _, child_name = dotted.rpartition(".")
    parent = sys.modules.get(parent_name)
    original = sys.modules.get(dotted)
    for name in list(sys.modules):
        if name == dotted or name.startswith(dotted + "."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module(dotted)
    if parent is not None and original is not None:
        # importlib 会把父包属性指向新实例；结束时恢复原始对象，
        # 避免并行/后续测试拿到不同实例导致异常类不匹配。
        request.addfinalizer(lambda: setattr(parent, child_name, original))
    return module


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("000001", "000001"),
        ("000001.SZ", "000001"),
        ("sz000001", "000001"),
        ("600000.SH", "600000"),
        ("sh600000", "600000"),
        ("", ""),
    ],
)
def test_ledger_invariants_normalize_code_six_digit(
    request, monkeypatch, raw, expected
):
    ledger_invariants = _reimport(
        request, monkeypatch, "freshquant.order_management.ledger_invariants"
    )
    assert ledger_invariants._normalize_code(raw) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"symbol": "000001"}, "000001"),
        ({"stock_code": "000001.SZ"}, "000001"),
        ({"stock_code": "sz000001"}, "000001"),
        ({"stock_code": "600000.SH"}, "600000"),
        ({"symbol": ""}, ""),
    ],
)
def test_rebuild_normalize_symbol_six_digit(request, monkeypatch, payload, expected):
    rebuild_service = _reimport(
        request, monkeypatch, "freshquant.order_management.rebuild.service"
    )
    assert rebuild_service._normalize_symbol(payload) == expected


def test_reconcile_positions_by_symbol_normalizes_suffixed_stock_code(
    request, monkeypatch
):
    reconcile_service = _reimport(
        request, monkeypatch, "freshquant.order_management.reconcile.service"
    )
    positions_by_symbol = reconcile_service._build_positions_by_symbol(
        [
            {"stock_code": "000001.SZ", "volume": 100},
            {"symbol": "600000", "volume": 200},
        ]
    )

    assert set(positions_by_symbol) == {"000001", "600000"}


def test_targeted_ledger_document_symbol_six_digit(request, monkeypatch):
    targeted_ledger = _reimport(
        request, monkeypatch, "freshquant.order_management.repair.targeted_ledger"
    )
    assert targeted_ledger._document_symbol({"symbol": "600917.SH"}) == "600917"
    assert targeted_ledger._document_symbol({"stock_code": "sz688772"}) == "688772"
