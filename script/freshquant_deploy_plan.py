from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import cast

SURFACE_ORDER = (
    "api",
    "web",
    "dagster",
    "qa",
    "tradingagents",
    "symphony",
    "market_data",
    "guardian",
    "position_management",
    "tpsl",
    "order_management",
)

SURFACE_ALIASES = {
    "api": "api",
    "apiserver": "api",
    "rear": "api",
    "web": "web",
    "webui": "web",
    "fqwebui": "web",
    "dagster": "dagster",
    "qa": "qa",
    "qawebserver": "qa",
    "tradingagents": "tradingagents",
    "tradingagents-cn": "tradingagents",
    "symphony": "symphony",
    "market_data": "market_data",
    "market-data": "market_data",
    "guardian": "guardian",
    "signal": "guardian",
    "strategy": "guardian",
    "position_management": "position_management",
    "position-management": "position_management",
    "tpsl": "tpsl",
    "order_management": "order_management",
    "order-management": "order_management",
}

DOCKER_SERVICE_MAP = {
    "api": ["fq_apiserver"],
    "web": ["fq_webui"],
    "dagster": ["fq_dagster_webserver", "fq_dagster_daemon"],
    "qa": ["fq_qawebserver"],
    "tradingagents": ["ta_backend", "ta_frontend"],
}

HOST_SURFACE_PROGRAMS = {
    "market_data": [
        "fqnext_realtime_xtdata_producer",
        "fqnext_realtime_xtdata_consumer",
        "fqnext_xtdata_adj_refresh_worker",
    ],
    "guardian": ["fqnext_guardian_event"],
    "position_management": ["fqnext_position_management_worker"],
    "tpsl": ["fqnext_tpsl_worker"],
    "order_management": [
        "fqnext_xtquant_broker",
        "fqnext_credit_subjects_worker",
    ],
}

HEALTH_CHECK_MAP = {
    "api": [
        "http://127.0.0.1:15000/api/runtime/components",
        "http://127.0.0.1:15000/api/runtime/health/summary",
        "http://127.0.0.1:15000/api/gantt/plates?provider=xgb",
    ],
    "web": [
        "http://127.0.0.1:18080/",
        "http://127.0.0.1:18080/gantt/shouban30",
        "http://127.0.0.1:18080/runtime-observability",
    ],
    "tradingagents": [
        "http://127.0.0.1:13000/api/health",
        "http://127.0.0.1:13080/health",
    ],
    "symphony": [
        "http://127.0.0.1:40123/api/v1/state",
    ],
}

VERIFICATION_MARKER_MAP = {
    "api": ["runtime-components", "health-summary"],
    "web": ["runtime-observability"],
    "dagster": ["dagster-ui"],
    "qa": ["qa-health"],
    "tradingagents": ["api-health", "frontend-health"],
    "symphony": ["http://127.0.0.1:40123/api/v1/state"],
    "market_data": ["xt-producer-heartbeat"],
    "guardian": ["guardian-event-worker"],
    "position_management": ["position-management-worker"],
    "tpsl": ["tpsl-tick-listener"],
    "order_management": ["xtquant-broker", "credit-subjects-worker"],
}


@dataclass(frozen=True)
class PathRule:
    label: str
    surfaces: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def matches(self, normalized_path: str) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class PrefixRule(PathRule):
    prefix: str = ""

    def matches(self, normalized_path: str) -> bool:
        return normalized_path.startswith(self.prefix)


@dataclass(frozen=True)
class ExactRule(PathRule):
    exact_path: str = ""

    def matches(self, normalized_path: str) -> bool:
        return normalized_path == self.exact_path


