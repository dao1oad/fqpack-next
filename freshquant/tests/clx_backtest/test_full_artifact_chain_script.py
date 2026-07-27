from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from freshquant.backtest.clx.ranking import _content_id
from freshquant.backtest.clx.ranking_io import _decode_external_audit_prefix

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="The artifact-chain entrypoint is a Linux bash runtime contract.",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAIN_SCRIPT = REPO_ROOT / "script/clx_backtest/run_full_artifact_chain.sh"
GATES = (
    ("v2_causal_signal_real.sh", "v2-causal-signal-real"),
    ("v2_ranking_real.sh", "v2-ranking-real"),
    ("v2_portfolio_real.sh", "v2-portfolio-real"),
)


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _chain_fixture(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    repo_root = tmp_path / "repo"
    runtime_root = tmp_path / "runtime"
    run_tag = "full-test"
    snapshot_id = "snapshot-test"
    run_root = runtime_root / "events" / run_tag
    command_log = tmp_path / "commands.log"
    holdout_access_log = runtime_root / f"audit/holdout-{run_tag}-event-access.jsonl"
    run_id = f"run-{run_tag}"
    freeze_id = "sha256:" + "a" * 64
    ranking_set_id = "sha256:" + "c" * 64
    claim_id = _content_id(
        {
            "ledger_schema_version": "clx-holdout-ledger-v1",
            "freeze_id": freeze_id,
            "ranking_set_id": ranking_set_id,
            "state": "CLAIMED",
        }
    )

    for path in (
        run_root / ".runner/finalized",
        run_root / "verify-run-identity.py",
        run_root / "facts/manifest.json",
        run_root / "facts/manifest.sha256",
        run_root / "event-study/manifest.sha256",
        runtime_root / f"snapshots/{snapshot_id}/calendar/part-00000.parquet",
        runtime_root / "config/split-plan.json",
        runtime_root / "config/ranking-config.json",
        runtime_root / "config/portfolio-config.json",
        runtime_root / f"rankings/{run_tag}/manifest.sha256",
        runtime_root / f"holdout/{run_tag}/manifest.sha256",
    ):
        _write(path, "fixture\n")
    run_contract = run_root / "run-contract.json"
    run_contract_payload = json.dumps({"run_id": run_id}, sort_keys=True) + "\n"
    _write(run_contract, run_contract_payload)
    _write(
        run_root / "run-contract.sha256",
        hashlib.sha256(run_contract_payload.encode("utf-8")).hexdigest()
        + "  run-contract.json\n",
    )
    for split in ("TRAIN", "VALIDATION", "HOLDOUT"):
        _write(
            runtime_root / f"portfolios/{run_tag}/{split}/manifest.sha256", "fixture\n"
        )

    gate_root = repo_root / "script/clx_backtest/gates"
    for filename, gate_id in GATES:
        _write(
            gate_root / filename,
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"printf 'direct:{gate_id}\\n' >> \"$CLX_TEST_COMMAND_LOG\"\n",
        )

    fake_bin = tmp_path / "bin"
    _write(
        fake_bin / "docker",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'docker:%s\\n\' "$*" >> "$CLX_TEST_COMMAND_LOG"\n'
        'if [[ "${1:-} ${2:-}" == "image inspect" '
        '&& "$*" == *"org.freshquant.clx.source-commit"* ]]; then\n'
        "  printf '%s\\n' \"$CLX_TEST_SOURCE_COMMIT\"\n"
        "  exit 0\n"
        "fi\n"
        'if [[ " $* " == *" freshquant.backtest.clx.event_study verify "* ]]; then\n'
        '  proof_c=""; marker_c=""; previous=""\n'
        '  for argument in "$@"; do\n'
        '    if [[ "$previous" == "--proof-output" ]]; then proof_c="$argument"; fi\n'
        '    if [[ "$previous" == "--chain-marker-output" ]]; then marker_c="$argument"; fi\n'
        '    previous="$argument"\n'
        "  done\n"
        '  proof="$CLX_RUNTIME_ROOT${proof_c#/runtime}"\n'
        '  marker="$CLX_RUNTIME_ROOT${marker_c#/runtime}"\n'
        '  mkdir -p "$(dirname "$proof")"\n'
        '  if [[ "${CLX_TEST_SKIP_EVENT_PROOF_FILE:-}" != "proof" ]]; then\n'
        '    printf \'{"schema_version":"clx-event-preverification-v1"}\\n\' > "$proof"\n'
        '    chmod 0444 "$proof"\n'
        "  fi\n"
        '  if [[ "${CLX_TEST_SKIP_EVENT_PROOF_FILE:-}" != "proof-sidecar" '
        '&& -f "$proof" ]]; then\n'
        "    printf '%s  %s\\n' \"$(sha256sum \"$proof\" | awk '{print $1}')\" "
        '"$(basename "$proof")" > "${proof%.json}.sha256"\n'
        '    chmod 0444 "${proof%.json}.sha256"\n'
        "  fi\n"
        '  if [[ "${CLX_TEST_SKIP_EVENT_PROOF_FILE:-}" != "marker" ]]; then\n'
        '    printf \'{"schema_version":"clx-event-preverification-marker-v1"}\\n\' > "$marker"\n'
        '    chmod 0444 "$marker"\n'
        "  fi\n"
        '  if [[ "${CLX_TEST_SKIP_EVENT_PROOF_FILE:-}" != "marker-sidecar" '
        '&& -f "$marker" ]]; then\n'
        "    printf '%s  %s\\n' \"$(sha256sum \"$marker\" | awk '{print $1}')\" "
        '"$(basename "$marker")" > "${marker}.sha256"\n'
        '    chmod 0444 "${marker}.sha256"\n'
        "  fi\n"
        "fi\n"
        'if [[ "${CLX_TEST_SKIP_HOLDOUT_AUDIT:-0}" != "1" '
        '&& " $* " == *" freshquant.backtest.clx.ranking reveal "* ]]; then\n'
        '  audit="$CLX_HOLDOUT_ACCESS_LOG"\n'
        '  temporary="${audit}.tmp-$$"\n'
        '  mkdir -p "$(dirname "$audit")"\n'
        "  {\n"
        "    printf "
        '\'{"attempt_no":0,"claim_id":"%s","decision":"ALLOW",'
        '"freeze_id":"%s","holdout":true,'
        '"operation":"REVEAL_HOLDOUT","purpose":"FINAL_REVEAL",'
        '"reason":"FROZEN_RULES_ONE_TIME_REVEAL","run_id":"%s",'
        '"schema_version":"clx-event-file-access-v1","sequence":1,'
        '"split_id":"HOLDOUT"}\\n\' '
        '"$CLX_TEST_CLAIM_ID" "$CLX_TEST_FREEZE_ID" "$CLX_TEST_RUN_ID"\n'
        "    printf "
        '\'{"attempt_no":0,"claim_id":"%s","dataset":"event_outcomes",'
        '"decision":"ALLOW","freeze_id":"%s","holdout":true,'
        '"operation":"OPEN_PARQUET",'
        '"path":"code_buckets/code_bucket=000/event_outcomes/'
        'reveal_year=2024/part-00000.parquet","purpose":"LOAD_HOLDOUT",'
        '"run_id":"%s","schema_version":'
        '"clx-event-file-access-v1","sequence":1}\\n\' '
        '"$CLX_TEST_CLAIM_ID" "$CLX_TEST_FREEZE_ID" "$CLX_TEST_RUN_ID"\n'
        '  } > "$temporary"\n'
        '  mv "$temporary" "$audit"\n'
        "fi\n"
        "if [[ \"${1:-} ${2:-}\" == 'container inspect' ]]; then exit 1; fi\n"
        "exit 0\n",
    )
    _write(
        fake_bin / "python3",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ "${1:-}" == */verify-run-identity.py ]]; then\n'
        '  phase="${2:-missing}"\n'
        '  printf \'identity:%s\\n\' "$phase" >> "$CLX_TEST_COMMAND_LOG"\n'
        '  if [[ "${CLX_TEST_IDENTITY_FAIL_PHASE:-}" == "$phase" ]]; then exit 86; fi\n'
        "  exit 0\n"
        "fi\n"
        'printf \'governance:%s\\n\' "$*" >> "$CLX_TEST_COMMAND_LOG"\n',
    )
    for path in fake_bin.iterdir():
        path.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "CLX_TEST_COMMAND_LOG": str(command_log),
            "CLX_REPO_ROOT": str(repo_root),
            "CLX_RUNTIME_ROOT": str(runtime_root),
            "CLX_FULL_RUN_TAG": run_tag,
            "CLX_SNAPSHOT_ID": snapshot_id,
            "CLX_SPLIT_PLAN": str(runtime_root / "config/split-plan.json"),
            "CLX_RANKING_CONFIG": str(runtime_root / "config/ranking-config.json"),
            "CLX_PORTFOLIO_CONFIG": str(runtime_root / "config/portfolio-config.json"),
            "CLX_HOLDOUT_ACCESS_LOG": str(holdout_access_log),
            "CLX_TEST_RUN_ID": run_id,
            "CLX_TEST_FREEZE_ID": freeze_id,
            "CLX_TEST_RANKING_SET_ID": ranking_set_id,
            "CLX_TEST_CLAIM_ID": claim_id,
            "CLX_TEST_SOURCE_COMMIT": "e" * 40,
            "CLX_ENGINE_IMAGE_ID": "sha256:test-image",
            "CLX_EXPECTED_ENGINE_SHA256": "a" * 64,
            "CLX_EXPECTED_ONLINE_ENGINE_SHA256": "b" * 64,
        }
    )
    env.pop("CLX_GATE_RUNNER", None)
    return env, repo_root, command_log


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(CHAIN_SCRIPT)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )


