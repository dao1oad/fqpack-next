from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_local_preflight_and_hook_scripts_exist() -> None:
    preflight_script = REPO_ROOT / "script" / "fq_local_preflight.ps1"
    hook_script = REPO_ROOT / ".githooks" / "pre-push"
    install_script = REPO_ROOT / "script" / "install_repo_hooks.ps1"
    open_pr_script = REPO_ROOT / "script" / "fq_open_pr.ps1"

    assert preflight_script.exists()
    assert hook_script.exists()
    assert install_script.exists()
    assert open_pr_script.exists()


def test_local_preflight_script_contains_preflight_contract() -> None:
    text = (REPO_ROOT / "script" / "fq_local_preflight.ps1").read_text(encoding="utf-8")

    assert "check_current_docs.py" in text
    assert "pre-commit" in text
    assert "check_pr_review_threads.py" in text
    assert '"pytest"' in text
    assert '"freshquant/tests"' in text
    assert '"loadfile"' in text
    assert "remote.pushDefault" in text
    assert "Invoke-ReviewThreadsCheck" in text
    assert "head_sha" in text
    assert "base_sha" in text
    assert "fq-preflight" in text


@pytest.mark.parametrize("child_exit_code", [0, 7])
def test_invoke_external_command_returns_only_native_exit_code(child_exit_code: int) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is not installed")

    preflight_script = REPO_ROOT / "script" / "fq_local_preflight.ps1"
    probe = f"Write-Output 'probe-output'; exit {child_exit_code}"
    command = r"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:FQ_TEST_PREFLIGHT, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw ($errors | Out-String) }
$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Invoke-ExternalCommand'
}, $true)
if ($null -eq $functionAst) { throw 'Invoke-ExternalCommand not found' }
Invoke-Expression $functionAst.Extent.Text
$value = Invoke-ExternalCommand -FilePath $env:FQ_TEST_POWERSHELL -Arguments @('-NoProfile', '-NonInteractive', '-Command', $env:FQ_TEST_PROBE)
[pscustomobject]@{ type = $value.GetType().FullName; value = $value } | ConvertTo-Json -Compress
"""
    environment = os.environ.copy()
    environment.update(
        {
            "FQ_TEST_PREFLIGHT": str(preflight_script),
            "FQ_TEST_POWERSHELL": powershell,
            "FQ_TEST_PROBE": probe,
        }
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.splitlines()[-1])
    assert payload == {"type": "System.Int32", "value": child_exit_code}
    assert "probe-output" in result.stdout


def test_pre_push_hook_uses_shell_wrapper_to_call_powershell() -> None:
    text = (REPO_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")

    assert text.startswith("#!/bin/sh")
    assert "powershell.exe" in text or "pwsh" in text
    assert "fq_local_preflight.ps1" in text


def test_open_pr_script_requires_preflight_before_gh_pr_create() -> None:
    text = (REPO_ROOT / "script" / "fq_open_pr.ps1").read_text(encoding="utf-8")

    assert "gh" in text
    assert "pr" in text
    assert "create" in text
    assert "fq_local_preflight.ps1" in text


def test_review_thread_check_script_exists() -> None:
    script = REPO_ROOT / "script" / "ci" / "check_pr_review_threads.py"

    assert script.exists()
