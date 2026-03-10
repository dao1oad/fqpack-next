import os

import pandas as pd

from freshquant.trading import dt


def test_call_without_proxy_env_hides_proxy_variables_during_call(monkeypatch):
    original_values = {
        "ALL_PROXY": "socks5://127.0.0.1:10808",
        "all_proxy": "socks5://127.0.0.1:10808",
        "HTTP_PROXY": "http://127.0.0.1:10809",
        "HTTPS_PROXY": "http://127.0.0.1:10809",
    }
    for key, value in original_values.items():
        monkeypatch.setenv(key, value)

    seen_during_call = {}

    def fake_fetch():
        for key in original_values:
            seen_during_call[key] = os.environ.get(key)
        return pd.DataFrame({"trade_date": pd.to_datetime(["2026-03-10"])})

    result = dt._call_without_proxy_env(fake_fetch)

    assert list(result["trade_date"].dt.strftime("%Y-%m-%d")) == ["2026-03-10"]
    assert seen_during_call == {key: None for key in original_values}
    for key, value in original_values.items():
        assert os.environ.get(key) == value
