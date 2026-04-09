from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "script" / "check_freshquant_runtime_post_deploy.ps1"


def test_runtime_post_deploy_check_resolves_repo_root_from_script_parent() -> None:
    script_text = SCRIPT.read_text(encoding="utf-8")

    assert "Join-Path $PSScriptRoot '..')).Path" in script_text
    assert "Join-Path $PSScriptRoot '..\\..\\..')).Path" not in script_text


def test_runtime_post_deploy_check_resolves_python_without_py_launcher() -> None:
    script_text = SCRIPT.read_text(encoding="utf-8")

    assert "Join-Path $repoRoot '.venv\\Scripts\\python.exe'" in script_text
    assert "Join-Path $repoRoot '.venv/bin/python'" in script_text
    assert "Get-Command py -ErrorAction SilentlyContinue" in script_text


def _run_powershell(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell is not available in PATH")
    assert executable is not None

    command = [
        executable,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        *args,
    ]
    completed = subprocess.run(
        command, capture_output=True, text=False, check=False, cwd=REPO_ROOT
    )
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        stdout=(completed.stdout or b"").decode("utf-8", errors="replace"),
        stderr=(completed.stderr or b"").decode("utf-8", errors="replace"),
    )


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_valid_supervisor_config_snapshot(path: Path) -> Path:
    return _write_json(
        path,
        {
            "ok": True,
            "configured_repo_root": (r"D:\fqpack\freshquant-2026.2.23"),
            "expected_repo_root": (r"D:\fqpack\freshquant-2026.2.23"),
            "failures": [],
            "warnings": [],
        },
    )


