from __future__ import annotations

import pytest

from freshquant.backtest.clx import (
    ClxSignalProtocolError,
    decode_legacy_single_digit_signal,
    decode_self_describing_signal,
    decode_signal,
    encode_signal,
)


@pytest.mark.parametrize(
    ("direction", "model_id", "occurrence", "primary_entrypoint", "raw_value"),
    [
        (1, 0, 1, 5, 105),
        (-1, 0, 3, 5, -305),
        (1, 16, 2, 7, 16207),
        (-1, 16, 1, 1, -16101),
        (1, 17, 9, 7, 17907),
    ],
)
def test_self_describing_signal_round_trip(
    direction: int,
    model_id: int,
    occurrence: int,
    primary_entrypoint: int,
    raw_value: int,
) -> None:
    assert (
        encode_signal(
            direction=direction,
            model_id=model_id,
            occurrence=occurrence,
            primary_entrypoint=primary_entrypoint,
        )
        == raw_value
    )

    decoded = decode_legacy_single_digit_signal(raw_value)
    assert decoded is not None
    assert decoded.direction == direction
    assert decoded.model_id == model_id
    assert decoded.occurrence == occurrence
    assert decoded.primary_entrypoint == primary_entrypoint
    assert decoded.concurrent_trigger_mask is None


def test_model_row_context_preserves_two_digit_occurrence() -> None:
    raw_value = encode_signal(
        direction=1,
        model_id=16,
        occurrence=10,
        primary_entrypoint=1,
    )
    assert raw_value == 17001

    decoded = decode_signal(raw_value, expected_model_id=16)
    assert decoded is not None
    assert (decoded.model_id, decoded.occurrence, decoded.primary_entrypoint) == (
        16,
        10,
        1,
    )

    with pytest.raises(ClxSignalProtocolError, match="occurrence"):
        decode_legacy_single_digit_signal(raw_value)


def test_adjacent_model_signal_remains_distinct_with_row_context() -> None:
    model_17_value = encode_signal(
        direction=1,
        model_id=17,
        occurrence=1,
        primary_entrypoint=1,
    )
    assert model_17_value == 17101

    decoded = decode_signal(model_17_value, expected_model_id=17)
    assert decoded is not None
    assert (decoded.model_id, decoded.occurrence, decoded.primary_entrypoint) == (
        17,
        1,
        1,
    )


def test_scalar_decode_is_ambiguous_without_row_context_for_occurrence_99() -> None:
    raw_value = encode_signal(
        direction=-1,
        model_id=0,
        occurrence=99,
        primary_entrypoint=7,
    )
    decoded = decode_signal(raw_value, expected_model_id=0)
    assert decoded is not None
    assert decoded.occurrence == 99

    legacy_interpretation = decode_legacy_single_digit_signal(raw_value)
    assert legacy_interpretation is not None
    assert (legacy_interpretation.model_id, legacy_interpretation.occurrence) == (9, 9)
    assert (legacy_interpretation.model_id, legacy_interpretation.occurrence) != (0, 99)


def test_zero_is_the_no_signal_value() -> None:
    assert decode_signal(0, expected_model_id=0) is None
    assert decode_self_describing_signal(0) is None


def test_concurrent_trigger_mask_is_separate_from_primary_entrypoint() -> None:
    pinbar_and_macd = (1 << (2 - 1)) | (1 << (7 - 1))
    decoded = decode_signal(
        16102,
        expected_model_id=16,
        concurrent_trigger_mask=pinbar_and_macd,
    )
    assert decoded is not None
    assert decoded.primary_entrypoint == 2
    assert decoded.concurrent_trigger_mask == pinbar_and_macd

    with pytest.raises(ClxSignalProtocolError, match="primary entrypoint"):
        decode_signal(16102, expected_model_id=16, concurrent_trigger_mask=1 << 6)


@pytest.mark.parametrize(
    "fields",
    [
        {"direction": 0, "model_id": 1, "occurrence": 1, "primary_entrypoint": 1},
        {"direction": True, "model_id": 1, "occurrence": 1, "primary_entrypoint": 1},
        {"direction": 1, "model_id": 18, "occurrence": 1, "primary_entrypoint": 1},
        {"direction": 1, "model_id": 1, "occurrence": 0, "primary_entrypoint": 1},
        {"direction": 1, "model_id": 1, "occurrence": 100, "primary_entrypoint": 1},
        {"direction": 1, "model_id": 1, "occurrence": 1, "primary_entrypoint": 0},
        {"direction": 1, "model_id": 1, "occurrence": 1, "primary_entrypoint": 8},
    ],
)
def test_encoder_rejects_values_outside_wire_contract(fields: dict[str, int]) -> None:
    with pytest.raises(ClxSignalProtocolError):
        encode_signal(**fields)


def test_decoder_rejects_signal_from_wrong_model_row() -> None:
    with pytest.raises(ClxSignalProtocolError):
        decode_signal(16101, expected_model_id=17)
