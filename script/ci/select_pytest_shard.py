#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def list_test_files(test_root: str | Path = "freshquant/tests") -> list[str]:
    root = Path(test_root)
    return sorted(path.as_posix() for path in root.glob("test_*.py"))


def select_shard(
    test_files: list[str], shard_index: int, shard_count: int
) -> list[str]:
    if shard_count <= 0:
        raise ValueError("shard_count must be greater than 0")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index must be within [0, shard_count)")
    normalized = sorted(dict.fromkeys(test_files))
    return [
        test_file
        for position, test_file in enumerate(normalized)
        if position % shard_count == shard_index
    ]


def write_github_output(path: str, selected: list[str]) -> None:
    payload = [
        "selected_json<<__FQ_EOF__",
        json.dumps(selected, ensure_ascii=False),
        "__FQ_EOF__",
        "pytest_args<<__FQ_EOF__",
        " ".join(selected),
        "__FQ_EOF__",
        "selected_count<<__FQ_EOF__",
        str(len(selected)),
        "__FQ_EOF__",
    ]
    Path(path).write_text("\n".join(payload) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Select a deterministic pytest shard")
    parser.add_argument("--test-root", default="freshquant/tests")
    parser.add_argument("--test-list-json")
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--github-output")
    parser.add_argument("--format", choices=("json", "args"), default="json")
    args = parser.parse_args()

    if args.test_list_json:
        test_files = json.loads(Path(args.test_list_json).read_text(encoding="utf-8"))
    else:
        test_files = list_test_files(args.test_root)

    selected = select_shard(test_files, args.shard_index, args.shard_count)

    if args.github_output:
        write_github_output(args.github_output, selected)

    if args.format == "args":
        print(" ".join(selected))
    else:
        print(json.dumps({"selected": selected}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
