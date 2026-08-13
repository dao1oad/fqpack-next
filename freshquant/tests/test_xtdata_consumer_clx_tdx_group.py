from __future__ import annotations

from datetime import datetime

import pytz  # type: ignore[import-untyped]

from freshquant.market_data.xtdata import strategy_consumer as consumer_module
from freshquant.market_data.xtdata.strategy_consumer import StrategyConsumer

SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")


class FakeRedis:
    def __init__(self):
        self.lock_keys = []

    def set(self, key, value, ex=None, nx=False):
        self.lock_keys.append(key)
        return True


class FakeRealtimeCollection:
    def __init__(self, existing=None):
        self.inserted = []
        self.existing = list(existing or [])
        self.last_query = None
        self.last_projection = None
        self.index_created = None

    def insert_many(self, docs, ordered=False):
        self.inserted.extend(list(docs))
        self.existing.extend(list(docs))

    def find(self, query=None, projection=None):
        self.last_query = query
        self.last_projection = projection
        lower = (query or {}).get("datetime", {}).get("$gte")
        if lower is None:
            return list(self.existing)
        return [
            dict(doc)
            for doc in self.existing
            if doc.get("datetime") is not None and doc["datetime"] >= lower
        ]

    def create_index(self, spec):
        self.index_created = spec


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


def _make_consumer(
    monkeypatch,
    rewrite_impl,
    ensure_impl=None,
    *,
    query_inst=None,
    existing=None,
):
    consumer_module._CLX_DATETIME_INDEX_ENSURED = False
    fake_redis = FakeRedis()
    realtime_collection = FakeRealtimeCollection(existing)
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
        "freshquant.clx_daily_selection.tdx_export._write_tdx_group_members_locked",
        rewrite_impl,
    )
    monkeypatch.setattr(
        "freshquant.clx_daily_selection.tdx_export.ensure_tdx_group_registered",
        ensure_impl or (lambda *args, **kwargs: True),
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
            {"signal": 1, "model": 10000, "close": 10.5},
            {"signal": 0, "model": 10001, "close": 10.5},
            {"signal": 1, "model": 10001, "close": 10.6},
        ]
    }
    return meta, fc_res


def _today_records():
    return [
        {
            "code": "sz000001",
            "datetime": SHANGHAI_TZ.localize(datetime(2026, 8, 10, 11, 0)),
        },
        {
            "code": "sh600000",
            "datetime": SHANGHAI_TZ.localize(datetime(2026, 8, 10, 10, 0)),
        },
        {
            "code": "sh600000",
            "datetime": SHANGHAI_TZ.localize(datetime(2026, 8, 10, 11, 0)),
        },
        # 昨日记录：不得参与当天分组
        {
            "code": "sh600001",
            "datetime": SHANGHAI_TZ.localize(datetime(2026, 8, 9, 15, 0)),
        },
    ]


def test_process_clx_signals_rewrites_today_group_from_db_in_last_time_order(
    monkeypatch,
):
    calls = []
    lock_held_flags = []

    def rewrite_impl(
        codes, *, tdx_home=None, block_key="CLX_15_30", display_name="clx_15_30"
    ):
        from freshquant.clx_daily_selection import tdx_export

        lock_held_flags.append(tdx_export._TDX_BLK_WRITE_LOCK.locked())
        calls.append((codes, block_key))
        return {"written_count": len(codes), "skipped_count": 0}

    consumer, fake_redis, realtime_collection = _make_consumer(
        monkeypatch, rewrite_impl, existing=_today_records()
    )
    meta, fc_res = _meta_and_result()
    meta["bar_time"] = int(
        SHANGHAI_TZ.localize(datetime(2026, 8, 10, 11, 0)).timestamp()
    )

    consumer._process_clx_signals(meta, fc_res)

    # 覆盖写在全模块锁内调用（避免旧快照覆盖新快照）
    assert lock_held_flags == [True]
    # 聚合结果：sh600000 取最后一次信号 11:00；昨日标的不参与；按 (datetime, code) 升序
    assert calls == [(["sh600000", "sz000001"], "CLX_15_30")]
    # 查询边界：只查当天记录
    assert realtime_collection.last_query == {
        "datetime": {"$gte": SHANGHAI_TZ.localize(datetime(2026, 8, 10, 0, 0))}
    }
    assert realtime_collection.last_projection == {"code": 1, "datetime": 1}
    # 信号仍正常入库
    assert len(realtime_collection.inserted) == 2


def test_process_clx_signals_creates_datetime_index_once(monkeypatch):
    def rewrite_impl(codes, **kwargs):
        return {"written_count": len(codes), "skipped_count": 0}

    consumer, _fake_redis, realtime_collection = _make_consumer(
        monkeypatch, rewrite_impl, existing=_today_records()
    )
    meta, fc_res = _meta_and_result()
    meta["bar_time"] = int(
        SHANGHAI_TZ.localize(datetime(2026, 8, 10, 11, 0)).timestamp()
    )

    consumer._process_clx_signals(meta, fc_res)
    consumer._process_clx_signals(meta, fc_res)

    assert realtime_collection.index_created == "datetime"


def test_process_clx_signals_insert_failure_skips_tdx_rewrite(monkeypatch):
    calls = []

    def rewrite_impl(codes, **kwargs):
        calls.append(codes)
        return {"written_count": len(codes), "skipped_count": 0}

    consumer, fake_redis, realtime_collection = _make_consumer(
        monkeypatch, rewrite_impl
    )

    def fail_insert(docs, ordered=False):
        raise RuntimeError("insert denied")

    monkeypatch.setattr(realtime_collection, "insert_many", fail_insert)
    meta, fc_res = _meta_and_result()

    # 入库失败：不抛异常、不写通达信分组（以数据库为真值）
    consumer._process_clx_signals(meta, fc_res)

    assert calls == []
    assert realtime_collection.inserted == []


def test_process_clx_signals_tdx_rewrite_failure_is_best_effort(monkeypatch):
    def rewrite_impl(codes, **kwargs):
        raise RuntimeError("TDX group rewrite denied")

    consumer, fake_redis, realtime_collection = _make_consumer(
        monkeypatch, rewrite_impl, existing=_today_records()
    )
    meta, fc_res = _meta_and_result()
    meta["bar_time"] = int(
        SHANGHAI_TZ.localize(datetime(2026, 8, 10, 11, 0)).timestamp()
    )

    # 必须不抛出异常，且信号仍正常入库
    consumer._process_clx_signals(meta, fc_res)

    assert len(realtime_collection.inserted) == 2


def test_process_clx_signals_skips_tdx_rewrite_without_models(monkeypatch):
    calls = []

    def rewrite_impl(codes, **kwargs):
        calls.append(codes)
        return {"written_count": len(codes), "skipped_count": 0}

    consumer, _fake_redis, realtime_collection = _make_consumer(
        monkeypatch, rewrite_impl
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


def test_process_clx_signals_skips_tdx_rewrite_for_current_holding(monkeypatch):
    def rewrite_impl(codes, **kwargs):
        raise AssertionError("holding code must not reach tdx rewrite")

    class FakeHoldingCollection:
        def find(self, query=None, projection=None):
            return [{"stock_code": "sh600000"}]

    consumer, _fake_redis, realtime_collection = _make_consumer(
        monkeypatch, rewrite_impl
    )
    consumer_module.DBfreshquant._collections["xt_positions"] = FakeHoldingCollection()
    meta, fc_res = _meta_and_result()

    consumer._process_clx_signals(meta, fc_res)

    assert realtime_collection.inserted == []
