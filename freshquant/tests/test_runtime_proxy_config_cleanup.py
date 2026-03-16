from __future__ import annotations

import importlib
import sys
from pathlib import Path


def test_freshquant_config_no_longer_exposes_proxy_defaults() -> None:
    import freshquant.config as config_module

    config_module = importlib.reload(config_module)

    assert not hasattr(config_module.Config, "PROXIES")
    assert not hasattr(config_module.Config, "PROXY_HOST")
    assert not hasattr(config_module.Config, "PROXY_PORT")


def test_fqxtrade_config_no_longer_exposes_proxy_defaults() -> None:
    package_root = Path("morningglory/fqxtrade").resolve()
    sys.path.insert(0, str(package_root))
    try:
        import fqxtrade.config as config_module

        config_module = importlib.reload(config_module)

        assert not hasattr(config_module.Config, "PROXIES")
        assert not hasattr(config_module.Config, "PROXY_HOST")
        assert not hasattr(config_module.Config, "PROXY_PORT")
    finally:
        sys.path.remove(str(package_root))


def test_freshquant_yaml_no_longer_contains_proxy_section() -> None:
    config_text = Path("freshquant/freshquant.yaml").read_text(encoding="utf-8")

    assert "\nproxy:\n" not in config_text


def test_example_env_file_no_longer_contains_proxy_keys() -> None:
    env_text = Path("deployment/examples/envs.fqnext.example").read_text(
        encoding="utf-8"
    )

    for key in (
        "ALL_PROXY=",
        "all_proxy=",
        "HTTP_PROXY=",
        "http_proxy=",
        "HTTPS_PROXY=",
        "https_proxy=",
        "NO_PROXY=",
        "no_proxy=",
    ):
        assert key not in env_text


def test_tradingagents_runtime_no_longer_defines_proxy_settings() -> None:
    config_text = Path("third_party/tradingagents-cn/app/core/config.py").read_text(
        encoding="utf-8"
    )

    assert "HTTP_PROXY: str = Field" not in config_text
    assert "HTTPS_PROXY: str = Field" not in config_text
    assert "NO_PROXY: str = Field" not in config_text
    assert "clear_proxy_env_for_current_process()" in config_text


def test_tradingagents_example_env_file_no_longer_contains_proxy_keys() -> None:
    env_text = Path("third_party/tradingagents-cn/.env.example").read_text(
        encoding="utf-8"
    )

    for key in (
        "ALL_PROXY=",
        "all_proxy=",
        "HTTP_PROXY=",
        "http_proxy=",
        "HTTPS_PROXY=",
        "https_proxy=",
        "NO_PROXY=",
        "no_proxy=",
    ):
        assert key not in env_text