def test_default_runner_executes_repository_v2_gates_without_governance(
    tmp_path: Path,
) -> None:
    env, _, command_log = _chain_fixture(tmp_path)

    result = _run(env)

    assert result.returncode == 0, result.stderr
    commands = command_log.read_text(encoding="utf-8").splitlines()
    assert [line for line in commands if line.startswith("direct:")] == [
        f"direct:{gate_id}" for _, gate_id in GATES
    ]
    assert not [line for line in commands if line.startswith("governance:")]
    reveal_commands = [
        line
        for line in commands
        if line.startswith("docker:")
        and "freshquant.backtest.clx.ranking reveal" in line
    ]
    assert len(reveal_commands) == 1
    assert "--resume-claimed" in reveal_commands[0]
    identities = [line for line in commands if line.startswith("identity:")]
    assert identities[0] == "identity:artifact-chain-start"
    assert "identity:artifact-chain-before-event-study" in identities
    assert "identity:artifact-chain-before-ranking" in identities
    assert "identity:artifact-chain-before-holdout-reveal" in identities
    assert "identity:artifact-chain-before-portfolio-holdout" in identities
    audit_path = Path(env["CLX_HOLDOUT_ACCESS_LOG"])
    assert stat.S_IMODE(audit_path.stat().st_mode) == 0o444
    audit = _decode_external_audit_prefix(
        audit_path.read_bytes(), expected_run_id=env["CLX_TEST_RUN_ID"]
    )
    assert [row["operation"] for row in audit] == [
        "REVEAL_HOLDOUT",
        "OPEN_PARQUET",
    ]
    assert all(row["freeze_id"] == env["CLX_TEST_FREEZE_ID"] for row in audit)
    assert all(row["claim_id"] == env["CLX_TEST_CLAIM_ID"] for row in audit)
    assert all(row["attempt_no"] == 0 for row in audit)
    event_verify = next(
        line
        for line in commands
        if line.startswith("docker:")
        and "freshquant.backtest.clx.event_study verify " in line
    )
    assert (
        "--proof-output /runtime/events/full-test/full-chain/event-preverification.json"
        in event_verify
    )
    assert (
        "--chain-marker-output /runtime/events/full-test/full-chain/event-study.passed"
        in event_verify
    )
    assert "--engine-image-id sha256:test-image" in event_verify
    assert f"--source-commit {env['CLX_TEST_SOURCE_COMMIT']}" in event_verify
    state = Path(env["CLX_RUNTIME_ROOT"]) / "events/full-test/full-chain"
    for path in (
        state / "event-preverification.json",
        state / "event-preverification.sha256",
        state / "event-study.passed",
        state / "event-study.passed.sha256",
    ):
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) == 0o444


