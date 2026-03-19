from __future__ import annotations

import argparse
import configparser
import json
import time
import xmlrpc.client
from pathlib import Path
from typing import Any, cast

DEFAULT_CONFIG_PATH = Path("D:/fqpack/config/supervisord.fqnext.conf")
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_SETTLE_SECONDS = 3.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
TRANSITIONAL_STATES = {"STARTING", "STOPPING"}
RETRYABLE_START_STATES = {"EXITED", "FATAL", "BACKOFF", "STARTING"}
TIMEOUT_FLOOR_COMMANDS = {"restart-surfaces", "wait-settled"}

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

SURFACE_MIN_TIMEOUT_SECONDS = {
    "market_data": 180.0,
    "tpsl": 90.0,
    "order_management": 120.0,
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


def resolve_effective_timeout_seconds(
    command: str,
    surfaces: list[str],
    requested_timeout_seconds: float,
) -> float:
    if command not in TIMEOUT_FLOOR_COMMANDS:
        return requested_timeout_seconds
    timeout_floor = max(
        (
            SURFACE_MIN_TIMEOUT_SECONDS.get(normalize_surface(surface), 0.0)
            for surface in surfaces
        ),
        default=0.0,
    )
    return max(requested_timeout_seconds, timeout_floor)


def build_server_proxy(rpc_url: str) -> xmlrpc.client.ServerProxy:
    return xmlrpc.client.ServerProxy(rpc_url)


def get_process_info(server: xmlrpc.client.ServerProxy, name: str) -> dict[str, object]:
    return cast(dict[str, object], cast(Any, server.supervisor.getProcessInfo(name)))


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
        current_state = str(info.get("statename", "")).upper()
        acceptable_states = {expected}
        if expected == "STOPPED":
            acceptable_states.add("EXITED")
        if current_state in acceptable_states:
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
    infos = {program: get_process_info(server, program) for program in programs}
    return build_status_entries(infos)


def build_status_entries(
    infos: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for program, info in infos.items():
        entries.append(
            {
                "name": program,
                "state": info.get("statename"),
                "pid": info.get("pid"),
                "description": info.get("description"),
            }
        )
    return entries


def _coerce_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"Expected int-compatible value, got {type(value).__name__}")


def _snapshot_signature(
    infos: dict[str, dict[str, object]],
) -> tuple[tuple[str, str, int, int, int, int], ...]:
    signature: list[tuple[str, str, int, int, int, int]] = []
    for program in sorted(infos):
        info = infos[program]
        signature.append(
            (
                program,
                str(info.get("statename", "")).upper(),
                _coerce_int(info.get("pid")),
                _coerce_int(info.get("start")),
                _coerce_int(info.get("stop")),
                _coerce_int(info.get("exitstatus")),
            )
        )
    return tuple(signature)


def wait_for_programs_settled(
    server: xmlrpc.client.ServerProxy,
    programs: list[str],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    settle_seconds: float = DEFAULT_SETTLE_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> dict[str, dict[str, object]]:
    deadline = time.time() + timeout_seconds
    last_signature: tuple[tuple[str, str, int, int, int, int], ...] | None = None
    stable_since: float | None = None
    last_infos: dict[str, dict[str, object]] | None = None

    while time.time() < deadline:
        current_infos = {
            program: get_process_info(server, program) for program in programs
        }
        last_infos = current_infos
        states = {
            program: str(info.get("statename", "")).upper()
            for program, info in current_infos.items()
        }
        now = time.time()
        if any(state in TRANSITIONAL_STATES for state in states.values()):
            last_signature = None
            stable_since = None
        else:
            signature = _snapshot_signature(current_infos)
            if signature != last_signature:
                last_signature = signature
                stable_since = now
            elif stable_since is not None and (now - stable_since) >= settle_seconds:
                return current_infos
        time.sleep(poll_interval_seconds)

    if last_infos is None:
        raise RuntimeError(
            "Programs did not return process info while waiting to settle"
        )
    raise RuntimeError(
        "Programs did not settle; last states="
        + json.dumps(
            {
                program: str(info.get("statename", "")).upper()
                for program, info in last_infos.items()
            },
            ensure_ascii=False,
        )
    )


def restart_programs(
    server: xmlrpc.client.ServerProxy,
    programs: list[str],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    result_lookup: dict[str, dict[str, object]] = {}
    errors: dict[str, str] = {}

    for program in programs:
        before = get_process_info(server, program)
        before_state = str(before.get("statename", "")).upper()
        result_entry = {
            "name": program,
            "before_state": before.get("statename"),
            "after_state": before.get("statename"),
            "pid": before.get("pid"),
        }

        try:
            if before_state == "RUNNING":
                server.supervisor.stopProcess(program, True)
                wait_for_state(
                    server, program, "STOPPED", timeout_seconds=timeout_seconds
                )

            after: dict[str, object] | None = None
            last_error: RuntimeError | None = None
            for attempt in range(2):
                server.supervisor.startProcess(program, False)
                try:
                    after = wait_for_state(
                        server, program, "RUNNING", timeout_seconds=timeout_seconds
                    )
                    break
                except RuntimeError as exc:
                    last_error = exc
                    settled = get_process_info(server, program)
                    latest_state = str(settled.get("statename", "")).upper()
                    try:
                        settled_infos = wait_for_programs_settled(
                            server,
                            [program],
                            timeout_seconds=min(timeout_seconds, 15.0),
                            settle_seconds=2.0,
                            poll_interval_seconds=1.0,
                        )
                        settled = settled_infos[program]
                        latest_state = str(settled.get("statename", "")).upper()
                    except RuntimeError:
                        pass

                    if latest_state == "RUNNING":
                        after = settled
                        break
                    if attempt >= 1 or latest_state not in RETRYABLE_START_STATES:
                        break

            if after is None:
                latest = get_process_info(server, program)
                latest_state = str(latest.get("statename", "")).upper()
                error_message = (
                    str(last_error)
                    if last_error is not None
                    else f"Program {program} did not reach RUNNING after retry"
                )
                errors[program] = error_message
                result_entry["after_state"] = latest.get("statename")
                result_entry["pid"] = latest.get("pid")
            else:
                result_entry["after_state"] = after.get("statename")
                result_entry["pid"] = after.get("pid")
        except Exception as exc:
            latest = get_process_info(server, program)
            errors[program] = str(exc)
            result_entry["after_state"] = latest.get("statename")
            result_entry["pid"] = latest.get("pid")

        results.append(result_entry)
        result_lookup[program] = result_entry

    if not errors and len(programs) == 1:
        return results

    settled_infos: dict[str, dict[str, object]] | None = None
    settle_error: str | None = None
    if len(programs) > 1 or errors:
        try:
            settled_infos = wait_for_programs_settled(
                server,
                programs,
                timeout_seconds=timeout_seconds,
            )
        except RuntimeError as exc:
            settle_error = str(exc)

    if settled_infos is None:
        settled_infos = {program: get_process_info(server, program) for program in programs}

    details: list[dict[str, object]] = []
    unresolved = bool(errors)
    for program in programs:
        latest = settled_infos.get(program) or get_process_info(server, program)
        result_entry = result_lookup[program]
        result_entry["after_state"] = latest.get("statename")
        result_entry["pid"] = latest.get("pid")
        final_state = str(latest.get("statename", "")).upper()
        if final_state != "RUNNING":
            unresolved = True

        detail: dict[str, object] = {
            "name": program,
            "before_state": result_entry["before_state"],
            "final_state": latest.get("statename"),
            "pid": latest.get("pid"),
        }
        if program in errors:
            detail["error"] = errors[program]
        details.append(detail)

    if settle_error is not None:
        unresolved = True
        details.append({"name": "__settle__", "error": settle_error})

    if unresolved:
        raise RuntimeError(
            "Programs failed to reconcile: " + json.dumps(details, ensure_ascii=False)
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
    wait_parser = subparsers.add_parser("wait-settled")
    wait_parser.add_argument("--surface", action="append", required=True)
    wait_parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    wait_parser.add_argument(
        "--settle-seconds",
        type=float,
        default=DEFAULT_SETTLE_SECONDS,
    )

    return parser


def resolve_target_programs(args: argparse.Namespace) -> tuple[list[str], list[str]]:
    raw_surfaces = list(args.surface or [])
    explicit_programs = list(getattr(args, "program", []) or [])
    if args.command == "status" and not raw_surfaces and not explicit_programs:
        raw_surfaces = list(SURFACE_ORDER)

    surfaces = ordered_surfaces(raw_surfaces)
    programs = list(explicit_programs)
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
    effective_timeout_seconds = resolve_effective_timeout_seconds(
        args.command,
        surfaces,
        float(getattr(args, "timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
    )

    if args.command == "status":
        payload = {
            "rpc_url": rpc_url,
            "surfaces": surfaces,
            "programs": collect_status(server, programs),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "wait-settled":
        infos = wait_for_programs_settled(
            server,
            programs,
            timeout_seconds=effective_timeout_seconds,
            settle_seconds=args.settle_seconds,
        )
        payload = {
            "rpc_url": rpc_url,
            "surfaces": surfaces,
            "programs": build_status_entries(infos),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    payload = {
        "rpc_url": rpc_url,
        "surfaces": surfaces,
        "programs": restart_programs(
            server,
            programs,
            timeout_seconds=effective_timeout_seconds,
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
