from __future__ import annotations

from freshquant.market_data.xtdata import strategy_consumer as consumer_module
from freshquant.market_data.xtdata.strategy_consumer import StrategyConsumer


class FakeRedis:
    def __init__(self):
        self.lock_keys = []

    def set(self, key, value, ex=None, nx=False):
        self.lock_keys.append(key)
        return True


class FakeRealtimeCollection:
    def __init__(self):
        self.inserted = []

    def insert_many(self, docs, ordered=False):
        self.inserted.extend(list(docs))


class FakeEmptyCollection:
    def find(self, query=None, projection=None):
        return []


class FakeDB:
    def __init__(self, realtime_collection):
        self._collections = {
            "realtime_screen_multi_period": realtime_collection,
            # 合并后 consumer 会先排除当前持仓，测试环境持仓为空
            "xt_positions": FakeEmptyCollection(),
        }

    def __getitem__(self, name):
        return self._collections[name]


def _make_consumer(monkeypatch, append_impl, *, query_inst=None):
    fake_redis = FakeRedis()
    realtime_collection = FakeRealtimeCollection()
    monkeypatch.setattr(consumer_module, "redis_db", fake_redis)
    monkeypatch.setattr(consumer_module, "DBfreshquant", FakeDB(realtime_collection))
    monkeypatch.setattr(
        "freshquant.instrument.general.query_instrument_info",
        query_inst or (lambda code: None),
    )
    monkeypatch.setattr(
        "freshquant.message.dingtalk.send_private_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "freshquant.clx_daily_selection.tdx_export.append_tdx_group_members",
        append_impl,
    )
    consumer = object.__new__(StrategyConsumer)
    return consumer, fake_redis, realtime_collection


def _meta_and_result(code="sh600000", period="15min"):
    meta = {
        "code": code,
        "period": period,
        "bar_time": 1780000000,
        "model_ids": [10000, 10001],
    }
    fc_res = {
        "signals": [
            {"signal": 1, "model": 10000, "close": 10.5, "stop_loss": 9.8},
            {"signal": 0, "model": 10001, "close": 10.5, "stop_loss": 9.8},
            {"signal": 1, "model": 10001, "close": 10.6, "stop_loss": 9.9},
        ]
    }
    return meta, fc_res


def test_process_clx_signals_appends_docs_codes_to_tdx_group(monkeypatch):
    calls = []

    def append_impl(
        symbols, *, tdx_home=None, block_key="CLX_15_30", display_name="clx_15_30"
    ):
        calls.append((symbols, block_key))
        return {
            "group_name": display_name,
            "file_name": f"{block_key}.blk",
            "appended_count": 1,
            "written_count": 1,
        }

    consumer, fake_redis, realtime_collection = _make_consumer(monkeypatch, append_impl)
    meta, fc_res = _meta_and_result()

    consumer._process_clx_signals(meta, fc_res)

    assert calls == [(["sh600000"], "CLX_15_30")]
    assert len(realtime_collection.inserted) == 2
    assert {doc["code"] for doc in realtime_collection.inserted} == {"sh600000"}
    assert len(fake_redis.lock_keys) == 2


def test_process_clx_signals_tdx_append_failure_is_best_effort(monkeypatch):
    def append_impl(
        symbols, *, tdx_home=None, block_key="CLX_15_30", display_name="clx_15_30"
    ):
        raise RuntimeError("TDX group write denied")

    consumer, fake_redis, realtime_collection = _make_consumer(monkeypatch, append_impl)
    meta, fc_res = _meta_and_result()

    # 必须不抛出异常，且信号仍正常入库
    consumer._process_clx_signals(meta, fc_res)

    assert len(realtime_collection.inserted) == 2


def test_process_clx_signals_skips_tdx_append_without_models(monkeypatch):
    calls = []

    def append_impl(
        symbols, *, tdx_home=None, block_key="CLX_15_30", display_name="clx_15_30"
    ):
        calls.append(symbols)
        return {"appended_count": 0, "written_count": 0}

    consumer, _fake_redis, realtime_collection = _make_consumer(
        monkeypatch, append_impl
    )
    meta = {
        "code": "sh600000",
        "period": "15min",
        "bar_time": 1780000000,
        "model_ids": [],
    }

    consumer._process_clx_signals(meta, {"signals": []})

    assert calls == []
    assert realtime_collection.inserted == []
