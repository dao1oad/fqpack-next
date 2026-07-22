"""Validated Python contract around ``fqcopilot.fq_clxs_all``."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from numbers import Integral
from typing import Any, Sequence

import numpy as np

from .signal import ALL_TRIGGER_MASK, ClxSignal, MODEL_IDS, decode_signal

MODEL_COUNT = len(MODEL_IDS)


class ClxEngineInputError(ValueError):
    """Raised before native code is called when OHLCV input is invalid."""


class ClxEngineProtocolError(RuntimeError):
    """Raised when the native batch result violates its 18-by-N contract."""


def _require_nonnegative_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ClxEngineInputError(f"{name} must be an integer, got {value!r}")
    value_int = int(value)
    if value_int < 0:
        raise ClxEngineInputError(f"{name} must be non-negative")
    return value_int


@dataclass(frozen=True, slots=True)
class ClxEngineOptions:
    """Native CLX options for the frozen research baseline.

    The defaults are ``1560/0/0`` from the installed formula.  The native
    ``trend_opt`` argument is also S0015's ``ext_opt``; using one would select
    MA1 instead of S0015's zero-value default MA250.  Batch mode always uses
    the native switch option zero.
    """

    wave_opt: int = 1560
    stretch_opt: int = 0
    trend_opt: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "wave_opt", _require_nonnegative_int("wave_opt", self.wave_opt)
        )
        object.__setattr__(
            self,
            "stretch_opt",
            _require_nonnegative_int("stretch_opt", self.stretch_opt),
        )
        object.__setattr__(
            self, "trend_opt", _require_nonnegative_int("trend_opt", self.trend_opt)
        )


@dataclass(frozen=True, slots=True)
class ClxBatchResult:
    """Immutable model-major signals plus optional shared base-trigger masks.

    Native detailed output contains only direction-specific shared predicate
    facts and may omit a model-specific or legacy-overloaded primary bit.
    :meth:`decoded_at` completes the per-event mask by unioning its primary bit
    without mutating the stored base masks.
    """

    signals_by_model: tuple[tuple[int, ...], ...]
    bar_count: int
    buy_base_trigger_masks: tuple[int, ...] | None = None
    sell_base_trigger_masks: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        has_buy = self.buy_base_trigger_masks is not None
        has_sell = self.sell_base_trigger_masks is not None
        if has_buy != has_sell:
            raise ClxEngineProtocolError(
                "buy and sell base trigger masks must be present together"
            )
        if has_buy and (
            len(self.buy_base_trigger_masks or ()) != self.bar_count
            or len(self.sell_base_trigger_masks or ()) != self.bar_count
        ):
            raise ClxEngineProtocolError(
                "base trigger mask rows must match the result bar count"
            )

    @property
    def shape(self) -> tuple[int, int]:
        return MODEL_COUNT, self.bar_count

    @property
    def has_concurrent_trigger_masks(self) -> bool:
        return self.buy_base_trigger_masks is not None

    def for_model(self, model_id: int) -> tuple[int, ...]:
        if isinstance(model_id, bool) or not isinstance(model_id, Integral):
            raise IndexError(f"model_id must be in 0..17, got {model_id!r}")
        model_int = int(model_id)
        if model_int not in MODEL_IDS:
            raise IndexError(f"model_id must be in 0..17, got {model_id!r}")
        return self.signals_by_model[model_int]

    def decoded_at(self, model_id: int, bar_index: int) -> ClxSignal | None:
        row = self.for_model(model_id)
        if isinstance(bar_index, bool) or not isinstance(bar_index, Integral):
            raise IndexError(f"bar_index must be in 0..{self.bar_count - 1}")
        index_int = int(bar_index)
        if not 0 <= index_int < self.bar_count:
            raise IndexError(f"bar_index must be in 0..{self.bar_count - 1}")

        raw_value = row[index_int]
        decoded = decode_signal(raw_value, expected_model_id=int(model_id))
        if decoded is None or not self.has_concurrent_trigger_masks:
            return decoded

        base_masks = (
            self.buy_base_trigger_masks
            if decoded.direction > 0
            else self.sell_base_trigger_masks
        )
        assert base_masks is not None
        concurrent_mask = base_masks[index_int]
        primary_bit = 1 << (decoded.primary_entrypoint - 1)
        concurrent_mask |= primary_bit
        return decode_signal(
            raw_value,
            expected_model_id=int(model_id),
            concurrent_trigger_mask=concurrent_mask,
        )


def _numeric_vector(name: str, values: Sequence[float]) -> tuple[float, ...]:
    if isinstance(values, (str, bytes)):
        raise ClxEngineInputError(f"{name} must be a one-dimensional numeric sequence")
    try:
        raw_values = tuple(values)
    except TypeError as exc:
        raise ClxEngineInputError(
            f"{name} must be a one-dimensional numeric sequence"
        ) from exc

    converted: list[float] = []
    for index, value in enumerate(raw_values):
        if isinstance(value, bool):
            raise ClxEngineInputError(f"{name}[{index}] must be a finite number")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ClxEngineInputError(
                f"{name}[{index}] must be a finite number"
            ) from exc
        if not math.isfinite(number):
            raise ClxEngineInputError(f"{name}[{index}] must be a finite number")
        converted.append(number)
    return tuple(converted)


def _validate_ohlcv(
    high: Sequence[float],
    low: Sequence[float],
    open_: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
) -> tuple[tuple[float, ...], ...]:
    vectors = (
        _numeric_vector("high", high),
        _numeric_vector("low", low),
        _numeric_vector("open", open_),
        _numeric_vector("close", close),
        _numeric_vector("volume", volume),
    )
    lengths = tuple(len(vector) for vector in vectors)
    if lengths[0] == 0:
        raise ClxEngineInputError("OHLCV input must contain at least one bar")
    if len(set(lengths)) != 1:
        raise ClxEngineInputError(
            "OHLCV vectors must have equal lengths; "
            f"got high/low/open/close/volume={lengths}"
        )
    return vectors


def _normalise_batch_output(raw_output: object, bar_count: int) -> ClxBatchResult:
    if isinstance(raw_output, (str, bytes)):
        raise ClxEngineProtocolError("fq_clxs_all output must contain 18 model rows")
    try:
        raw_rows = tuple(raw_output)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ClxEngineProtocolError(
            "fq_clxs_all output must contain 18 model rows"
        ) from exc

    if len(raw_rows) != MODEL_COUNT:
        raise ClxEngineProtocolError(
            f"fq_clxs_all returned {len(raw_rows)} model rows; expected {MODEL_COUNT}"
        )

    rows: list[tuple[int, ...]] = []
    for model_id, raw_row in enumerate(raw_rows):
        if isinstance(raw_row, (str, bytes)):
            raise ClxEngineProtocolError(f"model {model_id} output is not a signal row")
        try:
            values = tuple(raw_row)
        except TypeError as exc:
            raise ClxEngineProtocolError(
                f"model {model_id} output is not a signal row"
            ) from exc
        if len(values) != bar_count:
            raise ClxEngineProtocolError(
                f"model {model_id} returned {len(values)} bars; expected {bar_count}"
            )

        row: list[int] = []
        for bar_index, value in enumerate(values):
            if isinstance(value, bool):
                raise ClxEngineProtocolError(
                    f"model {model_id} bar {bar_index} signal must be an integer"
                )
            try:
                numeric = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ClxEngineProtocolError(
                    f"model {model_id} bar {bar_index} signal must be an integer"
                ) from exc
            if not math.isfinite(numeric) or not numeric.is_integer():
                raise ClxEngineProtocolError(
                    f"model {model_id} bar {bar_index} signal must be an integer"
                )
            signal_value = int(numeric)
            if signal_value:
                # Row context preserves occurrence >=10 despite model-digit overlap.
                decode_signal(signal_value, expected_model_id=model_id)
            row.append(signal_value)
        rows.append(tuple(row))
    return ClxBatchResult(tuple(rows), bar_count)


def _normalise_base_trigger_masks(
    name: str, raw_masks: object, bar_count: int
) -> tuple[int, ...]:
    if isinstance(raw_masks, (str, bytes)):
        raise ClxEngineProtocolError(f"{name} must contain one mask per bar")
    try:
        values = tuple(raw_masks)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ClxEngineProtocolError(
            f"{name} must contain one mask per bar"
        ) from exc
    if len(values) != bar_count:
        raise ClxEngineProtocolError(
            f"{name} returned {len(values)} bars; expected {bar_count}"
        )

    masks: list[int] = []
    for bar_index, value in enumerate(values):
        if isinstance(value, bool):
            raise ClxEngineProtocolError(
                f"{name} bar {bar_index} mask must be an integer"
            )
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ClxEngineProtocolError(
                f"{name} bar {bar_index} mask must be an integer"
            ) from exc
        if not math.isfinite(numeric) or not numeric.is_integer():
            raise ClxEngineProtocolError(
                f"{name} bar {bar_index} mask must be an integer"
            )
        mask = int(numeric)
        if mask < 0 or mask & ~ALL_TRIGGER_MASK:
            raise ClxEngineProtocolError(
                f"{name} bar {bar_index} mask must use only bits 0..6"
            )
        if mask & 1:
            raise ClxEngineProtocolError(
                f"{name} bar {bar_index} base mask must leave entrypoint 1 clear"
            )
        masks.append(mask)
    return tuple(masks)


def _normalise_detailed_batch_output(
    raw_output: object, bar_count: int
) -> ClxBatchResult:
    if not isinstance(raw_output, Mapping):
        raise ClxEngineProtocolError(
            "fq_clxs_all_detailed output must be a structured mapping"
        )
    required = (
        "signals_by_model",
        "buy_base_trigger_masks",
        "sell_base_trigger_masks",
    )
    missing = [key for key in required if key not in raw_output]
    if missing:
        raise ClxEngineProtocolError(
            "fq_clxs_all_detailed output is missing " + ", ".join(missing)
        )

    native_result = _try_normalise_native_detailed_batch_output(raw_output, bar_count)
    if native_result is not None:
        return native_result

    raw_result = _normalise_batch_output(raw_output["signals_by_model"], bar_count)
    buy_masks = _normalise_base_trigger_masks(
        "buy_base_trigger_masks", raw_output["buy_base_trigger_masks"], bar_count
    )
    sell_masks = _normalise_base_trigger_masks(
        "sell_base_trigger_masks", raw_output["sell_base_trigger_masks"], bar_count
    )

    return ClxBatchResult(
        raw_result.signals_by_model,
        bar_count,
        buy_base_trigger_masks=buy_masks,
        sell_base_trigger_masks=sell_masks,
    )


def _native_integer_array(value: object, shape: tuple[int, ...]) -> np.ndarray | None:
    """Return a signed native-integer view, or defer to the generic validator."""

    try:
        array = np.asarray(value)
    except (TypeError, ValueError):
        return None
    if array.shape != shape or array.dtype.kind not in {"i", "u"}:
        return None
    if array.dtype.kind == "u" and array.size:
        if int(array.max()) > np.iinfo(np.int64).max:
            return None
    return array.astype(np.int64, copy=False)


def _try_normalise_native_detailed_batch_output(
    raw_output: Mapping[str, object], bar_count: int
) -> ClxBatchResult | None:
    """Vector-validate the integer lists emitted by the compiled backend.

    Custom backends commonly use floats, objects, generators, or malformed
    nested rows in protocol tests.  Those representations deliberately fall
    through to the original scalar validator so its acceptance and exception
    contracts stay unchanged.
    """

    signals = _native_integer_array(
        raw_output["signals_by_model"], (MODEL_COUNT, bar_count)
    )
    buy = _native_integer_array(raw_output["buy_base_trigger_masks"], (bar_count,))
    sell = _native_integer_array(raw_output["sell_base_trigger_masks"], (bar_count,))
    if signals is None or buy is None or sell is None:
        return None

    if np.any(signals == np.iinfo(np.int64).min):
        return None
    magnitude = np.abs(signals)
    model_offsets = np.arange(MODEL_COUNT, dtype=np.int64)[:, None] * 1000
    remainder = magnitude - model_offsets
    occurrence = remainder // 100
    entrypoint = remainder % 100
    nonzero = signals != 0
    invalid_signal = nonzero & (
        (remainder <= 0)
        | (occurrence < 1)
        | (occurrence > 99)
        | (entrypoint < 1)
        | (entrypoint > 7)
    )
    invalid_mask = (
        (buy < 0)
        | ((buy & ~ALL_TRIGGER_MASK) != 0)
        | ((buy & 1) != 0)
        | (sell < 0)
        | ((sell & ~ALL_TRIGGER_MASK) != 0)
        | ((sell & 1) != 0)
    )
    if np.any(invalid_signal) or np.any(invalid_mask):
        return None

    return ClxBatchResult(
        tuple(tuple(row) for row in signals.tolist()),
        bar_count,
        buy_base_trigger_masks=tuple(buy.tolist()),
        sell_base_trigger_masks=tuple(sell.tolist()),
    )


class FqCopilotClxEngine:
    """Small validated adapter for the compiled ``fqcopilot`` module."""

    def __init__(self, backend: Any | None = None) -> None:
        self._backend = backend if backend is not None else import_module("fqcopilot")
        has_batch = callable(getattr(self._backend, "fq_clxs_all", None))
        has_detailed = callable(
            getattr(self._backend, "fq_clxs_all_detailed", None)
        )
        if not has_batch and not has_detailed:
            raise ClxEngineProtocolError(
                "fqcopilot backend has no callable CLX batch interface"
            )

    @property
    def supports_detailed_output(self) -> bool:
        return callable(getattr(self._backend, "fq_clxs_all_detailed", None))

    def calculate_all(
        self,
        high: Sequence[float],
        low: Sequence[float],
        open_: Sequence[float],
        close: Sequence[float],
        volume: Sequence[float],
        *,
        options: ClxEngineOptions | None = None,
    ) -> ClxBatchResult:
        """Calculate and validate the complete S0000..S0017 signal matrix."""

        high_values, low_values, open_values, close_values, volume_values = (
            _validate_ohlcv(high, low, open_, close, volume)
        )
        effective_options = options if options is not None else ClxEngineOptions()
        if not isinstance(effective_options, ClxEngineOptions):
            raise ClxEngineInputError("options must be a ClxEngineOptions instance")

        bar_count = len(high_values)
        native_args = (
            bar_count,
            high_values,
            low_values,
            open_values,
            close_values,
            volume_values,
            effective_options.wave_opt,
            effective_options.stretch_opt,
            effective_options.trend_opt,
        )
        if self.supports_detailed_output:
            raw_output = self._backend.fq_clxs_all_detailed(*native_args)
            return _normalise_detailed_batch_output(raw_output, bar_count)

        raw_output = self._backend.fq_clxs_all(*native_args)
        return _normalise_batch_output(raw_output, bar_count)
