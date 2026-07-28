"""Build the locked CLX18 30-minute F1-F6 capital simulation and report.

The executable filter contract contains the 64 F1-F6 subsets, represented by
``filter_mask`` values in ``0..63``.

Inputs (all below ``--root``):

* ``features/candidate_events.parquet`` - immutable signal facts;
* ``matrix/locked_config.json`` - four TRAIN+VALIDATION locked selections;
* ``matrix/reveal_matrix.parquet`` - optional, already-once-revealed AUDIT facts;
* ``snapshot/bars/<code>.parquet`` - 30-minute QFQ closes used for marking;
* ``snapshot/index_day.parquet`` and ``features/market_segments.csv`` -
  market calendar/regime facts.

The simulator uses CNY 5,000,000, 40 slots with up to CNY 125,000 capital per
slot, exits before entries at an identical bar timestamp, never adds to an
already-held stock, and applies 0.02% on each side.  It intentionally does not
model slippage, stamp duty, minimum commission, or 100-share board-lot
rounding; those omissions are repeated in every generated report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

STUDY_ID = "clx-30m-full-trigger-f1-f6-v1"
PORTFOLIO_CONTRACT_VERSION = 1
INITIAL_CAPITAL = 5_000_000.0
MAX_POSITIONS = 40
SLOT_CAPITAL = 125_000.0
FEE_PER_SIDE = 0.0002
DAILY_ENTRY_LIMITS: tuple[int | None, ...] = (1, 3, 5, 10, 20, None)
HORIZONS = (5, 30, 60, 90)
FILTER_NAMES = tuple(f"F{offset}" for offset in range(1, 7))
FILTER_DESCRIPTIONS = {
    "F1": "未复权原始开盘价1～6元",
    "F2": "个股近20个交易日收益≤0",
    "F3": "距近20个交易日高点回撤≥10%",
    "F4": "近20个交易日非年化日等效波动率≥3%",
    "F5": "收盘价≤MA60日等效均线",
    "F6": "上证指数近20个完整交易日收益≤0",
}
TRIGGER_BITS = {
    "MODEL_STRUCTURAL": 0x01,
    "PIN_BAR": 0x02,
    "ENGULFING": 0x04,
    "STRONG_FRACTAL": 0x08,
    "MA5_TURN": 0x10,
    "PRICE_VOLUME_CONFIRMATION": 0x20,
    "MACD_CROSS": 0x40,
}
BAR_CLOCKS = (
    "10:00",
    "10:30",
    "11:00",
    "11:30",
    "13:30",
    "14:00",
    "14:30",
    "15:00",
)
SHANGHAI_TIMEZONE = "Asia/Shanghai"
DEFAULT_ROOT = Path(
    "D:/fqpack/runtime/clx-backtest/studies/clx-30m-full-trigger-f1-f6-v1"
)

DAILY_BASELINES = {
    5: {
        "locked_combo": "MACD金叉+F4+F6",
        "train_net_win_rate": 0.5277,
        "validation_net_win_rate": 0.5719,
        "audit_net_win_rate": 0.4761,
        "total_return": -0.2324,
        "cagr": -0.0127,
        "max_drawdown": -0.4002,
    },
    30: {
        "locked_combo": "吞没+F3+F5",
        "train_net_win_rate": 0.5769,
        "validation_net_win_rate": 0.6135,
        "audit_net_win_rate": 0.5717,
        "total_return": 1.5508,
        "cagr": 0.0462,
        "max_drawdown": -0.4703,
    },
    60: {
        "locked_combo": "同时2个触发+F1+F2+F3",
        "train_net_win_rate": 0.6100,
        "validation_net_win_rate": 0.5995,
        "audit_net_win_rate": 0.6113,
        "total_return": 2.0773,
        "cagr": 0.0557,
        "max_drawdown": -0.6074,
    },
    90: {
        "locked_combo": "Pin Bar+F1+F4+F6",
        "train_net_win_rate": 0.6501,
        "validation_net_win_rate": 0.6141,
        "audit_net_win_rate": 0.7907,
        "total_return": 2.1358,
        "cagr": 0.0566,
        "max_drawdown": -0.5179,
    },
}


class PortfolioContractError(RuntimeError):
    """Raised when an immutable input or portfolio contract is invalid."""


@dataclass(frozen=True)
class LockedSelection:
    selection_id: str
    horizon: int
    model_codes: tuple[str, ...]
    trigger_kind: str
    trigger_value: int | None
    trigger_name: str
    trigger_id: str
    filter_mask: int
    filter_names: tuple[str, ...]
    development_score: float | None
    train_metrics: Mapping[str, Any]
    validation_metrics: Mapping[str, Any]

    def as_row(self) -> dict[str, Any]:
        return {
            "selection_id": self.selection_id,
            "horizon_trading_days": self.horizon,
            "model_code": ",".join(self.model_codes),
            "trigger_id": self.trigger_id,
            "trigger_kind": self.trigger_kind,
            "trigger_value": self.trigger_value,
            "trigger_name": self.trigger_name,
            "filter_mask": self.filter_mask,
            "filter_names": ",".join(self.filter_names),
            "development_score": self.development_score,
            "train_n": _metric(self.train_metrics, "sample_count", "n"),
            "train_net_win_rate": _metric(
                self.train_metrics, "net_win_rate", "win_rate"
            ),
            "train_mean_net_return": _metric(
                self.train_metrics, "mean_net_return", "net_mean_return"
            ),
            "validation_n": _metric(self.validation_metrics, "sample_count", "n"),
            "validation_net_win_rate": _metric(
                self.validation_metrics, "net_win_rate", "win_rate"
            ),
            "validation_mean_net_return": _metric(
                self.validation_metrics, "mean_net_return", "net_mean_return"
            ),
        }


@dataclass
class SimulationResult:
    summary: dict[str, Any]
    equity: pd.DataFrame
    trades: pd.DataFrame
    decisions: pd.DataFrame


def _metric(value: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in value:
            return value[name]
    return None


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: object) -> object:
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if value is pd.NA:
        return None
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=_json_default,
    )
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        stream.write(payload)
        temporary = Path(stream.name)
    os.replace(temporary, path)


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8-sig",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
    try:
        frame.to_csv(temporary, index=False, encoding="utf-8-sig")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _as_shanghai(values: Iterable[object]) -> pd.DatetimeIndex:
    result = pd.DatetimeIndex(pd.to_datetime(values, errors="coerce", utc=True))
    return result.tz_convert(SHANGHAI_TIMEZONE)


def _normalise_model_codes(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, Sequence):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        items = []
    if not items:
        raise PortfolioContractError("locked selection has no model_code")
    for item in items:
        if item not in {"ALL", "*", "UNION"} and not (
            len(item) == 5 and item.startswith("S") and item[1:].isdigit()
        ):
            raise PortfolioContractError(f"invalid locked model_code: {item}")
    return tuple(items)


def load_locked_selections(path: Path) -> list[LockedSelection]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PortfolioContractError(f"locked config is missing: {path}") from exc
    raw = payload.get("selections") if isinstance(payload, Mapping) else None
    if not isinstance(raw, list):
        raise PortfolioContractError("locked_config.json must contain selections[]")
    selections: list[LockedSelection] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise PortfolioContractError("locked selection must be an object")
        selector = item.get("trigger_selector")
        if not isinstance(selector, Mapping):
            raise PortfolioContractError("locked trigger_selector is missing")
        kind = str(selector.get("kind", "")).upper()
        if kind not in {"SINGLE_BIT", "EXACT_MASK", "COUNT_EQ", "COUNT_GTE", "ALL"}:
            raise PortfolioContractError(f"unsupported trigger kind: {kind}")
        value = selector.get("value")
        parsed_value = None if value is None else int(value)
        if kind == "SINGLE_BIT" and parsed_value not in TRIGGER_BITS.values():
            raise PortfolioContractError(
                "SINGLE_BIT value must be a native trigger bit"
            )
        if kind == "EXACT_MASK" and not (1 <= int(parsed_value or 0) <= 127):
            raise PortfolioContractError("EXACT_MASK value must be 1..127")
        if kind == "COUNT_EQ" and parsed_value != 2:
            raise PortfolioContractError("COUNT_EQ is frozen to value=2")
        if kind == "COUNT_GTE" and parsed_value != 3:
            raise PortfolioContractError("COUNT_GTE is frozen to value=3")
        if kind == "ALL" and parsed_value is not None:
            raise PortfolioContractError("ALL trigger value must be null")
        horizon = int(item.get("horizon_trading_days", item.get("horizon", 0)))
        if horizon not in HORIZONS:
            raise PortfolioContractError(f"invalid horizon: {horizon}")
        filter_mask = int(item.get("filter_mask", -1))
        if not 0 <= filter_mask <= 63:
            raise PortfolioContractError(
                f"F1-F6 filter_mask must be in 0..63, got {filter_mask}"
            )
        expected_names = tuple(
            name for bit, name in enumerate(FILTER_NAMES) if filter_mask & (1 << bit)
        )
        supplied_names = tuple(str(value) for value in item.get("filter_names", []))
        if supplied_names and supplied_names != expected_names:
            raise PortfolioContractError(
                f"selection {item.get('selection_id')} filter_names disagree with mask"
            )
        selection_id = str(item.get("selection_id", "")).strip()
        if not selection_id:
            raise PortfolioContractError("locked selection_id is missing")
        score = item.get("development_score")
        selections.append(
            LockedSelection(
                selection_id=selection_id,
                horizon=horizon,
                model_codes=_normalise_model_codes(
                    item.get("model_code", item.get("model_codes"))
                ),
                trigger_kind=kind,
                trigger_value=parsed_value,
                trigger_name=str(selector.get("name", kind)),
                trigger_id=str(item.get("trigger_id", kind)),
                filter_mask=filter_mask,
                filter_names=expected_names,
                development_score=(
                    float(score) if score is not None and pd.notna(score) else None
                ),
                train_metrics=dict(item.get("train_metrics") or {}),
                validation_metrics=dict(item.get("validation_metrics") or {}),
            )
        )
    horizons = [selection.horizon for selection in selections]
    if len(selections) != 4 or sorted(horizons) != list(HORIZONS):
        raise PortfolioContractError(
            "F1-F6 lock must contain exactly one selection for each 5/30/60/90 horizon"
        )
    if len({item.selection_id for item in selections}) != len(selections):
        raise PortfolioContractError("locked selection_id values are not unique")
    return sorted(selections, key=lambda item: item.horizon)


def _trigger_mask(frame: pd.DataFrame, selection: LockedSelection) -> pd.Series:
    masks = (
        pd.to_numeric(frame["concurrent_trigger_mask"], errors="coerce")
        .fillna(0)
        .astype("int64")
    )
    counts = (
        pd.to_numeric(frame["concurrent_trigger_count"], errors="coerce")
        .fillna(masks.map(int.bit_count))
        .astype("int64")
    )
    if selection.trigger_kind == "SINGLE_BIT":
        return masks.map(
            lambda value: bool(int(value) & int(selection.trigger_value or 0))
        )
    if selection.trigger_kind == "EXACT_MASK":
        return masks.eq(int(selection.trigger_value or 0))
    if selection.trigger_kind == "COUNT_EQ":
        return counts.eq(int(selection.trigger_value or 0))
    if selection.trigger_kind == "COUNT_GTE":
        return counts.ge(int(selection.trigger_value or 0))
    return pd.Series(True, index=frame.index)


def _event_ids(frame: pd.DataFrame) -> pd.Series:
    if "union_signal_id" in frame:
        supplied = frame["union_signal_id"].astype("string")
    elif "signal_fact_id" in frame:
        supplied = frame["signal_fact_id"].astype("string")
    else:
        supplied = pd.Series(pd.NA, index=frame.index, dtype="string")
    generated = [
        "sha256:"
        + hashlib.sha256(
            _canonical_bytes(
                {
                    "code": str(code),
                    "model_code": str(model),
                    "reveal_at": pd.Timestamp(reveal).isoformat(),
                }
            )
        ).hexdigest()
        for code, model, reveal in zip(
            frame["code"], frame["model_code"], frame["reveal_at"], strict=True
        )
    ]
    return supplied.fillna(pd.Series(generated, index=frame.index)).astype(str)


def select_locked_candidates(
    events: pd.DataFrame,
    selection: LockedSelection,
    *,
    scope: str = "AVAILABLE",
) -> pd.DataFrame:
    required = {
        "code",
        "model_code",
        "reveal_at",
        "entry_at",
        "qfq_entry_open",
        "concurrent_trigger_mask",
        "filter_pass_mask",
        f"h{selection.horizon}_status",
        f"h{selection.horizon}_exit_at",
        f"h{selection.horizon}_gross_return",
    }
    missing = sorted(required - set(events.columns))
    if missing:
        raise PortfolioContractError(f"candidate events miss columns: {missing}")
    frame = events.copy()
    for column in ("reveal_at", "entry_at", f"h{selection.horizon}_exit_at"):
        frame[column] = _as_shanghai(frame[column])
    wildcard = bool(set(selection.model_codes) & {"ALL", "*", "UNION"})
    model_pass = (
        pd.Series(True, index=frame.index)
        if wildcard
        else frame["model_code"].isin(selection.model_codes)
    )
    pass_masks = (
        pd.to_numeric(frame["filter_pass_mask"], errors="coerce")
        .fillna(0)
        .astype("int64")
    )
    filters_pass = (pass_masks & selection.filter_mask).eq(selection.filter_mask)
    executable = (
        frame.get("entry_executable", pd.Series(True, index=frame.index))
        .fillna(False)
        .astype(bool)
        & frame.get("entry_status", pd.Series("OK", index=frame.index)).eq("OK")
        & frame[f"h{selection.horizon}_status"].eq("OK")
    )
    mask = model_pass & filters_pass & executable & _trigger_mask(frame, selection)
    if scope.upper() == "AUDIT":
        if "split_id" not in frame:
            raise PortfolioContractError("AUDIT portfolio requires split_id")
        mask &= frame["split_id"].eq("AUDIT")
    elif scope.upper() != "AVAILABLE":
        raise PortfolioContractError(f"unsupported portfolio scope: {scope}")
    frame = frame.loc[mask].copy()
    if frame.empty:
        return frame
    frame["candidate_id"] = _event_ids(frame)
    frame["exit_at"] = frame[f"h{selection.horizon}_exit_at"]
    frame["qfq_entry_open"] = pd.to_numeric(frame["qfq_entry_open"], errors="coerce")
    frame["gross_return"] = pd.to_numeric(
        frame[f"h{selection.horizon}_gross_return"], errors="coerce"
    )
    frame["qfq_exit_open"] = frame["qfq_entry_open"] * (1 + frame["gross_return"])
    frame = frame[
        frame["qfq_entry_open"].gt(0)
        & frame["qfq_exit_open"].gt(0)
        & frame["exit_at"].gt(frame["entry_at"])
    ].copy()
    quality_columns = {
        "concurrent_trigger_count": 0,
        "same_code_reveal_model_count": 1,
        "same_reveal_event_count": 1,
        "amount_median_20d": 0.0,
        "raw_entry_gap": 0.0,
    }
    for column, default in quality_columns.items():
        if column not in frame:
            frame[column] = default
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(default)
    frame = frame.sort_values(
        [
            "entry_at",
            "concurrent_trigger_count",
            "same_code_reveal_model_count",
            "same_reveal_event_count",
            "amount_median_20d",
            "raw_entry_gap",
            "candidate_id",
        ],
        ascending=[True, False, False, True, False, True, True],
        kind="stable",
    )
    # Union duplicate facts represent the same stock/reveal decision.
    return frame.drop_duplicates("candidate_id", keep="first").reset_index(drop=True)


class MarkStore:
    """Lazy, audited QFQ 30-minute close lookup."""

    def __init__(self, root: Path):
        self.root = root
        self._values: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self.source_rows = 0

    def load(self, codes: Iterable[str]) -> None:
        for code in sorted({str(value) for value in codes}):
            if code in self._values:
                continue
            path = self.root / "snapshot" / "bars" / f"{code}.parquet"
            if not path.is_file():
                raise PortfolioContractError(
                    f"mark bars are missing for {code}: {path}"
                )
            frame = pd.read_parquet(path, columns=["bar_at", "qfq_close"])
            frame["bar_at"] = _as_shanghai(frame["bar_at"])
            frame["qfq_close"] = pd.to_numeric(frame["qfq_close"], errors="coerce")
            frame = (
                frame.dropna(subset=["bar_at", "qfq_close"])
                .loc[lambda value: value["qfq_close"].gt(0)]
                .sort_values("bar_at", kind="stable")
                .drop_duplicates("bar_at", keep="last")
            )
            if frame.empty:
                raise PortfolioContractError(
                    f"mark bars have no usable rows for {code}"
                )
            self._values[code] = (
                pd.DatetimeIndex(frame["bar_at"]).asi8,
                frame["qfq_close"].to_numpy(dtype=float),
            )
            self.source_rows += len(frame)

    def close(self, code: str, timestamp: pd.Timestamp, fallback: float) -> float:
        times, closes = self._values[code]
        offset = int(np.searchsorted(times, timestamp.value, side="right") - 1)
        return float(closes[offset]) if offset >= 0 else float(fallback)

    def all_timestamps(self, codes: Iterable[str]) -> pd.DatetimeIndex:
        arrays = [self._values[str(code)][0] for code in sorted(set(codes))]
        if not arrays:
            return pd.DatetimeIndex([], tz=SHANGHAI_TIMEZONE)
        values = np.unique(np.concatenate(arrays))
        return pd.DatetimeIndex(values, tz="UTC").tz_convert(SHANGHAI_TIMEZONE)


def build_simulation_clock(
    root: Path,
    selected_frames: Sequence[pd.DataFrame],
    marks: MarkStore,
) -> pd.DatetimeIndex:
    nonempty = [frame for frame in selected_frames if not frame.empty]
    if not nonempty:
        raise PortfolioContractError(
            "all locked selections have zero portfolio candidates"
        )
    first = min(frame["entry_at"].min() for frame in nonempty)
    last = max(frame["exit_at"].max() for frame in nonempty)
    index_path = root / "snapshot" / "index_day.parquet"
    if index_path.is_file():
        sessions = pd.to_datetime(
            pd.read_parquet(index_path, columns=["date"])["date"],
            errors="coerce",
        ).dropna()
        dates = sorted(
            {
                value.date()
                for value in sessions
                if first.date() <= value.date() <= last.date()
            }
        )
        regular = pd.DatetimeIndex(
            [
                pd.Timestamp(f"{session.isoformat()} {clock}", tz=SHANGHAI_TIMEZONE)
                for session in dates
                for clock in BAR_CLOCKS
            ]
        )
    else:
        codes = {
            str(code)
            for frame in nonempty
            for code in frame["code"].astype(str).unique()
        }
        regular = marks.all_timestamps(codes)
        regular = regular[(regular >= first) & (regular <= last)]
    actions = pd.DatetimeIndex(
        [
            value
            for frame in nonempty
            for column in ("entry_at", "exit_at")
            for value in frame[column]
        ]
    )
    clock = regular.union(actions).sort_values().unique()
    clock = clock[(clock >= first) & (clock <= last)]
    if clock.empty:
        raise PortfolioContractError("simulation clock is empty")
    return clock


def _stable_order(frame: pd.DataFrame, policy: str, seed: int | None) -> pd.DataFrame:
    if len(frame) <= 1:
        return frame
    if policy == "quality":
        return frame.sort_values(
            [
                "concurrent_trigger_count",
                "same_code_reveal_model_count",
                "same_reveal_event_count",
                "amount_median_20d",
                "raw_entry_gap",
                "candidate_id",
            ],
            ascending=[False, False, True, False, True, True],
            kind="stable",
        )
    if policy != "sha_random" or seed is None:
        raise PortfolioContractError(f"invalid ranking policy: {policy}")
    ordered = frame.copy()
    ordered["_order_hash"] = [
        hashlib.sha256(f"{seed:03d}|{value}".encode()).hexdigest()
        for value in ordered["candidate_id"]
    ]
    return ordered.sort_values(["_order_hash", "candidate_id"], kind="stable").drop(
        columns="_order_hash"
    )


def _max_consecutive_losses(returns: Sequence[float]) -> int:
    longest = current = 0
    for value in returns:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _underwater_stats(timestamps: pd.Series, drawdowns: pd.Series) -> tuple[int, float]:
    start: pd.Timestamp | None = None
    longest_bars = 0
    current_bars = 0
    longest_days = 0.0
    for timestamp, value in zip(timestamps, drawdowns, strict=True):
        if float(value) < -1e-14:
            if start is None:
                start = pd.Timestamp(timestamp)
                current_bars = 0
            current_bars += 1
            longest_bars = max(longest_bars, current_bars)
            longest_days = max(
                longest_days,
                (pd.Timestamp(timestamp) - start).total_seconds() / 86_400,
            )
        else:
            start = None
            current_bars = 0
    return longest_bars, longest_days


def simulate_portfolio(
    candidates: pd.DataFrame,
    *,
    selection: LockedSelection,
    scope: str,
    clock: pd.DatetimeIndex,
    marks: MarkStore,
    daily_entry_limit: int | None,
    ranking_policy: str,
    random_seed: int | None = None,
) -> SimulationResult:
    entries = {
        int(pd.Timestamp(timestamp).value): group
        for timestamp, group in candidates.groupby("entry_at", sort=False)
    }
    cash = INITIAL_CAPITAL
    positions: dict[str, dict[str, Any]] = {}
    opened_by_day: dict[object, int] = {}
    total_fees = 0.0
    buy_notional = 0.0
    sell_notional = 0.0
    peak_positions = 0
    decisions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []
    rejected = {
        "occupied": 0,
        "daily_limit": 0,
        "slots": 0,
        "cash": 0,
    }

    def reject(row: Mapping[str, Any], timestamp: pd.Timestamp, reason: str) -> None:
        rejected[reason] += 1
        decisions.append(
            {
                "selection_id": selection.selection_id,
                "horizon_trading_days": selection.horizon,
                "scope": scope,
                "daily_entry_limit": _limit_label(daily_entry_limit),
                "ranking_policy": ranking_policy,
                "random_seed": random_seed,
                "candidate_id": row["candidate_id"],
                "code": row["code"],
                "entry_at": timestamp,
                "decision": f"REJECT_{reason.upper()}",
            }
        )

    for timestamp in clock:
        timestamp = pd.Timestamp(timestamp)
        # Contract: every due exit is booked before any entry at the same bar.
        due = sorted(
            [
                (code, position)
                for code, position in positions.items()
                if position["exit_at"] <= timestamp
            ],
            key=lambda value: (value[1]["exit_at"], value[0]),
        )
        for code, position in due:
            exit_notional = position["units"] * position["exit_price"]
            exit_fee = exit_notional * FEE_PER_SIDE
            cash += exit_notional - exit_fee
            total_fees += exit_fee
            sell_notional += exit_notional
            net_pnl = exit_notional - exit_fee - position["entry_cost"]
            net_return = (exit_notional - exit_fee) / position["entry_cost"] - 1
            trades.append(
                {
                    "selection_id": selection.selection_id,
                    "horizon_trading_days": selection.horizon,
                    "scope": scope,
                    "daily_entry_limit": _limit_label(daily_entry_limit),
                    "ranking_policy": ranking_policy,
                    "random_seed": random_seed,
                    "candidate_id": position["candidate_id"],
                    "code": code,
                    "entry_at": position["entry_at"],
                    "exit_at": timestamp,
                    "entry_price": position["entry_price"],
                    "exit_price": position["exit_price"],
                    "units": position["units"],
                    "entry_notional": position["entry_notional"],
                    "exit_notional": exit_notional,
                    "entry_fee": position["entry_fee"],
                    "exit_fee": exit_fee,
                    "total_fee": position["entry_fee"] + exit_fee,
                    "net_pnl": net_pnl,
                    "net_return": net_return,
                    "entry_market_regime": position["market_regime"],
                }
            )
            positions.pop(code)

        incoming = entries.get(timestamp.value)
        if incoming is not None:
            ordered = _stable_order(incoming, ranking_policy, random_seed)
            day = timestamp.date()
            for row in ordered.to_dict(orient="records"):
                code = str(row["code"])
                if code in positions:
                    reject(row, timestamp, "occupied")
                    continue
                if (
                    daily_entry_limit is not None
                    and opened_by_day.get(day, 0) >= daily_entry_limit
                ):
                    reject(row, timestamp, "daily_limit")
                    continue
                if len(positions) >= MAX_POSITIONS:
                    reject(row, timestamp, "slots")
                    continue
                capital_budget = min(SLOT_CAPITAL, cash)
                if capital_budget <= 0:
                    reject(row, timestamp, "cash")
                    continue
                entry_notional = capital_budget / (1 + FEE_PER_SIDE)
                entry_fee = capital_budget - entry_notional
                units = entry_notional / float(row["qfq_entry_open"])
                cash -= capital_budget
                total_fees += entry_fee
                buy_notional += entry_notional
                positions[code] = {
                    "candidate_id": row["candidate_id"],
                    "entry_at": timestamp,
                    "exit_at": pd.Timestamp(row["exit_at"]),
                    "entry_price": float(row["qfq_entry_open"]),
                    "exit_price": float(row["qfq_exit_open"]),
                    "units": units,
                    "entry_notional": entry_notional,
                    "entry_fee": entry_fee,
                    "entry_cost": capital_budget,
                    "market_regime": str(row.get("market_regime", "UNKNOWN")),
                }
                opened_by_day[day] = opened_by_day.get(day, 0) + 1
                decisions.append(
                    {
                        "selection_id": selection.selection_id,
                        "horizon_trading_days": selection.horizon,
                        "scope": scope,
                        "daily_entry_limit": _limit_label(daily_entry_limit),
                        "ranking_policy": ranking_policy,
                        "random_seed": random_seed,
                        "candidate_id": row["candidate_id"],
                        "code": code,
                        "entry_at": timestamp,
                        "decision": "ACCEPT",
                    }
                )
        invested = 0.0
        for code, position in positions.items():
            invested += position["units"] * marks.close(
                code, timestamp, position["entry_price"]
            )
        equity = cash + invested
        if cash < -0.01 or len(positions) > MAX_POSITIONS or equity <= 0:
            raise PortfolioContractError(
                f"portfolio invariant failed at {timestamp}: "
                f"cash={cash}, positions={len(positions)}, equity={equity}"
            )
        peak_positions = max(peak_positions, len(positions))
        curve.append(
            {
                "selection_id": selection.selection_id,
                "horizon_trading_days": selection.horizon,
                "scope": scope,
                "daily_entry_limit": _limit_label(daily_entry_limit),
                "ranking_policy": ranking_policy,
                "random_seed": random_seed,
                "bar_at": timestamp,
                "cash": cash,
                "invested_value": invested,
                "equity": equity,
                "positions": len(positions),
                "capital_utilization": invested / equity,
            }
        )
    if positions:
        raise PortfolioContractError(
            f"{len(positions)} positions remain after the last mature exit"
        )
    equity_frame = pd.DataFrame(curve)
    equity_frame["normalized_equity"] = equity_frame["equity"] / INITIAL_CAPITAL
    equity_frame["drawdown"] = (
        equity_frame["equity"] / equity_frame["equity"].cummax() - 1
    )
    trade_frame = pd.DataFrame(trades)
    decision_frame = pd.DataFrame(decisions)
    trade_returns = (
        trade_frame["net_return"].to_numpy(dtype=float)
        if not trade_frame.empty
        else np.asarray([], dtype=float)
    )
    pnl = (
        trade_frame["net_pnl"].to_numpy(dtype=float)
        if not trade_frame.empty
        else np.asarray([], dtype=float)
    )
    winners = trade_returns[trade_returns > 0]
    losers = trade_returns[trade_returns < 0]
    longest_bars, longest_days = _underwater_stats(
        equity_frame["bar_at"], equity_frame["drawdown"]
    )
    elapsed_years = max(
        (
            equity_frame["bar_at"].iloc[-1] - equity_frame["bar_at"].iloc[0]
        ).total_seconds()
        / (365.25 * 86_400),
        1 / 365.25,
    )
    final_equity = float(equity_frame["equity"].iloc[-1])
    accepted = len(trade_frame)
    average_equity = float(equity_frame["equity"].mean())
    summary = {
        "selection_id": selection.selection_id,
        "horizon_trading_days": selection.horizon,
        "scope": scope,
        "daily_entry_limit": _limit_label(daily_entry_limit),
        "ranking_policy": ranking_policy,
        "random_seed": random_seed,
        "order_sha256": (
            "sha256:"
            + hashlib.sha256(
                f"{selection.selection_id}|{ranking_policy}|{random_seed}".encode()
            ).hexdigest()
        ),
        "initial_capital": INITIAL_CAPITAL,
        "final_equity": final_equity,
        "total_return": final_equity / INITIAL_CAPITAL - 1,
        "cagr": (final_equity / INITIAL_CAPITAL) ** (1 / elapsed_years) - 1,
        "max_drawdown": float(equity_frame["drawdown"].min()),
        "longest_underwater_bars": longest_bars,
        "longest_underwater_days": longest_days,
        "candidate_signals": len(candidates),
        "closed_trades": accepted,
        "candidate_acceptance_rate": (
            accepted / len(candidates) if len(candidates) else None
        ),
        "closed_win_rate": (
            float(np.mean(trade_returns > 0)) if len(trade_returns) else None
        ),
        "mean_trade_return": (
            float(trade_returns.mean()) if len(trade_returns) else None
        ),
        "median_trade_return": (
            float(np.median(trade_returns)) if len(trade_returns) else None
        ),
        "average_win": float(winners.mean()) if len(winners) else None,
        "average_loss_abs": float(abs(losers.mean())) if len(losers) else None,
        "payoff_ratio": (
            float(winners.mean() / abs(losers.mean()))
            if len(winners) and len(losers)
            else None
        ),
        "profit_factor": (
            float(pnl[pnl > 0].sum() / abs(pnl[pnl < 0].sum()))
            if np.any(pnl > 0) and np.any(pnl < 0)
            else None
        ),
        "max_consecutive_losses": _max_consecutive_losses(trade_returns),
        "total_fees": total_fees,
        "buy_notional": buy_notional,
        "sell_notional": sell_notional,
        "one_way_turnover": (
            (buy_notional + sell_notional) / (2 * average_equity)
            if average_equity > 0
            else None
        ),
        "two_way_turnover": (
            (buy_notional + sell_notional) / average_equity
            if average_equity > 0
            else None
        ),
        "average_positions": float(equity_frame["positions"].mean()),
        "peak_positions": peak_positions,
        "average_capital_utilization": float(
            equity_frame["capital_utilization"].mean()
        ),
        "peak_capital_utilization": float(equity_frame["capital_utilization"].max()),
        "rejected_occupied": rejected["occupied"],
        "rejected_daily_limit": rejected["daily_limit"],
        "rejected_slots": rejected["slots"],
        "rejected_cash": rejected["cash"],
        "start_at": equity_frame["bar_at"].iloc[0],
        "end_at": equity_frame["bar_at"].iloc[-1],
    }
    return SimulationResult(summary, equity_frame, trade_frame, decision_frame)


def _limit_label(value: int | None) -> str:
    return "UNLIMITED" if value is None else str(value)


def _regime_for_dates(dates: pd.Series, segments: pd.DataFrame) -> pd.Series:
    output = pd.Series("UNKNOWN", index=dates.index, dtype="string")
    if segments.empty:
        return output
    parsed = segments.copy()
    parsed["start_date"] = pd.to_datetime(parsed["start_date"]).dt.date
    parsed["end_date"] = pd.to_datetime(parsed["end_date"]).dt.date
    day_values = pd.to_datetime(dates).dt.date
    for row in parsed.itertuples(index=False):
        in_segment = day_values.ge(row.start_date) & day_values.le(row.end_date)
        output.loc[in_segment] = str(row.regime)
    return output


def build_period_metrics(
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    segments: pd.DataFrame,
) -> pd.DataFrame:
    if equity.empty:
        return pd.DataFrame()
    frame = equity.sort_values("bar_at", kind="stable").copy()
    frame["year"] = frame["bar_at"].dt.year.astype(str)
    frame["quarter"] = (
        frame["bar_at"].dt.tz_localize(None).dt.to_period("Q").astype(str)
    )
    frame["regime"] = _regime_for_dates(frame["bar_at"], segments)
    frame["bar_return"] = (
        frame["equity"]
        .pct_change(fill_method=None)
        .fillna(frame["equity"].iloc[0] / INITIAL_CAPITAL - 1)
    )
    trade_frame = trades.copy()
    if not trade_frame.empty:
        trade_frame["year"] = trade_frame["entry_at"].dt.year.astype(str)
        trade_frame["quarter"] = (
            trade_frame["entry_at"].dt.tz_localize(None).dt.to_period("Q").astype(str)
        )
        trade_frame["regime"] = trade_frame["entry_market_regime"].fillna("UNKNOWN")
    keys = [
        "selection_id",
        "horizon_trading_days",
        "scope",
        "daily_entry_limit",
        "ranking_policy",
    ]
    identity = {key: frame[key].iloc[0] for key in keys}
    rows: list[dict[str, Any]] = []
    for period_type, column in (
        ("YEAR", "year"),
        ("QUARTER", "quarter"),
        ("REGIME", "regime"),
    ):
        for period_id, group in frame.groupby(column, sort=True):
            period_trades = (
                trade_frame[trade_frame[column].eq(period_id)]
                if not trade_frame.empty
                else trade_frame
            )
            returns = (
                period_trades["net_return"].to_numpy(dtype=float)
                if not period_trades.empty
                else np.asarray([], dtype=float)
            )
            rows.append(
                {
                    **identity,
                    "period_type": period_type,
                    "period_id": str(period_id),
                    "start_at": group["bar_at"].min(),
                    "end_at": group["bar_at"].max(),
                    "start_equity": float(group["equity"].iloc[0]),
                    "end_equity": float(group["equity"].iloc[-1]),
                    "normalized_end_equity": float(
                        group["equity"].iloc[-1] / INITIAL_CAPITAL
                    ),
                    "portfolio_return": float(
                        np.prod(1 + group["bar_return"].to_numpy(dtype=float)) - 1
                    ),
                    "max_drawdown_within_period": float(
                        (group["equity"] / group["equity"].cummax() - 1).min()
                    ),
                    "closed_trades": len(period_trades),
                    "closed_win_rate": (
                        float(np.mean(returns > 0)) if len(returns) else None
                    ),
                    "mean_trade_return": (
                        float(np.mean(returns)) if len(returns) else None
                    ),
                }
            )
    return pd.DataFrame(rows)


def summarise_random_runs(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    metrics = (
        "total_return",
        "cagr",
        "max_drawdown",
        "closed_win_rate",
        "profit_factor",
        "total_fees",
        "average_capital_utilization",
        "candidate_acceptance_rate",
    )
    keys = [
        "selection_id",
        "horizon_trading_days",
        "scope",
        "daily_entry_limit",
    ]
    rows: list[dict[str, Any]] = []
    for identity, group in frame.groupby(keys, dropna=False, sort=True):
        row = dict(zip(keys, identity, strict=True))
        row["random_runs"] = len(group)
        for metric in metrics:
            values = pd.to_numeric(group[metric], errors="coerce").dropna()
            for label, quantile in (("p05", 0.05), ("p50", 0.50), ("p95", 0.95)):
                row[f"{metric}_{label}"] = (
                    float(values.quantile(quantile)) if len(values) else None
                )
        rows.append(row)
    return pd.DataFrame(rows)


def build_daily_baseline_comparison(summary: pd.DataFrame) -> pd.DataFrame:
    selected = summary[
        summary["scope"].eq("AVAILABLE")
        & summary["daily_entry_limit"].eq("5")
        & summary["ranking_policy"].eq("quality")
    ].copy()
    rows: list[dict[str, Any]] = []
    for row in selected.itertuples(index=False):
        baseline = DAILY_BASELINES[int(row.horizon_trading_days)]
        rows.append(
            {
                "horizon_trading_days": row.horizon_trading_days,
                "selection_id_30m": row.selection_id,
                "daily_locked_combo": baseline["locked_combo"],
                "portfolio_total_return_30m": row.total_return,
                "portfolio_total_return_daily": baseline["total_return"],
                "total_return_delta_30m_minus_daily": (
                    row.total_return - baseline["total_return"]
                ),
                "portfolio_cagr_30m": row.cagr,
                "portfolio_cagr_daily": baseline["cagr"],
                "cagr_delta_30m_minus_daily": row.cagr - baseline["cagr"],
                "portfolio_mdd_30m": row.max_drawdown,
                "portfolio_mdd_daily": baseline["max_drawdown"],
                "mdd_delta_30m_minus_daily": row.max_drawdown
                - baseline["max_drawdown"],
                "daily_train_net_win_rate": baseline["train_net_win_rate"],
                "daily_validation_net_win_rate": baseline["validation_net_win_rate"],
                "daily_audit_net_win_rate": baseline["audit_net_win_rate"],
                "period_comparability": "DIFFERENT_SAMPLE_WINDOWS_REVIEW_REQUIRED",
            }
        )
    return pd.DataFrame(rows)


def _daily_curves(equity: pd.DataFrame) -> pd.DataFrame:
    if equity.empty:
        return equity
    frame = equity.copy()
    frame["trade_date"] = frame["bar_at"].dt.date
    keys = [
        "selection_id",
        "horizon_trading_days",
        "scope",
        "daily_entry_limit",
        "ranking_policy",
        "trade_date",
    ]
    return (
        frame.sort_values("bar_at", kind="stable")
        .groupby(keys, as_index=False, dropna=False)
        .tail(1)
        .reset_index(drop=True)
    )


def _write_excel(
    path: Path,
    *,
    summary: pd.DataFrame,
    random_summary: pd.DataFrame,
    period_metrics: pd.DataFrame,
    daily_curves: pd.DataFrame,
    locked: pd.DataFrame,
    baseline: pd.DataFrame,
    reveal: pd.DataFrame,
) -> None:
    def excel_safe(frame: pd.DataFrame) -> pd.DataFrame:
        value = frame.copy()
        for column in value.columns:
            if isinstance(value[column].dtype, pd.DatetimeTZDtype):
                value[column] = value[column].dt.tz_localize(None)
        return value

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.tmp{path.suffix}")
    with pd.ExcelWriter(temporary, engine="openpyxl") as writer:
        excel_safe(summary).to_excel(writer, sheet_name="Portfolio", index=False)
        excel_safe(random_summary).to_excel(
            writer, sheet_name="RandomSensitivity", index=False
        )
        excel_safe(period_metrics).to_excel(
            writer, sheet_name="AnnualQuarterRegime", index=False
        )
        excel_safe(daily_curves).to_excel(
            writer, sheet_name="NormalizedCurves", index=False
        )
        excel_safe(locked).to_excel(writer, sheet_name="LockedConfigs", index=False)
        excel_safe(baseline).to_excel(writer, sheet_name="DailyBaseline", index=False)
        if not reveal.empty:
            excel_safe(reveal.iloc[:1_048_575]).to_excel(
                writer, sheet_name="AuditReveal", index=False
            )
        disclosure = pd.DataFrame(
            {
                "item": [
                    "signal",
                    "entry",
                    "exit",
                    "fee",
                    "mark",
                    "not_modelled",
                ],
                "contract": [
                    "30分钟K线收盘揭示；只用当时及以前数据",
                    "下一根实际存在的30分钟K线开盘",
                    "第5/30/60/90个股票交易日同槽位，缺K线按候选事实的下一可交易K线",
                    "买入、卖出各0.02%",
                    "30分钟前复权收盘，缺当前K线时沿用此前最近收盘",
                    "滑点、印花税、最低佣金、100股取整",
                ],
            }
        )
        disclosure.to_excel(writer, sheet_name="Contract", index=False)
        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
    os.replace(temporary, path)


def _fmt_pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):.2%}"


def build_markdown_report(
    *,
    root: Path,
    summary: pd.DataFrame,
    random_summary: pd.DataFrame,
    period_metrics: pd.DataFrame,
    locked: pd.DataFrame,
    baseline: pd.DataFrame,
    feature_summary: Mapping[str, Any],
    reveal_summary: pd.DataFrame,
) -> str:
    dates = summary[["start_at", "end_at"]].copy()
    minimum = pd.to_datetime(dates["start_at"]).min()
    maximum = pd.to_datetime(dates["end_at"]).max()
    short_sample = minimum.year >= 2024
    grade = "SHORT_SAMPLE（短样本）" if short_sample else "FULL_HISTORY"
    lines = [
        "# CLX18 30分钟锁定组合真实资金回测",
        "",
        "## 一、数据事实",
        "",
        f"- 证据等级：**{grade}**。",
        f"- 资金曲线区间：`{minimum.isoformat()}` 至 `{maximum.isoformat()}`。",
        (
            f"- 候选事件数：`{feature_summary.get('candidate_event_rows', 'NA')}`；"
            f"Union去重信号数：`{feature_summary.get('unique_union_signals', 'NA')}`。"
        ),
        f"- AUDIT揭示摘要：`{'已读取' if not reveal_summary.empty else '本次报告未找到揭示产物'}`。",
        "- 30分钟数据由本地 MongoDB 冻结为不可变 snapshot；报告阶段不修改源数据。",
        "",
        "## 二、冻结研究假设与资金合同",
        "",
        "- 模型冠军只由 TRAIN+VALIDATION 锁定；资金模拟直接使用 `matrix/locked_config.json`，不按 AUDIT 或资金结果重选。",
        "- 过滤空间为 **F1-F6 共64个子集**，`filter_mask` 范围 `0..63`。",
        "- 初始资金500万元；40槽；每槽最多12.5万元（含买入费的资本预算）。",
        "- 同一时点先退出后入场；同股持有期间不加仓；每日新开上限分别为1/3/5/10/20/不限。",
        "- 同一可交易时点内才做质量排序；不跨未来时点重排。100组敏感性用 `SHA256(seed|candidate_id)` 确定排序。",
        "- 买卖各收0.02%；30分钟前复权收盘盯市，停牌时沿用此前最近可得前复权收盘。",
        "- 未计：**滑点、印花税、最低佣金、100股取整**。",
        "",
        "## 三、样本内锁定配置",
        "",
        "|期限|模型|触发|过滤|TRAIN n/胜率|VALIDATION n/胜率|",
        "|---:|---|---|---|---:|---:|",
    ]
    for row in locked.itertuples(index=False):
        lines.append(
            f"|{row.horizon_trading_days}|{row.model_code}|{row.trigger_name}|"
            f"{row.filter_names or '零过滤'}|"
            f"{row.train_n}/{_fmt_pct(row.train_net_win_rate)}|"
            f"{row.validation_n}/{_fmt_pct(row.validation_net_win_rate)}|"
        )
    lines.extend(
        [
            "",
            "## 四、样本外 AUDIT 一次性揭示",
            "",
            "|期限|n|净胜率|95% CI|平均净收益|中位净收益|PF|相对上证平均超额|提示|",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    audit = (
        reveal_summary[reveal_summary["scope"].eq("AUDIT")]
        .sort_values("horizon_trading_days")
        .copy()
        if not reveal_summary.empty and "scope" in reveal_summary
        else pd.DataFrame()
    )
    if audit.empty:
        lines.append("|—|—|—|—|—|—|—|—|揭示摘要尚未产出|")
    else:
        for row in audit.itertuples(index=False):
            warning = (
                "小样本；多重比较"
                if bool(getattr(row, "small_sample_warning", False))
                else "多重比较"
            )
            lines.append(
                f"|{row.horizon_trading_days}|{row.sample_count}|"
                f"{_fmt_pct(row.net_win_rate)}|"
                f"[{_fmt_pct(row.net_win_rate_ci_low)},"
                f"{_fmt_pct(row.net_win_rate_ci_high)}]|"
                f"{_fmt_pct(row.mean_net_return)}|"
                f"{_fmt_pct(row.median_net_return)}|"
                f"{'NA' if pd.isna(row.profit_factor) else f'{row.profit_factor:.2f}'}|"
                f"{_fmt_pct(row.mean_net_excess_return)}|{warning}|"
            )
    lines.extend(
        [
            "",
            "## 五、真实资金模拟（AVAILABLE、质量排序、每日上限5）",
            "",
            "|期限|总收益|CAGR|最大回撤|最长水下天数|交易数|胜率|PF|费用|平均持仓|资金占用|录取率|",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    main = summary[
        summary["scope"].eq("AVAILABLE")
        & summary["daily_entry_limit"].eq("5")
        & summary["ranking_policy"].eq("quality")
    ].sort_values("horizon_trading_days")
    for row in main.itertuples(index=False):
        lines.append(
            f"|{row.horizon_trading_days}|{_fmt_pct(row.total_return)}|"
            f"{_fmt_pct(row.cagr)}|{_fmt_pct(row.max_drawdown)}|"
            f"{row.longest_underwater_days:.1f}|{row.closed_trades}|"
            f"{_fmt_pct(row.closed_win_rate)}|"
            f"{'NA' if pd.isna(row.profit_factor) else f'{row.profit_factor:.2f}'}|"
            f"¥{row.total_fees:,.0f}|{row.average_positions:.2f}|"
            f"{_fmt_pct(row.average_capital_utilization)}|"
            f"{_fmt_pct(row.candidate_acceptance_rate)}|"
        )
    lines.extend(
        [
            "",
            "完整的每日容量限制、年度/季度/行情阶段、30分钟净值与回撤、100组SHA随机排序分位数见同目录 CSV/Parquet 和 Excel。",
            "",
            "## 六、与日线基准直接对照（每日上限5）",
            "",
            "|期限|30分钟总收益|日线总收益|30分钟CAGR|日线CAGR|30分钟MDD|日线MDD|",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in baseline.sort_values("horizon_trading_days").itertuples(index=False):
        lines.append(
            f"|{row.horizon_trading_days}|{_fmt_pct(row.portfolio_total_return_30m)}|"
            f"{_fmt_pct(row.portfolio_total_return_daily)}|"
            f"{_fmt_pct(row.portfolio_cagr_30m)}|{_fmt_pct(row.portfolio_cagr_daily)}|"
            f"{_fmt_pct(row.portfolio_mdd_30m)}|{_fmt_pct(row.portfolio_mdd_daily)}|"
        )
    selected_models = set(locked["model_code"].astype(str).str.split(",").explode())
    preferred = [
        code for code in ("S0006", "S0016", "S0000") if code in selected_models
    ]
    reentered = [code for code in ("S0008", "S0013") if code in selected_models]
    lines.extend(
        [
            "",
            "> 日线和30分钟样本区间不相同；上表是合同基准对照，不把差值解释成纯周期因果效应。",
            "",
            "## 七、逐项回答",
            "",
        ]
    )
    for horizon in (30, 60):
        row = main[main["horizon_trading_days"].eq(horizon)]
        if len(row):
            item = row.iloc[0]
            audit_row = audit[audit["horizon_trading_days"].eq(horizon)]
            audit_text = (
                f"、AUDIT净胜率 `{_fmt_pct(audit_row.iloc[0].net_win_rate)}`"
                f"、AUDIT平均净收益 `{_fmt_pct(audit_row.iloc[0].mean_net_return)}`"
                if len(audit_row)
                else ""
            )
            lines.append(
                f"- **{horizon}日稳定性**：资金端净收益 `{_fmt_pct(item.total_return)}`、"
                f"MDD `{_fmt_pct(item.max_drawdown)}`{audit_text}；"
                "跨年/季度一致性须结合 `period_metrics.csv`，"
                "不以单一胜率下结论。"
            )
    five = main[main["horizon_trading_days"].eq(5)]
    if len(five):
        item = five.iloc[0]
        audit_five = audit[audit["horizon_trading_days"].eq(5)]
        audit_five_text = (
            f"30分钟AUDIT净胜率 `{_fmt_pct(audit_five.iloc[0].net_win_rate)}`、"
            f"平均净收益 `{_fmt_pct(audit_five.iloc[0].mean_net_return)}`；"
            if len(audit_five)
            else "30分钟AUDIT揭示摘要尚未产出；"
        )
        lines.append(
            f"- **5日样本外表现**：日线AUDIT胜率47.61%；{audit_five_text}"
            "30分钟资金端总收益"
            f"`{_fmt_pct(item.total_return)}`、CAGR `{_fmt_pct(item.cagr)}`。"
            "失效判断同时看净收益、样本量和资金回撤。"
        )
    lines.extend(
        [
            (
                f"- **90日高胜率来源**：本轮证据等级为 `{grade}`；若数据始于2024，"
                "则90日结论天然主要由2024年后行情贡献，不能外推到2015年以来。"
            ),
            (
                f"- **模型优先级**：锁定冠军中 S0006/S0016/S0000 命中为"
                f"`{preferred or '无'}`。"
            ),
            (
                f"- **S0008/S0013重新进入**：锁定冠军中命中为 `{reentered or '无'}`；"
                "这只表示TRAIN+VALIDATION选择结果。"
            ),
            (
                "- **费用覆盖**：表内净值已逐笔扣买卖各0.02%，累计费用和换手已输出；"
                "更高信号频率是否值得，以净CAGR、MDD和录取率共同判断。"
            ),
            (
                "- **新增信息还是拆密**：用候选事件数/Union去重信号数、同股同揭示模型数、"
                "录取率及随机排序区间共同审计；高重复且收益无改善更接近“拆得更密”。"
            ),
            "",
            "## 八、产物与复现",
            "",
            f"- 结果目录：`{(root / 'portfolio').resolve()}`",
            "- 复现命令见 `portfolio/reproduce_command.txt`；输入与输出SHA256见 `portfolio/manifest.json`。",
            "- 数据事实、研究假设、样本内锁定、AUDIT揭示与资金模拟在本报告中分区呈现。",
            "",
        ]
    )
    return "\n".join(lines)


def _load_feature_summary(root: Path, events: pd.DataFrame) -> dict[str, Any]:
    path = root / "features" / "summary.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "candidate_event_rows": len(events),
        "unique_union_signals": (
            int(events["union_signal_id"].nunique())
            if "union_signal_id" in events
            else None
        ),
        "unique_stocks": int(events["code"].nunique()),
    }


def _manifest_entry(
    path: Path, root: Path, *, rows: int | None = None
) -> dict[str, Any]:
    return {
        "logical_path": path.relative_to(root).as_posix(),
        "rows": rows,
        "file_size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def run_portfolios(
    *,
    root: Path,
    random_seeds: int = 100,
    include_audit_scope: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    if random_seeds < 0:
        raise PortfolioContractError("random_seeds must be non-negative")
    event_path = root / "features" / "candidate_events.parquet"
    lock_path = root / "matrix" / "locked_config.json"
    if not event_path.is_file():
        raise PortfolioContractError(f"candidate events are missing: {event_path}")
    selections = load_locked_selections(lock_path)
    event_columns = [
        "signal_fact_id",
        "union_signal_id",
        "code",
        "model_code",
        "reveal_at",
        "entry_at",
        "qfq_entry_open",
        "entry_executable",
        "entry_status",
        "concurrent_trigger_mask",
        "concurrent_trigger_count",
        "filter_pass_mask",
        "same_code_reveal_model_count",
        "same_reveal_event_count",
        "amount_median_20d",
        "raw_entry_gap",
        "market_regime",
        "split_id",
    ]
    for horizon in HORIZONS:
        event_columns.extend(
            (
                f"h{horizon}_status",
                f"h{horizon}_exit_at",
                f"h{horizon}_gross_return",
            )
        )
    events = pd.read_parquet(event_path, columns=event_columns)
    scopes = ["AVAILABLE"]
    if (
        include_audit_scope
        and "split_id" in events
        and events["split_id"].eq("AUDIT").any()
    ):
        scopes.append("AUDIT")
    selected: dict[tuple[str, str], pd.DataFrame] = {}
    for selection in selections:
        for scope in scopes:
            selected[(selection.selection_id, scope)] = select_locked_candidates(
                events, selection, scope=scope
            )
    available_frames = [
        selected[(selection.selection_id, "AVAILABLE")] for selection in selections
    ]
    codes = {
        str(code)
        for frame in available_frames
        for code in frame.get("code", pd.Series(dtype=str)).astype(str).unique()
    }
    marks = MarkStore(root)
    marks.load(codes)
    scope_clocks = {"AVAILABLE": build_simulation_clock(root, available_frames, marks)}
    if "AUDIT" in scopes:
        audit_frames = [
            selected[(selection.selection_id, "AUDIT")] for selection in selections
        ]
        if any(not frame.empty for frame in audit_frames):
            scope_clocks["AUDIT"] = build_simulation_clock(root, audit_frames, marks)
        else:
            scope_clocks["AUDIT"] = scope_clocks["AVAILABLE"]
    segment_path = root / "features" / "market_segments.csv"
    segments = (
        pd.read_csv(segment_path, encoding="utf-8-sig")
        if segment_path.is_file()
        else pd.DataFrame()
    )
    summaries: list[dict[str, Any]] = []
    random_summaries: list[dict[str, Any]] = []
    quality_equity: list[pd.DataFrame] = []
    quality_trades: list[pd.DataFrame] = []
    quality_decisions: list[pd.DataFrame] = []
    periods: list[pd.DataFrame] = []
    for selection in selections:
        for scope in scopes:
            frame = selected[(selection.selection_id, scope)]
            for daily_limit in DAILY_ENTRY_LIMITS:
                quality = simulate_portfolio(
                    frame,
                    selection=selection,
                    scope=scope,
                    clock=scope_clocks[scope],
                    marks=marks,
                    daily_entry_limit=daily_limit,
                    ranking_policy="quality",
                )
                summaries.append(quality.summary)
                quality_equity.append(quality.equity)
                quality_trades.append(quality.trades)
                quality_decisions.append(quality.decisions)
                periods.append(
                    build_period_metrics(quality.equity, quality.trades, segments)
                )
                # Random ordering is a capacity sensitivity on the full AVAILABLE
                # sequence. AUDIT receives the frozen quality run but no duplicate
                # 100-seed expansion.
                if scope == "AVAILABLE":
                    for seed in range(random_seeds):
                        random = simulate_portfolio(
                            frame,
                            selection=selection,
                            scope=scope,
                            clock=scope_clocks[scope],
                            marks=marks,
                            daily_entry_limit=daily_limit,
                            ranking_policy="sha_random",
                            random_seed=seed,
                        )
                        random_summaries.append(random.summary)
    summary_frame = pd.DataFrame(summaries)
    random_frame = pd.DataFrame(random_summaries)
    random_summary = summarise_random_runs(random_frame)
    equity_frame = pd.concat(quality_equity, ignore_index=True)
    trade_frame = (
        pd.concat(quality_trades, ignore_index=True)
        if any(not frame.empty for frame in quality_trades)
        else pd.DataFrame()
    )
    decision_frame = (
        pd.concat(quality_decisions, ignore_index=True)
        if any(not frame.empty for frame in quality_decisions)
        else pd.DataFrame()
    )
    period_frame = (
        pd.concat(periods, ignore_index=True)
        if any(not frame.empty for frame in periods)
        else pd.DataFrame()
    )
    locked_frame = pd.DataFrame([selection.as_row() for selection in selections])
    baseline_frame = build_daily_baseline_comparison(summary_frame)
    daily_curve_frame = _daily_curves(equity_frame)
    reveal_path = root / "matrix" / "reveal_matrix.parquet"
    reveal_summary_path = root / "matrix" / "reveal_summary.csv"
    reveal_frame = (
        pd.read_csv(reveal_summary_path, encoding="utf-8-sig")
        if reveal_summary_path.is_file()
        else pd.DataFrame()
    )
    feature_summary = _load_feature_summary(root, events)

    output = root / "portfolio"
    output.mkdir(parents=True, exist_ok=True)
    frames = {
        "portfolio_summary": summary_frame,
        "random_order_runs": random_frame,
        "random_order_sensitivity": random_summary,
        "period_metrics": period_frame,
        "equity_30m": equity_frame,
        "equity_daily": daily_curve_frame,
        "trades": trade_frame,
        "decisions": decision_frame,
        "locked_selections": locked_frame,
        "daily_baseline_comparison": baseline_frame,
    }
    written: list[Path] = []
    output_rows: dict[Path, int] = {}
    for name, frame in frames.items():
        parquet = output / f"{name}.parquet"
        csv = output / f"{name}.csv"
        _atomic_parquet(frame, parquet)
        _atomic_csv(frame, csv)
        written.extend((parquet, csv))
        output_rows[parquet] = len(frame)
        output_rows[csv] = len(frame)
    workbook = output / "clx_30m_portfolio_report.xlsx"
    _write_excel(
        workbook,
        summary=summary_frame,
        random_summary=random_summary,
        period_metrics=period_frame,
        daily_curves=daily_curve_frame,
        locked=locked_frame,
        baseline=baseline_frame,
        reveal=reveal_frame,
    )
    written.append(workbook)
    report = build_markdown_report(
        root=root,
        summary=summary_frame,
        random_summary=random_summary,
        period_metrics=period_frame,
        locked=locked_frame,
        baseline=baseline_frame,
        feature_summary=feature_summary,
        reveal_summary=reveal_frame,
    )
    report_path = output / "report.md"
    report_path.write_text(report, encoding="utf-8")
    written.append(report_path)
    config = {
        "study_id": STUDY_ID,
        "contract_version": PORTFOLIO_CONTRACT_VERSION,
        "filter_contract": "F1_F6_64_SUBSETS_ONLY",
        "initial_capital": INITIAL_CAPITAL,
        "max_positions": MAX_POSITIONS,
        "slot_capital_budget": SLOT_CAPITAL,
        "fee_per_side": FEE_PER_SIDE,
        "daily_entry_limits": [_limit_label(value) for value in DAILY_ENTRY_LIMITS],
        "ordering": {
            "quality": (
                "within identical entry_at: concurrent trigger count desc, "
                "same-code model count desc, crowding asc, liquidity desc, "
                "entry gap asc, candidate_id"
            ),
            "sensitivity": "SHA256(seed|candidate_id)",
            "random_seed_count": random_seeds,
        },
        "clock": "30-minute QFQ close; carry prior close through missing bars",
        "metric_formulas": {
            "one_way_turnover": "(buy_notional+sell_notional)/(2*mean_equity)",
            "two_way_turnover": "(buy_notional+sell_notional)/mean_equity",
            "profit_factor": "sum(positive_net_pnl)/abs(sum(negative_net_pnl))",
            "capital_utilization": "marked_position_value/equity",
        },
        "filter_descriptions": FILTER_DESCRIPTIONS,
        "omitted_costs": [
            "slippage",
            "stamp_duty",
            "minimum_commission",
            "100_share_rounding",
        ],
        "scopes": scopes,
        "candidate_events_sha256": sha256_file(event_path),
        "locked_config_sha256": sha256_file(lock_path),
    }
    config_path = output / "portfolio_config.json"
    _atomic_json(config_path, config)
    written.append(config_path)
    command = (
        f'& "<PYTHON>" "{Path(__file__).resolve()}" --root "{root}" '
        f"run --random-seeds {random_seeds}"
    )
    reproduce = output / "reproduce_command.txt"
    reproduce.write_text(command + "\n", encoding="utf-8")
    written.append(reproduce)
    manifest = {
        "study_id": STUDY_ID,
        "status": "COMPLETE",
        "input": {
            "candidate_events": {
                "logical_path": "features/candidate_events.parquet",
                "file_size": event_path.stat().st_size,
                "sha256": sha256_file(event_path),
            },
            "locked_config": {
                "logical_path": "matrix/locked_config.json",
                "file_size": lock_path.stat().st_size,
                "sha256": sha256_file(lock_path),
            },
            "reveal_matrix": (
                {
                    "logical_path": "matrix/reveal_matrix.parquet",
                    "file_size": reveal_path.stat().st_size,
                    "sha256": sha256_file(reveal_path),
                }
                if reveal_path.is_file()
                else None
            ),
            "reveal_summary": (
                {
                    "logical_path": "matrix/reveal_summary.csv",
                    "file_size": reveal_summary_path.stat().st_size,
                    "sha256": sha256_file(reveal_summary_path),
                }
                if reveal_summary_path.is_file()
                else None
            ),
        },
        "selection_count": len(selections),
        "quality_portfolios": len(summary_frame),
        "random_portfolios": len(random_frame),
        "mark_source_codes": len(codes),
        "mark_source_rows": marks.source_rows,
        "clock_rows": {
            scope: len(scope_clock) for scope, scope_clock in scope_clocks.items()
        },
        "outputs": [
            _manifest_entry(path, root, rows=output_rows.get(path)) for path in written
        ],
    }
    manifest_path = output / "manifest.json"
    _atomic_json(manifest_path, manifest)
    result = {
        "study_id": STUDY_ID,
        "root": str(root),
        "portfolio_dir": str(output),
        "quality_portfolios": len(summary_frame),
        "random_portfolios": len(random_frame),
        "report": str(report_path),
        "workbook": str(workbook),
        "manifest": str(manifest_path),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def rebuild_report(root: Path) -> dict[str, Any]:
    resolved = root.resolve()
    output = resolved / "portfolio"
    summary = pd.read_parquet(output / "portfolio_summary.parquet")
    random_summary = pd.read_parquet(output / "random_order_sensitivity.parquet")
    period_metrics = pd.read_parquet(output / "period_metrics.parquet")
    locked = pd.read_parquet(output / "locked_selections.parquet")
    baseline = pd.read_parquet(output / "daily_baseline_comparison.parquet")
    event_path = resolved / "features" / "candidate_events.parquet"
    try:
        events = pd.read_parquet(event_path, columns=["code", "union_signal_id"])
    except (KeyError, ValueError):
        events = pd.read_parquet(event_path, columns=["code"])
    reveal_summary_path = resolved / "matrix" / "reveal_summary.csv"
    reveal_summary = (
        pd.read_csv(reveal_summary_path, encoding="utf-8-sig")
        if reveal_summary_path.is_file()
        else pd.DataFrame()
    )
    text = build_markdown_report(
        root=resolved,
        summary=summary,
        random_summary=random_summary,
        period_metrics=period_metrics,
        locked=locked,
        baseline=baseline,
        feature_summary=_load_feature_summary(resolved, events),
        reveal_summary=reveal_summary,
    )
    path = output / "report.md"
    path.write_text(text, encoding="utf-8")
    result = {"report": str(path), "sha256": sha256_file(path)}
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def status(root: Path) -> dict[str, Any]:
    root = root.resolve()
    result = {
        "study_id": STUDY_ID,
        "root": str(root),
        "candidate_events": (root / "features" / "candidate_events.parquet").is_file(),
        "locked_config": (root / "matrix" / "locked_config.json").is_file(),
        "reveal_matrix": (root / "matrix" / "reveal_matrix.parquet").is_file(),
        "reveal_summary": (root / "matrix" / "reveal_summary.csv").is_file(),
        "portfolio_complete": (root / "portfolio" / "manifest.json").is_file(),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--random-seeds", type=int, default=100)
    run.add_argument("--no-audit-scope", action="store_true")
    commands.add_parser("report")
    commands.add_parser("status")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        run_portfolios(
            root=args.root,
            random_seeds=args.random_seeds,
            include_audit_scope=not args.no_audit_scope,
        )
    elif args.command == "report":
        rebuild_report(args.root)
    else:
        status(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
