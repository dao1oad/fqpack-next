from __future__ import annotations

import argparse
import configparser
import json
import time
import xmlrpc.client
from pathlib import Path


DEFAULT_CONFIG_PATH = Path("D:/fqpack/config/supervisord.fqnext.conf")
DEFAULT_TIMEOUT_SECONDS = 30.0

SURFACE_ORDER = (
    "market_data",
    "guardian",
    "position_management",
    "tpsl",
    "order_management",
)

SURFACE_ALIASES = {
    "market_data": "market_data",
    "market-data": "market_data",
    "guardian": "guardian",
    "position_management": "position_management",
    "position-management": "position_management",
    "tpsl": "tpsl",
    "order_management": "order_management",
    "order-management": "order_management",
}

SURFACE_PROGRAMS = {
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


def parse_supervisor_rpc_url(config_text: str) -> str:
    parser = configparser.ConfigParser()
    parser.read_string(config_text.lstrip("\ufeff"))
    if not parser.has_section("inet_http_server"):
        raise ValueError("inet_http_server section missing in supervisor config")
    port_value = parser.get("inet_http_server", "port", fallback="").strip()
    if not port_value:
        raise ValueError("inet_http_server.port missing in supervisor config")
    return f"http://{port_value}/RPC2"


def load_supervisor_rpc_url(config_path: Path) -> str:
    text = config_path.read_text(encoding="utf-8-sig")
    return parse_supervisor_rpc_url(text)


def normalize_surface(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in SURFACE_ALIASES:
        return SURFACE_ALIASES[normalized]
    raise ValueError(f"Unknown host deployment surface: {value}")


def resolve_surface_programs(surfaces: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for surface in surfaces:
        normalized = normalize_surface(surface)
        for program in SURFACE_PROGRAMS[normalized]:
            if program in seen:
                continue
            seen.add(program)
            ordered.append(program)
    return ordered


def ordered_surfaces(surfaces: list[str]) -> list[str]:
    selected = {normalize_surface(surface) for surface in surfaces}
    return [surface for surface in SURFACE_ORDER if surface in selected]


def build_server_proxy(rpc_url: str) -> xmlrpc.client.ServerProxy:
    return xmlrpc.client.ServerProxy(rpc_url)


def get_process_info(server: xmlrpc.client.ServerProxy, name: str) -> dict[str, object]:
    return server.supervisor.getProcessInfo(name)


def wait_for_state(
    server: xmlrpc.client.ServerProxy,
    name: str,
    expected_state: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    expected = expected_state.upper()
    last_info: dict[str, object] | None = None
    while time.time() < deadline:
        info = get_process_info(server, name)
        last_info = info
        if str(info.get("statename", "")).upper() == expected:
            return info
        time.sleep(1)
    if last_info is None:
        raise RuntimeError(f"Program {name} did not return process info while waiting")
    raise RuntimeError(
        f"Program {name} did not reach {expected_state}; last state={last_info.get('statename')}"
    )


def collect_status(
    server: xmlrpc.client.ServerProxy,
    programs: list[str],
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for program in programs:
        info = get_process_info(server, program)
        entries.append(
            {
                "name": program,
                "state": info.get("statename"),
                "pid": info.get("pid"),
                "description": info.get("description"),
            }
        )
    return entries


def restart_programs(
    server: xmlrpc.client.ServerProxy,
    programs: list[str],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for program in programs:
        before = get_process_info(server, program)
        before_state = str(before.get("statename", "")).upper()
        if before_state == "RUNNING":
            server.supervisor.stopProcess(program, True)
            wait_for_state(server, program, "STOPPED", timeout_seconds=timeout_seconds)
        server.supervisor.startProcess(program, True)
        after = wait_for_state(server, program, "RUNNING", timeout_seconds=timeout_seconds)
        results.append(
            {
                "name": program,
                "before_state": before.get("statename"),
                "after_state": after.get("statename"),
                "pid": after.get("pid"),
            }
        )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control fqnext supervisor runtime")
    parser.add_argument(
        "--config-path",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to supervisord.fqnext.conf",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--surface", action="append", default=[])
    status_parser.add_argument("--program", action="append", default=[])

    restart_parser = subparsers.add_parser("restart-surfaces")
    restart_parser.add_argument("--surface", action="append", required=True)
    restart_parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
    )

    return parser


def resolve_target_programs(args: argparse.Namespace) -> tuple[list[str], list[str]]:
    raw_surfaces = list(args.surface or [])
    if args.command == "status" and not raw_surfaces and not list(args.program or []):
        raw_surfaces = list(SURFACE_ORDER)

    surfaces = ordered_surfaces(raw_surfaces)
    programs = list(args.program or [])
    if surfaces:
        programs.extend(resolve_surface_programs(surfaces))
    programs = list(dict.fromkeys(programs))
    if not programs:
        raise ValueError("No target programs resolved")
    return surfaces, programs


def main() -> int:
    args = build_parser().parse_args()
    rpc_url = load_supervisor_rpc_url(args.config_path)
    server = build_server_proxy(rpc_url)
    surfaces, programs = resolve_target_programs(args)

    if args.command == "status":
        payload = {
            "rpc_url": rpc_url,
            "surfaces": surfaces,
            "programs": collect_status(server, programs),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    payload = {
        "rpc_url": rpc_url,
        "surfaces": surfaces,
        "programs": restart_programs(
            server,
            programs,
            timeout_seconds=args.timeout_seconds,
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