@pytest.mark.parametrize(
    "missing",
    ["proof", "proof-sidecar", "marker", "marker-sidecar"],
)
def test_chain_requires_all_event_preverification_publications(
    tmp_path: Path, missing: str
) -> None:
    env, _, _ = _chain_fixture(tmp_path)
    env["CLX_TEST_SKIP_EVENT_PROOF_FILE"] = missing

    result = _run(env)

    assert result.returncode == 1
    assert "required CLX chain input is missing" in (result.stdout + result.stderr)


def test_chain_recovery_uses_metadata_preverification_without_deep_event_reads(
    tmp_path: Path,
) -> None:
    env, _, command_log = _chain_fixture(tmp_path)
    first = _run(env)
    assert first.returncode == 0, first.stderr
    before = command_log.read_text(encoding="utf-8").splitlines()

    second = _run(env)

    assert second.returncode == 0, second.stderr
    after = command_log.read_text(encoding="utf-8").splitlines()[len(before) :]
    docker_commands = [line for line in after if line.startswith("docker:")]
    assert any(
        "freshquant.backtest.clx.event_study verify-preverification" in line
        for line in docker_commands
    )
    assert not any(
        "freshquant.backtest.clx.event_study build" in line for line in docker_commands
    )
    assert not any(
        "freshquant.backtest.clx.event_study verify --output-dir" in line
        for line in docker_commands
    )


