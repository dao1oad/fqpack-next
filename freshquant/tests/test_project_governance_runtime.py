from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME = REPO_ROOT / "tools" / "governance.py"
ASSET_RUNTIME = (
    REPO_ROOT
    / ".agents"
    / "skills"
    / "bootstrap-project-governance"
    / "assets"
    / "project-governance"
    / "tools"
    / "governance.py"
)
BOOTSTRAP = (
    REPO_ROOT
    / ".agents"
    / "skills"
    / "bootstrap-project-governance"
    / "scripts"
    / "bootstrap_governance.py"
)


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(repo / "tools" / "governance.py"),
            *args,
            "--repo",
            str(repo),
        ],
        cwd=repo,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


@pytest.fixture
def governed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "governed-repo"
    subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(BOOTSTRAP),
            "apply",
            "--repo",
            str(repo),
            "--project-name",
            "Governance Integrity Test",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    (repo / "src").mkdir()
    (repo / "tools" / "governance.py").write_bytes(RUNTIME.read_bytes())
    (repo / "src" / "app.txt").write_text("initial\n", encoding="utf-8")
    subprocess.run(
        ["git", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    project = {
        "schemaVersion": 1,
        "projectId": "governance-integrity-test",
        "projectName": "Governance Integrity Test",
        "initializedAt": "2026-07-23T00:00:00Z",
        "outcome": "Lock required checks and preserve sealed evidence",
        "nonGoals": ["deployment"],
        "hardConstraints": ["V2 evidence remains immutable"],
        "interactionPolicy": {
            "decisionPhase": "bootstrap_only",
            "runtimeQuestions": False,
            "escalationAllowlist": [],
        },
        "agentAuthority": {
            "fixed": ["outcome", "finalAcceptance"],
            "mutable": ["soft_gates"],
        },
        "budgets": {
            "deadlineAt": None,
            "maxCheckRuns": 10,
            "maxStopContinuations": 6,
            "maxNoProgressStops": 3,
            "sameFailureLimit": 2,
        },
        "preflight": {
            "goalAndBoundariesConfirmed": True,
            "repositoryRootVerified": True,
            "credentialsAndPermissionsVerified": True,
            "externalDependenciesProbed": True,
            "fallbacksDefined": True,
            "budgetsConfirmed": True,
            "finalAcceptanceConfirmed": True,
            "hookTrustReviewed": True,
        },
        "fallbacks": [{"when": "external_unready", "action": "keep_v2_missing"}],
        "finalAcceptance": {
            "claims": [
                {
                    "id": "CLAIM-001",
                    "description": "Real gate passes",
                    "itemRef": "WI-001",
                    "gateRef": "e2e-real",
                    "level": "V2",
                    "dataMode": "real",
                }
            ]
        },
    }
    command = [sys.executable, "-c", "print('gate-output')"]
    work = {
        "schemaVersion": 1,
        "revision": 1,
        "gates": [
            {
                "id": "unit-required",
                "level": "V0",
                "dataMode": "fixture",
                "command": command,
                "commandWindows": command,
                "subjectPaths": ["src/**"],
                "timeoutSeconds": 30,
            },
            {
                "id": "e2e-real",
                "level": "V2",
                "dataMode": "real",
                "command": command,
                "commandWindows": command,
                "subjectPaths": ["src/**"],
                "timeoutSeconds": 30,
            },
        ],
        "items": [
            {
                "id": "WI-001",
                "title": "Required slice",
                "bucket": "NOW",
                "pathScopes": ["src/**"],
                "gateRefs": ["unit-required", "e2e-real"],
                "requiredForFinal": True,
                "nextCheckpoint": "Both gates pass",
            }
        ],
    }
    (repo / ".governance" / "project.json").write_text(
        json.dumps(project, indent=2) + "\n", encoding="utf-8"
    )
    (repo / ".governance" / "work.json").write_text(
        json.dumps(work, indent=2) + "\n", encoding="utf-8"
    )
    (repo / ".governance" / "events.jsonl").write_text("", encoding="utf-8")
    assert _run(repo, "ready").returncode == 0
    assert _run(repo, "start").returncode == 0
    return repo


def test_runtime_matches_bootstrap_asset() -> None:
    assert RUNTIME.read_bytes() == ASSET_RUNTIME.read_bytes()


def test_start_locks_required_gate_specs_and_item_scope(governed_repo: Path) -> None:
    work_path = governed_repo / ".governance" / "work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    work["gates"][0]["command"] = [sys.executable, "-c", "raise SystemExit(0)"]
    work["items"][0]["pathScopes"] = []
    work_path.write_text(json.dumps(work, indent=2) + "\n", encoding="utf-8")
    assert _run(governed_repo, "derive").returncode == 0

    invalid = _run(governed_repo, "validate")
    assert invalid.returncode == 1
    issues = json.loads(invalid.stdout)["issues"]
    assert any("required Gate 发生漂移：unit-required" in issue for issue in issues)
    assert any("pathScopes 被缩窄：WI-001" in issue for issue in issues)
    blocked = _run(governed_repo, "run", "--item", "WI-001", "--gate", "e2e-real")
    assert blocked.returncode == 2
    assert "治理完整性检查失败" in blocked.stderr

    restored = _run(governed_repo, "restore-work-contract")
    assert restored.returncode == 0, restored.stderr
    assert json.loads(restored.stdout)["restored"] is True
    assert _run(governed_repo, "validate").returncode == 0


def test_started_event_requires_hook_lock(governed_repo: Path) -> None:
    events_path = governed_repo / ".governance" / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    start = next(event for event in events if event["type"] == "AUTONOMY_STARTED")
    start.pop("hookLock")
    start.pop("hookLockDigest")
    events_path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
    )
    assert _run(governed_repo, "derive").returncode == 0

    invalid = _run(governed_repo, "validate")
    assert invalid.returncode == 1
    assert "缺少 hookLock" in invalid.stdout
    restarted = _run(governed_repo, "start")
    assert restarted.returncode == 1
    assert "缺少 hookLock" in restarted.stdout


def test_soft_gate_can_be_added_without_changing_locked_work(
    governed_repo: Path,
) -> None:
    work_path = governed_repo / ".governance" / "work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    work["revision"] += 1
    work["gates"].append(
        {
            "id": "optional-soft",
            "level": "V0",
            "dataMode": "fixture",
            "command": [sys.executable, "-c", "raise SystemExit(0)"],
            "subjectPaths": ["src/**"],
            "timeoutSeconds": 30,
        }
    )
    work["items"].append(
        {
            "id": "WI-OPTIONAL",
            "title": "Optional work",
            "bucket": "LATER",
            "pathScopes": ["src/**"],
            "gateRefs": ["optional-soft"],
            "requiredForFinal": False,
            "nextCheckpoint": "Optional",
        }
    )
    work_path.write_text(json.dumps(work, indent=2) + "\n", encoding="utf-8")
    assert _run(governed_repo, "derive").returncode == 0
    assert _run(governed_repo, "validate").returncode == 0


def test_tampered_result_is_rejected_by_validate_check_and_hook(
    governed_repo: Path,
) -> None:
    run = _run(governed_repo, "run", "--item", "WI-001", "--gate", "e2e-real")
    assert run.returncode == 0, run.stderr
    run_payload = json.loads(run.stdout)
    unit_run = _run(governed_repo, "run", "--item", "WI-001", "--gate", "unit-required")
    assert unit_run.returncode == 0, unit_run.stderr
    assert (
        _run(
            governed_repo, "record", "--type", "WORK_IMPLEMENTED", "--item", "WI-001"
        ).returncode
        == 0
    )
    completed = _run(governed_repo, "check", "--completion")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["runtimeState"] == "COMPLETED"

    events = [
        json.loads(line)
        for line in (governed_repo / ".governance" / "events.jsonl")
        .read_text()
        .splitlines()
    ]
    check_event = next(event for event in events if event["type"] == "CHECK_FINISHED")
    assert check_event["resultSha256"]
    assert check_event["gateSpecDigest"] == run_payload["gateSpecDigest"]
    run_dir = governed_repo / ".governance" / "runs" / run_payload["runId"]
    assert (run_dir / "stdout.log").is_file()
    assert (run_dir / "stderr.log").is_file()

    result_path = run_dir / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["outcome"] = "pass" if result["outcome"] != "pass" else "fail"
    result_path.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")

    invalid = _run(governed_repo, "validate")
    assert invalid.returncode == 1
    assert any(
        "检查结果摘要不匹配" in issue for issue in json.loads(invalid.stdout)["issues"]
    )
    completion = _run(governed_repo, "check", "--completion")
    assert completion.returncode == 1
    assert json.loads(completion.stdout)["integrityIssues"]
    hook = _run(governed_repo, "hook-stop")
    assert hook.returncode == 0
    assert json.loads(hook.stdout)["decision"] == "block"
    events_after_hook = [
        json.loads(line)
        for line in (governed_repo / ".governance" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert events_after_hook[-1]["type"] == "PROJECT_COMPLETED"


def test_event_binding_tamper_is_rejected(governed_repo: Path) -> None:
    run = _run(governed_repo, "run", "--item", "WI-001", "--gate", "e2e-real")
    assert run.returncode == 0, run.stderr
    events_path = governed_repo / ".governance" / "events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]
    check_event = next(event for event in events if event["type"] == "CHECK_FINISHED")
    check_event["outcome"] = "fail"
    events_path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
    )
    assert _run(governed_repo, "derive").returncode == 0

    invalid = _run(governed_repo, "validate")
    assert invalid.returncode == 1
    assert any(
        "outcome 与事件不匹配" in issue
        for issue in json.loads(invalid.stdout)["issues"]
    )


def test_project_stop_hooks_allow_repository_scale_check_time() -> None:
    codex = json.loads(
        (REPO_ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8")
    )
    devin = json.loads(
        (REPO_ROOT / ".devin" / "hooks.v1.json").read_text(encoding="utf-8")
    )
    assert codex["hooks"]["Stop"][0]["hooks"][0]["timeout"] >= 120
    assert devin["Stop"][0]["hooks"][0]["timeout"] >= 120


@pytest.mark.parametrize(
    ("relative_path", "host_key"),
    [(Path(".codex/hooks.json"), "codex"), (Path(".devin/hooks.v1.json"), "devin")],
)
def test_runtime_rejects_stop_hook_timeout_drift(
    governed_repo: Path, relative_path: Path, host_key: str
) -> None:
    for gate_id in ("unit-required", "e2e-real"):
        passed = _run(governed_repo, "run", "--item", "WI-001", "--gate", gate_id)
        assert passed.returncode == 0, passed.stderr
    assert (
        _run(
            governed_repo, "record", "--type", "WORK_IMPLEMENTED", "--item", "WI-001"
        ).returncode
        == 0
    )
    completed = _run(governed_repo, "check", "--completion")
    assert completed.returncode == 0, completed.stderr

    hook_path = governed_repo / relative_path
    config = json.loads(hook_path.read_text(encoding="utf-8"))
    groups = config["hooks"]["Stop"] if host_key == "codex" else config["Stop"]
    groups[0]["hooks"][0]["timeout"] = 30
    hook_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    invalid = _run(governed_repo, "validate")
    assert invalid.returncode == 1
    assert "Stop Hook" in invalid.stdout
    check = _run(governed_repo, "check", "--completion")
    assert check.returncode == 1
    assert "Stop Hook" in check.stdout
    status = json.loads(_run(governed_repo, "status").stdout)
    assert status["runtimeState"] == "COMPLETED_INVALID"
    assert status["completion"]["eligible"] is False
    hook = _run(governed_repo, "hook-stop")
    assert json.loads(hook.stdout)["decision"] == "block"


def test_runtime_rejects_noop_stop_hook_command_drift(governed_repo: Path) -> None:
    hook_path = governed_repo / ".codex" / "hooks.json"
    config = json.loads(hook_path.read_text(encoding="utf-8"))
    handler = config["hooks"]["Stop"][0]["hooks"][0]
    active_field = "commandWindows" if os.name == "nt" else "command"
    handler[active_field] = "echo governance.py hook-stop"
    hook_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    invalid = _run(governed_repo, "validate")
    assert invalid.returncode == 1
    assert "执行规格发生漂移" in invalid.stdout
    check = _run(governed_repo, "check", "--completion")
    assert check.returncode == 1
    assert "执行规格发生漂移" in check.stdout


def test_runtime_rejects_stop_hook_matcher_drift(governed_repo: Path) -> None:
    hook_path = governed_repo / ".devin" / "hooks.v1.json"
    config = json.loads(hook_path.read_text(encoding="utf-8"))
    config["Stop"][0]["matcher"] = "never-match-governance"
    hook_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    invalid = _run(governed_repo, "validate")
    assert invalid.returncode == 1
    assert "执行规格发生漂移" in invalid.stdout
