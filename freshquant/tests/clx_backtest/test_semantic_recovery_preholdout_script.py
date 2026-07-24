from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "script/clx_backtest/run_semantic_recovery_preholdout.sh"
CAUSAL_GATE = REPO_ROOT / "script/clx_backtest/gates/v2_causal_signal_real.sh"
RANKING_GATE = REPO_ROOT / "script/clx_backtest/gates/v2_ranking_real.sh"


def test_semantic_recovery_preholdout_is_contract_pinned_before_writes() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert "umask 077" in script
    assert 'runner_uid="$(id -u)"' in script
    assert 'RUNNER_UID="$runner_uid"' in script
    assert "value.st_uid != runner_uid" in script
    assert "group_or_world_writable(value.st_mode)" in script
    assert "stat.S_ISVTX" in script
    assert "sticky shared parent" in script
    assert "ancestor is group/world writable without sticky bit" in script
    assert "Same-UID writers and Docker-daemon control" in script
    assert "missing_ok: bool = False" in script
    assert "canonical resolution failed" in script
    assert 'require_sealed_anchor(source / "facts", "source facts")' in script
    assert 'require_sealed_anchor(snapshot, "snapshot")' in script
    assert (
        'require_output_anchor(target, "target", kind="dir", allow_missing=False)'
        in script
    )
    assert 'require_output_anchor(target / "facts", "child facts"' in script
    assert (
        'require_output_anchor(event, "event", kind="dir", allow_missing=True)'
        in script
    )
    assert (
        'require_output_anchor(ranking, "ranking", kind="dir", allow_missing=True)'
        in script
    )
    assert 'require_output_anchor(ranking.parent, "ranking parent"' in script
    assert 'access.parent, "ranking access-log parent"' in script
    assert 'access, "ranking access log", kind="file"' in script

    assert "freshquant.backtest.clx.ranking reveal" not in script
    assert "freshquant.backtest.clx.portfolio" not in script
    assert "target frozen configs are missing" in script
    assert 'str(frozen_root / f"{name}.json")' in script
    assert "not materialized under the child root" in script
    assert "target frozen config root" in script
    assert "differs from the target frozen config" in script
    assert 'export CLX_EXPECTED_SNAPSHOT_ID="$snapshot_id"' in script
    assert (
        'export CLX_EXPECTED_SNAPSHOT_MANIFEST_SHA256="$snapshot_manifest_sha256"'
        in script
    )
    assert 'export CLX_EXPECTED_RUN_CONTRACT_SHA256="$run_contract_sha256"' in script
    assert 'export CLX_EXPECTED_SPLIT_PLAN_SHA256="$split_plan_sha256"' in script
    assert (
        'export CLX_EXPECTED_RANKING_CONFIG_SHA256="$ranking_config_sha256"' in script
    )
    assert "export CLX_REQUIRE_CHILD_RUN_CONTRACT=1" in script
    assert script.index('preflight_paths="$(') < script.index("for directory in")
    assert script.index(
        'verify_child_contract "before filesystem setup"'
    ) < script.index("for directory in")
    assert script.index(
        'verify_runtime_paths "before filesystem setup"'
    ) < script.index("for directory in")
    assert script.index('verify_engine_image "before filesystem setup"') < script.index(
        "run_python semantic-derive"
    )
    assert script.index("source and target run roots overlap") < script.index(
        "for directory in"
    )
    assert 'verify_child_contract "before $stage"' in script
    assert 'verify_runtime_paths "before $stage"' in script
    assert 'verify_engine_image "before $stage"' in script
    run_python_start = script.index("run_python() {")
    child_check = script.index(
        'verify_child_contract "before $stage"', run_python_start
    )
    engine_check = script.index('verify_engine_image "before $stage"', run_python_start)
    runtime_check = script.index(
        'verify_runtime_paths "before $stage"', run_python_start
    )
    docker_run = script.index("docker run --rm --network none", run_python_start)
    after_stage = script.index('verify_runtime_paths "after $stage"', run_python_start)
    assert child_check < engine_check < runtime_check < docker_run < after_stage
    assert script.index("# Sealed contracts retain host-absolute paths.") < docker_run
    assert "refresh_runtime_container_paths" in script
    assert "printf '%s' \"$root\"" in script
    assert "printf '%s' \"$path\"" in script
    assert '-v "$runtime_root:/runtime"' not in script
    assert '-v "$runtime_root:$runtime_root:ro"' in script
    assert '-v "$target_root:$target_c"' in script
    assert '-v "$audit_dir:$audit_c"' in script
    assert '-v "$evidence_root:$evidence_c"' in script
    assert script.index('-v "$runtime_root:$runtime_root:ro"') < script.index(
        '-v "$target_root:$target_c"'
    ) < script.index('-v "$source_root:$source_c:ro"')
    assert 'verify_runtime_paths "before mkdir $directory"' in script
    assert 'mkdir -p -m 700 "$directory"' in script
    assert 'verify_runtime_paths "after mkdir $directory"' in script
    assert script.index('verify_runtime_paths "before recovery lock"') < script.index(
        'exec 9>"$state_dir/.lock"'
    )
    assert 'verify_runtime_paths "before facts finalization"' in script
    assert 'verify_runtime_paths "before v2 causal gate"' in script
    assert 'verify_runtime_paths "before v2 ranking gate"' in script
    finalizer = script.index(
        'bash "$repo_root/script/clx_backtest/finalize_full_signal_facts.sh"'
    )
    assert (
        script.index('verify_child_contract "before facts finalization"')
        < script.index('verify_engine_image "before facts finalization"')
        < script.index('verify_runtime_paths "before facts finalization"')
        < finalizer
        < script.index('verify_runtime_paths "after facts finalization"')
    )
    causal_gate = script.index(
        'bash "$repo_root/script/clx_backtest/gates/v2_causal_signal_real.sh"'
    )
    assert (
        script.index('verify_child_contract "before v2 causal gate"')
        < script.index('verify_engine_image "before v2 causal gate"')
        < script.index('verify_runtime_paths "before v2 causal gate"')
        < causal_gate
        < script.index('verify_runtime_paths "after v2 causal gate"')
    )
    ranking_gate = script.index(
        'bash "$repo_root/script/clx_backtest/gates/v2_ranking_real.sh"'
    )
    assert (
        script.index('verify_child_contract "before v2 ranking gate"')
        < script.index('verify_engine_image "before v2 ranking gate"')
        < script.index('verify_runtime_paths "before v2 ranking gate"')
        < ranking_gate
        < script.index('verify_runtime_paths "after v2 ranking gate"')
    )
    assert "canonical identity drifted" in script
    assert '-v "$source_root:$source_c:ro" -v "$snapshot_dir:$snapshot_c:ro"' in script
    assert 'assert_tree(source_facts, "source facts", immutable=True)' in script
    assert 'assert_tree(snapshot, "snapshot", immutable=True)' in script
    assert 'assert_no_symlinks(snapshot, "snapshot root", immutable=True)' in script
    assert "checked_digest(snapshot_manifest_path, immutable=True)" in script

    snapshot_verify = (
        '-m freshquant.backtest.clx.snapshot verify --snapshot-dir "$snapshot_c"'
    )
    assert script.count(snapshot_verify) == 3
    assert script.index("run_python snapshot-content-preflight") < script.index(
        "for directory in"
    )
    assert script.index("run_python snapshot-content-before-event") < script.index(
        "run_python event-study"
    )
    assert script.index("run_python snapshot-content-before-ranking") < script.index(
        "run_python ranking"
    )


