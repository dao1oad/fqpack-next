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
_SAVE_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "sunflower"
    / "QUANTAXIS"
    / "QUANTAXIS"
    / "QASU"
    / "save_tdx.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("save_tdx_under_test", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_save_module():
    spec = importlib.util.spec_from_file_location(
        "qasu_save_tdx_under_test", _SAVE_MODULE_PATH
    )
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


def test_stock_day_empty_source_is_a_noop():
    module = _load_save_module()

    class Collection:
        def insert_many(self, documents):
            raise AssertionError(f"unexpected empty insert: {documents}")

    assert module._insert_stock_day_rows(Collection(), pd.DataFrame()) == 0
    assert module._insert_stock_day_rows(Collection(), None) == 0


def test_full_stock_day_sync_accepts_unlisted_empty_source(monkeypatch):
    module = _load_save_module()

    class Collection:
        def create_index(self, keys):
            return keys

        def find_one(self, query, sort=None):
            return None

        def insert_many(self, documents):
            raise AssertionError(f"unexpected empty insert: {documents}")

    class Client:
        stock_day = Collection()

    monkeypatch.setattr(
        module,
        "QA_fetch_get_stock_list",
        lambda: pd.DataFrame([{"code": "001232"}]),
    )
    monkeypatch.setattr(module, "QA_fetch_get_stock_day", lambda *args: pd.DataFrame())
    monkeypatch.setattr(module, "now_time", lambda: "2026-07-20 15:00:00")

    module.QA_SU_save_stock_day(client=Client())


def test_stock_day_nonempty_source_is_inserted(monkeypatch):
    module = _load_save_module()
    inserted = []

    class Collection:
        def insert_many(self, documents):
            inserted.extend(documents)

    monkeypatch.setattr(
        module,
        "QA_util_to_json_from_pandas",
        lambda data: [{"code": str(data.iloc[0]["code"])}],
    )

    assert (
        module._insert_stock_day_rows(Collection(), pd.DataFrame([{"code": "000001"}]))
        == 1
    )
    assert inserted == [{"code": "000001"}]
