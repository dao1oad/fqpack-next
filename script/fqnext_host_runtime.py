from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import subprocess
import sys
import time
import xmlrpc.client
from pathlib import Path
from typing import Any, cast

DEFAULT_CONFIG_PATH = Path("D:/fqpack/config/supervisord.fqnext.conf")
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_SETTLE_SECONDS = 3.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_RECOVERY_ATTEMPTS = 1
DEPENDENCY_PROBE_TIMEOUT_SECONDS = 60.0
STDERR_TAIL_CHARS = 2000
FAKE_START_VERIFY_WINDOW_S = 3.0
FAKE_START_VERIFY_POLL_S = 0.5
TRANSITIONAL_STATES = {"STARTING", "STOPPING"}
RETRYABLE_START_STATES = {"EXITED", "FATAL", "BACKOFF", "STARTING"}
TIMEOUT_FLOOR_COMMANDS = {"stop-surfaces", "restart-surfaces", "wait-settled"}

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
        "fqnext_xtdata_qfq_worker",
    ],
    "guardian": ["fqnext_guardian_event"],
    "position_management": ["fqnext_xt_account_sync_worker"],
    "tpsl": ["fqnext_tpsl_worker"],
    "order_management": [
        "fqnext_xtquant_broker",
        "fqnext_xt_account_sync_worker",
        "fqnext_xt_auto_repay_worker",
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


PROGRAM_COMMAND_MARKERS = {
    "fqnext_realtime_xtdata_producer": "market_data.xtdata.market_producer",
    "fqnext_realtime_xtdata_consumer": "market_data.xtdata.strategy_consumer",
    "fqnext_xtdata_adj_refresh_worker": "market_data.xtdata.adj_refresh_worker",
    "fqnext_xtdata_qfq_worker": "market_data.xtdata.qfq_worker",
    "fqnext_guardian_event": "signal.astock.job.monitor_stock_zh_a_min",
    "fqnext_xt_account_sync_worker": "xt_account_sync.worker",
    "fqnext_tpsl_worker": "tpsl.tick_listener",
    "fqnext_xtquant_broker": "fqxtrade.xtquant.broker",
    "fqnext_xt_auto_repay_worker": "xt_auto_repay.worker",
}


def list_matching_python_pids(marker: str) -> list[int]:
    """List Windows python.exe pids whose command line contains marker."""

    if os.name != "nt" or not marker:
        return []
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:  # pragma: no cover - best-effort probe
        return []
    try:
        payload = json.loads(result.stdout or "[]")
    except Exception:
        return []
    entries = payload if isinstance(payload, list) else [payload]
    pids: list[int] = []
    for entry in entries:
        command_line = str(entry.get("CommandLine") or "")
        if marker not in command_line:
            continue
        try:
            pid = int(entry.get("ProcessId") or 0)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            pids.append(pid)
    return sorted(set(pids))


def clear_program_processes(marker: str, *, timeout_seconds: float = 15.0) -> None:
    """Terminate every live python process matching marker and wait for exit.

    The venv ``.venv/Scripts/python.exe`` is a shim that spawns the real
    interpreter as a child process.  ``supervisor.stopProcess`` only stops
    the supervisor-tracked shim pid; the real interpreter can survive as an
    orphan holding XTData / Redis / Mongo resources, making the next
    ``startProcess`` exit immediately.  Enumerating live processes by command
    line and force-killing each (with a settle wait) clears shim + orphans
    before the restart starts clean.
    """

    if os.name != "nt" or not marker:
        return
    deadline = time.time() + float(timeout_seconds)
    while time.time() < deadline:
        pids = list_matching_python_pids(marker)
        if not pids:
            return
        for pid in pids:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True,
                    timeout=15,
                )
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
        time.sleep(1.0)


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


def extract_last_state_from_wait_error(error_message: str) -> str | None:
    match = re.search(r"last state=([A-Za-z_]+)", error_message)
    if match is None:
        return None
    return match.group(1).upper()


