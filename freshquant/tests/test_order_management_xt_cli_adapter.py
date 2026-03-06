import sys
import types

from click.testing import CliRunner


def _install_xt_cli_import_stubs(monkeypatch):
    broker_module = types.ModuleType("fqxtrade.xtquant.broker")
    broker_module.main = lambda: None
    xtquant_package = types.ModuleType("fqxtrade.xtquant")
    xtquant_package.broker = broker_module
    monkeypatch.setitem(sys.modules, "fqxtrade.xtquant.broker", broker_module)
    monkeypatch.setitem(sys.modules, "fqxtrade.xtquant", xtquant_package)

    fqxtrade_module = types.ModuleType("fqxtrade")
    fqxtrade_module.ORDER_QUEUE = "freshquant_order_queue"
    fqxtrade_module.xtquant = xtquant_package
    monkeypatch.setitem(sys.modules, "fqxtrade", fqxtrade_module)

    redis_module = types.ModuleType("fqxtrade.database.redis")
    redis_module.redis_db = types.SimpleNamespace(lpush=lambda *args, **kwargs: 1)
    monkeypatch.setitem(sys.modules, "fqxtrade.database.redis", redis_module)


def test_xtquant_buy_command_delegates_to_order_submit_service(monkeypatch):
    _install_xt_cli_import_stubs(monkeypatch)
    from morningglory.fqxtrade.fqxtrade.xtquant.cli_commands import xtquant

    captured = {}

    class FakeService:
        def submit_order(self, payload):
            captured.update(payload)
            return {"request_id": "req_xt_1", "internal_order_id": "ord_xt_1"}

    monkeypatch.setattr(
        "morningglory.fqxtrade.fqxtrade.xtquant.cli_commands._get_order_submit_service",
        lambda: FakeService(),
    )

    runner = CliRunner()
    result = runner.invoke(
        xtquant, ["buy", "600000.SH", "--price", "10.0", "--quantity", "300"]
    )

    assert result.exit_code == 0
    assert captured["action"] == "buy"
    assert captured["symbol"] == "600000"
    assert "ord_xt_1" in result.output
