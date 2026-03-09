from freshquant.market_data.xtdata import market_producer


def test_load_subscription_codes_only_uses_monitor_pool(monkeypatch):
    monkeypatch.setattr(
        market_producer,
        "load_monitor_codes",
        lambda *, mode, max_symbols: ["SH600000", "sz000001", ""],
    )

    codes = market_producer._load_subscription_codes(mode="guardian_1m", max_symbols=50)

    assert codes == ["sh600000", "sz000001"]
