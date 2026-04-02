from __future__ import annotations

import argparse
import configparser
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

DEFAULT_CONFIG_PATH = Path(r"D:\fqpack\config\supervisord.fqnext.conf")
DEFAULT_EXPECTED_REPO_ROOT = Path(
    r"D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production"
)
MODULE_NAMES = (
    "freshquant",
    "fqxtrade.xtquant.broker",
    "fqxtrade.xtquant.puppet",
    "QUANTAXIS",
)
PROGRAM_NAMES = (
    "fqnext_realtime_xtdata_producer",
    "fqnext_realtime_xtdata_consumer",
    "fqnext_guardian_event",
    "fqnext_xt_account_sync_worker",
    "fqnext_tpsl_worker",
    "fqnext_xtquant_broker",
    "fqnext_xtdata_adj_refresh_worker",
)


class CaseConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def _to_posix(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _normalize_path(path: str | Path | None) -> str:
    if path is None:
        return ""
    return _to_posix(path).rstrip("/").casefold()


def _is_within(path: str | None, root: Path) -> bool:
    normalized_path = _normalize_path(path)
    normalized_root = _normalize_path(root)
    return normalized_path == normalized_root or normalized_path.startswith(
        normalized_root + "/"
    )


def build_supervisor_config(repo_root: Path) -> str:
    root = _to_posix(repo_root)
    python_executable = f"{root}/.venv/Scripts/python.exe"
    path_value = f"{root}/.venv;{root}/.venv/Scripts;C:/Windows/System32"
    python_path_value = (
        f"{root};{root}/morningglory/fqxtrade;{root}/sunflower/QUANTAXIS"
    )
    return f"""[supervisord]
; FreshQuant 当前宿主机 Python 口径：formal deploy mirror .venv
; 如仓库路径不同，请同步调整下面的 PATH、PYTHONPATH 和 command
logfile=D:/fqdata/log/supervisord_fqnext.log
logfile_maxbytes=50MB
logfile_backups=10
loglevel=error
pidfile=D:/fqdata/supervisord_fqnext.pid
identifier=fqnext

[program-default]
directory={root}
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
stderr_logfile_maxbytes=50MB
stderr_logfile_backups=10
autorestart=true
startretries=10
envFiles=D:/fqpack/config/envs.conf
environment=PATH={path_value},PYTHONPATH={python_path_value}

[inet_http_server]
port=127.0.0.1:10011

[program:fqnext_realtime_xtdata_producer]
command={python_executable} -m freshquant.market_data.xtdata.market_producer
directory={root}
stdout_logfile=D:/fqdata/log/fqnext_realtime_xtdata_producer.log
stderr_logfile=D:/fqdata/log/fqnext_realtime_xtdata_producer_err.log
autostart=true
autorestart=true
startsecs=5

[program:fqnext_realtime_xtdata_consumer]
command={python_executable} -m freshquant.market_data.xtdata.strategy_consumer --prewarm --max-bars 20000
directory={root}
stdout_logfile=D:/fqdata/log/fqnext_realtime_xtdata_consumer.log
stderr_logfile=D:/fqdata/log/fqnext_realtime_xtdata_consumer_err.log
autostart=true
autorestart=true
startsecs=5

[program:fqnext_guardian_event]
command={python_executable} -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event
directory={root}
stdout_logfile=D:/fqdata/log/fqnext_guardian_event.log
stderr_logfile=D:/fqdata/log/fqnext_guardian_event_err.log
autostart=true
autorestart=true
startsecs=5

[program:fqnext_xt_account_sync_worker]
command={python_executable} -m freshquant.xt_account_sync.worker --interval 15
directory={root}
stdout_logfile=D:/fqdata/log/fqnext_xt_account_sync_worker.log
stderr_logfile=D:/fqdata/log/fqnext_xt_account_sync_worker_err.log
autostart=true
autorestart=true
startsecs=5

[program:fqnext_tpsl_worker]
command={python_executable} -m freshquant.tpsl.tick_listener
directory={root}
stdout_logfile=D:/fqdata/log/fqnext_tpsl_worker.log
stderr_logfile=D:/fqdata/log/fqnext_tpsl_worker_err.log
autostart=true
autorestart=true
startsecs=5

[program:fqnext_xtquant_broker]
command={python_executable} -m fqxtrade.xtquant.broker
directory={root}
stdout_logfile=D:/fqdata/log/fqnext_xtquant_broker.log
stderr_logfile=D:/fqdata/log/fqnext_xtquant_broker_err.log
autostart=true
autorestart=true
startsecs=5

[program:fqnext_xtdata_adj_refresh_worker]
command={python_executable} -m freshquant.market_data.xtdata.adj_refresh_worker
directory={root}
stdout_logfile=D:/fqdata/log/fqnext_xtdata_adj_refresh_worker.log
stderr_logfile=D:/fqdata/log/fqnext_xtdata_adj_refresh_worker_err.log
autostart=true
autorestart=true
startsecs=5

[group:fqnext_reference_data]
programs=fqnext_xtdata_adj_refresh_worker

[group:fqnext_trading_chain]
programs=fqnext_realtime_xtdata_producer,fqnext_realtime_xtdata_consumer,fqnext_guardian_event,fqnext_xt_account_sync_worker,fqnext_tpsl_worker,fqnext_xtquant_broker

[supervisorctl]
serverurl=http://127.0.0.1:10011
"""


def parse_config(config_path: Path) -> configparser.ConfigParser:
    parser = CaseConfigParser()
    parser.read_string(config_path.read_text(encoding="utf-8-sig"))
    return parser


def parse_environment(environment_value: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in environment_value.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def parse_env_file(env_file_path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    if not env_file_path.exists():
        return parsed
    for raw_line in env_file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def parse_env_files(config_path: Path, env_files_value: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in env_files_value.replace(",", ";").split(";"):
        raw_path = item.strip().strip('"').strip("'")
        if not raw_path:
            continue
        env_file_path = Path(raw_path)
        if not env_file_path.is_absolute():
            env_file_path = config_path.parent / env_file_path
        parsed.update(parse_env_file(env_file_path))
    return parsed


def collect_import_sources(config_path: Path) -> dict[str, dict[str, str | None]]:
    parser = parse_config(config_path)
    repo_root = Path(parser["program-default"]["directory"])
    python_executable = (
        parser["program:fqnext_xtquant_broker"]["command"].split(" -m ", 1)[0].strip()
    )
    environment = parse_environment(
        parser["program-default"].get("environment", fallback="")
    )
    environment.update(
        parse_env_files(
            config_path,
            parser["program-default"].get("envFiles", fallback=""),
        )
    )
    child_env = os.environ.copy()
    child_env.update(environment)
    child_env["PYTHONNOUSERSITE"] = "1"
    payload = json.dumps(list(MODULE_NAMES), ensure_ascii=False)
    python_snippet = "\n".join(
        [
            "import importlib",
            "import json",
            f"modules = json.loads({payload!r})",
            "result = {}",
            "for name in modules:",
            "    try:",
            "        module = importlib.import_module(name)",
            "        result[name] = {'path': getattr(module, '__file__', None), 'error': None}",
            "    except Exception as exc:",
            "        result[name] = {'path': None, 'error': str(exc)}",
            "print(json.dumps(result, ensure_ascii=False))",
        ]
    )
    command = [
        python_executable,
        "-c",
        python_snippet,
    ]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=child_env,
    )
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout).strip() or (
            f"subprocess exited with {completed.returncode}"
        )
        return {name: {"path": None, "error": error} for name in MODULE_NAMES}
    return json.loads(completed.stdout)


def inspect_supervisor_config(
    config_path: Path,
    expected_repo_root: Path = DEFAULT_EXPECTED_REPO_ROOT,
    import_inspector: Callable[[Path], dict[str, dict[str, str | None]]] | None = None,
) -> dict[str, Any]:
    parser = parse_config(config_path)
    expected_root = expected_repo_root
    expected_root_posix = _to_posix(expected_root)
    expected_python = f"{expected_root_posix}/.venv/Scripts/python.exe"
    failures: list[str] = []
    warnings: list[str] = []

    configured_repo_root = parser["program-default"].get("directory", "").strip()
    if _normalize_path(configured_repo_root) != _normalize_path(expected_root):
        failures.append(
            "supervisor config repo_root drifted: "
            f"expected={expected_root_posix} actual={configured_repo_root}"
        )

    environment = parse_environment(
        parser["program-default"].get("environment", fallback="")
    )
    path_value = environment.get("PATH", "")
    python_path_value = environment.get("PYTHONPATH", "")
    if not path_value.startswith(
        f"{expected_root_posix}/.venv;{expected_root_posix}/.venv/Scripts;"
    ):
        failures.append(
            f"supervisor config PATH drifted from deploy mirror: {path_value}"
        )
    expected_python_path_value = (
        f"{expected_root_posix};"
        f"{expected_root_posix}/morningglory/fqxtrade;"
        f"{expected_root_posix}/sunflower/QUANTAXIS"
    )
    if python_path_value != expected_python_path_value:
        failures.append(
            "supervisor config PYTHONPATH drifted from deploy mirror: "
            f"{python_path_value}"
        )

    program_directories: dict[str, str] = {}
    program_python_executables: dict[str, str] = {}
    for program_name in PROGRAM_NAMES:
        section_name = f"program:{program_name}"
        directory = parser[section_name].get("directory", "").strip()
        command = parser[section_name].get("command", "").strip()
        python_executable = command.split(" -m ", 1)[0].strip() if command else ""
        program_directories[program_name] = directory
        program_python_executables[program_name] = python_executable
        if _normalize_path(directory) != _normalize_path(expected_root):
            failures.append(f"program directory drifted: {program_name} -> {directory}")
        if _normalize_path(python_executable) != _normalize_path(expected_python):
            failures.append(
                f"program python drifted: {program_name} -> {python_executable}"
            )

    inspector = import_inspector or collect_import_sources
    import_sources = inspector(config_path)
    for module_name, payload in import_sources.items():
        module_path = payload.get("path")
        module_error = payload.get("error")
        if module_error:
            failures.append(
                f"import source check failed: {module_name}; {module_error}"
            )
            continue
        if not module_path:
            failures.append(f"import source missing: {module_name}")
            continue
        if not _is_within(module_path, expected_root):
            failures.append(
                f"import source drifted outside deploy mirror: {module_name} -> {module_path}"
            )
        if "site-packages" in _normalize_path(module_path):
            failures.append(
                f"import source drifted to site-packages: {module_name} -> {module_path}"
            )

    return {
        "ok": not failures,
        "config_path": str(config_path),
        "expected_repo_root": expected_root_posix,
        "configured_repo_root": configured_repo_root,
        "expected_python_executable": expected_python,
        "configured_python_executables": program_python_executables,
        "program_directories": program_directories,
        "warnings": warnings,
        "failures": failures,
        "import_sources": import_sources,
    }


def write_supervisor_config(repo_root: Path, output_path: Path) -> dict[str, Any]:
    content = build_supervisor_config(repo_root)
    previous = output_path.read_text(encoding="utf-8") if output_path.exists() else None
    changed = previous != content
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if changed:
        output_path.write_text(content, encoding="utf-8")
    return {
        "ok": True,
        "changed": changed,
        "output_path": str(output_path),
        "repo_root": _to_posix(repo_root),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render and validate FreshQuant host supervisor config."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    render_parser = subparsers.add_parser("render")
    render_parser.add_argument(
        "--repo-root", type=Path, default=DEFAULT_EXPECTED_REPO_ROOT
    )

    write_parser = subparsers.add_parser("write")
    write_parser.add_argument("--repo-root", type=Path, required=True)
    write_parser.add_argument("--output-path", type=Path, default=DEFAULT_CONFIG_PATH)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--config-path", type=Path, default=DEFAULT_CONFIG_PATH)
    inspect_parser.add_argument(
        "--expected-repo-root",
        type=Path,
        default=DEFAULT_EXPECTED_REPO_ROOT,
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "render":
        print(build_supervisor_config(args.repo_root), end="")
        return 0
    if args.command == "write":
        payload = write_supervisor_config(args.repo_root, args.output_path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "inspect":
        payload = inspect_supervisor_config(args.config_path, args.expected_repo_root)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["ok"] else 1
    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