PATH_RULES: tuple[PathRule, ...] = (
    PrefixRule(
        label="freshquant-rear",
        prefix="freshquant/rear/",
        surfaces=("api",),
    ),
    PrefixRule(
        label="order-management",
        prefix="freshquant/order_management/",
        surfaces=("api", "order_management"),
    ),
    PrefixRule(
        label="position-management",
        prefix="freshquant/position_management/",
        surfaces=("position_management",),
    ),
    PrefixRule(
        label="tpsl",
        prefix="freshquant/tpsl/",
        surfaces=("tpsl",),
    ),
    PrefixRule(
        label="market-data",
        prefix="freshquant/market_data/",
        surfaces=("market_data",),
        notes=("必要时重新 prewarm XTData consumer。",),
    ),
    PrefixRule(
        label="guardian",
        prefix="freshquant/strategy/",
        surfaces=("guardian",),
    ),
    PrefixRule(
        label="guardian-signal",
        prefix="freshquant/signal/",
        surfaces=("guardian",),
    ),
    PrefixRule(
        label="quantaxis",
        prefix="sunflower/QUANTAXIS/",
        surfaces=("qa", "guardian"),
        notes=("QUANTAXIS 变更通常同时影响 QAWebServer 和宿主机策略链。",),
    ),
    PrefixRule(
        label="gantt-readmodel",
        prefix="freshquant/data/gantt",
        surfaces=("api",),
        notes=("Gantt/Shouban30 读模型改动后按数据状态评估是否补跑 Dagster。",),
    ),
    ExactRule(
        label="shouban30-pool-service",
        exact_path="freshquant/shouban30_pool_service.py",
        surfaces=("api",),
        notes=("Shouban30 pool 改动后按数据状态评估是否补跑 Dagster。",),
    ),
    PrefixRule(
        label="webui",
        prefix="morningglory/fqwebui/",
        surfaces=("web",),
    ),
    PrefixRule(
        label="dagster",
        prefix="morningglory/fqdagster/",
        surfaces=("dagster",),
    ),
    PrefixRule(
        label="dagster-config",
        prefix="morningglory/fqdagsterconfig/",
        surfaces=("dagster",),
    ),
    PrefixRule(
        label="tradingagents",
        prefix="third_party/tradingagents-cn/",
        surfaces=("tradingagents",),
    ),
    PrefixRule(
        label="runtime-symphony",
        prefix="runtime/symphony/",
        surfaces=("symphony",),
    ),
)


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").strip()


def normalize_surface(value: str) -> str:
    normalized = value.strip().lower().replace("\\", "/")
    normalized = normalized.replace("/", "_")
    if normalized in SURFACE_ALIASES:
        return SURFACE_ALIASES[normalized]
    raise ValueError(f"Unknown deployment surface: {value}")


def ordered_surfaces(surfaces: set[str]) -> list[str]:
    return [surface for surface in SURFACE_ORDER if surface in surfaces]


def unique_in_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def load_changed_paths_from_git(
    repo_root: Path,
    base_sha: str | None,
    head_sha: str | None,
) -> list[str]:
    if not base_sha or not head_sha:
        return []

    result = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--name-only", base_sha, head_sha],
        check=True,
        capture_output=True,
        text=True,
    )
    return unique_in_order(
        [
            normalize_path(line)
            for line in result.stdout.splitlines()
            if normalize_path(line)
        ]
    )


def resolve_surfaces_from_paths(
    changed_paths: list[str],
) -> tuple[list[str], list[str]]:
    surfaces: set[str] = set()
    notes: list[str] = []

    for raw_path in changed_paths:
        path = normalize_path(raw_path)
        for rule in PATH_RULES:
            if rule.matches(path):
                surfaces.update(rule.surfaces)
                notes.extend(rule.notes)

    return ordered_surfaces(surfaces), unique_in_order(notes)


