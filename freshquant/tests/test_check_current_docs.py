from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "script" / "ci" / "check_current_docs.py"
PYTHON = Path(sys.executable)


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_guard(
    repo: Path, base_ref: str, head_ref: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PYTHON), str(SCRIPT_PATH), "--base-ref", base_ref, "--head-ref", head_ref],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _write(repo: Path, relative_path: str, content: str) -> None:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()

    assert _run_git(repo, "init", "-b", "main").returncode == 0
    assert _run_git(repo, "config", "user.email", "test@example.com").returncode == 0
    assert _run_git(repo, "config", "user.name", "Test User").returncode == 0

    _write(repo, "freshquant/rear/api_server.py", "print('base')\n")
    _write(repo, "docs/current/overview.md", "# overview\n")
    _write(repo, ".github/workflows/ci.yml", "name: CI\n")

    assert _run_git(repo, "add", ".").returncode == 0
    assert _run_git(repo, "commit", "-m", "base").returncode == 0
    base_ref = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, base_ref


def test_requires_docs_update_when_backend_facts_change(tmp_path: Path) -> None:
    repo, base_ref = _init_repo(tmp_path)
    _write(repo, "freshquant/rear/api_server.py", "print('changed')\n")
    assert _run_git(repo, "add", ".").returncode == 0
    assert _run_git(repo, "commit", "-m", "backend change").returncode == 0
    head_ref = _run_git(repo, "rev-parse", "HEAD").stdout.strip()

    result = _run_guard(repo, base_ref, head_ref)

    assert result.returncode != 0
    assert "docs/current" in (result.stderr + result.stdout)


def test_passes_when_current_docs_change_with_backend_change(tmp_path: Path) -> None:
    repo, base_ref = _init_repo(tmp_path)
    _write(repo, "freshquant/rear/api_server.py", "print('changed')\n")
    _write(repo, "docs/current/overview.md", "# updated overview\n")
    assert _run_git(repo, "add", ".").returncode == 0
    assert _run_git(repo, "commit", "-m", "backend change with docs").returncode == 0
    head_ref = _run_git(repo, "rev-parse", "HEAD").stdout.strip()

    result = _run_guard(repo, base_ref, head_ref)

    assert result.returncode == 0, result.stderr


def test_ci_only_changes_do_not_require_current_docs(tmp_path: Path) -> None:
    repo, base_ref = _init_repo(tmp_path)
    _write(repo, ".github/workflows/ci.yml", "name: Changed CI\n")
    assert _run_git(repo, "add", ".").returncode == 0
    assert _run_git(repo, "commit", "-m", "ci only").returncode == 0
    head_ref = _run_git(repo, "rev-parse", "HEAD").stdout.strip()

    result = _run_guard(repo, base_ref, head_ref)

    assert result.returncode == 0, result.stderr


def test_current_deployment_doc_mentions_production_mirror_worktree() -> None:
    deployment_text = (REPO_ROOT / "docs/current/deployment.md").read_text(
        encoding="utf-8"
    )
    runtime_text = (REPO_ROOT / "docs/current/runtime.md").read_text(encoding="utf-8")

    assert (
        r"D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production"
        in deployment_text
    )
    assert "deploy-production-main" in deployment_text
    assert "safe.directory" in deployment_text
    assert (
        r"D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production"
        in runtime_text
    )
