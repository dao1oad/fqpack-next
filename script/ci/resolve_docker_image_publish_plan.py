from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

IMAGE_DEFINITIONS = {
    "rear": {
        "image_name": "fqnext-rear",
        "context": ".",
        "dockerfile": "./docker/Dockerfile.rear",
        "build_input_prefixes": (
            "docker/Dockerfile.rear",
            ".dockerignore",
            "pyproject.toml",
            "uv.lock",
            "jupyter_server_config.json",
            "freshquant/",
            "morningglory/fqchan01/",
            "morningglory/fqchan02/",
            "morningglory/fqchan03/",
            "morningglory/fqchan04/",
            "morningglory/fqchan06/",
            "morningglory/fqcopilot/",
            "morningglory/fqdagster/",
            "morningglory/fqdagsterconfig/",
            "morningglory/fqxtrade/",
            "sunflower/xtquant/",
            "sunflower/pytdx/",
            "sunflower/backtrader/",
            "sunflower/QUANTAXIS/",
        ),
    },
    "webui": {
        "image_name": "fqnext-webui",
        "context": "./morningglory/fqwebui",
        "dockerfile": "./docker/Dockerfile.web",
        "build_input_prefixes": (
            "docker/Dockerfile.web",
            "morningglory/fqwebui/",
        ),
    },
    "ta-backend": {
        "image_name": "fqnext-ta-backend",
        "context": "./third_party/tradingagents-cn",
        "dockerfile": "./third_party/tradingagents-cn/Dockerfile.backend",
        "build_input_prefixes": (
            "third_party/tradingagents-cn/Dockerfile.backend",
            "third_party/tradingagents-cn/",
        ),
    },
    "ta-frontend": {
        "image_name": "fqnext-ta-frontend",
        "context": "./third_party/tradingagents-cn",
        "dockerfile": "./third_party/tradingagents-cn/Dockerfile.frontend",
        "build_input_prefixes": (
            "third_party/tradingagents-cn/Dockerfile.frontend",
            "third_party/tradingagents-cn/",
        ),
    },
}


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").strip()


def path_matches_prefix(path: str, prefix: str) -> bool:
    normalized_path = normalize_path(path)
    normalized_prefix = normalize_path(prefix)
    if normalized_prefix.endswith("/"):
        return normalized_path.startswith(normalized_prefix)
    return normalized_path == normalized_prefix or normalized_path.startswith(
        normalized_prefix + "/"
    )


def should_build_image(changed_paths: list[str], build_input_prefixes: tuple[str, ...]) -> bool:
    return any(
        path_matches_prefix(path, prefix)
        for path in changed_paths
        for prefix in build_input_prefixes
    )


def compute_publish_plan(
    changed_paths: list[str],
    bootstrap: bool = False,
) -> dict[str, dict[str, str | bool]]:
    plan: dict[str, dict[str, str | bool]] = {}
    for name, definition in IMAGE_DEFINITIONS.items():
        action = "build"
        if not bootstrap and not should_build_image(
            changed_paths,
            definition["build_input_prefixes"],
        ):
            action = "retag"

        plan[name] = {
            "name": name,
            "image_name": str(definition["image_name"]),
            "context": str(definition["context"]),
            "dockerfile": str(definition["dockerfile"]),
            "action": action,
        }
    return plan


def load_changed_paths(repo_root: Path, base_sha: str, head_sha: str) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "diff",
            "--name-only",
            base_sha,
            head_sha,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        normalize_path(line)
        for line in result.stdout.splitlines()
        if normalize_path(line)
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--base-sha")
    parser.add_argument("--head-sha")
    parser.add_argument("--bootstrap", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    changed_paths: list[str] = []
    if args.base_sha and args.head_sha:
        changed_paths = load_changed_paths(args.repo_root, args.base_sha, args.head_sha)

    plan = compute_publish_plan(changed_paths=changed_paths, bootstrap=args.bootstrap)
    payload = {
        "bootstrap": args.bootstrap,
        "changed_paths": changed_paths,
        "matrix": {"include": list(plan.values())},
        "plan": plan,
    }
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
