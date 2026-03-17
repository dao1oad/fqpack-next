from __future__ import annotations

from pathlib import Path


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
    text = (REPO_ROOT / "script" / "fq_local_preflight.ps1").read_text(
        encoding="utf-8"
    )

    assert "check_current_docs.py" in text
    assert "pre-commit" in text
    assert '"pytest"' in text
    assert '"freshquant/tests"' in text
    assert '"loadfile"' in text
    assert "remote.pushDefault" in text
    assert "head_sha" in text
    assert "base_sha" in text
    assert "fq-preflight" in text


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
