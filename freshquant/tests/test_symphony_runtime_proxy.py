from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SYMPHONY_START_SCRIPT = (
    REPO_ROOT / "runtime" / "symphony" / "scripts" / "start_freshquant_symphony.ps1"
)
HOST_ENVS_CONF = Path("D:/fqpack/config/envs.conf")


def test_start_freshquant_symphony_script_does_not_forward_proxy_env_vars() -> None:
    text = SYMPHONY_START_SCRIPT.read_text(encoding="utf-8")

    assert "'HTTP_PROXY'" not in text
    assert "'HTTPS_PROXY'" not in text
    assert "'ALL_PROXY'" not in text
    assert "'http_proxy'" not in text
    assert "'https_proxy'" not in text
    assert "'all_proxy'" not in text


def test_host_runtime_envs_clear_all_proxy_variants() -> None:
    text = HOST_ENVS_CONF.read_text(encoding="utf-8")

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
        assert key in text
