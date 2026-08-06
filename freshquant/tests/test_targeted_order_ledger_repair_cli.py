from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from freshquant.order_management.repair import targeted_ledger as repair_core

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = REPO_ROOT / "script" / "maintenance" / "targeted_order_ledger_repair.py"
TARGET_MAIN_SHA = "2e8754590c1b108637eaf2370ec99f5b1257810f"
BASE_SHA = "1" * 40


def test_apply_accepts_matching_formal_deploy_evidence(
    tmp_path,
    monkeypatch,
):
    module = _load_cli_module()
    paths = _write_apply_inputs(tmp_path)
    captured = {}
    database_calls = []
    databases = {"order": object(), "business": object()}

    monkeypatch.setattr(module, "_current_git_head", lambda: TARGET_MAIN_SHA)
    monkeypatch.setattr(
        module.repair_core,
        "build_repair_plan_hash",
        lambda _plan: "b" * 64,
    )
    monkeypatch.setattr(
        module,
        "_get_databases",
        lambda: database_calls.append(True) or databases,
    )

    def execute_targeted_repair(**kwargs):
        captured.update(kwargs)
        return {"status": "applied"}

    monkeypatch.setattr(
        module.repair_core,
        "execute_targeted_repair",
        execute_targeted_repair,
    )

    result = _run_apply(module, paths)

    assert result == {"status": "applied"}
    assert database_calls == [True]
    assert captured["databases"] is databases
    assert captured["deployed_main_sha"] == TARGET_MAIN_SHA


def test_apply_rejects_deploy_range_target_mismatch_before_database_access(
    tmp_path,
    monkeypatch,
):
    paths = _write_apply_inputs(tmp_path)
    deploy_state = _read_json(paths["deploy_state_path"])
    deploy_state["inputs"]["from_git_diff"] = f"{BASE_SHA}..{'f' * 40}"
    _write_json(paths["deploy_state_path"], deploy_state)

    _assert_gate_rejected(
        paths,
        monkeypatch,
        match="from_git_diff target sha",
    )


def test_apply_rejects_incomplete_deploy_phase_before_database_access(
    tmp_path,
    monkeypatch,
):
    paths = _write_apply_inputs(tmp_path)
    deploy_state = _read_json(paths["deploy_state_path"])
    deploy_state["phases"]["host"]["status"] = "failed"
    _write_json(paths["deploy_state_path"], deploy_state)

    _assert_gate_rejected(paths, monkeypatch, match="phase host is not completed")


def test_apply_rejects_runtime_verify_path_mismatch_before_database_access(
    tmp_path,
    monkeypatch,
):
    paths = _write_apply_inputs(tmp_path)
    deploy_state = _read_json(paths["deploy_state_path"])
    deploy_state["artifacts"]["verify_path"] = str(tmp_path / "other.json")
    _write_json(paths["deploy_state_path"], deploy_state)

    _assert_gate_rejected(paths, monkeypatch, match="verify_path does not match")


def test_apply_rejects_failed_runtime_verification_before_database_access(
    tmp_path,
    monkeypatch,
):
    paths = _write_apply_inputs(tmp_path)
    runtime_verify = _read_json(paths["runtime_verify_path"])
    runtime_verify["passed"] = False
    _write_json(paths["runtime_verify_path"], runtime_verify)

    _assert_gate_rejected(
        paths,
        monkeypatch,
        match="verification evidence did not pass",
    )


def test_apply_rejects_missing_runtime_surface_before_database_access(
    tmp_path,
    monkeypatch,
):
    paths = _write_apply_inputs(tmp_path)
    runtime_verify = _read_json(paths["runtime_verify_path"])
    runtime_verify["deployment_surfaces"] = ["api"]
    _write_json(paths["runtime_verify_path"], runtime_verify)

    _assert_gate_rejected(
        paths,
        monkeypatch,
        match="missing order_management surface",
    )


def _assert_gate_rejected(paths, monkeypatch, *, match):
    module = _load_cli_module()
    database_calls = []

    monkeypatch.setattr(module, "_current_git_head", lambda: TARGET_MAIN_SHA)
    monkeypatch.setattr(
        module.repair_core,
        "build_repair_plan_hash",
        lambda _plan: "b" * 64,
    )

    def fail_if_database_is_requested():
        database_calls.append(True)
        raise AssertionError("deployment gate failure must not connect to Mongo")

    monkeypatch.setattr(module, "_get_databases", fail_if_database_is_requested)
    monkeypatch.setattr(
        module.repair_core,
        "execute_targeted_repair",
        lambda **_kwargs: pytest.fail("core apply must not run when a gate fails"),
    )

    with pytest.raises(repair_core.TargetedRepairError, match=match):
        _run_apply(module, paths)

    assert database_calls == []


def _run_apply(module, paths):
    return module.run_apply(
        plan_path=paths["plan_path"],
        manifest_path=paths["manifest_path"],
        expected_plan_file_sha256=module.repair_core.sha256_file(paths["plan_path"]),
        expected_plan_hash="b" * 64,
        expected_preimage_hash="c" * 64,
        expected_manifest_hash="d" * 64,
        backup_dir=paths["backup_dir"],
        deploy_state_path=paths["deploy_state_path"],
        runtime_verify_path=paths["runtime_verify_path"],
        execute=True,
    )


def _write_apply_inputs(tmp_path):
    plan_path = _write_json(
        tmp_path / "plan.json",
        {"target_main_sha": TARGET_MAIN_SHA},
    )
    manifest_path = _write_json(tmp_path / "manifest.json", {})
    runtime_verify_path = _write_json(
        tmp_path / "runtime-verify.json",
        {
            "passed": True,
            "deployment_surfaces": ["api", "order_management"],
        },
    )
    deploy_state_path = _write_json(
        tmp_path / "deploy-state.json",
        {
            "inputs": {
                "from_git_diff": f"{BASE_SHA}..{TARGET_MAIN_SHA}",
                "deployment_surfaces": ["api", "order_management"],
            },
            "artifacts": {"verify_path": str(runtime_verify_path)},
            "phases": {
                phase: {"status": "completed"}
                for phase in ("docker", "host", "health", "verify")
            },
        },
    )
    return {
        "plan_path": plan_path,
        "manifest_path": manifest_path,
        "backup_dir": tmp_path / "backup",
        "deploy_state_path": deploy_state_path,
        "runtime_verify_path": runtime_verify_path,
    }


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_cli_module():
    spec = importlib.util.spec_from_file_location(
        "targeted_order_ledger_repair_cli_under_test",
        CLI_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
