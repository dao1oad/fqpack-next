"""Build, lock, and reveal the CLX18 30-minute F1-F6 research matrix.

The module deliberately separates model development from holdout disclosure:

* ``development`` physically reads only TRAIN and VALIDATION event rows;
* ``lock`` reads only the compact development candidate artifact;
* ``reveal`` validates the immutable lock before opening candidate events.

The six filters are represented by the low six bits of ``filter_pass_mask``.
Every one of the 64 required subsets is evaluated.  Trigger selectors cover
the seven inclusive native bits, all 127 exact masks, exactly two concurrent
bits, at least three concurrent bits, and the complete signal population.

Returns relative to the Shanghai index use an explicitly approximate daily
benchmark: the last completed index close before entry to the index close on
the stock exit trade date (backward-asof only when that date is absent).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

STUDY_ID = "clx-30m-full-trigger-f1-f6-v1"
MATRIX_CONTRACT_VERSION = 1
MODEL_CODES = tuple(f"S{model_id:04d}" for model_id in range(18))
HORIZONS = (5, 30, 60, 90)
DEVELOPMENT_SCOPES = ("TRAIN", "VALIDATION")
REVEAL_SCOPES = ("AUDIT", "AVAILABLE", "MATCHED90", "PURGED")

TRIGGER_BITS = {
    "MODEL_STRUCTURAL": 0x01,
    "PIN_BAR": 0x02,
    "ENGULFING": 0x04,
    "STRONG_FRACTAL": 0x08,
    "MA5_TURN": 0x10,
    "PRICE_VOLUME_CONFIRMATION": 0x20,
    "MACD_CROSS": 0x40,
}
TRIGGER_MASK = 0x7F

FILTER_COLUMNS = (
    "f1_raw_open_1_to_6",
    "f2_return_20d_le_0",
    "f3_drawdown_20d_ge_10pct",
    "f4_volatility_20d_ge_3pct",
    "f5_close_le_ma60d_equivalent",
    "f6_index_return_20d_le_0",
)
FILTER_NAMES = tuple(f"F{offset}" for offset in range(1, 7))
FILTER_MASK = 0x3F
FILTER_SUBSET_COUNT = 64

DEFAULT_ROOT = Path("D:/fqpack/runtime/clx-backtest/studies/" + STUDY_ID)
DEFAULT_MIN_TRAIN_SAMPLES = 60
DEFAULT_MIN_VALIDATION_SAMPLES = 30
DEFAULT_MIN_REVEAL_SAMPLES = 30
DEFAULT_TOP_PER_MODEL = 5
NOMINAL_ALPHA = 0.05


@dataclass(frozen=True)
class TriggerSelector:
    """One auditable trigger population."""

    trigger_id: str
    kind: str
    value: int | None
    name: str


def build_trigger_selectors() -> tuple[TriggerSelector, ...]:
    selectors: list[TriggerSelector] = []
    for name, bit in TRIGGER_BITS.items():
        selectors.append(
            TriggerSelector(
                trigger_id=f"SINGLE_{name}",
                kind="SINGLE_BIT",
                value=bit,
                name=name,
            )
        )
    for mask in range(1, TRIGGER_MASK + 1):
        selectors.append(
            TriggerSelector(
                trigger_id=f"EXACT_MASK_{mask:03d}",
                kind="EXACT_MASK",
                value=mask,
                name=f"EXACT_MASK_{mask:03d}",
            )
        )
    selectors.extend(
        (
            TriggerSelector(
                trigger_id="EXACTLY_2",
                kind="COUNT_EQ",
                value=2,
                name="exactly two concurrent triggers",
            ),
            TriggerSelector(
                trigger_id="AT_LEAST_3",
                kind="COUNT_GTE",
                value=3,
                name="at least three concurrent triggers",
            ),
            TriggerSelector(
                trigger_id="ALL",
                kind="ALL",
                value=None,
                name="all non-zero trigger masks",
            ),
        )
    )
    return tuple(selectors)


TRIGGER_SELECTORS = build_trigger_selectors()
TRIGGER_SELECTOR_SEMANTICS = {
    "SINGLE_BIT": (
        "inclusive membership: the named bit is set; concurrent masks also qualify"
    ),
    "EXACT_MASK": "the complete seven-bit native mask equals value",
    "COUNT_EQ": "native mask bit count equals value",
    "COUNT_GTE": "native mask bit count is at least value",
    "ALL": "all non-zero native masks",
}
EXACT_AGGREGATION_CONTRACT = {
    "EVENT": "one observation per model event",
    "UNION": "deduplicate by stock code and reveal timestamp",
    "MACRO": "one equal-weight observation per model mean",
    "DATE_BALANCED": "one equal-weight observation per reveal-date mean",
}


def trigger_selector_matches(selector: TriggerSelector, trigger_mask: int) -> bool:
    """Return the frozen selector semantics for one exact native mask."""

    mask = int(trigger_mask) & TRIGGER_MASK
    if mask == 0:
        return False
    if selector.kind == "SINGLE_BIT":
        return bool(mask & int(selector.value or 0))
    if selector.kind == "EXACT_MASK":
        return mask == int(selector.value or 0)
    if selector.kind == "COUNT_EQ":
        return mask.bit_count() == int(selector.value or 0)
    if selector.kind == "COUNT_GTE":
        return mask.bit_count() >= int(selector.value or 0)
    if selector.kind == "ALL":
        return True
    raise ValueError(f"unknown trigger selector kind: {selector.kind}")


SELECTOR_MEMBERSHIP = np.asarray(
    [
        [
            float(trigger_selector_matches(selector, exact_mask))
            for exact_mask in range(TRIGGER_MASK + 1)
        ]
        for selector in TRIGGER_SELECTORS
    ],
    dtype=np.float64,
)


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: object) -> object:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        numeric = float(value)
        return None if not math.isfinite(numeric) else numeric
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serialisable: {type(value)!r}")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_bytes(canonical_json_bytes(value) + b"\n")
    os.replace(temporary, path)


def write_frame_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    if path.suffix.lower() == ".parquet":
        frame.to_parquet(temporary, index=False)
    elif path.suffix.lower() == ".csv":
        frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    else:
        raise ValueError(f"unsupported frame path: {path}")
    os.replace(temporary, path)


class AtomicParquetWriter:
    """Stream homogeneous DataFrame chunks into one atomically replaced file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        self.writer: pq.ParquetWriter | None = None
        self.rows = 0

    def write(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if self.writer is None:
            self.writer = pq.ParquetWriter(
                self.temporary,
                table.schema,
                compression="zstd",
                use_dictionary=True,
            )
        else:
            table = table.cast(self.writer.schema, safe=False)
        self.writer.write_table(table)
        self.rows += len(frame)

    def close(self) -> None:
        if self.writer is None:
            raise RuntimeError(f"no rows were written to {self.path}")
        self.writer.close()
        self.writer = None
        os.replace(self.temporary, self.path)

    def abort(self) -> None:
        if self.writer is not None:
            self.writer.close()
            self.writer = None
        if self.temporary.exists():
            self.temporary.unlink()


def _filter_names(mask: int) -> str:
    names = [
        name for offset, name in enumerate(FILTER_NAMES) if int(mask) & (1 << offset)
    ]
    return "+".join(names) if names else "NONE"


def _selector_contract() -> list[dict[str, Any]]:
    return [asdict(selector) for selector in TRIGGER_SELECTORS]


def _logic_sha256() -> str:
    return sha256_file(Path(__file__).resolve())


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "file_size": path.stat().st_size,
        "file_sha256": sha256_file(path),
    }


def _manifest_reusable(
    manifest_path: Path,
    *,
    stage_id: str,
    output_keys: Sequence[str],
) -> bool:
    if not manifest_path.is_file():
        return False
    try:
        manifest = read_json(manifest_path)
        if manifest.get("stage_id") != stage_id:
            return False
        outputs = manifest["outputs"]
        for key in output_keys:
            meta = outputs[key]
            path = Path(str(meta["path"]))
            if not path.is_file() or sha256_file(path) != meta["file_sha256"]:
                return False
        return True
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _required_event_columns(horizons: Sequence[int]) -> list[str]:
    columns = [
        "code",
        "model_code",
        "concurrent_trigger_mask",
        "filter_pass_mask",
        "split_id",
        "reveal_at",
        "entry_trade_date",
        "index_feature_date",
        "market_regime",
    ]
    for horizon in horizons:
        columns.extend(
            (
                f"h{horizon}_status",
                f"h{horizon}_gross_return",
                f"h{horizon}_net_return",
                f"h{horizon}_exit_trade_date",
                f"h{horizon}_result_maturity_at",
                f"h{horizon}_split_boundary_status",
            )
        )
    return columns


