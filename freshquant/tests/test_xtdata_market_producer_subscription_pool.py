from types import SimpleNamespace

from freshquant.market_data.xtdata import market_producer


def test_load_subscription_codes_only_uses_monitor_pool(monkeypatch):
    monkeypatch.setattr(
        market_producer,
        "load_monitor_codes",
        lambda *, mode, max_symbols: ["SH600000", "sz000001", "", "sh600000"],
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
        "mode": "guardian_and_clx_15_30",
        "max_symbols": 88,
    }


def test_run_producer_with_xtdata_retry_retries_retryable_connect_errors():
    start_calls = []
    sleep_calls = []
    attempts = iter(
        [
            Exception("无法连接xtquant服务，请检查QMT是否开启"),
            "ok",
        ]
    )

    def fake_start():
        start_calls.append("called")
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    def fake_sleep(seconds):
        sleep_calls.append(seconds)

    result = market_producer.run_producer_with_xtdata_retry(
        start_fn=fake_start,
        sleep_fn=fake_sleep,
    )

    assert result == "ok"
    assert start_calls == ["called", "called"]
    assert sleep_calls == [5.0]
