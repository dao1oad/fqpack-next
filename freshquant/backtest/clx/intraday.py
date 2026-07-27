"""Causal primitives for the CLX 30-minute research path.

The daily snapshot and signal-fact schemas are intentionally left unchanged.
This module contains the small, pure core needed to validate QuantAxis
``stock_min`` documents, replay CLX prefixes with timestamp clocks, and match
entries/exits without looking through the current session.
"""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any, cast

import numpy as np
import pandas as pd

from .engine import MODEL_COUNT, ClxEngineOptions
from .signal import decode_signal

SHANGHAI_TIMEZONE = "Asia/Shanghai"
MONGO_MINUTE_TYPE = "30min"
BAR_SLOT_CLOCKS = (
    "10:00",
    "10:30",
    "11:00",
    "11:30",
    "13:30",
    "14:00",
    "14:30",
    "15:00",
)
BAR_SLOT_BY_CLOCK = {clock: slot for slot, clock in enumerate(BAR_SLOT_CLOCKS)}
HORIZONS = (30, 60, 90)
FEE_PER_SIDE = 0.002
LIMIT_MOVE = 0.095
EVENT_KINDS = ("ADD", "REPLACE", "REMOVE")

_BAR_COLUMNS = (
    "code",
    "bar_at",
    "trade_date",
    "trade_year",
    "session_no",
    "bar_no",
    "bar_slot",
    "bar_slot_label",
    "source_time_stamp",
    "source_date_stamp",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "raw_volume",
    "raw_amount",
    "adj_factor",
    "qfq_open",
    "qfq_high",
    "qfq_low",
    "qfq_close",
    "prior_close_date",
    "prior_raw_daily_close",
    "source_duplicate_count",
)
_DUPLICATE_VALUE_FIELDS = (
    "trade_date",
    "bar_slot",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "raw_volume",
    "raw_amount",
    "source_date_stamp",
)


class IntradayDataError(RuntimeError):
    """Raised when an intraday input violates the frozen causal contract."""