def test_v2_ranking_gate_rebinds_recovery_inputs_from_child_contract() -> None:
    gate = RANKING_GATE.read_text(encoding="utf-8")

    assert "CLX_REQUIRE_CHILD_RUN_CONTRACT" in gate
    assert "CLX_EXPECTED_RUN_CONTRACT_SHA256" in gate
    assert "CLX_EXPECTED_SPLIT_PLAN_SHA256" in gate
    assert "CLX_EXPECTED_RANKING_CONFIG_SHA256" in gate
    assert "CLX_EXPECTED_SNAPSHOT_MANIFEST_SHA256" in gate
    assert "child recovery requires CLX_RUN_CONTRACT" in gate
    assert "child frozen {name} config is outside the child root" in gate
    assert 'str(run_root / "frozen-configs")' in gate
    assert "child_contract_mounts" in gate
    assert 'snapshot_sha == os.environ["CLX_EXPECTED_SNAPSHOT_MANIFEST_SHA256"]' in gate
    assert (
        'file_sha256(split_plan_path) == os.environ["CLX_EXPECTED_SPLIT_PLAN_SHA256"]'
        in gate
    )
    assert "file_sha256(ranking_config_path) == os.environ[" in gate
    assert (
        'child_contract_sha == os.environ["CLX_EXPECTED_RUN_CONTRACT_SHA256"]' in gate
    )
    assert 'SIGNAL_DIR="$signal_dir"' in gate
    assert "semantic recovery signal facts require" in gate
    assert "signal facts derivation and child recovery lineage disagree" in gate
    assert "semantic recovery signal facts are outside CLX_FULL_RUN_ROOT" in gate
    assert 'str(run_root / "facts")' in gate
    assert "expected_run_contract_sha256=(" in gate


