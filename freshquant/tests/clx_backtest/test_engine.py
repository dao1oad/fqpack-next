from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from freshquant.backtest.clx import (
    ClxEngineInputError,
    ClxEngineOptions,
    ClxEngineProtocolError,
    ClxSignalProtocolError,
    FqCopilotClxEngine,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "clx_engine_golden.json"


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _sparse_signals(rows: tuple[tuple[int, ...], ...]) -> list[list[list[int]]]:
    return [
        [[bar_index, value] for bar_index, value in enumerate(row) if value]
        for row in rows
    ]


def test_real_fqcopilot_batch_matches_golden_and_each_single_model() -> None:
    from fqcopilot import fq_clxs

    fixture = _load_fixture()
    bars = fixture["ohlcv"]
    options = ClxEngineOptions(**fixture["options"])
    engine = FqCopilotClxEngine()

    result = engine.calculate_all(
        bars["high"],
        bars["low"],
        bars["open"],
        bars["close"],
        bars["volume"],
        options=options,
    )

    bar_count = fixture["bar_count"]
    assert result.shape == (18, bar_count)
    assert (
        _sparse_signals(result.signals_by_model) == fixture["expected_sparse_signals"]
    )

    observed_max_occurrence = []
    for model_id in range(18):
        single = fq_clxs(
            bar_count,
            bars["high"],
            bars["low"],
            bars["open"],
            bars["close"],
            bars["volume"],
            options.wave_opt,
            options.stretch_opt,
            options.trend_opt,
            model_id,  # batch fq_clxs_all has native switch_opt=0
        )
        assert tuple(int(value) for value in single) == result.for_model(model_id)

        occurrences = [
            result.decoded_at(model_id, bar_index).occurrence
            for bar_index, value in enumerate(result.for_model(model_id))
            if value
        ]
        observed_max_occurrence.append(max(occurrences, default=0))

    assert observed_max_occurrence == fixture["expected_max_occurrence_by_model"]
    assert max(observed_max_occurrence) == fixture["expected_fixture_max_occurrence"]
    assert all(any(row) for row in result.signals_by_model)


class _RecordingBackend:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls = 0

    def fq_clxs_all(self, *args: object) -> object:
        self.calls += 1
        return self.output


def _valid_output(bar_count: int) -> list[list[float]]:
    return [[0.0] * bar_count for _ in range(18)]


def test_research_baseline_options_preserve_s0015_default_ma250() -> None:
    options = ClxEngineOptions()
    assert (options.wave_opt, options.stretch_opt, options.trend_opt) == (1560, 0, 0)
    assert options.trend_opt != 1


def test_input_length_mismatch_is_rejected_before_native_call() -> None:
    backend = _RecordingBackend(_valid_output(2))
    engine = FqCopilotClxEngine(backend)

    with pytest.raises(ClxEngineInputError, match="equal lengths"):
        engine.calculate_all([2, 3], [1], [1, 2], [1.5, 2.5], [10, 20])
    assert backend.calls == 0


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), True, [1]])
def test_non_scalar_or_non_finite_input_is_rejected(bad_value: object) -> None:
    backend = _RecordingBackend(_valid_output(1))
    engine = FqCopilotClxEngine(backend)

    with pytest.raises(ClxEngineInputError, match="finite number"):
        engine.calculate_all([bad_value], [1], [1], [1], [1])
    assert backend.calls == 0


def test_empty_input_is_rejected_before_native_call() -> None:
    backend = _RecordingBackend(_valid_output(0))
    engine = FqCopilotClxEngine(backend)

    with pytest.raises(ClxEngineInputError, match="at least one bar"):
        engine.calculate_all([], [], [], [], [])
    assert backend.calls == 0


def test_batch_requires_exactly_18_model_rows() -> None:
    engine = FqCopilotClxEngine(_RecordingBackend([[0.0]] * 17))

    with pytest.raises(ClxEngineProtocolError, match="17 model rows"):
        engine.calculate_all([2], [1], [1], [1.5], [10])