def test_capture_baseline_records_runtime_state_from_snapshots(tmp_path: Path) -> None:
    docker_path = _write_json(
        tmp_path / "docker.json",
        [
            {
                "Name": "fq_mongodb",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
            {
                "Name": "fq_apiserver",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
        ],
    )
    service_path = _write_json(
        tmp_path / "services.json",
        [
            {"Name": "fqnext-supervisord", "Status": "Running"},
        ],
    )
    process_path = _write_json(
        tmp_path / "processes.json",
        [
            {
                "ProcessId": 101,
                "Name": "python.exe",
                "CommandLine": "python -m freshquant.market_data.xtdata.market_producer",
            },
            {
                "ProcessId": 202,
                "Name": "python.exe",
                "CommandLine": "python -m freshquant.xt_account_sync.worker --interval 15",
            },
        ],
    )
    output_path = tmp_path / "baseline.json"

    result = _run_powershell(
        SCRIPT,
        "-Mode",
        "CaptureBaseline",
        "-OutputPath",
        str(output_path),
        "-DockerSnapshotPath",
        str(docker_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    docker_entries = {entry["name"]: entry for entry in payload["baseline"]["docker"]}
    process_entries = {entry["id"]: entry for entry in payload["baseline"]["processes"]}
    service_entries = {
        entry["name"]: entry for entry in payload["baseline"]["services"]
    }

    assert payload["mode"] == "CaptureBaseline"
    assert payload["passed"] is True
    assert docker_entries["fq_mongodb"]["exists"] is True
    assert docker_entries["fq_apiserver"]["health_status"] == "healthy"
    assert service_entries["fqnext-supervisord"]["status"] == "Running"
    assert "fq-symphony-orchestrator" not in service_entries
    assert process_entries["market_data_producer"]["running"] is True
    assert process_entries["xt_account_sync_worker"]["running"] is True
    assert process_entries["guardian_monitor"]["running"] is False


def test_capture_baseline_normalizes_compose_prefixed_container_names(
    tmp_path: Path,
) -> None:
    docker_path = _write_json(
        tmp_path / "docker-prefixed.json",
        [
            {
                "Name": "fqnext_20260223-fq_mongodb-1",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
            {
                "Name": "fqnext_20260223-fq_apiserver-1",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
        ],
    )
    service_path = _write_json(
        tmp_path / "services.json",
        [
            {"Name": "fq-symphony-orchestrator", "Status": "Running"},
            {"Name": "fqnext-supervisord", "Status": "Running"},
        ],
    )
    process_path = _write_json(tmp_path / "processes.json", [])
    output_path = tmp_path / "baseline.json"

    result = _run_powershell(
        SCRIPT,
        "-Mode",
        "CaptureBaseline",
        "-OutputPath",
        str(output_path),
        "-DockerSnapshotPath",
        str(docker_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    docker_entries = {entry["name"]: entry for entry in payload["baseline"]["docker"]}

    assert docker_entries["fq_mongodb"]["exists"] is True
    assert docker_entries["fq_mongodb"]["health_status"] == "healthy"
    assert docker_entries["fq_apiserver"]["exists"] is True
    assert docker_entries["fq_apiserver"]["health_status"] == "healthy"


def test_capture_baseline_treats_absent_live_container_as_missing_without_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker_stub_windows = tmp_path / "docker.cmd"
    docker_stub_windows.write_text(
        "\n".join(
            [
                "@echo off",
                'if "%1"=="ps" (',
                "  echo fq_mongodb",
                "  exit /b 0",
                ")",
                'if "%1"=="inspect" (',
                '  if "%2"=="fq_mongodb" (',
                '    echo [{"Name":"fq_mongodb","State":{"Status":"running","Health":{"Status":"healthy"}}}]',
                "    exit /b 0",
                "  )",
                "  exit /b 1",
                ")",
                "exit /b 1",
            ]
        ),
        encoding="utf-8",
    )
    docker_stub_unix = tmp_path / "docker"
    docker_stub_unix.write_text(
        "\n".join(
            [
                "#!/usr/bin/env sh",
                'if [ \"$1\" = \"ps\" ]; then',
                "  printf '%s\\n' fq_mongodb",
                "  exit 0",
                "fi",
                'if [ \"$1\" = \"inspect\" ]; then',
                '  if [ \"$2\" = \"fq_mongodb\" ]; then',
                "    printf '%s\\n' '[{\"Name\":\"fq_mongodb\",\"State\":{\"Status\":\"running\",\"Health\":{\"Status\":\"healthy\"}}}]'",
                "    exit 0",
                "  fi",
                "  exit 1",
                "fi",
                "exit 1",
            ]
        ),
        encoding="utf-8",
    )
    docker_stub_unix.chmod(0o755)
    service_path = _write_json(
        tmp_path / "services.json",
        [
            {"Name": "fqnext-supervisord", "Status": "Running"},
        ],
    )
    process_path = _write_json(tmp_path / "processes.json", [])
    output_path = tmp_path / "baseline.json"

    monkeypatch.setenv(
        "PATH",
        str(tmp_path) + os.pathsep + os.environ.get("PATH", ""),
    )

    result = _run_powershell(
        SCRIPT,
        "-Mode",
        "CaptureBaseline",
        "-OutputPath",
        str(output_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    docker_entries = {entry["name"]: entry for entry in payload["baseline"]["docker"]}

    assert docker_entries["fq_mongodb"]["exists"] is True
    assert docker_entries["ta_backend"]["exists"] is False
    assert docker_entries["ta_backend"]["state_status"] == "missing"


def test_verify_requires_targeted_surfaces_and_preserves_baseline_processes(
    tmp_path: Path,
) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json",
        {
            "baseline": {
                "docker": [
                    {"name": "fq_mongodb", "exists": True},
                    {"name": "fq_redis", "exists": True},
                    {"name": "fq_apiserver", "exists": True},
                ],
                "services": [{"name": "fqnext-supervisord", "status": "Running"}],
                "processes": [
                    {"id": "market_data_producer", "running": True},
                    {"id": "xtdata_adj_refresh_worker", "running": False},
                    {"id": "market_data_consumer", "running": False},
                    {"id": "guardian_monitor", "running": False},
                    {"id": "xt_account_sync_worker", "running": True},
                    {"id": "tpsl_tick_listener", "running": False},
                    {"id": "xtquant_broker", "running": False},
                ],
            }
        },
    )
    docker_path = _write_json(
        tmp_path / "docker.json",
        [
            {
                "Name": "fq_mongodb",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
            {
                "Name": "fq_redis",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
            {
                "Name": "fq_apiserver",
                "State": {"Status": "restarting", "Health": {"Status": "starting"}},
            },
        ],
    )
    service_path = _write_json(
        tmp_path / "services.json",
        [
            {"Name": "fqnext-supervisord", "Status": "Stopped"},
        ],
    )
    process_path = _write_json(
        tmp_path / "processes.json",
        [],
    )
    output_path = tmp_path / "verify.json"
    supervisor_config_path = _write_valid_supervisor_config_snapshot(
        tmp_path / "supervisor-config.json"
    )

    result = _run_powershell(
        SCRIPT,
        "-Mode",
        "Verify",
        "-BaselinePath",
        str(baseline_path),
        "-OutputPath",
        str(output_path),
        "-DeploymentSurface",
        "api,market_data,position_management,order_management",
        "-DockerSnapshotPath",
        str(docker_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
        "-SupervisorConfigSnapshotPath",
        str(supervisor_config_path),
    )

    assert result.returncode != 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["mode"] == "Verify"
    assert payload["passed"] is False
    assert any("fq_apiserver" in failure for failure in payload["failures"])
    assert any("fqnext-supervisord" in failure for failure in payload["failures"])
    assert any("market_data_producer" in failure for failure in payload["failures"])
    assert any(
        "xtdata_adj_refresh_worker" in failure for failure in payload["failures"]
    )
    assert any("market_data_consumer" in failure for failure in payload["failures"])
    assert any("xt_account_sync_worker" in failure for failure in payload["failures"])
    assert any("xtquant_broker" in failure for failure in payload["failures"])
    assert not any(
        "credit_subjects_worker" in failure for failure in payload["failures"]
    )
    assert all(
        "fq-symphony-orchestrator" not in failure for failure in payload["failures"]
    )
    assert any("guardian_monitor" in warning for warning in payload["warnings"])


def test_verify_passes_when_required_runtime_state_is_restored(tmp_path: Path) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json",
        {
            "baseline": {
                "docker": [],
                "services": [{"name": "fqnext-supervisord", "status": "Running"}],
                "processes": [
                    {"id": "market_data_producer", "running": True},
                    {"id": "xtdata_adj_refresh_worker", "running": False},
                    {"id": "market_data_consumer", "running": False},
                    {"id": "guardian_monitor", "running": False},
                    {"id": "xt_account_sync_worker", "running": False},
                    {"id": "tpsl_tick_listener", "running": False},
                    {"id": "xtquant_broker", "running": False},
                    {"id": "xt_auto_repay_worker", "running": False},
                ],
            }
        },
    )
    docker_path = _write_json(
        tmp_path / "docker.json",
        [
            {
                "Name": "fq_mongodb",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
            {
                "Name": "fq_redis",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
            {
                "Name": "fq_apiserver",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
            {
                "Name": "fq_webui",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
        ],
    )
    service_path = _write_json(
        tmp_path / "services.json",
        [
            {"Name": "fqnext-supervisord", "Status": "Running"},
        ],
    )
    process_path = _write_json(
        tmp_path / "processes.json",
        [
            {
                "ProcessId": 401,
                "Name": "python.exe",
                "CommandLine": "python -m freshquant.market_data.xtdata.market_producer",
            },
            {
                "ProcessId": 402,
                "Name": "python.exe",
                "CommandLine": (
                    "python -m freshquant.market_data.xtdata.strategy_consumer "
                    "--prewarm"
                ),
            },
            {
                "ProcessId": 403,
                "Name": "python.exe",
                "CommandLine": "python -m freshquant.market_data.xtdata.adj_refresh_worker",
            },
            {
                "ProcessId": 404,
                "Name": "python.exe",
                "CommandLine": "python -m fqxtrade.xtquant.broker",
            },
            {
                "ProcessId": 405,
                "Name": "python.exe",
                "CommandLine": "python -m freshquant.xt_account_sync.worker",
            },
            {
                "ProcessId": 406,
                "Name": "python.exe",
                "CommandLine": "python -m freshquant.xt_auto_repay.worker",
            },
        ],
    )
    output_path = tmp_path / "verify.json"
    supervisor_config_path = _write_valid_supervisor_config_snapshot(
        tmp_path / "supervisor-config.json"
    )

    result = _run_powershell(
        SCRIPT,
        "-Mode",
        "Verify",
        "-BaselinePath",
        str(baseline_path),
        "-OutputPath",
        str(output_path),
        "-DeploymentSurface",
        "api,web,market_data,order_management",
        "-DockerSnapshotPath",
        str(docker_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
        "-SupervisorConfigSnapshotPath",
        str(supervisor_config_path),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["passed"] is True
    assert payload["failures"] == []
    assert any(
        check["name"] == "fq_apiserver" and check["passed"] is True
        for check in payload["docker_checks"]
    )
    assert any(
        check["id"] == "market_data_consumer" and check["passed"] is True
        for check in payload["process_checks"]
    )
    assert any(
        check["id"] == "xt_account_sync_worker" and check["passed"] is True
        for check in payload["process_checks"]
    )
    assert any(
        check["id"] == "xt_auto_repay_worker" and check["passed"] is True
        for check in payload["process_checks"]
    )


def test_verify_rejects_unknown_deployment_surface(tmp_path: Path) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json",
        {
            "baseline": {
                "docker": [],
                "services": [],
                "processes": [],
            }
        },
    )
    docker_path = _write_json(
        tmp_path / "docker.json",
        [
            {
                "Name": "fq_mongodb",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
            {
                "Name": "fq_redis",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
        ],
    )
    service_path = _write_json(tmp_path / "services.json", [])
    process_path = _write_json(tmp_path / "processes.json", [])
    output_path = tmp_path / "verify.json"

    result = _run_powershell(
        SCRIPT,
        "-Mode",
        "Verify",
        "-BaselinePath",
        str(baseline_path),
        "-OutputPath",
        str(output_path),
        "-DeploymentSurface",
        "api,unknown_surface",
        "-DockerSnapshotPath",
        str(docker_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
    )

    assert result.returncode != 0
    error_text = result.stderr + result.stdout
    assert "unknown_surface" in error_text
    assert "unknown deployment surface" in error_text.lower()


def test_verify_matches_xt_account_sync_worker_without_explicit_interval_flag(
    tmp_path: Path,
) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json",
        {
            "baseline": {
                "docker": [],
                "services": [{"name": "fqnext-supervisord", "status": "Running"}],
                "processes": [
                    {"id": "xt_account_sync_worker", "running": False},
                ],
            }
        },
    )
    docker_path = _write_json(
        tmp_path / "docker.json",
        [
            {
                "Name": "fq_mongodb",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
            {
                "Name": "fq_redis",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
        ],
    )
    service_path = _write_json(
        tmp_path / "services.json",
        [{"Name": "fqnext-supervisord", "Status": "Running"}],
    )
    process_path = _write_json(
        tmp_path / "processes.json",
        [
            {
                "ProcessId": 501,
                "Name": "python.exe",
                "CommandLine": "python -m freshquant.xt_account_sync.worker",
            }
        ],
    )
    output_path = tmp_path / "verify.json"
    supervisor_config_path = _write_valid_supervisor_config_snapshot(
        tmp_path / "supervisor-config.json"
    )

    result = _run_powershell(
        SCRIPT,
        "-Mode",
        "Verify",
        "-BaselinePath",
        str(baseline_path),
        "-OutputPath",
        str(output_path),
        "-DeploymentSurface",
        "position_management",
        "-DockerSnapshotPath",
        str(docker_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
        "-SupervisorConfigSnapshotPath",
        str(supervisor_config_path),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert any(
        check["id"] == "xt_account_sync_worker" and check["passed"] is True
        for check in payload["process_checks"]
    )


def test_verify_requires_fqnext_supervisord_for_host_managed_surfaces(
    tmp_path: Path,
) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json",
        {
            "baseline": {
                "docker": [],
                "services": [{"name": "fqnext-supervisord", "status": "Running"}],
                "processes": [
                    {"id": "xtquant_broker", "running": False},
                    {"id": "xt_account_sync_worker", "running": False},
                    {"id": "xt_auto_repay_worker", "running": False},
                ],
            }
        },
    )
    docker_path = _write_json(
        tmp_path / "docker.json",
        [
            {
                "Name": "fq_mongodb",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
            {
                "Name": "fq_redis",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
        ],
    )
    service_path = _write_json(
        tmp_path / "services.json",
        [{"Name": "fqnext-supervisord", "Status": "Stopped"}],
    )
    process_path = _write_json(
        tmp_path / "processes.json",
        [
            {
                "ProcessId": 601,
                "Name": "python.exe",
                "CommandLine": "python -m fqxtrade.xtquant.broker",
            },
            {
                "ProcessId": 602,
                "Name": "python.exe",
                "CommandLine": "python -m freshquant.xt_account_sync.worker",
            },
            {
                "ProcessId": 603,
                "Name": "python.exe",
                "CommandLine": "python -m freshquant.xt_auto_repay.worker",
            },
        ],
    )
    output_path = tmp_path / "verify.json"
    supervisor_config_path = _write_valid_supervisor_config_snapshot(
        tmp_path / "supervisor-config.json"
    )

    result = _run_powershell(
        SCRIPT,
        "-Mode",
        "Verify",
        "-BaselinePath",
        str(baseline_path),
        "-OutputPath",
        str(output_path),
        "-DeploymentSurface",
        "order_management",
        "-DockerSnapshotPath",
        str(docker_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
        "-SupervisorConfigSnapshotPath",
        str(supervisor_config_path),
    )

    assert result.returncode != 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert any("fqnext-supervisord" in failure for failure in payload["failures"])


def test_verify_prefers_supervisor_snapshot_for_host_managed_programs(
    tmp_path: Path,
) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json",
        {
            "baseline": {
                "docker": [],
                "services": [{"name": "fqnext-supervisord", "status": "Running"}],
                "processes": [
                    {"id": "xtquant_broker", "running": False},
                    {"id": "xt_account_sync_worker", "running": False},
                    {"id": "xt_auto_repay_worker", "running": False},
                ],
            }
        },
    )
    docker_path = _write_json(
        tmp_path / "docker.json",
        [
            {
                "Name": "fq_mongodb",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
            {
                "Name": "fq_redis",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
        ],
    )
    service_path = _write_json(
        tmp_path / "services.json",
        [{"Name": "fqnext-supervisord", "Status": "Running"}],
    )
    process_path = _write_json(
        tmp_path / "processes.json",
        [
            {"ProcessId": 701, "Name": "python.exe", "CommandLine": ""},
            {"ProcessId": 702, "Name": "python.exe", "CommandLine": ""},
        ],
    )
    supervisor_path = _write_json(
        tmp_path / "supervisor.json",
        [
            {
                "name": "fqnext_xtquant_broker",
                "statename": "RUNNING",
                "pid": 1701,
                "description": "pid 1701, uptime 0:01:00",
            },
            {
                "name": "fqnext_xt_account_sync_worker",
                "statename": "RUNNING",
                "pid": 1702,
                "description": "pid 1702, uptime 0:01:00",
            },
            {
                "name": "fqnext_xt_auto_repay_worker",
                "statename": "RUNNING",
                "pid": 1703,
                "description": "pid 1703, uptime 0:01:00",
            },
        ],
    )
    output_path = tmp_path / "verify.json"
    supervisor_config_path = _write_valid_supervisor_config_snapshot(
        tmp_path / "supervisor-config.json"
    )

    result = _run_powershell(
        SCRIPT,
        "-Mode",
        "Verify",
        "-BaselinePath",
        str(baseline_path),
        "-OutputPath",
        str(output_path),
        "-DeploymentSurface",
        "order_management",
        "-DockerSnapshotPath",
        str(docker_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
        "-SupervisorSnapshotPath",
        str(supervisor_path),
        "-SupervisorConfigSnapshotPath",
        str(supervisor_config_path),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert any(
        check["id"] == "xtquant_broker" and check["passed"] is True
        for check in payload["process_checks"]
    )
    assert any(
        check["id"] == "xt_account_sync_worker" and check["passed"] is True
        for check in payload["process_checks"]
    )
    assert any(
        check["id"] == "xt_auto_repay_worker" and check["passed"] is True
        for check in payload["process_checks"]
    )


def test_verify_fails_when_supervisor_config_still_points_to_main_runtime(
    tmp_path: Path,
) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json",
        {
            "baseline": {
                "docker": [],
                "services": [{"name": "fqnext-supervisord", "status": "Running"}],
                "processes": [
                    {"id": "xtquant_broker", "running": False},
                    {"id": "xt_account_sync_worker", "running": False},
                    {"id": "xt_auto_repay_worker", "running": False},
                ],
            }
        },
    )
    docker_path = _write_json(
        tmp_path / "docker.json",
        [
            {
                "Name": "fq_mongodb",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
            {
                "Name": "fq_redis",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
        ],
    )
    service_path = _write_json(
        tmp_path / "services.json",
        [{"Name": "fqnext-supervisord", "Status": "Running"}],
    )
    process_path = _write_json(
        tmp_path / "processes.json",
        [
            {
                "ProcessId": 801,
                "Name": "python.exe",
                "CommandLine": "python -m fqxtrade.xtquant.broker",
            },
            {
                "ProcessId": 802,
                "Name": "python.exe",
                "CommandLine": "python -m freshquant.xt_account_sync.worker",
            },
        ],
    )
    supervisor_path = _write_json(
        tmp_path / "supervisor.json",
        [
            {
                "name": "fqnext_xtquant_broker",
                "statename": "RUNNING",
                "pid": 1801,
                "description": "pid 1801, uptime 0:01:00",
            },
            {
                "name": "fqnext_xt_account_sync_worker",
                "statename": "RUNNING",
                "pid": 1802,
                "description": "pid 1802, uptime 0:01:00",
            },
            {
                "name": "fqnext_xt_auto_repay_worker",
                "statename": "RUNNING",
                "pid": 1803,
                "description": "pid 1803, uptime 0:01:00",
            },
        ],
    )
    supervisor_config_path = _write_json(
        tmp_path / "supervisor-config.json",
        {
            "ok": False,
            "configured_repo_root": (
                r"D:\fqpack\freshquant-2026.2.23\.worktrees\main-runtime"
            ),
            "expected_repo_root": (r"D:\fqpack\freshquant-2026.2.23"),
            "failures": [
                "supervisor config repo_root drifted to main-runtime",
                "import source drifted to .venv/Lib/site-packages/fqxtrade/xtquant/broker.py",
            ],
            "warnings": [],
        },
    )
    output_path = tmp_path / "verify.json"

    result = _run_powershell(
        SCRIPT,
        "-Mode",
        "Verify",
        "-BaselinePath",
        str(baseline_path),
        "-OutputPath",
        str(output_path),
        "-DeploymentSurface",
        "order_management",
        "-DockerSnapshotPath",
        str(docker_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
        "-SupervisorSnapshotPath",
        str(supervisor_path),
        "-SupervisorConfigSnapshotPath",
        str(supervisor_config_path),
    )

    assert result.returncode != 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert any("main-runtime" in failure for failure in payload["failures"])
    assert any("site-packages" in failure for failure in payload["failures"])


def test_verify_passes_when_supervisor_config_matches_deploy_mirror(
    tmp_path: Path,
) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json",
        {
            "baseline": {
                "docker": [],
                "services": [{"name": "fqnext-supervisord", "status": "Running"}],
                "processes": [
                    {"id": "xtquant_broker", "running": False},
                    {"id": "xt_account_sync_worker", "running": False},
                    {"id": "xt_auto_repay_worker", "running": False},
                ],
            }
        },
    )
    docker_path = _write_json(
        tmp_path / "docker.json",
        [
            {
                "Name": "fq_mongodb",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
            {
                "Name": "fq_redis",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
        ],
    )
    service_path = _write_json(
        tmp_path / "services.json",
        [{"Name": "fqnext-supervisord", "Status": "Running"}],
    )
    process_path = _write_json(
        tmp_path / "processes.json",
        [
            {
                "ProcessId": 901,
                "Name": "python.exe",
                "CommandLine": "python -m fqxtrade.xtquant.broker",
            },
            {
                "ProcessId": 902,
                "Name": "python.exe",
                "CommandLine": "python -m freshquant.xt_account_sync.worker",
            },
        ],
    )
    supervisor_path = _write_json(
        tmp_path / "supervisor.json",
        [
            {
                "name": "fqnext_xtquant_broker",
                "statename": "RUNNING",
                "pid": 1901,
                "description": "pid 1901, uptime 0:01:00",
            },
            {
                "name": "fqnext_xt_account_sync_worker",
                "statename": "RUNNING",
                "pid": 1902,
                "description": "pid 1902, uptime 0:01:00",
            },
            {
                "name": "fqnext_xt_auto_repay_worker",
                "statename": "RUNNING",
                "pid": 1903,
                "description": "pid 1903, uptime 0:01:00",
            },
        ],
    )
    supervisor_config_path = _write_json(
        tmp_path / "supervisor-config.json",
        {
            "ok": True,
            "configured_repo_root": (r"D:\fqpack\freshquant-2026.2.23"),
            "expected_repo_root": (r"D:\fqpack\freshquant-2026.2.23"),
            "failures": [],
            "warnings": [],
        },
    )
    output_path = tmp_path / "verify.json"

    result = _run_powershell(
        SCRIPT,
        "-Mode",
        "Verify",
        "-BaselinePath",
        str(baseline_path),
        "-OutputPath",
        str(output_path),
        "-DeploymentSurface",
        "order_management",
        "-DockerSnapshotPath",
        str(docker_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
        "-SupervisorSnapshotPath",
        str(supervisor_path),
        "-SupervisorConfigSnapshotPath",
        str(supervisor_config_path),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["failures"] == []


def test_verify_fails_when_supervisor_config_inspection_is_unavailable(
    tmp_path: Path,
) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json",
        {
            "baseline": {
                "docker": [],
                "services": [{"name": "fqnext-supervisord", "status": "Running"}],
                "processes": [
                    {"id": "xtquant_broker", "running": False},
                    {"id": "xt_account_sync_worker", "running": False},
                    {"id": "xt_auto_repay_worker", "running": False},
                ],
            }
        },
    )
    docker_path = _write_json(
        tmp_path / "docker.json",
        [
            {
                "Name": "fq_mongodb",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
            {
                "Name": "fq_redis",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            },
        ],
    )
    service_path = _write_json(
        tmp_path / "services.json",
        [{"Name": "fqnext-supervisord", "Status": "Running"}],
    )
    process_path = _write_json(
        tmp_path / "processes.json",
        [
            {
                "ProcessId": 1001,
                "Name": "python.exe",
                "CommandLine": "python -m fqxtrade.xtquant.broker",
            },
            {
                "ProcessId": 1002,
                "Name": "python.exe",
                "CommandLine": "python -m freshquant.xt_account_sync.worker",
            },
        ],
    )
    supervisor_path = _write_json(
        tmp_path / "supervisor.json",
        [
            {
                "name": "fqnext_xtquant_broker",
                "statename": "RUNNING",
                "pid": 2001,
                "description": "pid 2001, uptime 0:01:00",
            },
            {
                "name": "fqnext_xt_account_sync_worker",
                "statename": "RUNNING",
                "pid": 2002,
                "description": "pid 2002, uptime 0:01:00",
            },
            {
                "name": "fqnext_xt_auto_repay_worker",
                "statename": "RUNNING",
                "pid": 2003,
                "description": "pid 2003, uptime 0:01:00",
            },
        ],
    )
    output_path = tmp_path / "verify.json"

    result = _run_powershell(
        SCRIPT,
        "-Mode",
        "Verify",
        "-BaselinePath",
        str(baseline_path),
        "-OutputPath",
        str(output_path),
        "-DeploymentSurface",
        "order_management",
        "-DockerSnapshotPath",
        str(docker_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
        "-SupervisorSnapshotPath",
        str(supervisor_path),
    )

    assert result.returncode != 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert any("supervisor config" in failure for failure in payload["failures"])
