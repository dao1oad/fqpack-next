import importlib.util
import sys
import types
from pathlib import Path


def test_guardian_monitor_cli_only_exposes_event_mode():
    content = Path("freshquant/signal/astock/job/monitor_stock_zh_a_min.py").read_text(
        encoding="utf-8"
    )

    assert 'click.Choice(["event"])' in content
    assert '"poll"' not in content


def test_guardian_monitor_uses_trading_mode_capability_instead_of_strict_mode_match():
    content = Path("freshquant/signal/astock/job/monitor_stock_zh_a_min.py").read_text(
        encoding="utf-8"
    )

    assert "xtdata_trading_mode" in content
    assert "lines_for_modes" in content
    assert 'expected guardian_1m. Exiting.' not in content


def test_guardian_monitor_idle_standby_instead_of_exit():
    content = Path("freshquant/signal/astock/job/monitor_stock_zh_a_min.py").read_text(
        encoding="utf-8"
    )

    assert "Entering idle standby" in content
    assert "trading lines disabled. Exiting." not in content


def test_guardian_monitor_disables_buy_zs_huila_signal():
    content = Path("freshquant/signal/astock/job/monitor_stock_zh_a_min.py").read_text(
        encoding="utf-8"
    )

    assert 'DISABLED_GUARDIAN_SIGNAL_TYPES = {"buy_zs_huila"}' in content
    assert "if s.signal_type in DISABLED_GUARDIAN_SIGNAL_TYPES:" in content


def test_guardian_monitor_saves_raw_signal_type_for_review_traceability():
    """事件链保存信号时把原始 signal_type 一并落库。

    复盘读模型依赖该字段显示真实信号类型（否则做T加仓订单会被一律标成
    buy_zs_huila，与运行观测口径不一致）。
    """

    content = Path("freshquant/signal/astock/job/monitor_stock_zh_a_min.py").read_text(
        encoding="utf-8"
    )

    assert "signal_type=s.signal_type" in content


def test_query_must_pool_codes_cache_expires_after_one_minute(monkeypatch):
    records = [
        {
            "code": "000001",
            "instrument_type": "stock_cn",
            "disabled": False,
        }
    ]
    find_calls = []

    class FakeMemoizer:
        def __init__(self):
            self.now = 0

        def memoize(self, expiration):
            def decorator(func):
                cache = {}

                def wrapper(*args, **kwargs):
                    key = repr((args, sorted(kwargs.items())))
                    item = cache.get(key)
                    if item is None or self.now >= item[0]:
                        value = func(*args, **kwargs)
                        cache[key] = (self.now + expiration, value)
                        return value
                    return item[1]

                wrapper._test_expiration = expiration
                return wrapper

            return decorator

    class FakeCollection:
        def find(self, query):
            find_calls.append(query)
            return [dict(item) for item in records if not item.get("disabled")]

    class FakeDb:
        def __getitem__(self, _name):
            return FakeCollection()

    memoizer = FakeMemoizer()
    cache_stub = types.ModuleType("freshquant.database.cache")
    cache_stub.in_memory_cache = memoizer
    db_stub = types.ModuleType("freshquant.db")
    db_stub.DBfreshquant = FakeDb()
    code_stub = types.ModuleType("freshquant.util.code")
    code_stub.fq_util_code_append_market_code = lambda code: code
    code_stub.fq_util_code_append_market_code_suffix = lambda code: code
    monkeypatch.setitem(sys.modules, "freshquant.database.cache", cache_stub)
    monkeypatch.setitem(sys.modules, "freshquant.db", db_stub)
    monkeypatch.setitem(sys.modules, "freshquant.util.code", code_stub)

    module_path = Path("freshquant/pool/general.py").resolve()
    spec = importlib.util.spec_from_file_location("test_pool_general_ttl", module_path)
    assert spec is not None and spec.loader is not None
    pool_general = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pool_general)

    assert pool_general.queryMustPoolCodes() == ["000001"]
    records[0]["disabled"] = True
    memoizer.now = 59
    assert pool_general.queryMustPoolCodes() == ["000001"]
    memoizer.now = 60
    assert pool_general.queryMustPoolCodes() == []

    assert len(find_calls) == 2
    assert pool_general.queryMustPoolCodes._test_expiration == 60
