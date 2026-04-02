from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def load_module():
    module_path = Path("script/ci/sync_local_deploy_mirror.py")
    spec = importlib.util.spec_from_file_location(
        "sync_local_deploy_mirror", module_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def init_bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    return remote


def init_seed_repo(tmp_path: Path, remote: Path) -> tuple[Path, str]:
    seed = tmp_path / "seed"
    seed.mkdir()
    git(["init"], seed)
    git(["config", "user.name", "Codex"], seed)
    git(["config", "user.email", "codex@example.invalid"], seed)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    git(["add", "README.md"], seed)
    git(["commit", "-m", "seed"], seed)
    git(["branch", "-M", "main"], seed)
    git(["remote", "add", "origin", str(remote)], seed)
    git(["push", "-u", "origin", "main"], seed)
    return seed, git(["rev-parse", "HEAD"], seed)


def clone_mirror(tmp_path: Path, remote: Path) -> Path:
    mirror = tmp_path / "mirror"
    subprocess.run(["git", "clone", str(remote), str(mirror)], check=True)
    git(["config", "user.name", "Codex"], mirror)
    git(["config", "user.email", "codex@example.invalid"], mirror)
    git(["checkout", "main"], mirror)
    return mirror


def commit_in_repo(repo: Path, filename: str, content: str, message: str) -> str:
    (repo / filename).write_text(content, encoding="utf-8")
    git(["add", filename], repo)
    git(["commit", "-m", message], repo)
    return git(["rev-parse", "HEAD"], repo)


def push_main(repo: Path) -> str:
    git(["push", "origin", "main"], repo)
    return git(["rev-parse", "HEAD"], repo)


def test_sync_local_deploy_mirror_fast_forwards_clean_repo(tmp_path: Path) -> None:
    module = load_module()
    remote = init_bare_remote(tmp_path)
    seed, _ = init_seed_repo(tmp_path, remote)
    mirror = clone_mirror(tmp_path, remote)

    commit_in_repo(seed, "README.md", "updated\n", "update main")
    target_sha = push_main(seed)

    result = module.sync_local_deploy_mirror(repo_root=mirror, target_sha=target_sha)

    assert result["ok"] is True
    assert result["head_sha"] == target_sha
    assert git(["rev-parse", "HEAD"], mirror) == target_sha


def test_sync_local_deploy_mirror_can_use_dedicated_checkout_branch(
    tmp_path: Path,
) -> None:
    module = load_module()
    remote = init_bare_remote(tmp_path)
    seed, _ = init_seed_repo(tmp_path, remote)
    mirror = clone_mirror(tmp_path, remote)

    git(["checkout", "-b", "feature/local-change"], mirror)
    commit_in_repo(seed, "README.md", "updated\n", "update main")
    target_sha = push_main(seed)

    result = module.sync_local_deploy_mirror(
        repo_root=mirror,
        target_sha=target_sha,
        remote_url=str(remote),
        branch="main",
        checkout_branch="deploy-production-main",
    )

    assert result["ok"] is True
    assert result["head_sha"] == target_sha
    assert (
        git(["rev-parse", "--abbrev-ref", "HEAD"], mirror) == "deploy-production-main"
    )
    assert git(["rev-parse", "HEAD"], mirror) == target_sha


def test_sync_local_deploy_mirror_marks_repo_safe_before_git_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    mirror = tmp_path / "mirror"
    (mirror / ".git").mkdir(parents=True)

    subprocess_calls: list[list[str]] = []
    head_values = iter(("before-sha", "after-sha"))

    class FakeResult:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = ""
            self.stderr = ""

    def fake_run(
        args: list[str],
        cwd: Path,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
    ) -> FakeResult:
        subprocess_calls.append(args)
        result = FakeResult()
        if args[:4] == ["git", "show-ref", "--verify", "--quiet"]:
            result.returncode = 1
        return result

    def fake_run_git(repo_root: Path, *args: str) -> str:
        if args == ("status", "--porcelain"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return next(head_values)
        if args == ("rev-parse", "refs/remotes/origin/main"):
            return "after-sha"
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "run_git", fake_run_git)

    result = module.sync_local_deploy_mirror(
        repo_root=mirror,
        target_sha="after-sha",
        remote_url="https://github.com/dao1oad/fqpack-next.git",
        branch="main",
        checkout_branch="deploy-production-main",
    )

    assert result["ok"] is True
    assert subprocess_calls[0] == [
        "git",
        "config",
        "--global",
        "--add",
        "safe.directory",
        str(mirror.resolve()),
    ]
    assert [
        "git",
        "checkout",
        "-B",
        "deploy-production-main",
        "refs/remotes/origin/main",
    ] in subprocess_calls


def test_sync_local_deploy_mirror_rejects_dirty_repo(tmp_path: Path) -> None:
    module = load_module()
    remote = init_bare_remote(tmp_path)
    seed, seed_sha = init_seed_repo(tmp_path, remote)
    mirror = clone_mirror(tmp_path, remote)

    commit_in_repo(seed, "README.md", "updated\n", "update main")
    push_main(seed)

    (mirror / "README.md").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="dirty working tree"):
        module.sync_local_deploy_mirror(repo_root=mirror, target_sha=seed_sha)


