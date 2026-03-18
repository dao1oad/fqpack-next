#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_DURATION = 1.0


def list_test_files(test_root: str | Path = "freshquant/tests") -> list[str]:
    root = Path(test_root)
    return sorted(path.as_posix() for path in root.rglob("test_*.py"))


def select_shard(
    test_files: list[str],
    shard_index: int,
    shard_count: int,
    *,
    durations: dict[str, float] | None = None,
) -> list[str]:
    if shard_count <= 0:
        raise ValueError("shard_count must be greater than 0")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index must be within [0, shard_count)")
    normalized = sorted(dict.fromkeys(test_files))
    if not durations:
        return [
            test_file
            for position, test_file in enumerate(normalized)
            if position % shard_count == shard_index
        ]

    shard_buckets: list[list[str]] = [[] for _ in range(shard_count)]
    shard_loads: list[float] = [0.0 for _ in range(shard_count)]
    weighted_files = sorted(
        normalized,
        key=lambda test_file: (-_duration_for(test_file, durations), test_file),
    )
    for test_file in weighted_files:
        target = min(
            range(shard_count),
            key=lambda index: (shard_loads[index], len(shard_buckets[index]), index),
        )
        shard_buckets[target].append(test_file)
        shard_loads[target] += _duration_for(test_file, durations)
    return [test_file for test_file in shard_buckets[shard_index]]


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


def load_durations(path: str | Path | None) -> dict[str, float]:
    if path is None:
        return {}
    file_path = Path(path)
    if not file_path.exists():
        return {}

    raw = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}

    durations = {}
    for key, value in raw.items():
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if seconds <= 0:
            continue
        durations[str(key).replace("\\", "/")] = seconds
    return durations


def _duration_for(test_file: str, durations: dict[str, float]) -> float:
    return durations.get(test_file, DEFAULT_DURATION)


def main() -> int:
    parser = argparse.ArgumentParser(description="Select a deterministic pytest shard")
    parser.add_argument("--test-root", default="freshquant/tests")
    parser.add_argument("--test-list-json")
    parser.add_argument("--durations-json")
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--github-output")
    parser.add_argument("--format", choices=("json", "args"), default="json")
    args = parser.parse_args()

    if args.test_list_json:
        test_files = json.loads(Path(args.test_list_json).read_text(encoding="utf-8"))
    else:
        test_files = list_test_files(args.test_root)

    selected = select_shard(
        test_files,
        args.shard_index,
        args.shard_count,
        durations=load_durations(args.durations_json),
    )

    if args.github_output:
        write_github_output(args.github_output, selected)

    if args.format == "args":
        print(" ".join(selected))
    else:
        print(json.dumps({"selected": selected}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
