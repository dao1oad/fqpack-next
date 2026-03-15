from freshquant.market_data.xtdata import market_producer
from types import SimpleNamespace


def test_load_subscription_codes_only_uses_monitor_pool(monkeypatch):
    monkeypatch.setattr(
        market_producer,
        "load_monitor_codes",
        lambda *, mode, max_symbols: ["SH600000", "sz000001", ""],
    )

    codes = market_producer._load_subscription_codes(mode="guardian_1m", max_symbols=50)

    assert codes == ["sh600000", "sz000001"]


def test_resolve_producer_runtime_config_uses_system_settings_and_bootstrap():
    config = market_producer.resolve_producer_runtime_config(
        settings_provider=SimpleNamespace(
            monitor=SimpleNamespace(
                xtdata_mode="clx_15_30",
                xtdata_max_symbols=88,
            )
        ),
        bootstrap_provider=SimpleNamespace(xtdata=SimpleNamespace(port=58611)),
    )

    assert config == {
        "port": 58611,
        "mode": "clx_15_30",
        "max_symbols": 88,
    }
