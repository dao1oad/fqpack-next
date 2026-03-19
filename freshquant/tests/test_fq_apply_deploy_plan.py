from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_apply_deploy_plan_script_exists_and_uses_shared_planner() -> None:
    script_path = REPO_ROOT / "script" / "fq_apply_deploy_plan.ps1"

    assert script_path.exists()
    text = script_path.read_text(encoding="utf-8")
    assert "freshquant_deploy_plan.py" in text
    assert "docker_parallel_compose.ps1" in text
    assert "fqnext_host_runtime_ctl.ps1" in text
    assert "check_freshquant_runtime_post_deploy.ps1" in text


def test_apply_deploy_plan_supports_changed_paths_and_git_diff() -> None:
    text = (REPO_ROOT / "script" / "fq_apply_deploy_plan.ps1").read_text(
        encoding="utf-8"
    )

    assert "ChangedPath" in text
    assert "FromGitDiff" in text
    assert "DeploymentSurface" in text


def test_apply_deploy_plan_supports_resume_state_tracking() -> None:
    text = (REPO_ROOT / "script" / "fq_apply_deploy_plan.ps1").read_text(
        encoding="utf-8"
    )

    assert "StatePath" in text
    assert "ResumeFromStatePath" in text
    assert "ResumeLatest" in text
    assert "baseline" in text.lower()
    assert "docker" in text.lower()
    assert "host" in text.lower()
    assert "health" in text.lower()
    assert "verify" in text.lower()


def test_apply_deploy_plan_resets_failed_phases_to_pending_on_resume() -> None:
    text = (REPO_ROOT / "script" / "fq_apply_deploy_plan.ps1").read_text(
        encoding="utf-8"
    )

    assert '$status -eq "failed"' in text
    assert '$phaseState.status = "pending"' in text
