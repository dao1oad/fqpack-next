"""Causal CLX event outcomes and deterministic segmented event statistics.

The event clock is ``reveal_date``.  An actionable ADD/REPLACE is entered at
the next snapshot-calendar session's raw open; REMOVE is revision history, not
a new entry.  Raw prices remain the locked return domain, while adjustment
factor jumps are disclosed rather than normalized away.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import stat
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, TypeGuard

import numpy as np
import polars as pl

from ._file_lock import (
    fsync_directory,
    lock_exclusive,
    seal_tree_durable,
    tree_is_sealed,
    unlock,
)
from .model_registry import canonical_json_bytes
from .signal_dedup import (
    ACTIONABLE_EVENT_KINDS,
    DEDUP_RULE,
    deduplicate_actionable_rows,
)
from .snapshot import QUALITY_EXCLUDED_MATCHING

EVENT_STUDY_SCHEMA_VERSION = "clx-event-study-v2"
EVENT_PREVERIFICATION_SCHEMA_VERSION = "clx-event-preverification-v1"
EVENT_PREVERIFICATION_MARKER_SCHEMA_VERSION = "clx-event-preverification-marker-v1"
EVENT_PREVERIFICATION_REFERENCE_SCHEMA_VERSION = (
    "clx-event-preverification-reference-v1"
)
DIRECTION_ADJUSTED_RETURN_CONTRACT = "direction * (raw_exit_close / raw_entry_open - 1)"
DIRECTION_ADJUSTED_EXCURSION_CONTRACT = (
    "positive: max(high_return), min(low_return); "
    "negative: -min(low_return), -max(high_return)"
)
HORIZONS = (1, 3, 5, 10, 20)
SPLIT_NAMES = ("TRAIN", "VALIDATION", "HOLDOUT")
CORPORATE_ACTION_NOT_FULLY_LEDGERED = 1 << 24
EVENT_ENTRY_CENSORED = 1 << 25
EVENT_OUTCOME_CENSORED = 1 << 26
EVENT_DEDUPLICATED = 1 << 27

ENTRY_EXECUTABLE = "EXECUTABLE"
ENTRY_NO_NEXT_SESSION = "CENSORED_NO_NEXT_MARKET_SESSION"
ENTRY_MISSING_BAR = "CENSORED_MISSING_ENTRY_BAR"
ENTRY_QUALITY_EXCLUDED = "CENSORED_QUALITY_EXCLUDED_ENTRY_BAR"
ENTRY_NON_TRADING = "CENSORED_NON_TRADING_ENTRY_BAR"
ENTRY_INVALID_PRICE = "CENSORED_INVALID_ENTRY_PRICE"

OUTCOME_OK = "OK"
OUTCOME_NO_EXIT_SESSION = "CENSORED_NO_EXIT_SESSION"
OUTCOME_MISSING_EXIT_BAR = "CENSORED_MISSING_EXIT_BAR"
OUTCOME_MISSING_PATH_BAR = "CENSORED_MISSING_PATH_BAR"
OUTCOME_QUALITY_EXCLUDED = "CENSORED_QUALITY_EXCLUDED_PATH_BAR"
OUTCOME_NON_TRADING = "CENSORED_NON_TRADING_PATH_BAR"
OUTCOME_INVALID_PRICE = "CENSORED_INVALID_PATH_PRICE"
OUTCOME_ENTRY_NOT_EXECUTABLE = "CENSORED_ENTRY_NOT_EXECUTABLE"

SPLIT_ELIGIBLE = "ELIGIBLE"
SPLIT_PURGED = "PURGED_20_SESSION_BOUNDARY"
SPLIT_EMBARGOED = "EMBARGOED_20_SESSION_BOUNDARY"
SPLIT_PURGED_AND_EMBARGOED = "PURGED_AND_EMBARGOED_20_SESSION_BOUNDARY"
SPLIT_OUTSIDE = "OUTSIDE_SPLIT_PLAN"

_PARQUET_OPTIONS = {
    "compression": "zstd",
    "compression_level": 9,
    "statistics": True,
    "row_group_size": 65536,
}


class EventStudyError(RuntimeError):
    """Raised when event inputs or artifacts violate the frozen contract."""


class HoldoutAccessError(EventStudyError):
    """Raised when HOLDOUT is requested before its one-time reveal."""


@dataclass(frozen=True, slots=True)
class SplitWindow:
    split_id: str
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if self.split_id not in SPLIT_NAMES:
            raise ValueError(f"unsupported split_id: {self.split_id}")
        if self.start_date > self.end_date:
            raise ValueError("split start_date must not exceed end_date")


@dataclass(frozen=True, slots=True)
class SplitPlan:
    """Ordered reveal-date windows with a fixed 20-session boundary guard."""

    windows: tuple[SplitWindow, ...]
    purge_sessions: int = 20
    embargo_sessions: int = 20

    def __post_init__(self) -> None:
        if tuple(window.split_id for window in self.windows) != SPLIT_NAMES:
            raise ValueError("split plan must contain TRAIN, VALIDATION, HOLDOUT")
        for previous, current in zip(self.windows, self.windows[1:]):
            if previous.end_date >= current.start_date:
                raise ValueError("split windows must be mutually exclusive and ordered")
        if self.purge_sessions != 20 or self.embargo_sessions != 20:
            raise ValueError("V1 split boundary guard is frozen at 20 sessions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "windows": [
                {
                    "split_id": item.split_id,
                    "start_date": item.start_date.isoformat(),
                    "end_date": item.end_date.isoformat(),
                }
                for item in self.windows
            ],
            "purge_sessions": self.purge_sessions,
            "embargo_sessions": self.embargo_sessions,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SplitPlan":
        return cls(
            windows=tuple(
                SplitWindow(
                    split_id=str(item["split_id"]),
                    start_date=date.fromisoformat(str(item["start_date"])),
                    end_date=date.fromisoformat(str(item["end_date"])),
                )
                for item in value["windows"]
            ),
            purge_sessions=int(value.get("purge_sessions", 20)),
            embargo_sessions=int(value.get("embargo_sessions", 20)),
        )


@dataclass(frozen=True, slots=True)
class HoldoutAccess:
    """Minimal immutable freeze/reveal proof consumed by metrics queries."""

    freeze_id: str | None = None
    holdout_revealed: bool = False
    reveal_count: int = 0

    def authorize(self, requested_splits: Iterable[str]) -> None:
        requested = tuple(requested_splits)
        unknown = sorted(set(requested) - set(SPLIT_NAMES))
        if unknown:
            raise ValueError(f"unknown split ids: {unknown}")
        if "HOLDOUT" not in requested:
            return
        if not self.freeze_id or not self.holdout_revealed or self.reveal_count != 1:
            raise HoldoutAccessError(
                "HOLDOUT_LOCKED: a freeze_id and exactly one recorded reveal are required"
            )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    _atomic_write_bytes(
        path,
        (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        ),
    )


def _fsync_directory(path: Path) -> None:
    fsync_directory(path)


def _atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _sha256_reference(value: object) -> str:
    digest = str(value).removeprefix("sha256:")
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise EventStudyError("SHA-256 reference is malformed")
    return "sha256:" + digest


def _canonical_nonsymlink_path(
    value: str | Path, *, kind: str, must_exist: bool = False
) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = Path(os.path.abspath(candidate))
    current = Path(candidate.anchor)
    for component in candidate.parts[1:]:
        current /= component
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise EventStudyError(f"{kind} contains a symlink component: {current}")
    if must_exist and not candidate.exists():
        raise EventStudyError(f"{kind} is missing: {candidate}")
    return candidate


def _preverification_sidecar(path: Path) -> Path:
    if path.suffix == ".json":
        return path.with_suffix(".sha256")
    return path.with_name(path.name + ".sha256")


def _publish_readonly(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path = _canonical_nonsymlink_path(path, kind="preverification publication")
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
            fchmod = getattr(os, "fchmod", None)
            if fchmod is not None:
                fchmod(stream.fileno(), 0o444)
                os.fsync(stream.fileno())
        posix_publication = getattr(os, "fchmod", None) is not None
        try:
            os.link(temporary, path)
            if not posix_publication:
                temporary.unlink()
                path.chmod(0o444)
        except FileExistsError:
            metadata = os.lstat(path)
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_mode & 0o222
                or path.read_bytes() != value
            ):
                raise EventStudyError(
                    f"preverification publication differs from existing file: {path}"
                )
        _fsync_directory(path.parent)
    finally:
        if temporary.exists() and os.name == "nt":
            temporary.chmod(0o644)
        temporary.unlink(missing_ok=True)
        _fsync_directory(path.parent)


def _publish_readonly_with_sidecar(path: Path, value: bytes) -> str:
    digest = _sha256_bytes(value)
    _publish_readonly(path, value)
    _publish_readonly(
        _preverification_sidecar(path),
        f"{digest}  {path.name}\n".encode("ascii"),
    )
    return "sha256:" + digest


def _temporary_event_entry(name: str) -> bool:
    return any(token in name for token in (".tmp-", ".staging-", ".bootstrap-"))


def _event_tree_lstat_entries(root: Path) -> list[dict[str, object]]:
    root = _canonical_nonsymlink_path(root, kind="event artifact root", must_exist=True)
    if root.is_symlink() or not root.is_dir():
        raise EventStudyError(f"event artifact root is not a regular directory: {root}")
    entries: list[dict[str, object]] = []

    def append_entry(path: Path, relative: str, metadata: os.stat_result) -> None:
        mode = metadata.st_mode
        if stat.S_ISLNK(mode):
            raise EventStudyError(f"event artifact tree contains a symlink: {path}")
        if stat.S_ISDIR(mode):
            kind = "directory"
        elif stat.S_ISREG(mode):
            kind = "file"
        else:
            raise EventStudyError(
                f"event artifact tree contains a special file: {path}"
            )
        entries.append(
            {
                "path": relative,
                "type": kind,
                "mode": stat.S_IMODE(mode),
                "size": metadata.st_size,
                "mtime_ns": metadata.st_mtime_ns,
                "ctime_ns": metadata.st_ctime_ns,
                "device": metadata.st_dev,
                "inode": metadata.st_ino,
            }
        )

    def visit(directory: Path, relative: str) -> None:
        append_entry(directory, relative, os.lstat(directory))
        with os.scandir(directory) as stream:
            children = sorted(stream, key=lambda item: item.name)
        for child in children:
            if _temporary_event_entry(child.name):
                raise EventStudyError(
                    f"event artifact tree contains a temporary entry: {child.path}"
                )
            path = Path(child.path)
            child_relative = (
                child.name if relative == "." else f"{relative}/{child.name}"
            )
            metadata = child.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                visit(path, child_relative)
            else:
                append_entry(path, child_relative, metadata)

    visit(root, ".")
    return entries


def _assert_registered_event_parquet(
    entries: Sequence[Mapping[str, object]], manifest: Mapping[str, object]
) -> None:
    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise EventStudyError("event manifest artifact registry is invalid")
    registered = {
        str(item["path"])
        for item in raw_artifacts
        if isinstance(item, Mapping) and str(item.get("path", "")).endswith(".parquet")
    }
    actual = {
        str(item["path"])
        for item in entries
        if item.get("type") == "file" and str(item.get("path", "")).endswith(".parquet")
    }
    if actual != registered:
        raise EventStudyError(
            "event artifact Parquet registry differs from the manifest: "
            f"missing={sorted(registered - actual)[:10]}, "
            f"extra={sorted(actual - registered)[:10]}"
        )


def _with_content_hash(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    result[field] = _sha256_bytes(canonical_json_bytes(value))
    return result


def _acquire_build_lock(path: Path, event_set_id: str) -> int:
    """Lock a stable inode so competing builders cannot publish one event set."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        lock_exclusive(descriptor, blocking=False)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise EventStudyError(f"event build is already locked: {path}") from exc
    payload = canonical_json_bytes({"event_set_id": event_set_id, "pid": os.getpid()})
    os.ftruncate(descriptor, 0)
    os.write(descriptor, payload + b"\n")
    os.fsync(descriptor)
    return descriptor


def _release_build_lock(descriptor: int) -> None:
    try:
        unlock(descriptor)
    finally:
        os.close(descriptor)


def _schema_fingerprint(frame: pl.DataFrame) -> str:
    return _sha256_bytes(
        canonical_json_bytes(
            [(name, str(dtype)) for name, dtype in frame.schema.items()]
        )
    )


