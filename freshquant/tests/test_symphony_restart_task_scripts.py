from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPT = (
    REPO_ROOT
    / "runtime"
    / "symphony"
    / "scripts"
    / "install_freshquant_symphony_restart_task.ps1"
)
RUN_TASK_SCRIPT = (
    REPO_ROOT
    / "runtime"
    / "symphony"
    / "scripts"
    / "run_freshquant_symphony_restart_task.ps1"
)


def test_install_restart_task_grants_non_elevated_invoke_access() -> None:
    content = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert "Grant-TaskReadAndExecuteAccess" in content
    assert "GetSecurityDescriptor" in content
    assert "SetSecurityDescriptor" in content
    assert "FRFX" in content
    assert ".AddAccess(" not in content


def test_run_restart_task_waits_for_health_endpoint() -> None:
    content = RUN_TASK_SCRIPT.read_text(encoding="utf-8")

    assert "Wait-HealthEndpointReady" in content
    assert "HealthTimeoutSeconds" in content
    assert "HealthPollIntervalSeconds" in content