def build_deploy_plan(
    changed_paths: list[str] | None = None,
    explicit_surfaces: list[str] | None = None,
    *,
    repo_root: Path | None = None,
    base_sha: str | None = None,
    head_sha: str | None = None,
    issue_number: str | None = None,
    merge_commit: str | None = None,
) -> dict[str, object]:
    changed_paths = changed_paths or []
    explicit_surfaces = explicit_surfaces or []
    repo_root = (repo_root or Path(__file__).resolve().parent.parent).resolve()

    try:
        git_changed_paths = load_changed_paths_from_git(
            repo_root=repo_root,
            base_sha=base_sha,
            head_sha=head_sha,
        )
    except subprocess.CalledProcessError:
        if changed_paths:
            git_changed_paths = []
        else:
            raise
    normalized_changed_paths = unique_in_order(
        [normalize_path(path) for path in changed_paths] + git_changed_paths
    )

    surfaces_from_paths, notes = resolve_surfaces_from_paths(normalized_changed_paths)
    surfaces = set(surfaces_from_paths)
    for value in explicit_surfaces:
        surfaces.add(normalize_surface(value))

    ordered = ordered_surfaces(surfaces)
    docker_services = unique_in_order(
        [
            service
            for surface in ordered
            for service in DOCKER_SERVICE_MAP.get(surface, [])
        ]
    )
    host_surfaces = [surface for surface in ordered if surface in HOST_SURFACE_PROGRAMS]
    host_programs = unique_in_order(
        [
            program
            for surface in host_surfaces
            for program in HOST_SURFACE_PROGRAMS[surface]
        ]
    )
    health_checks = unique_in_order(
        [url for surface in ordered for url in HEALTH_CHECK_MAP.get(surface, [])]
    )
    verification_markers = {
        surface: VERIFICATION_MARKER_MAP.get(surface, [])
        for surface in ordered
        if VERIFICATION_MARKER_MAP.get(surface)
    }

    pre_deploy_steps: list[dict[str, object]] = []
    if ordered:
        pre_deploy_steps.append(
            {
                "kind": "runtime_baseline",
                "summary": "实际 deploy 前先采 runtime ops baseline。",
            }
        )
    if "symphony" in ordered:
        pre_deploy_steps.append(
            {
                "kind": "symphony_sync_restart",
                "summary": (
                    "若命中 runtime/symphony/**，先执行 "
                    "sync_freshquant_symphony_service.ps1，再通过管理员桥接重启 orchestrator。"
                ),
            }
        )
    if host_surfaces:
        pre_deploy_steps.append(
            {
                "kind": "host_supervisor_ensure",
                "summary": (
                    "确保 fqnext-supervisord service 处于 Running；"
                    "若 service 不可用，则按需触发 fqnext-supervisord-restart 管理员桥接。"
                ),
            }
        )

    docker_command = (
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "script/docker_parallel_compose.ps1",
            "up",
            "-d",
            "--build",
            *docker_services,
        ]
        if docker_services
        else []
    )
    host_command = (
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "script/fqnext_host_runtime_ctl.ps1",
            "-Mode",
            "EnsureServiceAndRestartSurfaces",
            "-DeploymentSurface",
            ",".join(host_surfaces),
            "-BridgeIfServiceUnavailable",
        ]
        if host_surfaces
        else []
    )
    cleanup_targets = {
        "issue_number": issue_number,
        "merge_commit": merge_commit,
        "remote_branch_hints": unique_in_order(
            [item for item in (f"issue-{issue_number}", f"gh-{issue_number}") if issue_number]
        ),
        "workspace_hints": unique_in_order(
            [item for item in (f"issue-{issue_number}", f"gh-{issue_number}") if issue_number]
        ),
        "artifact_prefixes": unique_in_order(
            [
                item
                for item in (
                    f"freshquant-stewardship-{issue_number}" if issue_number else None,
                    (
                        f"freshquant-merge-{merge_commit[:7]}"
                        if merge_commit
                        else None
                    ),
                )
                if item
            ]
        ),
    }

    return {
        "repo_root": str(repo_root),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "issue_number": issue_number,
        "merge_commit": merge_commit,
        "changed_paths": normalized_changed_paths,
        "deployment_required": bool(ordered),
        "deployment_surfaces": ordered,
        "effective_release_scope": ordered,
        "docker_services": docker_services,
        "host_surfaces": host_surfaces,
        "host_programs": host_programs,
        "runtime_ops_surfaces": ordered,
        "health_check_mode": "proxyless",
        "health_checks": health_checks,
        "verification_markers": verification_markers,
        "cleanup_targets": cleanup_targets,
        "pre_deploy_steps": pre_deploy_steps,
        "docker_command": docker_command,
        "host_command": host_command,
        "notes": notes,
    }


