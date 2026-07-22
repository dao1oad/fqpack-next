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
ENGINE_UNIT_GATE = REPO_ROOT / "script/clx_backtest/gates/engine_unit_fixture.sh"
ISOLATED_NATIVE_BUILD_GATES = (
    REPO_ROOT / "script/clx_backtest/gates/trigger_mask_fixture.sh",
    REPO_ROOT / "script/clx_backtest/gates/prefix_performance_fixture.sh",
    REPO_ROOT / "script/clx_backtest/gates/signal_facts_real_sample.sh",
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


def test_causal_chain_requires_a_frozen_online_engine_baseline() -> None:
    chain = (REPO_ROOT / "script/clx_backtest/run_full_artifact_chain.sh").read_text(
        encoding="utf-8"
    )
    gate = (REPO_ROOT / "script/clx_backtest/gates/v2_causal_signal_real.sh").read_text(
        encoding="utf-8"
    )

    for source in (chain, gate):
        assert "${CLX_EXPECTED_ONLINE_ENGINE_SHA256:?" in source
        assert "${CLX_EXPECTED_ONLINE_ENGINE_SHA256:-" not in source
    assert "export CLX_EXPECTED_ONLINE_ENGINE_SHA256" in chain
    assert 'expected_online="${CLX_EXPECTED_ONLINE_ENGINE_SHA256#sha256:}"' in gate
    assert 'EXPECTED_IMAGE="$image"' in gate
    assert 'contract["engine"]["image_id"]==os.environ["EXPECTED_IMAGE"]' in gate
    assert 'contract["engine"]["online_module_sha256"]' in gate
    assert 'expected_online="06b82' not in gate
    assert "docker exec -i fq_apiserver python -" in gate
    assert "docker exec fq_apiserver python -" not in gate


def test_engine_unit_gate_runs_only_the_signal_and_engine_unit_boundary() -> None:
    source = ENGINE_UNIT_GATE.read_text(encoding="utf-8")
    command = " ".join(source.replace("\\\n", " ").split())
    targets = [
        token
        for token in command.split()
        if token.startswith("freshquant/tests/clx_backtest")
    ]

    assert targets == [
        "freshquant/tests/clx_backtest/test_signal.py",
        "freshquant/tests/clx_backtest/test_engine.py",
    ]
    assert "python -m pytest -q freshquant/tests/clx_backtest\n" not in source
    assert "test_trigger_masks.py" not in source


def test_every_isolated_native_source_build_pins_pybind11() -> None:
    discovered = {
        path
        for path in (REPO_ROOT / "script/clx_backtest/gates").glob("*.sh")
        if "setup.py build_ext --inplace" in path.read_text(encoding="utf-8")
    }
    assert discovered == set(ISOLATED_NATIVE_BUILD_GATES)

    for script in ISOLATED_NATIVE_BUILD_GATES:
        source = script.read_text(encoding="utf-8")
        assert source.count("pybind11==3.0.2") == 1, script
        assert source.index("pybind11==3.0.2") < source.index(
            "setup.py build_ext --inplace"
        )
