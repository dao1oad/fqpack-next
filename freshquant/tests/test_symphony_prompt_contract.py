from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MERGING_PROMPT = REPO_ROOT / "runtime" / "symphony" / "prompts" / "merging.md"
MERGING_VALIDATOR = (
    REPO_ROOT
    / "runtime"
    / "symphony"
    / "scripts"
    / "assert_freshquant_merging_prompt.ps1"
)
SYNC_SCRIPT = (
    REPO_ROOT
    / "runtime"
    / "symphony"
    / "scripts"
    / "sync_freshquant_symphony_service.ps1"
)
START_SCRIPT = (
    REPO_ROOT / "runtime" / "symphony" / "scripts" / "start_freshquant_symphony.ps1"
)


def _run_powershell(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell is not available in PATH")
    assert executable is not None

    command = [
        executable,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        *args,
    ]
    return subprocess.run(
        command, capture_output=True, text=True, check=False, cwd=REPO_ROOT
    )


def test_merging_prompt_contract_passes_for_repo_prompt() -> None:
    result = _run_powershell(MERGING_VALIDATOR, "-PromptPath", str(MERGING_PROMPT))

    assert result.returncode == 0, result.stderr


def test_merging_prompt_contract_rejects_missing_guardrails(tmp_path: Path) -> None:
    prompt_path = tmp_path / "merging.md"
    prompt_path.write_text(
        """# FreshQuant Merging Prompt

You are in the `Merging` phase.

Required behavior:

- Confirm the Draft PR is ready to merge.
- Merge the PR to the remote `main` branch.
- Render a structured done summary.
""",
        encoding="utf-8",
    )

    result = _run_powershell(MERGING_VALIDATOR, "-PromptPath", str(prompt_path))

    assert result.returncode != 0
    assert "watch" in result.stderr.lower() or "workspace" in result.stderr.lower()


def test_sync_and_start_scripts_reference_merging_prompt_validator() -> None:
    sync_content = SYNC_SCRIPT.read_text(encoding="utf-8")
    start_content = START_SCRIPT.read_text(encoding="utf-8")

    assert "assert_freshquant_merging_prompt.ps1" in sync_content
    assert "assert_freshquant_merging_prompt.ps1" in start_content