def render_summary(plan: dict[str, object]) -> str:
    deployment_surfaces = cast(list[str], plan["deployment_surfaces"])
    docker_services = cast(list[str], plan["docker_services"])
    host_surfaces = cast(list[str], plan["host_surfaces"])
    host_programs = cast(list[str], plan["host_programs"])
    runtime_ops_surfaces = cast(list[str], plan["runtime_ops_surfaces"])
    health_checks = cast(list[str], plan["health_checks"])
    verification_markers = cast(dict[str, list[str]], plan["verification_markers"])
    cleanup_targets = cast(dict[str, object], plan["cleanup_targets"])
    pre_deploy_steps = cast(list[dict[str, object]], plan["pre_deploy_steps"])
    notes = cast(list[str], plan["notes"])

    lines = [
        "FreshQuant 部署计划",
        f"- base_sha: {plan['base_sha'] or 'none'}",
        f"- head_sha: {plan['head_sha'] or 'none'}",
        f"- issue_number: {plan['issue_number'] or 'none'}",
        f"- merge_commit: {plan['merge_commit'] or 'none'}",
        f"- deployment_required: {str(plan['deployment_required']).lower()}",
        "- deployment_surfaces: " + (", ".join(deployment_surfaces) or "none"),
        "- effective_release_scope: " + (", ".join(deployment_surfaces) or "none"),
        "- docker_services: " + (", ".join(docker_services) or "none"),
        "- host_surfaces: " + (", ".join(host_surfaces) or "none"),
        "- host_programs: " + (", ".join(host_programs) or "none"),
        "- runtime_ops_surfaces: " + (", ".join(runtime_ops_surfaces) or "none"),
        f"- health_check_mode: {plan['health_check_mode']}",
    ]

    if health_checks:
        lines.append("- health_checks:")
        lines.extend(f"  - {item}" for item in health_checks)
    if verification_markers:
        lines.append("- verification_markers:")
        for surface, markers in verification_markers.items():
            lines.append(f"  - {surface}: {', '.join(markers)}")
    lines.append("- cleanup_targets:")
    lines.extend(
        [
            "  - issue_number: " + str(cleanup_targets["issue_number"] or "none"),
            "  - merge_commit: " + str(cleanup_targets["merge_commit"] or "none"),
            "  - remote_branch_hints: "
            + (", ".join(cast(list[str], cleanup_targets["remote_branch_hints"])) or "none"),
            "  - workspace_hints: "
            + (", ".join(cast(list[str], cleanup_targets["workspace_hints"])) or "none"),
            "  - artifact_prefixes: "
            + (", ".join(cast(list[str], cleanup_targets["artifact_prefixes"])) or "none"),
        ]
    )
    if pre_deploy_steps:
        lines.append("- pre_deploy_steps:")
        lines.extend(f"  - {item['summary']}" for item in pre_deploy_steps)
    if notes:
        lines.append("- notes:")
        lines.extend(f"  - {item}" for item in notes)

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build FreshQuant deployment plan")
    parser.add_argument(
        "--changed-path",
        action="append",
        default=[],
        help="Changed path relative to repo root; repeat for multiple paths.",
    )
    parser.add_argument(
        "--deployment-surface",
        action="append",
        default=[],
        help="Explicit deployment surface; repeat for multiple surfaces.",
    )
    parser.add_argument("--base-sha", help="Optional git diff base SHA.")
    parser.add_argument("--head-sha", help="Optional git diff head SHA.")
    parser.add_argument("--issue-number", help="Source issue number.")
    parser.add_argument("--merge-commit", help="Merge commit SHA.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repository root used for git diff resolution.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "summary"),
        default="json",
        help="Output format.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    plan = build_deploy_plan(
        changed_paths=args.changed_path,
        explicit_surfaces=args.deployment_surface,
        repo_root=args.repo_root,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
        issue_number=args.issue_number,
        merge_commit=args.merge_commit,
    )
    if args.format == "summary":
        print(render_summary(plan))
    else:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
