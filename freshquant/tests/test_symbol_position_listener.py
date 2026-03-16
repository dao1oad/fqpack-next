# -*- coding: utf-8 -*-

import json

from freshquant.position_management.symbol_position_listener import (
    SingleSymbolPositionListener,
)


class FakeRedis:
    def __init__(self, payload=None):
        self.payload = payload

    def blpop(self, _keys, timeout=0):
        if self.payload is None:
            return None
        payload = self.payload
        self.payload = None
        return "QUEUE:BAR_CLOSE:0", json.dumps(payload)


class FakeService:
    def __init__(self):
        self.calls = []

    def refresh_from_bar_close(self, event):
        self.calls.append(event)
        return {"symbol": "600000", "market_value": 12600.0}


def test_listener_consumes_1min_bar_close_and_refreshes_snapshot():
    service = FakeService()
    listener = SingleSymbolPositionListener(
        service=service,
        redis_client=FakeRedis(
            {
                "event": "BAR_CLOSE",
                "code": "sh600000",
                "period": "1m",
                "data": {"close": 10.5},
                "created_at": 1710000000.0,
            }
        ),
        timeout=1,
    )

    result = listener.listen_once()

    assert result["symbol"] == "600000"
    assert len(service.calls) == 1
    assert service.calls[0].code == "sh600000"
    assert service.calls[0].period == "1min"


def test_listener_ignores_non_1min_bar_close():
    service = FakeService()
    listener = SingleSymbolPositionListener(
        service=service,
        redis_client=FakeRedis(
            {
                "event": "BAR_CLOSE",
                "code": "sh600000",
                "period": "5m",
                "data": {"close": 10.8},
                "created_at": 1710000000.0,
            }
        ),
        timeout=1,
    )

    result = listener.listen_once()

    assert result is None
    assert service.calls == []
