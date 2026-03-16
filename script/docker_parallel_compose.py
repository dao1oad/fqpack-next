from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

LABEL_KEY = "io.freshquant.git_sha"


def is_supported_up_build(args: list[str]) -> bool:
    return bool(args) and args[0] == "up" and "-d" in args


def extract_target_services(args: list[str], all_services: list[str]) -> list[str]:
    if not args:
        return []
    services = [item for item in args[1:] if item and not item.startswith("-")]
    return services or list(all_services)


def rewrite_compose_args_for_cached_images(
    args: list[str],
    all_services: list[str],
    service_images: dict[str, str],
    image_revisions: dict[str, str],
    current_revision: str,
) -> list[str]:
    if not is_supported_up_build(args):
        return list(args)
    if not current_revision:
        return list(args)

    for service in extract_target_services(args, all_services):
        image = service_images.get(service)
        if not image:
            return list(args)
        if image_revisions.get(image) != current_revision:
            return list(args)

    rewritten = ["--no-build" if item == "--build" else item for item in args]
    if "--no-build" in rewritten:
        return rewritten

    insert_at = 1
    while insert_at < len(rewritten) and rewritten[insert_at].startswith("-"):
        insert_at += 1
    rewritten.insert(insert_at, "--no-build")
    return rewritten


def run_capture(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def load_current_revision(repo_root: Path) -> str:
    result = run_capture(["git", "-C", str(repo_root), "rev-parse", "HEAD"])
    return result.stdout.strip()


def load_compose_service_images(compose_file: Path) -> tuple[list[str], dict[str, str]]:
    result = run_capture(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "config",
            "--format",
            "json",
        ]
    )
    payload = json.loads(result.stdout)
    services = payload.get("services", {})
    service_names = list(services.keys())
    service_images = {
        name: config.get("image", "")
        for name, config in services.items()
        if config.get("image")
    }
    return service_names, service_images


def load_image_revisions(images: list[str]) -> dict[str, str]:
    revisions: dict[str, str] = {}
    for image in images:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            continue
        payload = json.loads(result.stdout)
        if not payload:
            continue
        labels = payload[0].get("Config", {}).get("Labels", {}) or {}
        revision = labels.get(LABEL_KEY)
        if revision:
            revisions[image] = revision
    return revisions


def compute_rewrite_result(
    repo_root: Path,
    compose_file: Path,
    compose_args: list[str],
) -> dict[str, object]:
    current_revision = load_current_revision(repo_root)
    all_services, service_images = load_compose_service_images(compose_file)
    target_services = extract_target_services(compose_args, all_services)
    images = sorted({service_images.get(service, "") for service in target_services if service_images.get(service)})
    image_revisions = load_image_revisions(images)
    rewritten = rewrite_compose_args_for_cached_images(
        args=compose_args,
        all_services=all_services,
        service_images=service_images,
        image_revisions=image_revisions,
        current_revision=current_revision,
    )
    skipped = rewritten != compose_args
    reason = (
        "all target images already match current HEAD"
        if skipped
        else "build required or cache metadata unavailable"
    )
    return {
        "compose_args": rewritten,
        "skip_build": skipped,
        "reason": reason,
        "current_revision": current_revision,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    parser.add_argument(
        "--compose-file",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "docker" / "compose.parallel.yaml",
    )
    parser.add_argument("--compose-arg", action="append", default=[])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = compute_rewrite_result(
        repo_root=args.repo_root.resolve(),
        compose_file=args.compose_file.resolve(),
        compose_args=[str(item) for item in args.compose_arg],
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
