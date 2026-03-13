import os

import pandas as pd
import pytest
from requests.exceptions import SSLError  # type: ignore[import-untyped]

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


def test_fetch_trade_dates_retries_transient_ssl_error(monkeypatch):
    attempts = []

    def fake_fetch():
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise SSLError("temporary ssl failure")
        return pd.DataFrame({"trade_date": pd.to_datetime(["2026-03-10"])})

    result = dt._fetch_trade_dates_from_source(fake_fetch)

    assert list(result["trade_date"].dt.strftime("%Y-%m-%d")) == ["2026-03-10"]
    assert attempts == [1, 2]


def test_call_without_proxy_env_does_not_swallow_request_exception():
    with pytest.raises(SSLError, match="temporary ssl failure"):
        dt._call_without_proxy_env(
            lambda: (_ for _ in ()).throw(SSLError("temporary ssl failure"))
        )
