"""CLX batch backtest engine contracts."""

from .engine import (
    MODEL_COUNT,
    ClxBatchResult,
    ClxEngineInputError,
    ClxEngineOptions,
    ClxEngineProtocolError,
    FqCopilotClxEngine,
)
from .signal import (
    ALL_TRIGGER_MASK,
    MAX_LEGACY_SINGLE_DIGIT_OCCURRENCE,
    MAX_OCCURRENCE,
    MAX_SELF_DESCRIBING_OCCURRENCE,
    MODEL_IDS,
    PRIMARY_ENTRYPOINT_IDS,
    ClxSignal,
    ClxSignalProtocolError,
    decode_legacy_single_digit_signal,
    decode_self_describing_signal,
    decode_signal,
    encode_signal,
)

__all__ = [
    "ALL_TRIGGER_MASK",
    "MAX_LEGACY_SINGLE_DIGIT_OCCURRENCE",
    "MAX_OCCURRENCE",
    "MAX_SELF_DESCRIBING_OCCURRENCE",
    "MODEL_COUNT",
    "MODEL_IDS",
    "PRIMARY_ENTRYPOINT_IDS",
    "ClxBatchResult",
    "ClxEngineInputError",
    "ClxEngineOptions",
    "ClxEngineProtocolError",
    "ClxSignal",
    "ClxSignalProtocolError",
    "FqCopilotClxEngine",
    "decode_signal",
    "decode_legacy_single_digit_signal",
    "decode_self_describing_signal",
    "encode_signal",
]
