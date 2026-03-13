from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


class _GitHubApiStub:
    def __init__(self) -> None:
        self.list_pages: list[int] = []
        self.comment_bodies: list[str] = []
        self.patch_paths: list[str] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._build_handler())
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return None

            def _send_json(self, payload: object, status: int = 200) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/repos/dao1oad/fqpack-next/issues/999":
                    self._send_json(
                        {
                            "number": 999,
                            "state": "open",
                            "labels": [{"name": "merging"}],
                        }
                    )
                    return

                if parsed.path == "/repos/dao1oad/fqpack-next/issues":
                    query = parse_qs(parsed.query)
                    page = int(query.get("page", ["1"])[0])
                    owner.list_pages.append(page)

                    if page == 1:
                        issues = [{"number": index} for index in range(1, 101)]
                    elif page == 2:
                        issues = [{"number": 150}]
                    else:
                        issues = []

                    self._send_json(issues)
                    return

                self._send_json({"message": f"Unhandled GET {parsed.path}"}, status=404)

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/repos/dao1oad/fqpack-next/issues/999/comments":
                    content_length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(content_length) or b"{}")
                    owner.comment_bodies.append(payload.get("body", ""))
                    self._send_json({"id": 1}, status=201)
                    return

                self._send_json(
                    {"message": f"Unhandled POST {parsed.path}"}, status=404
                )

            def do_PATCH(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/repos/dao1oad/fqpack-next/issues/999":
                    owner.patch_paths.append(parsed.path)
                    self._send_json({"state": "closed"})
                    return

                self._send_json(
                    {"message": f"Unhandled PATCH {parsed.path}"}, status=404
                )

        return Handler

    def __enter__(self) -> "_GitHubApiStub":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def test_request_cleanup_writes_manifest(tmp_path: Path) -> None:
    service_root = tmp_path / "service"
    workspaces_root = service_root / "workspaces"
    workspace_path = workspaces_root / "GH-999"
    workspace_path.mkdir(parents=True)

    result = _run_powershell(
        REQUEST_SCRIPT,
        "-ServiceRoot",
        str(service_root),
        "-IssueIdentifier",
        "GH-999",
        "-BranchName",
        "feature/gh-999",
        "-WorkspacePath",
        str(workspace_path),
        "-DeploymentCommentBody",
        "deployment body",
        "-OriginUrl",
        "ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git",
        "-IssueUrl",
        "https://github.com/dao1oad/fqpack-next/issues/999",
        "-PullRequestNumber",
        "123",
        "-PullRequestUrl",
        "https://github.com/dao1oad/fqpack-next/pull/123",
    )

    assert result.returncode == 0, result.stderr
    request_path = service_root / "artifacts" / "cleanup-requests" / "GH-999.json"
    assert request_path.exists()
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload["issueIdentifier"] == "GH-999"
    assert payload["branchName"] == "feature/gh-999"
    assert (
        payload["originUrl"] == "ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git"
    )
    assert payload["workspacePath"] == str(workspace_path)
    assert payload["deploymentCommentBody"] == "deployment body"
    assert payload["issueUrl"] == "https://github.com/dao1oad/fqpack-next/issues/999"
    assert payload["pullRequestNumber"] == 123
    assert (
        payload["pullRequestUrl"] == "https://github.com/dao1oad/fqpack-next/pull/123"
    )
    assert payload["repository"] == "dao1oad/fqpack-next"
    assert payload["artifactsRetentionDays"] == 14


def test_request_cleanup_reads_deployment_comment_body_from_utf8_file(
    tmp_path: Path,
) -> None:
    service_root = tmp_path / "service"
    workspaces_root = service_root / "workspaces"
    workspace_path = workspaces_root / "GH-999"
    workspace_path.mkdir(parents=True)

    comment_body = (
        "已核对 PR `#105`\n\n"
        "- `fq_webui` 当前为 `Up`\n"
        "- 页面 `/kline-slim` 返回 `200`\n"
        "- 中文说明保持原样"
    )
    comment_path = tmp_path / "deployment-comment.md"
    comment_path.write_text(comment_body, encoding="utf-8")

    result = _run_powershell(
        REQUEST_SCRIPT,
        "-ServiceRoot",
        str(service_root),
        "-IssueIdentifier",
        "GH-999",
        "-BranchName",
        "feature/gh-999",
        "-WorkspacePath",
        str(workspace_path),
        "-DeploymentCommentBodyPath",
        str(comment_path),
        "-OriginUrl",
        "ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git",
        "-IssueUrl",
        "https://github.com/dao1oad/fqpack-next/issues/999",
    )

    assert result.returncode == 0, result.stderr
    request_path = service_root / "artifacts" / "cleanup-requests" / "GH-999.json"
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert _normalize_newlines(payload["deploymentCommentBody"]) == comment_body


def test_request_cleanup_rejects_workspace_outside_workspace_root(
    tmp_path: Path,
) -> None:
    service_root = tmp_path / "service"
    outside_workspace = tmp_path / "outside" / "GH-999"
    outside_workspace.mkdir(parents=True)

    result = _run_powershell(
        REQUEST_SCRIPT,
        "-ServiceRoot",
        str(service_root),
        "-IssueIdentifier",
        "GH-999",
        "-BranchName",
        "feature/gh-999",
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
    workspace_path = workspaces_root / "GH-999"
    workspace_path.mkdir(parents=True)
    (workspace_path / "tracked.txt").write_text("ok", encoding="utf-8")

    stale_artifact = artifacts_root / "GH-998"
    stale_artifact.mkdir(parents=True)
    active_artifact = artifacts_root / "GH-1000"
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
        "GH-999",
        "-BranchName",
        "feature/gh-999",
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
        "GH-999",
        "-WorkspacePath",
        str(workspace_path),
        "-SkipRemoteBranchDelete",
        "-SkipGitHubUpdate",
        "-ActiveIssueIdentifiers",
        "GH-1000",
    )

    assert finalizer_result.returncode == 0, finalizer_result.stderr
    assert not workspace_path.exists()
    assert not stale_artifact.exists()
    assert active_artifact.exists()
    assert system_dir.exists()

    result_path = artifacts_root / "cleanup-results" / "GH-999.json"
    assert result_path.exists()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["success"] is True
    assert payload["workspaceDeleted"] is True
    assert payload["remoteBranchDeleted"] == "skipped"
    assert payload["githubUpdated"] == "skipped"


def test_finalizer_deletes_remote_branch_without_workspace(tmp_path: Path) -> None:
    service_root = tmp_path / "service"
    workspaces_root = service_root / "workspaces"
    workspace_path = workspaces_root / "GH-999"
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
        "HEAD:refs/heads/feature/gh-999",
        cwd=seed_path,
    )
    assert push_feature.returncode == 0, push_feature.stderr

    request_result = _run_powershell(
        REQUEST_SCRIPT,
        "-ServiceRoot",
        str(service_root),
        "-IssueIdentifier",
        "GH-999",
        "-BranchName",
        "feature/gh-999",
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
        "GH-999",
        "-WorkspacePath",
        str(workspace_path),
        "-SkipGitHubUpdate",
    )
    assert finalizer_result.returncode == 0, finalizer_result.stderr

    remote_branch_check = _run_git(
        "ls-remote",
        "--exit-code",
        "--heads",
        str(remote_path),
        "feature/gh-999",
        cwd=tmp_path,
    )
    assert remote_branch_check.returncode == 2, (
        remote_branch_check.stdout + remote_branch_check.stderr
    )


