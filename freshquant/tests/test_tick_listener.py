"""tpsl tick_listener 断连自愈与毒消息保护测试（P2-B）。"""

from __future__ import annotations

import redis

import freshquant.tpsl.tick_listener as tick_listener_module
from freshquant.tpsl.tick_listener import TickQuoteListener


class _FakeRedis:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0
        self.disconnected = 0

    def blpop(self, keys, timeout=5):
        self.calls += 1
        if not self.results:
            raise SystemExit("done")
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def connection_pool(self):
        return self

    def disconnect(self):
        self.disconnected += 1


def _run_with_stop(listener):
    try:
        listener.run_forever()
    except SystemExit:
        pass


def test_run_forever_recovers_after_redis_connection_error(monkeypatch):
    processed = []
    fake = _FakeRedis(
        [
            redis.exceptions.ConnectionError("down"),
            (
                "TICK_QUOTE:0",
                '{"code":"sz000001","bid1":10.0,"ask1":10.1,'
                '"last_price":10.05,"tick_time":1700000000000,'
                '"created_at":1700000000.0}',
            ),
        ]
    )
    listener = TickQuoteListener(
        lambda ev: processed.append(ev.code),
        redis_client=fake,
        timeout=1,
    )
    monkeypatch.setattr(listener, "_rebuild_redis_client", lambda: None)

    _run_with_stop(listener)

    assert processed == ["sz000001"]
    # 第 1 次 blpop 抛连接错误，第 2 次返回消息，第 3 次抛 SystemExit 结束
    assert fake.calls == 3


def test_run_forever_skips_poison_message_and_continues():
    processed = []
    fake = _FakeRedis(
        [
            ("TICK_QUOTE:0", b"{not-json"),
            (
                "TICK_QUOTE:0",
                '{"code":"sz000002","bid1":9.0,"ask1":9.1,'
                '"last_price":9.05,"tick_time":1700000000000,'
                '"created_at":1700000000.0}',
            ),
        ]
    )
    listener = TickQuoteListener(
        lambda ev: processed.append(ev.code),
        redis_client=fake,
        timeout=1,
    )

    _run_with_stop(listener)

    assert processed == ["sz000002"]
    # 毒消息 + 正常消息 + SystemExit 结束
    assert fake.calls == 3


def test_run_forever_rebuilds_client_when_none(monkeypatch):
    processed = []
    fake = _FakeRedis(
        [
            (
                "TICK_QUOTE:0",
                '{"code":"sz000003","bid1":8.0,"ask1":8.1,'
                '"last_price":8.05,"tick_time":1700000000000,'
                '"created_at":1700000000.0}',
            ),
        ]
    )
    rebuild_calls = []
    # 构造器用 redis_client or redis_db 兜底：把模块级 redis_db 置 None，
    # 才能覆盖"client 不可用 → 重建"路径（避免连上真实 Redis 无限轮询）。
    monkeypatch.setattr(tick_listener_module, "redis_db", None)
    listener = TickQuoteListener(
        lambda ev: processed.append(ev.code),
        redis_client=None,
        timeout=1,
    )

    def _rebuild():
        rebuild_calls.append(1)
        listener.redis_client = fake

    monkeypatch.setattr(listener, "_rebuild_redis_client", _rebuild)

    _run_with_stop(listener)

    assert processed == ["sz000003"]
    assert len(rebuild_calls) == 1