def test_batch_requires_one_value_per_input_bar() -> None:
    output = _valid_output(2)
    output[7] = [0.0]
    engine = FqCopilotClxEngine(_RecordingBackend(output))

    with pytest.raises(ClxEngineProtocolError, match="model 7 returned 1 bars"):
        engine.calculate_all([2, 3], [1, 2], [1, 2], [1.5, 2.5], [10, 20])


def test_batch_rejects_fractional_signal() -> None:
    output = _valid_output(1)
    output[3][0] = 3101.5
    engine = FqCopilotClxEngine(_RecordingBackend(output))

    with pytest.raises(ClxEngineProtocolError, match="signal must be an integer"):
        engine.calculate_all([2], [1], [1], [1.5], [10])


def test_batch_uses_model_row_to_decode_overlapping_occurrence_digits() -> None:
    output = _valid_output(1)
    output[16][0] = 17001.0  # model 16, occurrence 10, entrypoint 1
    engine = FqCopilotClxEngine(_RecordingBackend(output))

    result = engine.calculate_all([2], [1], [1], [1.5], [10])
    decoded = result.decoded_at(16, 0)
    assert decoded is not None
    assert (decoded.model_id, decoded.occurrence, decoded.primary_entrypoint) == (
        16,
        10,
        1,
    )


def test_batch_rejects_signal_that_cannot_belong_to_its_model_row() -> None:
    output = _valid_output(1)
    output[17][0] = 16101.0
    engine = FqCopilotClxEngine(_RecordingBackend(output))

    with pytest.raises(ClxSignalProtocolError):
        engine.calculate_all([2], [1], [1], [1.5], [10])


@pytest.mark.parametrize(
    "options",
    [
        {"wave_opt": -1},
        {"stretch_opt": 1.5},
        {"trend_opt": True},
    ],
)
def test_options_require_nonnegative_integers(options: dict[str, object]) -> None:
    with pytest.raises(ClxEngineInputError):
        ClxEngineOptions(**options)


class _DetailedRecordingBackend:
    def __init__(self, output: object, *, expose_legacy: bool = False) -> None:
        self.output = output
        self.calls = 0
        if expose_legacy:
            self.fq_clxs_all = self._legacy_must_not_run

    def fq_clxs_all_detailed(self, *args: object) -> object:
        self.calls += 1
        return self.output

    def _legacy_must_not_run(self, *args: object) -> object:
        raise AssertionError("detailed backend must be preferred")


def _valid_detailed_output(bar_count: int) -> dict[str, object]:
    return {
        "signals_by_model": _valid_output(bar_count),
        "buy_base_trigger_masks": [0] * bar_count,
        "sell_base_trigger_masks": [0] * bar_count,
    }


def test_native_integer_detailed_output_uses_vector_fast_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import freshquant.backtest.clx.engine as engine_module

    output = {
        "signals_by_model": [[0] * 2 for _ in range(18)],
        "buy_base_trigger_masks": [2, 0],
        "sell_base_trigger_masks": [0, 2],
    }
    output["signals_by_model"][16][0] = 17001
    output["signals_by_model"][0][1] = -102

    def scalar_fallback_must_not_run(*_args: object) -> object:
        raise AssertionError("valid native integer output must use the fast path")

    monkeypatch.setattr(
        engine_module, "_normalise_batch_output", scalar_fallback_must_not_run
    )
    monkeypatch.setattr(
        engine_module,
        "_normalise_base_trigger_masks",
        scalar_fallback_must_not_run,
    )

    result = FqCopilotClxEngine(_DetailedRecordingBackend(output)).calculate_all(
        [2, 3], [1, 2], [1, 2], [1.5, 2.5], [10, 20]
    )

    occurrence_ten = result.decoded_at(16, 0)
    assert occurrence_ten is not None and occurrence_ten.occurrence == 10
    assert result.buy_base_trigger_masks == (2, 0)
    assert result.sell_base_trigger_masks == (0, 2)