def test_chain_requires_the_run_scoped_external_holdout_audit(
    tmp_path: Path,
) -> None:
    env, _, command_log = _chain_fixture(tmp_path)
    env["CLX_TEST_SKIP_HOLDOUT_AUDIT"] = "1"

    result = _run(env)

    assert result.returncode == 1
    assert "required CLX chain input is missing" in (result.stdout + result.stderr)
    assert env["CLX_HOLDOUT_ACCESS_LOG"] in (result.stdout + result.stderr)
    commands = command_log.read_text(encoding="utf-8").splitlines()
    assert any("freshquant.backtest.clx.ranking reveal" in line for line in commands)
    assert not any(
        "freshquant.backtest.clx.ranking verify --holdout-dir" in line
        for line in commands
    )
    assert not Path(env["CLX_HOLDOUT_ACCESS_LOG"]).exists()


def test_identity_drift_stops_before_the_next_artifact_stage(tmp_path: Path) -> None:
    env, _, command_log = _chain_fixture(tmp_path)
    env["CLX_TEST_IDENTITY_FAIL_PHASE"] = "artifact-chain-before-ranking"

    result = _run(env)

    assert result.returncode == 86
    commands = command_log.read_text(encoding="utf-8").splitlines()
    docker_commands = [line for line in commands if line.startswith("docker:")]
    assert any(
        "freshquant.backtest.clx.event_study verify" in line for line in docker_commands
    )
    assert not any(
        "freshquant.backtest.clx.ranking build" in line for line in docker_commands
    )


def test_signal_stop_is_verified_and_not_ignored() -> None:
    script = CHAIN_SCRIPT.read_text(encoding="utf-8")

    assert 'docker stop -t 30 "$signal_container"' in script
    assert 'docker stop -t 30 "$signal_container" >/dev/null || true' not in script
    assert "signal container is still running after stop" in script