def _finite_float(value: object, *, field: str) -> float:
    if isinstance(value, bool) or value is None:
        raise IntradayDataError(f"{field} must be a finite number")
    try:
        number = float(cast(Any, value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise IntradayDataError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise IntradayDataError(f"{field} must be a finite number")
    return number


def _local_timestamp(value: object, *, field: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise IntradayDataError(f"{field} is not a valid timestamp") from exc
    if pd.isna(timestamp):
        raise IntradayDataError(f"{field} is not a valid timestamp")
    try:
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(SHANGHAI_TIMEZONE)
        else:
            timestamp = timestamp.tz_convert(SHANGHAI_TIMEZONE)
    except (TypeError, ValueError) as exc:
        raise IntradayDataError(f"{field} is not a valid timestamp") from exc
    return timestamp


def _calendar_date(value: object, *, field: str) -> date:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise IntradayDataError(f"{field} is not a valid date") from exc
    if pd.isna(timestamp):
        raise IntradayDataError(f"{field} is not a valid date")
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(SHANGHAI_TIMEZONE)
    return timestamp.date()


def _same_duplicate_values(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return all(left[field] == right[field] for field in _DUPLICATE_VALUE_FIELDS)


def _normalise_minute_document(document: Mapping[str, Any]) -> dict[str, Any]:
    code = str(document.get("code", "")).strip()
    if not code:
        raise IntradayDataError("30min document has no code")
    bar_at = _local_timestamp(document.get("datetime"), field=f"{code}.datetime")
    if bar_at.second or bar_at.microsecond:
        raise IntradayDataError(
            f"unsupported 30min bar slot for {code}: {bar_at.isoformat()}"
        )
    clock = bar_at.strftime("%H:%M")
    try:
        bar_slot = BAR_SLOT_BY_CLOCK[clock]
    except KeyError as exc:
        raise IntradayDataError(
            f"unsupported 30min bar slot for {code}: {bar_at.isoformat()}"
        ) from exc

    trade_date = _calendar_date(document.get("date"), field=f"{code}.date")
    if trade_date != bar_at.date():
        raise IntradayDataError(
            f"30min date/datetime disagree for {code}: "
            f"{trade_date.isoformat()} != {bar_at.date().isoformat()}"
        )

    source_time_stamp = _finite_float(
        document.get("time_stamp"), field=f"{code}.time_stamp"
    )
    if not math.isclose(
        source_time_stamp, bar_at.timestamp(), rel_tol=0.0, abs_tol=0.5
    ):
        raise IntradayDataError(
            f"30min datetime/time_stamp disagree for {code}/{bar_at.isoformat()}"
        )
    source_date_stamp = _finite_float(
        document.get("date_stamp"), field=f"{code}.date_stamp"
    )

    prices = {
        field: _finite_float(document.get(field), field=f"{code}.{field}")
        for field in ("open", "high", "low", "close")
    }
    if any(value <= 0 for value in prices.values()):
        raise IntradayDataError(f"30min prices must be positive for {code}")
    if not (
        prices["high"] >= max(prices["open"], prices["close"])
        and prices["low"] <= min(prices["open"], prices["close"])
        and prices["high"] >= prices["low"]
    ):
        raise IntradayDataError(
            f"invalid 30min OHLC shape for {code}/{bar_at.isoformat()}"
        )
    raw_volume = _finite_float(document.get("vol"), field=f"{code}.vol")
    raw_amount = _finite_float(document.get("amount"), field=f"{code}.amount")
    if raw_volume < 0 or raw_amount < 0:
        raise IntradayDataError(
            f"30min volume and amount must be non-negative for {code}"
        )
    return {
        "code": code,
        "bar_at": bar_at,
        "trade_date": trade_date,
        "bar_slot": bar_slot,
        "source_time_stamp": source_time_stamp,
        "source_date_stamp": source_date_stamp,
        "raw_open": prices["open"],
        "raw_high": prices["high"],
        "raw_low": prices["low"],
        "raw_close": prices["close"],
        "raw_volume": raw_volume,
        "raw_amount": raw_amount,
        "source_duplicate_count": 1,
    }


def _factor_by_key(
    documents: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, date], float]:
    result: dict[tuple[str, date], float] = {}
    for document in documents:
        code = str(document.get("code", "")).strip()
        if not code:
            raise IntradayDataError("stock_adj document has no code")
        trade_date = _calendar_date(document.get("date"), field=f"{code}.adj.date")
        factor = _finite_float(document.get("adj"), field=f"{code}.adj")
        if factor <= 0:
            raise IntradayDataError(
                f"stock_adj factor must be positive for {code}/{trade_date}"
            )
        key = (code, trade_date)
        previous = result.get(key)
        if previous is not None and previous != factor:
            raise IntradayDataError(
                f"conflicting stock_adj duplicate for {code}/{trade_date}"
            )
        result[key] = factor
    return result


def _daily_closes(
    documents: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[list[date], list[float]]]:
    keyed: dict[tuple[str, date], float] = {}
    for document in documents:
        code = str(document.get("code", "")).strip()
        if not code:
            raise IntradayDataError("stock_day document has no code")
        trade_date = _calendar_date(
            document.get("date"), field=f"{code}.stock_day.date"
        )
        close = _finite_float(document.get("close"), field=f"{code}.stock_day.close")
        if close <= 0:
            raise IntradayDataError(
                f"stock_day close must be positive for {code}/{trade_date}"
            )
        key = (code, trade_date)
        previous = keyed.get(key)
        if previous is not None and previous != close:
            raise IntradayDataError(
                f"conflicting stock_day duplicate for {code}/{trade_date}"
            )
        keyed[key] = close

    grouped: defaultdict[str, list[tuple[date, float]]] = defaultdict(list)
    for (code, trade_date), close in keyed.items():
        grouped[code].append((trade_date, close))
    result: dict[str, tuple[list[date], list[float]]] = {}
    for code, rows in grouped.items():
        rows.sort()
        result[code] = (
            [trade_date for trade_date, _ in rows],
            [close for _, close in rows],
        )
    return result


def build_intraday_bars(
    *,
    minute_docs: Iterable[Mapping[str, Any]],
    adj_docs: Iterable[Mapping[str, Any]],
    daily_docs: Iterable[Mapping[str, Any]],
) -> pd.DataFrame:
    """Build deterministic 30-minute bars from projected Mongo documents.

    ``stock_min`` is filtered to the literal QuantAxis value ``"30min"``.
    Exact repeated source rows are collapsed by ``(code, type, time_stamp)``;
    a duplicate key with different market values is rejected.
    """

    unique: dict[tuple[str, str, float], dict[str, Any]] = {}
    for document in minute_docs:
        if document.get("type") != MONGO_MINUTE_TYPE:
            continue
        row = _normalise_minute_document(document)
        key = (row["code"], MONGO_MINUTE_TYPE, row["source_time_stamp"])
        previous = unique.get(key)
        if previous is None:
            unique[key] = row
            continue
        if not _same_duplicate_values(previous, row):
            raise IntradayDataError(
                "conflicting duplicate 30min key "
                f"{row['code']}/{row['bar_at'].isoformat()}"
            )
        previous["source_duplicate_count"] += 1

    if not unique:
        return pd.DataFrame(columns=_BAR_COLUMNS)

    factors = _factor_by_key(adj_docs)
    closes = _daily_closes(daily_docs)
    rows = sorted(unique.values(), key=lambda item: (item["code"], item["bar_at"]))
    session_by_date = {
        trade_date: number
        for number, trade_date in enumerate(
            sorted({row["trade_date"] for row in rows}), start=1
        )
    }
    bar_number_by_code: defaultdict[str, int] = defaultdict(int)
    output: list[dict[str, Any]] = []
    for row in rows:
        code = row["code"]
        trade_date = row["trade_date"]
        factor = factors.get((code, trade_date))
        if factor is None:
            raise IntradayDataError(
                f"missing stock_adj factor for {code}/{trade_date.isoformat()}"
            )
        prior_close_date: date | None = None
        prior_close = math.nan
        code_closes = closes.get(code)
        if code_closes is not None:
            dates, values = code_closes
            prior_index = bisect_left(dates, trade_date) - 1
            if prior_index >= 0:
                prior_close_date = dates[prior_index]
                prior_close = values[prior_index]

        bar_number_by_code[code] += 1
        raw_prices = {
            field: row[f"raw_{field}"] for field in ("open", "high", "low", "close")
        }
        output.append(
            {
                **row,
                "trade_year": trade_date.year,
                "session_no": session_by_date[trade_date],
                "bar_no": bar_number_by_code[code],
                "bar_slot_label": BAR_SLOT_CLOCKS[row["bar_slot"]],
                "adj_factor": factor,
                **{
                    f"qfq_{field}": price * factor
                    for field, price in raw_prices.items()
                },
                "prior_close_date": prior_close_date,
                "prior_raw_daily_close": prior_close,
            }
        )
    return (
        pd.DataFrame(output)
        .loc[:, _BAR_COLUMNS]
        .sort_values(["code", "bar_at"], kind="stable")
        .reset_index(drop=True)
    )


def attach_previous_session_regimes(
    events: pd.DataFrame,
    index: pd.DataFrame,
    *,
    reveal_column: str = "reveal_at",
    index_date_column: str = "date",
) -> pd.DataFrame:
    """Attach only the latest index feature date strictly before the signal day."""

    if reveal_column not in events.columns:
        raise IntradayDataError(f"events miss {reveal_column}")
    if index_date_column not in index.columns:
        raise IntradayDataError(f"index miss {index_date_column}")

    left = events.copy()
    left["_event_order"] = np.arange(len(left), dtype=np.int64)
    left[reveal_column] = [
        _local_timestamp(value, field=reveal_column) for value in left[reveal_column]
    ]
    left["_reveal_trade_date"] = pd.to_datetime(
        [value.date() for value in left[reveal_column]]
    )

    right = index.copy()
    right["index_feature_date"] = pd.to_datetime(
        [
            _calendar_date(value, field=index_date_column)
            for value in right[index_date_column]
        ]
    )
    right = (
        right.drop(columns=[index_date_column])
        .sort_values("index_feature_date", kind="stable")
        .drop_duplicates("index_feature_date", keep="last")
    )
    overlapping = set(left.columns) & (set(right.columns) - {"index_feature_date"}) - {
        "_event_order",
        "_reveal_trade_date",
    }
    if overlapping:
        raise IntradayDataError(
            f"events already contain index feature columns: {sorted(overlapping)}"
        )

    merged = pd.merge_asof(
        left.sort_values("_reveal_trade_date", kind="stable"),
        right,
        left_on="_reveal_trade_date",
        right_on="index_feature_date",
        direction="backward",
        allow_exact_matches=False,
    )
    known = merged["index_feature_date"].notna()
    if (
        merged.loc[known, "index_feature_date"]
        >= merged.loc[known, "_reveal_trade_date"]
    ).any():
        raise IntradayDataError("index regime must be strictly prior to reveal day")
    return (
        merged.sort_values("_event_order", kind="stable")
        .drop(columns=["_event_order", "_reveal_trade_date"])
        .reset_index(drop=True)
    )


def _prepare_execution_bars(bars: pd.DataFrame) -> pd.DataFrame:
    required = {
        "bar_at",
        "trade_date",
        "bar_slot",
        "raw_open",
        "qfq_open",
        "prior_raw_daily_close",
    }
    missing = required - set(bars.columns)
    if missing:
        raise IntradayDataError(f"execution bars miss {sorted(missing)}")
    frame = bars.copy()
    if "code" in frame.columns and frame["code"].nunique(dropna=False) > 1:
        raise IntradayDataError("execution bars must contain exactly one code")
    frame["bar_at"] = [
        _local_timestamp(value, field="bar_at") for value in frame["bar_at"]
    ]
    frame["trade_date"] = [
        _calendar_date(value, field="trade_date") for value in frame["trade_date"]
    ]
    if any(
        trade_date != bar_at.date()
        for trade_date, bar_at in zip(frame["trade_date"], frame["bar_at"], strict=True)
    ):
        raise IntradayDataError("execution bar_at/trade_date values disagree")
    try:
        frame["bar_slot"] = frame["bar_slot"].astype("int64")
    except (TypeError, ValueError) as exc:
        raise IntradayDataError("bar_slot must be an integer") from exc
    if (~frame["bar_slot"].isin(range(len(BAR_SLOT_CLOCKS)))).any():
        raise IntradayDataError("bar_slot must be in 0..7")
    for bar_at, bar_slot in zip(frame["bar_at"], frame["bar_slot"], strict=True):
        if BAR_SLOT_CLOCKS[int(bar_slot)] != bar_at.strftime("%H:%M"):
            raise IntradayDataError("bar_at does not match bar_slot")
    for field in ("raw_open", "qfq_open", "prior_raw_daily_close"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    frame = frame.sort_values("bar_at", kind="stable").reset_index(drop=True)
    if frame["bar_at"].duplicated().any():
        raise IntradayDataError("execution bars contain duplicate bar_at values")
    return frame


def locate_next_bar_entry(
    bars: pd.DataFrame,
    reveal_at: object,
    *,
    limit_move: float = LIMIT_MOVE,
) -> dict[str, Any]:
    """Select the first actual stock bar strictly after signal revelation."""

    frame = _prepare_execution_bars(bars)
    reveal = _local_timestamp(reveal_at, field="reveal_at")
    result: dict[str, Any] = {
        "reveal_at": reveal,
        "entry_executable": False,
        "entry_status": "NO_NEXT_BAR",
    }
    positions = np.flatnonzero((frame["bar_at"] > reveal).to_numpy())
    if not len(positions):
        return result
    entry_index = int(positions[0])
    row = frame.iloc[entry_index]
    result.update(
        {
            "_entry_index": entry_index,
            "entry_at": row["bar_at"],
            "entry_trade_date": row["trade_date"],
            "entry_bar_slot": int(row["bar_slot"]),
            "raw_entry_open": float(row["raw_open"]),
            "qfq_entry_open": float(row["qfq_open"]),
            "prior_raw_daily_close": float(row["prior_raw_daily_close"]),
        }
    )
    raw_open = result["raw_entry_open"]
    qfq_open = result["qfq_entry_open"]
    prior_close = result["prior_raw_daily_close"]
    if not (
        math.isfinite(raw_open)
        and raw_open > 0
        and math.isfinite(qfq_open)
        and qfq_open > 0
        and math.isfinite(prior_close)
        and prior_close > 0
    ):
        result["entry_status"] = "INVALID_ENTRY_PRICE"
        return result
    entry_gap = raw_open / prior_close - 1
    result["raw_entry_gap"] = entry_gap
    if entry_gap > limit_move:
        result["entry_status"] = "ENTRY_LIMIT_UP"
        return result
    result["entry_status"] = "OK"
    result["entry_executable"] = True
    return result


def _canonical_slot_delay(
    *,
    session_dates: Sequence[date],
    target_session_index: int,
    target_slot: int,
    exit_date: date,
    exit_slot: int,
) -> int:
    exit_session_index = bisect_left(session_dates, exit_date)
    if (
        exit_session_index >= len(session_dates)
        or session_dates[exit_session_index] != exit_date
    ):
        raise IntradayDataError("exit date is absent from execution session calendar")
    return (
        (exit_session_index - target_session_index) * len(BAR_SLOT_CLOCKS)
        + exit_slot
        - target_slot
    )


def compute_trading_day_exits(
    *,
    bars: pd.DataFrame,
    reveal_at: object,
    horizons: Sequence[int] = HORIZONS,
    fee_per_side: float = FEE_PER_SIDE,
    limit_move: float = LIMIT_MOVE,
) -> dict[str, Any]:
    """Match next-bar entry and same-slot exits after stock trading-day horizons."""

    frame = _prepare_execution_bars(bars)
    result = locate_next_bar_entry(frame, reveal_at, limit_move=limit_move)
    entry_index = result.pop("_entry_index", None)
    horizon_values: list[int] = []
    for horizon in horizons:
        if isinstance(horizon, bool) or not isinstance(horizon, (int, np.integer)):
            raise IntradayDataError("horizons must contain positive integers")
        horizon_int = int(horizon)
        if horizon_int <= 0:
            raise IntradayDataError("horizons must contain positive integers")
        horizon_values.append(horizon_int)
    if not (0 <= fee_per_side < 1):
        raise IntradayDataError("fee_per_side must be in [0, 1)")

    if result["entry_status"] != "OK" or entry_index is None:
        for horizon in horizon_values:
            result[f"h{horizon}_status"] = result["entry_status"]
        return result

    session_dates = sorted(set(frame["trade_date"]))
    entry_date = result["entry_trade_date"]
    entry_session_index = bisect_left(session_dates, entry_date)
    if (
        entry_session_index >= len(session_dates)
        or session_dates[entry_session_index] != entry_date
    ):
        raise IntradayDataError("entry date is absent from execution session calendar")
    entry_slot = int(result["entry_bar_slot"])
    qfq_entry_open = float(result["qfq_entry_open"])

    for horizon in horizon_values:
        prefix = f"h{horizon}"
        target_session_index = entry_session_index + horizon
        if target_session_index >= len(session_dates):
            result[f"{prefix}_status"] = "CENSORED"
            continue
        target_date = session_dates[target_session_index]
        result[f"{prefix}_target_trade_date"] = target_date
        target_clock = BAR_SLOT_CLOCKS[entry_slot]
        target_at = pd.Timestamp(
            f"{target_date.isoformat()} {target_clock}", tz=SHANGHAI_TIMEZONE
        )
        candidate_positions = np.flatnonzero((frame["bar_at"] >= target_at).to_numpy())
        if not len(candidate_positions):
            result[f"{prefix}_status"] = "CENSORED"
            continue

        exit_index: int | None = None
        invalid_exit = False
        for raw_index in candidate_positions:
            candidate = frame.iloc[int(raw_index)]
            raw_open = float(candidate["raw_open"])
            prior_close = float(candidate["prior_raw_daily_close"])
            if not (
                math.isfinite(raw_open)
                and raw_open > 0
                and math.isfinite(prior_close)
                and prior_close > 0
            ):
                invalid_exit = True
                break
            if raw_open / prior_close - 1 <= -limit_move:
                continue
            exit_index = int(raw_index)
            break
        if exit_index is None:
            result[f"{prefix}_status"] = (
                "INVALID_EXIT_PRICE" if invalid_exit else "CENSORED_LIMIT_DOWN"
            )
            continue

        exit_row = frame.iloc[exit_index]
        qfq_exit_open = float(exit_row["qfq_open"])
        if not math.isfinite(qfq_exit_open) or qfq_exit_open <= 0:
            result[f"{prefix}_status"] = "INVALID_EXIT_PRICE"
            continue
        exit_date = exit_row["trade_date"]
        exit_slot = int(exit_row["bar_slot"])
        delay = _canonical_slot_delay(
            session_dates=session_dates,
            target_session_index=target_session_index,
            target_slot=entry_slot,
            exit_date=exit_date,
            exit_slot=exit_slot,
        )
        gross_return = qfq_exit_open / qfq_entry_open - 1
        net_return = (
            qfq_exit_open * (1 - fee_per_side) / (qfq_entry_open * (1 + fee_per_side))
            - 1
        )
        result.update(
            {
                f"{prefix}_status": "OK",
                f"{prefix}_exit_at": exit_row["bar_at"],
                f"{prefix}_exit_trade_date": exit_date,
                f"{prefix}_exit_bar_slot": exit_slot,
                f"{prefix}_exit_delay": delay,
                f"{prefix}_gross_return": gross_return,
                f"{prefix}_net_return": net_return,
            }
        )
    return result


def _timestamp_identity(value: object, *, field: str) -> str:
    return _local_timestamp(value, field=field).isoformat(timespec="seconds")


def intraday_fact_id(
    *,
    signal_set_id: str,
    code: str,
    expected_model_id: int,
    signal_at: object,
    reveal_at: object,
    event_kind: str,
) -> str:
    """Return a stable fact identity that retains hour/minute/second."""

    if event_kind not in EVENT_KINDS:
        raise IntradayDataError(f"unsupported event kind: {event_kind}")
    identity = {
        "signal_set_id": str(signal_set_id),
        "code": str(code),
        "expected_model_id": int(expected_model_id),
        "signal_at": _timestamp_identity(signal_at, field="signal_at"),
        "reveal_at": _timestamp_identity(reveal_at, field="reveal_at"),
        "event_kind": event_kind,
    }
    payload = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _prefix_matrices(result: Any, bar_count: int) -> tuple[np.ndarray, np.ndarray]:
    try:
        raw = np.asarray(result.signals_by_model, dtype=np.int64)
    except (AttributeError, TypeError, ValueError) as exc:
        raise IntradayDataError("engine result has no valid signals_by_model") from exc
    if raw.shape != (MODEL_COUNT, bar_count):
        raise IntradayDataError(
            "engine result shape must be " f"{MODEL_COUNT}x{bar_count}, got {raw.shape}"
        )

    buy_masks = getattr(result, "buy_base_trigger_masks", None)
    sell_masks = getattr(result, "sell_base_trigger_masks", None)
    if buy_masks is None or sell_masks is None:
        raise IntradayDataError(
            "30min trigger research requires detailed direction mask vectors"
        )
    buy = np.asarray(buy_masks, dtype=np.uint8)
    sell = np.asarray(sell_masks, dtype=np.uint8)
    if buy.shape != (bar_count,) or sell.shape != (bar_count,):
        raise IntradayDataError("engine mask vectors do not match prefix length")
    base = np.where(raw > 0, buy[None, :], sell[None, :]).astype(np.uint8)
    base[raw == 0] = 0

    nonzero = raw != 0
    model_offsets = np.arange(MODEL_COUNT, dtype=np.int64)[:, None] * 1000
    entrypoints = (np.abs(raw) - model_offsets) % 100
    primary_bits = np.left_shift(
        np.uint8(1),
        np.clip(entrypoints - 1, 0, 6).astype(np.uint8),
    ).astype(np.uint8)
    completed = np.where(nonzero, np.bitwise_or(base, primary_bits), 0).astype(np.uint8)
    return raw, completed


def replay_prefix_events(
    *,
    bars: pd.DataFrame,
    engine: Any,
    signal_set_id: str,
    options: ClxEngineOptions | None = None,
    code: str | None = None,
) -> list[dict[str, Any]]:
    """Replay every from-zero prefix and emit adjacent timestamped revisions."""

    required = {
        "bar_at",
        "qfq_high",
        "qfq_low",
        "qfq_open",
        "qfq_close",
        "raw_volume",
    }
    missing = required - set(bars.columns)
    if missing:
        raise IntradayDataError(f"prefix bars miss {sorted(missing)}")
    frame = bars.copy()
    frame["bar_at"] = [
        _local_timestamp(value, field="bar_at") for value in frame["bar_at"]
    ]
    if not frame["bar_at"].is_monotonic_increasing:
        raise IntradayDataError("prefix bars must be sorted by bar_at")
    if frame["bar_at"].duplicated().any():
        raise IntradayDataError("prefix bars contain duplicate bar_at values")

    if code is None:
        if "code" not in frame.columns or frame["code"].nunique(dropna=False) != 1:
            raise IntradayDataError("prefix bars must identify exactly one code")
        code = str(frame["code"].iloc[0])
    elif "code" in frame.columns and (frame["code"].astype(str).ne(str(code)).any()):
        raise IntradayDataError("prefix bars contain another code")
    if options is None:
        options = ClxEngineOptions()

    input_columns = (
        "qfq_high",
        "qfq_low",
        "qfq_open",
        "qfq_close",
        "raw_volume",
    )
    vectors: list[list[float]] = []
    for field in input_columns:
        values = pd.to_numeric(frame[field], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise IntradayDataError(f"prefix input {field} contains invalid values")
        vectors.append(values.tolist())
    clocks = frame["bar_at"].tolist()

    previous_raw = np.zeros((MODEL_COUNT, 0), dtype=np.int64)
    previous_masks = np.zeros((MODEL_COUNT, 0), dtype=np.uint8)
    revisions: defaultdict[tuple[int, int], int] = defaultdict(int)
    events: list[dict[str, Any]] = []

    for endpoint in range(len(frame)):
        prefix = tuple(vector[: endpoint + 1] for vector in vectors)
        result = engine.calculate_all(*prefix, options=options)
        current_raw, current_masks = _prefix_matrices(result, endpoint + 1)
        coordinates: list[tuple[int, int]] = []
        if endpoint:
            changed = (previous_raw != current_raw[:, :endpoint]) | (
                previous_masks != current_masks[:, :endpoint]
            )
            coordinates.extend(
                (int(model_id), int(position))
                for model_id, position in np.argwhere(changed)
            )
        coordinates.extend(
            (int(model_id), endpoint)
            for model_id in np.flatnonzero(current_raw[:, endpoint] != 0)
        )

        for model_id, position in sorted(coordinates):
            old_raw = (
                int(previous_raw[model_id, position]) if position < endpoint else 0
            )
            old_mask = (
                int(previous_masks[model_id, position]) if position < endpoint else 0
            )
            new_raw = int(current_raw[model_id, position])
            new_mask = int(current_masks[model_id, position])
            if old_raw == 0 and new_raw != 0:
                event_kind = "ADD"
            elif old_raw != 0 and new_raw == 0:
                event_kind = "REMOVE"
            elif (
                old_raw != 0
                and new_raw != 0
                and (old_raw != new_raw or old_mask != new_mask)
            ):
                event_kind = "REPLACE"
            else:
                raise IntradayDataError("invalid adjacent-prefix state transition")

            revisions[(model_id, position)] += 1
            signal_at = clocks[position]
            reveal_at = clocks[endpoint]
            current_signal = (
                decode_signal(new_raw, expected_model_id=model_id) if new_raw else None
            )
            event = {
                "signal_set_id": signal_set_id,
                "code": code,
                "expected_model_id": model_id,
                "model_id": model_id,
                "model_code": f"S{model_id:04d}",
                "signal_at": signal_at,
                "signal_trade_date": signal_at.date(),
                "as_of_at": reveal_at,
                "reveal_at": reveal_at,
                "reveal_trade_date": reveal_at.date(),
                "revision_no": revisions[(model_id, position)],
                "event_kind": event_kind,
                "previous_raw_signal": old_raw,
                "current_raw_signal": new_raw,
                "previous_concurrent_trigger_mask": old_mask if old_raw else None,
                "concurrent_trigger_mask": new_mask if new_raw else None,
                "direction": current_signal.direction if current_signal else None,
                "occurrence": current_signal.occurrence if current_signal else None,
                "primary_entrypoint": (
                    current_signal.primary_entrypoint if current_signal else None
                ),
                "actionable": new_raw != 0,
            }
            event["signal_fact_id"] = intraday_fact_id(
                signal_set_id=signal_set_id,
                code=code,
                expected_model_id=model_id,
                signal_at=signal_at,
                reveal_at=reveal_at,
                event_kind=event_kind,
            )
            events.append(event)
        previous_raw = current_raw
        previous_masks = current_masks
    return events


# Descriptive aliases for call sites that prefer construction/ID verbs.
build_intraday_frame = build_intraday_bars
make_intraday_fact_id = intraday_fact_id

__all__ = [
    "BAR_SLOT_CLOCKS",
    "FEE_PER_SIDE",
    "HORIZONS",
    "IntradayDataError",
    "LIMIT_MOVE",
    "MONGO_MINUTE_TYPE",
    "SHANGHAI_TIMEZONE",
    "attach_previous_session_regimes",
    "build_intraday_bars",
    "build_intraday_frame",
    "compute_trading_day_exits",
    "intraday_fact_id",
    "locate_next_bar_entry",
    "make_intraday_fact_id",
    "replay_prefix_events",
]