def test_finalizer_keeps_active_artifacts_from_paginated_github_issue_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_root = tmp_path / "service"
    workspaces_root = service_root / "workspaces"
    artifacts_root = service_root / "artifacts"
    workspace_path = workspaces_root / "GH-999"
    workspace_path.mkdir(parents=True)
    (workspace_path / "tracked.txt").write_text("ok", encoding="utf-8")

    active_artifact = artifacts_root / "GH-150"
    active_artifact.mkdir(parents=True)
    stale_artifact = artifacts_root / "GH-151"
    stale_artifact.mkdir(parents=True)

    stale_time = 1_700_000_000
    os.utime(active_artifact, (stale_time, stale_time))
    os.utime(stale_artifact, (stale_time, stale_time))

    request_result = _run_powershell(
        REQUEST_SCRIPT,
        "-ServiceRoot",
        str(service_root),
        "-IssueIdentifier",
        "GH-999",
        "-BranchName",
        "feature/gh-999",
        "-WorkspacePath",
        str(workspace_path),
        "-DeploymentCommentBody",
        "deployment body",
        "-OriginUrl",
        "ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git",
        "-Repository",
        "dao1oad/fqpack-next",
    )
    assert request_result.returncode == 0, request_result.stderr

    with _GitHubApiStub() as stub:
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        monkeypatch.setenv("FRESHQUANT_GITHUB_API_BASE_URL", stub.base_url)
        monkeypatch.setenv("GITHUB_API_BASE_URL", stub.base_url)

        finalizer_result = _run_powershell(
            FINALIZER_SCRIPT,
            "-ServiceRoot",
            str(service_root),
            "-IssueIdentifier",
            "GH-999",
            "-WorkspacePath",
            str(workspace_path),
            "-SkipRemoteBranchDelete",
        )

    assert finalizer_result.returncode == 0, finalizer_result.stderr
    assert not workspace_path.exists()
    assert active_artifact.exists()
    assert not stale_artifact.exists()
    assert stub.list_pages == [1, 2]
    assert len(stub.comment_bodies) == 1
    assert stub.patch_paths == ["/repos/dao1oad/fqpack-next/issues/999"]

    result_path = artifacts_root / "cleanup-results" / "GH-999.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["success"] is True
    assert payload["issueClosed"] is True
    assert payload["githubUpdated"] is True


