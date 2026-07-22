"""Build resumable causal CLX signal facts from an immutable snapshot.

Every event comes from comparing two adjacent from-zero prefix calculations.
The completed trigger mask is deliberately split into native shared-predicate
bits and synthetic model-primary bits so S0002's legacy entrypoint-3 overload
does not masquerade as the shared engulfing predicate.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import multiprocessing
import os
import re
import shutil
import socket
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import polars as pl

from ._file_lock import fsync_directory, lock_exclusive, unlock
from .engine import MODEL_COUNT, ClxBatchResult, ClxEngineOptions, FqCopilotClxEngine
from .model_registry import (
    ENTRYPOINT_SEMANTICS,
    MODEL_REGISTRY_VERSION,
    S0002_LEGACY_ENTRYPOINT3_SEMANTIC,
    canonical_json_bytes,
    get_model_registry,
    model_registry_sha256,
)
from .signal import decode_signal
from .snapshot import QUALITY_EXCLUDED_CLX

SIGNAL_FACTS_SCHEMA_VERSION = "clx-causal-signal-facts-v1"
CAUSAL_ROUTE = "PREFIX_REPLAY"
ENGINE_INPUT_PRICE_DOMAIN = "QFQ_OHLC_RAW_VOLUME"
EVENT_KINDS = ("ADD", "REPLACE", "REMOVE")
DEFAULT_BUCKET_COUNT = 64
SIGNAL_QUALITY_S0002_LEGACY_OVERLOAD = 1 << 16
SIGNAL_QUALITY_UNEXPECTED_SYNTHETIC_PRIMARY = 1 << 17
BUILD_LOCK_SCHEMA_VERSION = "clx-signal-build-lock-v1"

_ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")


class SignalFactsError(RuntimeError):
    """Raised when causal facts or their lineage fail the frozen contract."""


@dataclass(frozen=True, slots=True)
class SignalBuildSpec:
    """Immutable selection and engine options for one signal set."""

    run_id: str
    codes: tuple[str, ...] = ()
    bucket_count: int = DEFAULT_BUCKET_COUNT
    options: ClxEngineOptions = field(default_factory=ClxEngineOptions)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not _ULID_RE.fullmatch(self.run_id):
            raise ValueError("run_id must be a canonical uppercase 26-character ULID")
        codes = tuple(sorted(set(self.codes)))
        if any(len(code) != 6 or not code.isdigit() for code in codes):
            raise ValueError("codes must contain six-digit stock codes")
        if isinstance(self.bucket_count, bool) or not 1 <= self.bucket_count <= 256:
            raise ValueError("bucket_count must be an integer in 1..256")
        if not isinstance(self.options, ClxEngineOptions):
            raise ValueError("options must be a ClxEngineOptions instance")
        object.__setattr__(self, "codes", codes)


_FACT_SCHEMA: dict[str, Any] = {
    "signal_fact_id": pl.String,
    "run_id": pl.String,
    "snapshot_id": pl.String,
    "snapshot_manifest_sha256": pl.String,
    "source_database": pl.String,
    "source_bar_file_sha256": pl.String,
    "signal_set_id": pl.String,
    "engine_id": pl.String,
    "code": pl.String,
    "expected_model_id": pl.UInt8,
    "model_id": pl.UInt8,
    "model_code": pl.String,
    "signal_date": pl.Date,
    "as_of_date": pl.Date,
    "reveal_date": pl.Date,
    "revision_no": pl.UInt16,
    "event_kind": pl.String,
    "event_reason": pl.String,
    "previous_raw_signal": pl.Int32,
    "current_raw_signal": pl.Int32,
    "previous_direction": pl.Int8,
    "previous_occurrence": pl.UInt8,
    "previous_primary_entrypoint": pl.UInt8,
    "previous_primary_trigger_semantic": pl.String,
    "previous_direction_base_trigger_mask": pl.UInt8,
    "previous_synthetic_primary_mask": pl.UInt8,
    "previous_concurrent_trigger_mask": pl.UInt8,
    "direction": pl.Int8,
    "occurrence": pl.UInt8,
    "primary_entrypoint": pl.UInt8,
    "primary_trigger_semantic": pl.String,
    "primary_trigger_semantic_source": pl.String,
    "primary_entrypoint_overloaded": pl.Boolean,
    "direction_base_trigger_mask": pl.UInt8,
    "synthetic_primary_mask": pl.UInt8,
    "concurrent_trigger_mask": pl.UInt8,
    "actionable": pl.Boolean,
    "causal_route": pl.String,
    "engine_input_price_domain": pl.String,
    "quality_mask": pl.UInt32,
    "reveal_year": pl.Int16,
    "code_bucket": pl.UInt8,
}

_SORT_COLUMNS = [
    "reveal_date",
    "code",
    "expected_model_id",
    "signal_date",
    "revision_no",
    "event_kind",
]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_sha256_sidecar(path: Path, expected_filename: str) -> str:
    try:
        line = path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise SignalFactsError(f"SHA-256 sidecar is missing: {path}") from exc
    parts = line.split()
    if (
        len(parts) != 2
        or parts[1] != expected_filename
        or not re.fullmatch(r"[0-9a-f]{64}", parts[0])
    ):
        raise SignalFactsError(f"invalid SHA-256 sidecar: {path}")
    return parts[0]


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


def _schema_fingerprint(frame: pl.DataFrame) -> str:
    payload = [(name, str(dtype)) for name, dtype in frame.schema.items()]
    return _sha256_bytes(canonical_json_bytes(payload))


def _fsync_directory(path: Path) -> None:
    fsync_directory(path)


def _atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        with temporary.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, value: object) -> None:
    _atomic_write_bytes(
        path,
        (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        ),
    )


def _boot_id() -> str | None:
    try:
        value = (
            Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        )
    except OSError:
        return None
    return value or None


def _process_start_id(pid: int) -> str | None:
    if os.name == "nt":
        state, start_id = _windows_process_identity(pid)
        return start_id if state == "ACTIVE" else None

    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except OSError:
        return None
    try:
        # Fields after the final ')' begin at proc field 3; starttime is 22.
        return stat.rsplit(")", 1)[1].split()[19]
    except (IndexError, ValueError):
        return None


def _windows_process_identity(pid: int) -> tuple[str, str | None]:
    """Return a Windows process's liveness and creation-time identity.

    ``os.kill(pid, 0)`` is not a liveness probe on Windows: CPython routes
    non-console-control signals through ``TerminateProcess``.  Querying the
    process handle instead keeps the probe side-effect free and lets the build
    lock distinguish PID reuse by the immutable creation ``FILETIME``.
    """

    if os.name != "nt":
        return "UNKNOWN", None
    if pid <= 0 or pid > 0xFFFFFFFF:
        return "DEAD", None

    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    error_invalid_parameter = 87
    error_access_denied = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    get_process_times = kernel32.GetProcessTimes
    get_process_times.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    )
    get_process_times.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    ctypes.set_last_error(0)
    handle = open_process(process_query_limited_information, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == error_invalid_parameter:
            return "DEAD", None
        if error == error_access_denied:
            return "UNKNOWN", None
        return "UNKNOWN", None

    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if not get_process_times(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return "UNKNOWN", None
        start_id = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return "ACTIVE", str(start_id)
    finally:
        close_handle(handle)


def _build_lock_owner(signal_set_id: str) -> dict[str, Any]:
    return {
        "schema_version": BUILD_LOCK_SCHEMA_VERSION,
        "hostname": socket.gethostname(),
        "boot_id": _boot_id(),
        "pid": os.getpid(),
        "process_start_id": _process_start_id(os.getpid()),
        "signal_set_id": signal_set_id,
    }


def _local_lock_owner_state(owner: Mapping[str, Any]) -> str:
    """Return ACTIVE, DEAD, or UNKNOWN for a strictly local lock owner."""

    if owner.get("schema_version") != BUILD_LOCK_SCHEMA_VERSION:
        return "UNKNOWN"
    if owner.get("hostname") != socket.gethostname():
        return "UNKNOWN"
    pid = owner.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return "UNKNOWN"

    current_boot_id = _boot_id()
    recorded_boot_id = owner.get("boot_id")
    if (
        isinstance(recorded_boot_id, str)
        and current_boot_id is not None
        and recorded_boot_id != current_boot_id
    ):
        return "DEAD"

    if os.name == "nt":
        state, current_start_id = _windows_process_identity(pid)
        if state != "ACTIVE":
            return state
        recorded_start_id = owner.get("process_start_id")
        if current_start_id is None or not isinstance(recorded_start_id, str):
            return "UNKNOWN"
        return "ACTIVE" if current_start_id == recorded_start_id else "DEAD"

    proc_root = Path("/proc")
    if proc_root.is_dir():
        process_path = proc_root / str(pid)
        if not process_path.exists():
            return "DEAD"
        current_start_id = _process_start_id(pid)
        recorded_start_id = owner.get("process_start_id")
        if current_start_id is None or not isinstance(recorded_start_id, str):
            return "UNKNOWN"
        return "ACTIVE" if current_start_id == recorded_start_id else "DEAD"

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "DEAD"
    except (PermissionError, OSError):
        return "UNKNOWN"
    return "ACTIVE"


def _acquire_build_lock(lock_path: Path, signal_set_id: str) -> int:
    """Acquire an advisory lock and reclaim only a proven local dead owner."""

    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    try:
        try:
            lock_exclusive(descriptor, blocking=False)
            acquired = True
        except BlockingIOError as exc:
            raise SignalFactsError(
                "another live signal build holds the output lock"
            ) from exc

        os.lseek(descriptor, 0, os.SEEK_SET)
        raw_owner = os.read(descriptor, 64 * 1024).strip()
        if raw_owner:
            try:
                owner = json.loads(raw_owner.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                owner = None
            if isinstance(owner, Mapping):
                state = _local_lock_owner_state(owner)
                if state == "ACTIVE":
                    raise SignalFactsError(
                        "existing build lock belongs to a live local process"
                    )
            # Successful exclusive flock is authoritative for this stable
            # inode. DEAD, UNKNOWN, foreign, and damaged prior metadata cannot
            # represent an active protocol-compliant holder and are replaced.

        payload = canonical_json_bytes(_build_lock_owner(signal_set_id)) + b"\n"
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        _fsync_directory(lock_path.parent)
        return descriptor
    except BaseException:
        try:
            if acquired:
                unlock(descriptor)
        finally:
            os.close(descriptor)
        raise


def _release_build_lock(_lock_path: Path, descriptor: int) -> None:
    try:
        os.ftruncate(descriptor, 0)
        os.fsync(descriptor)
    finally:
        try:
            unlock(descriptor)
        finally:
            os.close(descriptor)


def _with_content_hash(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    result = dict(value)
    result[field_name] = _sha256_bytes(canonical_json_bytes(result))
    return result


def code_bucket(code: str, bucket_count: int) -> int:
    """Assign a code to a stable bucket without Python hash randomization."""

    return int(hashlib.sha256(code.encode("ascii")).hexdigest()[:8], 16) % bucket_count


def _load_snapshot_manifest(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = root / "manifest.json"
    if not path.is_file():
        raise SignalFactsError(f"snapshot manifest is missing: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    sidecar = root / "manifest.sha256"
    if sidecar.is_file():
        recorded = _read_sha256_sidecar(sidecar, "manifest.json")
        actual = _sha256_file(path)
        if recorded != actual:
            raise SignalFactsError("snapshot manifest.sha256 sidecar mismatch")
        embedded = manifest.pop("manifest_sha256", None)
        if embedded is not None:
            raise SignalFactsError(
                "snapshot manifest mixes sidecar and legacy embedded hashes"
            )
    else:
        # Read-only compatibility for snapshots published before the sidecar
        # contract. New snapshot producers write manifest.sha256.
        recorded = manifest.get("manifest_sha256")
        unhashed = dict(manifest)
        unhashed.pop("manifest_sha256", None)
        actual = _sha256_bytes(canonical_json_bytes(unhashed))
        if recorded != actual:
            raise SignalFactsError("snapshot manifest hash is missing or invalid")
    manifest["manifest_sha256"] = recorded
    if not isinstance(manifest.get("snapshot_id"), str):
        raise SignalFactsError("snapshot_id is missing")

    by_code: dict[str, Any] = {}
    for item in manifest.get("dataset", {}).get("bar_files", []):
        partition = item.get("partition", {})
        code = partition.get("code")
        if not isinstance(code, str) or code in by_code:
            raise SignalFactsError("snapshot bar files are not unique by code")
        by_code[code] = item
    if not by_code:
        raise SignalFactsError("snapshot contains no code bar files")
    return manifest, by_code


def _engine_identity(engine: Any, options: ClxEngineOptions) -> dict[str, Any]:
    backend = getattr(engine, "_backend", None)
    backend_path_raw = getattr(backend, "__file__", None)
    backend_path = Path(backend_path_raw) if backend_path_raw else None
    native_sha = (
        _sha256_file(backend_path)
        if backend_path is not None and backend_path.is_file()
        else None
    )
    adapter_files: list[dict[str, str]] = []
    for filename in ("engine.py", "signal.py", "signal_facts.py", "model_registry.py"):
        path = Path(__file__).with_name(filename)
        if path.is_file():
            adapter_files.append({"name": filename, "sha256": _sha256_file(path)})
    explicit_version = getattr(engine, "engine_version", None)
    payload = {
        "engine_class": f"{engine.__class__.__module__}.{engine.__class__.__qualname__}",
        "explicit_engine_version": explicit_version,
        "native_module_name": backend_path.name if backend_path else None,
        "native_module_sha256": native_sha,
        "adapter_files": adapter_files,
        "options": {
            "wave_opt": options.wave_opt,
            "stretch_opt": options.stretch_opt,
            "ext_opt": options.trend_opt,
            "trend_opt_alias": options.trend_opt,
            "switch_opt": 0,
        },
        "model_registry_sha256": model_registry_sha256(),
        "detailed_base_mask_contract": "UNMODIFIED_SHARED_PREDICATES",
    }
    return payload | {
        "engine_id": "sha256:" + _sha256_bytes(canonical_json_bytes(payload))
    }


def _git_commit(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _build_config(
    *,
    snapshot_manifest: Mapping[str, Any],
    selected_codes: Sequence[str],
    bar_files: Mapping[str, Any],
    spec: SignalBuildSpec,
    engine_identity: Mapping[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SIGNAL_FACTS_SCHEMA_VERSION,
        "snapshot_id": snapshot_manifest["snapshot_id"],
        "snapshot_manifest_sha256": snapshot_manifest["manifest_sha256"],
        "selected_codes": list(selected_codes),
        "source_bar_files": [
            {
                "code": code,
                "path": bar_files[code]["path"],
                "sha256": bar_files[code]["sha256"],
                "logical_sha256": bar_files[code].get("logical_sha256"),
            }
            for code in selected_codes
        ],
        "bucket_count": spec.bucket_count,
        "bucket_assignment": "int(sha256(code).hexdigest()[0:8],16) modulo bucket_count",
        "causal_route": CAUSAL_ROUTE,
        "engine_input_price_domain": ENGINE_INPUT_PRICE_DOMAIN,
        "engine_identity": dict(engine_identity),
        "model_registry_sha256": model_registry_sha256(),
        "semantic_contract": {
            "primary_dimension": "primary_trigger_semantic",
            "s0002_entrypoint3_overload": S0002_LEGACY_ENTRYPOINT3_SEMANTIC,
            "completed_mask_formula": (
                "direction_base_trigger_mask OR synthetic_primary_mask"
            ),
        },
    }
    signal_set_payload = {
        key: payload[key]
        for key in (
            "schema_version",
            "snapshot_id",
            "snapshot_manifest_sha256",
            "selected_codes",
            "source_bar_files",
            "bucket_count",
            "causal_route",
            "engine_input_price_domain",
            "engine_identity",
            "model_registry_sha256",
            "semantic_contract",
        )
    }
    payload["signal_set_id"] = "sha256:" + _sha256_bytes(
        canonical_json_bytes(signal_set_payload)
    )
    payload["run_id"] = spec.run_id
    return payload


def _mask_matrices(
    result: ClxBatchResult,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return raw, native-base, synthetic-primary, and completed masks."""

    if not result.has_concurrent_trigger_masks:
        raise SignalFactsError(
            "causal signal facts require detailed native shared-predicate masks"
        )
    raw = np.asarray(result.signals_by_model, dtype=np.int32)
    if raw.shape != (MODEL_COUNT, result.bar_count):
        raise SignalFactsError("native signal matrix shape mismatch")
    buy = np.asarray(result.buy_base_trigger_masks, dtype=np.uint8)
    sell = np.asarray(result.sell_base_trigger_masks, dtype=np.uint8)
    base = np.where(raw > 0, buy[None, :], sell[None, :]).astype(np.uint8)
    nonzero = raw != 0
    base[~nonzero] = 0

    model_offsets = np.arange(MODEL_COUNT, dtype=np.int32)[:, None] * 1000
    entrypoints = (np.abs(raw) - model_offsets) % 100
    primary_bits = np.left_shift(
        np.uint8(1), np.clip(entrypoints - 1, 0, 6).astype(np.uint8)
    ).astype(np.uint8)
    synthetic = np.where(
        nonzero & ((base & primary_bits) == 0), primary_bits, 0
    ).astype(np.uint8)
    completed = np.bitwise_or(base, synthetic)
    return raw, base, synthetic, completed


