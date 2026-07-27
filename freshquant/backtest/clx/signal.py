"""CLX signal wire-format contract.

The native engine stores only the primary trigger in the integer code.  A
future concurrent-trigger calculation can attach its seven-bit mask to the
decoded value without changing the wire format.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral

MODEL_IDS = tuple(range(18))
PRIMARY_ENTRYPOINT_IDS = tuple(range(1, 8))
MAX_OCCURRENCE = 99
MAX_LEGACY_SINGLE_DIGIT_OCCURRENCE = 9
# Backward-compatible constant name; the scalar format is not intrinsically
# self-describing once the row-aware protocol permits occurrence 10..99.
MAX_SELF_DESCRIBING_OCCURRENCE = MAX_LEGACY_SINGLE_DIGIT_OCCURRENCE
ALL_TRIGGER_MASK = (1 << len(PRIMARY_ENTRYPOINT_IDS)) - 1


class ClxSignalProtocolError(ValueError):
    """Raised when a value is outside the unambiguous CLX signal contract."""


@dataclass(frozen=True, slots=True)
class ClxSignal:
    """Decoded CLX signal.

    ``concurrent_trigger_mask`` is ``None`` until all same-bar trigger
    predicates have been evaluated.  When present, bits 0..6 represent
    entrypoints 1..7 and the primary-entrypoint bit must be set.
    """

    raw_value: int
    direction: int
    model_id: int
    occurrence: int
    primary_entrypoint: int
    concurrent_trigger_mask: int | None = None


def _as_protocol_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ClxSignalProtocolError(f"{name} must be an integer, got {value!r}")
    return int(value)


def _validate_fields(
    *,
    direction: object,
    model_id: object,
    occurrence: object,
    primary_entrypoint: object,
    max_occurrence: int = MAX_OCCURRENCE,
) -> tuple[int, int, int, int]:
    direction_int = _as_protocol_int("direction", direction)
    model_int = _as_protocol_int("model_id", model_id)
    occurrence_int = _as_protocol_int("occurrence", occurrence)
    entrypoint_int = _as_protocol_int("primary_entrypoint", primary_entrypoint)

    if direction_int not in (-1, 1):
        raise ClxSignalProtocolError("direction must be -1 or 1")
    if model_int not in MODEL_IDS:
        raise ClxSignalProtocolError("model_id must be in the inclusive range 0..17")
    if not 1 <= occurrence_int <= max_occurrence:
        raise ClxSignalProtocolError(f"occurrence must be in 1..{max_occurrence}")
    if entrypoint_int not in PRIMARY_ENTRYPOINT_IDS:
        raise ClxSignalProtocolError("primary_entrypoint must be in 1..7")
    return direction_int, model_int, occurrence_int, entrypoint_int


def _validate_trigger_mask(mask: object | None, primary_entrypoint: int) -> int | None:
    if mask is None:
        return None
    mask_int = _as_protocol_int("concurrent_trigger_mask", mask)
    if mask_int < 0 or mask_int & ~ALL_TRIGGER_MASK:
        raise ClxSignalProtocolError("concurrent_trigger_mask must use only bits 0..6")
    primary_bit = 1 << (primary_entrypoint - 1)
    if not mask_int & primary_bit:
        raise ClxSignalProtocolError(
            "concurrent_trigger_mask must include the primary entrypoint bit"
        )
    return mask_int


def encode_signal(
    *, direction: int, model_id: int, occurrence: int, primary_entrypoint: int
) -> int:
    """Encode a non-zero CLX signal using the model-row-aware layout."""

    direction_int, model_int, occurrence_int, entrypoint_int = _validate_fields(
        direction=direction,
        model_id=model_id,
        occurrence=occurrence,
        primary_entrypoint=primary_entrypoint,
    )
    magnitude = model_int * 1000 + occurrence_int * 100 + entrypoint_int
    return direction_int * magnitude


def decode_signal(
    raw_value: int,
    *,
    expected_model_id: int,
    concurrent_trigger_mask: int | None = None,
) -> ClxSignal | None:
    """Decode a CLX integer with its model-row context.

    The model row makes occurrence values 1..99 losslessly recoverable even
    when occurrence >=10 overlaps the digits normally read as ``model_id``.
    Zero remains the no-signal value.
    """

    raw_int = _as_protocol_int("raw_value", raw_value)
    if raw_int == 0:
        if concurrent_trigger_mask is not None:
            raise ClxSignalProtocolError("a zero signal cannot carry a trigger mask")
        return None

    direction = 1 if raw_int > 0 else -1
    magnitude = abs(raw_int)

    model_id = _as_protocol_int("expected_model_id", expected_model_id)
    if model_id not in MODEL_IDS:
        raise ClxSignalProtocolError(
            "expected_model_id must be in the inclusive range 0..17"
        )
    remainder = magnitude - model_id * 1000
    if remainder <= 0:
        raise ClxSignalProtocolError(
            f"signal {raw_int} does not belong to model row {model_id}"
        )

    occurrence, primary_entrypoint = divmod(remainder, 100)
    direction, model_id, occurrence, primary_entrypoint = _validate_fields(
        direction=direction,
        model_id=model_id,
        occurrence=occurrence,
        primary_entrypoint=primary_entrypoint,
    )
    trigger_mask = _validate_trigger_mask(concurrent_trigger_mask, primary_entrypoint)
    return ClxSignal(
        raw_value=raw_int,
        direction=direction,
        model_id=model_id,
        occurrence=occurrence,
        primary_entrypoint=primary_entrypoint,
        concurrent_trigger_mask=trigger_mask,
    )


def decode_legacy_single_digit_signal(
    raw_value: int, *, concurrent_trigger_mask: int | None = None
) -> ClxSignal | None:
    """Apply the legacy one-occurrence-digit convention to a scalar code.

    This is a compatibility interpretation, not proof that a scalar is
    intrinsically unambiguous.  For example, 17101 can mean model 17 /
    occurrence 1 under this convention or model 16 / occurrence 11 with row
    context.  Use :func:`decode_signal` with a trusted model row for native
    batch data.
    """

    raw_int = _as_protocol_int("raw_value", raw_value)
    if raw_int == 0:
        if concurrent_trigger_mask is not None:
            raise ClxSignalProtocolError("a zero signal cannot carry a trigger mask")
        return None

    direction = 1 if raw_int > 0 else -1
    model_id, remainder = divmod(abs(raw_int), 1000)
    occurrence, primary_entrypoint = divmod(remainder, 100)
    direction, model_id, occurrence, primary_entrypoint = _validate_fields(
        direction=direction,
        model_id=model_id,
        occurrence=occurrence,
        primary_entrypoint=primary_entrypoint,
        max_occurrence=MAX_LEGACY_SINGLE_DIGIT_OCCURRENCE,
    )
    trigger_mask = _validate_trigger_mask(concurrent_trigger_mask, primary_entrypoint)
    return ClxSignal(
        raw_value=raw_int,
        direction=direction,
        model_id=model_id,
        occurrence=occurrence,
        primary_entrypoint=primary_entrypoint,
        concurrent_trigger_mask=trigger_mask,
    )


def decode_self_describing_signal(
    raw_value: int, *, concurrent_trigger_mask: int | None = None
) -> ClxSignal | None:
    """Compatibility alias for :func:`decode_legacy_single_digit_signal`."""

    return decode_legacy_single_digit_signal(
        raw_value, concurrent_trigger_mask=concurrent_trigger_mask
    )
