from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "runtime"
    / "symphony"
    / "scripts"
    / "check_freshquant_runtime_post_deploy.ps1"
)


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
            {"Name": "fq-symphony-orchestrator", "Status": "Running"},
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
                "CommandLine": (
                    "python -m freshquant.position_management.worker --interval 3"
                ),
            },
            {
                "ProcessId": 303,
                "Name": "python.exe",
                "CommandLine": (
                    "python -m freshquant.order_management.credit_subjects.worker"
                ),
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
    assert service_entries["fq-symphony-orchestrator"]["status"] == "Running"
    assert service_entries["fqnext-supervisord"]["status"] == "Running"
    assert process_entries["market_data_producer"]["running"] is True
    assert process_entries["position_management_worker"]["running"] is True
    assert process_entries["credit_subjects_worker"]["running"] is True
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
                "services": [{"name": "fq-symphony-orchestrator", "status": "Running"}],
                "processes": [
                    {"id": "market_data_producer", "running": True},
                    {"id": "xtdata_adj_refresh_worker", "running": False},
                    {"id": "market_data_consumer", "running": False},
                    {"id": "guardian_monitor", "running": False},
                    {"id": "position_management_worker", "running": True},
                    {"id": "tpsl_tick_listener", "running": False},
                    {"id": "xtquant_broker", "running": False},
                    {"id": "credit_subjects_worker", "running": False},
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
            {"Name": "fq-symphony-orchestrator", "Status": "Stopped"},
            {"Name": "fqnext-supervisord", "Status": "Stopped"},
        ],
    )
    process_path = _write_json(
        tmp_path / "processes.json",
        [],
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
        "api,market_data,position_management,symphony,order_management",
        "-DockerSnapshotPath",
        str(docker_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
    )

    assert result.returncode != 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["mode"] == "Verify"
    assert payload["passed"] is False
    assert any("fq_apiserver" in failure for failure in payload["failures"])
    assert any("fq-symphony-orchestrator" in failure for failure in payload["failures"])
    assert any("fqnext-supervisord" in failure for failure in payload["failures"])
    assert any("market_data_producer" in failure for failure in payload["failures"])
    assert any(
        "xtdata_adj_refresh_worker" in failure for failure in payload["failures"]
    )
    assert any("market_data_consumer" in failure for failure in payload["failures"])
    assert any(
        "position_management_worker" in failure for failure in payload["failures"]
    )
    assert any("xtquant_broker" in failure for failure in payload["failures"])
    assert any("credit_subjects_worker" in failure for failure in payload["failures"])
    assert any("guardian_monitor" in warning for warning in payload["warnings"])


def test_verify_passes_when_required_runtime_state_is_restored(tmp_path: Path) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json",
        {
            "baseline": {
                "docker": [],
                "services": [{"name": "fq-symphony-orchestrator", "status": "Running"}],
                "processes": [
                    {"id": "market_data_producer", "running": True},
                    {"id": "xtdata_adj_refresh_worker", "running": False},
                    {"id": "market_data_consumer", "running": False},
                    {"id": "guardian_monitor", "running": False},
                    {"id": "position_management_worker", "running": False},
                    {"id": "tpsl_tick_listener", "running": False},
                    {"id": "xtquant_broker", "running": False},
                    {"id": "credit_subjects_worker", "running": False},
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
            {"Name": "fq-symphony-orchestrator", "Status": "Running"},
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
                "CommandLine": (
                    "python -m freshquant.order_management.credit_subjects.worker"
                ),
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
        "api,web,market_data,symphony,order_management",
        "-DockerSnapshotPath",
        str(docker_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
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
        check["id"] == "credit_subjects_worker" and check["passed"] is True
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


def test_verify_matches_position_worker_without_explicit_interval_flag(
    tmp_path: Path,
) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json",
        {
            "baseline": {
                "docker": [],
                "services": [{"name": "fqnext-supervisord", "status": "Running"}],
                "processes": [
                    {"id": "position_management_worker", "running": False},
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
                "CommandLine": "python -m freshquant.position_management.worker",
            }
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
        "position_management",
        "-DockerSnapshotPath",
        str(docker_path),
        "-ServiceSnapshotPath",
        str(service_path),
        "-ProcessSnapshotPath",
        str(process_path),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert any(
        check["id"] == "position_management_worker" and check["passed"] is True
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
                    {"id": "credit_subjects_worker", "running": False},
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
                "CommandLine": (
                    "python -m freshquant.order_management.credit_subjects.worker"
                ),
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
    )

    assert result.returncode != 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert any("fqnext-supervisord" in failure for failure in payload["failures"])
