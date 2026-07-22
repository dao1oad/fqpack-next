from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

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

    for path in (
        run_root / ".runner/finalized",
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
        "if [[ \"${1:-} ${2:-}\" == 'container inspect' ]]; then exit 1; fi\n"
        "exit 0\n",
    )
    _write(
        fake_bin / "python3",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
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
            "CLX_ENGINE_IMAGE_ID": "sha256:test-image",
            "CLX_EXPECTED_ENGINE_SHA256": "a" * 64,
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
    assert any(
        "freshquant.backtest.clx.ranking reveal" in line
        for line in commands
        if line.startswith("docker:")
    )


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
