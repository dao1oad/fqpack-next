from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def run_git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def ensure_git_repo(repo_root: Path) -> None:
    if not (repo_root / ".git").exists():
        raise RuntimeError(f"deploy mirror is not a git repository: {repo_root}")


def ensure_safe_directory(repo_root: Path) -> None:
    subprocess.run(
        ["git", "config", "--global", "--add", "safe.directory", str(repo_root)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )


def ensure_clean_worktree(repo_root: Path) -> None:
    status = run_git(repo_root, "status", "--porcelain")
    if status:
        raise RuntimeError(f"deploy mirror has a dirty working tree: {repo_root}")


def clean_ignored_artifacts(repo_root: Path) -> None:
    subprocess.run(
        ["git", "clean", "-ffdX"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )


def current_head_sha(repo_root: Path) -> str:
    return run_git(repo_root, "rev-parse", "HEAD")


def fetch_origin_main(repo_root: Path, *, remote_url: str | None, branch: str) -> str:
    if remote_url:
        fetch_args = [
            "git",
            "fetch",
            remote_url,
            f"refs/heads/{branch}:refs/remotes/origin/{branch}",
        ]
    else:
        fetch_args = ["git", "fetch", "origin", branch]
    subprocess.run(
        fetch_args,
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return run_git(repo_root, "rev-parse", f"refs/remotes/origin/{branch}")


def local_branch_exists(repo_root: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def checkout_local_branch(repo_root: Path, *, branch: str, remote_branch: str) -> None:
    if local_branch_exists(repo_root, branch):
        args = ["git", "checkout", branch]
    else:
        args = ["git", "checkout", "-B", branch, f"refs/remotes/origin/{remote_branch}"]
    subprocess.run(
        args,
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )


def fast_forward_branch(repo_root: Path, *, remote_branch: str) -> None:
    result = subprocess.run(
        ["git", "merge", "--ff-only", f"refs/remotes/origin/{remote_branch}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"failed to fast-forward {remote_branch}: "
            + ((result.stderr or result.stdout).strip() or "unknown git merge error")
        )


def sync_local_deploy_mirror(
    *,
    repo_root: Path,
    target_sha: str,
    remote_url: str | None = None,
    branch: str = "main",
    checkout_branch: str | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    ensure_git_repo(repo_root)
    ensure_safe_directory(repo_root)
    clean_ignored_artifacts(repo_root)
    ensure_clean_worktree(repo_root)

    resolved_checkout_branch = checkout_branch or branch
    before_sha = current_head_sha(repo_root)
    origin_main_sha = fetch_origin_main(repo_root, remote_url=remote_url, branch=branch)
    if origin_main_sha != target_sha:
        raise RuntimeError(
            f"origin/main does not match target sha: origin/main={origin_main_sha} target={target_sha}"
        )

    checkout_local_branch(
        repo_root, branch=resolved_checkout_branch, remote_branch=branch
    )
    fast_forward_branch(repo_root, remote_branch=branch)

    head_sha = current_head_sha(repo_root)
    if head_sha != target_sha:
        raise RuntimeError(
            f"deploy mirror head does not match target sha after sync: head={head_sha} target={target_sha}"
        )

    return {
        "ok": True,
        "repo_root": str(repo_root),
        "before_sha": before_sha,
        "origin_main_sha": origin_main_sha,
        "head_sha": head_sha,
        "target_sha": target_sha,
        "checkout_branch": resolved_checkout_branch,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize the local production deploy mirror to a target main sha."
    )
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--remote-url")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--checkout-branch")
    parser.add_argument("--format", choices=("json", "summary"), default="json")
    return parser


def render_summary(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "local deploy mirror sync",
            f"ok: {str(result['ok']).lower()}",
            f"repo_root: {result['repo_root']}",
            f"before_sha: {result['before_sha']}",
            f"head_sha: {result['head_sha']}",
            f"target_sha: {result['target_sha']}",
            f"checkout_branch: {result['checkout_branch']}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = sync_local_deploy_mirror(
            repo_root=Path(args.repo_root),
            target_sha=args.target_sha,
            remote_url=args.remote_url,
            branch=args.branch,
            checkout_branch=args.checkout_branch,
        )
    except Exception as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        return 1

    if args.format == "summary":
        print(render_summary(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
