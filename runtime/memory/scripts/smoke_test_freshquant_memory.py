from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from freshquant.runtime.memory import (
    InMemoryMemoryStore,
    MemoryRuntimeConfig,
    compile_context_pack,
    refresh_memory,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path.cwd())
    parser.add_argument("--service-root", default=None)
    parser.add_argument("--issue-identifier", default="MEMORY-SMOKE")
    parser.add_argument("--role", default="codex")
    args = parser.parse_args()

    environ = dict(os.environ)
    if args.service_root:
        # Smoke test should stay inside the caller-provided sandbox root instead of
        # writing artifacts to the default host runtime directory from bootstrap.
        environ.setdefault("FRESHQUANT_MEMORY__ARTIFACT_ROOT", "artifacts/memory")

    config = MemoryRuntimeConfig.from_settings(
        repo_root=args.repo_root,
        service_root=args.service_root,
        environ=environ,
    )
    store = InMemoryMemoryStore()
    refresh_summary = refresh_memory(
        config,
        store,
        issue_identifier=args.issue_identifier,
        issue_state="Smoke Test",
        branch_name="memory-smoke-test",
        git_status="clean",
    )
    output_path = compile_context_pack(
        config,
        store,
        issue_identifier=args.issue_identifier,
        role=args.role,
    )
    print(
        json.dumps(
            {
                "refresh_summary": refresh_summary,
                "context_pack_path": str(output_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
