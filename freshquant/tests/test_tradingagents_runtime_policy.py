from pathlib import Path

import tomllib


def test_tradingagents_backend_targets_python312() -> None:
    text = Path("third_party/tradingagents-cn/Dockerfile.backend").read_text(
        encoding="utf-8"
    )
    assert "FROM python:3.12" in text
    assert "uv sync --frozen" in text


def test_tradingagents_pyproject_requires_python312() -> None:
    data = tomllib.loads(
        Path("third_party/tradingagents-cn/pyproject.toml").read_text(encoding="utf-8")
    )
    assert data["project"]["requires-python"] == ">=3.12,<3.13"


def test_tradingagents_python_version_file_is_312() -> None:
    version = Path("third_party/tradingagents-cn/.python-version").read_text(
        encoding="utf-8"
    ).strip()
    assert version == "3.12"


def test_tradingagents_compose_uses_project_venv() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")
    assert "/app/.venv/bin/python" in text


def test_tradingagents_compose_provides_dev_jwt_secret_default() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")
    assert 'JWT_SECRET: ${JWT_SECRET:-change-me-in-production}' in text


def test_tradingagents_qianfan_extra_uses_resolvable_release() -> None:
    data = tomllib.loads(
        Path("third_party/tradingagents-cn/pyproject.toml").read_text(encoding="utf-8")
    )
    assert data["project"]["optional-dependencies"]["qianfan"] == [
        "qianfan>=0.4.12.3,<0.5"
    ]
