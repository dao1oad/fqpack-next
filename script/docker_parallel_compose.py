from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

LABEL_KEY = "io.freshquant.git_sha"
DEFAULT_GHCR_NAMESPACE = os.environ.get("FQ_GHCR_NAMESPACE", "ghcr.io/dao1oad")
REMOTE_CACHE_ENV = "FQ_ENABLE_REMOTE_CACHE_PULL"

SERVICE_IMAGE_ENV_VARS = {
    "fq_apiserver": "FQNEXT_REAR_IMAGE",
    "fq_tdxhq": "FQNEXT_REAR_IMAGE",
    "fq_dagster_webserver": "FQNEXT_REAR_IMAGE",
    "fq_dagster_daemon": "FQNEXT_REAR_IMAGE",
    "fq_qawebserver": "FQNEXT_REAR_IMAGE",
    "fq_webui": "FQNEXT_WEBUI_IMAGE",
    "ta_backend": "FQNEXT_TA_BACKEND_IMAGE",
    "ta_frontend": "FQNEXT_TA_FRONTEND_IMAGE",
}

SERVICE_REGISTRY_PACKAGES = {
    "fq_apiserver": "fqnext-rear",
    "fq_tdxhq": "fqnext-rear",
    "fq_dagster_webserver": "fqnext-rear",
    "fq_dagster_daemon": "fqnext-rear",
    "fq_qawebserver": "fqnext-rear",
    "fq_webui": "fqnext-webui",
    "ta_backend": "fqnext-ta-backend",
    "ta_frontend": "fqnext-ta-frontend",
}

SHARED_REAR_BUILD_INPUT_PREFIXES = (
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
)

GLOBAL_BUILD_INPUT_PREFIXES = (
    "docker/compose.parallel.yaml",
    "script/docker_parallel_compose.py",
    "script/docker_parallel_compose.ps1",
)

SERVICE_BUILD_INPUT_PREFIXES = {
    "fq_apiserver": SHARED_REAR_BUILD_INPUT_PREFIXES,
    "fq_tdxhq": SHARED_REAR_BUILD_INPUT_PREFIXES,
    "fq_dagster_webserver": SHARED_REAR_BUILD_INPUT_PREFIXES,
    "fq_dagster_daemon": SHARED_REAR_BUILD_INPUT_PREFIXES,
    "fq_qawebserver": SHARED_REAR_BUILD_INPUT_PREFIXES,
    "fq_webui": (
        "docker/Dockerfile.web",
        "morningglory/fqwebui/",
    ),
    "ta_backend": (
        "third_party/tradingagents-cn/Dockerfile.backend",
        "third_party/tradingagents-cn/",
    ),
    "ta_frontend": (
        "third_party/tradingagents-cn/Dockerfile.frontend",
        "third_party/tradingagents-cn/",
    ),
}