def load_feature_events(
    path: Path,
    *,
    horizons: Sequence[int] = HORIZONS,
    split_filter: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Read only columns required by the matrix, optionally with pushdown."""

    if not path.is_file():
        raise FileNotFoundError(path)
    filters = (
        [("split_id", "in", list(split_filter))] if split_filter is not None else None
    )
    frame = pd.read_parquet(
        path,
        columns=_required_event_columns(horizons),
        filters=filters,
    )
    missing = sorted(set(_required_event_columns(horizons)) - set(frame.columns))
    if missing:
        raise RuntimeError(f"candidate events miss columns: {missing}")
    frame["model_code"] = frame["model_code"].astype(str)
    frame["split_id"] = frame["split_id"].astype(str)
    frame["concurrent_trigger_mask"] = (
        pd.to_numeric(frame["concurrent_trigger_mask"], errors="raise")
        .astype("int16")
        .map(lambda value: int(value) & TRIGGER_MASK)
    )
    if frame["concurrent_trigger_mask"].eq(0).any():
        raise RuntimeError("candidate events contain zero trigger masks")
    frame["filter_pass_mask"] = (
        pd.to_numeric(frame["filter_pass_mask"], errors="raise")
        .astype("int16")
        .map(lambda value: int(value) & FILTER_MASK)
    )
    if split_filter is not None:
        unexpected = set(frame["split_id"].unique()) - set(split_filter)
        if unexpected:
            raise RuntimeError(
                f"Parquet split pushdown leaked rows: {sorted(unexpected)}"
            )
    return frame.reset_index(drop=True)


def _to_day_array(values: Iterable[object]) -> np.ndarray:
    parsed = pd.to_datetime(pd.Series(values), errors="coerce", utc=True)
    return parsed.to_numpy(dtype="datetime64[ns]").astype("datetime64[D]")


def _reveal_day_array(values: Iterable[object]) -> np.ndarray:
    parsed = pd.to_datetime(pd.Series(values), errors="coerce", utc=True)
    local = parsed.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return local.to_numpy(dtype="datetime64[ns]").astype("datetime64[D]")


def _asof_index_close(
    targets: np.ndarray,
    index_dates: np.ndarray,
    index_closes: np.ndarray,
    *,
    strict: bool,
) -> tuple[np.ndarray, np.ndarray]:
    side = "left" if strict else "right"
    positions = np.searchsorted(index_dates, targets, side=side) - 1
    valid_target = ~np.isnat(targets)
    valid = valid_target & (positions >= 0)
    closes = np.full(len(targets), np.nan, dtype=float)
    mapped_dates = np.full(len(targets), np.datetime64("NaT"), dtype="datetime64[D]")
    closes[valid] = index_closes[positions[valid]]
    mapped_dates[valid] = index_dates[positions[valid]]
    return closes, mapped_dates


def attach_index_benchmark(
    events: pd.DataFrame,
    index: pd.DataFrame,
    *,
    horizons: Sequence[int] = HORIZONS,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Attach causal daily close-to-close index returns to stock outcomes."""

    frame = events.copy()
    required_index = {"date", "close"}
    if not required_index.issubset(index.columns):
        raise RuntimeError("index snapshot must contain date and close")
    market = index.loc[:, ["date", "close"]].copy()
    market["date"] = pd.to_datetime(market["date"], errors="coerce")
    market["close"] = pd.to_numeric(market["close"], errors="coerce")
    market = (
        market.dropna(subset=["date", "close"])
        .loc[lambda value: value["close"].gt(0)]
        .sort_values("date", kind="stable")
        .drop_duplicates("date", keep="last")
    )
    if market.empty:
        raise RuntimeError("index snapshot has no valid close")
    index_dates = (
        market["date"].to_numpy(dtype="datetime64[ns]").astype("datetime64[D]")
    )
    index_closes = market["close"].to_numpy(dtype=float)

    reveal_days = _reveal_day_array(frame["reveal_at"])
    entry_days = _to_day_array(frame["entry_trade_date"])
    base_close, base_date = _asof_index_close(
        entry_days,
        index_dates,
        index_closes,
        strict=True,
    )
    # A non-executable early event can lack entry_trade_date.  The fallback is
    # still causal because exact reveal dates are disallowed.
    missing_base = ~np.isfinite(base_close)
    fallback_close, fallback_date = _asof_index_close(
        reveal_days,
        index_dates,
        index_closes,
        strict=True,
    )
    base_close[missing_base] = fallback_close[missing_base]
    base_date[missing_base] = fallback_date[missing_base]
    future_or_same_entry = (
        ~np.isnat(base_date) & ~np.isnat(entry_days) & (base_date >= entry_days)
    )
    if future_or_same_entry.any():
        raise RuntimeError("index benchmark base must be before entry date")
    source_days = _to_day_array(frame["index_feature_date"])
    future_or_same_feature = (
        ~np.isnat(source_days) & ~np.isnat(reveal_days) & (source_days >= reveal_days)
    )
    if future_or_same_feature.any():
        raise RuntimeError("index feature date must be before reveal date")

    frame["benchmark_entry_index_date"] = pd.to_datetime(base_date)
    frame["benchmark_entry_index_close"] = base_close
    audit: dict[str, Any] = {
        "formula": (
            "Shanghai index close on the last completed day before entry "
            "to close on stock exit trade date; arithmetic excess="
            "stock net return-index return"
        ),
        "frequency": "daily close-to-close approximation",
        "base_missing_before_fallback": int(missing_base.sum()),
        "base_missing_after_fallback": int((~np.isfinite(base_close)).sum()),
        "future_or_same_day_entry_base_count": int(future_or_same_entry.sum()),
        "future_or_same_day_feature_count": int(future_or_same_feature.sum()),
        "horizons": {},
    }
    for horizon in horizons:
        exit_days = _to_day_array(frame[f"h{horizon}_exit_trade_date"])
        exit_close, mapped_exit_date = _asof_index_close(
            exit_days,
            index_dates,
            index_closes,
            strict=False,
        )
        status_ok = frame[f"h{horizon}_status"].eq("OK").to_numpy(dtype=bool)
        benchmark_valid = (
            status_ok
            & np.isfinite(base_close)
            & np.isfinite(exit_close)
            & (base_close > 0)
        )
        index_return = np.full(len(frame), np.nan, dtype=float)
        index_return[benchmark_valid] = (
            exit_close[benchmark_valid] / base_close[benchmark_valid] - 1
        )
        stock_net = pd.to_numeric(
            frame[f"h{horizon}_net_return"], errors="coerce"
        ).to_numpy(dtype=float)
        frame[f"h{horizon}_benchmark_exit_index_date"] = pd.to_datetime(
            mapped_exit_date
        )
        frame[f"h{horizon}_index_return"] = index_return
        frame[f"h{horizon}_net_excess_return"] = stock_net - index_return
        lag = exit_days.astype("int64") - mapped_exit_date.astype("int64")
        backward = benchmark_valid & (lag > 0)
        audit["horizons"][str(horizon)] = {
            "status_ok_rows": int(status_ok.sum()),
            "mapped_rows": int(benchmark_valid.sum()),
            "missing_rows": int((status_ok & ~benchmark_valid).sum()),
            "backward_asof_exit_rows": int(backward.sum()),
            "maximum_exit_mapping_lag_calendar_days": (
                int(lag[backward].max()) if backward.any() else 0
            ),
        }
    return frame, audit


def _scope_masks(
    frame: pd.DataFrame,
    *,
    horizon: int,
    scope: str,
    time_splits: Mapping[str, Sequence[str]],
    horizons: Sequence[int] = HORIZONS,
) -> dict[str, np.ndarray]:
    split_ids = frame["split_id"].astype(str).to_numpy()
    research_split_ids = tuple(
        split_id
        for split_id in ("TRAIN", "VALIDATION", "AUDIT")
        if split_id in time_splits
    )
    research = np.isin(split_ids, research_split_ids)
    status_ok = frame[f"h{horizon}_status"].eq("OK").to_numpy(dtype=bool)
    maturity_days = _to_day_array(frame[f"h{horizon}_result_maturity_at"])
    split_end = np.full(len(frame), np.datetime64("NaT"), dtype="datetime64[D]")
    for split_id in research_split_ids:
        split_end[split_ids == split_id] = np.datetime64(
            str(time_splits[split_id][1]), "D"
        )
    recomputed_purged = (
        research
        & status_ok
        & ~np.isnat(maturity_days)
        & ~np.isnat(split_end)
        & (maturity_days > split_end)
    )
    declared_boundary = (
        frame[f"h{horizon}_split_boundary_status"].fillna("").astype(str)
    )
    unknown_declared = ~declared_boundary.isin(
        ("AVAILABLE", "PURGED", "UNAVAILABLE", "OUT_OF_SCOPE")
    )
    if unknown_declared.any():
        raise RuntimeError(
            f"h{horizon} has unknown split boundary statuses: "
            f"{sorted(declared_boundary.loc[unknown_declared].unique())}"
        )
    declared_purged = declared_boundary.eq("PURGED").to_numpy(dtype=bool)
    declared_available = declared_boundary.eq("AVAILABLE").to_numpy(dtype=bool)
    if not np.array_equal(recomputed_purged, declared_purged):
        raise RuntimeError(
            f"h{horizon} split boundary status disagrees with maturity timestamp"
        )

    if scope in ("TRAIN", "VALIDATION", "AUDIT"):
        if scope not in time_splits:
            raise RuntimeError(f"study config misses {scope} split")
        candidate = split_ids == scope
        sample = candidate & declared_available
    elif scope == "AVAILABLE":
        candidate = research
        sample = candidate & declared_available
    elif scope == "MATCHED90":
        candidate = research
        jointly_mature = candidate.copy()
        for candidate_horizon in horizons:
            jointly_mature &= (
                frame[f"h{candidate_horizon}_split_boundary_status"]
                .eq("AVAILABLE")
                .to_numpy(dtype=bool)
            )
        sample = jointly_mature
    elif scope == "PURGED":
        candidate = research
        sample = declared_purged
    else:
        raise ValueError(f"unknown matrix scope: {scope}")

    return {
        "candidate": candidate,
        "status_ok": candidate & status_ok,
        "sample": sample,
        "boundary_purged": candidate & declared_purged,
    }


def _bincount_cube(
    exact_masks: np.ndarray,
    pass_masks: np.ndarray,
    selected: np.ndarray,
    *,
    weights: np.ndarray | None = None,
) -> np.ndarray:
    chosen = np.asarray(selected, dtype=bool)
    if not chosen.any():
        return np.zeros((TRIGGER_MASK + 1, FILTER_SUBSET_COUNT), dtype=np.float64)
    indexes = exact_masks[chosen].astype(np.int64) * FILTER_SUBSET_COUNT + pass_masks[
        chosen
    ].astype(np.int64)
    selected_weights = None if weights is None else weights[chosen]
    return np.bincount(
        indexes,
        weights=selected_weights,
        minlength=(TRIGGER_MASK + 1) * FILTER_SUBSET_COUNT,
    ).reshape(TRIGGER_MASK + 1, FILTER_SUBSET_COUNT)


def _superset_zeta(cube: np.ndarray) -> np.ndarray:
    """Convert exact pass masks to totals satisfying each required subset."""

    transformed = np.asarray(cube, dtype=np.float64).copy()
    for offset in range(len(FILTER_NAMES)):
        bit = 1 << offset
        for required_mask in range(FILTER_SUBSET_COUNT):
            if not required_mask & bit:
                transformed[:, required_mask] += transformed[:, required_mask | bit]
    return transformed


def _project_metric(
    exact_masks: np.ndarray,
    pass_masks: np.ndarray,
    selected: np.ndarray,
    *,
    weights: np.ndarray | None = None,
) -> np.ndarray:
    cube = _bincount_cube(
        exact_masks,
        pass_masks,
        selected,
        weights=weights,
    )
    return SELECTOR_MEMBERSHIP @ _superset_zeta(cube)


def _safe_divide(
    numerator: np.ndarray,
    denominator: np.ndarray,
) -> np.ndarray:
    result = np.full(np.broadcast_shapes(numerator.shape, denominator.shape), np.nan)
    np.divide(
        numerator,
        denominator,
        out=result,
        where=np.asarray(denominator) != 0,
    )
    return result


def _wilson_bounds(
    wins: np.ndarray,
    counts: np.ndarray,
    *,
    z: float,
) -> tuple[np.ndarray, np.ndarray]:
    rates = _safe_divide(wins, counts)
    denominator = 1 + z * z / np.where(counts > 0, counts, 1)
    center = (rates + z * z / (2 * np.where(counts > 0, counts, 1))) / denominator
    radius = (
        z
        * np.sqrt(
            rates * (1 - rates) / np.where(counts > 0, counts, 1)
            + z
            * z
            / (4 * np.where(counts > 0, counts, 1) * np.where(counts > 0, counts, 1))
        )
        / denominator
    )
    lower = center - radius
    upper = center + radius
    lower[counts <= 0] = np.nan
    upper[counts <= 0] = np.nan
    return lower, upper


def _minimum_for_scope(
    scope: str,
    *,
    min_train_samples: int,
    min_validation_samples: int,
    min_reveal_samples: int,
) -> int:
    if scope == "TRAIN":
        return int(min_train_samples)
    if scope == "VALIDATION":
        return int(min_validation_samples)
    return int(min_reveal_samples)


def build_matrix_chunk(
    frame: pd.DataFrame,
    *,
    model_code: str,
    horizon: int,
    scope: str,
    time_splits: Mapping[str, Sequence[str]],
    hypothesis_family_size: int,
    min_train_samples: int = DEFAULT_MIN_TRAIN_SAMPLES,
    min_validation_samples: int = DEFAULT_MIN_VALIDATION_SAMPLES,
    min_reveal_samples: int = DEFAULT_MIN_REVEAL_SAMPLES,
    horizons: Sequence[int] = HORIZONS,
) -> pd.DataFrame:
    """Build one model × horizon × scope matrix using exact subset transforms."""

    if hypothesis_family_size <= 0:
        raise ValueError("hypothesis_family_size must be positive")
    subset = frame.loc[frame["model_code"].eq(model_code)].reset_index(drop=True)
    exact_masks = (
        subset["concurrent_trigger_mask"].to_numpy(dtype=np.int16)
        if len(subset)
        else np.empty(0, dtype=np.int16)
    )
    pass_masks = (
        (subset["filter_pass_mask"].to_numpy(dtype=np.int16) & FILTER_MASK)
        if len(subset)
        else np.empty(0, dtype=np.int16)
    )
    scope_masks = _scope_masks(
        subset,
        horizon=horizon,
        scope=scope,
        time_splits=time_splits,
        horizons=horizons,
    )

    gross = pd.to_numeric(subset[f"h{horizon}_gross_return"], errors="coerce").to_numpy(
        dtype=float
    )
    net = pd.to_numeric(subset[f"h{horizon}_net_return"], errors="coerce").to_numpy(
        dtype=float
    )
    index_return = pd.to_numeric(
        subset[f"h{horizon}_index_return"], errors="coerce"
    ).to_numpy(dtype=float)
    excess = pd.to_numeric(
        subset[f"h{horizon}_net_excess_return"], errors="coerce"
    ).to_numpy(dtype=float)
    finite_returns = np.isfinite(gross) & np.isfinite(net)
    sample = scope_masks["sample"] & finite_returns
    benchmark_sample = sample & np.isfinite(index_return) & np.isfinite(excess)
    projected: dict[str, np.ndarray] = {
        "candidate_count": _project_metric(
            exact_masks, pass_masks, scope_masks["candidate"]
        ),
        "status_ok_count": _project_metric(
            exact_masks, pass_masks, scope_masks["status_ok"]
        ),
        "sample_count": _project_metric(exact_masks, pass_masks, sample),
        "boundary_purged_count": _project_metric(
            exact_masks, pass_masks, scope_masks["boundary_purged"]
        ),
        "gross_win_count": _project_metric(
            exact_masks, pass_masks, sample & (gross > 0)
        ),
        "net_win_count": _project_metric(exact_masks, pass_masks, sample & (net > 0)),
        "gross_return_sum": _project_metric(
            exact_masks, pass_masks, sample, weights=gross
        ),
        "net_return_sum": _project_metric(exact_masks, pass_masks, sample, weights=net),
        "net_return_square_sum": _project_metric(
            exact_masks, pass_masks, sample, weights=net * net
        ),
        "net_profit_count": _project_metric(
            exact_masks, pass_masks, sample & (net > 0)
        ),
        "net_profit_sum": _project_metric(
            exact_masks,
            pass_masks,
            sample & (net > 0),
            weights=net,
        ),
        "net_loss_count": _project_metric(exact_masks, pass_masks, sample & (net < 0)),
        "net_loss_abs_sum": _project_metric(
            exact_masks,
            pass_masks,
            sample & (net < 0),
            weights=-net,
        ),
        "benchmark_sample_count": _project_metric(
            exact_masks, pass_masks, benchmark_sample
        ),
        "index_return_sum": _project_metric(
            exact_masks,
            pass_masks,
            benchmark_sample,
            weights=index_return,
        ),
        "net_excess_return_sum": _project_metric(
            exact_masks,
            pass_masks,
            benchmark_sample,
            weights=excess,
        ),
    }

    selector_count = len(TRIGGER_SELECTORS)
    selector_indexes = np.repeat(np.arange(selector_count), FILTER_SUBSET_COUNT)
    required_masks = np.tile(
        np.arange(FILTER_SUBSET_COUNT, dtype=np.int16), selector_count
    )
    flattened = {name: values.reshape(-1) for name, values in projected.items()}
    sample_count = flattened["sample_count"]
    candidate_count = flattened["candidate_count"]
    status_ok_count = flattened["status_ok_count"]
    net_win_count = flattened["net_win_count"]
    gross_win_count = flattened["gross_win_count"]
    net_profit_count = flattened["net_profit_count"]
    net_loss_count = flattened["net_loss_count"]
    benchmark_count = flattened["benchmark_sample_count"]

    nominal_z = NormalDist().inv_cdf(1 - NOMINAL_ALPHA / 2)
    corrected_alpha = NOMINAL_ALPHA / hypothesis_family_size
    corrected_z = NormalDist().inv_cdf(1 - corrected_alpha / 2)
    net_ci_low, net_ci_high = _wilson_bounds(net_win_count, sample_count, z=nominal_z)
    corrected_low, corrected_high = _wilson_bounds(
        net_win_count, sample_count, z=corrected_z
    )
    gross_ci_low, gross_ci_high = _wilson_bounds(
        gross_win_count, sample_count, z=nominal_z
    )
    mean_net = _safe_divide(flattened["net_return_sum"], sample_count)
    net_variance = (
        _safe_divide(flattened["net_return_square_sum"], sample_count)
        - mean_net * mean_net
    )
    net_variance = np.where(net_variance < 0, 0, net_variance)
    minimum = _minimum_for_scope(
        scope,
        min_train_samples=min_train_samples,
        min_validation_samples=min_validation_samples,
        min_reveal_samples=min_reveal_samples,
    )

    selector_values = pd.array(
        [TRIGGER_SELECTORS[index].value for index in selector_indexes],
        dtype="Int16",
    )
    result = pd.DataFrame(
        {
            "scope": scope,
            "model_code": model_code,
            "trigger_id": [
                TRIGGER_SELECTORS[index].trigger_id for index in selector_indexes
            ],
            "trigger_selector_kind": [
                TRIGGER_SELECTORS[index].kind for index in selector_indexes
            ],
            "trigger_selector_value": selector_values,
            "trigger_selector_name": [
                TRIGGER_SELECTORS[index].name for index in selector_indexes
            ],
            "filter_mask": required_masks.astype(np.int16),
            "filter_names": [_filter_names(mask) for mask in required_masks],
            "filter_count": np.fromiter(
                (int(mask).bit_count() for mask in required_masks),
                dtype=np.int8,
                count=len(required_masks),
            ),
            "horizon_trading_days": int(horizon),
            "candidate_count": np.rint(candidate_count).astype(np.int64),
            "status_ok_count": np.rint(status_ok_count).astype(np.int64),
            "sample_count": np.rint(sample_count).astype(np.int64),
            "unavailable_count": np.rint(candidate_count - status_ok_count).astype(
                np.int64
            ),
            "boundary_purged_count": np.rint(flattened["boundary_purged_count"]).astype(
                np.int64
            ),
            "sample_retention_rate": _safe_divide(sample_count, candidate_count),
            "gross_win_count": np.rint(gross_win_count).astype(np.int64),
            "gross_win_rate": _safe_divide(gross_win_count, sample_count),
            "gross_win_rate_ci_low": gross_ci_low,
            "gross_win_rate_ci_high": gross_ci_high,
            "net_win_count": np.rint(net_win_count).astype(np.int64),
            "net_win_rate": _safe_divide(net_win_count, sample_count),
            "net_win_rate_ci_low": net_ci_low,
            "net_win_rate_ci_high": net_ci_high,
            "net_win_rate_bonferroni_ci_low": corrected_low,
            "net_win_rate_bonferroni_ci_high": corrected_high,
            "mean_gross_return": _safe_divide(
                flattened["gross_return_sum"], sample_count
            ),
            "mean_net_return": mean_net,
            "net_return_std": np.sqrt(net_variance),
            "average_net_win": _safe_divide(
                flattened["net_profit_sum"], net_profit_count
            ),
            "average_net_loss_abs": _safe_divide(
                flattened["net_loss_abs_sum"], net_loss_count
            ),
            "payoff_ratio": _safe_divide(
                _safe_divide(flattened["net_profit_sum"], net_profit_count),
                _safe_divide(flattened["net_loss_abs_sum"], net_loss_count),
            ),
            "profit_factor": _safe_divide(
                flattened["net_profit_sum"],
                flattened["net_loss_abs_sum"],
            ),
            "benchmark_sample_count": np.rint(benchmark_count).astype(np.int64),
            "mean_index_return": _safe_divide(
                flattened["index_return_sum"], benchmark_count
            ),
            "mean_net_excess_return": _safe_divide(
                flattened["net_excess_return_sum"], benchmark_count
            ),
            "minimum_sample_required": minimum,
            "minimum_sample_pass": sample_count >= minimum,
            "small_sample_warning": sample_count < minimum,
            "nominal_confidence_level": 1 - NOMINAL_ALPHA,
            "multiple_comparison_family_size": int(hypothesis_family_size),
            "bonferroni_alpha": corrected_alpha,
            "multiple_testing_warning": True,
        }
    )
    return result


def build_development_candidates(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    *,
    min_train_samples: int = DEFAULT_MIN_TRAIN_SAMPLES,
    min_validation_samples: int = DEFAULT_MIN_VALIDATION_SAMPLES,
) -> pd.DataFrame:
    """Join development scopes and calculate the deterministic lock score."""

    keys = (
        "model_code",
        "trigger_id",
        "trigger_selector_kind",
        "trigger_selector_value",
        "trigger_selector_name",
        "filter_mask",
        "filter_names",
        "filter_count",
        "horizon_trading_days",
    )
    metric_columns = (
        "candidate_count",
        "sample_count",
        "sample_retention_rate",
        "net_win_rate",
        "net_win_rate_ci_low",
        "net_win_rate_ci_high",
        "mean_net_return",
        "profit_factor",
        "mean_net_excess_return",
    )
    left = train.loc[:, [*keys, *metric_columns]].rename(
        columns={name: f"train_{name}" for name in metric_columns}
    )
    right = validation.loc[:, [*keys, *metric_columns]].rename(
        columns={name: f"validation_{name}" for name in metric_columns}
    )
    joined = left.merge(right, on=list(keys), how="inner", validate="one_to_one")
    eligible = (
        joined["train_sample_count"].ge(min_train_samples)
        & joined["validation_sample_count"].ge(min_validation_samples)
        & joined["train_net_win_rate_ci_low"].notna()
        & joined["validation_net_win_rate_ci_low"].notna()
        & joined["train_mean_net_return"].notna()
        & joined["validation_mean_net_return"].notna()
    )
    joined["eligible_for_lock"] = eligible
    joined["development_score"] = (
        0.30 * joined["train_net_win_rate_ci_low"]
        + 0.40 * joined["validation_net_win_rate_ci_low"]
        + 0.15 * joined[["train_net_win_rate", "validation_net_win_rate"]].min(axis=1)
        + 0.075 * joined["train_mean_net_return"].clip(-0.10, 0.10)
        + 0.075 * joined["validation_mean_net_return"].clip(-0.10, 0.10)
        - 0.002 * joined["filter_count"]
    )
    joined.loc[~eligible, "development_score"] = np.nan
    joined["selection_uses_audit"] = False
    return joined


def _candidate_sort(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(
        [
            "development_score",
            "validation_net_win_rate_ci_low",
            "validation_mean_net_return",
            "validation_sample_count",
            "filter_count",
            "model_code",
            "trigger_id",
            "filter_mask",
        ],
        ascending=[False, False, False, False, True, True, True, True],
        kind="stable",
    )


def select_locked_config(
    candidates: pd.DataFrame,
    *,
    horizons: Sequence[int] = HORIZONS,
) -> list[dict[str, Any]]:
    """Select one global champion per horizon from development facts only."""

    prohibited = [
        column
        for column in candidates.columns
        if column.lower().startswith(("audit_", "available_", "matched90_", "purged_"))
    ]
    if prohibited:
        raise RuntimeError(
            f"development candidate artifact leaks reveal columns: {prohibited}"
        )
    selections: list[dict[str, Any]] = []
    for horizon in horizons:
        eligible = candidates.loc[
            candidates["horizon_trading_days"].eq(horizon)
            & candidates["eligible_for_lock"].eq(True)
            & candidates["development_score"].notna()
        ]
        if eligible.empty:
            raise RuntimeError(
                f"no development candidate satisfies minimum samples for h{horizon}"
            )
        winner = _candidate_sort(eligible).iloc[0].to_dict()
        selector_value = winner["trigger_selector_value"]
        if pd.isna(selector_value):
            selector_value = None
        else:
            selector_value = int(selector_value)
        core = {
            "horizon_trading_days": int(horizon),
            "model_code": str(winner["model_code"]),
            "trigger_id": str(winner["trigger_id"]),
            "trigger_selector": {
                "kind": str(winner["trigger_selector_kind"]),
                "value": selector_value,
                "name": str(winner["trigger_selector_name"]),
            },
            "filter_mask": int(winner["filter_mask"]),
            "filter_names": (
                []
                if str(winner["filter_names"]) == "NONE"
                else str(winner["filter_names"]).split("+")
            ),
        }
        selection_id = "sha256:" + sha256_bytes(canonical_json_bytes(core))
        selections.append(
            {
                "selection_id": selection_id,
                **core,
                "development_score": float(winner["development_score"]),
                "train_metrics": {
                    "sample_count": int(winner["train_sample_count"]),
                    "win_rate": float(winner["train_net_win_rate"]),
                    "win_rate_ci_low": float(winner["train_net_win_rate_ci_low"]),
                    "win_rate_ci_high": float(winner["train_net_win_rate_ci_high"]),
                    "mean_net_return": float(winner["train_mean_net_return"]),
                    "profit_factor": (
                        float(winner["train_profit_factor"])
                        if pd.notna(winner["train_profit_factor"])
                        else None
                    ),
                    "mean_net_excess_return": (
                        float(winner["train_mean_net_excess_return"])
                        if pd.notna(winner["train_mean_net_excess_return"])
                        else None
                    ),
                },
                "validation_metrics": {
                    "sample_count": int(winner["validation_sample_count"]),
                    "win_rate": float(winner["validation_net_win_rate"]),
                    "win_rate_ci_low": float(winner["validation_net_win_rate_ci_low"]),
                    "win_rate_ci_high": float(
                        winner["validation_net_win_rate_ci_high"]
                    ),
                    "mean_net_return": float(winner["validation_mean_net_return"]),
                    "profit_factor": (
                        float(winner["validation_profit_factor"])
                        if pd.notna(winner["validation_profit_factor"])
                        else None
                    ),
                    "mean_net_excess_return": (
                        float(winner["validation_mean_net_excess_return"])
                        if pd.notna(winner["validation_mean_net_excess_return"])
                        else None
                    ),
                },
            }
        )
    return selections


def _study_config(root: Path) -> tuple[Path, dict[str, Any]]:
    path = root / "audit" / "study_config.json"
    config = read_json(path)
    time_splits = config.get("time_splits")
    if not isinstance(time_splits, dict):
        raise TypeError("study_config.json misses time_splits")
    for split_id in ("TRAIN", "VALIDATION", "AUDIT"):
        bounds = time_splits.get(split_id)
        if (
            not isinstance(bounds, list)
            or len(bounds) != 2
            or str(bounds[0]) > str(bounds[1])
        ):
            raise RuntimeError(f"invalid {split_id} time split")
    return path, config


def _stage_identity(payload: Mapping[str, Any]) -> str:
    return "sha256:" + sha256_bytes(canonical_json_bytes(payload))


def _development_identity(
    *,
    features_path: Path,
    config_path: Path,
    index_path: Path,
    min_train_samples: int,
    min_validation_samples: int,
    top_per_model: int,
) -> tuple[str, dict[str, Any]]:
    payload = {
        "matrix_contract_version": MATRIX_CONTRACT_VERSION,
        "logic_sha256": _logic_sha256(),
        "candidate_events_sha256": sha256_file(features_path),
        "study_config_sha256": sha256_file(config_path),
        "index_snapshot_sha256": sha256_file(index_path),
        "scopes": list(DEVELOPMENT_SCOPES),
        "models": list(MODEL_CODES),
        "horizons": list(HORIZONS),
        "trigger_selector_contract": _selector_contract(),
        "filter_contract": {
            "columns": list(FILTER_COLUMNS),
            "subsets": FILTER_SUBSET_COUNT,
            "source_mask_applied": FILTER_MASK,
        },
        "minimum_samples": {
            "TRAIN": min_train_samples,
            "VALIDATION": min_validation_samples,
        },
        "top_per_model": top_per_model,
    }
    return _stage_identity(payload), payload


def _top_development_rows(
    candidates: pd.DataFrame,
    *,
    limit: int,
) -> pd.DataFrame:
    eligible = candidates.loc[candidates["eligible_for_lock"].eq(True)]
    if eligible.empty:
        return eligible
    return _candidate_sort(eligible).head(limit).reset_index(drop=True)


def run_development(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    matrix_dir = root / "matrix"
    matrix_dir.mkdir(parents=True, exist_ok=True)
    features_path = root / "features" / "candidate_events.parquet"
    index_path = root / "snapshot" / "index_day.parquet"
    config_path, config = _study_config(root)
    if not features_path.is_file():
        raise FileNotFoundError(features_path)
    if not index_path.is_file():
        raise FileNotFoundError(index_path)

    stage_id, identity = _development_identity(
        features_path=features_path,
        config_path=config_path,
        index_path=index_path,
        min_train_samples=args.min_train_samples,
        min_validation_samples=args.min_validation_samples,
        top_per_model=args.top_per_model,
    )
    matrix_path = matrix_dir / "development_matrix.parquet"
    candidates_path = matrix_dir / "development_lock_candidates.parquet"
    summary_path = matrix_dir / "development_summary.csv"
    detailed_path = matrix_dir / "development_top_detailed.parquet"
    detailed_csv_path = matrix_dir / "development_top_detailed.csv"
    group_detail_path = matrix_dir / "development_top_group_detail.parquet"
    manifest_path = matrix_dir / "development_manifest.json"
    if not args.force and _manifest_reusable(
        manifest_path,
        stage_id=stage_id,
        output_keys=(
            "matrix",
            "lock_candidates",
            "summary",
            "top_detailed",
            "top_detailed_csv",
            "top_group_detail",
        ),
    ):
        result = {
            "stage": "development",
            "stage_id": stage_id,
            "reused": True,
            "manifest_path": str(manifest_path),
        }
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result

    # Parquet predicate pushdown is a hard anti-leakage property of this stage.
    events = load_feature_events(
        features_path,
        split_filter=DEVELOPMENT_SCOPES,
    )
    if set(events["split_id"].unique()) - set(DEVELOPMENT_SCOPES):
        raise RuntimeError("development input contains non-development rows")
    index = pd.read_parquet(index_path, columns=["date", "close"])
    events, benchmark_audit = attach_index_benchmark(events, index)
    time_splits = config["time_splits"]
    family_size = len(MODEL_CODES) * len(TRIGGER_SELECTORS) * FILTER_SUBSET_COUNT

    writer = AtomicParquetWriter(matrix_path)
    retained: list[pd.DataFrame] = []
    try:
        for model_no, model_code in enumerate(MODEL_CODES, start=1):
            model_events = events.loc[events["model_code"].eq(model_code)]
            for horizon in HORIZONS:
                train = build_matrix_chunk(
                    model_events,
                    model_code=model_code,
                    horizon=horizon,
                    scope="TRAIN",
                    time_splits=time_splits,
                    hypothesis_family_size=family_size,
                    min_train_samples=args.min_train_samples,
                    min_validation_samples=args.min_validation_samples,
                )
                validation = build_matrix_chunk(
                    model_events,
                    model_code=model_code,
                    horizon=horizon,
                    scope="VALIDATION",
                    time_splits=time_splits,
                    hypothesis_family_size=family_size,
                    min_train_samples=args.min_train_samples,
                    min_validation_samples=args.min_validation_samples,
                )
                writer.write(train)
                writer.write(validation)
                development = build_development_candidates(
                    train,
                    validation,
                    min_train_samples=args.min_train_samples,
                    min_validation_samples=args.min_validation_samples,
                )
                top = _top_development_rows(
                    development,
                    limit=args.top_per_model,
                )
                if not top.empty:
                    retained.append(top)
            if args.progress_every and model_no % args.progress_every == 0:
                print(
                    json.dumps(
                        {
                            "stage": "development",
                            "models_complete": model_no,
                            "models_total": len(MODEL_CODES),
                            "matrix_rows": writer.rows,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
        writer.close()
    except BaseException:
        writer.abort()
        raise

    if not retained:
        raise RuntimeError(
            "no TRAIN/VALIDATION candidate satisfies the minimum sample contract"
        )
    lock_candidates = pd.concat(retained, ignore_index=True)
    lock_candidates = _candidate_sort(lock_candidates).reset_index(drop=True)
    write_frame_atomic(lock_candidates, candidates_path)
    write_frame_atomic(lock_candidates, summary_path)

    detailed_frames: list[pd.DataFrame] = []
    group_frames: list[pd.DataFrame] = []
    for row in lock_candidates.to_dict(orient="records"):
        selection = _development_row_selection(row)
        model_events = events.loc[events["model_code"].eq(selection["model_code"])]
        overview, groups = build_exact_detail_tables(
            model_events,
            selection=selection,
            scopes=DEVELOPMENT_SCOPES,
            time_splits=time_splits,
            model_populations=("SELECTED_MODEL",),
            minimum_sample={
                "TRAIN": args.min_train_samples,
                "VALIDATION": args.min_validation_samples,
            },
            source_kind="DEVELOPMENT_TOP",
        )
        overview["development_score"] = float(row["development_score"])
        groups["development_score"] = float(row["development_score"])
        detailed_frames.append(overview)
        if not groups.empty:
            group_frames.append(groups)

    # Preserve a meaningful 18-model Macro/Union view for the eventual global
    # champion of each horizon without opening the sealed AUDIT rows.
    for horizon in HORIZONS:
        winner = _candidate_sort(
            lock_candidates.loc[lock_candidates["horizon_trading_days"].eq(horizon)]
        ).iloc[0]
        selection = _development_row_selection(winner.to_dict())
        overview, groups = build_exact_detail_tables(
            events,
            selection=selection,
            scopes=DEVELOPMENT_SCOPES,
            time_splits=time_splits,
            model_populations=("ALL_MODELS_SAME_RULE",),
            minimum_sample={
                "TRAIN": args.min_train_samples,
                "VALIDATION": args.min_validation_samples,
            },
            source_kind="DEVELOPMENT_GLOBAL_TOP_ALL_MODELS",
        )
        overview["development_score"] = float(winner["development_score"])
        groups["development_score"] = float(winner["development_score"])
        detailed_frames.append(overview)
        if not groups.empty:
            group_frames.append(groups)
    exact_detailed = pd.concat(detailed_frames, ignore_index=True)
    exact_groups = (
        pd.concat(group_frames, ignore_index=True) if group_frames else pd.DataFrame()
    )
    write_frame_atomic(exact_detailed, detailed_path)
    write_frame_atomic(exact_detailed, detailed_csv_path)
    write_frame_atomic(exact_groups, group_detail_path)
    output_rows_expected = (
        len(MODEL_CODES)
        * len(HORIZONS)
        * len(DEVELOPMENT_SCOPES)
        * len(TRIGGER_SELECTORS)
        * FILTER_SUBSET_COUNT
    )
    if writer.rows != output_rows_expected:
        raise RuntimeError(
            f"development matrix rows {writer.rows} != {output_rows_expected}"
        )

    manifest = {
        "study_id": STUDY_ID,
        "stage": "development",
        "stage_id": stage_id,
        "matrix_contract_version": MATRIX_CONTRACT_VERSION,
        "identity": identity,
        "data_access_contract": {
            "candidate_event_scopes_physically_read": list(DEVELOPMENT_SCOPES),
            "reveal_scopes_read": [],
            "audit_used_in_score": False,
        },
        "row_contract": {
            "matrix_rows": writer.rows,
            "trigger_selectors": len(TRIGGER_SELECTORS),
            "trigger_selector_semantics": TRIGGER_SELECTOR_SEMANTICS,
            "filter_subsets": FILTER_SUBSET_COUNT,
            "filter_subset_semantics": (
                "event qualifies when (filter_pass_mask & required_mask) "
                "equals required_mask"
            ),
            "models": len(MODEL_CODES),
            "horizons": len(HORIZONS),
            "scopes": list(DEVELOPMENT_SCOPES),
        },
        "selection_contract": {
            "score": (
                "0.30*TRAIN Wilson95 lower + 0.40*VALIDATION Wilson95 lower "
                "+ 0.15*min(TRAIN,VALIDATION win rate) "
                "+ 0.075*clipped TRAIN mean net return "
                "+ 0.075*clipped VALIDATION mean net return "
                "- 0.002*filter count"
            ),
            "minimum_samples": {
                "TRAIN": args.min_train_samples,
                "VALIDATION": args.min_validation_samples,
            },
            "multiple_testing": {
                "family_size_per_horizon": family_size,
                "nominal_alpha": NOMINAL_ALPHA,
                "bonferroni_alpha": NOMINAL_ALPHA / family_size,
                "warning": (
                    "Many correlated model/trigger/filter hypotheses are tested; "
                    "unadjusted rankings are exploratory."
                ),
            },
            "per_model_top_rows_retained": args.top_per_model,
            "global_maximum_preserved": True,
        },
        "statistics_layering": {
            "exhaustive_matrix": (
                "additive exact counts, rates, means, standard deviation, "
                "payoff ratio, profit factor, confidence intervals, and "
                "daily benchmark excess for every cell"
            ),
            "development_top_exact": (
                "exact median, P05/P25/P50/P75/P95, CVaR5, distinct stocks "
                "and dates, loss streak, PnL concentration, crowding, "
                "Event/Union/Macro/DateBalanced, year/quarter/regime groups"
            ),
            "aggregation_contract": EXACT_AGGREGATION_CONTRACT,
            "reason": (
                "non-additive order statistics are materialized for the "
                "development shortlist rather than approximated across the "
                "entire exhaustive matrix"
            ),
            "audit_rows_used": False,
        },
        "benchmark_audit": benchmark_audit,
        "outputs": {
            "matrix": _artifact(matrix_path),
            "lock_candidates": _artifact(candidates_path),
            "summary": _artifact(summary_path),
            "top_detailed": _artifact(detailed_path),
            "top_detailed_csv": _artifact(detailed_csv_path),
            "top_group_detail": _artifact(group_detail_path),
        },
    }
    write_json_atomic(manifest_path, manifest)
    result = {
        "stage": "development",
        "stage_id": stage_id,
        "reused": False,
        "matrix_rows": writer.rows,
        "lock_candidate_rows": len(lock_candidates),
        "top_detailed_rows": len(exact_detailed),
        "top_group_detail_rows": len(exact_groups),
        "manifest_path": str(manifest_path),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def _lock_identity(
    development_manifest_path: Path,
    candidates_path: Path,
) -> tuple[str, dict[str, Any]]:
    payload = {
        "matrix_contract_version": MATRIX_CONTRACT_VERSION,
        "logic_sha256": _logic_sha256(),
        "development_manifest_sha256": sha256_file(development_manifest_path),
        "development_candidates_sha256": sha256_file(candidates_path),
        "horizons": list(HORIZONS),
        "selection_count": len(HORIZONS),
    }
    return _stage_identity(payload), payload


def run_lock(args: argparse.Namespace) -> dict[str, Any]:
    """Lock without opening candidate_events or any holdout artifact."""

    root = Path(args.root).resolve()
    matrix_dir = root / "matrix"
    development_manifest_path = matrix_dir / "development_manifest.json"
    candidates_path = matrix_dir / "development_lock_candidates.parquet"
    development_manifest = read_json(development_manifest_path)
    access = development_manifest.get("data_access_contract", {})
    if access.get("candidate_event_scopes_physically_read") != list(DEVELOPMENT_SCOPES):
        raise RuntimeError(
            "development manifest does not prove TRAIN/VALIDATION isolation"
        )
    if access.get("audit_used_in_score") is not False:
        raise RuntimeError("development manifest does not prove AUDIT exclusion")
    expected_candidates = development_manifest["outputs"]["lock_candidates"]
    if (
        expected_candidates["file_sha256"] != sha256_file(candidates_path)
        or Path(str(expected_candidates["path"])).resolve() != candidates_path.resolve()
    ):
        raise RuntimeError("development lock candidate identity mismatch")

    stage_id, identity = _lock_identity(
        development_manifest_path,
        candidates_path,
    )
    locked_path = matrix_dir / "locked_config.json"
    summary_path = matrix_dir / "locked_config.csv"
    manifest_path = matrix_dir / "lock_manifest.json"
    if not args.force and _manifest_reusable(
        manifest_path,
        stage_id=stage_id,
        output_keys=("locked_config", "summary"),
    ):
        result = {
            "stage": "lock",
            "stage_id": stage_id,
            "reused": True,
            "manifest_path": str(manifest_path),
        }
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result

    candidates = pd.read_parquet(candidates_path)
    selections = select_locked_config(candidates)
    if len(selections) != len(HORIZONS):
        raise RuntimeError("lock must contain exactly one selection per horizon")
    lock_payload = {
        "study_id": STUDY_ID,
        "matrix_contract_version": MATRIX_CONTRACT_VERSION,
        "development_stage_id": development_manifest["stage_id"],
        "lock_stage_id": stage_id,
        "selection_policy": (
            "one deterministic global champion per horizon using TRAIN and "
            "VALIDATION only; holdout remains sealed"
        ),
        "filter_contract": {
            "filters": list(FILTER_NAMES),
            "subset_count": FILTER_SUBSET_COUNT,
            "mask_range": [0, FILTER_MASK],
        },
        "selections": selections,
    }
    lock_id = "sha256:" + sha256_bytes(canonical_json_bytes(lock_payload))
    locked = {"lock_id": lock_id, **lock_payload}
    write_json_atomic(locked_path, locked)
    flat_rows = []
    for selection in selections:
        flat_rows.append(
            {
                "lock_id": lock_id,
                "selection_id": selection["selection_id"],
                "horizon_trading_days": selection["horizon_trading_days"],
                "model_code": selection["model_code"],
                "trigger_id": selection["trigger_id"],
                "trigger_selector_kind": selection["trigger_selector"]["kind"],
                "trigger_selector_value": selection["trigger_selector"]["value"],
                "filter_mask": selection["filter_mask"],
                "filter_names": "+".join(selection["filter_names"]) or "NONE",
                "development_score": selection["development_score"],
                "train_sample_count": selection["train_metrics"]["sample_count"],
                "train_win_rate": selection["train_metrics"]["win_rate"],
                "validation_sample_count": selection["validation_metrics"][
                    "sample_count"
                ],
                "validation_win_rate": selection["validation_metrics"]["win_rate"],
            }
        )
    write_frame_atomic(pd.DataFrame(flat_rows), summary_path)
    manifest = {
        "study_id": STUDY_ID,
        "stage": "lock",
        "stage_id": stage_id,
        "lock_id": lock_id,
        "identity": identity,
        "data_access_contract": {
            "read": [
                "matrix/development_manifest.json",
                "matrix/development_lock_candidates.parquet",
            ],
            "candidate_events_read": False,
            "audit_or_reveal_metrics_read": False,
        },
        "outputs": {
            "locked_config": _artifact(locked_path),
            "summary": _artifact(summary_path),
        },
    }
    write_json_atomic(manifest_path, manifest)
    result = {
        "stage": "lock",
        "stage_id": stage_id,
        "lock_id": lock_id,
        "reused": False,
        "selections": len(selections),
        "manifest_path": str(manifest_path),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def _load_lock_for_reveal(root: Path) -> tuple[Path, dict[str, Any]]:
    """The first reveal read: fail closed before any event or index access."""

    path = root / "matrix" / "locked_config.json"
    locked = read_json(path)
    if locked.get("study_id") != STUDY_ID:
        raise RuntimeError("locked_config study_id mismatch")
    selections = locked.get("selections")
    if not isinstance(selections, list) or len(selections) != len(HORIZONS):
        raise RuntimeError("locked_config must contain four horizon selections")
    observed_horizons: list[int] = []
    for selection in selections:
        horizon = int(selection["horizon_trading_days"])
        observed_horizons.append(horizon)
        model_code = str(selection["model_code"])
        if model_code not in MODEL_CODES:
            raise RuntimeError(f"lock contains unknown model: {model_code}")
        filter_mask = int(selection["filter_mask"])
        if not 0 <= filter_mask <= FILTER_MASK:
            raise RuntimeError(f"lock contains invalid filter mask: {filter_mask}")
        selector = TriggerSelector(
            trigger_id=str(selection["trigger_id"]),
            kind=str(selection["trigger_selector"]["kind"]),
            value=(
                None
                if selection["trigger_selector"].get("value") is None
                else int(selection["trigger_selector"]["value"])
            ),
            name=str(selection["trigger_selector"].get("name") or ""),
        )
        if selector.trigger_id not in {
            candidate.trigger_id for candidate in TRIGGER_SELECTORS
        }:
            raise RuntimeError(
                f"lock contains unknown trigger selector: {selector.trigger_id}"
            )
        expected = next(
            candidate
            for candidate in TRIGGER_SELECTORS
            if candidate.trigger_id == selector.trigger_id
        )
        if selector.kind != expected.kind or selector.value != expected.value:
            raise RuntimeError(
                f"lock trigger selector contract mismatch: {selector.trigger_id}"
            )
    if sorted(observed_horizons) != sorted(HORIZONS):
        raise RuntimeError("locked_config horizons are incomplete or duplicated")
    payload = {key: value for key, value in locked.items() if key != "lock_id"}
    expected_lock_id = "sha256:" + sha256_bytes(canonical_json_bytes(payload))
    if locked.get("lock_id") != expected_lock_id:
        raise RuntimeError("locked_config lock_id mismatch")
    return path, locked


def _reveal_identity(
    *,
    lock_path: Path,
    features_path: Path,
    config_path: Path,
    index_path: Path,
    min_reveal_samples: int,
) -> tuple[str, dict[str, Any]]:
    payload = {
        "matrix_contract_version": MATRIX_CONTRACT_VERSION,
        "logic_sha256": _logic_sha256(),
        "locked_config_sha256": sha256_file(lock_path),
        "candidate_events_sha256": sha256_file(features_path),
        "study_config_sha256": sha256_file(config_path),
        "index_snapshot_sha256": sha256_file(index_path),
        "scopes": list(REVEAL_SCOPES),
        "models": list(MODEL_CODES),
        "horizons": list(HORIZONS),
        "trigger_selector_contract": _selector_contract(),
        "filter_contract": {
            "columns": list(FILTER_COLUMNS),
            "subsets": FILTER_SUBSET_COUNT,
            "source_mask_applied": FILTER_MASK,
        },
        "minimum_reveal_samples": min_reveal_samples,
    }
    return _stage_identity(payload), payload


def _selection_event_mask(
    frame: pd.DataFrame,
    selection: Mapping[str, Any],
    *,
    all_models: bool = False,
) -> np.ndarray:
    selector_contract = selection["trigger_selector"]
    selector = TriggerSelector(
        trigger_id=str(selection["trigger_id"]),
        kind=str(selector_contract["kind"]),
        value=(
            None
            if selector_contract.get("value") is None
            else int(selector_contract["value"])
        ),
        name=str(selector_contract.get("name") or ""),
    )
    exact_masks = frame["concurrent_trigger_mask"].to_numpy(dtype=np.int16)
    trigger = np.fromiter(
        (trigger_selector_matches(selector, int(mask)) for mask in exact_masks),
        dtype=bool,
        count=len(frame),
    )
    required_filter = int(selection["filter_mask"])
    pass_masks = frame["filter_pass_mask"].to_numpy(dtype=np.int16) & FILTER_MASK
    filters = (pass_masks & required_filter) == required_filter
    model = (
        np.ones(len(frame), dtype=bool)
        if all_models
        else frame["model_code"].eq(str(selection["model_code"])).to_numpy(dtype=bool)
    )
    return model & trigger & filters


def _longest_loss_streak(values: np.ndarray) -> int:
    longest = 0
    current = 0
    for value in values:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _selected_detailed_metrics(
    frame: pd.DataFrame,
    *,
    selection: Mapping[str, Any],
    scope: str,
    time_splits: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    horizon = int(selection["horizon_trading_days"])
    configuration = _selection_event_mask(frame, selection)
    scope_masks = _scope_masks(
        frame,
        horizon=horizon,
        scope=scope,
        time_splits=time_splits,
    )
    gross = pd.to_numeric(frame[f"h{horizon}_gross_return"], errors="coerce").to_numpy(
        dtype=float
    )
    net = pd.to_numeric(frame[f"h{horizon}_net_return"], errors="coerce").to_numpy(
        dtype=float
    )
    index_return = pd.to_numeric(
        frame[f"h{horizon}_index_return"], errors="coerce"
    ).to_numpy(dtype=float)
    excess = pd.to_numeric(
        frame[f"h{horizon}_net_excess_return"], errors="coerce"
    ).to_numpy(dtype=float)
    sample = (
        configuration & scope_masks["sample"] & np.isfinite(gross) & np.isfinite(net)
    )
    sample_frame = frame.loc[sample].copy()
    sample_frame["_net"] = net[sample]
    sample_frame = sample_frame.sort_values(["reveal_at", "code"], kind="stable")
    net_values = sample_frame["_net"].to_numpy(dtype=float)
    gross_values = gross[sample]
    benchmark = sample & np.isfinite(index_return) & np.isfinite(excess)
    candidate_count = int((configuration & scope_masks["candidate"]).sum())
    status_ok_count = int((configuration & scope_masks["status_ok"]).sum())
    boundary_count = int((configuration & scope_masks["boundary_purged"]).sum())
    count = len(net_values)
    wins = int((net_values > 0).sum())
    ci_low, ci_high = _wilson_bounds(
        np.asarray([wins], dtype=float),
        np.asarray([count], dtype=float),
        z=NormalDist().inv_cdf(1 - NOMINAL_ALPHA / 2),
    )
    positive = net_values[net_values > 0]
    negative = net_values[net_values < 0]
    reveal_dates = (
        pd.to_datetime(sample_frame["reveal_at"], utc=True)
        .dt.tz_convert("Asia/Shanghai")
        .dt.date
        if count
        else pd.Series(dtype=object)
    )
    daily_counts = reveal_dates.value_counts() if count else pd.Series(dtype=int)
    positive_total = float(positive.sum()) if len(positive) else 0.0
    top_count = max(1, math.ceil(len(positive) * 0.10)) if len(positive) else 0
    concentration = (
        float(np.sort(positive)[-top_count:].sum() / positive_total)
        if positive_total > 0 and top_count
        else np.nan
    )
    result: dict[str, Any] = {
        "lock_id": "",
        "selection_id": str(selection["selection_id"]),
        "scope": scope,
        "horizon_trading_days": horizon,
        "model_code": str(selection["model_code"]),
        "trigger_id": str(selection["trigger_id"]),
        "trigger_selector_kind": str(selection["trigger_selector"]["kind"]),
        "trigger_selector_value": selection["trigger_selector"].get("value"),
        "filter_mask": int(selection["filter_mask"]),
        "filter_names": "+".join(selection["filter_names"]) or "NONE",
        "candidate_count": candidate_count,
        "status_ok_count": status_ok_count,
        "sample_count": count,
        "unavailable_count": candidate_count - status_ok_count,
        "boundary_purged_count": boundary_count,
        "unique_stock_count": (
            int(sample_frame["code"].astype(str).nunique()) if count else 0
        ),
        "unique_signal_date_count": int(reveal_dates.nunique()) if count else 0,
        "gross_win_rate": float((gross_values > 0).mean()) if count else np.nan,
        "net_win_rate": wins / count if count else np.nan,
        "net_win_rate_ci_low": float(ci_low[0]) if count else np.nan,
        "net_win_rate_ci_high": float(ci_high[0]) if count else np.nan,
        "mean_gross_return": float(gross_values.mean()) if count else np.nan,
        "mean_net_return": float(net_values.mean()) if count else np.nan,
        "median_net_return": float(np.median(net_values)) if count else np.nan,
        "average_net_win": (float(positive.mean()) if len(positive) else np.nan),
        "average_net_loss_abs": (float(-negative.mean()) if len(negative) else np.nan),
        "payoff_ratio": (
            float(positive.mean() / -negative.mean())
            if len(positive) and len(negative)
            else np.nan
        ),
        "profit_factor": (
            float(positive.sum() / -negative.sum())
            if len(negative) and -negative.sum() > 0
            else np.nan
        ),
        "p05_net_return": (float(np.quantile(net_values, 0.05)) if count else np.nan),
        "p25_net_return": (float(np.quantile(net_values, 0.25)) if count else np.nan),
        "p50_net_return": (float(np.quantile(net_values, 0.50)) if count else np.nan),
        "p75_net_return": (float(np.quantile(net_values, 0.75)) if count else np.nan),
        "p95_net_return": (float(np.quantile(net_values, 0.95)) if count else np.nan),
        "cvar5_net_return": (
            float(net_values[net_values <= np.quantile(net_values, 0.05)].mean())
            if count
            else np.nan
        ),
        "mean_index_return": (
            float(index_return[benchmark].mean()) if benchmark.any() else np.nan
        ),
        "mean_net_excess_return": (
            float(excess[benchmark].mean()) if benchmark.any() else np.nan
        ),
        "max_consecutive_losses": _longest_loss_streak(net_values),
        "positive_pnl_top10pct_concentration": concentration,
        "mean_same_day_signal_crowding": (
            float(daily_counts.mean()) if len(daily_counts) else np.nan
        ),
        "peak_same_day_signal_crowding": (
            int(daily_counts.max()) if len(daily_counts) else 0
        ),
    }
    return result


def _development_row_selection(row: Mapping[str, Any]) -> dict[str, Any]:
    selector_value = row["trigger_selector_value"]
    selector_value = None if pd.isna(selector_value) else int(selector_value)
    filter_names = (
        []
        if str(row["filter_names"]) == "NONE"
        else str(row["filter_names"]).split("+")
    )
    core = {
        "horizon_trading_days": int(row["horizon_trading_days"]),
        "model_code": str(row["model_code"]),
        "trigger_id": str(row["trigger_id"]),
        "trigger_selector": {
            "kind": str(row["trigger_selector_kind"]),
            "value": selector_value,
            "name": str(row["trigger_selector_name"]),
        },
        "filter_mask": int(row["filter_mask"]),
        "filter_names": filter_names,
    }
    return {
        "selection_id": "sha256:" + sha256_bytes(canonical_json_bytes(core)),
        **core,
    }


def _prepared_selection_sample(
    frame: pd.DataFrame,
    *,
    selection: Mapping[str, Any],
    scope: str,
    time_splits: Mapping[str, Sequence[str]],
    all_models: bool,
) -> tuple[pd.DataFrame, dict[str, int]]:
    horizon = int(selection["horizon_trading_days"])
    configuration = _selection_event_mask(
        frame,
        selection,
        all_models=all_models,
    )
    scope_masks = _scope_masks(
        frame,
        horizon=horizon,
        scope=scope,
        time_splits=time_splits,
    )
    gross = pd.to_numeric(frame[f"h{horizon}_gross_return"], errors="coerce").to_numpy(
        dtype=float
    )
    net = pd.to_numeric(frame[f"h{horizon}_net_return"], errors="coerce").to_numpy(
        dtype=float
    )
    index_return = pd.to_numeric(
        frame[f"h{horizon}_index_return"], errors="coerce"
    ).to_numpy(dtype=float)
    excess = pd.to_numeric(
        frame[f"h{horizon}_net_excess_return"], errors="coerce"
    ).to_numpy(dtype=float)
    sample_mask = (
        configuration & scope_masks["sample"] & np.isfinite(gross) & np.isfinite(net)
    )
    sample = frame.loc[
        sample_mask,
        ["code", "model_code", "reveal_at", "market_regime"],
    ].copy()
    sample["_gross"] = gross[sample_mask]
    sample["_net"] = net[sample_mask]
    sample["_index"] = index_return[sample_mask]
    sample["_excess"] = excess[sample_mask]
    local_reveal = pd.to_datetime(sample["reveal_at"], utc=True).dt.tz_convert(
        "Asia/Shanghai"
    )
    sample["_reveal_date"] = local_reveal.dt.date
    sample["_year"] = local_reveal.dt.year.astype(str)
    sample["_quarter"] = (
        local_reveal.dt.year.astype(str) + "Q" + local_reveal.dt.quarter.astype(str)
    )
    sample["_regime"] = sample["market_regime"].fillna("UNKNOWN").astype(str)
    sample = sample.sort_values(
        ["reveal_at", "code", "model_code"], kind="stable"
    ).reset_index(drop=True)
    counts = {
        "candidate_count": int((configuration & scope_masks["candidate"]).sum()),
        "status_ok_count": int((configuration & scope_masks["status_ok"]).sum()),
        "boundary_purged_count": int(
            (configuration & scope_masks["boundary_purged"]).sum()
        ),
    }
    return sample, counts


def _aggregation_observations(
    sample: pd.DataFrame,
    aggregation: str,
) -> pd.DataFrame:
    value_columns = ["_gross", "_net", "_index", "_excess"]
    if aggregation == "EVENT":
        return sample.loc[:, value_columns].copy()
    if aggregation == "UNION":
        return (
            sample.drop_duplicates(["code", "reveal_at"], keep="first")
            .loc[:, value_columns]
            .reset_index(drop=True)
        )
    if aggregation == "DATE_BALANCED":
        return (
            sample.groupby("_reveal_date", sort=True, observed=True)[value_columns]
            .mean()
            .reset_index(drop=True)
        )
    if aggregation == "MACRO":
        return (
            sample.groupby("model_code", sort=True, observed=True)[value_columns]
            .mean()
            .reset_index(drop=True)
        )
    raise ValueError(f"unknown exact aggregation: {aggregation}")


def _exact_observation_metrics(
    observations: pd.DataFrame,
    *,
    underlying: pd.DataFrame,
    counts: Mapping[str, int],
) -> dict[str, Any]:
    gross = observations["_gross"].to_numpy(dtype=float)
    net = observations["_net"].to_numpy(dtype=float)
    finite = np.isfinite(gross) & np.isfinite(net)
    gross = gross[finite]
    net = net[finite]
    index_return = observations["_index"].to_numpy(dtype=float)[finite]
    excess = observations["_excess"].to_numpy(dtype=float)[finite]
    count = len(net)
    wins = int((net > 0).sum())
    ci_low, ci_high = _wilson_bounds(
        np.asarray([wins], dtype=float),
        np.asarray([count], dtype=float),
        z=NormalDist().inv_cdf(1 - NOMINAL_ALPHA / 2),
    )
    positive = net[net > 0]
    negative = net[net < 0]
    benchmark = np.isfinite(index_return) & np.isfinite(excess)
    daily_counts = (
        underlying.groupby("_reveal_date", observed=True).size()
        if len(underlying)
        else pd.Series(dtype=int)
    )
    positive_total = float(positive.sum()) if len(positive) else 0.0
    top_count = max(1, math.ceil(len(positive) * 0.10)) if len(positive) else 0
    concentration = (
        float(np.sort(positive)[-top_count:].sum() / positive_total)
        if positive_total > 0 and top_count
        else np.nan
    )
    return {
        **{name: int(value) for name, value in counts.items()},
        "unavailable_count": int(counts["candidate_count"] - counts["status_ok_count"]),
        "underlying_event_count": len(underlying),
        "sample_count": count,
        "unique_stock_count": int(underlying["code"].astype(str).nunique()),
        "unique_signal_date_count": int(underlying["_reveal_date"].nunique()),
        "unique_model_count": int(underlying["model_code"].astype(str).nunique()),
        "gross_win_rate": float((gross > 0).mean()) if count else np.nan,
        "net_win_rate": wins / count if count else np.nan,
        "net_win_rate_ci_low": float(ci_low[0]) if count else np.nan,
        "net_win_rate_ci_high": float(ci_high[0]) if count else np.nan,
        "mean_gross_return": float(gross.mean()) if count else np.nan,
        "mean_net_return": float(net.mean()) if count else np.nan,
        "median_net_return": float(np.median(net)) if count else np.nan,
        "average_net_win": (float(positive.mean()) if len(positive) else np.nan),
        "average_net_loss_abs": (float(-negative.mean()) if len(negative) else np.nan),
        "payoff_ratio": (
            float(positive.mean() / -negative.mean())
            if len(positive) and len(negative)
            else np.nan
        ),
        "profit_factor": (
            float(positive.sum() / -negative.sum())
            if len(negative) and -negative.sum() > 0
            else np.nan
        ),
        "p05_net_return": (float(np.quantile(net, 0.05)) if count else np.nan),
        "p25_net_return": (float(np.quantile(net, 0.25)) if count else np.nan),
        "p50_net_return": (float(np.quantile(net, 0.50)) if count else np.nan),
        "p75_net_return": (float(np.quantile(net, 0.75)) if count else np.nan),
        "p95_net_return": (float(np.quantile(net, 0.95)) if count else np.nan),
        "cvar5_net_return": (
            float(net[net <= np.quantile(net, 0.05)].mean()) if count else np.nan
        ),
        "mean_index_return": (
            float(index_return[benchmark].mean()) if benchmark.any() else np.nan
        ),
        "mean_net_excess_return": (
            float(excess[benchmark].mean()) if benchmark.any() else np.nan
        ),
        "max_consecutive_losses": _longest_loss_streak(net),
        "positive_pnl_top10pct_concentration": concentration,
        "mean_same_day_signal_crowding": (
            float(daily_counts.mean()) if len(daily_counts) else np.nan
        ),
        "peak_same_day_signal_crowding": (
            int(daily_counts.max()) if len(daily_counts) else 0
        ),
    }


def build_exact_detail_tables(
    frame: pd.DataFrame,
    *,
    selection: Mapping[str, Any],
    scopes: Sequence[str],
    time_splits: Mapping[str, Sequence[str]],
    model_populations: Sequence[str],
    minimum_sample: int | Mapping[str, int],
    source_kind: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Exact, non-additive statistics for shortlisted or locked configs."""

    overview_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    for scope in scopes:
        required_sample = (
            int(minimum_sample[scope])
            if isinstance(minimum_sample, Mapping)
            else int(minimum_sample)
        )
        for population in model_populations:
            if population not in (
                "SELECTED_MODEL",
                "ALL_MODELS_SAME_RULE",
            ):
                raise ValueError(f"unknown model population: {population}")
            sample, counts = _prepared_selection_sample(
                frame,
                selection=selection,
                scope=scope,
                time_splits=time_splits,
                all_models=population == "ALL_MODELS_SAME_RULE",
            )
            metadata = {
                "source_kind": source_kind,
                "selection_id": str(selection["selection_id"]),
                "scope": scope,
                "model_population": population,
                "horizon_trading_days": int(selection["horizon_trading_days"]),
                "selected_model_code": str(selection["model_code"]),
                "trigger_id": str(selection["trigger_id"]),
                "trigger_selector_kind": str(selection["trigger_selector"]["kind"]),
                "trigger_selector_value": selection["trigger_selector"].get("value"),
                "filter_mask": int(selection["filter_mask"]),
                "filter_names": "+".join(selection["filter_names"]) or "NONE",
            }
            for aggregation in ("EVENT", "UNION", "MACRO", "DATE_BALANCED"):
                observations = _aggregation_observations(sample, aggregation)
                metrics = _exact_observation_metrics(
                    observations,
                    underlying=sample,
                    counts=counts,
                )
                overview_rows.append(
                    {
                        **metadata,
                        "aggregation": aggregation,
                        **metrics,
                        "minimum_sample_required": required_sample,
                        "minimum_sample_pass": len(sample) >= required_sample,
                        "small_sample_warning": len(sample) < required_sample,
                        "multiple_testing_warning": True,
                    }
                )

            group_contracts = (
                ("YEAR", "_year"),
                ("QUARTER", "_quarter"),
                ("MARKET_REGIME", "_regime"),
            )
            for group_dimension, group_column in group_contracts:
                for group_value, grouped in sample.groupby(
                    group_column,
                    sort=True,
                    observed=True,
                ):
                    for aggregation in (
                        "EVENT",
                        "UNION",
                        "MACRO",
                        "DATE_BALANCED",
                    ):
                        observations = _aggregation_observations(
                            grouped,
                            aggregation,
                        )
                        metrics = _exact_observation_metrics(
                            observations,
                            underlying=grouped,
                            counts={
                                "candidate_count": len(grouped),
                                "status_ok_count": len(grouped),
                                "boundary_purged_count": 0,
                            },
                        )
                        group_rows.append(
                            {
                                **metadata,
                                "group_dimension": group_dimension,
                                "group_value": str(group_value),
                                "aggregation": aggregation,
                                **metrics,
                                "minimum_sample_required": required_sample,
                                "minimum_sample_pass": (
                                    len(grouped) >= required_sample
                                ),
                                "small_sample_warning": (
                                    len(grouped) < required_sample
                                ),
                                "multiple_testing_warning": True,
                            }
                        )
    return pd.DataFrame(overview_rows), pd.DataFrame(group_rows)


def run_reveal(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()

    # Keep this before _study_config, hashing, index reads, and event reads.
    lock_path, locked = _load_lock_for_reveal(root)

    matrix_dir = root / "matrix"
    features_path = root / "features" / "candidate_events.parquet"
    index_path = root / "snapshot" / "index_day.parquet"
    config_path, config = _study_config(root)
    if not features_path.is_file():
        raise FileNotFoundError(features_path)
    if not index_path.is_file():
        raise FileNotFoundError(index_path)
    stage_id, identity = _reveal_identity(
        lock_path=lock_path,
        features_path=features_path,
        config_path=config_path,
        index_path=index_path,
        min_reveal_samples=args.min_reveal_samples,
    )
    matrix_path = matrix_dir / "reveal_matrix.parquet"
    summary_path = matrix_dir / "reveal_summary.csv"
    detailed_path = matrix_dir / "reveal_locked_detailed.parquet"
    group_detail_path = matrix_dir / "reveal_locked_group_detail.parquet"
    manifest_path = matrix_dir / "reveal_manifest.json"
    if not args.force and _manifest_reusable(
        manifest_path,
        stage_id=stage_id,
        output_keys=("matrix", "summary", "locked_detailed", "group_detail"),
    ):
        result = {
            "stage": "reveal",
            "stage_id": stage_id,
            "lock_id": locked["lock_id"],
            "reused": True,
            "manifest_path": str(manifest_path),
        }
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result

    events = load_feature_events(features_path)
    index = pd.read_parquet(index_path, columns=["date", "close"])
    events, benchmark_audit = attach_index_benchmark(events, index)
    time_splits = config["time_splits"]
    family_size = len(MODEL_CODES) * len(TRIGGER_SELECTORS) * FILTER_SUBSET_COUNT
    writer = AtomicParquetWriter(matrix_path)
    try:
        for model_no, model_code in enumerate(MODEL_CODES, start=1):
            model_events = events.loc[events["model_code"].eq(model_code)]
            for horizon in HORIZONS:
                for scope in REVEAL_SCOPES:
                    chunk = build_matrix_chunk(
                        model_events,
                        model_code=model_code,
                        horizon=horizon,
                        scope=scope,
                        time_splits=time_splits,
                        hypothesis_family_size=family_size,
                        min_reveal_samples=args.min_reveal_samples,
                    )
                    writer.write(chunk)
            if args.progress_every and model_no % args.progress_every == 0:
                print(
                    json.dumps(
                        {
                            "stage": "reveal",
                            "models_complete": model_no,
                            "models_total": len(MODEL_CODES),
                            "matrix_rows": writer.rows,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
        writer.close()
    except BaseException:
        writer.abort()
        raise

    expected_rows = (
        len(MODEL_CODES)
        * len(HORIZONS)
        * len(REVEAL_SCOPES)
        * len(TRIGGER_SELECTORS)
        * FILTER_SUBSET_COUNT
    )
    if writer.rows != expected_rows:
        raise RuntimeError(f"reveal matrix rows {writer.rows} != {expected_rows}")

    detailed_rows: list[dict[str, Any]] = []
    for selection in locked["selections"]:
        for scope in REVEAL_SCOPES:
            row = _selected_detailed_metrics(
                events,
                selection=selection,
                scope=scope,
                time_splits=time_splits,
            )
            row["lock_id"] = locked["lock_id"]
            detailed_rows.append(row)
    detailed = pd.DataFrame(detailed_rows).sort_values(
        ["horizon_trading_days", "scope"], kind="stable"
    )
    detailed["minimum_sample_required"] = int(args.min_reveal_samples)
    detailed["minimum_sample_pass"] = detailed["sample_count"].ge(
        args.min_reveal_samples
    )
    detailed["small_sample_warning"] = ~detailed["minimum_sample_pass"]
    detailed["multiple_testing_warning"] = True
    write_frame_atomic(detailed, summary_path)

    exact_frames: list[pd.DataFrame] = []
    exact_group_frames: list[pd.DataFrame] = []
    for selection in locked["selections"]:
        overview, groups = build_exact_detail_tables(
            events,
            selection=selection,
            scopes=REVEAL_SCOPES,
            time_splits=time_splits,
            model_populations=(
                "SELECTED_MODEL",
                "ALL_MODELS_SAME_RULE",
            ),
            minimum_sample=args.min_reveal_samples,
            source_kind="LOCKED_AFTER_REVEAL",
        )
        overview["lock_id"] = locked["lock_id"]
        groups["lock_id"] = locked["lock_id"]
        exact_frames.append(overview)
        if not groups.empty:
            exact_group_frames.append(groups)
    exact_detailed = pd.concat(exact_frames, ignore_index=True)
    exact_groups = (
        pd.concat(exact_group_frames, ignore_index=True)
        if exact_group_frames
        else pd.DataFrame()
    )
    write_frame_atomic(exact_detailed, detailed_path)
    write_frame_atomic(exact_groups, group_detail_path)

    manifest = {
        "study_id": STUDY_ID,
        "stage": "reveal",
        "stage_id": stage_id,
        "lock_id": locked["lock_id"],
        "matrix_contract_version": MATRIX_CONTRACT_VERSION,
        "identity": identity,
        "data_access_contract": {
            "locked_config_validated_before_candidate_events_read": True,
            "revealed_scopes": list(REVEAL_SCOPES),
            "development_selection_recomputed_after_reveal": False,
        },
        "scope_definitions": {
            "AUDIT": (
                "AUDIT reveal rows with OK outcome whose exit trade date does "
                "not cross the frozen AUDIT end"
            ),
            "AVAILABLE": (
                "all TRAIN/VALIDATION/AUDIT outcomes whose frozen "
                "split_boundary_status is AVAILABLE"
            ),
            "MATCHED90": (
                "common rows whose frozen split_boundary_status is AVAILABLE "
                "for all 5/30/60/90 horizons"
            ),
            "PURGED": (
                "otherwise valid outcomes excluded only because their exit "
                "crosses the originating frozen split boundary"
            ),
        },
        "benchmark_audit": benchmark_audit,
        "statistical_cautions": {
            "minimum_reveal_samples": args.min_reveal_samples,
            "multiple_comparison_family_size_per_horizon": family_size,
            "bonferroni_alpha": NOMINAL_ALPHA / family_size,
            "warning": (
                "The exhaustive reveal matrix is descriptive after lock; "
                "AUDIT must not be used to reselect the champions."
            ),
        },
        "statistics_layering": {
            "exhaustive_matrix": (
                "additive exact statistics for every model/trigger/filter cell"
            ),
            "locked_exact": (
                "exact median, P05/P25/P50/P75/P95, CVaR5, distinct stocks "
                "and dates, loss streak, PnL concentration, crowding, "
                "Event/Union/Macro/DateBalanced, year/quarter/regime groups"
            ),
            "aggregation_contract": EXACT_AGGREGATION_CONTRACT,
            "non_additive_full_matrix_policy": (
                "order statistics are not approximated for all exhaustive "
                "cells; exact values are materialized for locked selections"
            ),
            "audit_reselection_permitted": False,
        },
        "row_contract": {
            "matrix_rows": writer.rows,
            "locked_summary_rows": len(detailed),
            "locked_detailed_rows": len(exact_detailed),
            "locked_group_detail_rows": len(exact_groups),
            "trigger_selectors": len(TRIGGER_SELECTORS),
            "trigger_selector_semantics": TRIGGER_SELECTOR_SEMANTICS,
            "filter_subsets": FILTER_SUBSET_COUNT,
            "filter_subset_semantics": (
                "event qualifies when (filter_pass_mask & required_mask) "
                "equals required_mask"
            ),
            "scopes": list(REVEAL_SCOPES),
        },
        "outputs": {
            "matrix": _artifact(matrix_path),
            "summary": _artifact(summary_path),
            "locked_detailed": _artifact(detailed_path),
            "group_detail": _artifact(group_detail_path),
        },
    }
    write_json_atomic(manifest_path, manifest)
    result = {
        "stage": "reveal",
        "stage_id": stage_id,
        "lock_id": locked["lock_id"],
        "reused": False,
        "matrix_rows": writer.rows,
        "locked_summary_rows": len(detailed),
        "locked_detailed_rows": len(exact_detailed),
        "locked_group_detail_rows": len(exact_groups),
        "manifest_path": str(manifest_path),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def run_status(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    matrix_dir = root / "matrix"
    result = {
        "study_id": STUDY_ID,
        "root": str(root),
        "development_complete": (matrix_dir / "development_manifest.json").is_file(),
        "lock_complete": (matrix_dir / "locked_config.json").is_file(),
        "reveal_complete": (matrix_dir / "reveal_manifest.json").is_file(),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    development = subparsers.add_parser("development")
    development.add_argument(
        "--min-train-samples",
        type=_positive_int,
        default=DEFAULT_MIN_TRAIN_SAMPLES,
    )
    development.add_argument(
        "--min-validation-samples",
        type=_positive_int,
        default=DEFAULT_MIN_VALIDATION_SAMPLES,
    )
    development.add_argument(
        "--top-per-model",
        type=_positive_int,
        default=DEFAULT_TOP_PER_MODEL,
    )
    development.add_argument("--progress-every", type=int, default=1)
    development.add_argument("--force", action="store_true")
    development.set_defaults(handler=run_development)

    lock = subparsers.add_parser("lock")
    lock.add_argument("--force", action="store_true")
    lock.set_defaults(handler=run_lock)

    reveal = subparsers.add_parser("reveal")
    reveal.add_argument(
        "--min-reveal-samples",
        type=_positive_int,
        default=DEFAULT_MIN_REVEAL_SAMPLES,
    )
    reveal.add_argument("--progress-every", type=int, default=1)
    reveal.add_argument("--force", action="store_true")
    reveal.set_defaults(handler=run_reveal)

    status = subparsers.add_parser("status")
    status.set_defaults(handler=run_status)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
