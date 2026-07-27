from __future__ import annotations

import hashlib
import io
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

from freshquant.backtest.clx import run_verified_engine_python

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_SCRIPTS = (
    REPO_ROOT / "script/clx_backtest/finalize_full_signal_facts.sh",
    REPO_ROOT / "script/clx_backtest/gates/v2_causal_signal_real.sh",
    REPO_ROOT / "script/clx_backtest/gates/v2_ranking_real.sh",
    REPO_ROOT / "script/clx_backtest/gates/v2_portfolio_real.sh",
    REPO_ROOT / "script/clx_backtest/run_full_artifact_chain.sh",
)
ENGINE_UNIT_GATE = REPO_ROOT / "script/clx_backtest/gates/engine_unit_fixture.sh"
ENGINE_RUNTIME_RUNNER = (
    REPO_ROOT / "freshquant/backtest/clx/run_verified_engine_python.py"
)
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


def test_formal_subprocesses_verify_the_sealed_native_module_in_process() -> None:
    expected_pythonpath = "PYTHONPATH=/opt/clx-src:/opt/clx-engine:/workspace"
    expected_runner = "-m freshquant.backtest.clx.run_verified_engine_python"
    expected_counts = {
        REPO_ROOT / "script/clx_backtest/run_full_artifact_chain.sh": 1,
        REPO_ROOT / "script/clx_backtest/gates/v2_causal_signal_real.sh": 2,
        REPO_ROOT / "script/clx_backtest/gates/v2_ranking_real.sh": 1,
        REPO_ROOT / "script/clx_backtest/gates/v2_portfolio_real.sh": 1,
    }

    for script, count in expected_counts.items():
        source = script.read_text(encoding="utf-8")
        assert source.count(expected_pythonpath) == count, script
        assert source.count(expected_runner) == count, script
        assert (
            source.count('-e CLX_EXPECTED_ENGINE_SHA256="$CLX_EXPECTED_ENGINE_SHA256"')
            == count
        ), script
        assert source.count("-w /opt/clx-src") == count, script
        assert "-w /workspace" not in source, script
        assert "PYTHONPATH=/workspace " not in source, script
        assert "${CLX_EXPECTED_ENGINE_SHA256:?" in source, script

    runner = ENGINE_RUNTIME_RUNNER.read_text(encoding="utf-8")
    for token in (
        'SOURCE_ROOT = Path("/opt/clx-src")',
        'ENGINE_ROOT = Path("/opt/clx-engine")',
        'os.environ.get("CLX_EXPECTED_ENGINE_SHA256"',
        '"freshquant.backtest.clx": source_root / "freshquant/backtest/clx"',
        "runner_path.parent != package_root",
        "target module is outside sealed CLX source",
        "path.parent != engine_root",
        "hashlib.sha256(path.read_bytes()).hexdigest()",
        '"status": "engine-runtime-verified"',
        "runpy.run_module",
        'exec(compile(source, "<stdin>", "exec"), namespace)',
    ):
        assert token in runner
    assert "os.exec" not in runner


def test_verified_engine_runner_executes_target_with_the_checked_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine_root = tmp_path / "engine"
    engine_root.mkdir()
    module_path = engine_root / "fqcopilot.so"
    module_path.write_bytes(b"sealed-native-fixture")
    module = ModuleType("fqcopilot")
    module.__file__ = str(module_path)
    monkeypatch.setitem(sys.modules, "fqcopilot", module)
    monkeypatch.setattr(run_verified_engine_python, "ENGINE_ROOT", engine_root)
    monkeypatch.setattr(run_verified_engine_python, "SOURCE_ROOT", REPO_ROOT)
    monkeypatch.setenv(
        "CLX_EXPECTED_ENGINE_SHA256",
        hashlib.sha256(module_path.read_bytes()).hexdigest(),
    )

    target_output = tmp_path / "target.json"
    monkeypatch.setenv("CLX_TEST_ENGINE_TARGET_OUTPUT", str(target_output))
    target_source = (
        "import json, os, pathlib, sys, fqcopilot\n"
        "pathlib.Path(os.environ['CLX_TEST_ENGINE_TARGET_OUTPUT']).write_text(\n"
        "    json.dumps({'pid': os.getpid(), 'module_path': fqcopilot.__file__, "
        "'argv': sys.argv}), encoding='utf-8'\n"
        ")\n"
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        type("BinaryStdin", (), {"buffer": io.BytesIO(target_source.encode())})(),
    )

    result = run_verified_engine_python.main(["test-runtime-stage", "-", "argument"])

    assert result == 0
    observed = json.loads(target_output.read_text(encoding="utf-8"))
    assert observed["pid"] == os.getpid()
    assert Path(observed["module_path"]).resolve() == module_path.resolve()
    assert observed["argv"][1:] == ["argument"]

    module_identity = run_verified_engine_python.verify_python_sources(
        ["-m", "freshquant.backtest.clx.model_registry"]
    )
    assert Path(str(module_identity["runner_path"])).parent == (
        REPO_ROOT / "freshquant/backtest/clx"
    )
    assert Path(str(module_identity["target_module_path"])) == (
        REPO_ROOT / "freshquant/backtest/clx/model_registry.py"
    )


def test_verified_engine_runner_rejects_loaded_module_sha_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_path = tmp_path / "fqcopilot.so"
    module_path.write_bytes(b"drifted-native-fixture")
    module = ModuleType("fqcopilot")
    module.__file__ = str(module_path)
    monkeypatch.setitem(sys.modules, "fqcopilot", module)
    monkeypatch.setattr(run_verified_engine_python, "ENGINE_ROOT", tmp_path)
    monkeypatch.setenv("CLX_EXPECTED_ENGINE_SHA256", "0" * 64)

    with pytest.raises(
        run_verified_engine_python.EngineRuntimeError,
        match="fqcopilot runtime SHA-256 mismatch",
    ):
        run_verified_engine_python.verify_engine_runtime("test-runtime-stage", ["-"])


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
        assert source.count("FQCOPILOT_BUILD_TARGET=fqcopilot") == 1, script
        assert source.index("pybind11==3.0.2") < source.index(
            "setup.py build_ext --inplace"
        )
        assert source.index("FQCOPILOT_BUILD_TARGET=fqcopilot") < source.index(
            "setup.py build_ext --inplace"
        )


def test_trigger_mask_source_build_pins_runtime_numpy() -> None:
    source = ISOLATED_NATIVE_BUILD_GATES[0].read_text(encoding="utf-8")
    assert source.count("numpy==2.2.6") == 1
    assert source.index("numpy==2.2.6") < source.index(
        "python setup.py build_ext --inplace"
    )