def test_sync_local_deploy_mirror_rejects_target_sha_mismatch(tmp_path: Path) -> None:
    module = load_module()
    remote = init_bare_remote(tmp_path)
    seed, _ = init_seed_repo(tmp_path, remote)
    mirror = clone_mirror(tmp_path, remote)

    commit_in_repo(seed, "README.md", "updated\n", "update main")
    push_main(seed)

    with pytest.raises(RuntimeError, match="origin/main does not match target sha"):
        module.sync_local_deploy_mirror(repo_root=mirror, target_sha="deadbeef")


def test_sync_local_deploy_mirror_rejects_non_fast_forward_main(tmp_path: Path) -> None:
    module = load_module()
    remote = init_bare_remote(tmp_path)
    seed, _ = init_seed_repo(tmp_path, remote)
    mirror = clone_mirror(tmp_path, remote)

    commit_in_repo(mirror, "local.txt", "local\n", "local only commit")
    commit_in_repo(seed, "remote.txt", "remote\n", "remote commit")
    target_sha = push_main(seed)

    with pytest.raises(RuntimeError, match="failed to fast-forward main"):
        module.sync_local_deploy_mirror(repo_root=mirror, target_sha=target_sha)


def test_sync_local_deploy_mirror_removes_ignored_artifacts(tmp_path: Path) -> None:
    module = load_module()
    remote = init_bare_remote(tmp_path)
    seed, _ = init_seed_repo(tmp_path, remote)
    (seed / ".gitignore").write_text("build/\n", encoding="utf-8")
    git(["add", ".gitignore"], seed)
    git(["commit", "-m", "ignore build artifacts"], seed)
    target_sha = push_main(seed)
    mirror = clone_mirror(tmp_path, remote)

    ignored_dir = mirror / "build"
    ignored_dir.mkdir()
    (ignored_dir / "stale.txt").write_text("stale\n", encoding="utf-8")

    result = module.sync_local_deploy_mirror(repo_root=mirror, target_sha=target_sha)

    assert result["ok"] is True
    assert result["head_sha"] == target_sha
    assert not ignored_dir.exists()


def test_sync_local_deploy_mirror_preserves_live_venv_but_cleans_other_ignored_artifacts(
    tmp_path: Path,
) -> None:
    module = load_module()
    remote = init_bare_remote(tmp_path)
    seed, _ = init_seed_repo(tmp_path, remote)
    (seed / ".gitignore").write_text(".venv/\nbuild/\n", encoding="utf-8")
    git(["add", ".gitignore"], seed)
    git(["commit", "-m", "ignore deploy venv and build artifacts"], seed)
    target_sha = push_main(seed)
    mirror = clone_mirror(tmp_path, remote)

    live_venv = mirror / ".venv"
    live_venv.mkdir()
    (live_venv / "pyvenv.cfg").write_text("home = C:/Python312\n", encoding="utf-8")

    ignored_dir = mirror / "build"
    ignored_dir.mkdir()
    (ignored_dir / "stale.txt").write_text("stale\n", encoding="utf-8")

    result = module.sync_local_deploy_mirror(repo_root=mirror, target_sha=target_sha)

    assert result["ok"] is True
    assert result["head_sha"] == target_sha
    assert live_venv.exists()
    assert (live_venv / "pyvenv.cfg").exists()
    assert not ignored_dir.exists()
