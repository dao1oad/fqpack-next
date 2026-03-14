from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_CODEX_SESSION_SCRIPT = (
    REPO_ROOT / "runtime" / "symphony" / "scripts" / "run_freshquant_codex_session.ps1"
)
WORKFLOW_PROMPT = REPO_ROOT / "runtime" / "symphony" / "WORKFLOW.freshquant.md"
TODO_PROMPT = REPO_ROOT / "runtime" / "symphony" / "prompts" / "todo.md"
IN_PROGRESS_PROMPT = REPO_ROOT / "runtime" / "symphony" / "prompts" / "in_progress.md"
GLOBAL_STEWARDSHIP_PROMPT = (
    REPO_ROOT / "runtime" / "symphony" / "prompts" / "global_stewardship.md"
)


def test_run_codex_session_refreshes_and_compiles_memory_before_launch() -> None:
    content = RUN_CODEX_SESSION_SCRIPT.read_text(encoding="utf-8")

    assert "refresh_freshquant_memory.py" in content
    assert "compile_freshquant_context_pack.py" in content
    assert "FQ_MEMORY_CONTEXT_PATH" in content
    assert (
        "& $codexPath --config shell_environment_policy.inherit=all app-server"
        in content
    )


def test_run_codex_session_derives_memory_role_from_issue_state() -> None:
    content = RUN_CODEX_SESSION_SCRIPT.read_text(encoding="utf-8")

    assert "Get-MemoryContextRole" in content
    assert "Global Stewardship" in content
    assert "--role" in content
    assert "$memoryContextRole" in content
    assert (
        "[Environment]::SetEnvironmentVariable('FQ_MEMORY_CONTEXT_ROLE', $memoryContextRole, 'Process')"
        in content
    )


def test_workflow_prompt_requires_memory_context_as_derived_input() -> None:
    content = WORKFLOW_PROMPT.read_text(encoding="utf-8")

    assert "FQ_MEMORY_CONTEXT_PATH" in content
    assert "read the memory context pack first" in content.lower()
    assert "does not replace GitHub" in content


def test_all_runtime_prompts_reference_memory_context_contract() -> None:
    for prompt_path in (TODO_PROMPT, IN_PROGRESS_PROMPT, GLOBAL_STEWARDSHIP_PROMPT):
        content = prompt_path.read_text(encoding="utf-8")

        assert "FQ_MEMORY_CONTEXT_PATH" in content, str(prompt_path)
        assert "memory context" in content.lower(), str(prompt_path)