def _signal_semantics(
    *, model_id: int, raw_signal: int, base_mask: int, synthetic_mask: int
) -> dict[str, Any]:
    decoded = decode_signal(raw_signal, expected_model_id=model_id)
    assert decoded is not None
    entrypoint = decoded.primary_entrypoint
    primary_bit = 1 << (entrypoint - 1)
    overloaded = model_id == 2 and entrypoint == 3
    if overloaded and base_mask & primary_bit:
        semantic = "ENGULFING"
        source = "SHARED_BASE_PREDICATE"
    elif overloaded:
        semantic = S0002_LEGACY_ENTRYPOINT3_SEMANTIC
        source = "S0002_MODEL_LEGACY_FALLBACK"
    elif entrypoint == 1:
        semantic = ENTRYPOINT_SEMANTICS[entrypoint]
        source = "MODEL_STRUCTURAL_PRIMARY"
    else:
        semantic = ENTRYPOINT_SEMANTICS[entrypoint]
        source = (
            "SHARED_BASE_PREDICATE"
            if base_mask & primary_bit
            else "MODEL_PRIMARY_SYNTHETIC"
        )
    if not (base_mask | synthetic_mask) & primary_bit:
        raise SignalFactsError("completed trigger mask is missing its primary bit")
    return {
        "direction": decoded.direction,
        "occurrence": decoded.occurrence,
        "primary_entrypoint": entrypoint,
        "primary_trigger_semantic": semantic,
        "primary_trigger_semantic_source": source,
        "primary_entrypoint_overloaded": overloaded,
    }


