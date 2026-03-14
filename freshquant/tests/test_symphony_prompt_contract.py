from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PROMPT = REPO_ROOT / "runtime" / "symphony" / "WORKFLOW.freshquant.md"
WORKFLOW_VALIDATOR = (
    REPO_ROOT
    / "runtime"
    / "symphony"
    / "scripts"
    / "assert_freshquant_workflow_prompt.ps1"
)
GLOBAL_STEWARDSHIP_PROMPT = (
    REPO_ROOT / "runtime" / "symphony" / "prompts" / "global_stewardship.md"
)
GLOBAL_STEWARDSHIP_VALIDATOR = (
    REPO_ROOT
    / "runtime"
    / "symphony"
    / "scripts"
    / "assert_freshquant_global_stewardship_prompt.ps1"
)
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


def test_workflow_prompt_contract_passes_for_repo_prompt() -> None:
    result = _run_powershell(WORKFLOW_VALIDATOR, "-WorkflowPath", str(WORKFLOW_PROMPT))

    assert result.returncode == 0, result.stderr


def test_global_stewardship_prompt_contract_passes_for_repo_prompt() -> None:
    result = _run_powershell(
        GLOBAL_STEWARDSHIP_VALIDATOR,
        "-PromptPath",
        str(GLOBAL_STEWARDSHIP_PROMPT),
    )

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


def test_global_stewardship_prompt_contract_rejects_missing_runtime_ops_guardrails(
    tmp_path: Path,
) -> None:
    prompt_path = tmp_path / "global_stewardship.md"
    prompt_path.write_text(
        """# FreshQuant Global Stewardship Prompt

You are the single global Codex automation for FreshQuant `Global Stewardship`.

Required behavior:

- Read the current `main` state before deciding any deployment batch.
- Run post-deploy health checks.
- Complete cleanup for covered issues.
- Close the original issue only after `deploy + health check + cleanup` are complete.
""",
        encoding="utf-8",
    )

    result = _run_powershell(
        GLOBAL_STEWARDSHIP_VALIDATOR,
        "-PromptPath",
        str(prompt_path),
    )

    assert result.returncode != 0
    assert (
        "runtime" in result.stderr.lower()
        or "cleanup" in result.stderr.lower()
        or "deploy plan" in result.stderr.lower()
        or "host runtime" in result.stderr.lower()
    )


def test_workflow_prompt_contract_rejects_missing_runtime_ops_guardrail(
    tmp_path: Path,
) -> None:
    workflow_path = tmp_path / "workflow.md"
    workflow_path.write_text(
        """---
tracker:
  kind: github
  repo: dao1oad/fqpack-next
  state_labels:
    todo: todo
    in_progress: in-progress
    rework: rework
    merging: merging
    global_stewardship: global-stewardship
---

You are working on FreshQuant GitHub issue `{{ issue.identifier }}`

Issue context:
Identifier: {{ issue.identifier }}
Title: {{ issue.title }}
Current state: {{ issue.state }}
URL: {{ issue.url }}

Description:
{{ issue.description }}

State contract:

- `Merging`: merge the PR, write the merge handoff comment, and move the issue to `Global Stewardship`.
- `Global Stewardship`: global Codex automation handles deploy, health check, cleanup, and follow-up issue creation.

Required behavior:

7. If a task is high risk, the first priority is to make sure the GitHub review surface exists. If there is no linked Draft PR yet, first create or switch to the issue branch, create the Draft PR, and publish the complete Design Review Packet in the PR body before more repo exploration.
11. If the issue enters `Blocked`, record the blocker, clear condition, evidence, and target recovery state in GitHub. Do not leave a blocked task without saying whether it should resume to `In Progress`, `Rework`, or `Global Stewardship`.
12. Once Design Review is approved, do not ask for new human approval to handle CI, merge conflicts, deploy failures, or cleanup failures within the same issue scope. Route that work to `Rework` or `Global Stewardship` by default; use `Blocked` only when a new real external blocker appears and record the blocker, clear condition, evidence, and target recovery state.
13. When GitHub truth proves a blocked task is misclassified, restore it automatically: merged PR, pending ops -> `Global Stewardship`; open non-draft PR -> `Rework`; approved draft PR -> `In Progress`.
17. If code repair is needed after merge, only create a follow-up issue for the next Symphony round; do not create a repair PR directly from the global automation.
""",
        encoding="utf-8",
    )

    result = _run_powershell(WORKFLOW_VALIDATOR, "-WorkflowPath", str(workflow_path))

    assert result.returncode != 0
    assert (
        "runtime ops" in result.stderr.lower()
        or "global stewardship" in result.stderr.lower()
    )


def test_sync_script_references_global_runtime_ops_check_script() -> None:
    sync_content = SYNC_SCRIPT.read_text(encoding="utf-8")

    assert "check_freshquant_runtime_post_deploy.ps1" in sync_content


def test_global_stewardship_prompt_references_shared_deploy_scripts() -> None:
    prompt_content = GLOBAL_STEWARDSHIP_PROMPT.read_text(encoding="utf-8")

    assert "freshquant_deploy_plan.py" in prompt_content
    assert "fqnext_host_runtime_ctl.ps1" in prompt_content


def test_sync_and_start_scripts_reference_merging_prompt_validator() -> None:
    sync_content = SYNC_SCRIPT.read_text(encoding="utf-8")
    start_content = START_SCRIPT.read_text(encoding="utf-8")

    assert "assert_freshquant_merging_prompt.ps1" in sync_content
    assert "assert_freshquant_merging_prompt.ps1" in start_content
