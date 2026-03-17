#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


DOCS_ONLY_PREFIXES = (
    "docs/",
    ".codex/",
)
DOCS_ONLY_FILES = {
    "README.md",
    "AGENTS.md",
}


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


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").strip()


def unique_in_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = normalize_path(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def is_docs_only_path(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized in DOCS_ONLY_FILES or normalized.startswith(DOCS_ONLY_PREFIXES)


def load_deploy_plan_module() -> Any:
    module_path = Path(__file__).resolve().parents[1] / "freshquant_deploy_plan.py"
    spec = importlib.util.spec_from_file_location("freshquant_deploy_plan", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load deploy plan module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_context(
    changed_files: list[str],
    deployment_required: bool,
    deployment_surfaces: list[str] | None = None,
    docker_services: list[str] | None = None,
    host_surfaces: list[str] | None = None,
) -> dict[str, object]:
    normalized_files = unique_in_order(changed_files)
    docs_only = bool(normalized_files) and all(
        is_docs_only_path(path) for path in normalized_files
    )

    return {
        "changed_files": normalized_files,
        "has_changes": bool(normalized_files),
        "docs_only": docs_only,
        "deployment_required": deployment_required,
        "deployment_surfaces": deployment_surfaces or [],
        "docker_services": docker_services or [],
        "host_surfaces": host_surfaces or [],
    }


def write_github_output(path: str, payload: dict[str, object]) -> None:
    lines = []
    for key, value in payload.items():
        if isinstance(value, bool):
            rendered = str(value).lower()
        else:
            rendered = json.dumps(value, ensure_ascii=False)
        lines.append(f"{key}<<__FQ_EOF__")
        lines.append(rendered)
        lines.append("__FQ_EOF__")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect FreshQuant CI context")
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--github-output")
    args = parser.parse_args()

    try:
        changed_files = git_diff_name_only(args.base_ref, args.head_ref)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr.decode("utf-8", errors="replace"))
        return 2

    deploy_plan_module = load_deploy_plan_module()
    deploy_plan = deploy_plan_module.build_deploy_plan(changed_paths=changed_files)
    context = build_context(
        changed_files=changed_files,
        deployment_required=bool(deploy_plan["deployment_required"]),
        deployment_surfaces=list(deploy_plan["deployment_surfaces"]),
        docker_services=list(deploy_plan["docker_services"]),
        host_surfaces=list(deploy_plan["host_surfaces"]),
    )

    payload = {
        "base_ref": args.base_ref,
        "changed_files_json": context["changed_files"],
        "has_changes": context["has_changes"],
        "docs_only": context["docs_only"],
        "deployment_required": context["deployment_required"],
        "deployment_surfaces_json": context["deployment_surfaces"],
        "docker_services_json": context["docker_services"],
        "host_surfaces_json": context["host_surfaces"],
    }

    if args.github_output:
        write_github_output(args.github_output, payload)

    print(json.dumps(context, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