def restart_programs(
    server: xmlrpc.client.ServerProxy,
    programs: list[str],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    recovery_attempts: int = DEFAULT_RECOVERY_ATTEMPTS,
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
                clear_program_processes(
                    PROGRAM_COMMAND_MARKERS.get(program, program),
                    timeout_seconds=min(timeout_seconds, 15.0),
                )

            after: dict[str, object] | None = None
            last_error: RuntimeError | None = None
            for attempt in range(2):
                pre_start = get_process_info(server, program)
                server.supervisor.startProcess(program, False)
                # P3-C：快速识别"假启动"——supervisord-go 状态机卡死时
                # startProcess 返回 True 但从未真正 spawn 新进程（pid/start 不更新）。
                # 不再傻等 RUNNING 超时，几秒内判死并走服务级自愈。
                if detect_fake_start(server, program, before=pre_start):
                    last_error = RuntimeError(
                        f"FAKE_START_DETECTED: {program} startProcess returned True "
                        "but supervisor never spawned a new process (state machine wedged)"
                    )
                    break
                try:
                    after = wait_for_state(
                        server, program, "RUNNING", timeout_seconds=timeout_seconds
                    )
                    break
                except RuntimeError as exc:
                    last_error = exc
                    settled = get_process_info(server, program)
                    latest_state = str(settled.get("statename", "")).upper()
                    retry_state = (
                        extract_last_state_from_wait_error(str(exc)) or latest_state
                    )
                    if attempt >= 1 or retry_state not in RETRYABLE_START_STATES:
                        break
                    # P3-A：第 1 次失败且状态可重试时，先跑依赖就绪探测再重试，
                    # 避免"依赖未就绪即反复拉起"耗尽预算。
                    if not probe_dependencies(
                        timeout_seconds=DEPENDENCY_PROBE_TIMEOUT_SECONDS
                    ):
                        print(
                            f"dependency readiness probe failed before retrying "
                            f"{program}; still retrying",
                            file=sys.stderr,
                        )

            if after is None:
                latest = get_process_info(server, program)
                latest_state = str(latest.get("statename", "")).upper()
                error_message = (
                    str(last_error)
                    if last_error is not None
                    else f"Program {program} did not reach RUNNING after retry"
                )
                stderr_tail = program_stderr_tail(server, program)
                if stderr_tail:
                    error_message = f"{error_message}\nstderr_tail={stderr_tail[-STDERR_TAIL_CHARS:]}"
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
        settle_attempts = max(0, int(recovery_attempts)) + 1
        for settle_attempt in range(settle_attempts):
            try:
                settled_infos = wait_for_programs_settled(
                    server,
                    programs,
                    timeout_seconds=timeout_seconds,
                )
            except RuntimeError as exc:
                settled_infos = None
                settle_error = str(exc)
            if settled_infos is not None and all(
                str(info.get("statename", "")).upper() == "RUNNING"
                for info in settled_infos.values()
            ):
                settle_error = None
                break
            if settle_attempt >= settle_attempts - 1:
                break
            current_infos = (
                settled_infos
                if settled_infos is not None
                else {
                    program: get_process_info(server, program) for program in programs
                }
            )
            for program in programs:
                if (
                    str(current_infos.get(program, {}).get("statename", "")).upper()
                    != "RUNNING"
                ):
                    try:
                        server.supervisor.startProcess(program, False)
                    except Exception:
                        pass
            settled_infos = None

    if settled_infos is None:
        settled_infos = {
            program: get_process_info(server, program) for program in programs
        }

    details: list[dict[str, object]] = []
    unresolved = False
    for program in programs:
        latest = settled_infos.get(program) or get_process_info(server, program)
        result_entry = result_lookup[program]
        result_entry["after_state"] = latest.get("statename")
        result_entry["pid"] = latest.get("pid")
        final_state = str(latest.get("statename", "")).upper()
        if final_state != "RUNNING":
            unresolved = True
        else:
            errors.pop(program, None)

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


def detect_fake_start(
    server: xmlrpc.client.ServerProxy,
    program: str,
    *,
    before: dict[str, object] | None = None,
    window_seconds: float = FAKE_START_VERIFY_WINDOW_S,
    poll_interval_seconds: float = FAKE_START_VERIFY_POLL_S,
) -> bool:
    """startProcess 后短窗口内验证 supervisor 是否真正动作。

    判据（任一满足即"有动作"，返回 False）：
    - 进程 pid 变化且 > 0（新进程已出现）
    - supervisor 记录的 start 时间戳更新（spawn 被记录）

    窗口内始终无动作 → 判定"假启动"，返回 True。必须在 startProcess 之前
    捕获 ``before`` 基线，否则正常启动也会被误判。
    """
    before = before if before is not None else get_process_info(server, program)
    before_pid = _coerce_int(before.get("pid"))
    before_start = _coerce_int(before.get("start"))
    deadline = time.time() + float(window_seconds)
    while time.time() < deadline:
        info = get_process_info(server, program)
        pid = _coerce_int(info.get("pid"))
        start_ts = _coerce_int(info.get("start"))
        if pid > 0 and pid != before_pid:
            return False
        if start_ts > 0 and start_ts != before_start:
            return False
        time.sleep(float(poll_interval_seconds))
    return True


def probe_dependencies(
    timeout_seconds: float = DEPENDENCY_PROBE_TIMEOUT_SECONDS,
) -> bool:
    """运行应用级依赖就绪探测（script/ci/wait_for_deploy_dependencies.py）。

    探测不可用/失败返回 False（不阻塞重启流程，仅作为重试前的等待窗口）。
    """
    script = Path(__file__).resolve().parent / "ci" / "wait_for_deploy_dependencies.py"
    if not script.exists():
        return False
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(script),
                "--timeout-seconds",
                str(max(float(timeout_seconds), 1.0)),
            ],
            capture_output=True,
            text=True,
            timeout=max(float(timeout_seconds) + 30.0, 60.0),
        )
        if proc.returncode != 0:
            return False
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        if not lines:
            return False
        payload = json.loads(lines[-1])
        return bool(payload.get("ok") and payload.get("ready"))
    except Exception:
        return False


