from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def parse_primary_worktree_path(porcelain_text: str) -> Path:
    for raw_line in porcelain_text.splitlines():
        line = raw_line.strip()
        if line.startswith("worktree "):
            return Path(line.removeprefix("worktree ").strip())
    raise ValueError("git worktree list --porcelain output missing worktree entry")


def resolve_runtime_log_host_dir(primary_worktree: Path) -> Path:
    return primary_worktree / "logs" / "runtime"


def resolve_compose_env_file(primary_worktree: Path) -> Path:
    return primary_worktree / ".env"


def load_primary_worktree_path(repo_root: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_primary_worktree_path(result.stdout)


def resolve_runtime_policy(
    repo_root: Path,
    primary_worktree: Path | None = None,
    compose_env_file: Path | None = None,
    runtime_log_dir: Path | None = None,
    *,
    prefer_clean_worktree: bool = False,
    allow_dirty_primary: bool = False,
) -> dict[str, object]:
    resolved_repo_root = repo_root.resolve()
    resolved_primary_worktree = (
        primary_worktree.resolve()
        if primary_worktree is not None
        else load_primary_worktree_path(resolved_repo_root)
    )
    resolved_compose_env = (
        compose_env_file.resolve()
        if compose_env_file is not None
        else resolve_compose_env_file(resolved_primary_worktree)
    )
    resolved_runtime_log = (
        runtime_log_dir.resolve()
        if runtime_log_dir is not None
        else resolve_runtime_log_host_dir(resolved_primary_worktree)
    )

    return {
        "repo_root": str(resolved_repo_root),
        "build_worktree": str(resolved_repo_root),
        "primary_worktree": str(resolved_primary_worktree),
        "compose_env_file": str(resolved_compose_env),
        "runtime_log_dir": str(resolved_runtime_log),
        "prefer_clean_worktree": prefer_clean_worktree,
        "allow_dirty_primary": allow_dirty_primary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Current repository root or worktree root",
    )
    parser.add_argument(
        "--kind",
        choices=(
            "runtime-log-dir",
            "compose-env-file",
            "primary-worktree",
            "runtime-policy",
        ),
        default="runtime-log-dir",
        help="Which derived path to print",
    )
    parser.add_argument(
        "--primary-worktree",
        type=Path,
        help="Explicit primary worktree path.",
    )
    parser.add_argument(
        "--compose-env-file",
        type=Path,
        help="Explicit compose env file path.",
    )
    parser.add_argument(
        "--runtime-log-dir",
        type=Path,
        help="Explicit runtime log host directory.",
    )
    parser.add_argument(
        "--prefer-clean-worktree",
        action="store_true",
        help="Prefer using the current clean worktree as the build root.",
    )
    parser.add_argument(
        "--allow-dirty-primary",
        action="store_true",
        help="Allow the primary worktree to stay dirty when env/log paths are reused.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = resolve_runtime_policy(
        repo_root=args.repo_root,
        primary_worktree=args.primary_worktree,
        compose_env_file=args.compose_env_file,
        runtime_log_dir=args.runtime_log_dir,
        prefer_clean_worktree=args.prefer_clean_worktree,
        allow_dirty_primary=args.allow_dirty_primary,
    )
    if args.kind == "primary-worktree":
        print(policy["primary_worktree"])
    elif args.kind == "compose-env-file":
        print(policy["compose_env_file"])
    elif args.kind == "runtime-policy":
        print(json.dumps(policy, ensure_ascii=False, indent=2))
    else:
        print(policy["runtime_log_dir"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
