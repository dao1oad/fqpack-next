from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "sunflower"
    / "QUANTAXIS"
    / "QUANTAXIS"
    / "QAFetch"
    / "QATdx.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("save_tdx_under_test", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stock_fetch_failover_moves_to_next_repo_host(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "get_mainmarket_ip", lambda *_: ("10.0.0.1", 7709))
    monkeypatch.setattr(
        module,
        "stock_ip_list",
        [
            {"ip": "10.0.0.1", "port": 7709},
            {"ip": "10.0.0.2", "port": 7709},
        ],
    )
    calls = []

    def fetcher(*args, ip=None, port=None, **kwargs):
        calls.append((ip, port))
        if ip == "10.0.0.1":
            return None
        return pd.DataFrame([{"code": "000001"}])

    result = module._fetch_stock_bars_with_failover(fetcher, "000001")

    assert len(result) == 1
    assert calls == [("10.0.0.1", 7709), ("10.0.0.2", 7709)]


def test_stock_fetch_failover_accepts_filtered_empty_result(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "get_mainmarket_ip", lambda *_: ("10.0.0.1", 7709))
    monkeypatch.setattr(
        module,
        "stock_ip_list",
        [{"ip": "10.0.0.1", "port": 7709}, {"ip": "10.0.0.2", "port": 7709}],
    )
    calls = []

    def fetcher(*args, ip=None, port=None, **kwargs):
        calls.append((ip, port))
        return pd.DataFrame()

    result = module._fetch_stock_bars_with_failover(fetcher, "000001")

    assert result.empty
    assert calls == [("10.0.0.1", 7709)]


def test_stock_fetch_failover_raises_when_all_hosts_fail(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "get_mainmarket_ip", lambda *_: ("10.0.0.1", 7709))
    monkeypatch.setattr(
        module,
        "stock_ip_list",
        [{"ip": "10.0.0.1", "port": 7709}, {"ip": "10.0.0.2", "port": 7709}],
    )

    with pytest.raises(RuntimeError, match="all TDX stock hosts failed"):
        module._fetch_stock_bars_with_failover(
            lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timeout")),
            "000001",
        )
