from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import threading
from pathlib import Path


def test_runtime_network_context_temporarily_clears_proxy_variables(monkeypatch):
    spec = importlib.util.find_spec("freshquant.runtime.network")
    assert spec is not None

    network = importlib.import_module("freshquant.runtime.network")

    original_values = {
        "ALL_PROXY": "socks5://127.0.0.1:10808",
        "all_proxy": "socks5://127.0.0.1:10808",
        "HTTP_PROXY": "http://127.0.0.1:10809",
        "http_proxy": "http://127.0.0.1:10809",
        "HTTPS_PROXY": "http://127.0.0.1:10809",
        "https_proxy": "http://127.0.0.1:10809",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }
    for key, value in original_values.items():
        monkeypatch.setenv(key, value)

    seen_during_call = {}

    with network.without_proxy_env():
        for key in original_values:
            seen_during_call[key] = os.environ.get(key)

    assert seen_during_call == {key: None for key in original_values}
    for key, value in original_values.items():
        assert os.environ.get(key) == value


def test_clear_proxy_env_for_current_process_removes_proxy_variables(monkeypatch):
    spec = importlib.util.find_spec("freshquant.runtime.network")
    assert spec is not None

    network = importlib.import_module("freshquant.runtime.network")

    original_values = {
        "ALL_PROXY": "socks5://127.0.0.1:10808",
        "all_proxy": "socks5://127.0.0.1:10808",
        "HTTP_PROXY": "http://127.0.0.1:10809",
        "http_proxy": "http://127.0.0.1:10809",
        "HTTPS_PROXY": "http://127.0.0.1:10809",
        "https_proxy": "http://127.0.0.1:10809",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }
    for key, value in original_values.items():
        monkeypatch.setenv(key, value)

    network.clear_proxy_env_for_current_process()

    for key in original_values:
        assert os.environ.get(key) in (None, "")


def test_runtime_network_context_restores_values_after_nested_calls(monkeypatch):
    network = importlib.import_module("freshquant.runtime.network")

    original_values = {
        "ALL_PROXY": "socks5://127.0.0.1:10808",
        "HTTP_PROXY": "http://127.0.0.1:10809",
        "HTTPS_PROXY": "http://127.0.0.1:10809",
        "NO_PROXY": "127.0.0.1,localhost",
    }
    for key, value in original_values.items():
        monkeypatch.setenv(key, value)

    with network.without_proxy_env():
        assert all(os.environ.get(key) is None for key in original_values)
        with network.without_proxy_env():
            assert all(os.environ.get(key) is None for key in original_values)
        assert all(os.environ.get(key) is None for key in original_values)

    for key, value in original_values.items():
        assert os.environ.get(key) == value


def test_clear_proxy_waits_for_active_without_proxy_context(monkeypatch):
    network = importlib.import_module("freshquant.runtime.network")

    original_values = {
        "ALL_PROXY": "socks5://127.0.0.1:10808",
        "HTTP_PROXY": "http://127.0.0.1:10809",
        "HTTPS_PROXY": "http://127.0.0.1:10809",
    }
    for key, value in original_values.items():
        monkeypatch.setenv(key, value)

    entered = threading.Event()
    release = threading.Event()
    cleared = threading.Event()

    def hold_without_proxy_env() -> None:
        with network.without_proxy_env():
            entered.set()
            release.wait(timeout=5)

    def clear_proxy_env() -> None:
        assert entered.wait(timeout=5)
        network.clear_proxy_env_for_current_process()
        cleared.set()

    context_thread = threading.Thread(target=hold_without_proxy_env)
    clear_thread = threading.Thread(target=clear_proxy_env)

    context_thread.start()
    clear_thread.start()

    assert entered.wait(timeout=5)
    assert not cleared.wait(timeout=0.2)

    release.set()

    context_thread.join(timeout=5)
    clear_thread.join(timeout=5)

    assert not context_thread.is_alive()
    assert not clear_thread.is_alive()
    assert cleared.is_set()

    for key in original_values:
        assert os.environ.get(key) in (None, "")


def test_importing_freshquant_clears_proxy_variables(monkeypatch):
    original_values = {
        "ALL_PROXY": "socks5://127.0.0.1:10808",
        "HTTP_PROXY": "http://127.0.0.1:10809",
        "HTTPS_PROXY": "http://127.0.0.1:10809",
    }
    for key, value in original_values.items():
        monkeypatch.setenv(key, value)

    import freshquant

    importlib.reload(freshquant)

    for key in original_values:
        assert os.environ.get(key) in (None, "")


def test_importing_fqxtrade_clears_proxy_variables(monkeypatch):
    package_root = Path("morningglory/fqxtrade").resolve()
    sys.path.insert(0, str(package_root))
    try:
        original_values = {
            "ALL_PROXY": "socks5://127.0.0.1:10808",
            "HTTP_PROXY": "http://127.0.0.1:10809",
            "HTTPS_PROXY": "http://127.0.0.1:10809",
        }
        for key, value in original_values.items():
            monkeypatch.setenv(key, value)

        import fqxtrade

        importlib.reload(fqxtrade)

        for key in original_values:
            assert os.environ.get(key) in (None, "")
    finally:
        sys.path.remove(str(package_root))