def program_stderr_tail(
    server: xmlrpc.client.ServerProxy,
    program: str,
    max_chars: int = STDERR_TAIL_CHARS,
) -> str:
    """通过 supervisor RPC 取 stderr 尾部，用于失败归因（依赖类 vs 程序自身故障）。"""
    try:
        result = cast(
            tuple[Any, Any, str, Any],
            server.supervisor.tailProcessStderrLog(program, 0, max_chars),
        )
        _offset, _length, text, _overflow = result
        return str(text or "").strip()
    except Exception:
        return ""


def stop_programs(
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
                after = wait_for_state(
                    server, program, "STOPPED", timeout_seconds=timeout_seconds
                )
                result_entry["after_state"] = after.get("statename")
                result_entry["pid"] = after.get("pid")
            else:
                result_entry["after_state"] = before.get("statename")
                result_entry["pid"] = before.get("pid")
        except Exception as exc:
            latest = get_process_info(server, program)
            errors[program] = str(exc)
            result_entry["after_state"] = latest.get("statename")
            result_entry["pid"] = latest.get("pid")

        results.append(result_entry)
        result_lookup[program] = result_entry

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
        settled_infos = {
            program: get_process_info(server, program) for program in programs
        }

    details: list[dict[str, object]] = []
    unresolved = bool(errors)
    for program in programs:
        latest = settled_infos.get(program) or get_process_info(server, program)
        result_entry = result_lookup[program]
        result_entry["after_state"] = latest.get("statename")
        result_entry["pid"] = latest.get("pid")
        final_state = str(latest.get("statename", "")).upper()
        if final_state not in {"STOPPED", "EXITED", "FATAL"}:
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
            "Programs failed to stop cleanly: "
            + json.dumps(details, ensure_ascii=False)
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

    stop_parser = subparsers.add_parser("stop-surfaces")
    stop_parser.add_argument("--surface", action="append", required=True)
    stop_parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
    )

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

    if args.command == "stop-surfaces":
        payload = {
            "rpc_url": rpc_url,
            "surfaces": surfaces,
            "programs": stop_programs(
                server,
                programs,
                timeout_seconds=effective_timeout_seconds,
            ),
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
