#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys

DOCS_PREFIX = "docs/current/"

DOC_REQUIRED_PREFIXES = (
    "freshquant/rear/",
    "freshquant/market_data/xtdata/",
    "freshquant/strategy/",
    "freshquant/order_management/",
    "freshquant/position_management/",
    "freshquant/tpsl/",
    "freshquant/runtime_observability/",
    "freshquant/data/gantt",
    "freshquant/data/gantt_",
    "docker/",
    "runtime/",
    "morningglory/fqwebui/src/views/",
    "morningglory/fqdagster/",
    "third_party/tradingagents-cn/",
)

DOC_REQUIRED_FILES = (
    "freshquant/cli.py",
    "freshquant/config.py",
    "README.md",
)

DOC_EXEMPT_PREFIXES = (
    ".github/",
    "script/ci/",
    "docs/",
)


def run(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def git_diff_name_only(base_ref: str, head_ref: str) -> list[str]:
    result = run(["git", "diff", "--name-only", f"{base_ref}...{head_ref}"])
    text = result.stdout.decode("utf-8", errors="replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


def any_matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CI check: current docs must be updated when system facts change."
    )
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    args = parser.parse_args()

    try:
        changed_files = git_diff_name_only(args.base_ref, args.head_ref)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr.decode("utf-8", errors="replace"))
        return 2

    if not changed_files:
        print("docs-current-guard: no changes detected; OK")
        return 0

    relevant_changed_files = [
        path
        for path in changed_files
        if not any_matches_prefix(path, DOC_EXEMPT_PREFIXES)
    ]

    requires_docs = any(
        any_matches_prefix(path, DOC_REQUIRED_PREFIXES) or path in DOC_REQUIRED_FILES
        for path in relevant_changed_files
    )
    docs_updated = any(path.startswith(DOCS_PREFIX) for path in changed_files)

    if requires_docs and not docs_updated:
        sys.stderr.write(
            "ERROR: This PR changes current system behavior/config/runtime areas "
            "but does not update docs/current/**.\n"
        )
        sys.stderr.write(
            "You must update the affected current-state documentation in the same PR.\n"
        )
        return 3

    print("docs-current-guard: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
