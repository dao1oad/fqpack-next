from __future__ import annotations

from types import SimpleNamespace

import pytest

from freshquant.clx_daily_selection.contracts import frozen_profile
from freshquant.clx_daily_selection.engine import FqCopilotProductionEngine


def bars():
    return [
        {
            "date": "2026-03-19",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 1000.0,
        }
    ]


def test_engine_calls_batch_with_explicit_switch_one():
    captured = []

    def batch(*args):
        captured.append(args)
        return [[model_id * 1000 + 101] for model_id in range(18)]

    engine = FqCopilotProductionEngine(
        SimpleNamespace(fq_clxs_all=batch, fq_clxs=lambda *_args: [])
    )

    rows = engine.calculate(bars(), frozen_profile())

    assert captured[0][-1] == 1
    assert len(rows) == 18


def test_engine_legacy_batch_signature_records_production_single_fallback():
    model_ids = []

    def legacy_batch(*_args):
        raise TypeError("takes exactly 9 positional arguments (10 given)")

    def single(*args):
        model_ids.append(args[-1])
        return [args[-1] - 10000]

    engine = FqCopilotProductionEngine(
        SimpleNamespace(fq_clxs_all=legacy_batch, fq_clxs=single)
    )

    result = engine.calculate_with_metadata(bars(), frozen_profile())

    assert result["calculation_mode"] == "single_model_fallback"
    assert result["fallback_reason"] == "fq_clxs_all_missing_switch_opt"
    assert model_ids == list(range(10000, 10018))


def test_engine_missing_batch_entrypoint_records_production_single_fallback():
    model_ids = []

    def single(*args):
        model_ids.append(args[-1])
        return [args[-1] - 10000]

    result = FqCopilotProductionEngine(
        SimpleNamespace(fq_clxs=single)
    ).calculate_with_metadata(bars(), frozen_profile())

    assert result["calculation_mode"] == "single_model_fallback"
    assert result["fallback_reason"] == "fq_clxs_all_unavailable"
    assert model_ids == list(range(10000, 10018))


def test_engine_does_not_fallback_on_batch_calculation_type_error():
    def broken_batch(*_args):
        raise TypeError("invalid OHLC payload")

    engine = FqCopilotProductionEngine(
        SimpleNamespace(fq_clxs_all=broken_batch, fq_clxs=lambda *_args: [])
    )

    with pytest.raises(TypeError, match="invalid OHLC"):
        engine.calculate(bars(), frozen_profile())


def test_engine_returns_bar_aligned_s0002_structural_evidence():
    captured = []

    def native_evidence(*args):
        captured.append(args)
        return {
            "trigger_codes": [1],
            "triggers": ["buy_engulfing"],
        }

    module = SimpleNamespace(fq_s0002_entrypoint3_evidence=native_evidence)
    engine = FqCopilotProductionEngine(module)

    evidence = engine.s0002_entrypoint3_evidence(bars(), frozen_profile())

    assert evidence == {
        "trigger_codes": [1],
        "triggers": ["buy_engulfing"],
    }
    assert captured[0][-1] == 1


def test_engine_rejects_misaligned_s0002_structural_evidence():
    module = SimpleNamespace(
        fq_s0002_entrypoint3_evidence=lambda *_args: {
            "trigger_codes": [],
            "triggers": [],
        }
    )
    engine = FqCopilotProductionEngine(module)

    with pytest.raises(RuntimeError, match="align"):
        engine.s0002_entrypoint3_evidence(bars(), frozen_profile())


def test_engine_health_is_ready_only_with_batch_and_evidence_capabilities():
    ready = FqCopilotProductionEngine(
        SimpleNamespace(
            fq_clxs_all=lambda *_args: [],
            fq_s0002_entrypoint3_evidence=lambda *_args: {},
        )
    ).health()
    degraded = FqCopilotProductionEngine(
        SimpleNamespace(fq_clxs=lambda *_args: [])
    ).health()
    unavailable = FqCopilotProductionEngine(SimpleNamespace()).health()

    assert ready["status"] == "ready"
    assert ready["missing_capabilities"] == []
    assert degraded["status"] == "degraded"
    assert degraded["calculation_available"] is True
    assert degraded["missing_capabilities"] == [
        "fq_clxs_all",
        "fq_s0002_entrypoint3_evidence",
    ]
    assert unavailable["status"] == "unavailable"
    assert "production_calculation" in unavailable["missing_capabilities"]
