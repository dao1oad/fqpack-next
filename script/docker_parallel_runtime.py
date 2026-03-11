from __future__ import annotations

import argparse
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
        choices=("runtime-log-dir", "compose-env-file", "primary-worktree"),
        default="runtime-log-dir",
        help="Which derived path to print",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    primary_worktree = load_primary_worktree_path(args.repo_root.resolve())
    if args.kind == "primary-worktree":
        print(primary_worktree)
    elif args.kind == "compose-env-file":
        print(resolve_compose_env_file(primary_worktree))
    else:
        print(resolve_runtime_log_host_dir(primary_worktree))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
