from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from freshquant.runtime.memory import (
    InMemoryMemoryStore,
    MemoryRuntimeConfig,
    MongoMemoryStore,
    bootstrap_memory_context,
)


def _git_output(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _resolve_branch_name(repo_root: Path, explicit_branch_name: str | None) -> str:
    if explicit_branch_name and explicit_branch_name.strip():
        return explicit_branch_name.strip()

    branch_name = _git_output(repo_root, "branch", "--show-current")
    return branch_name or "unknown"


def _resolve_git_status(repo_root: Path, explicit_git_status: str | None) -> str:
    if explicit_git_status and explicit_git_status.strip():
        return explicit_git_status.strip()

    status_output = _git_output(repo_root, "status", "--short")
    if not status_output:
        return "clean"
    return "; ".join(line.strip() for line in status_output.splitlines() if line.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path.cwd())
    parser.add_argument("--service-root", default=None)
    parser.add_argument("--issue-identifier", default=None)
    parser.add_argument("--issue-state", default=None)
    parser.add_argument("--branch-name", default=None)
    parser.add_argument("--git-status", default=None)
    parser.add_argument("--role", default=None)
    parser.add_argument("--in-memory", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    issue_state = (
        args.issue_state
        or os.environ.get("SYMPHONY_ISSUE_STATE")
        or os.environ.get("FRESHQUANT_ISSUE_STATE")
        or "Local Session"
    )
    branch_name = _resolve_branch_name(repo_root, args.branch_name)
    git_status = _resolve_git_status(repo_root, args.git_status)

    environ = dict(os.environ)
    if args.service_root:
        # When callers provide an explicit service root, keep bootstrap artifacts
        # under that root unless they explicitly override the artifact directory.
        environ.setdefault("FRESHQUANT_MEMORY__ARTIFACT_ROOT", "artifacts/memory")

    config = MemoryRuntimeConfig.from_settings(
        repo_root=repo_root,
        service_root=args.service_root,
        environ=environ,
    )
    if args.in_memory:
        store = InMemoryMemoryStore()
    else:
        store = MongoMemoryStore(
            host=config.mongo_host,
            port=config.mongo_port,
            db_name=config.mongo_db,
        )

    payload = bootstrap_memory_context(
        config,
        store,
        workspace_path=repo_root,
        branch_name=branch_name,
        git_status=git_status,
        issue_state=issue_state,
        role=args.role,
        issue_identifier=args.issue_identifier,
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