@pytest.mark.parametrize("image_value", [None, ""])
def test_chain_requires_an_explicit_engine_image(
    tmp_path: Path, image_value: str | None
) -> None:
    env, _, command_log = _chain_fixture(tmp_path)
    if image_value is None:
        env.pop("CLX_ENGINE_IMAGE_ID")
    else:
        env["CLX_ENGINE_IMAGE_ID"] = image_value

    result = _run(env)

    assert result.returncode != 0
    assert "CLX_ENGINE_IMAGE_ID must name the verified immutable engine image" in (
        result.stderr
    )
    assert not command_log.exists()


@pytest.mark.parametrize("digest_value", [None, ""])
def test_chain_requires_an_explicit_native_engine_digest(
    tmp_path: Path, digest_value: str | None
) -> None:
    env, _, command_log = _chain_fixture(tmp_path)
    if digest_value is None:
        env.pop("CLX_EXPECTED_ENGINE_SHA256")
    else:
        env["CLX_EXPECTED_ENGINE_SHA256"] = digest_value

    result = _run(env)

    assert result.returncode != 0
    assert (
        "CLX_EXPECTED_ENGINE_SHA256 must name the verified native engine digest"
        in result.stderr
    )
    assert not command_log.exists()


@pytest.mark.parametrize("digest_value", [None, ""])
def test_chain_requires_an_explicit_online_engine_baseline(
    tmp_path: Path, digest_value: str | None
) -> None:
    env, _, command_log = _chain_fixture(tmp_path)
    if digest_value is None:
        env.pop("CLX_EXPECTED_ONLINE_ENGINE_SHA256")
    else:
        env["CLX_EXPECTED_ONLINE_ENGINE_SHA256"] = digest_value

    result = _run(env)

    assert result.returncode != 0
    assert (
        "CLX_EXPECTED_ONLINE_ENGINE_SHA256 must name the frozen online engine baseline"
        in result.stderr
    )
    assert not command_log.exists()


def test_governance_runner_records_the_three_bound_item_gate_pairs(
    tmp_path: Path,
) -> None:
    env, repo_root, command_log = _chain_fixture(tmp_path)
    env["CLX_GATE_RUNNER"] = "governance"
    _write(repo_root / "tools/governance.py", "# fixture\n")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    commands = command_log.read_text(encoding="utf-8").splitlines()
    assert [line for line in commands if line.startswith("governance:")] == [
        "governance:tools/governance.py run --item WI-004 --gate v2-causal-signal-real",
        "governance:tools/governance.py run --item WI-006 --gate v2-ranking-real",
        "governance:tools/governance.py run --item WI-007 --gate v2-portfolio-real",
    ]
    assert not [line for line in commands if line.startswith("direct:")]


@pytest.mark.parametrize("runner", ["", "auto", "DIRECT"])
def test_runner_value_is_an_explicit_closed_enum(tmp_path: Path, runner: str) -> None:
    env, repo_root, command_log = _chain_fixture(tmp_path)
    env["CLX_GATE_RUNNER"] = runner
    _write(repo_root / "tools/governance.py", "# fixture\n")

    result = _run(env)

    assert result.returncode == 64
    assert f"invalid CLX_GATE_RUNNER: {runner}" in result.stderr
    assert not command_log.exists()


def test_selected_runner_missing_dependency_does_not_fall_back(tmp_path: Path) -> None:
    env, repo_root, command_log = _chain_fixture(tmp_path)
    env["CLX_GATE_RUNNER"] = "direct"
    _write(repo_root / "tools/governance.py", "# fixture\n")
    (repo_root / "script/clx_backtest/gates/v2_ranking_real.sh").unlink()

    result = _run(env)

    assert result.returncode == 1
    assert "v2_ranking_real.sh" in result.stderr
    assert not command_log.exists()


def test_governance_mode_does_not_fall_back_to_direct_gates(tmp_path: Path) -> None:
    env, _, command_log = _chain_fixture(tmp_path)
    env["CLX_GATE_RUNNER"] = "governance"

    result = _run(env)

    assert result.returncode == 1
    assert "tools/governance.py" in result.stderr
    assert not command_log.exists()