def env_flag(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


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


def load_dirty_paths(repo_root: Path) -> list[str]:
    result = run_capture(
        ["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=all"]
    )
    dirty_paths: list[str] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        dirty_paths.append(normalize_path(path))
    return dirty_paths


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


def load_local_image_revisions(images: list[str]) -> dict[str, str]:
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


def load_remote_image_revisions(images: list[str]) -> dict[str, str]:
    revisions: dict[str, str] = {}
    for image in images:
        result = subprocess.run(
            ["docker", "manifest", "inspect", image],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            continue
        if ":" in image:
            revisions[image] = image.rsplit(":", 1)[1]
    return revisions


def build_registry_service_images(current_revision: str) -> dict[str, str]:
    return {
        service: f"{DEFAULT_GHCR_NAMESPACE}/{package}:{current_revision}"
        for service, package in SERVICE_REGISTRY_PACKAGES.items()
    }


def build_image_overrides(
    target_services: list[str],
    service_images: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    overrides: dict[str, str] = {}
    pull_images: list[str] = []

    for service in target_services:
        env_name = SERVICE_IMAGE_ENV_VARS.get(service)
        image = service_images.get(service)
        if not env_name or not image:
            continue
        overrides[env_name] = image
        if image not in pull_images:
            pull_images.append(image)

    return overrides, pull_images


def dirty_paths_affect_target_services(
    dirty_paths: list[str],
    target_services: list[str],
) -> bool:
    if not dirty_paths:
        return False

    prefixes = list(GLOBAL_BUILD_INPUT_PREFIXES)
    for service in target_services:
        service_prefixes = SERVICE_BUILD_INPUT_PREFIXES.get(service)
        if service_prefixes is None:
            return True
        prefixes.extend(service_prefixes)

    for path in dirty_paths:
        if any(path_matches_prefix(path, prefix) for prefix in prefixes):
            return True

    return False


def compute_rewrite_result(
    repo_root: Path,
    compose_file: Path,
    compose_args: list[str],
) -> dict[str, object]:
    current_revision = load_current_revision(repo_root)
    all_services, service_images = load_compose_service_images(compose_file)
    target_services = extract_target_services(compose_args, all_services)

    local_images = sorted(
        {
            service_images.get(service, "")
            for service in target_services
            if service_images.get(service)
        }
    )
    local_image_revisions = load_local_image_revisions(local_images)

    registry_service_images = build_registry_service_images(current_revision)
    remote_images = sorted(
        {
            registry_service_images.get(service, "")
            for service in target_services
            if registry_service_images.get(service)
        }
    )
    remote_image_revisions = load_remote_image_revisions(remote_images)

    dirty_paths = load_dirty_paths(repo_root)
    dirty_affects_target = dirty_paths_affect_target_services(
        dirty_paths, target_services
    )
    force_local_build = env_flag("FQ_DOCKER_FORCE_LOCAL_BUILD")
    enable_remote_cache_pull = env_flag(REMOTE_CACHE_ENV)

    mode = "build_required"
    rewritten = list(compose_args)
    image_overrides: dict[str, str] = {}
    pull_images: list[str] = []

    if not dirty_affects_target and not force_local_build:
        if enable_remote_cache_pull:
            remote_rewritten = rewrite_compose_args_for_cached_images(
                args=compose_args,
                all_services=all_services,
                service_images=registry_service_images,
                image_revisions=remote_image_revisions,
                current_revision=current_revision,
            )
            if remote_rewritten != compose_args:
                mode = "remote_cached"
                rewritten = remote_rewritten
                image_overrides, pull_images = build_image_overrides(
                    target_services, registry_service_images
                )
            else:
                local_rewritten = rewrite_compose_args_for_cached_images(
                    args=compose_args,
                    all_services=all_services,
                    service_images=service_images,
                    image_revisions=local_image_revisions,
                    current_revision=current_revision,
                )
                if local_rewritten != compose_args:
                    mode = "local_cached"
                    rewritten = local_rewritten
        else:
            local_rewritten = rewrite_compose_args_for_cached_images(
                args=compose_args,
                all_services=all_services,
                service_images=service_images,
                image_revisions=local_image_revisions,
                current_revision=current_revision,
            )
            if local_rewritten != compose_args:
                mode = "local_cached"
                rewritten = local_rewritten

    skipped = rewritten != compose_args
    if mode == "remote_cached":
        reason = "matching registry images already exist for current HEAD"
    elif mode == "local_cached":
        reason = "all target local images already match current HEAD"
    elif force_local_build:
        reason = "local build forced by FQ_DOCKER_FORCE_LOCAL_BUILD"
    elif not enable_remote_cache_pull:
        reason = (
            "build required, target local cache missing or dirty inputs present; "
            f"remote cache disabled by default ({REMOTE_CACHE_ENV})"
        )
    else:
        reason = "build required, dirty paths affect target build inputs, or cache metadata unavailable"

    return {
        "compose_args": rewritten,
        "skip_build": skipped,
        "reason": reason,
        "current_revision": current_revision,
        "mode": mode,
        "dirty_paths": dirty_paths,
        "image_overrides": image_overrides,
        "pull_images": pull_images,
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
        default=Path(__file__).resolve().parent.parent
        / "docker"
        / "compose.parallel.yaml",
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
