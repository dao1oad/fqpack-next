#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROGRESS_FILE = "docs/migration/progress.md"
BREAKING_CHANGES_FILE = "docs/migration/breaking-changes.md"

RFC_PATH_RE = re.compile(r"^docs/rfcs/(?P<num>\d{4})-[a-z0-9][a-z0-9-]*\.md$")

# Changes in these areas are considered "migration/feature/code" work and must
# update progress.
PROGRESS_REQUIRED_PREFIXES = (
    "freshquant/",
    "morningglory/",
    "ikebana/",
    "sunflower/",
    "script/",
    "docker/",
    "deps/",
)
PROGRESS_REQUIRED_FILES = (
    "pyproject.toml",
    "package.py",
    "install.py",
    "install.bat",
    "deploy.bat",
    "deploy_rear.bat",
    "deploy_web.bat",
)

# Meta changes that shouldn't require migration progress updates.
PROGRESS_EXEMPT_PREFIXES = (
    ".github/",
    "script/ci/",
)

# Touching these is *likely* to be a public-interface change; require explicit
# breaking-change documentation (even if the answer is "none").
BREAKING_REQUIRED_PREFIXES = (
    "freshquant/command/",
    "freshquant/rear/",
)
BREAKING_REQUIRED_FILES = (
    "freshquant/cli.py",
    "freshquant/__main__.py",
    "freshquant/__init__.py",
    "freshquant/config.py",
    "pyproject.toml",
)


@dataclass(frozen=True)
class Change:
    status: str  # A/M/D/R/C/...
    path: str
    path2: str | None = None


def run(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


def git_diff_name_only(base_ref: str, head_ref: str) -> list[str]:
    result = run(["git", "diff", "--name-only", f"{base_ref}...{head_ref}"])
    text = result.stdout.decode("utf-8", errors="replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


def git_diff_name_status(base_ref: str, head_ref: str) -> list[Change]:
    result = run(["git", "diff", "--name-status", "-z", f"{base_ref}...{head_ref}"])
    tokens = result.stdout.split(b"\0")

    changes: list[Change] = []
    i = 0
    while i < len(tokens):
        if not tokens[i]:
            break
        status_raw = tokens[i].decode("utf-8", errors="replace")
        status = status_raw[:1]
        i += 1
        if i >= len(tokens):
            break
        path1 = tokens[i].decode("utf-8", errors="surrogateescape")
        i += 1

        if status in {"R", "C"}:
            if i >= len(tokens):
                break
            path2 = tokens[i].decode("utf-8", errors="surrogateescape")
            i += 1
            changes.append(Change(status=status, path=path1, path2=path2))
        else:
            changes.append(Change(status=status, path=path1))

    return changes


def any_matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def load_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CI governance checks for migration/RFC discipline."
    )
    parser.add_argument(
        "--base-ref", required=True, help="Git ref/commit for base (e.g. origin/main)"
    )
    parser.add_argument(
        "--head-ref", required=True, help="Git ref/commit for head (e.g. HEAD)"
    )
    args = parser.parse_args()

    base_ref: str = args.base_ref
    head_ref: str = args.head_ref

    try:
        changed_files = git_diff_name_only(base_ref, head_ref)
        changes = git_diff_name_status(base_ref, head_ref)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(e.stderr.decode("utf-8", errors="replace"))
        return 2

    if not changed_files:
        print("governance: no changes detected; OK")
        return 0

    changed_set = set(changed_files)
    relevant_changed_files = [
        p for p in changed_files if not any_matches_prefix(p, PROGRESS_EXEMPT_PREFIXES)
    ]

    rfc_files_changed: list[str] = []
    rfc_files_added: list[str] = []
    rfc_nums_added: list[str] = []

    for ch in changes:
        # Treat renames as "changed"; only status A counts as added.
        paths = [ch.path] + ([ch.path2] if ch.path2 else [])
        for p in paths:
            if not p:
                continue
            m = RFC_PATH_RE.match(p)
            if not m:
                continue
            if p in {"docs/rfcs/0000-template.md", "docs/rfcs/README.md"}:
                continue
            if p not in rfc_files_changed:
                rfc_files_changed.append(p)
            if ch.status == "A":
                rfc_files_added.append(p)
                num = m.group("num")
                if num not in rfc_nums_added:
                    rfc_nums_added.append(num)

    requires_progress = False

    if rfc_files_changed:
        requires_progress = True

    if any(
        any_matches_prefix(p, PROGRESS_REQUIRED_PREFIXES)
        or p in PROGRESS_REQUIRED_FILES
        for p in relevant_changed_files
    ):
        requires_progress = True

    if requires_progress and PROGRESS_FILE not in changed_set:
        sys.stderr.write(
            "ERROR: This PR changes migration/code/RFC-related files but does not update "
            f"`{PROGRESS_FILE}`.\n"
            "Fix: update the progress table (status, updated date, notes) and link the RFC.\n"
        )
        sys.stderr.write("Changed files (sample):\n")
        for p in changed_files[:50]:
            sys.stderr.write(f"  - {p}\n")
        if len(changed_files) > 50:
            sys.stderr.write(f"  ... ({len(changed_files) - 50} more)\n")
        return 3

    if rfc_nums_added:
        progress_text = (
            load_text(PROGRESS_FILE)
            if PROGRESS_FILE in changed_set
            else load_text(PROGRESS_FILE)
        )
        missing: list[str] = []
        for num in rfc_nums_added:
            if not re.search(
                rf"^\|\s*{re.escape(num)}\s*\|", progress_text, flags=re.MULTILINE
            ):
                missing.append(num)
        if missing:
            sys.stderr.write(
                "ERROR: New RFC file(s) added but not registered in progress table "
                f"`{PROGRESS_FILE}`.\n"
                f"Missing RFC numbers: {', '.join(missing)}\n"
                "Fix: add a row for each RFC in the progress table.\n"
            )
            return 4

    requires_breaking = any(
        any_matches_prefix(p, BREAKING_REQUIRED_PREFIXES)
        or p in BREAKING_REQUIRED_FILES
        for p in changed_files
    )
    if requires_breaking and BREAKING_CHANGES_FILE not in changed_set:
        sys.stderr.write(
            "ERROR: This PR touches public-interface areas (CLI/API/config) but does not update "
            f"`{BREAKING_CHANGES_FILE}`.\n"
            "Fix: add an entry referencing the RFC. If there is no breaking change, "
            "add a short '无破坏性变更' entry for traceability.\n"
        )
        return 5

    print("governance: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
