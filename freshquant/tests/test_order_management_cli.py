from click.testing import CliRunner

from freshquant.command.om_order import om_order_command_group


def test_om_order_submit_command_calls_submit_service(monkeypatch):
    captured = {}

    class FakeService:
        def submit_order(self, payload):
            captured.update(payload)
            return {"request_id": "req_cli_1", "internal_order_id": "ord_cli_1"}

    monkeypatch.setattr(
        "freshquant.command.om_order._get_order_submit_service",
        lambda: FakeService(),
    )

    runner = CliRunner()
    result = runner.invoke(
        om_order_command_group,
        [
            "submit",
            "--action",
            "buy",
            "--symbol",
            "600000.SH",
            "--price",
            "9.98",
            "--quantity",
            "300",
            "--source",
            "cli",
        ],
    )

    assert result.exit_code == 0
    assert captured["symbol"] == "600000"
    assert captured["action"] == "buy"
    assert "ord_cli_1" in result.output


def test_om_order_cancel_command_calls_cancel_service(monkeypatch):
    captured = {}

    class FakeService:
        def cancel_order(self, payload):
            captured.update(payload)
            return {"request_id": "req_cli_cancel_1", "internal_order_id": payload["internal_order_id"]}

    monkeypatch.setattr(
        "freshquant.command.om_order._get_order_submit_service",
        lambda: FakeService(),
    )

    runner = CliRunner()
    result = runner.invoke(
        om_order_command_group,
        [
            "cancel",
            "--internal-order-id",
            "ord_cancel_cli_1",
            "--source",
            "cli",
        ],
    )

    assert result.exit_code == 0
    assert captured["internal_order_id"] == "ord_cancel_cli_1"
    assert "req_cli_cancel_1" in result.output
