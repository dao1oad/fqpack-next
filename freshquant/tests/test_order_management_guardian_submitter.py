from freshquant.order_management.submit.guardian import submit_guardian_order


def test_submit_guardian_order_uses_strategy_source_and_guardian_strategy(monkeypatch):
    captured = {}

    class FakeService:
        def submit_order(self, payload):
            captured.update(payload)
            return {
                "request_id": "req_guardian_1",
                "internal_order_id": "ord_guardian_1",
            }

    monkeypatch.setattr(
        "freshquant.order_management.submit.guardian._get_order_submit_service",
        lambda: FakeService(),
    )
    monkeypatch.setattr(
        "freshquant.order_management.submit.guardian._resolve_guardian_strategy_name",
        lambda: "strategy::Guardian",
    )

    result = submit_guardian_order("buy", "sz000001", 10.12, 300)

    assert result["internal_order_id"] == "ord_guardian_1"
    assert captured["action"] == "buy"
    assert captured["symbol"] == "000001"
    assert captured["source"] == "strategy"
    assert captured["strategy_name"] == "strategy::Guardian"


def test_submit_guardian_order_passes_profitability_hint(monkeypatch):
    captured = {}

    class FakeService:
        def submit_order(self, payload):
            captured.update(payload)
            return {
                "request_id": "req_guardian_2",
                "internal_order_id": "ord_guardian_2",
            }

    monkeypatch.setattr(
        "freshquant.order_management.submit.guardian._get_order_submit_service",
        lambda: FakeService(),
    )
    monkeypatch.setattr(
        "freshquant.order_management.submit.guardian._resolve_guardian_strategy_name",
        lambda: "strategy::Guardian",
    )

    result = submit_guardian_order(
        "sell",
        "sz000001",
        10.12,
        300,
        is_profitable=True,
    )

    assert result["internal_order_id"] == "ord_guardian_2"
    assert captured["position_management_is_profitable"] is True


def test_submit_guardian_order_carries_strategy_context_and_marks_buy_grid_accepted(
    monkeypatch,
):
    captured = {}
    mark_calls = []

    class FakeService:
        def submit_order(self, payload):
            captured.update(payload)
            return {
                "request_id": "req_guardian_3",
                "internal_order_id": "ord_guardian_3",
            }

    class FakeGuardianBuyGridService:
        def mark_buy_order_accepted(self, code, **kwargs):
            mark_calls.append((code, kwargs))
            return {"code": code, "buy_active": [False, False, True]}

    strategy_context = {
        "guardian_buy_grid": {
            "grid_level": "BUY-2",
            "hit_levels": ["BUY-1", "BUY-2"],
            "source_price": 9.81,
            "signal_time": "2026-04-04T10:15:30+08:00",
        }
    }

    monkeypatch.setattr(
        "freshquant.order_management.submit.guardian._get_order_submit_service",
        lambda: FakeService(),
    )
    monkeypatch.setattr(
        "freshquant.order_management.submit.guardian._get_guardian_buy_grid_service",
        lambda: FakeGuardianBuyGridService(),
    )
    monkeypatch.setattr(
        "freshquant.order_management.submit.guardian._resolve_guardian_strategy_name",
        lambda: "strategy::Guardian",
    )

    result = submit_guardian_order(
        "buy",
        "sz000001",
        10.12,
        300,
        strategy_context=strategy_context,
    )

    assert result["internal_order_id"] == "ord_guardian_3"
    assert captured["strategy_context"] == strategy_context
    assert mark_calls == [
        (
            "000001",
            {
                "hit_levels": ["BUY-1", "BUY-2"],
                "grid_level": "BUY-2",
                "source_price": 9.81,
                "signal_time": "2026-04-04T10:15:30+08:00",
            },
        )
    ]