@pytest.mark.parametrize("bad_value", [True, 3101.5, object()])
def test_detailed_fast_path_preserves_invalid_signal_contract(
    bad_value: object,
) -> None:
    output = _valid_detailed_output(1)
    signals = output["signals_by_model"]
    assert isinstance(signals, list)
    signals[3][0] = bad_value
    engine = FqCopilotClxEngine(_DetailedRecordingBackend(output))

    with pytest.raises(ClxEngineProtocolError, match="signal must be an integer"):
        engine.calculate_all([2], [1], [1], [1.5], [10])


def test_detailed_fast_path_preserves_ragged_row_contract() -> None:
    output = _valid_detailed_output(2)
    signals = output["signals_by_model"]
    assert isinstance(signals, list)
    signals[7] = [0.0]
    engine = FqCopilotClxEngine(_DetailedRecordingBackend(output))

    with pytest.raises(ClxEngineProtocolError, match="model 7 returned 1 bars"):
        engine.calculate_all([2, 3], [1, 2], [1, 2], [1.5, 2.5], [10, 20])


@pytest.mark.parametrize("bad_mask", [True, 1.5, object()])
def test_detailed_fast_path_preserves_invalid_mask_contract(bad_mask: object) -> None:
    output = _valid_detailed_output(1)
    output["buy_base_trigger_masks"] = [bad_mask]
    engine = FqCopilotClxEngine(_DetailedRecordingBackend(output))

    with pytest.raises(ClxEngineProtocolError, match="mask must be an integer"):
        engine.calculate_all([2], [1], [1], [1.5], [10])


def test_detailed_batch_attaches_direction_mask_and_platform_structure_bit() -> None:
    output = _valid_detailed_output(2)
    signals = output["signals_by_model"]
    assert isinstance(signals, list)
    signals[0][0] = 101.0
    signals[0][1] = -102.0
    output["buy_base_trigger_masks"] = [1 << 1, 0]
    output["sell_base_trigger_masks"] = [0, 1 << 1]
    backend = _DetailedRecordingBackend(output, expose_legacy=True)

    result = FqCopilotClxEngine(backend).calculate_all(
        [2, 3], [1, 2], [1, 2], [1.5, 2.5], [10, 20]
    )

    assert backend.calls == 1
    assert result.has_concurrent_trigger_masks
    assert result.buy_base_trigger_masks == (2, 0)
    assert result.sell_base_trigger_masks == (0, 2)
    buy_structure = result.decoded_at(0, 0)
    sell_pinbar = result.decoded_at(0, 1)
    assert buy_structure is not None and buy_structure.concurrent_trigger_mask == 3
    assert sell_pinbar is not None and sell_pinbar.concurrent_trigger_mask == 2


def test_detailed_batch_synthesizes_missing_primary_without_mutating_base() -> None:
    output = _valid_detailed_output(1)
    signals = output["signals_by_model"]
    assert isinstance(signals, list)
    signals[0][0] = 102.0
    engine = FqCopilotClxEngine(_DetailedRecordingBackend(output))

    result = engine.calculate_all([2], [1], [1], [1.5], [10])

    assert result.buy_base_trigger_masks == (0,)
    decoded = result.decoded_at(0, 0)
    assert decoded is not None
    assert decoded.concurrent_trigger_mask == 1 << (decoded.primary_entrypoint - 1)


def test_detailed_base_masks_leave_model_structural_bit_clear() -> None:
    output = _valid_detailed_output(1)
    output["buy_base_trigger_masks"] = [1]
    engine = FqCopilotClxEngine(_DetailedRecordingBackend(output))

    with pytest.raises(ClxEngineProtocolError, match="entrypoint 1 clear"):
        engine.calculate_all([2], [1], [1], [1.5], [10])


def test_legacy_batch_backend_remains_supported_without_trigger_masks() -> None:
    backend = _RecordingBackend(_valid_output(1))
    result = FqCopilotClxEngine(backend).calculate_all([2], [1], [1], [1.5], [10])

    assert backend.calls == 1
    assert not result.has_concurrent_trigger_masks
    assert result.buy_base_trigger_masks is None
    assert result.sell_base_trigger_masks is None
