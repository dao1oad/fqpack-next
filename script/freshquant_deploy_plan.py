from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

SURFACE_ORDER = (
    "api",
    "web",
    "dagster",
    "qa",
    "tradingagents",
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

DOCKER_BUILD_TARGET_MAP = {
    "api": ["fq_apiserver"],
    "web": ["fq_webui"],
    "dagster": ["fq_apiserver"],
    "qa": ["fq_apiserver"],
    "tradingagents": ["ta_backend", "ta_frontend"],
}

HOST_SURFACE_PROGRAMS = {
    "market_data": [
        "fqnext_realtime_xtdata_producer",
        "fqnext_realtime_xtdata_consumer",
        "fqnext_xtdata_adj_refresh_worker",
    ],
    "guardian": ["fqnext_guardian_event"],
    "position_management": ["fqnext_xt_account_sync_worker"],
    "tpsl": ["fqnext_tpsl_worker"],
    "order_management": [
        "fqnext_xtquant_broker",
        "fqnext_xt_account_sync_worker",
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
        "http://127.0.0.1:18080/api/stock_data?period=1d&symbol=sh512800&endDate=2025-07-10&barCount=2",
    ],
    "tradingagents": [
        "http://127.0.0.1:13000/api/health",
        "http://127.0.0.1:13080/health",
    ],
}

ALL_HOST_RUNTIME_SURFACES = (
    "market_data",
    "guardian",
    "position_management",
    "tpsl",
    "order_management",
)
FRESHQUANT_SHARED_RUNTIME_SURFACES = (
    "api",
    "dagster",
    *ALL_HOST_RUNTIME_SURFACES,
)
FRESHQUANT_MESSAGE_SURFACES = ("market_data", "guardian")
FRESHQUANT_TRADING_SURFACES = ("api", "dagster", "market_data", "guardian")
FRESHQUANT_LEGACY_CONFIG_SURFACES = ("dagster", "market_data", "guardian")
FQXTRADE_RUNTIME_SURFACES = ("order_management",)
DOCKER_PARALLEL_ALL_SURFACES = ("api", "web", "dagster", "qa", "tradingagents")
DOCKER_PARALLEL_ALL_SERVICES = (
    "fq_mongodb",
    "fq_redis",
    "fq_runtime_clickhouse",
    "fq_apiserver",
    "fq_runtime_indexer",
    "fq_tdxhq",
    "fq_dagster_webserver",
    "fq_dagster_daemon",
    "fq_qawebserver",
    "fq_webui",
    "ta_backend",
    "ta_frontend",
)
DOCKER_PARALLEL_COMPOSE_PATH = "docker/compose.parallel.yaml"


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
    ExactRule(
        label="freshquant-package-root",
        exact_path="freshquant/__init__.py",
        surfaces=FRESHQUANT_SHARED_RUNTIME_SURFACES,
        notes=(
            "`freshquant.__init__` 变更会影响 API、Dagster 与所有宿主机 `python -m freshquant...` 运行面。",
        ),
    ),
    ExactRule(
        label="freshquant-runtime-network",
        exact_path="freshquant/runtime/network.py",
        surfaces=FRESHQUANT_SHARED_RUNTIME_SURFACES,
        notes=(
            "`freshquant.runtime.network` 当前被 FreshQuant/FQXTrade 入口、钉钉通知与交易日历请求共享复用。",
        ),
    ),
    PrefixRule(
        label="freshquant-message",
        prefix="freshquant/message/",
        surfaces=FRESHQUANT_MESSAGE_SURFACES,
    ),
    PrefixRule(
        label="freshquant-trading",
        prefix="freshquant/trading/",
        surfaces=FRESHQUANT_TRADING_SURFACES,
    ),
    ExactRule(
        label="freshquant-config",
        exact_path="freshquant/config.py",
        surfaces=FRESHQUANT_LEGACY_CONFIG_SURFACES,
        notes=(
            "`freshquant.config` 仍被 market_data / guardian / dagster 链路直接引用。",
        ),
    ),
    ExactRule(
        label="freshquant-legacy-yaml",
        exact_path="freshquant/freshquant.yaml",
        surfaces=FRESHQUANT_LEGACY_CONFIG_SURFACES,
        notes=(
            "旧 `freshquant.yaml` 虽已降级，但当前仍随 `freshquant.config` 被部分宿主机链路读取。",
        ),
    ),
    PrefixRule(
        label="order-management",
        prefix="freshquant/order_management/",
        surfaces=("api", "order_management"),
    ),
    PrefixRule(
        label="xt-account-sync",
        prefix="freshquant/xt_account_sync/",
        surfaces=("position_management", "order_management"),
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
        label="etf-adj-sync",
        exact_path="freshquant/data/etf_adj_sync.py",
        surfaces=("dagster",),
        notes=("ETF 前复权 xdxr/adj 同步逻辑变更后必须重部署 Dagster。",),
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
        label="fqxtrade-runtime",
        prefix="morningglory/fqxtrade/fqxtrade/",
        surfaces=FQXTRADE_RUNTIME_SURFACES,
        notes=("vendored `fqxtrade` 改动会影响 broker / ingest 等宿主机订单链。",),
    ),
    PrefixRule(
        label="tradingagents",
        prefix="third_party/tradingagents-cn/",
        surfaces=("tradingagents",),
    ),
    ExactRule(
        label="host-runtime-ctl",
        exact_path="script/fqnext_host_runtime_ctl.ps1",
        surfaces=ALL_HOST_RUNTIME_SURFACES,
        notes=(
            "host runtime control script 变更后必须重跑全部宿主机 surfaces，确保 supervisor 配置与运行进程被重新收敛。",
        ),
    ),
    ExactRule(
        label="host-supervisor-config",
        exact_path="script/fqnext_supervisor_config.py",
        surfaces=ALL_HOST_RUNTIME_SURFACES,
        notes=(
            "supervisor config renderer / inspector 变更后必须重跑全部宿主机 surfaces，确保正式运行面切到最新 deploy mirror 口径。",
        ),
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
) -> dict[str, object]:
    changed_paths = changed_paths or []
    explicit_surfaces = explicit_surfaces or []
    normalized_changed_paths = [normalize_path(path) for path in changed_paths]
    compose_parallel_changed = DOCKER_PARALLEL_COMPOSE_PATH in normalized_changed_paths

    surfaces_from_paths, notes = resolve_surfaces_from_paths(normalized_changed_paths)
    surfaces = set(surfaces_from_paths)
    if compose_parallel_changed:
        surfaces.update(DOCKER_PARALLEL_ALL_SURFACES)
        notes.append(
            "`docker/compose.parallel.yaml` 变更会直接影响 Docker 并行环境；正式 deploy 统一重建/重启全部受管容器。"
        )
    for value in explicit_surfaces:
        surfaces.add(normalize_surface(value))

    ordered = ordered_surfaces(surfaces)
    docker_build_targets = unique_in_order(
        [
            service
            for surface in ordered
            for service in DOCKER_BUILD_TARGET_MAP.get(surface, [])
        ]
    )
    docker_up_services = unique_in_order(
        [
            service
            for surface in ordered
            for service in DOCKER_SERVICE_MAP.get(surface, [])
        ]
    )
    docker_services = unique_in_order(docker_build_targets + docker_up_services)
    if compose_parallel_changed:
        docker_services = unique_in_order(
            [*DOCKER_PARALLEL_ALL_SERVICES, *docker_services]
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

    pre_deploy_steps: list[dict[str, object]] = []
    if ordered:
        pre_deploy_steps.append(
            {
                "kind": "runtime_baseline",
                "summary": "实际 deploy 前先采 runtime ops baseline。",
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

    docker_command: list[str] = []
    if docker_services:
        docker_command = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "script/docker_parallel_compose.ps1",
            "up",
            "-d",
            "--build",
        ]
        # Web-only deploy should not bounce unchanged API/QA dependencies.
        if ordered == ["web"] and docker_services == ["fq_webui"]:
            docker_command.append("--no-deps")
        docker_command.extend(docker_services)
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

    return {
        "changed_paths": normalized_changed_paths,
        "deployment_required": bool(ordered),
        "deployment_surfaces": ordered,
        "docker_build_targets": docker_build_targets,
        "docker_up_services": docker_up_services,
        "docker_services": docker_services,
        "host_surfaces": host_surfaces,
        "host_programs": host_programs,
        "runtime_ops_surfaces": ordered,
        "health_checks": health_checks,
        "pre_deploy_steps": pre_deploy_steps,
        "docker_command": docker_command,
        "host_command": host_command,
        "notes": notes,
    }


def render_summary(plan: dict[str, object]) -> str:
    deployment_surfaces = cast(list[str], plan["deployment_surfaces"])
    docker_build_targets = cast(list[str], plan["docker_build_targets"])
    docker_up_services = cast(list[str], plan["docker_up_services"])
    docker_services = cast(list[str], plan["docker_services"])
    host_surfaces = cast(list[str], plan["host_surfaces"])
    host_programs = cast(list[str], plan["host_programs"])
    runtime_ops_surfaces = cast(list[str], plan["runtime_ops_surfaces"])
    health_checks = cast(list[str], plan["health_checks"])
    pre_deploy_steps = cast(list[dict[str, object]], plan["pre_deploy_steps"])
    notes = cast(list[str], plan["notes"])

    lines = [
        "FreshQuant 部署计划",
        f"- deployment_required: {str(plan['deployment_required']).lower()}",
        "- deployment_surfaces: " + (", ".join(deployment_surfaces) or "none"),
        "- docker_build_targets: " + (", ".join(docker_build_targets) or "none"),
        "- docker_up_services: " + (", ".join(docker_up_services) or "none"),
        "- docker_services: " + (", ".join(docker_services) or "none"),
        "- host_surfaces: " + (", ".join(host_surfaces) or "none"),
        "- host_programs: " + (", ".join(host_programs) or "none"),
        "- runtime_ops_surfaces: " + (", ".join(runtime_ops_surfaces) or "none"),
    ]

    if health_checks:
        lines.append("- health_checks:")
        lines.extend(f"  - {item}" for item in health_checks)
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
    )
    if args.format == "summary":
        print(render_summary(plan))
    else:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
