from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOST_ENVS_CONF = Path(os.environ.get("FQ_HOST_ENVS_CONF", "D:/fqpack/config/envs.conf"))


def test_repo_no_longer_ships_runtime_symphony_service_tree() -> None:
    assert not (REPO_ROOT / "runtime" / "symphony").exists()


def test_host_runtime_envs_clear_all_proxy_variants() -> None:
    if not HOST_ENVS_CONF.exists():
        pytest.skip(f"host env file not available: {HOST_ENVS_CONF}")

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