@pytest.mark.skipif(os.name == "nt", reason="bash runtime is verified on POSIX")
def test_v2_ranking_gate_rejects_unpinned_recovery_signal_before_docker(
    tmp_path: Path,
) -> None:
    def write_hashed_manifest(path: Path, value: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
        path.write_bytes(payload)
        path.with_name("manifest.sha256").write_text(
            f"{hashlib.sha256(payload).hexdigest()}  manifest.json\n",
            encoding="ascii",
        )

    snapshot_dir = tmp_path / "snapshot"
    signal_dir = tmp_path / "child-run" / "facts"
    write_hashed_manifest(
        snapshot_dir / "manifest.json", {"snapshot_id": "snapshot-test"}
    )
    write_hashed_manifest(
        signal_dir / "manifest.json",
        {
            "run_id": "semantic-recovery-test",
            "derivation": {
                "schema_version": "clx-semantic-derivation-v1",
                "migration_id": "s0002-entrypoint4-strong-swing-v1",
            },
        },
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker-called"
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'docker invoked\\n' > \"$CLX_TEST_DOCKER_LOG\"\n"
        "exit 99\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    env = os.environ.copy()
    for name in (
        "CLX_REQUIRE_CHILD_RUN_CONTRACT",
        "CLX_EXPECTED_RUN_CONTRACT_SHA256",
        "CLX_RUN_CONTRACT",
        "CLX_FULL_RUN_ROOT",
    ):
        env.pop(name, None)
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "CLX_TEST_DOCKER_LOG": str(docker_log),
            "CLX_SNAPSHOT_ID": "snapshot-test",
            "CLX_SNAPSHOT_DIR": str(snapshot_dir),
            "CLX_SIGNAL_DIR": str(signal_dir),
            "CLX_ENGINE_IMAGE_ID": "sha256:" + "a" * 64,
            "CLX_EXPECTED_ENGINE_SHA256": "b" * 64,
        }
    )

    result = subprocess.run(
        ["bash", str(RANKING_GATE)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode != 0
    assert "semantic recovery signal facts require" in result.stderr
    assert not docker_log.exists()


@pytest.mark.skipif(os.name == "nt", reason="bash runtime is verified on POSIX")
def test_v2_ranking_gate_rejects_recovery_signal_outside_child_root_before_docker(
    tmp_path: Path,
) -> None:
    def write_hashed_json(path: Path, value: dict[str, object], *, sealed: bool) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        path.write_bytes(payload)
        sidecar = path.with_suffix(".sha256")
        sidecar.write_text(f"{digest}  {path.name}\n", encoding="ascii")
        if sealed:
            path.chmod(0o444)
            sidecar.chmod(0o444)
        return digest

    snapshot_dir = tmp_path / "snapshot"
    child_root = tmp_path / "child-run"
    (child_root / "facts").mkdir(parents=True)
    external_signal_dir = tmp_path / "external-facts"
    write_hashed_json(
        snapshot_dir / "manifest.json", {"snapshot_id": "snapshot-test"}, sealed=False
    )
    recovery = {
        "schema_version": "clx-semantic-derivation-v1",
        "migration_id": "s0002-entrypoint4-strong-swing-v1",
        "source_run_id": "source-run",
        "source_signal_set_id": "sha256:" + "a" * 64,
        "source_manifest_sha256": "b" * 64,
        "source_evidence_sha256": "c" * 64,
        "source_run_contract_sha256": "d" * 64,
    }
    contract_path = child_root / "run-contract.json"
    contract_sha = write_hashed_json(
        contract_path,
        {
            "run_id": "child-run",
            "holdout_state": "LOCKED",
            "recovery": recovery,
        },
        sealed=True,
    )
    write_hashed_json(
        external_signal_dir / "manifest.json",
        {
            "run_id": "child-run",
            "derivation": {
                **recovery,
                "target_run_contract_sha256": contract_sha,
            },
        },
        sealed=False,
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker-called"
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'docker invoked\\n' > \"$CLX_TEST_DOCKER_LOG\"\n"
        "exit 99\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "CLX_TEST_DOCKER_LOG": str(docker_log),
            "CLX_FULL_RUN_ROOT": str(child_root),
            "CLX_RUN_CONTRACT": str(contract_path),
            "CLX_REQUIRE_CHILD_RUN_CONTRACT": "1",
            "CLX_EXPECTED_RUN_CONTRACT_SHA256": contract_sha,
            "CLX_SNAPSHOT_ID": "snapshot-test",
            "CLX_SNAPSHOT_DIR": str(snapshot_dir),
            "CLX_SIGNAL_DIR": str(external_signal_dir),
            "CLX_ENGINE_IMAGE_ID": "sha256:" + "e" * 64,
            "CLX_EXPECTED_ENGINE_SHA256": "f" * 64,
        }
    )

    result = subprocess.run(
        ["bash", str(RANKING_GATE)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "semantic recovery signal facts are outside CLX_FULL_RUN_ROOT" in result.stderr
    )
    assert not docker_log.exists()


@pytest.mark.skipif(os.name == "nt", reason="bash runtime is verified on POSIX")
def test_v2_ranking_gate_keeps_legacy_snapshot_pin_for_custom_dir(
    tmp_path: Path,
) -> None:
    snapshot_dir = tmp_path / "custom-snapshot"
    snapshot_dir.mkdir()
    manifest_path = snapshot_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({"snapshot_id": "sha256:not-the-legacy-baseline"}),
        encoding="utf-8",
    )
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    (snapshot_dir / "manifest.sha256").write_text(
        f"{manifest_sha256}  manifest.json\n", encoding="ascii"
    )

    env = os.environ.copy()
    env.pop("CLX_SNAPSHOT_ID", None)
    env.update(
        {
            "CLX_SNAPSHOT_DIR": str(snapshot_dir),
            "CLX_ENGINE_IMAGE_ID": "sha256:" + "a" * 64,
            "CLX_EXPECTED_ENGINE_SHA256": "b" * 64,
        }
    )
    result = subprocess.run(
        ["bash", str(RANKING_GATE)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode != 0
    assert "CLX_SNAPSHOT_ID differs from the mounted snapshot manifest" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="bash runtime is verified on POSIX")
def test_v2_causal_gate_accepts_finalized_marker_without_sidecar(
    tmp_path: Path,
) -> None:
    def write_immutable(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        path.chmod(0o444)

    def write_hashed_json(path: Path, value: dict[str, object]) -> str:
        payload = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        write_immutable(path, payload)
        write_immutable(
            path.with_name(f"{path.name}.sha256"),
            f"{digest}  {path.name}\n".encode("ascii"),
        )
        return digest

    run_id = "semantic-recovery-test"
    signal_set_id = "sha256:" + "e" * 64
    image = "sha256:" + "a" * 64
    engine_sha = "b" * 64
    online_sha = "c" * 64
    image_source_commit = "f" * 40
    image_host_source_commit = "1" * 40
    snapshot_id = "snapshot-test"
    snapshot_manifest_sha = "d" * 64
    counts = {
        "codes": 5201,
        "source_rows": 16426284,
        "eligible_rows": 16426281,
        "excluded_clx_rows": 3,
        "prefix_calls": 16426281,
        "signal_revisions": 1,
        "tradable_signal_facts": 1,
        "unexpected_synthetic_primary": 0,
    }
    verification = {
        "status": "verified",
        "deep": True,
        "signal_revisions": 1,
        "tradable_signal_facts": 1,
    }
    run_root = tmp_path / "run"
    facts = run_root / "facts"
    runner = run_root / ".runner"
    configs = run_root / "frozen-configs"
    runner.mkdir(parents=True)
    configs.mkdir()

    frozen_configs: dict[str, dict[str, str]] = {}
    for name in ("split_plan", "ranking", "portfolio"):
        path = configs / f"{name}.json"
        payload = f'{{"name":"{name}"}}\n'.encode("utf-8")
        write_immutable(path, payload)
        frozen_configs[name] = {
            "path": str(path),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    contract_path = run_root / "run-contract.json"
    contract = {
        "run_id": run_id,
        "holdout_state": "LOCKED",
        "engine": {
            "image_id": image,
            "module_sha256": engine_sha,
            "online_module_sha256": online_sha,
        },
        "source": {
            "image_source_commit": image_source_commit,
            "image_host_source_commit": image_host_source_commit,
        },
        "frozen_configs": frozen_configs,
    }
    contract_payload = (json.dumps(contract, sort_keys=True) + "\n").encode("utf-8")
    contract_sha = hashlib.sha256(contract_payload).hexdigest()
    write_immutable(contract_path, contract_payload)
    write_immutable(
        contract_path.with_suffix(".sha256"),
        f"{contract_sha}  {contract_path.name}\n".encode("ascii"),
    )

    manifest_path = facts / "manifest.json"
    manifest = {
        "state": "COMPLETE",
        "run_id": run_id,
        "signal_set_id": signal_set_id,
        "snapshot": {
            "snapshot_id": snapshot_id,
            "manifest_sha256": snapshot_manifest_sha,
        },
        "engine": {"native_module_sha256": engine_sha},
        "config": {"wave_opt": 1560, "stretch_opt": 0, "ext_opt": 0},
        "causality": {"route": "PREFIX_REPLAY", "full_history_trade_source": False},
        "partitioning": {"bucket_count": 64},
        "completed_buckets": list(range(64)),
        "counts": counts,
        "quality": {"unknown_scalar_protocol_count": 0},
        "artifacts": [{"path": "placeholder.parquet"}],
    }
    manifest_payload = (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_payload).hexdigest()
    write_immutable(manifest_path, manifest_payload)
    write_immutable(
        facts / "manifest.sha256",
        f"{manifest_sha}  manifest.json\n".encode("ascii"),
    )
    facts.chmod(0o555)

    evidence_path = tmp_path / "evidence.json"
    evidence_sha = write_hashed_json(
        evidence_path,
        {
            "schema_version": "clx-v2-causal-signal-finalization-v1",
            "status": "verified",
            "runner_image_source_commit": image_source_commit,
            "run_id": run_id,
            "signal_set_id": signal_set_id,
            "manifest_sha256": manifest_sha,
            "run_contract_sha256": contract_sha,
            "snapshot_id": snapshot_id,
            "counts": counts,
            "completed_buckets": 64,
            "deep_verify": verification,
        },
    )
    finalized_path = runner / "finalized"
    write_immutable(
        finalized_path,
        (
            json.dumps(
                {
                    "schema_version": "clx-signal-finalization-marker-v1",
                    "status": "FINALIZED",
                    "run_id": run_id,
                    "signal_set_id": signal_set_id,
                    "manifest_sha256": manifest_sha,
                    "run_contract_sha256": contract_sha,
                    "evidence_path": str(evidence_path),
                    "evidence_sha256": evidence_sha,
                },
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
    )
    write_immutable(runner / "complete", b"{}\n")
    assert not finalized_path.with_name("finalized.sha256").exists()

    docker_log = tmp_path / "docker.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "%s\\n" "$*" >> "$CLX_TEST_DOCKER_LOG"\n'
        'if [[ "${1:-}" == "image" && "${2:-}" == "inspect" ]]; then\n'
        '  printf "%s\\n" "$CLX_ENGINE_IMAGE_ID"\n'
        'elif [[ "${1:-}" == "run" ]]; then\n'
        '  printf "%s\\n" "$CLX_TEST_VERIFY_JSON"\n'
        'elif [[ "${1:-}" == "exec" ]]; then\n'
        '  printf "%s\\n" "$CLX_EXPECTED_ONLINE_ENGINE_SHA256"\n'
        "else\n"
        "  exit 99\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "CLX_TEST_DOCKER_LOG": str(docker_log),
            "CLX_TEST_VERIFY_JSON": json.dumps(verification),
            "CLX_FULL_RUN_ROOT": str(run_root),
            "CLX_ENGINE_IMAGE_ID": image,
            "CLX_EXPECTED_ENGINE_SHA256": engine_sha,
            "CLX_EXPECTED_ONLINE_ENGINE_SHA256": online_sha,
            "CLX_EXPECTED_SNAPSHOT_ID": snapshot_id,
            "CLX_EXPECTED_SNAPSHOT_MANIFEST_SHA256": snapshot_manifest_sha,
        }
    )

    result = subprocess.run(
        ["bash", str(CAUSAL_GATE)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    calls = docker_log.read_text(encoding="utf-8").splitlines()
    assert sum(call.startswith("run ") for call in calls) == 2


def test_v2_causal_gate_keeps_finalization_marker_and_evidence_integrity_distinct() -> (
    None
):
    gate = CAUSAL_GATE.read_text(encoding="utf-8")

    assert "def load_immutable_json(path):" in gate
    assert 'finalized=load_immutable_json(root/".runner/finalized")' in gate
    assert "evidence, evidence_sha=load_hashed_json(evidence_path)" in gate
    assert 'load_hashed_json(root/".runner/finalized")' not in gate
    assert 'complete=load_immutable_json(root/".runner/complete")' in gate
    assert (
        'evidence["runner_image_source_commit"]==contract["source"]["image_source_commit"]'
        in gate
    )
    assert 'FACTS="$facts"' in gate
    assert "signal facts derivation and child recovery lineage disagree" in gate


@pytest.mark.skipif(os.name == "nt", reason="bash runtime is verified on POSIX")
def test_v2_causal_gate_rejects_unpinned_or_wrong_child_contract_before_docker(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "child-run"
    runner = run_root / ".runner"
    runner.mkdir(parents=True)
    (runner / "complete").write_text("complete\n", encoding="utf-8")
    (runner / "finalized").write_text("finalized\n", encoding="utf-8")

    contract_path = run_root / "run-contract.json"
    contract_payload = json.dumps(
        {
            "run_id": "child-run",
            "holdout_state": "LOCKED",
            "recovery": {"migration_id": "s0002-entrypoint4-strong-swing-v1"},
        },
        sort_keys=True,
    ).encode("utf-8")
    contract_path.write_bytes(contract_payload)
    contract_sha = hashlib.sha256(contract_payload).hexdigest()
    contract_sidecar = contract_path.with_suffix(".sha256")
    contract_sidecar.write_text(
        f"{contract_sha}  {contract_path.name}\n", encoding="ascii"
    )
    for path in (contract_path, contract_sidecar):
        path.chmod(0o444)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker-called"
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'docker invoked\\n' > \"$CLX_TEST_DOCKER_LOG\"\n"
        "exit 99\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "CLX_TEST_DOCKER_LOG": str(docker_log),
            "CLX_FULL_RUN_ROOT": str(run_root),
            "CLX_RUN_CONTRACT": str(contract_path),
            "CLX_ENGINE_IMAGE_ID": "sha256:" + "a" * 64,
            "CLX_EXPECTED_ENGINE_SHA256": "b" * 64,
            "CLX_EXPECTED_ONLINE_ENGINE_SHA256": "c" * 64,
        }
    )

    unpinned = subprocess.run(
        ["bash", str(CAUSAL_GATE)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert unpinned.returncode != 0
    assert "semantic recovery child requires" in unpinned.stderr
    assert not docker_log.exists()

    env.update(
        {
            "CLX_REQUIRE_CHILD_RUN_CONTRACT": "1",
            "CLX_EXPECTED_RUN_CONTRACT_SHA256": "f" * 64,
        }
    )
    wrong_sha = subprocess.run(
        ["bash", str(CAUSAL_GATE)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert wrong_sha.returncode != 0
    assert "child run contract SHA-256 differs from expected" in wrong_sha.stderr
    assert not docker_log.exists()

    facts = run_root / "facts"
    facts.mkdir()
    manifest_path = facts / "manifest.json"
    manifest_payload = b'{"run_id":"child-run"}\n'
    manifest_path.write_bytes(manifest_payload)
    manifest_sha = hashlib.sha256(manifest_payload).hexdigest()
    manifest_sidecar = facts / "manifest.sha256"
    manifest_sidecar.write_text(f"{manifest_sha}  manifest.json\n", encoding="ascii")
    for path in (manifest_path, manifest_sidecar):
        path.chmod(0o444)
    facts.chmod(0o555)
    env.update(
        {
            "CLX_REQUIRE_CHILD_RUN_CONTRACT": "1",
            "CLX_EXPECTED_RUN_CONTRACT_SHA256": contract_sha,
        }
    )
    missing_derivation = subprocess.run(
        ["bash", str(CAUSAL_GATE)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert missing_derivation.returncode != 0
    assert "signal facts derivation and child recovery lineage disagree" in (
        missing_derivation.stderr
    )
    assert not docker_log.exists()
