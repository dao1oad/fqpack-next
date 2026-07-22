from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_GATE = REPO_ROOT / "script/clx_backtest/gates/v2_frontend_real.sh"
E2E_GATE = REPO_ROOT / "script/clx_backtest/gates/v2_e2e_real.sh"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v2_frontend_gate_is_real_read_only_and_identity_bound() -> None:
    script = source(FRONTEND_GATE)

    for token in (
        "set -Eeuo pipefail",
        "CLX_REAL_RUN_ID",
        "CLX_API_BASE_URL",
        "CLX_WEB_BASE_URL",
        "CLX_EXPECTED_PROJECTED_MANIFEST_SHA256",
        "CLX_EXPECTED_SNAPSHOT_ID",
        "CLX_EXPECTED_SIGNAL_SET_ID",
        "CLX_EXPECTED_EVENT_SET_ID",
        "CLX_EXPECTED_RANKING_SET_ID",
        "CLX_EXPECTED_API_FREEZE_ID",
        "CLX_EXPECTED_RANKING_FREEZE_ID",
        "CLX_EXPECTED_REVEAL_ID",
        "CLX_PLAYWRIGHT_IMAGE_ID",
        "CLX_FRONTEND_EVIDENCE_OUT",
        "chromium.launch",
        "clx-results-panel",
        "clx-experiments-panel",
        "clx-compare-panel",
        "REVEALED",
        "reveal_count",
        "forbiddenMutations",
        "clx-v2-frontend-real-evidence-v1",
    ):
        assert token in script
    assert "fixture" not in script.lower()
    assert "/holdout/reveal" not in script
    assert "installFixtureApi" not in script


def test_v2_e2e_gate_closes_artifact_mongo_deploy_and_governance_chain() -> None:
    script = source(E2E_GATE)

    for token in (
        "set -Eeuo pipefail",
        "CLX_ARTIFACT_RUN_ID",
        "CLX_SNAPSHOT_DIR",
        "CLX_SIGNAL_DIR",
        "CLX_EVENT_DIR",
        "CLX_RANKING_DIR",
        "CLX_HOLDOUT_DIR",
        "CLX_PORTFOLIO_ROOT",
        "CLX_HOLDOUT_LEDGER_DIR",
        "freshquant_clx_backtest",
        "CLX_MONGO_URI",
        "CLX_API_CONTAINER",
        "CLX_WORKER_CONTAINER",
        "CLX_WEB_CONTAINER",
        "CLX_API_IMAGE_ID",
        "freshquant_health_check.py",
        "CLX_GOVERNANCE_EVENTS",
        "v2-causal-signal-real",
        "v2-ranking-real",
        "v2-portfolio-real",
        "v2-frontend-real",
        "subjectDigestBefore",
        "subjectDigestAfter",
        "successful_holdout_reads",
        "freeze_records",
        "holdout_jobs",
        "clx-v2-e2e-real-evidence-v1",
    ):
        assert token in script
    assert "/holdout/reveal" not in script
    assert "fixture" not in script.lower()


@pytest.mark.skipif(os.name == "nt", reason="bash syntax is verified on POSIX")
@pytest.mark.parametrize("script", [FRONTEND_GATE, E2E_GATE])
def test_v2_delivery_gate_bash_syntax(script: Path) -> None:
    result = subprocess.run(
        ["bash", "-n", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name == "nt", reason="bash runtime is verified on POSIX")
@pytest.mark.parametrize("script", [FRONTEND_GATE, E2E_GATE])
def test_v2_delivery_gates_fail_closed_without_explicit_bindings(script: Path) -> None:
    env = {"PATH": os.environ["PATH"]}
    result = subprocess.run(
        ["bash", str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 64
    assert "is required by the V2" in result.stderr
