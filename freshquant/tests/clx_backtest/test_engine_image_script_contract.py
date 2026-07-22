from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_SCRIPTS = (
    REPO_ROOT / "script/clx_backtest/finalize_full_signal_facts.sh",
    REPO_ROOT / "script/clx_backtest/gates/v2_causal_signal_real.sh",
    REPO_ROOT / "script/clx_backtest/gates/v2_ranking_real.sh",
    REPO_ROOT / "script/clx_backtest/gates/v2_portfolio_real.sh",
    REPO_ROOT / "script/clx_backtest/run_full_artifact_chain.sh",
)


def test_formal_chain_scripts_require_an_operator_selected_engine_image() -> None:
    for script in ENGINE_SCRIPTS:
        source = script.read_text(encoding="utf-8")
        assert "${CLX_ENGINE_IMAGE_ID:?" in source, script
        assert 'image="$CLX_ENGINE_IMAGE_ID"' in source, script
        assert "${CLX_ENGINE_IMAGE_ID:-" not in source, script
        assert 'docker image inspect "$image"' in source, script


def test_causal_chain_requires_an_operator_selected_native_engine_digest() -> None:
    chain = (REPO_ROOT / "script/clx_backtest/run_full_artifact_chain.sh").read_text(
        encoding="utf-8"
    )
    gate = (REPO_ROOT / "script/clx_backtest/gates/v2_causal_signal_real.sh").read_text(
        encoding="utf-8"
    )

    for source in (chain, gate):
        assert "${CLX_EXPECTED_ENGINE_SHA256:?" in source
        assert "${CLX_EXPECTED_ENGINE_SHA256:-" not in source
    assert "export CLX_EXPECTED_ENGINE_SHA256" in chain
    assert 'expected_engine="${CLX_EXPECTED_ENGINE_SHA256#sha256:}"' in gate
    assert 'expected_engine="fc0e74' not in gate
