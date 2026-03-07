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
