from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_deploy_workflow_uses_single_production_entrypoint() -> None:
    text = Path(".github/workflows/deploy-production.yml").read_text(encoding="utf-8")

    assert "script/ci/run_production_deploy.ps1" in text
    assert "py -3.12 -m uv sync --frozen" not in text
    assert "py -3.12 script/ci/run_formal_deploy.py" not in text


def test_deploy_workflow_runs_from_canonical_repo_root_directly() -> None:
    text = Path(".github/workflows/deploy-production.yml").read_text(encoding="utf-8")

    assert (
        "$entrypoint = Join-Path $env:FQ_DEPLOY_CANONICAL_REPO_ROOT "
        "'script/ci/run_production_deploy.ps1'"
    ) in text
    assert "-File $entrypoint" in text
    assert r"FQ_DEPLOY_CANONICAL_REPO_ROOT: D:\fqpack\freshquant-2026.2.23" in text
    assert 'FQ_DOCKER_FORCE_LOCAL_BUILD: "1"' in text
    assert "FQ_DEPLOY_BOOTSTRAP_ROOT" not in text
    assert "FQ_DEPLOY_MIRROR_ROOT" not in text
    assert "FQ_DEPLOY_MIRROR_BRANCH" not in text


def test_run_production_deploy_syncs_local_main_before_formal_deploy() -> None:
    text = Path("script/ci/run_production_deploy.ps1").read_text(encoding="utf-8")

    assert '[string]$CanonicalRoot' in text
    assert '[string]$TargetSha' in text
    assert "Invoke-Git -RepoRoot $CanonicalRoot -Arguments @(\"fetch\", \"origin\", \"main\")" in text
    assert 'Invoke-Git -RepoRoot $CanonicalRoot -Arguments @("checkout", "-f", "main")' in text
    assert 'Invoke-Git -RepoRoot $CanonicalRoot -Arguments @("reset", "--hard", $TargetSha)' in text
    assert 'Invoke-Git -RepoRoot $CanonicalRoot -Arguments @("clean", "-ffd")' in text
    assert '$currentBranch = Get-GitOutput -RepoRoot $CanonicalRoot -Arguments @("branch", "--show-current")' in text
    assert "stale push deploy trigger" in text
    assert "BootstrapRoot" not in text
    assert "MirrorRoot" not in text
    assert "SkipBootstrapReexec" not in text


def test_run_production_deploy_quiesces_host_runtime_before_retrying_uv_sync() -> None:
    text = Path("script/ci/run_production_deploy.ps1").read_text(encoding="utf-8")

    assert "StopSurfaces" in text
    assert "RestartSurfaces" in text
    assert "retrying uv sync after quiescing host runtime surfaces" in text
    assert "$hostRuntimeSurfaces = @(" in text


def test_run_production_deploy_repairs_missing_repo_venv_metadata() -> None:
    text = Path("script/ci/run_production_deploy.ps1").read_text(encoding="utf-8")

    assert "Repair-RepoVirtualenv" in text
    assert "pyvenv.cfg" in text
    assert '"-m", "uv", "venv"' in text
    assert '"--clear"' in text
    assert "canonical repo virtualenv" in text


def test_run_production_deploy_uses_canonical_repo_root_venv() -> None:
    text = Path("script/ci/run_production_deploy.ps1").read_text(encoding="utf-8")

    assert '.venv\\Scripts\\python.exe' in text
    assert "Test-RepoVirtualenvHealthy" in text
    assert "Invoke-UvSyncWithHostRuntimeQuiesce" in text
    assert '--repo-root", "."' in text


def test_run_production_deploy_catches_py_launcher_failures_before_fallback() -> None:
    text = Path("script/ci/run_production_deploy.ps1").read_text(encoding="utf-8")
    start = text.index("function Get-PyLauncherPython312")
    end = text.index("function Get-RegisteredPython312Candidates")
    py_launcher_block = text[start:end]

    assert (
        '$pythonExe = & $pyCommand.Source -3.12 -c "import sys; print(sys.executable)" 2>$null'
        in py_launcher_block
    )
    assert "try {" in py_launcher_block
    assert "catch {" in py_launcher_block
    assert "return $null" in py_launcher_block


def _powershell_executable() -> str:
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell is not available in PATH")
    assert executable is not None
    return executable


def test_run_production_deploy_help_exits_zero() -> None:
    result = subprocess.run(
        [
            _powershell_executable(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "script/ci/run_production_deploy.ps1",
            "-Help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Run production deploy" in result.stdout
