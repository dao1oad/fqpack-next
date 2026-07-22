from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from freshquant.backtest.clx import ClxEngineOptions, FqCopilotClxEngine

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _detailed_native() -> Any:
    import fqcopilot

    if not callable(getattr(fqcopilot, "fq_clxs_all_detailed", None)):
        pytest.skip("installed fqcopilot predates detailed trigger-mask interface")
    return fqcopilot


def _args(fixture: dict[str, Any]) -> tuple[Any, ...]:
    bars = fixture["ohlcv"]
    options = fixture["options"]
    return (
        fixture["bar_count"],
        bars["high"],
        bars["low"],
        bars["open"],
        bars["close"],
        bars["volume"],
        options["wave_opt"],
        options["stretch_opt"],
        options["trend_opt"],
    )


def test_native_detailed_interface_preserves_legacy_raw_and_mask_golden() -> None:
    fqcopilot = _detailed_native()
    fixture = _load("clx_engine_golden.json")
    golden = _load("clx_trigger_masks_golden.json")

    legacy_rows = fqcopilot.fq_clxs_all(*_args(fixture))
    detailed = fqcopilot.fq_clxs_all_detailed(*_args(fixture))

    assert set(detailed) == {
        "signals_by_model",
        "buy_base_trigger_masks",
        "sell_base_trigger_masks",
    }
    rows = detailed["signals_by_model"]
    buy_masks = detailed["buy_base_trigger_masks"]
    sell_masks = detailed["sell_base_trigger_masks"]
    assert len(rows) == 18
    assert all(len(row) == golden["bar_count"] for row in rows)
    assert len(buy_masks) == len(sell_masks) == golden["bar_count"]
    assert rows == [[int(value) for value in row] for row in legacy_rows]

    assert hashlib.sha256(bytes(buy_masks)).hexdigest() == golden["buy_masks_sha256"]
    assert hashlib.sha256(bytes(sell_masks)).hexdigest() == golden["sell_masks_sha256"]
    assert sum(bool(mask) for mask in buy_masks) == golden["buy_nonzero_bars"]
    assert sum(bool(mask) for mask in sell_masks) == golden["sell_nonzero_bars"]
    assert (
        sum(mask.bit_count() >= 2 for mask in buy_masks)
        == golden["buy_concurrent_bars"]
    )
    assert (
        sum(mask.bit_count() >= 2 for mask in sell_masks)
        == golden["sell_concurrent_bars"]
    )

    # Native base masks reserve bit 0 for platform-level structural evidence,
    # retain all other bits, and exercise every predicate 2..7 in this fixture.
    assert all(mask & 1 == 0 for mask in (*buy_masks, *sell_masks))
    observed_bits = 0
    for mask in (*buy_masks, *sell_masks):
        observed_bits |= mask
    assert observed_bits == sum(1 << (entrypoint - 1) for entrypoint in range(2, 8))


def test_engine_completes_primary_per_raw_event_and_keeps_all_concurrency() -> None:
    _detailed_native()
    fixture = _load("clx_engine_golden.json")
    golden = _load("clx_trigger_masks_golden.json")
    bars = fixture["ohlcv"]
    result = FqCopilotClxEngine().calculate_all(
        bars["high"],
        bars["low"],
        bars["open"],
        bars["close"],
        bars["volume"],
        options=ClxEngineOptions(**fixture["options"]),
    )

    assert result.has_concurrent_trigger_masks
    primary_counts = {entrypoint: 0 for entrypoint in range(1, 8)}
    structure_count = 0
    concurrent_signal_count = 0
    for model_id, row in enumerate(result.signals_by_model):
        for bar_index, raw_value in enumerate(row):
            if raw_value == 0:
                continue
            decoded = result.decoded_at(model_id, bar_index)
            assert decoded is not None
            mask = decoded.concurrent_trigger_mask
            assert mask is not None
            primary_counts[decoded.primary_entrypoint] += 1
            assert mask & (1 << (decoded.primary_entrypoint - 1))
            if decoded.primary_entrypoint == 1:
                structure_count += 1
                assert mask & 1
            if mask.bit_count() >= 2:
                concurrent_signal_count += 1

    assert structure_count == golden["primary_entrypoint_counts"]["1"]
    assert concurrent_signal_count == golden["concurrent_signal_count"]
    assert primary_counts == {
        int(key): value for key, value in golden["primary_entrypoint_counts"].items()
    }


def test_s0002_legacy_entrypoint3_keeps_engulfing_base_predicate_clear() -> None:
    fqcopilot = _detailed_native()
    fixture = _load("clx_engine_golden.json")
    detailed = fqcopilot.fq_clxs_all_detailed(*_args(fixture))

    s0002_entrypoint3 = [
        bar_index
        for bar_index, raw_value in enumerate(detailed["signals_by_model"][2])
        if raw_value and abs(raw_value) % 100 == 3
    ]
    assert s0002_entrypoint3 == [445, 524, 948, 1021, 1163]
    entrypoint3_bit = 1 << (3 - 1)
    for bar_index in s0002_entrypoint3:
        raw_value = detailed["signals_by_model"][2][bar_index]
        base_masks = (
            detailed["buy_base_trigger_masks"]
            if raw_value > 0
            else detailed["sell_base_trigger_masks"]
        )
        assert base_masks[bar_index] & entrypoint3_bit == 0

    bars = fixture["ohlcv"]
    result = FqCopilotClxEngine().calculate_all(
        bars["high"],
        bars["low"],
        bars["open"],
        bars["close"],
        bars["volume"],
        options=ClxEngineOptions(**fixture["options"]),
    )
    for bar_index in s0002_entrypoint3:
        decoded = result.decoded_at(2, bar_index)
        assert decoded is not None
        assert decoded.concurrent_trigger_mask is not None
        assert decoded.concurrent_trigger_mask & entrypoint3_bit


def test_native_detailed_rejects_negative_length() -> None:
    fqcopilot = _detailed_native()

    with pytest.raises(ValueError, match="non-negative"):
        fqcopilot.fq_clxs_all_detailed(-1, [], [], [], [], [], 1560, 0, 0)


@pytest.mark.parametrize(
    ("length", "high", "low", "open_", "close", "volume"),
    [
        (2, [2.0], [1.0], [1.0], [1.5], [10.0]),
        (1, [2.0], [], [1.0], [1.5], [10.0]),
    ],
)
def test_native_detailed_rejects_length_or_vector_mismatch(
    length: int,
    high: list[float],
    low: list[float],
    open_: list[float],
    close: list[float],
    volume: list[float],
) -> None:
    fqcopilot = _detailed_native()

    with pytest.raises(ValueError, match="every OHLCV vector length"):
        fqcopilot.fq_clxs_all_detailed(
            length, high, low, open_, close, volume, 1560, 0, 0
        )


def test_native_detailed_accepts_zero_length_vectors() -> None:
    fqcopilot = _detailed_native()

    detailed = fqcopilot.fq_clxs_all_detailed(0, [], [], [], [], [], 1560, 0, 0)

    assert detailed == {
        "signals_by_model": [[] for _ in range(18)],
        "buy_base_trigger_masks": [],
        "sell_base_trigger_masks": [],
    }