def _fact_id(row: Mapping[str, Any]) -> str:
    identity = {
        "signal_set_id": row["signal_set_id"],
        "code": row["code"],
        "expected_model_id": row["expected_model_id"],
        "signal_date": row["signal_date"].isoformat(),
        "as_of_date": row["as_of_date"].isoformat(),
        "event_kind": row["event_kind"],
    }
    return "sha256:" + _sha256_bytes(canonical_json_bytes(identity))


def _process_code(
    *,
    frame: pl.DataFrame,
    code: str,
    bucket: int,
    source_meta: Mapping[str, Any],
    snapshot_manifest: Mapping[str, Any],
    build_config: Mapping[str, Any],
    engine: Any,
    options: ClxEngineOptions,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required = {
        "code",
        "trade_date",
        "qfq_open",
        "qfq_high",
        "qfq_low",
        "qfq_close",
        "raw_volume",
        "quality_mask",
    }
    missing = required - set(frame.columns)
    if missing:
        raise SignalFactsError(f"{code} snapshot bars miss {sorted(missing)}")
    if frame.filter(pl.col("code") != code).height:
        raise SignalFactsError(f"{code} partition contains another code")
    if not frame.equals(frame.sort("trade_date")):
        raise SignalFactsError(f"{code} bars are not sorted")

    excluded_rows = frame.filter(
        (pl.col("quality_mask") & QUALITY_EXCLUDED_CLX) != 0
    ).height
    eligible = frame.filter((pl.col("quality_mask") & QUALITY_EXCLUDED_CLX) == 0)
    input_columns = [
        "qfq_high",
        "qfq_low",
        "qfq_open",
        "qfq_close",
        "raw_volume",
    ]
    if eligible.is_empty():
        return [], {
            "code": code,
            "source_rows": frame.height,
            "eligible_rows": 0,
            "excluded_clx_rows": excluded_rows,
            "prefix_calls": 0,
            "revision_counts": {kind: 0 for kind in EVENT_KINDS},
            "actionable_facts": 0,
            "occurrence_ge_10": 0,
            "s0002_legacy_entrypoint3": 0,
            "unexpected_synthetic_primary": 0,
        }
    if eligible.select([pl.col(name).is_null().any() for name in input_columns]).row(
        0
    ) != (False,) * len(input_columns):
        raise SignalFactsError(f"{code} eligible CLX input contains nulls")

    vectors = tuple(eligible[name].to_list() for name in input_columns)
    dates: list[date] = eligible["trade_date"].to_list()
    qualities = [int(value) for value in eligible["quality_mask"].to_list()]
    previous_raw = np.zeros((MODEL_COUNT, 0), dtype=np.int32)
    previous_base = np.zeros((MODEL_COUNT, 0), dtype=np.uint8)
    previous_synthetic = np.zeros((MODEL_COUNT, 0), dtype=np.uint8)
    previous_completed = np.zeros((MODEL_COUNT, 0), dtype=np.uint8)
    revision_numbers: defaultdict[tuple[int, int], int] = defaultdict(int)
    rows: list[dict[str, Any]] = []
    revision_counts: Counter[str] = Counter()
    semantic_counts: Counter[str] = Counter()
    unexpected_synthetic = 0

    for endpoint in range(eligible.height):
        prefix = tuple(vector[: endpoint + 1] for vector in vectors)
        result = engine.calculate_all(*prefix, options=options)
        current_raw, current_base, current_synthetic, current_completed = (
            _mask_matrices(result)
        )
        common = endpoint
        coordinates: list[tuple[int, int]] = []
        if common:
            changed = (
                (previous_raw != current_raw[:, :common])
                | (previous_base != current_base[:, :common])
                | (previous_synthetic != current_synthetic[:, :common])
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
            old_raw = int(previous_raw[model_id, position]) if position < common else 0
            new_raw = int(current_raw[model_id, position])
            old_base = (
                int(previous_base[model_id, position]) if position < common else 0
            )
            old_synthetic = (
                int(previous_synthetic[model_id, position]) if position < common else 0
            )
            old_completed = (
                int(previous_completed[model_id, position]) if position < common else 0
            )
            new_base = int(current_base[model_id, position])
            new_synthetic = int(current_synthetic[model_id, position])
            new_completed = int(current_completed[model_id, position])
            if old_raw == 0 and new_raw != 0:
                event_kind = "ADD"
            elif old_raw != 0 and new_raw == 0:
                event_kind = "REMOVE"
            elif (
                old_raw != 0
                and new_raw != 0
                and (
                    old_raw != new_raw
                    or old_base != new_base
                    or old_synthetic != new_synthetic
                )
            ):
                event_kind = "REPLACE"
            else:
                raise SignalFactsError("invalid adjacent-prefix state transition")

            previous_fields: dict[str, Any]
            if old_raw:
                old_semantics = _signal_semantics(
                    model_id=model_id,
                    raw_signal=old_raw,
                    base_mask=old_base,
                    synthetic_mask=old_synthetic,
                )
                previous_fields = {
                    "previous_direction": old_semantics["direction"],
                    "previous_occurrence": old_semantics["occurrence"],
                    "previous_primary_entrypoint": old_semantics["primary_entrypoint"],
                    "previous_primary_trigger_semantic": old_semantics[
                        "primary_trigger_semantic"
                    ],
                    "previous_direction_base_trigger_mask": old_base,
                    "previous_synthetic_primary_mask": old_synthetic,
                    "previous_concurrent_trigger_mask": old_completed,
                }
            else:
                previous_fields = {
                    "previous_direction": None,
                    "previous_occurrence": None,
                    "previous_primary_entrypoint": None,
                    "previous_primary_trigger_semantic": None,
                    "previous_direction_base_trigger_mask": None,
                    "previous_synthetic_primary_mask": None,
                    "previous_concurrent_trigger_mask": None,
                }

            current_fields: dict[str, Any]
            signal_quality = qualities[position] | qualities[endpoint]
            if new_raw:
                semantics = _signal_semantics(
                    model_id=model_id,
                    raw_signal=new_raw,
                    base_mask=new_base,
                    synthetic_mask=new_synthetic,
                )
                current_fields = {
                    **semantics,
                    "direction_base_trigger_mask": new_base,
                    "synthetic_primary_mask": new_synthetic,
                    "concurrent_trigger_mask": new_completed,
                }
                semantic_counts[semantics["primary_trigger_semantic"]] += 1
                if (
                    semantics["primary_trigger_semantic"]
                    == S0002_LEGACY_ENTRYPOINT3_SEMANTIC
                ):
                    signal_quality |= SIGNAL_QUALITY_S0002_LEGACY_OVERLOAD
                primary_bit = 1 << (semantics["primary_entrypoint"] - 1)
                if (
                    semantics["primary_entrypoint"] != 1
                    and new_synthetic & primary_bit
                    and semantics["primary_trigger_semantic"]
                    != S0002_LEGACY_ENTRYPOINT3_SEMANTIC
                ):
                    signal_quality |= SIGNAL_QUALITY_UNEXPECTED_SYNTHETIC_PRIMARY
                    unexpected_synthetic += 1
            else:
                current_fields = {
                    "direction": None,
                    "occurrence": None,
                    "primary_entrypoint": None,
                    "primary_trigger_semantic": None,
                    "primary_trigger_semantic_source": None,
                    "primary_entrypoint_overloaded": None,
                    "direction_base_trigger_mask": None,
                    "synthetic_primary_mask": None,
                    "concurrent_trigger_mask": None,
                }

            revision_numbers[(model_id, position)] += 1
            revision_no = revision_numbers[(model_id, position)]
            if revision_no > 65535:
                raise SignalFactsError("revision_no exceeds uint16")
            signal_date = dates[position]
            reveal_date = dates[endpoint]
            row: dict[str, Any] = {
                "run_id": build_config["run_id"],
                "snapshot_id": snapshot_manifest["snapshot_id"],
                "snapshot_manifest_sha256": snapshot_manifest["manifest_sha256"],
                "source_database": snapshot_manifest.get("source", {}).get(
                    "database", "UNKNOWN"
                ),
                "source_bar_file_sha256": source_meta["sha256"],
                "signal_set_id": build_config["signal_set_id"],
                "engine_id": build_config["engine_identity"]["engine_id"],
                "code": code,
                "expected_model_id": model_id,
                "model_id": model_id,
                "model_code": f"S{model_id:04d}",
                "signal_date": signal_date,
                "as_of_date": reveal_date,
                "reveal_date": reveal_date,
                "revision_no": revision_no,
                "event_kind": event_kind,
                "event_reason": (
                    "RAW_SIGNAL_TRANSITION"
                    if old_raw != new_raw
                    else "TRIGGER_PROVENANCE_TRANSITION"
                ),
                "previous_raw_signal": old_raw,
                "current_raw_signal": new_raw,
                **previous_fields,
                **current_fields,
                "actionable": new_raw != 0,
                "causal_route": CAUSAL_ROUTE,
                "engine_input_price_domain": ENGINE_INPUT_PRICE_DOMAIN,
                "quality_mask": signal_quality,
                "reveal_year": reveal_date.year,
                "code_bucket": bucket,
            }
            row["signal_fact_id"] = _fact_id(row)
            rows.append(row)
            revision_counts[event_kind] += 1

        previous_raw = current_raw
        previous_base = current_base
        previous_synthetic = current_synthetic
        previous_completed = current_completed

    return rows, {
        "code": code,
        "source_rows": frame.height,
        "eligible_rows": eligible.height,
        "excluded_clx_rows": excluded_rows,
        "prefix_calls": eligible.height,
        "revision_counts": {kind: revision_counts[kind] for kind in EVENT_KINDS},
        "actionable_facts": sum(bool(row["actionable"]) for row in rows),
        "occurrence_ge_10": sum(
            row["occurrence"] is not None and row["occurrence"] >= 10 for row in rows
        ),
        "s0002_legacy_entrypoint3": semantic_counts[S0002_LEGACY_ENTRYPOINT3_SEMANTIC],
        "unexpected_synthetic_primary": unexpected_synthetic,
    }


def _fact_frame(rows: Sequence[Mapping[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=_FACT_SCHEMA, strict=True).sort(_SORT_COLUMNS)


def _write_artifact(
    frame: pl.DataFrame, physical_path: Path, logical_path: str, dataset: str
) -> dict[str, Any]:
    physical_path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(
        physical_path,
        compression="zstd",
        compression_level=9,
        statistics=True,
        row_group_size=65536,
    )
    meta: dict[str, Any] = {
        "dataset": dataset,
        "path": logical_path,
        "rows": frame.height,
        "schema_fingerprint": _schema_fingerprint(frame),
        "logical_sha256": _logical_frame_sha256(frame),
        "file_sha256": _sha256_file(physical_path),
    }
    if frame.height:
        min_reveal_date = frame["reveal_date"].min()
        max_reveal_date = frame["reveal_date"].max()
        if not isinstance(min_reveal_date, date) or not isinstance(
            max_reveal_date, date
        ):
            raise SignalFactsError("fact reveal-date column is not date32")
        meta["min_reveal_date"] = min_reveal_date.isoformat()
        meta["max_reveal_date"] = max_reveal_date.isoformat()
    return meta


def _sum_stats(code_stats: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "codes": len(code_stats),
        "source_rows": sum(int(item["source_rows"]) for item in code_stats),
        "eligible_rows": sum(int(item["eligible_rows"]) for item in code_stats),
        "excluded_clx_rows": sum(int(item["excluded_clx_rows"]) for item in code_stats),
        "prefix_calls": sum(int(item["prefix_calls"]) for item in code_stats),
        "revision_counts": {
            kind: sum(int(item["revision_counts"][kind]) for item in code_stats)
            for kind in EVENT_KINDS
        },
        "actionable_facts": sum(int(item["actionable_facts"]) for item in code_stats),
        "occurrence_ge_10": sum(int(item["occurrence_ge_10"]) for item in code_stats),
        "s0002_legacy_entrypoint3": sum(
            int(item["s0002_legacy_entrypoint3"]) for item in code_stats
        ),
        "unexpected_synthetic_primary": sum(
            int(item["unexpected_synthetic_primary"]) for item in code_stats
        ),
    }


def _process_bucket(
    *,
    snapshot_root: Path,
    output_root: Path,
    staging: Path,
    bucket: int,
    codes: Sequence[str],
    source_files: Mapping[str, Any],
    snapshot_manifest: Mapping[str, Any],
    build_config: Mapping[str, Any],
    engine: Any,
    options: ClxEngineOptions,
) -> dict[str, Any]:
    all_rows: list[dict[str, Any]] = []
    code_stats: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    for code in codes:
        source_meta = source_files[code]
        source_path = snapshot_root / source_meta["path"]
        actual_sha = _sha256_file(source_path)
        if actual_sha != source_meta["sha256"]:
            raise SignalFactsError(f"snapshot bar file hash mismatch for {code}")
        frame = pl.read_parquet(source_path)
        rows, stats = _process_code(
            frame=frame,
            code=code,
            bucket=bucket,
            source_meta=source_meta,
            snapshot_manifest=snapshot_manifest,
            build_config=build_config,
            engine=engine,
            options=options,
        )
        all_rows.extend(rows)
        code_stats.append(stats)
        inputs.append(
            {
                "code": code,
                "path": source_meta["path"],
                "file_sha256": actual_sha,
                "logical_sha256": source_meta.get("logical_sha256"),
                "rows": frame.height,
            }
        )

    artifacts: list[dict[str, Any]] = []
    if all_rows:
        revisions = _fact_frame(all_rows)
        for year in sorted(revisions["reveal_year"].unique().to_list()):
            year_frame = revisions.filter(pl.col("reveal_year") == year)
            relative = (
                f"code_buckets/code_bucket={bucket:03d}/signal_revisions/"
                f"reveal_year={year}/part-00000.parquet"
            )
            physical = (
                staging
                / "signal_revisions"
                / f"reveal_year={year}"
                / "part-00000.parquet"
            )
            artifacts.append(
                _write_artifact(year_frame, physical, relative, "signal_revisions")
            )
            tradable = year_frame.filter(pl.col("actionable"))
            if tradable.height:
                relative = (
                    f"code_buckets/code_bucket={bucket:03d}/tradable_signal_facts/"
                    f"reveal_year={year}/part-00000.parquet"
                )
                physical = (
                    staging
                    / "tradable_signal_facts"
                    / f"reveal_year={year}"
                    / "part-00000.parquet"
                )
                artifacts.append(
                    _write_artifact(
                        tradable, physical, relative, "tradable_signal_facts"
                    )
                )

    checkpoint_payload = {
        "schema_version": SIGNAL_FACTS_SCHEMA_VERSION,
        "state": "COMPLETE",
        "snapshot_id": snapshot_manifest["snapshot_id"],
        "signal_set_id": build_config["signal_set_id"],
        "code_bucket": bucket,
        "codes": list(codes),
        "inputs": inputs,
        "artifacts": sorted(
            artifacts, key=lambda item: (item["dataset"], item["path"])
        ),
        "stats": _sum_stats(code_stats),
        "code_stats": code_stats,
    }
    checkpoint = _with_content_hash(checkpoint_payload, "checkpoint_sha256")
    _write_json(staging / "checkpoint.json", checkpoint)
    return checkpoint


_NATIVE_WORKER_CONTEXT: dict[str, Any] | None = None


def _initialize_native_bucket_worker(
    snapshot_root: Path,
    output_root: Path,
    source_files: Mapping[str, Any],
    snapshot_manifest: Mapping[str, Any],
    build_config: Mapping[str, Any],
    options: ClxEngineOptions,
) -> None:
    """Initialize one spawned process with its own native engine instance."""

    global _NATIVE_WORKER_CONTEXT
    _NATIVE_WORKER_CONTEXT = {
        "snapshot_root": snapshot_root,
        "output_root": output_root,
        "source_files": source_files,
        "snapshot_manifest": snapshot_manifest,
        "build_config": build_config,
        "options": options,
        "engine": FqCopilotClxEngine(),
    }


def _process_native_bucket_task(
    task: tuple[int, tuple[str, ...], str],
) -> dict[str, Any]:
    """Write one bucket staging tree; only the parent publishes it."""

    if _NATIVE_WORKER_CONTEXT is None:
        raise SignalFactsError("native bucket worker was not initialized")
    bucket, codes, staging_raw = task
    started = time.perf_counter()
    checkpoint = _process_bucket(
        snapshot_root=_NATIVE_WORKER_CONTEXT["snapshot_root"],
        output_root=_NATIVE_WORKER_CONTEXT["output_root"],
        staging=Path(staging_raw),
        bucket=bucket,
        codes=codes,
        source_files=_NATIVE_WORKER_CONTEXT["source_files"],
        snapshot_manifest=_NATIVE_WORKER_CONTEXT["snapshot_manifest"],
        build_config=_NATIVE_WORKER_CONTEXT["build_config"],
        engine=_NATIVE_WORKER_CONTEXT["engine"],
        options=_NATIVE_WORKER_CONTEXT["options"],
    )
    return {
        "bucket": bucket,
        "checkpoint_sha256": checkpoint["checkpoint_sha256"],
        "worker_pid": os.getpid(),
        "elapsed_seconds": time.perf_counter() - started,
    }


def _verify_artifact_path(path: Path, meta: Mapping[str, Any]) -> pl.DataFrame:
    if not path.is_file():
        raise SignalFactsError(f"artifact is missing: {meta['path']}")
    if _sha256_file(path) != meta["file_sha256"]:
        raise SignalFactsError(f"artifact file hash mismatch: {meta['path']}")
    frame = pl.read_parquet(path)
    if frame.height != int(meta["rows"]):
        raise SignalFactsError(f"artifact row count mismatch: {meta['path']}")
    if _schema_fingerprint(frame) != meta["schema_fingerprint"]:
        raise SignalFactsError(f"artifact schema mismatch: {meta['path']}")
    if _logical_frame_sha256(frame) != meta["logical_sha256"]:
        raise SignalFactsError(f"artifact logical hash mismatch: {meta['path']}")
    return frame


def _verify_artifact(output_root: Path, meta: Mapping[str, Any]) -> pl.DataFrame:
    return _verify_artifact_path(output_root / str(meta["path"]), meta)


def _read_checkpoint(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise SignalFactsError(f"bucket checkpoint is missing: {label}")
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    recorded = checkpoint.pop("checkpoint_sha256", None)
    actual = _sha256_bytes(canonical_json_bytes(checkpoint))
    checkpoint["checkpoint_sha256"] = recorded
    if recorded != actual:
        raise SignalFactsError(f"checkpoint hash mismatch: {label}")
    return checkpoint


def _load_checkpoint(output_root: Path, bucket_dir: Path) -> dict[str, Any]:
    checkpoint = _read_checkpoint(bucket_dir / "checkpoint.json", bucket_dir.name)
    for meta in checkpoint["artifacts"]:
        _verify_artifact(output_root, meta)
    return checkpoint


def _load_staged_checkpoint(staging: Path, bucket: int) -> dict[str, Any]:
    label = f"code_bucket={bucket:03d} staging"
    checkpoint = _read_checkpoint(staging / "checkpoint.json", label)
    logical_prefix = f"code_buckets/code_bucket={bucket:03d}/"
    for meta in checkpoint["artifacts"]:
        logical_path = str(meta["path"])
        if not logical_path.startswith(logical_prefix):
            raise SignalFactsError(
                f"staged artifact escaped its bucket: {logical_path}"
            )
        relative = logical_path.removeprefix(logical_prefix)
        _verify_artifact_path(staging / relative, meta)
    return checkpoint


def _prepare_bucket_staging(output_root: Path, bucket: int) -> Path:
    staging = (
        output_root
        / "code_buckets"
        / f".code_bucket={bucket:03d}.staging-{os.getpid()}"
    )
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    return staging


def _publish_bucket_staging(
    *,
    output_root: Path,
    staging: Path,
    final_dir: Path,
    bucket: int,
    codes: Sequence[str],
    signal_set_id: str,
    checkpoint_sha256: str,
) -> dict[str, Any]:
    """Verify an isolated staging tree, atomically publish, then verify again."""

    checkpoint = _load_staged_checkpoint(staging, bucket)
    if checkpoint["checkpoint_sha256"] != checkpoint_sha256:
        raise SignalFactsError("worker checkpoint digest differs from staged content")
    if checkpoint["code_bucket"] != bucket:
        raise SignalFactsError("worker checkpoint bucket mismatch")
    if checkpoint["codes"] != list(codes):
        raise SignalFactsError("worker checkpoint code membership mismatch")
    if checkpoint["signal_set_id"] != signal_set_id:
        raise SignalFactsError("worker checkpoint signal_set_id mismatch")
    if final_dir.exists():
        raise SignalFactsError(f"bucket destination already exists: {final_dir.name}")
    os.replace(staging, final_dir)
    _fsync_directory(final_dir.parent)
    return _load_checkpoint(output_root, final_dir)


def _deep_verify_bucket(
    output_root: Path, checkpoint: Mapping[str, Any]
) -> dict[str, int]:
    revision_frames: list[pl.DataFrame] = []
    tradable_frames: list[pl.DataFrame] = []
    for meta in checkpoint["artifacts"]:
        frame = _verify_artifact(output_root, meta)
        if frame.schema != _FACT_SCHEMA:
            raise SignalFactsError(f"fact schema differs: {meta['path']}")
        if meta["dataset"] == "signal_revisions":
            revision_frames.append(frame)
        elif meta["dataset"] == "tradable_signal_facts":
            tradable_frames.append(frame)

    if not revision_frames:
        if tradable_frames:
            raise SignalFactsError("tradable facts exist without revisions")
        return {"revisions": 0, "tradable": 0}

    revisions = pl.concat(revision_frames, how="vertical").sort(_SORT_COLUMNS)
    if revisions["signal_fact_id"].n_unique() != revisions.height:
        raise SignalFactsError("duplicate signal_fact_id")
    if revisions.filter(pl.col("model_id") != pl.col("expected_model_id")).height:
        raise SignalFactsError("model_id differs from its matrix-row truth")
    if revisions.filter(
        (pl.col("signal_date") > pl.col("reveal_date"))
        | (pl.col("reveal_date") > pl.col("as_of_date"))
    ).height:
        raise SignalFactsError("signal/reveal/as-of date order violation")
    if revisions.filter(pl.col("reveal_date") != pl.col("as_of_date")).height:
        raise SignalFactsError("PREFIX_REPLAY reveal_date must equal as_of_date")

    expected_revision: defaultdict[tuple[str, int, date], int] = defaultdict(int)
    for row in revisions.iter_rows(named=True):
        key = (row["code"], row["expected_model_id"], row["signal_date"])
        expected_revision[key] += 1
        if row["revision_no"] != expected_revision[key]:
            raise SignalFactsError("revision_no is not contiguous")
        kind = row["event_kind"]
        old_raw = row["previous_raw_signal"]
        new_raw = row["current_raw_signal"]
        if kind == "ADD" and not (old_raw == 0 and new_raw != 0):
            raise SignalFactsError("invalid ADD transition")
        if kind == "REMOVE" and not (old_raw != 0 and new_raw == 0):
            raise SignalFactsError("invalid REMOVE transition")
        if kind == "REPLACE" and not (old_raw != 0 and new_raw != 0):
            raise SignalFactsError("invalid REPLACE transition")
        if new_raw == 0:
            if row["actionable"] or row["concurrent_trigger_mask"] is not None:
                raise SignalFactsError("REMOVE exposes a current signal")
            continue
        completed = row["concurrent_trigger_mask"]
        base = row["direction_base_trigger_mask"]
        synthetic = row["synthetic_primary_mask"]
        if base & synthetic or (base | synthetic) != completed:
            raise SignalFactsError("base/synthetic/completed mask invariant failed")
        primary_bit = 1 << (row["primary_entrypoint"] - 1)
        if not completed & primary_bit:
            raise SignalFactsError("completed mask misses the primary bit")
        if row["expected_model_id"] == 2 and row["primary_entrypoint"] == 3:
            expected_semantic = (
                "ENGULFING" if base & primary_bit else S0002_LEGACY_ENTRYPOINT3_SEMANTIC
            )
            if row["primary_trigger_semantic"] != expected_semantic:
                raise SignalFactsError("S0002 entrypoint-3 semantic misclassified")

    expected_tradable = revisions.filter(pl.col("actionable"))
    actual_tradable = (
        pl.concat(tradable_frames, how="vertical").sort(_SORT_COLUMNS)
        if tradable_frames
        else _fact_frame([])
    )
    if not expected_tradable.equals(actual_tradable):
        raise SignalFactsError("tradable materialization differs from revisions")
    return {"revisions": revisions.height, "tradable": actual_tradable.height}


def verify_signal_facts(output_dir: str | Path, *, deep: bool = True) -> dict[str, Any]:
    """Verify manifests, immutable bucket checkpoints, hashes and fact semantics."""

    output_root = Path(output_dir).resolve()
    manifest_path = output_root / "manifest.json"
    digest_path = output_root / "manifest.sha256"
    if not manifest_path.is_file() or not digest_path.is_file():
        raise SignalFactsError("complete signal manifest is missing")
    recorded_manifest_sha = _read_sha256_sidecar(digest_path, "manifest.json")
    if _sha256_file(manifest_path) != recorded_manifest_sha:
        raise SignalFactsError("manifest file SHA-256 mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("state") != "COMPLETE":
        raise SignalFactsError("signal manifest state is not COMPLETE")

    registry_path = output_root / manifest["model_registry"]["path"]
    if _sha256_file(registry_path) != manifest["model_registry"]["file_sha256"]:
        raise SignalFactsError("model registry file hash mismatch")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    actual_registry_digest = "sha256:" + _sha256_bytes(canonical_json_bytes(registry))
    if actual_registry_digest != manifest["model_registry"]["logical_sha256"]:
        raise SignalFactsError("model registry logical hash mismatch")
    overrides = registry.get("semantic_overrides", [])
    if not any(
        item.get("model_id") == 2
        and item.get("entrypoint") == 3
        and item.get("legacy_semantic") == S0002_LEGACY_ENTRYPOINT3_SEMANTIC
        for item in overrides
    ):
        raise SignalFactsError("S0002 legacy semantic disclosure is missing")

    totals = {"revisions": 0, "tradable": 0}
    artifacts: list[dict[str, Any]] = []
    for bucket in manifest["completed_buckets"]:
        bucket_dir = output_root / "code_buckets" / f"code_bucket={bucket:03d}"
        checkpoint = _load_checkpoint(output_root, bucket_dir)
        if checkpoint["signal_set_id"] != manifest["signal_set_id"]:
            raise SignalFactsError("checkpoint signal_set_id mismatch")
        artifacts.extend(checkpoint["artifacts"])
        if deep:
            counts = _deep_verify_bucket(output_root, checkpoint)
            totals = {key: totals[key] + counts[key] for key in totals}
    expected_artifacts = sorted(
        manifest["artifacts"], key=lambda item: (item["dataset"], item["path"])
    )
    actual_artifacts = sorted(
        artifacts, key=lambda item: (item["dataset"], item["path"])
    )
    if expected_artifacts != actual_artifacts:
        raise SignalFactsError("manifest artifact registry differs from checkpoints")
    if deep and (
        totals["revisions"] != manifest["counts"]["signal_revisions"]
        or totals["tradable"] != manifest["counts"]["tradable_signal_facts"]
    ):
        raise SignalFactsError("manifest fact totals mismatch")
    return {
        "status": "verified",
        "signal_set_id": manifest["signal_set_id"],
        "snapshot_id": manifest["snapshot"]["snapshot_id"],
        "manifest_sha256": recorded_manifest_sha,
        "completed_buckets": len(manifest["completed_buckets"]),
        "signal_revisions": manifest["counts"]["signal_revisions"],
        "tradable_signal_facts": manifest["counts"]["tradable_signal_facts"],
        "deep": deep,
    }


def build_signal_facts(
    snapshot_dir: str | Path,
    output_dir: str | Path,
    *,
    spec: SignalBuildSpec | None = None,
    engine: Any | None = None,
    resume: bool = False,
    max_buckets: int | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    """Build deterministic per-bucket facts; completed buckets are immutable."""

    started = time.perf_counter()
    if max_buckets is not None and (isinstance(max_buckets, bool) or max_buckets < 1):
        raise ValueError("max_buckets must be a positive integer")
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("workers must be a positive integer")
    if workers > 1 and engine is not None:
        raise ValueError("workers > 1 requires the default native CLX engine")
    snapshot_root = Path(snapshot_dir).resolve()
    output_root = Path(output_dir).resolve()
    if spec is None:
        raise ValueError("spec with an explicit ULID run_id is required")
    effective_spec = spec
    effective_engine = engine if engine is not None else FqCopilotClxEngine()
    snapshot_manifest, source_files = _load_snapshot_manifest(snapshot_root)
    selected_codes = (
        effective_spec.codes if effective_spec.codes else tuple(sorted(source_files))
    )
    missing = [code for code in selected_codes if code not in source_files]
    if missing:
        raise SignalFactsError(f"selected codes are absent from snapshot: {missing}")
    identity = _engine_identity(effective_engine, effective_spec.options)
    expected_config = _build_config(
        snapshot_manifest=snapshot_manifest,
        selected_codes=selected_codes,
        bar_files=source_files,
        spec=effective_spec,
        engine_identity=identity,
    )

    if not output_root.exists():
        bootstrap = output_root.parent / f".{output_root.name}.bootstrap-{os.getpid()}"
        if bootstrap.exists():
            shutil.rmtree(bootstrap)
        bootstrap.mkdir(parents=True)
        registry = get_model_registry()
        _write_json(bootstrap / "model_registry.json", registry)
        _write_json(bootstrap / "build_config.json", expected_config)
        os.replace(bootstrap, output_root)
    config_path = output_root / "build_config.json"
    if not config_path.is_file():
        raise SignalFactsError("existing output has no build_config.json")
    actual_config = json.loads(config_path.read_text(encoding="utf-8"))
    if actual_config != expected_config:
        raise SignalFactsError("existing output belongs to another signal build")
    manifest_path = output_root / "manifest.json"
    manifest_digest_path = output_root / "manifest.sha256"
    recover_unpublished_manifest = False
    if manifest_digest_path.exists():
        if not manifest_path.is_file():
            raise SignalFactsError(
                "manifest publication marker exists without manifest.json"
            )
        try:
            recorded_digest = _read_sha256_sidecar(
                manifest_digest_path, "manifest.json"
            )
        except SignalFactsError:
            if not resume:
                raise
            # A malformed marker has never established publication. It is
            # regenerated from immutable checkpoints while holding the lock.
            recover_unpublished_manifest = True
        else:
            if recorded_digest != _sha256_file(manifest_path):
                raise SignalFactsError(
                    "published manifest content differs from its SHA-256 marker"
                )
            result = verify_signal_facts(output_root)
            result["idempotent_reuse"] = True
            result["elapsed_seconds"] = time.perf_counter() - started
            result["workers_requested"] = workers
            result["workers_used"] = 0
            result["worker_processes"] = 0
            return result
    elif manifest_path.is_file():
        if not resume:
            raise SignalFactsError("unpublished manifest requires resume=True")
        recover_unpublished_manifest = True
    if not resume and any((output_root / "code_buckets").glob("code_bucket=*")):
        raise SignalFactsError("incomplete output requires resume=True")

    lock_path = output_root / ".build.lock"
    lock_descriptor = _acquire_build_lock(lock_path, expected_config["signal_set_id"])
    processed_now = 0
    workers_used = 0
    worker_pids: set[int] = set()
    try:
        if recover_unpublished_manifest:
            manifest_digest_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            _fsync_directory(output_root)
        bucket_root = output_root / "code_buckets"
        for stale in bucket_root.glob(".code_bucket=*.staging-*"):
            shutil.rmtree(stale)
        buckets: defaultdict[int, list[str]] = defaultdict(list)
        for code in selected_codes:
            buckets[code_bucket(code, effective_spec.bucket_count)].append(code)

        pending_buckets: list[int] = []
        for bucket in sorted(buckets):
            final_dir = bucket_root / f"code_bucket={bucket:03d}"
            if final_dir.exists():
                checkpoint = _load_checkpoint(output_root, final_dir)
                if checkpoint["codes"] != sorted(buckets[bucket]):
                    raise SignalFactsError("checkpoint code membership mismatch")
                continue
            pending_buckets.append(bucket)
        scheduled_buckets = (
            pending_buckets[:max_buckets]
            if max_buckets is not None
            else pending_buckets
        )
        staging_by_bucket: dict[int, Path] = {}
        try:
            if workers == 1:
                workers_used = 1 if scheduled_buckets else 0
                if scheduled_buckets:
                    worker_pids.add(os.getpid())
                for bucket in scheduled_buckets:
                    staging = _prepare_bucket_staging(output_root, bucket)
                    staging_by_bucket[bucket] = staging
                    checkpoint = _process_bucket(
                        snapshot_root=snapshot_root,
                        output_root=output_root,
                        staging=staging,
                        bucket=bucket,
                        codes=sorted(buckets[bucket]),
                        source_files=source_files,
                        snapshot_manifest=snapshot_manifest,
                        build_config=expected_config,
                        engine=effective_engine,
                        options=effective_spec.options,
                    )
                    final_dir = bucket_root / f"code_bucket={bucket:03d}"
                    _publish_bucket_staging(
                        output_root=output_root,
                        staging=staging,
                        final_dir=final_dir,
                        bucket=bucket,
                        codes=sorted(buckets[bucket]),
                        signal_set_id=expected_config["signal_set_id"],
                        checkpoint_sha256=checkpoint["checkpoint_sha256"],
                    )
                    processed_now += 1
            elif scheduled_buckets:
                workers_used = min(workers, len(scheduled_buckets))
                for bucket in scheduled_buckets:
                    staging_by_bucket[bucket] = _prepare_bucket_staging(
                        output_root, bucket
                    )
                spawn_context = multiprocessing.get_context("spawn")
                with concurrent.futures.ProcessPoolExecutor(
                    max_workers=workers_used,
                    mp_context=spawn_context,
                    initializer=_initialize_native_bucket_worker,
                    initargs=(
                        snapshot_root,
                        output_root,
                        source_files,
                        snapshot_manifest,
                        expected_config,
                        effective_spec.options,
                    ),
                ) as executor:
                    future_by_bucket = {
                        bucket: executor.submit(
                            _process_native_bucket_task,
                            (
                                bucket,
                                tuple(sorted(buckets[bucket])),
                                str(staging_by_bucket[bucket]),
                            ),
                        )
                        for bucket in scheduled_buckets
                    }
                    # Future retrieval and publication stay in stable bucket order.
                    for bucket in scheduled_buckets:
                        worker_result = future_by_bucket[bucket].result()
                        if worker_result["bucket"] != bucket:
                            raise SignalFactsError(
                                "native worker returned another bucket"
                            )
                        worker_pids.add(int(worker_result["worker_pid"]))
                        final_dir = bucket_root / f"code_bucket={bucket:03d}"
                        _publish_bucket_staging(
                            output_root=output_root,
                            staging=staging_by_bucket[bucket],
                            final_dir=final_dir,
                            bucket=bucket,
                            codes=sorted(buckets[bucket]),
                            signal_set_id=expected_config["signal_set_id"],
                            checkpoint_sha256=worker_result["checkpoint_sha256"],
                        )
                        processed_now += 1
        except BaseException:
            for staging in staging_by_bucket.values():
                shutil.rmtree(staging, ignore_errors=True)
            raise

        if max_buckets is not None and processed_now >= max_buckets:
            return {
                "state": "INCOMPLETE",
                "signal_set_id": expected_config["signal_set_id"],
                "processed_buckets_this_call": processed_now,
                "completed_buckets": len(
                    list((output_root / "code_buckets").glob("code_bucket=*"))
                ),
                "elapsed_seconds": time.perf_counter() - started,
                "workers_requested": workers,
                "workers_used": workers_used,
                "worker_processes": len(worker_pids),
            }

        checkpoints: list[dict[str, Any]] = []
        for bucket in sorted(buckets):
            directory = output_root / "code_buckets" / f"code_bucket={bucket:03d}"
            checkpoints.append(_load_checkpoint(output_root, directory))
        stats = _sum_stats(
            [item for checkpoint in checkpoints for item in checkpoint["code_stats"]]
        )
        artifacts = sorted(
            [item for checkpoint in checkpoints for item in checkpoint["artifacts"]],
            key=lambda item: (item["dataset"], item["path"]),
        )
        registry_path = output_root / "model_registry.json"
        manifest = {
            "manifest_version": 1,
            "schema_version": SIGNAL_FACTS_SCHEMA_VERSION,
            "state": "COMPLETE",
            "run_id": expected_config["run_id"],
            "signal_set_id": expected_config["signal_set_id"],
            "snapshot": {
                "snapshot_id": snapshot_manifest["snapshot_id"],
                "manifest_sha256": snapshot_manifest["manifest_sha256"],
                "as_of_trade_date": snapshot_manifest.get("spec", {}).get("as_of"),
                "source_database": snapshot_manifest.get("source", {}).get("database"),
                "source_access_mode": snapshot_manifest.get("source", {}).get(
                    "access_mode"
                ),
            },
            "code": {
                "git_commit": _git_commit(Path(__file__).resolve().parents[3]),
                "adapter_files": identity["adapter_files"],
                "native_module_sha256": identity["native_module_sha256"],
            },
            "engine": identity,
            "config": {
                "build_config_sha256": "sha256:"
                + _sha256_bytes(canonical_json_bytes(expected_config)),
                "model_registry_sha256": model_registry_sha256(),
                "wave_opt": effective_spec.options.wave_opt,
                "stretch_opt": effective_spec.options.stretch_opt,
                "ext_opt": effective_spec.options.trend_opt,
                "trend_opt_alias": effective_spec.options.trend_opt,
                "switch_opt": 0,
            },
            "model_registry": {
                "registry_version": MODEL_REGISTRY_VERSION,
                "path": "model_registry.json",
                "file_sha256": _sha256_file(registry_path),
                "logical_sha256": model_registry_sha256(),
                "s0002_entrypoint3_legacy_semantic": S0002_LEGACY_ENTRYPOINT3_SEMANTIC,
                "ranking_dimension": "primary_trigger_semantic",
            },
            "causality": {
                "route": CAUSAL_ROUTE,
                "full_history_trade_source": False,
                "prefix_scope": "FROM_FIRST_ELIGIBLE_SNAPSHOT_BAR_THROUGH_AS_OF",
                "reveal_rule": "reveal_date_equals_adjacent_prefix_as_of_date",
            },
            "trigger_provenance": {
                "native_base_masks": "UNMODIFIED_SHARED_PREDICATES",
                "completed_mask_formula": (
                    "direction_base_trigger_mask OR synthetic_primary_mask"
                ),
                "s0002_entrypoint3": {
                    "base_bit_present": "ENGULFING",
                    "base_bit_absent": S0002_LEGACY_ENTRYPOINT3_SEMANTIC,
                    "base_bit_absent_primary_source": "SYNTHETIC_PRIMARY_MASK",
                },
            },
            "partitioning": {
                "columns": ["code_bucket", "reveal_year"],
                "bucket_count": effective_spec.bucket_count,
                "atomic_checkpoint_unit": "code_bucket",
                "resume_rule": "verify immutable checkpoint and artifacts before skip",
            },
            "completed_buckets": sorted(buckets),
            "counts": {
                **stats,
                "signal_revisions": sum(
                    int(item["rows"])
                    for item in artifacts
                    if item["dataset"] == "signal_revisions"
                ),
                "tradable_signal_facts": sum(
                    int(item["rows"])
                    for item in artifacts
                    if item["dataset"] == "tradable_signal_facts"
                ),
            },
            "quality": {
                "quality_mask_extensions": {
                    "S0002_LEGACY_ENTRYPOINT3_OVERLOAD": SIGNAL_QUALITY_S0002_LEGACY_OVERLOAD,
                    "UNEXPECTED_SYNTHETIC_PRIMARY": SIGNAL_QUALITY_UNEXPECTED_SYNTHETIC_PRIMARY,
                },
                "unknown_scalar_protocol_count": 0,
                "known_semantic_overloads": [
                    {
                        "model_code": "S0002",
                        "primary_entrypoint": 3,
                        "resolved_dimension": "primary_trigger_semantic",
                        "legacy_semantic": S0002_LEGACY_ENTRYPOINT3_SEMANTIC,
                    }
                ],
            },
            "artifacts": artifacts,
        }
        _write_json(output_root / "manifest.json", manifest)
        _atomic_write_bytes(
            output_root / "manifest.sha256",
            (_sha256_file(output_root / "manifest.json") + "  manifest.json\n").encode(
                "ascii"
            ),
        )
    finally:
        _release_build_lock(lock_path, lock_descriptor)

    result = verify_signal_facts(output_root)
    result["idempotent_reuse"] = False
    result["processed_buckets_this_call"] = processed_now
    result["elapsed_seconds"] = time.perf_counter() - started
    result["workers_requested"] = workers
    result["workers_used"] = workers_used
    result["worker_processes"] = len(worker_pids)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--snapshot-dir", required=True)
    build.add_argument("--output-dir", required=True)
    build.add_argument("--run-id", required=True)
    build.add_argument("--code", action="append", default=[])
    build.add_argument("--bucket-count", type=int, default=DEFAULT_BUCKET_COUNT)
    build.add_argument("--resume", action="store_true")
    build.add_argument("--max-buckets", type=int)
    build.add_argument("--workers", type=int, default=1)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--output-dir", required=True)
    verify.add_argument("--shallow", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "verify":
        result = verify_signal_facts(args.output_dir, deep=not args.shallow)
    else:
        result = build_signal_facts(
            args.snapshot_dir,
            args.output_dir,
            spec=SignalBuildSpec(
                run_id=args.run_id,
                codes=tuple(args.code),
                bucket_count=args.bucket_count,
            ),
            resume=args.resume,
            max_buckets=args.max_buckets,
            workers=args.workers,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
