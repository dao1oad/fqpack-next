from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUEST_SCRIPT = (
    REPO_ROOT
    / "runtime"
    / "symphony"
    / "scripts"
    / "request_freshquant_symphony_cleanup.ps1"
)
FINALIZER_SCRIPT = (
    REPO_ROOT
    / "runtime"
    / "symphony"
    / "scripts"
    / "invoke_freshquant_symphony_cleanup_finalizer.ps1"
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


def _run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    command = ["git", *args]
    return subprocess.run(command, capture_output=True, text=True, check=False, cwd=cwd)


def test_request_cleanup_writes_manifest(tmp_path: Path) -> None:
    service_root = tmp_path / "service"
    workspaces_root = service_root / "workspaces"
    workspace_path = workspaces_root / "FRE-999"
    workspace_path.mkdir(parents=True)

    result = _run_powershell(
        REQUEST_SCRIPT,
        "-ServiceRoot",
        str(service_root),
        "-IssueIdentifier",
        "FRE-999",
        "-BranchName",
        "feature/fre-999",
        "-WorkspacePath",
        str(workspace_path),
        "-DeploymentCommentBody",
        "deployment body",
        "-OriginUrl",
        "ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git",
    )

    assert result.returncode == 0, result.stderr
    request_path = service_root / "artifacts" / "cleanup-requests" / "FRE-999.json"
    assert request_path.exists()
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload["issueIdentifier"] == "FRE-999"
    assert payload["branchName"] == "feature/fre-999"
    assert (
        payload["originUrl"] == "ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git"
    )
    assert payload["workspacePath"] == str(workspace_path)
    assert payload["deploymentCommentBody"] == "deployment body"
    assert payload["artifactsRetentionDays"] == 14


def test_request_cleanup_rejects_workspace_outside_workspace_root(
    tmp_path: Path,
) -> None:
    service_root = tmp_path / "service"
    outside_workspace = tmp_path / "outside" / "FRE-999"
    outside_workspace.mkdir(parents=True)

    result = _run_powershell(
        REQUEST_SCRIPT,
        "-ServiceRoot",
        str(service_root),
        "-IssueIdentifier",
        "FRE-999",
        "-BranchName",
        "feature/fre-999",
        "-WorkspacePath",
        str(outside_workspace),
        "-DeploymentCommentBody",
        "deployment body",
        "-OriginUrl",
        "ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git",
    )

    assert result.returncode != 0
    assert "workspace" in result.stderr.lower()


def test_finalizer_removes_workspace_and_stale_artifacts(tmp_path: Path) -> None:
    service_root = tmp_path / "service"
    workspaces_root = service_root / "workspaces"
    artifacts_root = service_root / "artifacts"
    workspace_path = workspaces_root / "FRE-999"
    workspace_path.mkdir(parents=True)
    (workspace_path / "tracked.txt").write_text("ok", encoding="utf-8")

    stale_artifact = artifacts_root / "FRE-998"
    stale_artifact.mkdir(parents=True)
    active_artifact = artifacts_root / "FRE-1000"
    active_artifact.mkdir(parents=True)
    system_dir = artifacts_root / "cleanup-results"
    system_dir.mkdir(parents=True)

    stale_time = 1_700_000_000
    os.utime(stale_artifact, (stale_time, stale_time))
    os.utime(active_artifact, (stale_time, stale_time))

    request_result = _run_powershell(
        REQUEST_SCRIPT,
        "-ServiceRoot",
        str(service_root),
        "-IssueIdentifier",
        "FRE-999",
        "-BranchName",
        "feature/fre-999",
        "-WorkspacePath",
        str(workspace_path),
        "-DeploymentCommentBody",
        "deployment body",
        "-OriginUrl",
        "ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git",
        "-ArtifactsRetentionDays",
        "14",
    )
    assert request_result.returncode == 0, request_result.stderr

    finalizer_result = _run_powershell(
        FINALIZER_SCRIPT,
        "-ServiceRoot",
        str(service_root),
        "-IssueIdentifier",
        "FRE-999",
        "-WorkspacePath",
        str(workspace_path),
        "-SkipRemoteBranchDelete",
        "-SkipLinearUpdate",
        "-ActiveIssueIdentifiers",
        "FRE-1000",
    )

    assert finalizer_result.returncode == 0, finalizer_result.stderr
    assert not workspace_path.exists()
    assert not stale_artifact.exists()
    assert active_artifact.exists()
    assert system_dir.exists()

    result_path = artifacts_root / "cleanup-results" / "FRE-999.json"
    assert result_path.exists()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["success"] is True
    assert payload["workspaceDeleted"] is True
    assert payload["remoteBranchDeleted"] == "skipped"


def test_finalizer_deletes_remote_branch_without_workspace(tmp_path: Path) -> None:
    service_root = tmp_path / "service"
    workspaces_root = service_root / "workspaces"
    workspace_path = workspaces_root / "FRE-999"
    workspace_path.mkdir(parents=True)

    remote_path = tmp_path / "remote.git"
    init_remote = _run_git("init", "--bare", str(remote_path), cwd=tmp_path)
    assert init_remote.returncode == 0, init_remote.stderr

    seed_path = tmp_path / "seed"
    clone_remote = _run_git("clone", str(remote_path), str(seed_path), cwd=tmp_path)
    assert clone_remote.returncode == 0, clone_remote.stderr

    assert (
        _run_git("config", "user.email", "test@example.com", cwd=seed_path).returncode
        == 0
    )
    assert _run_git("config", "user.name", "Test User", cwd=seed_path).returncode == 0
    (seed_path / "tracked.txt").write_text("ok", encoding="utf-8")
    assert _run_git("add", "tracked.txt", cwd=seed_path).returncode == 0
    assert _run_git("commit", "-m", "seed", cwd=seed_path).returncode == 0
    push_feature = _run_git(
        "push",
        "origin",
        "HEAD:refs/heads/feature/fre-999",
        cwd=seed_path,
    )
    assert push_feature.returncode == 0, push_feature.stderr

    request_result = _run_powershell(
        REQUEST_SCRIPT,
        "-ServiceRoot",
        str(service_root),
        "-IssueIdentifier",
        "FRE-999",
        "-BranchName",
        "feature/fre-999",
        "-WorkspacePath",
        str(workspace_path),
        "-DeploymentCommentBody",
        "deployment body",
        "-OriginUrl",
        str(remote_path),
    )
    assert request_result.returncode == 0, request_result.stderr

    workspace_path.rmdir()
    finalizer_result = _run_powershell(
        FINALIZER_SCRIPT,
        "-ServiceRoot",
        str(service_root),
        "-IssueIdentifier",
        "FRE-999",
        "-WorkspacePath",
        str(workspace_path),
        "-SkipLinearUpdate",
    )
    assert finalizer_result.returncode == 0, finalizer_result.stderr

    remote_branch_check = _run_git(
        "ls-remote",
        "--exit-code",
        "--heads",
        str(remote_path),
        "feature/fre-999",
        cwd=tmp_path,
    )
    assert remote_branch_check.returncode == 2, (
        remote_branch_check.stdout + remote_branch_check.stderr
    )