def test_finalizer_posts_utf8_markdown_comment_body_from_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_root = tmp_path / "service"
    workspaces_root = service_root / "workspaces"
    workspace_path = workspaces_root / "GH-999"
    workspace_path.mkdir(parents=True)
    (workspace_path / "tracked.txt").write_text("ok", encoding="utf-8")

    comment_body = (
        "已核对 PR `#105`、CI 和运行面。\n\n"
        "- `fq_webui` / `fq_apiserver` 当前均为 `Up`\n"
        "- `http://127.0.0.1:18080/kline-slim` 返回 `200`\n"
        "- 中文不应被替换成问号"
    )
    comment_path = tmp_path / "deployment-comment.md"
    comment_path.write_text(comment_body, encoding="utf-8")

    request_result = _run_powershell(
        REQUEST_SCRIPT,
        "-ServiceRoot",
        str(service_root),
        "-IssueIdentifier",
        "GH-999",
        "-BranchName",
        "feature/gh-999",
        "-WorkspacePath",
        str(workspace_path),
        "-DeploymentCommentBodyPath",
        str(comment_path),
        "-OriginUrl",
        "ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git",
        "-Repository",
        "dao1oad/fqpack-next",
    )
    assert request_result.returncode == 0, request_result.stderr

    with _GitHubApiStub() as stub:
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        monkeypatch.setenv("FRESHQUANT_GITHUB_API_BASE_URL", stub.base_url)
        monkeypatch.setenv("GITHUB_API_BASE_URL", stub.base_url)

        finalizer_result = _run_powershell(
            FINALIZER_SCRIPT,
            "-ServiceRoot",
            str(service_root),
            "-IssueIdentifier",
            "GH-999",
            "-WorkspacePath",
            str(workspace_path),
            "-SkipRemoteBranchDelete",
        )

    assert finalizer_result.returncode == 0, finalizer_result.stderr
    assert len(stub.comment_bodies) == 1
    expected_comment_body = (
        comment_body
        + "\n## Cleanup Results\n\n"
        + "- Remote branch cleanup: `skipped`\n"
        + "- Workspace cleanup: `True`\n"
        + "- Artifacts retention days: `14`\n\n"
        + "### Pruned Artifacts\n\n"
        + "- `none`"
    )
    assert _normalize_newlines(stub.comment_bodies[0]) == expected_comment_body
