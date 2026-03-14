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
    return subprocess.run(
        command, capture_output=True, text=True, check=False, cwd=REPO_ROOT
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
        [{"Name": "fq-symphony-orchestrator", "Status": "Running"}],
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
    assert process_entries["market_data_producer"]["running"] is True
    assert process_entries["position_management_worker"]["running"] is True
    assert process_entries["guardian_monitor"]["running"] is False


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
                "services": [
                    {"name": "fq-symphony-orchestrator", "status": "Running"}
                ],
                "processes": [
                    {"id": "market_data_producer", "running": True},
                    {"id": "market_data_consumer", "running": False},
                    {"id": "guardian_monitor", "running": False},
                    {"id": "position_management_worker", "running": True},
                    {"id": "tpsl_tick_listener", "running": False},
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
        [{"Name": "fq-symphony-orchestrator", "Status": "Stopped"}],
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
        "api,market_data,position_management,symphony",
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
    assert any(
        "fq-symphony-orchestrator" in failure for failure in payload["failures"]
    )
    assert any("market_data_producer" in failure for failure in payload["failures"])
    assert any("market_data_consumer" in failure for failure in payload["failures"])
    assert any(
        "position_management_worker" in failure for failure in payload["failures"]
    )
    assert any("guardian_monitor" in warning for warning in payload["warnings"])


def test_verify_passes_when_required_runtime_state_is_restored(tmp_path: Path) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json",
        {
            "baseline": {
                "docker": [],
                "services": [
                    {"name": "fq-symphony-orchestrator", "status": "Running"}
                ],
                "processes": [
                    {"id": "market_data_producer", "running": True},
                    {"id": "market_data_consumer", "running": False},
                    {"id": "guardian_monitor", "running": False},
                    {"id": "position_management_worker", "running": False},
                    {"id": "tpsl_tick_listener", "running": False},
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
        [{"Name": "fq-symphony-orchestrator", "Status": "Running"}],
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
        "api,web,market_data,symphony",
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
