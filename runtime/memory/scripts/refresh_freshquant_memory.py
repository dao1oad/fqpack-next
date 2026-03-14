from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from freshquant.runtime.memory import MemoryRuntimeConfig, MongoMemoryStore, refresh_memory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path.cwd())
    parser.add_argument("--service-root", default=None)
    parser.add_argument("--issue-identifier", required=True)
    parser.add_argument("--issue-state", default="unknown")
    parser.add_argument("--branch-name", default="unknown")
    parser.add_argument("--git-status", default="clean")
    args = parser.parse_args()

    config = MemoryRuntimeConfig.from_settings(
        repo_root=args.repo_root,
        service_root=args.service_root,
    )
    store = MongoMemoryStore(
        host=config.mongo_host,
        port=config.mongo_port,
        db_name=config.mongo_db,
    )
    summary = refresh_memory(
        config,
        store,
        issue_identifier=args.issue_identifier,
        issue_state=args.issue_state,
        branch_name=args.branch_name,
        git_status=args.git_status,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
