from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from freshquant.runtime.memory import (
    MemoryRuntimeConfig,
    MongoMemoryStore,
    compile_context_pack,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path.cwd())
    parser.add_argument("--service-root", default=None)
    parser.add_argument("--issue-identifier", required=True)
    parser.add_argument("--role", required=True)
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
    output_path = compile_context_pack(
        config,
        store,
        issue_identifier=args.issue_identifier,
        role=args.role,
    )
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
