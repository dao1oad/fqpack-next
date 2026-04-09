from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "script" / "fqnext_supervisor_config.py"
EXPECTED_REPO_ROOT = Path(
    r"D:\fqpack\freshquant-2026.2.23"
)


def load_module():
    spec = importlib.util.spec_from_file_location(
        "fqnext_supervisor_config", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_supervisor_config_targets_canonical_repo_root() -> None:
    module = load_module()

    config_text = module.build_supervisor_config(EXPECTED_REPO_ROOT)

    expected_root = str(EXPECTED_REPO_ROOT).replace("\\", "/")
    assert f"directory={expected_root}" in config_text
    assert (
        "environment=PATH="
        f"{expected_root}/.venv;"
        f"{expected_root}/.venv/Scripts;"
        "C:/Windows/System32,"
        "PYTHONPATH="
        f"{expected_root};"
        f"{expected_root}/morningglory/fqxtrade;"
        f"{expected_root}/sunflower/QUANTAXIS"
    ) in config_text
    assert (
        f"command={expected_root}/.venv/Scripts/python.exe -m fqxtrade.xtquant.broker"
        in config_text
    )
    assert (
        f"command={expected_root}/.venv/Scripts/python.exe -m freshquant.xt_auto_repay.worker"
        in config_text
    )


def test_inspect_supervisor_config_rejects_main_runtime_and_site_packages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_module()
    config_path = tmp_path / "supervisord.fqnext.conf"
    config_path.write_text(
        module.build_supervisor_config(
            Path(r"D:\fqpack\freshquant-2026.2.23\.worktrees\main-runtime")
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "collect_import_sources",
        lambda *_args, **_kwargs: {
            "freshquant": {
                "path": (
                    "D:/fqpack/freshquant-2026.2.23/.venv/Lib/site-packages/"
                    "freshquant/__init__.py"
                ),
                "error": None,
            },
            "fqxtrade.xtquant.broker": {
                "path": (
                    "D:/fqpack/freshquant-2026.2.23/.venv/Lib/site-packages/"
                    "fqxtrade/xtquant/broker.py"
                ),
                "error": None,
            },
            "fqxtrade.xtquant.puppet": {
                "path": (
                    "D:/fqpack/freshquant-2026.2.23/.venv/Lib/site-packages/"
                    "fqxtrade/xtquant/puppet.py"
                ),
                "error": None,
            },
            "QUANTAXIS": {
                "path": (
                    "D:/fqpack/freshquant-2026.2.23/.venv/Lib/site-packages/"
                    "QUANTAXIS/__init__.py"
                ),
                "error": None,
            },
        },
    )

    result = module.inspect_supervisor_config(
        config_path=config_path,
        expected_repo_root=EXPECTED_REPO_ROOT,
    )

    assert result["ok"] is False
    assert any("main-runtime" in failure for failure in result["failures"])
    assert any("site-packages" in failure for failure in result["failures"])


def test_inspect_supervisor_config_accepts_canonical_repo_root_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_module()
    config_path = tmp_path / "supervisord.fqnext.conf"
    config_path.write_text(
        module.build_supervisor_config(EXPECTED_REPO_ROOT),
        encoding="utf-8",
    )

    expected_root = str(EXPECTED_REPO_ROOT).replace("\\", "/")
    monkeypatch.setattr(
        module,
        "collect_import_sources",
        lambda *_args, **_kwargs: {
            "freshquant": {
                "path": f"{expected_root}/freshquant/__init__.py",
                "error": None,
            },
            "fqxtrade.xtquant.broker": {
                "path": f"{expected_root}/morningglory/fqxtrade/fqxtrade/xtquant/broker.py",
                "error": None,
            },
            "fqxtrade.xtquant.puppet": {
                "path": f"{expected_root}/morningglory/fqxtrade/fqxtrade/xtquant/puppet.py",
                "error": None,
            },
            "QUANTAXIS": {
                "path": f"{expected_root}/sunflower/QUANTAXIS/QUANTAXIS/__init__.py",
                "error": None,
            },
        },
    )

    result = module.inspect_supervisor_config(
        config_path=config_path,
        expected_repo_root=EXPECTED_REPO_ROOT,
    )

    assert result["ok"] is True
    assert result["failures"] == []


def test_write_supervisor_config_preserves_mtime_when_content_unchanged(
    tmp_path: Path,
) -> None:
    module = load_module()
    config_path = tmp_path / "supervisord.fqnext.conf"
    config_path.write_text(
        module.build_supervisor_config(EXPECTED_REPO_ROOT),
        encoding="utf-8",
    )
    original_timestamp = 1_700_000_000
    os.utime(config_path, (original_timestamp, original_timestamp))
    original_mtime_ns = config_path.stat().st_mtime_ns

    result = module.write_supervisor_config(EXPECTED_REPO_ROOT, config_path)

    assert result["changed"] is False
    assert config_path.stat().st_mtime_ns == original_mtime_ns


def test_collect_import_sources_builds_valid_python_snippet(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_module()
    config_path = tmp_path / "supervisord.fqnext.conf"
    config_path.write_text(
        module.build_supervisor_config(EXPECTED_REPO_ROOT),
        encoding="utf-8",
    )

    def fake_run(command, **kwargs):
        assert str(kwargs["cwd"]).replace("\\", "/") == str(EXPECTED_REPO_ROOT).replace(
            "\\", "/"
        )
        compile(command[2], "<fqnext_supervisor_config>", "exec")
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"freshquant":{"path":"D:/fqpack/freshquant-2026.2.23/'
                'freshquant/__init__.py","error":null}}'
            ),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.collect_import_sources(config_path)

    assert result["freshquant"]["error"] is None


def test_collect_import_sources_loads_supervisor_env_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_module()
    env_file = tmp_path / "envs.conf"
    env_file.write_text(
        "FRESHQUANT_MONGODB__HOST=127.0.0.1\nFRESHQUANT_MONGODB__PORT=27027\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "supervisord.fqnext.conf"
    config_text = module.build_supervisor_config(EXPECTED_REPO_ROOT).replace(
        "envFiles=D:/fqpack/config/envs.conf",
        f"envFiles={env_file.as_posix()}",
    )
    config_path.write_text(config_text, encoding="utf-8")

    def fake_run(command, **kwargs):
        assert kwargs["env"]["FRESHQUANT_MONGODB__HOST"] == "127.0.0.1"
        assert kwargs["env"]["FRESHQUANT_MONGODB__PORT"] == "27027"
        return SimpleNamespace(
            returncode=0,
            stdout='{"freshquant":{"path":"x","error":null}}',
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.collect_import_sources(config_path)

    assert result["freshquant"]["error"] is None