def _logical_frame_sha256(frame: pl.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(
        canonical_json_bytes(
            [(name, str(dtype)) for name, dtype in frame.schema.items()]
        )
    )
    for seeds in ((0, 1, 2, 3), (11, 13, 17, 19)):
        hashes = frame.hash_rows(
            seed=seeds[0], seed_1=seeds[1], seed_2=seeds[2], seed_3=seeds[3]
        )
        digest.update(hashes.to_numpy().astype("<u8", copy=False).tobytes())
    return digest.hexdigest()


def _read_hashed_manifest(root: Path, *, kind: str) -> tuple[dict[str, Any], str]:
    path = root / "manifest.json"
    if not path.is_file():
        raise EventStudyError(f"{kind} manifest is missing: {path}")
    raw = path.read_bytes()
    manifest = json.loads(raw)
    sidecar = root / "manifest.sha256"
    if sidecar.is_file():
        digest_line = sidecar.read_text(encoding="ascii").strip()
        parts = digest_line.split()
        if len(parts) == 1:
            recorded = parts[0]
        elif len(parts) == 2 and parts[1] == "manifest.json":
            # Snapshots use sha256sum-compatible output, while signal manifests
            # historically stored the bare digest.
            recorded = parts[0]
        else:
            raise EventStudyError(f"{kind} manifest.sha256 format is invalid")
        if recorded != _sha256_bytes(raw):
            raise EventStudyError(f"{kind} manifest.sha256 sidecar mismatch")
        embedded = manifest.pop("manifest_sha256", None)
        if embedded is not None:
            raise EventStudyError(f"{kind} manifest mixes sidecar and embedded hashes")
        return manifest, recorded
    recorded = manifest.pop("manifest_sha256", None)
    actual = _sha256_bytes(canonical_json_bytes(manifest))
    normalized = str(recorded).removeprefix("sha256:") if recorded else None
    if normalized != actual:
        raise EventStudyError(f"{kind} legacy embedded manifest hash mismatch")
    manifest["manifest_sha256"] = recorded
    return manifest, str(recorded)


def _artifact_hash(meta: Mapping[str, Any]) -> str:
    value = meta.get("file_sha256", meta.get("sha256"))
    if not isinstance(value, str):
        raise EventStudyError("artifact metadata has no file SHA-256")
    return value.removeprefix("sha256:")


def _verify_artifact(root: Path, meta: Mapping[str, Any]) -> Path:
    path = root / str(meta["path"])
    if not path.is_file():
        raise EventStudyError(f"artifact is missing: {path}")
    if _sha256_file(path) != _artifact_hash(meta):
        raise EventStudyError(f"artifact file SHA-256 mismatch: {path}")
    return path


def _calendar_dates(calendar: pl.DataFrame) -> tuple[date, ...]:
    required = {"trade_date", "session_no"}
    if not required.issubset(calendar.columns):
        raise EventStudyError(
            f"calendar misses columns: {sorted(required-set(calendar.columns))}"
        )
    ordered = calendar.sort("session_no")
    if ordered["session_no"].to_list() != list(range(1, ordered.height + 1)):
        raise EventStudyError("calendar session_no must be one-based contiguous")
    dates = tuple(ordered["trade_date"].to_list())
    if len(set(dates)) != len(dates) or tuple(sorted(dates)) != dates:
        raise EventStudyError("calendar trade_date must be unique and ascending")
    return dates


@dataclass(frozen=True, slots=True)
class _BoundSplit:
    split_id: str
    start_index: int
    end_index: int


def _bind_split_plan(
    calendar_dates: Sequence[date], split_plan: SplitPlan
) -> tuple[_BoundSplit, ...]:
    result: list[_BoundSplit] = []
    for window in split_plan.windows:
        indices = [
            index
            for index, day in enumerate(calendar_dates)
            if window.start_date <= day <= window.end_date
        ]
        if not indices:
            raise EventStudyError(f"split {window.split_id} has no snapshot session")
        result.append(_BoundSplit(window.split_id, indices[0], indices[-1]))
    for previous, current in zip(result, result[1:]):
        if previous.end_index >= current.start_index:
            raise EventStudyError("bound split sessions overlap")
    return tuple(result)


def _split_for_event(
    reveal_index: int, bound: Sequence[_BoundSplit], split_plan: SplitPlan
) -> tuple[str, str]:
    for position, window in enumerate(bound):
        if not window.start_index <= reveal_index <= window.end_index:
            continue
        purged = (
            position < len(bound) - 1
            and reveal_index
            >= bound[position + 1].start_index - split_plan.purge_sessions
        )
        embargoed = (
            position > 0
            and reveal_index < window.start_index + split_plan.embargo_sessions
        )
        if purged and embargoed:
            status = SPLIT_PURGED_AND_EMBARGOED
        elif purged:
            status = SPLIT_PURGED
        elif embargoed:
            status = SPLIT_EMBARGOED
        else:
            status = SPLIT_ELIGIBLE
        return window.split_id, status
    return "OUTSIDE", SPLIT_OUTSIDE


_REQUIRED_SIGNAL_COLUMNS = {
    "signal_fact_id",
    "code",
    "expected_model_id",
    "model_code",
    "signal_date",
    "reveal_date",
    "revision_no",
    "event_kind",
    "direction",
    "occurrence",
    "primary_entrypoint",
    "primary_trigger_semantic",
    "direction_base_trigger_mask",
    "synthetic_primary_mask",
    "concurrent_trigger_mask",
    "actionable",
    "quality_mask",
    "code_bucket",
}

_REQUIRED_BAR_COLUMNS = {
    "code",
    "trade_date",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "raw_volume",
    "adj_factor",
    "quality_mask",
}


def _deduplicate_actionable(
    signals: pl.DataFrame,
) -> tuple[list[dict[str, Any]], int, int]:
    missing = _REQUIRED_SIGNAL_COLUMNS - set(signals.columns)
    if missing:
        raise EventStudyError(f"signal facts miss columns: {sorted(missing)}")
    rows = list(signals.iter_rows(named=True))
    remove_count = signals.filter(pl.col("event_kind") == "REMOVE").height
    winners, duplicate_count = deduplicate_actionable_rows(rows)
    return winners, duplicate_count, remove_count


def _finite_positive(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and value > 0


def _entry_status(bar: Mapping[str, Any] | None) -> str:
    if bar is None:
        return ENTRY_MISSING_BAR
    if int(bar["quality_mask"] or 0) & QUALITY_EXCLUDED_MATCHING:
        return ENTRY_QUALITY_EXCLUDED
    if not _finite_positive(bar["raw_volume"]):
        return ENTRY_NON_TRADING
    if not _finite_positive(bar["raw_open"]):
        return ENTRY_INVALID_PRICE
    return ENTRY_EXECUTABLE


def _path_status(
    path: Sequence[Mapping[str, Any] | None], *, exit_bar_missing: bool
) -> str:
    if exit_bar_missing:
        return OUTCOME_MISSING_EXIT_BAR
    if any(bar is None for bar in path):
        return OUTCOME_MISSING_PATH_BAR
    concrete = [bar for bar in path if bar is not None]
    if any(
        int(bar["quality_mask"] or 0) & QUALITY_EXCLUDED_MATCHING for bar in concrete
    ):
        return OUTCOME_QUALITY_EXCLUDED
    if any(not _finite_positive(bar["raw_volume"]) for bar in concrete):
        return OUTCOME_NON_TRADING
    for bar in concrete:
        if not all(
            _finite_positive(bar[column])
            for column in ("raw_high", "raw_low", "raw_close")
        ):
            return OUTCOME_INVALID_PRICE
    return OUTCOME_OK


def _adj_factor_jumps(path: Sequence[Mapping[str, Any]]) -> int:
    factors = [bar.get("adj_factor") for bar in path]
    numeric_factors: list[float] = []
    for value in factors:
        if not _finite_positive(value):
            return 0
        numeric_factors.append(float(value))
    return sum(
        not math.isclose(previous, current, rel_tol=1e-12, abs_tol=1e-15)
        for previous, current in zip(numeric_factors, numeric_factors[1:])
    )


def build_event_outcomes_frame(
    signals: pl.DataFrame,
    bars: pl.DataFrame,
    calendar: pl.DataFrame,
    split_plan: SplitPlan,
    *,
    run_id: str = "fixture-event-run",
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Materialize one deterministic wide outcome row per deduplicated entry."""

    bar_missing = _REQUIRED_BAR_COLUMNS - set(bars.columns)
    if bar_missing:
        raise EventStudyError(f"snapshot bars miss columns: {sorted(bar_missing)}")
    if bars.select(pl.struct(["code", "trade_date"]).n_unique()).item() != bars.height:
        raise EventStudyError("snapshot bars contain duplicate (code,trade_date)")
    calendar_days = _calendar_dates(calendar)
    calendar_index = {day: index for index, day in enumerate(calendar_days)}
    bound_splits = _bind_split_plan(calendar_days, split_plan)
    bar_map = {
        (row["code"], row["trade_date"]): row for row in bars.iter_rows(named=True)
    }
    winners, duplicate_count, remove_count = _deduplicate_actionable(signals)
    output: list[dict[str, Any]] = []

    for fact in winners:
        reveal_date = fact["reveal_date"]
        if fact["signal_date"] > reveal_date:
            raise EventStudyError("signal_date exceeds reveal_date")
        reveal_index = calendar_index.get(reveal_date)
        if reveal_index is None:
            raise EventStudyError("signal reveal_date is absent from snapshot calendar")
        split_id, split_status = _split_for_event(
            reveal_index, bound_splits, split_plan
        )
        entry_index = reveal_index + 1
        entry_trade_date = (
            calendar_days[entry_index] if entry_index < len(calendar_days) else None
        )
        entry_bar = (
            bar_map.get((fact["code"], entry_trade_date))
            if entry_trade_date is not None
            else None
        )
        entry_status = (
            _entry_status(entry_bar)
            if entry_trade_date is not None
            else ENTRY_NO_NEXT_SESSION
        )
        if entry_status == ENTRY_EXECUTABLE:
            assert entry_bar is not None
            entry_open_value = entry_bar["raw_open"]
            assert _finite_positive(entry_open_value)
            raw_entry_open = float(entry_open_value)
        else:
            raw_entry_open = None
        quality_mask = int(fact["quality_mask"] or 0)
        if entry_status != ENTRY_EXECUTABLE:
            quality_mask |= EVENT_ENTRY_CENSORED
        if int(fact["dedup_group_size"]) > 1:
            quality_mask |= EVENT_DEDUPLICATED

        row: dict[str, Any] = {
            "run_id": run_id,
            "signal_fact_id": str(fact["signal_fact_id"]),
            "code": str(fact["code"]),
            "expected_model_id": int(fact["expected_model_id"]),
            "model_code": str(fact["model_code"]),
            "signal_date": fact["signal_date"],
            "reveal_date": reveal_date,
            "revision_no": int(fact["revision_no"]),
            "event_kind": str(fact["event_kind"]),
            "direction": int(fact["direction"]),
            "occurrence": int(fact["occurrence"]),
            "primary_entrypoint": int(fact["primary_entrypoint"]),
            "primary_trigger_semantic": str(fact["primary_trigger_semantic"]),
            "direction_base_trigger_mask": int(fact["direction_base_trigger_mask"]),
            "synthetic_primary_mask": int(fact["synthetic_primary_mask"]),
            "concurrent_trigger_mask": int(fact["concurrent_trigger_mask"]),
            "dedup_group_size": int(fact["dedup_group_size"]),
            "entry_trade_date": entry_trade_date,
            "entry_status": entry_status,
            "raw_entry_open": raw_entry_open,
            "split_id": split_id,
            "split_boundary_status": split_status,
            "quality_mask": quality_mask,
            "corporate_action_any": False,
            "reveal_year": reveal_date.year,
            "code_bucket": int(fact["code_bucket"]),
        }

        for horizon in HORIZONS:
            prefix = f"h{horizon}"
            exit_index = entry_index + horizon - 1
            exit_date = (
                calendar_days[exit_index]
                if entry_trade_date is not None and exit_index < len(calendar_days)
                else None
            )
            row[f"{prefix}_exit_date"] = exit_date
            row[f"{prefix}_raw_exit_close"] = None
            row[f"{prefix}_raw_return"] = None
            row[f"{prefix}_direction_adjusted_return"] = None
            row[f"{prefix}_mfe"] = None
            row[f"{prefix}_mae"] = None
            row[f"{prefix}_adj_factor_jump_count"] = 0
            row[f"{prefix}_corporate_action_status"] = "NONE_OBSERVED"

            if entry_status != ENTRY_EXECUTABLE:
                status = OUTCOME_ENTRY_NOT_EXECUTABLE
            elif exit_date is None:
                status = OUTCOME_NO_EXIT_SESSION
            else:
                path_dates = calendar_days[entry_index : exit_index + 1]
                path = [bar_map.get((fact["code"], day)) for day in path_dates]
                status = _path_status(path, exit_bar_missing=path[-1] is None)
                if status == OUTCOME_OK:
                    assert raw_entry_open is not None
                    concrete = [item for item in path if item is not None]
                    exit_close = float(concrete[-1]["raw_close"])
                    raw_return = exit_close / raw_entry_open - 1.0
                    jump_count = _adj_factor_jumps(concrete)
                    row[f"{prefix}_raw_exit_close"] = exit_close
                    row[f"{prefix}_raw_return"] = raw_return
                    row[f"{prefix}_direction_adjusted_return"] = (
                        int(fact["direction"]) * raw_return
                    )
                    high_return = (
                        max(float(item["raw_high"]) for item in concrete)
                        / raw_entry_open
                        - 1.0
                    )
                    low_return = (
                        min(float(item["raw_low"]) for item in concrete)
                        / raw_entry_open
                        - 1.0
                    )
                    if int(fact["direction"]) > 0:
                        mfe, mae = high_return, low_return
                    else:
                        # Match direction_adjusted_return = direction * raw_return:
                        # a falling low is favorable and a rising high is adverse.
                        mfe, mae = -low_return, -high_return
                    row[f"{prefix}_mfe"] = mfe
                    row[f"{prefix}_mae"] = mae
                    row[f"{prefix}_adj_factor_jump_count"] = jump_count
                    if jump_count:
                        row[f"{prefix}_corporate_action_status"] = (
                            "CORPORATE_ACTION_NOT_FULLY_LEDGERED"
                        )
                        row["corporate_action_any"] = True
                        row["quality_mask"] |= CORPORATE_ACTION_NOT_FULLY_LEDGERED
            row[f"{prefix}_status"] = status
            if status != OUTCOME_OK:
                row["quality_mask"] |= EVENT_OUTCOME_CENSORED
        output.append(row)

    frame = pl.DataFrame(output, infer_schema_length=None)
    if frame.height:
        frame = frame.sort(
            [
                "reveal_date",
                "code",
                "expected_model_id",
                "direction",
                "signal_fact_id",
            ]
        ).with_columns(pl.col("quality_mask").cast(pl.UInt32))
    summary = {
        "input_signal_revisions": signals.height,
        "remove_revisions_ignored": remove_count,
        "actionable_duplicates_removed": duplicate_count,
        "event_outcomes": frame.height,
        "entry_executable": (
            frame.filter(pl.col("entry_status") == ENTRY_EXECUTABLE).height
            if frame.height
            else 0
        ),
        "entry_censored": (
            frame.filter(pl.col("entry_status") != ENTRY_EXECUTABLE).height
            if frame.height
            else 0
        ),
        "corporate_action_events": (
            frame.filter(pl.col("corporate_action_any")).height if frame.height else 0
        ),
        "dedup_rule": DEDUP_RULE,
    }
    return frame, summary


def _segment_memberships(row: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    model = str(row["model_code"])
    direction = f"{int(row['direction']):+d}"
    occurrence = str(int(row["occurrence"]))
    primary = str(row["primary_trigger_semantic"])
    base_mask = int(row["direction_base_trigger_mask"])
    synthetic_mask = int(row["synthetic_primary_mask"])
    concurrent_mask = int(row["concurrent_trigger_mask"])
    memberships: list[tuple[str, str]] = [
        ("SINGLE_MODEL", str(row["model_code"])),
        ("OCCURRENCE", occurrence),
        ("PRIMARY_TRIGGER_SEMANTIC", primary),
        (
            "DIRECTION_BASE_TRIGGER_MASK",
            f"0x{base_mask:02x}",
        ),
        ("SYNTHETIC_PRIMARY_MASK", f"0x{synthetic_mask:02x}"),
        ("CONCURRENT_TRIGGER_MASK", f"0x{concurrent_mask:02x}"),
        ("MODEL_X_DIRECTION", f"{model}|direction={direction}"),
        (
            "MODEL_X_DIRECTION_X_PRIMARY_TRIGGER",
            f"{model}|direction={direction}|primary={primary}",
        ),
        ("MODEL_X_PRIMARY_TRIGGER_SEMANTIC", f"{model}|primary={primary}"),
        ("MODEL_X_OCCURRENCE", f"{model}|occurrence={occurrence}"),
        (
            "MODEL_X_OCCURRENCE_X_PRIMARY_TRIGGER",
            f"{model}|occurrence={occurrence}|primary={primary}",
        ),
        (
            "MODEL_X_CONCURRENT_TRIGGER_MASK",
            f"{model}|mask=0x{concurrent_mask:02x}",
        ),
    ]
    memberships.extend(
        ("MODEL_X_BASE_TRIGGER_ID", f"{model}|entrypoint={entrypoint}")
        for entrypoint in range(1, 9)
        if base_mask & (1 << (entrypoint - 1))
    )
    if synthetic_mask:
        memberships.append(
            (
                "MODEL_X_SYNTHETIC_PRIMARY_SEMANTIC",
                f"{model}|primary={primary}",
            )
        )
        memberships.extend(
            (
                "MODEL_X_SYNTHETIC_TRIGGER_ID",
                f"{model}|entrypoint={entrypoint}",
            )
            for entrypoint in range(1, 9)
            if synthetic_mask & (1 << (entrypoint - 1))
        )
    return tuple(memberships)


def _bootstrap_mean(
    values_by_date: Mapping[date, Sequence[float]],
    *,
    replicates: int,
    seed_material: str,
) -> tuple[float | None, float | None, float | None]:
    dates = sorted(values_by_date)
    if not dates:
        return None, None, None
    observed = np.asarray(
        [value for day in dates for value in values_by_date[day]], dtype=np.float64
    )
    if len(dates) < 2 or replicates <= 0:
        mean = float(observed.mean())
        return mean, mean, 1.0
    seed = int.from_bytes(
        hashlib.sha256(seed_material.encode("utf-8")).digest()[:8], "little"
    )
    rng = np.random.default_rng(seed)
    means = np.empty(replicates, dtype=np.float64)
    blocks = [np.asarray(values_by_date[day], dtype=np.float64) for day in dates]
    for index in range(replicates):
        sampled = rng.integers(0, len(blocks), size=len(blocks))
        means[index] = np.concatenate([blocks[position] for position in sampled]).mean()
    ci_low, ci_high = np.quantile(means, [0.025, 0.975], method="linear")
    non_positive = (np.count_nonzero(means <= 0.0) + 1) / (replicates + 1)
    non_negative = (np.count_nonzero(means >= 0.0) + 1) / (replicates + 1)
    p_value = min(1.0, 2.0 * min(non_positive, non_negative))
    return float(ci_low), float(ci_high), float(p_value)


def _eligible_session_counts(
    calendar_dates: Sequence[date], split_plan: SplitPlan
) -> dict[str, int]:
    bound = _bind_split_plan(calendar_dates, split_plan)
    counts = {name: 0 for name in SPLIT_NAMES}
    for index in range(len(calendar_dates)):
        split_id, status = _split_for_event(index, bound, split_plan)
        if status == SPLIT_ELIGIBLE:
            counts[split_id] += 1
    return counts


def _apply_bh_fdr(rows: list[dict[str, Any]]) -> None:
    families: dict[tuple[str, int, str], list[int]] = {}
    for index, row in enumerate(rows):
        if row["p_value"] is not None:
            families.setdefault(
                (row["split_id"], row["horizon"], row["segment_type"]), []
            ).append(index)
    for indices in families.values():
        ordered = sorted(
            indices,
            key=lambda index: (
                rows[index]["p_value"],
                rows[index]["segment_type"],
                rows[index]["segment_value"],
            ),
        )
        running = 1.0
        for reverse_rank in range(len(ordered), 0, -1):
            index = ordered[reverse_rank - 1]
            adjusted = rows[index]["p_value"] * len(ordered) / reverse_rank
            running = min(running, adjusted)
            rows[index]["fdr_q_value"] = min(1.0, running)


def build_event_metrics_frame(
    outcomes: pl.DataFrame,
    calendar: pl.DataFrame,
    split_plan: SplitPlan,
    *,
    requested_splits: Sequence[str] = ("TRAIN", "VALIDATION"),
    access: HoldoutAccess | None = None,
    bootstrap_replicates: int = 1000,
    combo_id: str = "SINGLE_SIGNAL_DIMENSIONS_V1",
) -> pl.DataFrame:
    """Aggregate deterministic long metrics using reveal-date block bootstrap."""

    effective_access = access if access is not None else HoldoutAccess()
    effective_access.authorize(requested_splits)
    if bootstrap_replicates < 0:
        raise ValueError("bootstrap_replicates must be non-negative")
    requested = tuple(dict.fromkeys(requested_splits))
    calendar_days = _calendar_dates(calendar)
    density_denominators = _eligible_session_counts(calendar_days, split_plan)
    grouped: dict[tuple[str, str, str, int], list[Mapping[str, Any]]] = {}
    for row in outcomes.iter_rows(named=True):
        split_id = row["split_id"]
        if split_id not in requested:
            continue
        for segment_type, segment_value in _segment_memberships(row):
            for horizon in HORIZONS:
                grouped.setdefault(
                    (split_id, segment_type, segment_value, horizon), []
                ).append(row)

    metrics: list[dict[str, Any]] = []
    run_id = outcomes["run_id"][0] if outcomes.height else "EMPTY"
    for key in sorted(grouped):
        split_id, segment_type, segment_value, horizon = key
        rows = grouped[key]
        prefix = f"h{horizon}"
        eligible = [
            row for row in rows if row["split_boundary_status"] == SPLIT_ELIGIBLE
        ]
        executable = [row for row in eligible if row[f"{prefix}_status"] == OUTCOME_OK]
        values = np.asarray(
            [row[f"{prefix}_direction_adjusted_return"] for row in executable],
            dtype=np.float64,
        )
        values_by_date: dict[date, list[float]] = {}
        for row in executable:
            values_by_date.setdefault(row["reveal_date"], []).append(
                float(row[f"{prefix}_direction_adjusted_return"])
            )
        ci_low, ci_high, p_value = _bootstrap_mean(
            values_by_date,
            replicates=bootstrap_replicates,
            seed_material="|".join(map(str, (run_id, *key, bootstrap_replicates))),
        )
        yearly: dict[int, list[float]] = {}
        for row in executable:
            yearly.setdefault(row["reveal_date"].year, []).append(
                float(row[f"{prefix}_direction_adjusted_return"])
            )
        yearly_means = {
            year: float(np.mean(year_values)) for year, year_values in yearly.items()
        }
        worst_year = (
            min(yearly_means, key=lambda year: (yearly_means[year], year))
            if yearly_means
            else None
        )
        quantiles = (
            np.quantile(values, [0.05, 0.25, 0.75, 0.95], method="linear")
            if values.size
            else [None] * 4
        )
        metrics.append(
            {
                "run_id": run_id,
                "combo_id": combo_id,
                "split_id": split_id,
                "segment_type": segment_type,
                "segment_value": segment_value,
                "horizon": horizon,
                "n_total": len(rows),
                "n_executable": len(executable),
                "n_censored": len(eligible) - len(executable),
                "n_purged_or_embargoed": len(rows) - len(eligible),
                "mean": float(values.mean()) if values.size else None,
                "median": float(np.median(values)) if values.size else None,
                "std": (float(values.std(ddof=1)) if values.size >= 2 else None),
                "win_rate": (
                    float(np.count_nonzero(values > 0.0) / values.size)
                    if values.size
                    else None
                ),
                "p05": float(quantiles[0]) if values.size else None,
                "p25": float(quantiles[1]) if values.size else None,
                "p75": float(quantiles[2]) if values.size else None,
                "p95": float(quantiles[3]) if values.size else None,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "mfe_mean": (
                    float(np.mean([row[f"{prefix}_mfe"] for row in executable]))
                    if executable
                    else None
                ),
                "mae_mean": (
                    float(np.mean([row[f"{prefix}_mae"] for row in executable]))
                    if executable
                    else None
                ),
                "signal_density": (
                    len(eligible) / density_denominators[split_id]
                    if density_denominators[split_id]
                    else None
                ),
                "year_positive_ratio": (
                    sum(value > 0.0 for value in yearly_means.values())
                    / len(yearly_means)
                    if yearly_means
                    else None
                ),
                "worst_year": worst_year,
                "worst_year_mean": (
                    yearly_means[worst_year] if worst_year is not None else None
                ),
                "p_value": p_value,
                "fdr_q_value": None,
                "bootstrap_block": "reveal_date",
                "bootstrap_replicates": bootstrap_replicates,
            }
        )
    _apply_bh_fdr(metrics)
    return (
        pl.DataFrame(metrics, infer_schema_length=None).sort(
            ["split_id", "segment_type", "segment_value", "horizon"]
        )
        if metrics
        else pl.DataFrame()
    )


_SEGMENT_TYPES = (
    "SINGLE_MODEL",
    "OCCURRENCE",
    "PRIMARY_TRIGGER_SEMANTIC",
    "DIRECTION_BASE_TRIGGER_MASK",
    "SYNTHETIC_PRIMARY_MASK",
    "CONCURRENT_TRIGGER_MASK",
    "MODEL_X_DIRECTION",
    "MODEL_X_DIRECTION_X_PRIMARY_TRIGGER",
    "MODEL_X_PRIMARY_TRIGGER_SEMANTIC",
    "MODEL_X_OCCURRENCE",
    "MODEL_X_OCCURRENCE_X_PRIMARY_TRIGGER",
    "MODEL_X_CONCURRENT_TRIGGER_MASK",
    "MODEL_X_BASE_TRIGGER_ID",
    "MODEL_X_SYNTHETIC_PRIMARY_SEMANTIC",
    "MODEL_X_SYNTHETIC_TRIGGER_ID",
)

_METRIC_COLUMNS = (
    "run_id",
    "combo_id",
    "split_id",
    "segment_type",
    "segment_value",
    "horizon",
    "n_total",
    "n_executable",
    "n_censored",
    "n_purged_or_embargoed",
    "mean",
    "median",
    "std",
    "win_rate",
    "p05",
    "p25",
    "p75",
    "p95",
    "ci_low",
    "ci_high",
    "mfe_mean",
    "mae_mean",
    "signal_density",
    "year_positive_ratio",
    "worst_year",
    "worst_year_mean",
    "p_value",
    "fdr_q_value",
    "bootstrap_block",
    "bootstrap_replicates",
)


def _hex_mask(column: str) -> pl.Expr:
    return pl.col(column).map_elements(
        lambda value: f"0x{int(value):02x}", return_dtype=pl.String
    )


def _signed_direction() -> pl.Expr:
    return pl.col("direction").map_elements(
        lambda value: f"{int(value):+d}", return_dtype=pl.String
    )


def _trigger_membership_values(mask_column: str) -> pl.Expr:
    values = []
    for entrypoint in range(1, 9):
        bit = 1 << (entrypoint - 1)
        values.append(
            pl.when(
                (pl.col(mask_column).cast(pl.UInt64) & pl.lit(bit, dtype=pl.UInt64))
                != 0
            )
            .then(
                pl.concat_str(
                    [
                        pl.col("model_code"),
                        pl.lit(f"|entrypoint={entrypoint}"),
                    ]
                )
            )
            .otherwise(pl.lit(None, dtype=pl.String))
        )
    return pl.concat_list(values).list.drop_nulls()


def _segment_lazy_frame(source: pl.LazyFrame, segment_type: str) -> pl.LazyFrame:
    model = pl.col("model_code")
    occurrence = pl.col("occurrence").cast(pl.String)
    primary = pl.col("primary_trigger_semantic")
    if segment_type == "SINGLE_MODEL":
        expression = model
    elif segment_type == "OCCURRENCE":
        expression = occurrence
    elif segment_type == "PRIMARY_TRIGGER_SEMANTIC":
        expression = primary
    elif segment_type == "DIRECTION_BASE_TRIGGER_MASK":
        expression = _hex_mask("direction_base_trigger_mask")
    elif segment_type == "SYNTHETIC_PRIMARY_MASK":
        expression = _hex_mask("synthetic_primary_mask")
    elif segment_type == "CONCURRENT_TRIGGER_MASK":
        expression = _hex_mask("concurrent_trigger_mask")
    elif segment_type == "MODEL_X_DIRECTION":
        expression = pl.concat_str([model, pl.lit("|direction="), _signed_direction()])
    elif segment_type == "MODEL_X_DIRECTION_X_PRIMARY_TRIGGER":
        expression = pl.concat_str(
            [
                model,
                pl.lit("|direction="),
                _signed_direction(),
                pl.lit("|primary="),
                primary,
            ]
        )
    elif segment_type == "MODEL_X_PRIMARY_TRIGGER_SEMANTIC":
        expression = pl.concat_str([model, pl.lit("|primary="), primary])
    elif segment_type == "MODEL_X_OCCURRENCE":
        expression = pl.concat_str([model, pl.lit("|occurrence="), occurrence])
    elif segment_type == "MODEL_X_OCCURRENCE_X_PRIMARY_TRIGGER":
        expression = pl.concat_str(
            [
                model,
                pl.lit("|occurrence="),
                occurrence,
                pl.lit("|primary="),
                primary,
            ]
        )
    elif segment_type == "MODEL_X_CONCURRENT_TRIGGER_MASK":
        expression = pl.concat_str(
            [model, pl.lit("|mask="), _hex_mask("concurrent_trigger_mask")]
        )
    elif segment_type == "MODEL_X_BASE_TRIGGER_ID":
        return (
            source.with_columns(
                _trigger_membership_values("direction_base_trigger_mask").alias(
                    "segment_value"
                )
            )
            .explode("segment_value", empty_as_null=True)
            .filter(pl.col("segment_value").is_not_null())
        )
    elif segment_type == "MODEL_X_SYNTHETIC_PRIMARY_SEMANTIC":
        return source.filter(pl.col("synthetic_primary_mask") != 0).with_columns(
            pl.concat_str([model, pl.lit("|primary="), primary]).alias("segment_value")
        )
    elif segment_type == "MODEL_X_SYNTHETIC_TRIGGER_ID":
        return (
            source.with_columns(
                _trigger_membership_values("synthetic_primary_mask").alias(
                    "segment_value"
                )
            )
            .explode("segment_value", empty_as_null=True)
            .filter(pl.col("segment_value").is_not_null())
        )
    else:  # pragma: no cover - guarded by the frozen tuple above
        raise ValueError(f"unknown segment type: {segment_type}")
    return source.with_columns(expression.alias("segment_value"))


def _empty_metric_statistics() -> dict[str, Any]:
    return {
        "mean": None,
        "median": None,
        "std": None,
        "win_rate": None,
        "p05": None,
        "p25": None,
        "p75": None,
        "p95": None,
        "ci_low": None,
        "ci_high": None,
        "mfe_mean": None,
        "mae_mean": None,
        "year_positive_ratio": None,
        "worst_year": None,
        "worst_year_mean": None,
        "p_value": None,
    }


def _statistics_for_ordered_values(
    rows: Sequence[tuple[date, float, float, float]],
    *,
    bootstrap_replicates: int,
    seed_material: str,
) -> dict[str, Any]:
    if not rows:
        return _empty_metric_statistics()
    values = np.asarray([row[1] for row in rows], dtype=np.float64)
    values_by_date: dict[date, list[float]] = {}
    yearly: dict[int, list[float]] = {}
    for reveal_date, value, _mfe, _mae in rows:
        values_by_date.setdefault(reveal_date, []).append(value)
        yearly.setdefault(reveal_date.year, []).append(value)
    ci_low, ci_high, p_value = _bootstrap_mean(
        values_by_date,
        replicates=bootstrap_replicates,
        seed_material=seed_material,
    )
    yearly_means = {
        year: float(np.mean(year_values)) for year, year_values in yearly.items()
    }
    worst_year = min(yearly_means, key=lambda year: (yearly_means[year], year))
    quantiles = np.quantile(values, [0.05, 0.25, 0.75, 0.95], method="linear")
    return {
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "std": float(values.std(ddof=1)) if values.size >= 2 else None,
        "win_rate": float(np.count_nonzero(values > 0.0) / values.size),
        "p05": float(quantiles[0]),
        "p25": float(quantiles[1]),
        "p75": float(quantiles[2]),
        "p95": float(quantiles[3]),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "mfe_mean": float(np.mean([row[2] for row in rows])),
        "mae_mean": float(np.mean([row[3] for row in rows])),
        "year_positive_ratio": (
            sum(value > 0.0 for value in yearly_means.values()) / len(yearly_means)
        ),
        "worst_year": worst_year,
        "worst_year_mean": yearly_means[worst_year],
        "p_value": p_value,
    }


def build_event_metrics_from_artifacts(
    outcome_paths: Sequence[str | Path],
    calendar: pl.DataFrame,
    split_plan: SplitPlan,
    *,
    run_id: str,
    requested_splits: Sequence[str] = ("TRAIN", "VALIDATION"),
    access: HoldoutAccess | None = None,
    bootstrap_replicates: int = 1000,
    combo_id: str = "SINGLE_SIGNAL_DIMENSIONS_V1",
) -> pl.DataFrame:
    """Aggregate metrics without materializing all outcomes as Python objects.

    One segment type and horizon is collected at a time into compact Arrow
    columns.  Rows are explicitly sorted into the legacy outcome order before
    NumPy statistics and reveal-date bootstrap are evaluated, preserving the
    V1 floating-point operation order.
    """

    effective_access = access if access is not None else HoldoutAccess()
    effective_access.authorize(requested_splits)
    if bootstrap_replicates < 0:
        raise ValueError("bootstrap_replicates must be non-negative")
    requested = tuple(dict.fromkeys(requested_splits))
    if not outcome_paths:
        return pl.DataFrame()
    calendar_days = _calendar_dates(calendar)
    density_denominators = _eligible_session_counts(calendar_days, split_plan)
    source = pl.scan_parquet([str(Path(path)) for path in outcome_paths]).filter(
        pl.col("split_id").is_in(requested)
    )
    metrics: list[dict[str, Any]] = []
    order_columns = [
        "reveal_date",
        "code",
        "expected_model_id",
        "direction",
        "signal_fact_id",
    ]

    for segment_type in _SEGMENT_TYPES:
        segmented = _segment_lazy_frame(source, segment_type)
        counts = (
            segmented.group_by(["split_id", "segment_value"])
            .agg(
                pl.len().alias("n_total"),
                (pl.col("split_boundary_status") == SPLIT_ELIGIBLE)
                .sum()
                .alias("n_eligible"),
            )
            .collect(engine="streaming")
        )
        count_by_key = {
            (str(row["split_id"]), str(row["segment_value"])): row
            for row in counts.iter_rows(named=True)
        }
        for horizon in HORIZONS:
            prefix = f"h{horizon}"
            executable = (
                segmented.filter(
                    (pl.col("split_boundary_status") == SPLIT_ELIGIBLE)
                    & (pl.col(f"{prefix}_status") == OUTCOME_OK)
                )
                .select(
                    "split_id",
                    "segment_value",
                    *order_columns,
                    pl.col(f"{prefix}_direction_adjusted_return").alias("value"),
                    pl.col(f"{prefix}_mfe").alias("mfe"),
                    pl.col(f"{prefix}_mae").alias("mae"),
                )
                .sort(["split_id", "segment_value", *order_columns])
                .collect(engine="streaming")
            )
            executable_counts = {
                (str(row["split_id"]), str(row["segment_value"])): int(row["len"])
                for row in executable.group_by(
                    ["split_id", "segment_value"], maintain_order=True
                )
                .len()
                .iter_rows(named=True)
            }
            statistics: dict[tuple[str, str], dict[str, Any]] = {}
            current_key: tuple[str, str] | None = None
            ordered_values: list[tuple[date, float, float, float]] = []

            def finish_group() -> None:
                if current_key is None:
                    return
                statistics[current_key] = _statistics_for_ordered_values(
                    ordered_values,
                    bootstrap_replicates=bootstrap_replicates,
                    seed_material="|".join(
                        map(
                            str,
                            (
                                run_id,
                                current_key[0],
                                segment_type,
                                current_key[1],
                                horizon,
                                bootstrap_replicates,
                            ),
                        )
                    ),
                )

            for row in executable.iter_rows(named=True):
                key = (str(row["split_id"]), str(row["segment_value"]))
                if key != current_key:
                    finish_group()
                    current_key = key
                    ordered_values = []
                ordered_values.append(
                    (
                        row["reveal_date"],
                        float(row["value"]),
                        float(row["mfe"]),
                        float(row["mae"]),
                    )
                )
            finish_group()

            for key in sorted(count_by_key):
                split_id, segment_value = key
                count_row = count_by_key[key]
                n_total = int(count_row["n_total"])
                n_eligible = int(count_row["n_eligible"])
                n_executable = executable_counts.get(key, 0)
                row = {
                    "run_id": run_id,
                    "combo_id": combo_id,
                    "split_id": split_id,
                    "segment_type": segment_type,
                    "segment_value": segment_value,
                    "horizon": horizon,
                    "n_total": n_total,
                    "n_executable": n_executable,
                    "n_censored": n_eligible - n_executable,
                    "n_purged_or_embargoed": n_total - n_eligible,
                    **statistics.get(key, _empty_metric_statistics()),
                    "signal_density": (
                        n_eligible / density_denominators[split_id]
                        if density_denominators[split_id]
                        else None
                    ),
                    "fdr_q_value": None,
                    "bootstrap_block": "reveal_date",
                    "bootstrap_replicates": bootstrap_replicates,
                }
                metrics.append(row)
    _apply_bh_fdr(metrics)
    return (
        pl.DataFrame(metrics, infer_schema_length=None)
        .select(_METRIC_COLUMNS)
        .sort(["split_id", "segment_type", "segment_value", "horizon"])
        if metrics
        else pl.DataFrame()
    )


def _selection_outcome_paths(
    root: Path,
    artifacts: Sequence[Mapping[str, Any]],
    split_plan: SplitPlan,
    requested_splits: Sequence[str],
) -> list[Path]:
    requested = set(requested_splits)
    windows = {window.split_id: window for window in split_plan.windows}
    holdout_start = windows["HOLDOUT"].start_date
    selected: list[Path] = []
    for meta in artifacts:
        minimum_raw = meta.get("min_reveal_date")
        maximum_raw = meta.get("max_reveal_date")
        if not isinstance(minimum_raw, str) or not isinstance(maximum_raw, str):
            raise EventStudyError(
                "event outcome artifact has no selection-safe reveal-date bounds"
            )
        minimum = date.fromisoformat(minimum_raw)
        maximum = date.fromisoformat(maximum_raw)
        if minimum < holdout_start <= maximum:
            raise EventStudyError(
                "event outcome artifact straddles the HOLDOUT selection boundary"
            )
        partition = meta.get("partition")
        split_id = (
            str(partition.get("split_id"))
            if isinstance(partition, Mapping) and partition.get("split_id") is not None
            else None
        )
        if split_id is not None:
            if split_id not in requested:
                continue
            window = windows.get(split_id)
            if (
                window is None
                or minimum < window.start_date
                or maximum > window.end_date
            ):
                raise EventStudyError(
                    "event outcome partition differs from its split date bounds"
                )
        else:
            if minimum >= holdout_start:
                continue
            if not any(
                current_split in requested
                and maximum >= window.start_date
                and minimum <= window.end_date
                for current_split, window in windows.items()
            ):
                continue
        selected.append(root / str(meta["path"]))
    if not selected:
        raise EventStudyError("no pre-HOLDOUT event paths are eligible for aggregation")
    return selected


_SIGNAL_BUCKET_PATTERN = re.compile(r"(?:^|/)code_bucket=(\d+)(?:/|$)")


def _load_snapshot_catalog(
    snapshot_root: Path,
) -> tuple[dict[str, Any], str, pl.DataFrame, dict[str, Mapping[str, Any]]]:
    manifest, manifest_sha = _read_hashed_manifest(snapshot_root, kind="snapshot")
    dataset = manifest.get("dataset", {})
    calendar_meta = dataset.get("calendar_file")
    if not isinstance(calendar_meta, Mapping):
        raise EventStudyError("snapshot manifest has no calendar_file")
    calendar = pl.read_parquet(_verify_artifact(snapshot_root, calendar_meta))
    by_code: dict[str, Mapping[str, Any]] = {}
    for meta in dataset.get("bar_files", []):
        code = meta.get("partition", {}).get("code")
        if isinstance(code, str):
            if code in by_code:
                raise EventStudyError(f"snapshot has duplicate bar file for {code}")
            by_code[code] = meta
    return manifest, manifest_sha, calendar, by_code


@dataclass(frozen=True, slots=True)
class _SignalBucketCatalog:
    manifest: dict[str, Any]
    manifest_sha256: str
    metas_by_bucket: Mapping[int, tuple[Mapping[str, Any], ...]]
    legacy_frames_by_bucket: Mapping[int, tuple[pl.DataFrame, ...]]

    @property
    def buckets(self) -> tuple[int, ...]:
        return tuple(
            sorted(set(self.metas_by_bucket) | set(self.legacy_frames_by_bucket))
        )


def _load_signal_catalog(signal_root: Path) -> _SignalBucketCatalog:
    manifest, manifest_sha = _read_hashed_manifest(signal_root, kind="signal")
    if manifest.get("state") != "COMPLETE":
        raise EventStudyError("signal manifest state is not COMPLETE")
    metas = [
        item
        for item in manifest.get("artifacts", [])
        if item.get("dataset") == "signal_revisions"
    ]
    if not metas:
        raise EventStudyError("signal manifest has no signal_revisions artifacts")
    metas_by_bucket: dict[int, list[Mapping[str, Any]]] = {}
    legacy_frames_by_bucket: dict[int, list[pl.DataFrame]] = {}
    for meta in sorted(metas, key=lambda item: str(item["path"])):
        path = _verify_artifact(signal_root, meta)
        match = _SIGNAL_BUCKET_PATTERN.search(str(meta["path"]).replace("\\", "/"))
        if match is not None:
            metas_by_bucket.setdefault(int(match.group(1)), []).append(meta)
            continue
        # Compatibility for V1 fixtures and pre-bucket artifacts.  Production
        # manifests are bucket-addressable and never take this bounded route.
        frame = pl.read_parquet(path)
        if "code_bucket" not in frame.columns:
            raise EventStudyError("unpartitioned signal artifact has no code_bucket")
        for key, partition in frame.partition_by("code_bucket", as_dict=True).items():
            bucket = int(key[0] if isinstance(key, tuple) else key)
            legacy_frames_by_bucket.setdefault(bucket, []).append(partition)
    return _SignalBucketCatalog(
        manifest=manifest,
        manifest_sha256=manifest_sha,
        metas_by_bucket={key: tuple(value) for key, value in metas_by_bucket.items()},
        legacy_frames_by_bucket={
            key: tuple(value) for key, value in legacy_frames_by_bucket.items()
        },
    )


def _load_bucket_signals(
    signal_root: Path, catalog: _SignalBucketCatalog, bucket: int
) -> pl.DataFrame:
    frames = list(catalog.legacy_frames_by_bucket.get(bucket, ()))
    frames.extend(
        pl.read_parquet(signal_root / str(meta["path"]))
        for meta in catalog.metas_by_bucket.get(bucket, ())
    )
    if not frames:
        raise EventStudyError(f"signal bucket {bucket} has no fact frame")
    frame = pl.concat(frames, how="vertical")
    values = set(frame["code_bucket"].unique().to_list())
    if values != {bucket}:
        raise EventStudyError(
            f"signal bucket path/content mismatch: expected {bucket}, got {sorted(values)}"
        )
    return frame


def _write_parquet_artifact(
    frame: pl.DataFrame, physical: Path, relative: str, dataset: str
) -> dict[str, Any]:
    physical.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(physical, **_PARQUET_OPTIONS)
    # The Windows CRT rejects ``fsync`` on a read-only descriptor.
    with physical.open("rb+") as stream:
        os.fsync(stream.fileno())
    _fsync_directory(physical.parent)
    result: dict[str, Any] = {
        "dataset": dataset,
        "path": relative,
        "rows": frame.height,
        "schema_fingerprint": _schema_fingerprint(frame),
        "logical_sha256": _logical_frame_sha256(frame),
        "file_sha256": _sha256_file(physical),
    }
    if frame.height and "reveal_date" in frame.columns:
        result["min_reveal_date"] = frame["reveal_date"].min().isoformat()
        result["max_reveal_date"] = frame["reveal_date"].max().isoformat()
    return result


def _event_support_dates(
    signals: pl.DataFrame,
    calendar_days: Sequence[date],
    calendar_index: Mapping[date, int],
) -> tuple[date, ...]:
    required: set[date] = set()
    actionable = signals.filter(
        pl.col("event_kind").is_in(ACTIONABLE_EVENT_KINDS) & pl.col("actionable")
    )
    for reveal_date in actionable["reveal_date"].unique().to_list():
        reveal_index = calendar_index.get(reveal_date)
        if reveal_index is None:
            raise EventStudyError("signal reveal_date is absent from snapshot calendar")
        start = reveal_index + 1
        required.update(calendar_days[start : start + max(HORIZONS)])
    return tuple(sorted(required))


def _read_filtered_code_bars(path: Path, support_dates: Sequence[date]) -> pl.DataFrame:
    source = pl.scan_parquet(path).select(sorted(_REQUIRED_BAR_COLUMNS))
    if not support_dates:
        return source.head(0).collect(engine="streaming")
    return source.filter(
        pl.col("trade_date").is_between(
            support_dates[0], support_dates[-1], closed="both"
        )
        & pl.col("trade_date").is_in(support_dates)
    ).collect(engine="streaming")


def _sum_event_summaries(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "input_signal_revisions": sum(
            int(item["input_signal_revisions"]) for item in summaries
        ),
        "remove_revisions_ignored": sum(
            int(item["remove_revisions_ignored"]) for item in summaries
        ),
        "actionable_duplicates_removed": sum(
            int(item["actionable_duplicates_removed"]) for item in summaries
        ),
        "event_outcomes": sum(int(item["event_outcomes"]) for item in summaries),
        "entry_executable": sum(int(item["entry_executable"]) for item in summaries),
        "entry_censored": sum(int(item["entry_censored"]) for item in summaries),
        "corporate_action_events": sum(
            int(item["corporate_action_events"]) for item in summaries
        ),
        "dedup_rule": DEDUP_RULE,
    }


def _read_event_checkpoint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise EventStudyError(f"event bucket checkpoint is missing: {path}")
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    recorded = checkpoint.pop("checkpoint_sha256", None)
    actual = _sha256_bytes(canonical_json_bytes(checkpoint))
    checkpoint["checkpoint_sha256"] = recorded
    if recorded != actual:
        raise EventStudyError(f"event bucket checkpoint hash mismatch: {path}")
    return checkpoint


def _load_event_checkpoint(output_root: Path, bucket: int) -> dict[str, Any]:
    directory = output_root / "code_buckets" / f"code_bucket={bucket:03d}"
    checkpoint = _read_event_checkpoint(directory / "checkpoint.json")
    if int(checkpoint["code_bucket"]) != bucket:
        raise EventStudyError("event bucket checkpoint id mismatch")
    for meta in checkpoint["artifacts"]:
        _verify_artifact(output_root, meta)
    return checkpoint


def _verify_staged_event_checkpoint(staging: Path, bucket: int) -> dict[str, Any]:
    checkpoint = _read_event_checkpoint(staging / "checkpoint.json")
    if int(checkpoint["code_bucket"]) != bucket:
        raise EventStudyError("staged event bucket checkpoint id mismatch")
    prefix = Path("code_buckets") / f"code_bucket={bucket:03d}"
    for meta in checkpoint["artifacts"]:
        relative = Path(str(meta["path"])).relative_to(prefix)
        physical = staging / relative
        if not physical.is_file() or _sha256_file(physical) != _artifact_hash(meta):
            raise EventStudyError(f"staged event artifact mismatch: {physical}")
    return checkpoint


def _process_event_bucket(
    *,
    snapshot_root: Path,
    signal_root: Path,
    output_root: Path,
    staging: Path,
    bucket: int,
    catalog: _SignalBucketCatalog,
    source_files: Mapping[str, Mapping[str, Any]],
    calendar: pl.DataFrame,
    split_plan: SplitPlan,
    run_id: str,
    event_set_id: str,
) -> dict[str, Any]:
    signals = _load_bucket_signals(signal_root, catalog, bucket)
    if "run_id" in signals.columns and set(signals["run_id"].drop_nulls()) != {run_id}:
        raise EventStudyError("signal fact run_id differs from signal manifest")
    codes = tuple(sorted(str(value) for value in signals["code"].unique().to_list()))
    missing = sorted(set(codes) - set(source_files))
    if missing:
        raise EventStudyError(f"signal codes absent from snapshot: {missing}")
    calendar_days = _calendar_dates(calendar)
    calendar_index = {day: index for index, day in enumerate(calendar_days)}
    signal_partitions = {
        str(key[0] if isinstance(key, tuple) else key): partition
        for key, partition in signals.partition_by("code", as_dict=True).items()
    }
    outcomes_by_code: list[pl.DataFrame] = []
    summaries: list[dict[str, Any]] = []
    code_stats: list[dict[str, Any]] = []
    snapshot_inputs: list[dict[str, Any]] = []
    for code in codes:
        code_signals = signal_partitions[code]
        source_meta = source_files[code]
        source_path = _verify_artifact(snapshot_root, source_meta)
        support_dates = _event_support_dates(
            code_signals, calendar_days, calendar_index
        )
        bars = _read_filtered_code_bars(source_path, support_dates)
        outcomes, summary = build_event_outcomes_frame(
            code_signals, bars, calendar, split_plan, run_id=run_id
        )
        if outcomes.height:
            outcomes_by_code.append(outcomes)
        summaries.append(summary)
        source_rows = source_meta.get("rows")
        if source_rows is None:
            source_rows = (
                pl.scan_parquet(source_path)
                .select(pl.len())
                .collect(engine="streaming")
                .item()
            )
        code_stats.append(
            {
                "code": code,
                "signal_revisions": code_signals.height,
                "event_outcomes": outcomes.height,
                "source_bar_rows": int(source_rows),
                "materialized_bar_rows": bars.height,
                "support_sessions": len(support_dates),
                "support_start_date": (
                    support_dates[0].isoformat() if support_dates else None
                ),
                "support_end_date": (
                    support_dates[-1].isoformat() if support_dates else None
                ),
            }
        )
        snapshot_inputs.append(
            {
                "code": code,
                "path": str(source_meta["path"]),
                "file_sha256": _artifact_hash(source_meta),
                "rows": int(source_rows),
            }
        )

    artifacts: list[dict[str, Any]] = []
    if outcomes_by_code:
        outcomes = pl.concat(outcomes_by_code, how="vertical").sort(
            [
                "reveal_date",
                "code",
                "expected_model_id",
                "direction",
                "signal_fact_id",
            ]
        )
        for year in sorted(outcomes["reveal_year"].unique().to_list()):
            partition = outcomes.filter(pl.col("reveal_year") == year)
            tail = f"event_outcomes/reveal_year={int(year)}/part-00000.parquet"
            relative = f"code_buckets/code_bucket={bucket:03d}/{tail}"
            meta = _write_parquet_artifact(
                partition, staging / tail, relative, "event_outcomes"
            )
            meta["partition"] = {
                "code_bucket": bucket,
                "reveal_year": int(year),
            }
            artifacts.append(meta)
    summary = _sum_event_summaries(summaries)
    signal_inputs = [
        {
            "path": str(meta["path"]),
            "file_sha256": _artifact_hash(meta),
            "rows": int(meta.get("rows", 0)),
        }
        for meta in catalog.metas_by_bucket.get(bucket, ())
    ]
    checkpoint_payload = {
        "schema_version": EVENT_STUDY_SCHEMA_VERSION,
        "state": "COMPLETE",
        "event_set_id": event_set_id,
        "run_id": run_id,
        "code_bucket": bucket,
        "codes": list(codes),
        "signal_inputs": signal_inputs,
        "snapshot_inputs": snapshot_inputs,
        "bar_loading": {
            "unit": "ONE_CODE",
            "filter": "UNION_OF_EVENT_T_PLUS_1_THROUGH_H20_SESSIONS",
            "full_market_python_bar_map": False,
            "source_bar_rows": sum(item["source_bar_rows"] for item in code_stats),
            "materialized_bar_rows": sum(
                item["materialized_bar_rows"] for item in code_stats
            ),
            "max_materialized_bar_rows_per_code": max(
                (item["materialized_bar_rows"] for item in code_stats), default=0
            ),
        },
        "summary": summary,
        "code_stats": code_stats,
        "artifacts": sorted(
            artifacts, key=lambda item: (item["dataset"], item["path"])
        ),
    }
    checkpoint = _with_content_hash(checkpoint_payload, "checkpoint_sha256")
    _write_json(staging / "checkpoint.json", checkpoint)
    return checkpoint


def _publish_event_bucket(
    output_root: Path, staging: Path, bucket: int, event_set_id: str
) -> dict[str, Any]:
    checkpoint = _verify_staged_event_checkpoint(staging, bucket)
    if checkpoint["event_set_id"] != event_set_id:
        raise EventStudyError("staged event checkpoint belongs to another event set")
    final = output_root / "code_buckets" / f"code_bucket={bucket:03d}"
    if final.exists():
        raise EventStudyError(f"event bucket already exists: {final}")
    os.replace(staging, final)
    _fsync_directory(final.parent)
    return _load_event_checkpoint(output_root, bucket)


def build_event_study(
    snapshot_dir: str | Path,
    signal_dir: str | Path,
    output_dir: str | Path,
    split_plan: SplitPlan,
    *,
    bootstrap_replicates: int = 1000,
    resume: bool = False,
    max_buckets: int | None = None,
) -> dict[str, Any]:
    """Checkpoint bucket outcomes, then publish locked TRAIN/VALIDATION metrics."""

    if bootstrap_replicates < 0:
        raise ValueError("bootstrap_replicates must be non-negative")
    if max_buckets is not None and (isinstance(max_buckets, bool) or max_buckets < 1):
        raise ValueError("max_buckets must be a positive integer")
    snapshot_root = Path(snapshot_dir).resolve()
    signal_root = Path(signal_dir).resolve()
    output_root = Path(output_dir).resolve()
    signal_catalog = _load_signal_catalog(signal_root)
    signal_manifest = signal_catalog.manifest
    snapshot_manifest, snapshot_sha, calendar, source_files = _load_snapshot_catalog(
        snapshot_root
    )
    signal_snapshot = signal_manifest.get("snapshot", {}).get("snapshot_id")
    if (
        signal_snapshot is not None
        and signal_snapshot != snapshot_manifest["snapshot_id"]
    ):
        raise EventStudyError("signal and event snapshot_id differ")
    identity_payload = {
        "schema_version": EVENT_STUDY_SCHEMA_VERSION,
        "snapshot_id": snapshot_manifest["snapshot_id"],
        "snapshot_manifest_sha256": snapshot_sha,
        "signal_set_id": signal_manifest["signal_set_id"],
        "signal_manifest_sha256": signal_catalog.manifest_sha256,
        "horizons": list(HORIZONS),
        "entry_clock": "reveal_date next snapshot session raw_open",
        "return_price_domain": "RAW",
        "direction_adjusted_return": DIRECTION_ADJUSTED_RETURN_CONTRACT,
        "direction_adjusted_excursions": DIRECTION_ADJUSTED_EXCURSION_CONTRACT,
        "dedup_rule": DEDUP_RULE,
        "split_plan": split_plan.to_dict(),
        "bootstrap_block": "reveal_date",
        "bootstrap_replicates": bootstrap_replicates,
    }
    run_id = signal_manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise EventStudyError("signal manifest has no run_id")
    event_set_id = "sha256:" + _sha256_bytes(canonical_json_bytes(identity_payload))
    expected_config = {
        "schema_version": EVENT_STUDY_SCHEMA_VERSION,
        "event_set_id": event_set_id,
        "run_id": run_id,
        "identity": identity_payload,
        "storage": {
            "checkpoint_unit": "code_bucket",
            "bar_materialization_unit": "code",
            "bar_session_filter": "event T+1 through H20",
            "metric_materialization": "segment_type x horizon Arrow slice",
        },
    }

    if not output_root.exists():
        bootstrap = output_root.parent / f".{output_root.name}.bootstrap-{os.getpid()}"
        shutil.rmtree(bootstrap, ignore_errors=True)
        bootstrap.mkdir(parents=True)
        _write_json(bootstrap / "build_config.json", expected_config)
        os.replace(bootstrap, output_root)
        _fsync_directory(output_root.parent)
    config_path = output_root / "build_config.json"
    if not config_path.is_file():
        raise EventStudyError("existing event output has no build_config.json")
    actual_config = json.loads(config_path.read_text(encoding="utf-8"))
    if actual_config != expected_config:
        raise EventStudyError("existing event output belongs to another event build")
    manifest_path = output_root / "manifest.json"
    marker_path = output_root / "manifest.sha256"
    if marker_path.is_file():
        return verify_event_study(output_root)
    if manifest_path.is_file() and not resume:
        raise EventStudyError("unpublished event manifest requires resume=True")
    if not resume and any((output_root / "code_buckets").glob("code_bucket=*")):
        raise EventStudyError("incomplete event output requires resume=True")

    lock_descriptor = _acquire_build_lock(output_root / ".build.lock", event_set_id)
    try:
        manifest_path.unlink(missing_ok=True)
        for pattern in (
            ".manifest.json.tmp-*",
            ".manifest.sha256.tmp-*",
            "event_metrics/.part-00000.parquet.staging-*",
        ):
            for stale_file in output_root.glob(pattern):
                stale_file.unlink()
        for stale in (output_root / "code_buckets").glob(".code_bucket=*.staging-*"):
            shutil.rmtree(stale)
        completed: dict[int, dict[str, Any]] = {}
        pending: list[int] = []
        for bucket in signal_catalog.buckets:
            final = output_root / "code_buckets" / f"code_bucket={bucket:03d}"
            if final.exists():
                checkpoint = _load_event_checkpoint(output_root, bucket)
                if checkpoint["event_set_id"] != event_set_id:
                    raise EventStudyError("event bucket belongs to another event set")
                completed[bucket] = checkpoint
            else:
                pending.append(bucket)
        scheduled = pending[:max_buckets] if max_buckets is not None else pending
        for bucket in scheduled:
            staging = (
                output_root
                / "code_buckets"
                / f".code_bucket={bucket:03d}.staging-{os.getpid()}"
            )
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True)
            try:
                _process_event_bucket(
                    snapshot_root=snapshot_root,
                    signal_root=signal_root,
                    output_root=output_root,
                    staging=staging,
                    bucket=bucket,
                    catalog=signal_catalog,
                    source_files=source_files,
                    calendar=calendar,
                    split_plan=split_plan,
                    run_id=run_id,
                    event_set_id=event_set_id,
                )
                completed[bucket] = _publish_event_bucket(
                    output_root, staging, bucket, event_set_id
                )
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        remaining = sorted(set(signal_catalog.buckets) - set(completed))
        if remaining:
            return {
                "state": "INCOMPLETE",
                "run_id": run_id,
                "event_set_id": event_set_id,
                "completed_buckets": len(completed),
                "remaining_buckets": len(remaining),
            }

        checkpoints = [completed[bucket] for bucket in sorted(completed)]
        outcome_artifacts = sorted(
            [item for checkpoint in checkpoints for item in checkpoint["artifacts"]],
            key=lambda item: (item["dataset"], item["path"]),
        )
        outcome_paths = _selection_outcome_paths(
            output_root,
            outcome_artifacts,
            split_plan,
            ("TRAIN", "VALIDATION"),
        )
        metrics = build_event_metrics_from_artifacts(
            outcome_paths,
            calendar,
            split_plan,
            run_id=run_id,
            requested_splits=("TRAIN", "VALIDATION"),
            bootstrap_replicates=bootstrap_replicates,
        )
        metric_relative = "event_metrics/part-00000.parquet"
        metric_path = output_root / metric_relative
        metric_path.parent.mkdir(parents=True, exist_ok=True)
        metric_staging = metric_path.with_name(
            f".{metric_path.name}.staging-{os.getpid()}"
        )
        metric_staging.unlink(missing_ok=True)
        metric_meta = _write_parquet_artifact(
            metrics, metric_staging, metric_relative, "event_metrics"
        )
        os.replace(metric_staging, metric_path)
        _fsync_directory(metric_path.parent)
        summaries = [checkpoint["summary"] for checkpoint in checkpoints]
        summary = _sum_event_summaries(summaries)
        bar_loading = {
            "unit": "ONE_CODE_WITHIN_SIGNAL_BUCKET",
            "filter": "UNION_OF_EVENT_T_PLUS_1_THROUGH_H20_SESSIONS",
            "full_market_python_bar_map": False,
            "source_bar_rows": sum(
                int(checkpoint["bar_loading"]["source_bar_rows"])
                for checkpoint in checkpoints
            ),
            "materialized_bar_rows": sum(
                int(checkpoint["bar_loading"]["materialized_bar_rows"])
                for checkpoint in checkpoints
            ),
            "max_materialized_bar_rows_per_code": max(
                (
                    int(checkpoint["bar_loading"]["max_materialized_bar_rows_per_code"])
                    for checkpoint in checkpoints
                ),
                default=0,
            ),
        }
        artifacts = sorted(
            [*outcome_artifacts, metric_meta],
            key=lambda item: (item["dataset"], item["path"]),
        )
        manifest = {
            "manifest_version": 1,
            "schema_version": EVENT_STUDY_SCHEMA_VERSION,
            "state": "COMPLETE",
            "run_id": run_id,
            "event_set_id": event_set_id,
            "identity": identity_payload,
            "snapshot": {
                "snapshot_id": snapshot_manifest["snapshot_id"],
                "manifest_sha256": snapshot_sha,
            },
            "signals": {
                "signal_set_id": signal_manifest["signal_set_id"],
                "manifest_sha256": signal_catalog.manifest_sha256,
            },
            "event_clock": {
                "anchor": "reveal_date",
                "entry": "next market session raw_open",
                "horizons": list(HORIZONS),
                "missing_bar_policy": "CENSOR_WITHOUT_ROLL_OR_FILL",
                "direction_adjusted_return": identity_payload[
                    "direction_adjusted_return"
                ],
                "direction_adjusted_excursions": identity_payload[
                    "direction_adjusted_excursions"
                ],
            },
            "corporate_action_disclosure": {
                "return_domain": "RAW",
                "adj_factor_jump_quality_flag": CORPORATE_ACTION_NOT_FULLY_LEDGERED,
                "qfq_return_substitution": False,
            },
            "dedup": {
                "key": ["code", "reveal_date", "expected_model_id", "direction"],
                "rule": DEDUP_RULE,
            },
            "split_plan": split_plan.to_dict(),
            "holdout_access": {
                "metrics_materialized": False,
                "required": "freeze_id + holdout_revealed + reveal_count=1",
            },
            "partitioning": {
                "checkpoint_unit": "code_bucket",
                "outcome_columns": ["code_bucket", "reveal_year"],
                "completed_buckets": sorted(completed),
                "resume_rule": "verify immutable checkpoint and artifacts before skip",
            },
            "memory_contract": {
                "bars": bar_loading,
                "outcomes": "PARQUET_BUCKETS_NOT_FULL_MARKET_PYTHON_ROWS",
                "metrics": (
                    "ONE_SEGMENT_TYPE_X_HORIZON_ARROW_SLICE_SORTED_IN_V1_ORDER"
                ),
                "floating_point_order": "LEGACY_REVEAL_CODE_MODEL_DIRECTION_FACT",
            },
            "summary": summary,
            "metric_rows": metrics.height,
            "artifacts": artifacts,
        }
        _write_json(manifest_path, manifest)
        _atomic_write_bytes(
            marker_path,
            (_sha256_file(manifest_path) + "  manifest.json\n").encode("ascii"),
        )
    finally:
        _release_build_lock(lock_descriptor)
    return verify_event_study(output_root)


def _preverification_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _preverification_marker(
    proof: Mapping[str, object], proof_sha256: str
) -> dict[str, object]:
    return {
        "schema_version": EVENT_PREVERIFICATION_MARKER_SCHEMA_VERSION,
        "state": "COMPLETE",
        "run_id": proof["run_id"],
        "event_set_id": proof["event_set_id"],
        "event_manifest_sha256": proof["event_manifest_sha256"],
        "proof_sha256": proof_sha256,
        "tree_lstat_sha256": proof["tree_lstat_sha256"],
        "verifier_module_sha256": proof["verifier_module_sha256"],
        "engine_image_id": proof["engine_image_id"],
        "source_commit": proof["source_commit"],
        "run_contract_sha256": proof["run_contract_sha256"],
    }


def _preverification_reference(
    proof_path: Path,
    proof_sha256: str,
    marker_path: Path,
    marker_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": EVENT_PREVERIFICATION_REFERENCE_SCHEMA_VERSION,
        "proof_path": str(
            _canonical_nonsymlink_path(
                proof_path, kind="event preverification proof", must_exist=True
            )
        ),
        "proof_sha256": proof_sha256,
        "marker_path": str(
            _canonical_nonsymlink_path(
                marker_path, kind="event preverification marker", must_exist=True
            )
        ),
        "marker_sha256": marker_sha256,
    }


def _verify_event_outcome_date_contract(
    frame: pl.DataFrame,
    meta: Mapping[str, object],
    split_plan: SplitPlan,
) -> None:
    """Recompute the date bounds that downstream readers use for path pruning."""

    if frame.is_empty():
        raise EventStudyError("event outcome artifact is empty")
    minimum = frame["reveal_date"].min()
    maximum = frame["reveal_date"].max()
    if not isinstance(minimum, date) or not isinstance(maximum, date):
        raise EventStudyError("event outcome reveal-date bounds are invalid")
    if (
        meta.get("min_reveal_date") != minimum.isoformat()
        or meta.get("max_reveal_date") != maximum.isoformat()
    ):
        raise EventStudyError(
            "event outcome manifest reveal-date bounds differ from artifact"
        )

    allowed_statuses = {
        "TRAIN": {SPLIT_ELIGIBLE, SPLIT_PURGED},
        "VALIDATION": {
            SPLIT_ELIGIBLE,
            SPLIT_PURGED,
            SPLIT_EMBARGOED,
            SPLIT_PURGED_AND_EMBARGOED,
        },
        "HOLDOUT": {SPLIT_ELIGIBLE, SPLIT_EMBARGOED},
        "OUTSIDE": {SPLIT_OUTSIDE},
    }
    assignments = frame.select(
        ["reveal_date", "split_id", "split_boundary_status"]
    ).unique()
    for reveal_date, split_id, boundary_status in assignments.iter_rows():
        expected_split = next(
            (
                window.split_id
                for window in split_plan.windows
                if window.start_date <= reveal_date <= window.end_date
            ),
            "OUTSIDE",
        )
        if split_id != expected_split:
            raise EventStudyError("event outcome split_id differs from the split plan")
        if boundary_status not in allowed_statuses[expected_split]:
            raise EventStudyError(
                "event outcome boundary status is incompatible with split_id"
            )


def verify_event_study(
    output_dir: str | Path,
    *,
    proof_output: str | Path | None = None,
    chain_marker_output: str | Path | None = None,
    engine_image_id: str | None = None,
    source_commit: str | None = None,
    run_contract_sha256: str | None = None,
) -> dict[str, Any]:
    root = _canonical_nonsymlink_path(
        output_dir, kind="event artifact root", must_exist=True
    )
    publish_preverification = (
        proof_output is not None or chain_marker_output is not None
    )
    if publish_preverification and (
        proof_output is None or chain_marker_output is None
    ):
        raise EventStudyError(
            "proof_output and chain_marker_output must be provided together"
        )
    if publish_preverification:
        if not isinstance(engine_image_id, str) or not engine_image_id:
            raise EventStudyError("event preverification requires engine_image_id")
        if not isinstance(source_commit, str) or not re.fullmatch(
            r"[0-9a-f]{40}", source_commit
        ):
            raise EventStudyError("event preverification source_commit is malformed")
        normalized_contract_sha = _sha256_reference(run_contract_sha256)
        before_verification = _event_tree_lstat_entries(root)
    else:
        normalized_contract_sha = None
        before_verification = None
    manifest, manifest_sha = _read_hashed_manifest(root, kind="event")
    if (
        manifest.get("state") != "COMPLETE"
        or manifest.get("schema_version") != EVENT_STUDY_SCHEMA_VERSION
    ):
        raise EventStudyError("event manifest state/schema is invalid")
    identity = manifest.get("identity")
    event_clock = manifest.get("event_clock")
    if (
        not isinstance(identity, Mapping)
        or not isinstance(event_clock, Mapping)
        or identity.get("schema_version") != EVENT_STUDY_SCHEMA_VERSION
        or identity.get("direction_adjusted_return")
        != DIRECTION_ADJUSTED_RETURN_CONTRACT
        or identity.get("direction_adjusted_excursions")
        != DIRECTION_ADJUSTED_EXCURSION_CONTRACT
        or event_clock.get("direction_adjusted_return")
        != DIRECTION_ADJUSTED_RETURN_CONTRACT
        or event_clock.get("direction_adjusted_excursions")
        != DIRECTION_ADJUSTED_EXCURSION_CONTRACT
    ):
        raise EventStudyError("event manifest directional outcome contract is invalid")
    try:
        split_plan = SplitPlan.from_dict(manifest["split_plan"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EventStudyError("event manifest split plan is invalid") from exc
    counts = {"event_outcomes": 0, "event_metrics": 0}
    paths: set[str] = set()
    partitions: set[tuple[int, int]] = set()
    for meta in manifest.get("artifacts", []):
        logical_path = str(meta["path"])
        if logical_path in paths:
            raise EventStudyError(f"duplicate event artifact path: {logical_path}")
        paths.add(logical_path)
        path = _verify_artifact(root, meta)
        frame = pl.read_parquet(path)
        if frame.height != int(meta["rows"]):
            raise EventStudyError(f"artifact row count mismatch: {path}")
        if _schema_fingerprint(frame) != meta["schema_fingerprint"]:
            raise EventStudyError(f"artifact schema mismatch: {path}")
        if _logical_frame_sha256(frame) != meta["logical_sha256"]:
            raise EventStudyError(f"artifact logical hash mismatch: {path}")
        dataset = str(meta["dataset"])
        counts[dataset] = counts.get(dataset, 0) + frame.height
        if dataset == "event_outcomes":
            _verify_event_outcome_date_contract(frame, meta, split_plan)
            if (
                frame.select(pl.struct(["run_id", "signal_fact_id"]).n_unique()).item()
                != frame.height
            ):
                raise EventStudyError("duplicate event outcome primary key")
            if frame.filter(pl.col("event_kind") == "REMOVE").height:
                raise EventStudyError("REMOVE materialized as a new event entry")
            partition = meta.get("partition")
            if isinstance(partition, Mapping):
                bucket = int(partition["code_bucket"])
                year = int(partition["reveal_year"])
                key = (bucket, year)
                if key in partitions:
                    raise EventStudyError("duplicate event outcome partition")
                partitions.add(key)
                if set(frame["code_bucket"].unique().to_list()) != {bucket}:
                    raise EventStudyError(
                        "event outcome code_bucket partition mismatch"
                    )
                if set(frame["reveal_year"].unique().to_list()) != {year}:
                    raise EventStudyError(
                        "event outcome reveal_year partition mismatch"
                    )
                if set(frame["run_id"].unique().to_list()) != {manifest["run_id"]}:
                    raise EventStudyError("event outcome run_id mismatch")
    completed = manifest.get("partitioning", {}).get("completed_buckets", [])
    if completed:
        checkpoint_artifacts: list[dict[str, Any]] = []
        for bucket in completed:
            checkpoint = _load_event_checkpoint(root, int(bucket))
            if checkpoint["event_set_id"] != manifest["event_set_id"]:
                raise EventStudyError("event checkpoint set id mismatch")
            checkpoint_artifacts.extend(checkpoint["artifacts"])
        expected = sorted(
            [
                item
                for item in manifest["artifacts"]
                if item["dataset"] == "event_outcomes"
            ],
            key=lambda item: item["path"],
        )
        actual = sorted(checkpoint_artifacts, key=lambda item: item["path"])
        if expected != actual:
            raise EventStudyError("event artifact registry differs from checkpoints")
    if counts["event_outcomes"] != manifest["summary"]["event_outcomes"]:
        raise EventStudyError("event outcome manifest count mismatch")
    if counts["event_metrics"] != manifest["metric_rows"]:
        raise EventStudyError("event metric manifest count mismatch")
    result = {
        "status": "verified",
        "run_id": manifest["run_id"],
        "event_set_id": manifest["event_set_id"],
        "manifest_sha256": manifest_sha,
        **counts,
        "corporate_action_events": manifest["summary"]["corporate_action_events"],
        "holdout_metrics_materialized": manifest["holdout_access"][
            "metrics_materialized"
        ],
    }
    if not publish_preverification:
        return result

    assert proof_output is not None and chain_marker_output is not None
    assert before_verification is not None
    after_verification = _event_tree_lstat_entries(root)
    if before_verification != after_verification:
        raise EventStudyError("event artifact tree changed during deep verification")
    _assert_registered_event_parquet(after_verification, manifest)
    if not tree_is_sealed(root):
        seal_tree_durable(root)
    if not tree_is_sealed(root):
        raise EventStudyError("event artifact tree did not become immutable")
    sealed_entries = _event_tree_lstat_entries(root)
    _assert_registered_event_parquet(sealed_entries, manifest)
    tree_lstat_sha256 = "sha256:" + _sha256_bytes(canonical_json_bytes(sealed_entries))
    identity = manifest["identity"]
    assert isinstance(identity, Mapping)
    proof = {
        "schema_version": EVENT_PREVERIFICATION_SCHEMA_VERSION,
        "state": "COMPLETE",
        "verification_method": "verify_event_study",
        "run_id": manifest["run_id"],
        "event_set_id": manifest["event_set_id"],
        "event_manifest_sha256": _sha256_reference(manifest_sha),
        "signal_set_id": identity["signal_set_id"],
        "signal_manifest_sha256": _sha256_reference(identity["signal_manifest_sha256"]),
        "verification_result": result,
        "tree_entries": sealed_entries,
        "tree_lstat_sha256": tree_lstat_sha256,
        "verifier_module_sha256": "sha256:" + _sha256_file(Path(__file__).resolve()),
        "engine_image_id": engine_image_id,
        "source_commit": source_commit,
        "run_contract_sha256": normalized_contract_sha,
    }
    proof_path = _canonical_nonsymlink_path(
        proof_output, kind="event preverification proof"
    )
    marker_path = _canonical_nonsymlink_path(
        chain_marker_output, kind="event preverification marker"
    )
    if root == proof_path or root in proof_path.parents:
        raise EventStudyError("event preverification proof must be outside event tree")
    if root == marker_path or root in marker_path.parents:
        raise EventStudyError("event preverification marker must be outside event tree")
    proof_sha256 = _publish_readonly_with_sidecar(
        proof_path, _preverification_json_bytes(proof)
    )
    marker = _preverification_marker(proof, proof_sha256)
    marker_sha256 = _publish_readonly_with_sidecar(
        marker_path, _preverification_json_bytes(marker)
    )
    result["event_preverification"] = _preverification_reference(
        proof_path, proof_sha256, marker_path, marker_sha256
    )
    return result


def _read_preverification_payload(
    path: Path, *, expected_sha256: object | None = None
) -> tuple[bytes, str]:
    if path.is_symlink() or not path.is_file():
        raise EventStudyError(f"preverification file is missing or a symlink: {path}")
    if path.stat().st_mode & 0o222:
        raise EventStudyError(f"preverification file is not read-only: {path}")
    payload = path.read_bytes()
    digest = "sha256:" + _sha256_bytes(payload)
    if expected_sha256 is not None and digest != _sha256_reference(expected_sha256):
        raise EventStudyError(f"preverification reference digest mismatch: {path}")
    sidecar = _preverification_sidecar(path)
    if sidecar.is_symlink() or not sidecar.is_file():
        raise EventStudyError(
            f"preverification sidecar is missing or a symlink: {sidecar}"
        )
    if sidecar.stat().st_mode & 0o222:
        raise EventStudyError(f"preverification sidecar is not read-only: {sidecar}")
    parts = sidecar.read_text(encoding="ascii").strip().split()
    if (
        len(parts) != 2
        or parts[1] != path.name
        or parts[0] != digest.removeprefix("sha256:")
    ):
        raise EventStudyError(f"preverification sidecar mismatch: {sidecar}")
    return payload, digest


def _decode_preverification_object(payload: bytes, *, kind: str) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EventStudyError(f"{kind} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise EventStudyError(f"{kind} is not a JSON object")
    return value


def _validate_preverification_proof(
    root: Path,
    proof: Mapping[str, object],
    *,
    expected_engine_image_id: str | None = None,
    expected_source_commit: str | None = None,
    expected_run_contract_sha256: str | None = None,
) -> tuple[dict[str, Any], list[Mapping[str, object]]]:
    if (
        proof.get("schema_version") != EVENT_PREVERIFICATION_SCHEMA_VERSION
        or proof.get("state") != "COMPLETE"
        or proof.get("verification_method") != "verify_event_study"
    ):
        raise EventStudyError("event preverification proof state/schema is invalid")
    current_verifier_sha = "sha256:" + _sha256_file(Path(__file__).resolve())
    if proof.get("verifier_module_sha256") != current_verifier_sha:
        raise EventStudyError("event preverification verifier module differs")
    engine_image_id = proof.get("engine_image_id")
    source_commit = proof.get("source_commit")
    run_contract_sha256 = _sha256_reference(proof.get("run_contract_sha256"))
    if not isinstance(engine_image_id, str) or not engine_image_id:
        raise EventStudyError("event preverification engine image is invalid")
    if not isinstance(source_commit, str) or not re.fullmatch(
        r"[0-9a-f]{40}", source_commit
    ):
        raise EventStudyError("event preverification source commit is invalid")
    if (
        expected_engine_image_id is not None
        and engine_image_id != expected_engine_image_id
    ):
        raise EventStudyError("event preverification engine image differs")
    if expected_source_commit is not None and source_commit != expected_source_commit:
        raise EventStudyError("event preverification source commit differs")
    if (
        expected_run_contract_sha256 is not None
        and run_contract_sha256 != _sha256_reference(expected_run_contract_sha256)
    ):
        raise EventStudyError("event preverification run contract differs")

    manifest, manifest_sha = _read_hashed_manifest(root, kind="event")
    identity = manifest.get("identity")
    if not isinstance(identity, Mapping):
        raise EventStudyError("event manifest identity is invalid")
    expected_identity = {
        "run_id": manifest.get("run_id"),
        "event_set_id": manifest.get("event_set_id"),
        "event_manifest_sha256": _sha256_reference(manifest_sha),
        "signal_set_id": identity.get("signal_set_id"),
        "signal_manifest_sha256": _sha256_reference(
            identity.get("signal_manifest_sha256")
        ),
    }
    if any(proof.get(key) != value for key, value in expected_identity.items()):
        raise EventStudyError("event preverification identity differs from manifest")
    verification = proof.get("verification_result")
    if not isinstance(verification, Mapping):
        raise EventStudyError("event preverification result is missing")
    for key in ("run_id", "event_set_id", "manifest_sha256"):
        expected = expected_identity[
            "event_manifest_sha256" if key == "manifest_sha256" else key
        ]
        actual = verification.get(key)
        if key == "manifest_sha256":
            actual = _sha256_reference(actual)
        if actual != expected:
            raise EventStudyError("event preverification result identity differs")
    if verification.get("status") != "verified":
        raise EventStudyError("event preverification result status is invalid")

    raw_entries = proof.get("tree_entries")
    if not isinstance(raw_entries, list) or not all(
        isinstance(item, Mapping) for item in raw_entries
    ):
        raise EventStudyError("event preverification tree registry is invalid")
    tree_entries = list(raw_entries)
    expected_tree_sha = "sha256:" + _sha256_bytes(canonical_json_bytes(tree_entries))
    if proof.get("tree_lstat_sha256") != expected_tree_sha:
        raise EventStudyError("event preverification tree registry hash differs")
    if not tree_is_sealed(root):
        raise EventStudyError("event artifact tree is not immutable")
    current_entries = _event_tree_lstat_entries(root)
    if current_entries != tree_entries:
        raise EventStudyError("event artifact tree differs from preverification proof")
    _assert_registered_event_parquet(current_entries, manifest)
    return manifest, tree_entries


def verify_event_preverification(
    output_dir: str | Path,
    reference: Mapping[str, object],
    *,
    expected_engine_image_id: str | None = None,
    expected_source_commit: str | None = None,
    expected_run_contract_sha256: str | None = None,
) -> dict[str, object]:
    if (
        reference.get("schema_version")
        != EVENT_PREVERIFICATION_REFERENCE_SCHEMA_VERSION
    ):
        raise EventStudyError("event preverification reference schema is invalid")
    root = _canonical_nonsymlink_path(
        output_dir, kind="event artifact root", must_exist=True
    )
    proof_path = _canonical_nonsymlink_path(
        str(reference.get("proof_path", "")),
        kind="event preverification proof",
        must_exist=True,
    )
    marker_path = _canonical_nonsymlink_path(
        str(reference.get("marker_path", "")),
        kind="event preverification marker",
        must_exist=True,
    )
    for path in (proof_path, marker_path):
        if root == path or root in path.parents:
            raise EventStudyError(
                "event preverification metadata must be outside event tree"
            )
    proof_payload, proof_sha256 = _read_preverification_payload(
        proof_path, expected_sha256=reference.get("proof_sha256")
    )
    marker_payload, marker_sha256 = _read_preverification_payload(
        marker_path, expected_sha256=reference.get("marker_sha256")
    )
    proof = _decode_preverification_object(
        proof_payload, kind="event preverification proof"
    )
    marker = _decode_preverification_object(
        marker_payload, kind="event preverification marker"
    )
    manifest, tree_entries = _validate_preverification_proof(
        root,
        proof,
        expected_engine_image_id=expected_engine_image_id,
        expected_source_commit=expected_source_commit,
        expected_run_contract_sha256=expected_run_contract_sha256,
    )
    if marker != _preverification_marker(proof, proof_sha256):
        raise EventStudyError("event preverification marker differs from proof")
    return {
        "status": "preverified",
        "run_id": manifest["run_id"],
        "event_set_id": manifest["event_set_id"],
        "manifest_sha256": proof["event_manifest_sha256"],
        "proof_sha256": proof_sha256,
        "marker_sha256": marker_sha256,
        "tree_lstat_sha256": proof["tree_lstat_sha256"],
        "tree_entries": len(tree_entries),
        "verifier_module_sha256": proof["verifier_module_sha256"],
        "engine_image_id": proof["engine_image_id"],
        "source_commit": proof["source_commit"],
        "run_contract_sha256": proof["run_contract_sha256"],
    }


def recover_event_preverification_publication(
    output_dir: str | Path,
    proof_path: str | Path,
    marker_path: str | Path,
    *,
    expected_engine_image_id: str,
    expected_source_commit: str,
    expected_run_contract_sha256: str,
) -> dict[str, object]:
    root = _canonical_nonsymlink_path(
        output_dir, kind="event artifact root", must_exist=True
    )
    proof = _canonical_nonsymlink_path(
        proof_path, kind="event preverification proof", must_exist=True
    )
    marker = _canonical_nonsymlink_path(
        marker_path, kind="event preverification marker"
    )
    if proof.is_symlink() or not proof.is_file():
        raise EventStudyError("event preverification proof is missing during recovery")
    if proof.stat().st_mode & 0o222:
        raise EventStudyError("event preverification proof is not read-only")
    proof_payload = proof.read_bytes()
    proof_sha256 = "sha256:" + _sha256_bytes(proof_payload)
    proof_document = _decode_preverification_object(
        proof_payload, kind="event preverification proof"
    )
    _validate_preverification_proof(
        root,
        proof_document,
        expected_engine_image_id=expected_engine_image_id,
        expected_source_commit=expected_source_commit,
        expected_run_contract_sha256=expected_run_contract_sha256,
    )
    _publish_readonly_with_sidecar(proof, proof_payload)
    marker_payload = _preverification_json_bytes(
        _preverification_marker(proof_document, proof_sha256)
    )
    marker_sha256 = _publish_readonly_with_sidecar(marker, marker_payload)
    reference = _preverification_reference(proof, proof_sha256, marker, marker_sha256)
    result = verify_event_preverification(
        root,
        reference,
        expected_engine_image_id=expected_engine_image_id,
        expected_source_commit=expected_source_commit,
        expected_run_contract_sha256=expected_run_contract_sha256,
    )
    result["event_preverification"] = reference
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--snapshot-dir", required=True)
    build.add_argument("--signal-dir", required=True)
    build.add_argument("--output-dir", required=True)
    build.add_argument("--split-plan", required=True)
    build.add_argument("--bootstrap-replicates", type=int, default=1000)
    build.add_argument("--resume", action="store_true")
    build.add_argument("--max-buckets", type=int)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--output-dir", required=True)
    verify.add_argument("--proof-output")
    verify.add_argument("--chain-marker-output")
    verify.add_argument("--engine-image-id")
    verify.add_argument("--source-commit")
    verify.add_argument("--run-contract-sha256")
    preverification = subparsers.add_parser("verify-preverification")
    preverification.add_argument("--output-dir", required=True)
    preverification.add_argument("--proof", required=True)
    preverification.add_argument("--chain-marker", required=True)
    preverification.add_argument("--engine-image-id", required=True)
    preverification.add_argument("--source-commit", required=True)
    preverification.add_argument("--run-contract-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "verify":
        result = verify_event_study(
            args.output_dir,
            proof_output=args.proof_output,
            chain_marker_output=args.chain_marker_output,
            engine_image_id=args.engine_image_id,
            source_commit=args.source_commit,
            run_contract_sha256=args.run_contract_sha256,
        )
    elif args.command == "verify-preverification":
        result = recover_event_preverification_publication(
            args.output_dir,
            args.proof,
            args.chain_marker,
            expected_engine_image_id=args.engine_image_id,
            expected_source_commit=args.source_commit,
            expected_run_contract_sha256=args.run_contract_sha256,
        )
    else:
        plan = SplitPlan.from_dict(
            json.loads(Path(args.split_plan).read_text(encoding="utf-8"))
        )
        result = build_event_study(
            args.snapshot_dir,
            args.signal_dir,
            args.output_dir,
            plan,
            bootstrap_replicates=args.bootstrap_replicates,
            resume=args.resume,
            max_buckets=args.max_buckets,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
