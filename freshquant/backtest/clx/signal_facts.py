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
import stat
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
    S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC,
    S0002_STRONG_SWING_ENTRYPOINT4_SOURCE,
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
SIGNAL_QUALITY_S0002_STRONG_SWING_OVERLOAD = 1 << 18
BUILD_LOCK_SCHEMA_VERSION = "clx-signal-build-lock-v1"
SEMANTIC_DERIVATION_SCHEMA_VERSION = "clx-semantic-derivation-v1"
SEMANTIC_DERIVATION_MIGRATION_ID = "s0002-entrypoint4-strong-swing-v1"
SEMANTIC_RECOVERY_FROZEN_CONFIG_NAMES = ("split_plan", "ranking", "portfolio")
SEMANTIC_FINALIZATION_MARKER_SCHEMA_VERSION = "clx-signal-finalization-marker-v1"
SEMANTIC_FINALIZATION_EVIDENCE_SCHEMA_VERSION = "clx-v2-causal-signal-finalization-v1"
SEMANTIC_DERIVATION_ALLOWED_FIELDS = (
    "run_id",
    "signal_set_id",
    "engine_id",
    "signal_fact_id",
    "primary_trigger_semantic",
    "primary_trigger_semantic_source",
    "primary_entrypoint_overloaded",
    "previous_primary_trigger_semantic",
    "quality_mask",
)

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


@dataclass(frozen=True, slots=True)
class SemanticDerivationSpec:
    """Pinned input identity for the sole S0002/e4 semantic recovery."""

    run_id: str
    migration_id: str
    expected_source_signal_set_id: str
    expected_source_manifest_sha256: str
    expected_source_evidence_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not _ULID_RE.fullmatch(self.run_id):
            raise ValueError("run_id must be a canonical uppercase 26-character ULID")
        if self.migration_id != SEMANTIC_DERIVATION_MIGRATION_ID:
            raise ValueError("unsupported semantic derivation migration_id")
        if not isinstance(self.expected_source_signal_set_id, str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.expected_source_signal_set_id
        ):
            raise ValueError("expected_source_signal_set_id must be a SHA-256 ID")
        for name in (
            "expected_source_manifest_sha256",
            "expected_source_evidence_sha256",
        ):
            value = getattr(self, name).removeprefix("sha256:")
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(f"{name} must be a SHA-256 digest")
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class SemanticRecoveryRunSpec:
    """Identity supplied while preparing a new sealed semantic-recovery run."""

    derivation: SemanticDerivationSpec
    engine_image_id: str
    image_source_commit: str
    image_host_source_commit: str
    engine_module_sha256: str
    online_module_sha256: str

    def __post_init__(self) -> None:
        if not self.engine_image_id:
            raise ValueError("engine_image_id must be non-empty")
        for name in (
            "image_source_commit",
            "image_host_source_commit",
        ):
            if not re.fullmatch(r"[0-9a-f]{40}", getattr(self, name)):
                raise ValueError(f"{name} must be a lowercase Git commit")
        for name in ("engine_module_sha256", "online_module_sha256"):
            value = getattr(self, name).removeprefix("sha256:")
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
            object.__setattr__(self, name, value)


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

    win_dll = getattr(ctypes, "WinDLL")
    set_last_error = getattr(ctypes, "set_last_error")
    get_last_error = getattr(ctypes, "get_last_error")

    kernel32 = win_dll("kernel32", use_last_error=True)
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

    set_last_error(0)
    handle = open_process(process_query_limited_information, False, pid)
    if not handle:
        error = get_last_error()
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
            "s0002_entrypoint4_overload": S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC,
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
    overloaded = model_id == 2 and entrypoint in (3, 4)
    if model_id == 2 and entrypoint == 4:
        semantic = S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC
        source = S0002_STRONG_SWING_ENTRYPOINT4_SOURCE
    elif model_id == 2 and entrypoint == 3 and base_mask & primary_bit:
        semantic = "ENGULFING"
        source = "SHARED_BASE_PREDICATE"
    elif model_id == 2 and entrypoint == 3:
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
            "s0002_strong_swing_entrypoint4": 0,
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
                if (
                    semantics["primary_trigger_semantic"]
                    == S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC
                ):
                    signal_quality |= SIGNAL_QUALITY_S0002_STRONG_SWING_OVERLOAD
                primary_bit = 1 << (semantics["primary_entrypoint"] - 1)
                if (
                    semantics["primary_entrypoint"] != 1
                    and new_synthetic & primary_bit
                    and semantics["primary_trigger_semantic"]
                    not in {
                        S0002_LEGACY_ENTRYPOINT3_SEMANTIC,
                        S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC,
                    }
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
        "s0002_strong_swing_entrypoint4": semantic_counts[
            S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC
        ],
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
        "s0002_strong_swing_entrypoint4": sum(
            int(item["s0002_strong_swing_entrypoint4"]) for item in code_stats
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


def _semantic_profile(registry: Mapping[str, Any]) -> str:
    """Recognize the sealed semantic contract carried by an artifact registry."""

    overrides = registry.get("semantic_overrides")
    if not isinstance(overrides, list):
        raise SignalFactsError("model registry semantic overrides are missing")
    has_entrypoint3 = any(
        isinstance(item, Mapping)
        and item.get("model_id") == 2
        and item.get("entrypoint") == 3
        and item.get("legacy_semantic") == S0002_LEGACY_ENTRYPOINT3_SEMANTIC
        for item in overrides
    )
    if not has_entrypoint3:
        raise SignalFactsError("S0002 legacy semantic disclosure is missing")

    registry_version = registry.get("registry_version")
    entrypoint4 = [
        item
        for item in overrides
        if isinstance(item, Mapping)
        and item.get("model_id") == 2
        and item.get("entrypoint") == 4
    ]
    if registry_version == "clx-18-v1":
        if entrypoint4:
            raise SignalFactsError("legacy registry unexpectedly declares S0002/e4")
        return "S0002_E4_LEGACY_SHARED"
    if registry_version == MODEL_REGISTRY_VERSION:
        if len(entrypoint4) != 1:
            raise SignalFactsError("S0002 strong-swing semantic disclosure is missing")
        entry = entrypoint4[0]
        if (
            entry.get("model_primary_semantic")
            != S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC
            or entry.get("ranking_dimension") != "primary_trigger_semantic"
        ):
            raise SignalFactsError("S0002 strong-swing semantic disclosure is invalid")
        return "S0002_E4_STRONG_SWING"
    raise SignalFactsError(f"unsupported model registry version: {registry_version!r}")


def _expected_s0002_semantics(
    *,
    entrypoint: int,
    base_mask: int,
    primary_bit: int,
    profile: str,
) -> tuple[str, str | None, bool | None]:
    """Resolve the versioned S0002 overloads for deep artifact verification."""

    if entrypoint == 3:
        if base_mask & primary_bit:
            return "ENGULFING", "SHARED_BASE_PREDICATE", True
        return S0002_LEGACY_ENTRYPOINT3_SEMANTIC, "S0002_MODEL_LEGACY_FALLBACK", True
    if entrypoint == 4:
        if profile == "S0002_E4_LEGACY_SHARED":
            return (
                "STRONG_FRACTAL",
                (
                    "SHARED_BASE_PREDICATE"
                    if base_mask & primary_bit
                    else "MODEL_PRIMARY_SYNTHETIC"
                ),
                False,
            )
        if profile == "S0002_E4_STRONG_SWING":
            return (
                S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC,
                S0002_STRONG_SWING_ENTRYPOINT4_SOURCE,
                True,
            )
    raise SignalFactsError("invalid S0002 semantic verification request")


def _deep_verify_bucket(
    output_root: Path, checkpoint: Mapping[str, Any], *, semantic_profile: str
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
        if row["expected_model_id"] == 2 and row["primary_entrypoint"] in (3, 4):
            expected_semantic, expected_source, expected_overloaded = (
                _expected_s0002_semantics(
                    entrypoint=int(row["primary_entrypoint"]),
                    base_mask=int(base),
                    primary_bit=primary_bit,
                    profile=semantic_profile,
                )
            )
            if row["primary_trigger_semantic"] != expected_semantic:
                raise SignalFactsError("S0002 primary semantic is misclassified")
            if row["primary_trigger_semantic_source"] != expected_source:
                raise SignalFactsError("S0002 primary semantic source is misclassified")
            if row["primary_entrypoint_overloaded"] is not expected_overloaded:
                raise SignalFactsError("S0002 overload marker is misclassified")
            quality_mask = int(row["quality_mask"])
            legacy_quality = bool(quality_mask & SIGNAL_QUALITY_S0002_LEGACY_OVERLOAD)
            unexpected = bool(
                quality_mask & SIGNAL_QUALITY_UNEXPECTED_SYNTHETIC_PRIMARY
            )
            swing_quality = bool(
                quality_mask & SIGNAL_QUALITY_S0002_STRONG_SWING_OVERLOAD
            )
            if row["primary_entrypoint"] == 3:
                expected_legacy_quality = (
                    expected_semantic == S0002_LEGACY_ENTRYPOINT3_SEMANTIC
                )
                if (
                    legacy_quality != expected_legacy_quality
                    or unexpected
                    or swing_quality
                ):
                    raise SignalFactsError("S0002/e3 quality flags are invalid")
            else:
                has_synthetic_primary = bool(synthetic & primary_bit)
                if semantic_profile == "S0002_E4_LEGACY_SHARED":
                    if (
                        legacy_quality
                        or unexpected is not has_synthetic_primary
                        or swing_quality
                    ):
                        raise SignalFactsError(
                            "legacy S0002/e4 quality flags are invalid"
                        )
                elif legacy_quality or unexpected or not swing_quality:
                    raise SignalFactsError("S0002/e4 quality flags are invalid")
        if old_raw:
            previous = decode_signal(
                int(old_raw), expected_model_id=int(row["expected_model_id"])
            )
            assert previous is not None
            if row["expected_model_id"] == 2 and previous.primary_entrypoint in (3, 4):
                previous_bit = 1 << (previous.primary_entrypoint - 1)
                previous_semantic, _, _ = _expected_s0002_semantics(
                    entrypoint=previous.primary_entrypoint,
                    base_mask=int(row["previous_direction_base_trigger_mask"]),
                    primary_bit=previous_bit,
                    profile=semantic_profile,
                )
                if row["previous_primary_trigger_semantic"] != previous_semantic:
                    raise SignalFactsError(
                        "previous S0002 primary semantic is misclassified"
                    )

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

    partitioning = manifest.get("partitioning")
    bucket_count = (
        partitioning.get("bucket_count") if isinstance(partitioning, Mapping) else None
    )
    completed_buckets = manifest.get("completed_buckets")
    if (
        isinstance(bucket_count, bool)
        or not isinstance(bucket_count, int)
        or bucket_count < 1
        or not isinstance(completed_buckets, list)
        or any(
            isinstance(bucket, bool) or not isinstance(bucket, int)
            for bucket in completed_buckets
        )
        or completed_buckets != sorted(set(completed_buckets))
        or any(bucket < 0 or bucket >= bucket_count for bucket in completed_buckets)
    ):
        raise SignalFactsError("signal manifest completed bucket coverage is invalid")

    registry_path = output_root / manifest["model_registry"]["path"]
    if _sha256_file(registry_path) != manifest["model_registry"]["file_sha256"]:
        raise SignalFactsError("model registry file hash mismatch")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    actual_registry_digest = "sha256:" + _sha256_bytes(canonical_json_bytes(registry))
    if actual_registry_digest != manifest["model_registry"]["logical_sha256"]:
        raise SignalFactsError("model registry logical hash mismatch")
    semantic_profile = _semantic_profile(registry)

    totals = {"revisions": 0, "tradable": 0}
    artifacts: list[dict[str, Any]] = []
    for bucket in completed_buckets:
        bucket_dir = output_root / "code_buckets" / f"code_bucket={bucket:03d}"
        checkpoint = _load_checkpoint(output_root, bucket_dir)
        if checkpoint["signal_set_id"] != manifest["signal_set_id"]:
            raise SignalFactsError("checkpoint signal_set_id mismatch")
        artifacts.extend(checkpoint["artifacts"])
        if deep:
            counts = _deep_verify_bucket(
                output_root, checkpoint, semantic_profile=semantic_profile
            )
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
        "completed_buckets": len(completed_buckets),
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
    if max_buckets is not None and (
        not isinstance(max_buckets, int)
        or isinstance(max_buckets, bool)
        or max_buckets < 1
    ):
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
                "s0002_entrypoint4_strong_swing_semantic": (
                    S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC
                ),
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
                "s0002_entrypoint4": {
                    "base_bit_semantic": "STRONG_FRACTAL",
                    "model_primary_semantic": S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC,
                    "model_primary_source": S0002_STRONG_SWING_ENTRYPOINT4_SOURCE,
                    "base_bit_absent_primary_source": "SYNTHETIC_PRIMARY_MASK",
                    "base_bit_present": "CONCURRENT_SHARED_WAVE_FACT",
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
                    "S0002_STRONG_SWING_ENTRYPOINT4_OVERLOAD": (
                        SIGNAL_QUALITY_S0002_STRONG_SWING_OVERLOAD
                    ),
                    "UNEXPECTED_SYNTHETIC_PRIMARY": SIGNAL_QUALITY_UNEXPECTED_SYNTHETIC_PRIMARY,
                },
                "unknown_scalar_protocol_count": 0,
                "known_semantic_overloads": [
                    {
                        "model_code": "S0002",
                        "primary_entrypoint": 3,
                        "resolved_dimension": "primary_trigger_semantic",
                        "legacy_semantic": S0002_LEGACY_ENTRYPOINT3_SEMANTIC,
                    },
                    {
                        "model_code": "S0002",
                        "primary_entrypoint": 4,
                        "resolved_dimension": "primary_trigger_semantic",
                        "model_primary_semantic": (
                            S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC
                        ),
                    },
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


def _load_hashed_json(path: Path) -> tuple[dict[str, Any], str]:
    """Read a JSON artifact with its sibling ``.sha256`` sidecar."""

    if not path.is_file():
        raise SignalFactsError(f"required JSON artifact is missing: {path}")
    sidecar = path.with_suffix(".sha256")
    recorded = _read_sha256_sidecar(sidecar, path.name)
    if _sha256_file(path) != recorded:
        raise SignalFactsError(f"JSON artifact SHA-256 mismatch: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SignalFactsError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise SignalFactsError(f"JSON artifact must be an object: {path}")
    return value, recorded


def _assert_no_symlinks(root: Path, *, label: str) -> None:
    if root.is_symlink():
        raise SignalFactsError(f"{label} must not be a symbolic link")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise SignalFactsError(f"{label} contains a symbolic link: {path}")


def _assert_readonly_tree(root: Path, *, label: str) -> None:
    """Require the finalized source facts tree to be immutable on Linux."""

    _assert_no_symlinks(root, label=label)
    if os.name == "nt":
        return
    for path in (root, *root.rglob("*")):
        mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
        if mode & 0o222:
            raise SignalFactsError(f"{label} is writable: {path}")


def _assert_immutable_regular_file(path: Path, *, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise SignalFactsError(f"{label} must be an immutable regular file: {path}")
    if (
        os.name != "nt"
        and stat.S_IMODE(path.stat(follow_symlinks=False).st_mode) & 0o222
    ):
        raise SignalFactsError(f"{label} is writable: {path}")


def _path_contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _resolve_semantic_recovery_path(
    value: str | Path,
    *,
    label: str,
    require_exists: bool,
) -> Path:
    """Resolve an input path only after every supplied component rejects symlinks."""

    path = Path(value)
    lexical = path if path.is_absolute() else Path.cwd() / path
    current = Path(lexical.anchor)
    for component in lexical.parts[1:]:
        if component in ("", "."):
            continue
        if component == "..":
            current = current.parent
            continue
        current /= component
        if current.is_symlink():
            raise SignalFactsError(
                f"{label} must not contain a symbolic link: {current}"
            )
    try:
        return lexical.resolve(strict=require_exists)
    except FileNotFoundError as exc:
        raise SignalFactsError(f"{label} is missing: {lexical}") from exc
    except OSError as exc:
        raise SignalFactsError(f"{label} cannot be resolved: {lexical}") from exc


def _validate_semantic_recovery_frozen_configs(
    contract: Mapping[str, Any],
    *,
    label: str,
    expected_configs: Mapping[str, Any] | None = None,
    materialized_root: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Validate the exact frozen configuration inputs inherited by a child run."""

    frozen_configs = contract.get("frozen_configs")
    if not isinstance(frozen_configs, Mapping):
        raise SignalFactsError(f"{label} frozen config contract is missing")
    validated: dict[str, dict[str, Any]] = {}
    for name in SEMANTIC_RECOVERY_FROZEN_CONFIG_NAMES:
        item = frozen_configs.get(name)
        if not isinstance(item, Mapping):
            raise SignalFactsError(f"{label} {name} config is missing")
        normalized = dict(item)
        path_value = normalized.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise SignalFactsError(f"{label} {name} config path is invalid")
        path = Path(path_value)
        digest = str(normalized.get("sha256", "")).removeprefix("sha256:")
        if not path.is_absolute() or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SignalFactsError(f"{label} {name} config is invalid")

        expected: Mapping[str, Any] | None = None
        if expected_configs is not None:
            candidate = expected_configs.get(name)
            if not isinstance(candidate, Mapping):
                raise SignalFactsError(f"{label} {name} config lineage differs")
            expected = candidate
            expected_path = expected.get("path")
            expected_digest = str(expected.get("sha256", "")).removeprefix("sha256:")
            source_digest = str(normalized.get("source_sha256", "")).removeprefix(
                "sha256:"
            )
            if (
                normalized.get("source_path") != expected_path
                or source_digest != expected_digest
                or digest != expected_digest
                or materialized_root is None
            ):
                raise SignalFactsError(f"{label} {name} config lineage differs")

        resolved_path = _resolve_semantic_recovery_path(
            path, label=f"{label} {name} config", require_exists=True
        )
        if not resolved_path.is_file():
            raise SignalFactsError(f"{label} {name} config is invalid")
        if _sha256_file(resolved_path) != digest:
            raise SignalFactsError(f"{label} {name} config SHA-256 differs")

        if expected is not None:
            expected_path = _resolve_semantic_recovery_path(
                materialized_root / f"{name}.json",
                label=f"{label} {name} materialized config",
                require_exists=False,
            )
            if resolved_path != expected_path:
                raise SignalFactsError(f"{label} {name} config lineage differs")
            sidecar = resolved_path.with_name(f"{resolved_path.name}.sha256")
            try:
                recorded_digest = _read_sha256_sidecar(sidecar, resolved_path.name)
            except SignalFactsError as exc:
                raise SignalFactsError(
                    f"{label} {name} config materialization sidecar differs"
                ) from exc
            if recorded_digest != digest:
                raise SignalFactsError(
                    f"{label} {name} config materialization sidecar differs"
                )
            _assert_immutable_regular_file(
                resolved_path, label=f"{label} {name} materialized config"
            )
            _assert_immutable_regular_file(
                sidecar, label=f"{label} {name} materialized config sidecar"
            )
        validated[name] = normalized
    return validated


def _seal_bytes_once(path: Path, value: bytes, *, label: str) -> None:
    """Publish a content-addressed immutable file without replacing prior data."""

    if path.is_symlink():
        raise SignalFactsError(f"{label} must not be a symbolic link: {path}")
    if path.exists():
        if not path.is_file() or path.read_bytes() != value:
            raise SignalFactsError(f"immutable semantic recovery conflict: {path}")
    else:
        _atomic_write_bytes(path, value)
    if os.name != "nt":
        path.chmod(0o444)


def _materialized_semantic_recovery_configs(
    source_configs: Mapping[str, Mapping[str, Any]], target_root: Path
) -> dict[str, dict[str, Any]]:
    """Describe child-local frozen copies while retaining the sealed source lineage."""

    configs_root = target_root / "frozen-configs"
    return {
        name: {
            "path": str(configs_root / f"{name}.json"),
            "sha256": str(source_configs[name]["sha256"]).removeprefix("sha256:"),
            "source_path": source_configs[name]["path"],
            "source_sha256": str(source_configs[name]["sha256"]).removeprefix(
                "sha256:"
            ),
        }
        for name in SEMANTIC_RECOVERY_FROZEN_CONFIG_NAMES
    }


def _materialize_semantic_recovery_configs(
    source_configs: Mapping[str, Mapping[str, Any]], target_root: Path
) -> None:
    """Copy frozen inputs into the child run, rejecting source or target link paths."""

    configs_root = _resolve_semantic_recovery_path(
        target_root / "frozen-configs",
        label="semantic recovery target frozen config root",
        require_exists=False,
    )
    configs_root.mkdir(parents=True, exist_ok=True)
    _assert_no_symlinks(
        configs_root, label="semantic recovery target frozen config root"
    )
    for name in SEMANTIC_RECOVERY_FROZEN_CONFIG_NAMES:
        source_item = source_configs[name]
        source_path = _resolve_semantic_recovery_path(
            str(source_item["path"]),
            label=f"semantic recovery source {name} config",
            require_exists=True,
        )
        if not source_path.is_file():
            raise SignalFactsError(f"semantic recovery source {name} config is invalid")
        source_bytes = source_path.read_bytes()
        source_digest = _sha256_bytes(source_bytes)
        expected_digest = str(source_item["sha256"]).removeprefix("sha256:")
        if source_digest != expected_digest:
            raise SignalFactsError(
                f"semantic recovery source {name} config SHA-256 differs"
            )
        target_path = configs_root / f"{name}.json"
        _seal_bytes_once(
            target_path,
            source_bytes,
            label=f"semantic recovery target {name} config",
        )
        _seal_bytes_once(
            target_path.with_name(f"{target_path.name}.sha256"),
            f"{source_digest}  {target_path.name}\n".encode("ascii"),
            label=f"semantic recovery target {name} config sidecar",
        )


def _validate_recovery_roots(source_root: Path, target_root: Path) -> None:
    if (
        source_root == target_root
        or _path_contains(source_root, target_root)
        or _path_contains(target_root, source_root)
    ):
        raise SignalFactsError("semantic recovery source and target roots overlap")
    if target_root.exists() and target_root.is_symlink():
        raise SignalFactsError(
            "semantic recovery target root must not be a symbolic link"
        )
    if target_root.exists():
        _assert_no_symlinks(target_root, label="semantic recovery target root")
    target_parent = target_root.parent
    if not target_parent.exists():
        target_parent.mkdir(parents=True)
    if source_root.stat().st_dev != target_parent.stat().st_dev:
        raise SignalFactsError(
            "semantic recovery source and target must share an atomic filesystem"
        )


def _source_build_signal_set_id(build_config: Mapping[str, Any]) -> str:
    keys = (
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
    if any(key not in build_config for key in keys):
        raise SignalFactsError("source signal build config is incomplete")
    return "sha256:" + _sha256_bytes(
        canonical_json_bytes({key: build_config[key] for key in keys})
    )


def _load_semantic_recovery_source(
    source_run_root: str | Path, *, spec: SemanticDerivationSpec
) -> dict[str, Any]:
    """Verify the sealed v1 facts and contract accepted by this migration."""

    source_root = _resolve_semantic_recovery_path(
        source_run_root,
        label="semantic recovery source root",
        require_exists=True,
    )
    facts_root = source_root / "facts"
    if not facts_root.is_dir():
        raise SignalFactsError("semantic recovery source has no facts directory")
    _assert_readonly_tree(facts_root, label="semantic recovery source facts")
    manifest, manifest_sha256 = _load_hashed_json(facts_root / "manifest.json")
    if manifest_sha256 != spec.expected_source_manifest_sha256:
        raise SignalFactsError("semantic recovery source manifest SHA-256 differs")
    if manifest.get("signal_set_id") != spec.expected_source_signal_set_id:
        raise SignalFactsError("semantic recovery source signal_set_id differs")
    if manifest.get("state") != "COMPLETE":
        raise SignalFactsError("semantic recovery source facts are not complete")
    source_verify = verify_signal_facts(facts_root, deep=True)
    if source_verify.get("signal_set_id") != spec.expected_source_signal_set_id:
        raise SignalFactsError("source deep verification identity differs")

    registry_path = facts_root / str(manifest.get("model_registry", {}).get("path", ""))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if _semantic_profile(registry) != "S0002_E4_LEGACY_SHARED":
        raise SignalFactsError(
            "semantic recovery only accepts the sealed S0002/e4 v1 contract"
        )
    registry_sha256 = "sha256:" + _sha256_bytes(canonical_json_bytes(registry))
    if registry_sha256 != manifest.get("model_registry", {}).get("logical_sha256"):
        raise SignalFactsError("semantic recovery source registry identity differs")

    build_config_path = facts_root / "build_config.json"
    try:
        build_config = json.loads(build_config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SignalFactsError(
            "semantic recovery source build config is invalid"
        ) from exc
    if _source_build_signal_set_id(build_config) != manifest["signal_set_id"]:
        raise SignalFactsError("semantic recovery source build config identity differs")
    if build_config.get("model_registry_sha256") != registry_sha256:
        raise SignalFactsError("semantic recovery source registry/config mismatch")
    if build_config.get("run_id") != manifest.get("run_id"):
        raise SignalFactsError("semantic recovery source run_id mismatch")

    contract_path = _resolve_semantic_recovery_path(
        source_root / "run-contract.json",
        label="semantic recovery source run contract",
        require_exists=True,
    )
    contract_sidecar = _resolve_semantic_recovery_path(
        source_root / "run-contract.sha256",
        label="semantic recovery source run contract sidecar",
        require_exists=True,
    )
    _assert_immutable_regular_file(
        contract_path, label="semantic recovery source run contract"
    )
    _assert_immutable_regular_file(
        contract_sidecar, label="semantic recovery source run contract sidecar"
    )
    contract, contract_sha256 = _load_hashed_json(contract_path)
    if contract.get("run_id") != manifest.get("run_id"):
        raise SignalFactsError("semantic recovery source run contract run_id differs")
    if contract.get("holdout_state") != "LOCKED":
        raise SignalFactsError("semantic recovery source has left the HOLDOUT lock")
    contract_snapshot = contract.get("snapshot", {})
    manifest_snapshot = manifest.get("snapshot", {})
    if contract_snapshot.get("snapshot_id") != manifest_snapshot.get(
        "snapshot_id"
    ) or str(contract_snapshot.get("manifest_sha256", "")).removeprefix(
        "sha256:"
    ) != str(
        manifest_snapshot.get("manifest_sha256", "")
    ).removeprefix(
        "sha256:"
    ):
        raise SignalFactsError("semantic recovery source snapshot contract differs")
    contract_engine = contract.get("engine", {})
    native_sha256 = manifest.get("engine", {}).get("native_module_sha256")
    if not isinstance(native_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", native_sha256
    ):
        raise SignalFactsError(
            "semantic recovery source native engine digest is invalid"
        )
    if (
        str(contract_engine.get("module_sha256", "")).removeprefix("sha256:")
        != native_sha256
    ):
        raise SignalFactsError("semantic recovery source native engine differs")
    frozen_configs = _validate_semantic_recovery_frozen_configs(
        contract, label="semantic recovery source"
    )

    finalized_path = _resolve_semantic_recovery_path(
        source_root / ".runner" / "finalized",
        label="semantic recovery source finalization marker",
        require_exists=True,
    )
    _assert_immutable_regular_file(
        finalized_path, label="semantic recovery source finalization marker"
    )
    try:
        finalized = json.loads(finalized_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SignalFactsError(
            "semantic recovery source finalization marker is invalid"
        ) from exc
    if not isinstance(finalized, Mapping):
        raise SignalFactsError(
            "semantic recovery source finalization marker is invalid"
        )
    if (
        finalized.get("schema_version") != SEMANTIC_FINALIZATION_MARKER_SCHEMA_VERSION
        or finalized.get("status") != "FINALIZED"
    ):
        raise SignalFactsError(
            "semantic recovery source finalization marker is not finalized"
        )
    if (
        finalized.get("run_id") != manifest.get("run_id")
        or finalized.get("signal_set_id") != manifest.get("signal_set_id")
        or str(finalized.get("manifest_sha256", "")).removeprefix("sha256:")
        != manifest_sha256
        or str(finalized.get("run_contract_sha256", "")).removeprefix("sha256:")
        != contract_sha256
    ):
        raise SignalFactsError("semantic recovery source finalization identity differs")
    evidence_path_raw = finalized.get("evidence_path")
    if not isinstance(evidence_path_raw, str) or not evidence_path_raw:
        raise SignalFactsError("semantic recovery source evidence path is missing")
    if not Path(evidence_path_raw).is_absolute():
        raise SignalFactsError("semantic recovery source evidence path is invalid")
    evidence_path = _resolve_semantic_recovery_path(
        evidence_path_raw,
        label="semantic recovery source finalization evidence",
        require_exists=True,
    )
    evidence_sha256 = str(finalized.get("evidence_sha256", "")).removeprefix("sha256:")
    if evidence_sha256 != spec.expected_source_evidence_sha256:
        raise SignalFactsError("semantic recovery source evidence SHA-256 differs")
    _assert_immutable_regular_file(
        evidence_path, label="semantic recovery source finalization evidence"
    )
    evidence_sidecar = evidence_path.with_name(f"{evidence_path.name}.sha256")
    _assert_immutable_regular_file(
        evidence_sidecar, label="semantic recovery source finalization evidence sidecar"
    )
    if _sha256_file(evidence_path) != evidence_sha256:
        raise SignalFactsError("semantic recovery source evidence content differs")
    if _read_sha256_sidecar(evidence_sidecar, evidence_path.name) != evidence_sha256:
        raise SignalFactsError("semantic recovery source evidence sidecar differs")
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SignalFactsError("semantic recovery source evidence is invalid") from exc
    if not isinstance(evidence, Mapping):
        raise SignalFactsError("semantic recovery source evidence is invalid")
    if (
        evidence.get("schema_version") != SEMANTIC_FINALIZATION_EVIDENCE_SCHEMA_VERSION
        or evidence.get("status") != "verified"
    ):
        raise SignalFactsError("semantic recovery source evidence is not verified")
    if (
        evidence.get("run_id") != manifest.get("run_id")
        or evidence.get("signal_set_id") != manifest.get("signal_set_id")
        or str(evidence.get("manifest_sha256", "")).removeprefix("sha256:")
        != manifest_sha256
        or str(evidence.get("run_contract_sha256", "")).removeprefix("sha256:")
        != contract_sha256
    ):
        raise SignalFactsError("semantic recovery source evidence identity differs")
    if (
        evidence.get("snapshot_id") != manifest.get("snapshot", {}).get("snapshot_id")
        or evidence.get("counts") != manifest.get("counts")
        or evidence.get("completed_buckets")
        != len(manifest.get("completed_buckets", ()))
        or evidence.get("deep_verify") != source_verify
    ):
        raise SignalFactsError(
            "semantic recovery source evidence deep verification differs"
        )

    return {
        "root": source_root,
        "facts_root": facts_root,
        "manifest": manifest,
        "manifest_sha256": manifest_sha256,
        "registry": registry,
        "registry_sha256": registry_sha256,
        "build_config": build_config,
        "contract": contract,
        "contract_sha256": contract_sha256,
        "frozen_configs": frozen_configs,
        "finalized": finalized,
        "evidence": evidence,
        "evidence_sha256": evidence_sha256,
    }


def _sealed_json_once(path: Path, value: Mapping[str, Any]) -> str:
    """Publish a deterministic JSON/sidecar pair without replacing an existing one."""

    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    digest = _sha256_bytes(payload)
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise SignalFactsError(f"immutable semantic recovery conflict: {path}")
    else:
        _atomic_write_bytes(path, payload)
    sidecar = path.with_suffix(".sha256")
    sidecar_payload = f"{digest}  {path.name}\n".encode("ascii")
    if sidecar.exists():
        if not sidecar.is_file() or sidecar.read_bytes() != sidecar_payload:
            raise SignalFactsError(
                f"immutable semantic recovery sidecar conflict: {sidecar}"
            )
    else:
        _atomic_write_bytes(sidecar, sidecar_payload)
    if os.name != "nt":
        path.chmod(0o444)
        sidecar.chmod(0o444)
    return digest


def prepare_semantic_recovery_run(
    source_run_root: str | Path,
    target_run_root: str | Path,
    *,
    spec: SemanticRecoveryRunSpec,
) -> dict[str, Any]:
    """Create the immutable child-run contract required before derivation."""

    source = _load_semantic_recovery_source(source_run_root, spec=spec.derivation)
    if spec.derivation.run_id == source["manifest"]["run_id"]:
        raise SignalFactsError("semantic recovery child run_id must differ from source")
    target_root = _resolve_semantic_recovery_path(
        target_run_root,
        label="semantic recovery target root",
        require_exists=False,
    )
    _validate_recovery_roots(source["root"], target_root)
    target_root.mkdir(parents=True, exist_ok=True)
    prepare_lock_path = target_root / ".prepare.lock"
    prepare_lock = _acquire_build_lock(
        prepare_lock_path, f"semantic-recovery-prepare:{spec.derivation.run_id}"
    )
    try:
        entries = [path for path in target_root.iterdir() if path != prepare_lock_path]
        if entries:
            contract_path = target_root / "run-contract.json"
            if not contract_path.is_file():
                raise SignalFactsError("semantic recovery target root is not empty")

        source_manifest = source["manifest"]
        source_config = source["build_config"]
        if (
            spec.engine_module_sha256
            != source_manifest["engine"]["native_module_sha256"]
        ):
            raise SignalFactsError(
                "semantic recovery target native engine differs from source"
            )
        copied_configs = _materialized_semantic_recovery_configs(
            source["frozen_configs"], target_root
        )

        target_contract = {
            "schema_version": "clx-semantic-recovery-run-contract-v1",
            "run_id": spec.derivation.run_id,
            "holdout_state": "LOCKED",
            "snapshot": dict(source_manifest["snapshot"]),
            "engine": {
                "image_id": spec.engine_image_id,
                "module_sha256": spec.engine_module_sha256,
                "online_module_sha256": spec.online_module_sha256,
                "wave_opt": source_config["engine_identity"]["options"]["wave_opt"],
                "stretch_opt": source_config["engine_identity"]["options"][
                    "stretch_opt"
                ],
                "trend_opt": source_config["engine_identity"]["options"]["ext_opt"],
                "image_identity": {
                    "id": spec.engine_image_id,
                    "source_commit": spec.image_source_commit,
                    "host_source_commit": spec.image_host_source_commit,
                    "native_module_sha256": spec.engine_module_sha256,
                },
            },
            "source": {
                "image_source_commit": spec.image_source_commit,
                "image_host_source_commit": spec.image_host_source_commit,
            },
            "frozen_configs": copied_configs,
            "recovery": {
                "schema_version": SEMANTIC_DERIVATION_SCHEMA_VERSION,
                "migration_id": spec.derivation.migration_id,
                "source_run_id": source_manifest["run_id"],
                "source_signal_set_id": source_manifest["signal_set_id"],
                "source_manifest_sha256": source["manifest_sha256"],
                "source_evidence_sha256": source["evidence_sha256"],
                "source_run_contract_sha256": source["contract_sha256"],
                "source_native_module_sha256": source_manifest["engine"][
                    "native_module_sha256"
                ],
                "target_model_registry_sha256": model_registry_sha256(),
            },
        }
        contract_path = target_root / "run-contract.json"
        contract_sha256 = _sealed_json_once(contract_path, target_contract)
        _materialize_semantic_recovery_configs(source["frozen_configs"], target_root)
        runner_root = target_root / ".runner"
        runner_root.mkdir(exist_ok=True)
        return {
            "status": "prepared",
            "run_id": spec.derivation.run_id,
            "target_run_contract_sha256": contract_sha256,
            "source_signal_set_id": source_manifest["signal_set_id"],
            "source_manifest_sha256": source["manifest_sha256"],
            "source_evidence_sha256": source["evidence_sha256"],
        }
    finally:
        _release_build_lock(prepare_lock_path, prepare_lock)


def _load_semantic_recovery_target_contract(
    target_root: Path,
    *,
    source: Mapping[str, Any],
    spec: SemanticDerivationSpec,
) -> tuple[dict[str, Any], str]:
    contract, contract_sha256 = _load_hashed_json(target_root / "run-contract.json")
    recovery = contract.get("recovery")
    if not isinstance(recovery, Mapping):
        raise SignalFactsError(
            "semantic recovery target contract has no recovery lineage"
        )
    expected_recovery = {
        "schema_version": SEMANTIC_DERIVATION_SCHEMA_VERSION,
        "migration_id": spec.migration_id,
        "source_run_id": source["manifest"]["run_id"],
        "source_signal_set_id": source["manifest"]["signal_set_id"],
        "source_manifest_sha256": source["manifest_sha256"],
        "source_evidence_sha256": source["evidence_sha256"],
        "source_run_contract_sha256": source["contract_sha256"],
        "source_native_module_sha256": source["manifest"]["engine"][
            "native_module_sha256"
        ],
        "target_model_registry_sha256": model_registry_sha256(),
    }
    if any(recovery.get(key) != value for key, value in expected_recovery.items()):
        raise SignalFactsError("semantic recovery target contract lineage differs")
    if contract.get("run_id") != spec.run_id:
        raise SignalFactsError("semantic recovery target contract run_id differs")
    if spec.run_id == source["manifest"]["run_id"]:
        raise SignalFactsError("semantic recovery child run_id must differ from source")
    if contract.get("holdout_state") != "LOCKED":
        raise SignalFactsError(
            "semantic recovery target contract has left the HOLDOUT lock"
        )
    if contract.get("snapshot") != source["manifest"].get("snapshot"):
        raise SignalFactsError("semantic recovery target contract snapshot differs")
    engine = contract.get("engine")
    if not isinstance(engine, Mapping):
        raise SignalFactsError("semantic recovery target contract engine is missing")
    native_sha256 = source["manifest"]["engine"]["native_module_sha256"]
    if str(engine.get("module_sha256", "")).removeprefix("sha256:") != native_sha256:
        raise SignalFactsError(
            "semantic recovery target contract native engine differs"
        )
    if not engine.get("image_id") or not re.fullmatch(
        r"[0-9a-f]{64}",
        str(engine.get("online_module_sha256", "")).removeprefix("sha256:"),
    ):
        raise SignalFactsError(
            "semantic recovery target contract engine identity is invalid"
        )
    _validate_semantic_recovery_frozen_configs(
        contract,
        label="semantic recovery target",
        expected_configs=source["frozen_configs"],
        materialized_root=target_root / "frozen-configs",
    )
    if os.name != "nt":
        for path in (
            target_root / "run-contract.json",
            target_root / "run-contract.sha256",
        ):
            if stat.S_IMODE(path.stat().st_mode) & 0o222:
                raise SignalFactsError(
                    "semantic recovery target contract must be immutable"
                )
    return contract, contract_sha256


def _semantic_derivation_config(
    *,
    source: Mapping[str, Any],
    target_contract_sha256: str,
    spec: SemanticDerivationSpec,
    engine_identity: Mapping[str, Any],
) -> dict[str, Any]:
    source_manifest = source["manifest"]
    source_config = source["build_config"]
    payload: dict[str, Any] = {
        "schema_version": SIGNAL_FACTS_SCHEMA_VERSION,
        "derivation_schema_version": SEMANTIC_DERIVATION_SCHEMA_VERSION,
        "migration_id": spec.migration_id,
        "source": {
            "run_id": source_manifest["run_id"],
            "signal_set_id": source_manifest["signal_set_id"],
            "manifest_sha256": source["manifest_sha256"],
            "evidence_sha256": source["evidence_sha256"],
            "run_contract_sha256": source["contract_sha256"],
            "build_config_sha256": "sha256:"
            + _sha256_bytes(canonical_json_bytes(source_config)),
            "model_registry_sha256": source["registry_sha256"],
        },
        "target_run_contract_sha256": target_contract_sha256,
        "snapshot_id": source_manifest["snapshot"]["snapshot_id"],
        "snapshot_manifest_sha256": source_manifest["snapshot"]["manifest_sha256"],
        "selected_codes": list(source_config["selected_codes"]),
        "bucket_count": source_config["bucket_count"],
        "causal_route": source_config["causal_route"],
        "engine_input_price_domain": source_config["engine_input_price_domain"],
        "engine_identity": dict(engine_identity),
        "model_registry_sha256": model_registry_sha256(),
        "semantic_contract": {
            "primary_dimension": "primary_trigger_semantic",
            "s0002_entrypoint3_overload": S0002_LEGACY_ENTRYPOINT3_SEMANTIC,
            "s0002_entrypoint4_overload": S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC,
            "completed_mask_formula": (
                "direction_base_trigger_mask OR synthetic_primary_mask"
            ),
        },
        "native_prefix_calls_this_run": 0,
    }
    identity_payload = {
        key: payload[key]
        for key in (
            "schema_version",
            "derivation_schema_version",
            "migration_id",
            "source",
            "target_run_contract_sha256",
            "snapshot_id",
            "snapshot_manifest_sha256",
            "selected_codes",
            "bucket_count",
            "causal_route",
            "engine_input_price_domain",
            "engine_identity",
            "model_registry_sha256",
            "semantic_contract",
            "native_prefix_calls_this_run",
        )
    }
    payload["signal_set_id"] = "sha256:" + _sha256_bytes(
        canonical_json_bytes(identity_payload)
    )
    payload["run_id"] = spec.run_id
    return payload


def _is_s0002_entrypoint(
    row: Mapping[str, Any], *, raw_field: str, entrypoint: int
) -> bool:
    raw = int(row[raw_field])
    if raw == 0 or int(row["expected_model_id"]) != 2:
        return False
    decoded = decode_signal(raw, expected_model_id=2)
    return decoded is not None and decoded.primary_entrypoint == entrypoint


def _validate_legacy_row_for_derivation(row: Mapping[str, Any]) -> None:
    """Reject every source semantic/quality state outside the one known bug."""

    current_raw = int(row["current_raw_signal"])
    if current_raw:
        entrypoint = int(row["primary_entrypoint"])
        primary_bit = 1 << (entrypoint - 1)
        base = int(row["direction_base_trigger_mask"])
        synthetic = int(row["synthetic_primary_mask"])
        if _is_s0002_entrypoint(row, raw_field="current_raw_signal", entrypoint=4):
            expected_semantic, expected_source, expected_overloaded = (
                _expected_s0002_semantics(
                    entrypoint=4,
                    base_mask=base,
                    primary_bit=primary_bit,
                    profile="S0002_E4_LEGACY_SHARED",
                )
            )
            if (
                row["primary_trigger_semantic"] != expected_semantic
                or row["primary_trigger_semantic_source"] != expected_source
                or row["primary_entrypoint_overloaded"] is not expected_overloaded
            ):
                raise SignalFactsError("semantic recovery source S0002/e4 row differs")
            unexpected = bool(
                int(row["quality_mask"]) & SIGNAL_QUALITY_UNEXPECTED_SYNTHETIC_PRIMARY
            )
            legacy_quality = bool(
                int(row["quality_mask"]) & SIGNAL_QUALITY_S0002_LEGACY_OVERLOAD
            )
            if legacy_quality or unexpected is not bool(synthetic & primary_bit):
                raise SignalFactsError(
                    "semantic recovery source S0002/e4 quality differs"
                )
            if int(row["quality_mask"]) & SIGNAL_QUALITY_S0002_STRONG_SWING_OVERLOAD:
                raise SignalFactsError(
                    "semantic recovery source has a future S0002/e4 flag"
                )
        elif int(row["quality_mask"]) & SIGNAL_QUALITY_UNEXPECTED_SYNTHETIC_PRIMARY:
            raise SignalFactsError(
                "semantic recovery source has another unexpected synthetic primary"
            )

    previous_raw = int(row["previous_raw_signal"])
    if previous_raw and _is_s0002_entrypoint(
        row, raw_field="previous_raw_signal", entrypoint=4
    ):
        previous_bit = 1 << 3
        expected_semantic, _, _ = _expected_s0002_semantics(
            entrypoint=4,
            base_mask=int(row["previous_direction_base_trigger_mask"]),
            primary_bit=previous_bit,
            profile="S0002_E4_LEGACY_SHARED",
        )
        if row["previous_primary_trigger_semantic"] != expected_semantic:
            raise SignalFactsError("semantic recovery source previous S0002/e4 differs")


def _derive_semantic_frame(
    frame: pl.DataFrame, *, build_config: Mapping[str, Any]
) -> tuple[pl.DataFrame, dict[str, int]]:
    if frame.schema != _FACT_SCHEMA:
        raise SignalFactsError("semantic recovery source fact schema differs")
    rewritten_rows: list[dict[str, Any]] = []
    counters = {
        "rewritten_current_rows": 0,
        "rewritten_previous_rows": 0,
        "e4_synthetic_rows": 0,
    }
    for original in frame.iter_rows(named=True):
        row = dict(original)
        _validate_legacy_row_for_derivation(row)
        row["run_id"] = build_config["run_id"]
        row["signal_set_id"] = build_config["signal_set_id"]
        row["engine_id"] = build_config["engine_identity"]["engine_id"]
        if _is_s0002_entrypoint(row, raw_field="current_raw_signal", entrypoint=4):
            row["primary_trigger_semantic"] = S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC
            row["primary_trigger_semantic_source"] = (
                S0002_STRONG_SWING_ENTRYPOINT4_SOURCE
            )
            row["primary_entrypoint_overloaded"] = True
            row["quality_mask"] = (
                int(row["quality_mask"]) & ~SIGNAL_QUALITY_UNEXPECTED_SYNTHETIC_PRIMARY
            ) | SIGNAL_QUALITY_S0002_STRONG_SWING_OVERLOAD
            counters["rewritten_current_rows"] += 1
            if int(row["synthetic_primary_mask"]) & (1 << 3):
                counters["e4_synthetic_rows"] += 1
        if _is_s0002_entrypoint(row, raw_field="previous_raw_signal", entrypoint=4):
            row["previous_primary_trigger_semantic"] = (
                S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC
            )
            counters["rewritten_previous_rows"] += 1
        row["signal_fact_id"] = _fact_id(row)
        for key, value in original.items():
            if key not in SEMANTIC_DERIVATION_ALLOWED_FIELDS and row[key] != value:
                raise SignalFactsError(
                    "semantic derivation attempted an out-of-scope change"
                )
        rewritten_rows.append(row)
    return _fact_frame(rewritten_rows), counters


def _load_semantic_recovery_source_bucket(
    source: Mapping[str, Any], *, bucket: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_root = Path(source["facts_root"])
    source_bucket = source_root / "code_buckets" / f"code_bucket={bucket:03d}"
    source_checkpoint = _load_checkpoint(source_root, source_bucket)
    if (
        source_checkpoint.get("schema_version") != SIGNAL_FACTS_SCHEMA_VERSION
        or source_checkpoint.get("state") != "COMPLETE"
        or source_checkpoint.get("code_bucket") != bucket
        or source_checkpoint.get("snapshot_id")
        != source["manifest"]["snapshot"]["snapshot_id"]
    ):
        raise SignalFactsError("semantic recovery source checkpoint lineage differs")
    if source_checkpoint.get("signal_set_id") != source["manifest"]["signal_set_id"]:
        raise SignalFactsError("semantic recovery source checkpoint identity differs")
    source_artifacts = sorted(
        source_checkpoint["artifacts"], key=lambda item: (item["dataset"], item["path"])
    )
    return source_checkpoint, source_artifacts


def _derive_semantic_bucket(
    *,
    source: Mapping[str, Any],
    staging: Path,
    bucket: int,
    build_config: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, int]]:
    source_root = Path(source["facts_root"])
    source_checkpoint, source_artifacts = _load_semantic_recovery_source_bucket(
        source, bucket=bucket
    )
    revision_artifacts = [
        item for item in source_artifacts if item["dataset"] == "signal_revisions"
    ]
    source_prefix = f"code_buckets/code_bucket={bucket:03d}/"
    artifacts: list[dict[str, Any]] = []
    counters = {
        "rewritten_current_rows": 0,
        "rewritten_previous_rows": 0,
        "e4_synthetic_rows": 0,
    }
    strong_swing_by_code: Counter[str] = Counter()
    for source_meta in revision_artifacts:
        source_path = source_root / str(source_meta["path"])
        frame = _verify_artifact_path(source_path, source_meta)
        transformed, frame_counters = _derive_semantic_frame(
            frame, build_config=build_config
        )
        for name in counters:
            counters[name] += frame_counters[name]
        for code, rows in (
            transformed.filter(
                (pl.col("expected_model_id") == 2)
                & (pl.col("primary_entrypoint") == 4)
                & pl.col("actionable")
            )
            .group_by("code")
            .len()
            .iter_rows()
        ):
            strong_swing_by_code[str(code)] += int(rows)
        logical = str(source_meta["path"])
        if not logical.startswith(source_prefix):
            raise SignalFactsError(
                "semantic recovery source artifact escaped its bucket"
            )
        relative = logical.removeprefix(source_prefix)
        artifacts.append(
            _write_artifact(
                transformed,
                staging / relative,
                logical,
                "signal_revisions",
            )
        )
        tradable = transformed.filter(pl.col("actionable"))
        if tradable.height:
            tradable_relative = relative.replace(
                "signal_revisions/", "tradable_signal_facts/", 1
            )
            tradable_logical = source_prefix + tradable_relative
            artifacts.append(
                _write_artifact(
                    tradable,
                    staging / tradable_relative,
                    tradable_logical,
                    "tradable_signal_facts",
                )
            )

    source_code_stats = source_checkpoint.get("code_stats")
    if not isinstance(source_code_stats, list):
        raise SignalFactsError(
            "semantic recovery source checkpoint code stats are missing"
        )
    code_stats: list[dict[str, Any]] = []
    for raw_stats in source_code_stats:
        if not isinstance(raw_stats, Mapping) or not isinstance(
            raw_stats.get("code"), str
        ):
            raise SignalFactsError("semantic recovery source code stats are invalid")
        stats = dict(raw_stats)
        code = str(stats["code"])
        stats["s0002_strong_swing_entrypoint4"] = strong_swing_by_code[code]
        stats["unexpected_synthetic_primary"] = 0
        code_stats.append(stats)
    if sorted(item["code"] for item in code_stats) != sorted(
        source_checkpoint["codes"]
    ):
        raise SignalFactsError("semantic recovery source code stats membership differs")

    derivation = {
        "schema_version": SEMANTIC_DERIVATION_SCHEMA_VERSION,
        "migration_id": SEMANTIC_DERIVATION_MIGRATION_ID,
        "source_run_id": source["manifest"]["run_id"],
        "source_signal_set_id": source["manifest"]["signal_set_id"],
        "source_manifest_sha256": source["manifest_sha256"],
        "source_evidence_sha256": source["evidence_sha256"],
        "source_run_contract_sha256": source["contract_sha256"],
        "target_run_contract_sha256": build_config["target_run_contract_sha256"],
        "source_checkpoint_sha256": source_checkpoint["checkpoint_sha256"],
        "source_artifacts_sha256": "sha256:"
        + _sha256_bytes(canonical_json_bytes(source_artifacts)),
        "allowed_row_fields": list(SEMANTIC_DERIVATION_ALLOWED_FIELDS),
        "rewritten_current_rows": counters["rewritten_current_rows"],
        "rewritten_previous_rows": counters["rewritten_previous_rows"],
        "e4_synthetic_rows": counters["e4_synthetic_rows"],
        "native_prefix_calls_this_run": 0,
    }
    checkpoint_payload = {
        "schema_version": SIGNAL_FACTS_SCHEMA_VERSION,
        "state": "COMPLETE",
        "snapshot_id": source["manifest"]["snapshot"]["snapshot_id"],
        "signal_set_id": build_config["signal_set_id"],
        "code_bucket": bucket,
        "codes": list(source_checkpoint["codes"]),
        "inputs": list(source_checkpoint["inputs"]),
        "artifacts": sorted(
            artifacts, key=lambda item: (item["dataset"], item["path"])
        ),
        "stats": _sum_stats(code_stats),
        "code_stats": code_stats,
        "derivation": derivation,
    }
    checkpoint = _with_content_hash(checkpoint_payload, "checkpoint_sha256")
    _write_json(staging / "checkpoint.json", checkpoint)
    return checkpoint, counters


def _verify_existing_semantic_recovery_bucket(
    *,
    source: Mapping[str, Any],
    facts_root: Path,
    bucket: int,
    build_config: Mapping[str, Any],
    migration_id: str,
) -> dict[str, Any]:
    """Recompute an existing partial bucket before allowing resume to skip it."""

    final_dir = facts_root / "code_buckets" / f"code_bucket={bucket:03d}"
    target_checkpoint = _load_checkpoint(facts_root, final_dir)
    source_checkpoint, source_artifacts = _load_semantic_recovery_source_bucket(
        source, bucket=bucket
    )
    expected_source_artifacts_sha256 = "sha256:" + _sha256_bytes(
        canonical_json_bytes(source_artifacts)
    )
    derivation = target_checkpoint.get("derivation")
    if not isinstance(derivation, Mapping) or (
        derivation.get("schema_version") != SEMANTIC_DERIVATION_SCHEMA_VERSION
        or derivation.get("migration_id") != migration_id
        or derivation.get("source_checkpoint_sha256")
        != source_checkpoint["checkpoint_sha256"]
        or derivation.get("source_artifacts_sha256") != expected_source_artifacts_sha256
        or derivation.get("native_prefix_calls_this_run") != 0
    ):
        raise SignalFactsError("semantic recovery checkpoint lineage differs")
    for key, expected in (
        ("schema_version", SIGNAL_FACTS_SCHEMA_VERSION),
        ("state", "COMPLETE"),
        ("snapshot_id", source["manifest"]["snapshot"]["snapshot_id"]),
        ("signal_set_id", build_config["signal_set_id"]),
        ("code_bucket", bucket),
        ("codes", list(source_checkpoint["codes"])),
        ("inputs", list(source_checkpoint["inputs"])),
    ):
        if target_checkpoint.get(key) != expected:
            raise SignalFactsError(f"semantic recovery checkpoint {key} differs")

    target_artifacts: dict[tuple[str, str], Mapping[str, Any]] = {}
    for meta in target_checkpoint["artifacts"]:
        key = (str(meta.get("dataset", "")), str(meta.get("path", "")))
        if key in target_artifacts:
            raise SignalFactsError(
                "semantic recovery checkpoint has duplicate artifacts"
            )
        target_artifacts[key] = meta

    source_root = Path(source["facts_root"])
    source_prefix = f"code_buckets/code_bucket={bucket:03d}/"
    expected_target_keys: set[tuple[str, str]] = set()
    counters = {
        "rewritten_current_rows": 0,
        "rewritten_previous_rows": 0,
        "e4_synthetic_rows": 0,
    }
    strong_swing_by_code: Counter[str] = Counter()
    for source_meta in source_artifacts:
        if source_meta["dataset"] != "signal_revisions":
            continue
        logical = str(source_meta["path"])
        if not logical.startswith(source_prefix):
            raise SignalFactsError(
                "semantic recovery source artifact escaped its bucket"
            )
        source_frame = _verify_artifact_path(source_root / logical, source_meta)
        transformed, frame_counters = _derive_semantic_frame(
            source_frame, build_config=build_config
        )
        for name in counters:
            counters[name] += frame_counters[name]
        for code, rows in (
            transformed.filter(
                (pl.col("expected_model_id") == 2)
                & (pl.col("primary_entrypoint") == 4)
                & pl.col("actionable")
            )
            .group_by("code")
            .len()
            .iter_rows()
        ):
            strong_swing_by_code[str(code)] += int(rows)

        revision_key = ("signal_revisions", logical)
        revision_meta = target_artifacts.get(revision_key)
        if revision_meta is None:
            raise SignalFactsError(
                "semantic recovery checkpoint revision artifact is missing"
            )
        target_revision = _verify_artifact_path(facts_root / logical, revision_meta)
        if not target_revision.equals(transformed):
            raise SignalFactsError(
                "semantic recovery checkpoint revision artifact differs"
            )
        expected_target_keys.add(revision_key)

        tradable = transformed.filter(pl.col("actionable"))
        if tradable.height:
            relative = logical.removeprefix(source_prefix)
            tradable_logical = source_prefix + relative.replace(
                "signal_revisions/", "tradable_signal_facts/", 1
            )
            tradable_key = ("tradable_signal_facts", tradable_logical)
            tradable_meta = target_artifacts.get(tradable_key)
            if tradable_meta is None:
                raise SignalFactsError(
                    "semantic recovery checkpoint tradable artifact is missing"
                )
            target_tradable = _verify_artifact_path(
                facts_root / tradable_logical, tradable_meta
            )
            if not target_tradable.equals(tradable):
                raise SignalFactsError(
                    "semantic recovery checkpoint tradable artifact differs"
                )
            expected_target_keys.add(tradable_key)
    if set(target_artifacts) != expected_target_keys:
        raise SignalFactsError("semantic recovery checkpoint artifact set differs")

    source_code_stats = source_checkpoint.get("code_stats")
    if not isinstance(source_code_stats, list):
        raise SignalFactsError("semantic recovery source code stats are missing")
    expected_code_stats: list[dict[str, Any]] = []
    for raw_stats in source_code_stats:
        if not isinstance(raw_stats, Mapping) or not isinstance(
            raw_stats.get("code"), str
        ):
            raise SignalFactsError("semantic recovery source code stats are invalid")
        stats = dict(raw_stats)
        code = str(stats["code"])
        stats["s0002_strong_swing_entrypoint4"] = strong_swing_by_code[code]
        stats["unexpected_synthetic_primary"] = 0
        expected_code_stats.append(stats)
    if target_checkpoint.get("code_stats") != expected_code_stats:
        raise SignalFactsError("semantic recovery checkpoint code stats differ")
    if target_checkpoint.get("stats") != _sum_stats(expected_code_stats):
        raise SignalFactsError("semantic recovery checkpoint stats differ")
    expected_derivation = {
        "schema_version": SEMANTIC_DERIVATION_SCHEMA_VERSION,
        "migration_id": migration_id,
        "source_run_id": source["manifest"]["run_id"],
        "source_signal_set_id": source["manifest"]["signal_set_id"],
        "source_manifest_sha256": source["manifest_sha256"],
        "source_evidence_sha256": source["evidence_sha256"],
        "source_run_contract_sha256": source["contract_sha256"],
        "target_run_contract_sha256": build_config["target_run_contract_sha256"],
        "source_checkpoint_sha256": source_checkpoint["checkpoint_sha256"],
        "source_artifacts_sha256": expected_source_artifacts_sha256,
        "allowed_row_fields": list(SEMANTIC_DERIVATION_ALLOWED_FIELDS),
        "rewritten_current_rows": counters["rewritten_current_rows"],
        "rewritten_previous_rows": counters["rewritten_previous_rows"],
        "e4_synthetic_rows": counters["e4_synthetic_rows"],
        "native_prefix_calls_this_run": 0,
    }
    if dict(derivation) != expected_derivation:
        raise SignalFactsError("semantic recovery checkpoint lineage differs")
    return target_checkpoint


def _semantic_derivation_manifest(
    *,
    source: Mapping[str, Any],
    build_config: Mapping[str, Any],
    target_contract_sha256: str,
    checkpoints: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    stats = _sum_stats(
        [item for checkpoint in checkpoints for item in checkpoint["code_stats"]]
    )
    artifacts = sorted(
        [item for checkpoint in checkpoints for item in checkpoint["artifacts"]],
        key=lambda item: (item["dataset"], item["path"]),
    )
    counters = {
        name: sum(int(checkpoint["derivation"][name]) for checkpoint in checkpoints)
        for name in (
            "rewritten_current_rows",
            "rewritten_previous_rows",
            "e4_synthetic_rows",
        )
    }
    if not counters["rewritten_current_rows"]:
        raise SignalFactsError(
            "semantic recovery source has no S0002/e4 rows to repair"
        )
    if stats["unexpected_synthetic_primary"] != 0:
        raise SignalFactsError("semantic recovery left an unexpected synthetic primary")
    source_manifest = source["manifest"]
    source_config = source["build_config"]
    identity = build_config["engine_identity"]
    return {
        "manifest_version": 2,
        "schema_version": SIGNAL_FACTS_SCHEMA_VERSION,
        "state": "COMPLETE",
        "run_id": build_config["run_id"],
        "signal_set_id": build_config["signal_set_id"],
        "snapshot": dict(source_manifest["snapshot"]),
        "code": {
            "git_commit": _git_commit(Path(__file__).resolve().parents[3]),
            "adapter_files": identity["adapter_files"],
            "native_module_sha256": identity["native_module_sha256"],
        },
        "engine": identity,
        "config": {
            "build_config_sha256": "sha256:"
            + _sha256_bytes(canonical_json_bytes(build_config)),
            "model_registry_sha256": model_registry_sha256(),
            "wave_opt": identity["options"]["wave_opt"],
            "stretch_opt": identity["options"]["stretch_opt"],
            "ext_opt": identity["options"]["ext_opt"],
            "trend_opt_alias": identity["options"]["trend_opt_alias"],
            "switch_opt": identity["options"]["switch_opt"],
        },
        "model_registry": {
            "registry_version": MODEL_REGISTRY_VERSION,
            "path": "model_registry.json",
            "file_sha256": None,
            "logical_sha256": model_registry_sha256(),
            "s0002_entrypoint3_legacy_semantic": S0002_LEGACY_ENTRYPOINT3_SEMANTIC,
            "s0002_entrypoint4_strong_swing_semantic": (
                S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC
            ),
            "ranking_dimension": "primary_trigger_semantic",
        },
        "causality": {
            "route": source_manifest["causality"]["route"],
            "full_history_trade_source": False,
            "prefix_scope": source_manifest["causality"]["prefix_scope"],
            "reveal_rule": source_manifest["causality"]["reveal_rule"],
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
            "s0002_entrypoint4": {
                "base_bit_semantic": "STRONG_FRACTAL",
                "model_primary_semantic": S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC,
                "model_primary_source": S0002_STRONG_SWING_ENTRYPOINT4_SOURCE,
                "base_bit_absent_primary_source": "SYNTHETIC_PRIMARY_MASK",
                "base_bit_present": "CONCURRENT_SHARED_WAVE_FACT",
            },
        },
        "partitioning": {
            "columns": ["code_bucket", "reveal_year"],
            "bucket_count": source_config["bucket_count"],
            "atomic_checkpoint_unit": "code_bucket",
            "resume_rule": "verify immutable checkpoint and artifacts before skip",
        },
        "completed_buckets": sorted(
            int(checkpoint["code_bucket"]) for checkpoint in checkpoints
        ),
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
                "S0002_STRONG_SWING_ENTRYPOINT4_OVERLOAD": (
                    SIGNAL_QUALITY_S0002_STRONG_SWING_OVERLOAD
                ),
                "UNEXPECTED_SYNTHETIC_PRIMARY": SIGNAL_QUALITY_UNEXPECTED_SYNTHETIC_PRIMARY,
            },
            "unknown_scalar_protocol_count": 0,
            "known_semantic_overloads": [
                {
                    "model_code": "S0002",
                    "primary_entrypoint": 3,
                    "resolved_dimension": "primary_trigger_semantic",
                    "legacy_semantic": S0002_LEGACY_ENTRYPOINT3_SEMANTIC,
                },
                {
                    "model_code": "S0002",
                    "primary_entrypoint": 4,
                    "resolved_dimension": "primary_trigger_semantic",
                    "model_primary_semantic": (S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC),
                },
            ],
        },
        "derivation": {
            "schema_version": SEMANTIC_DERIVATION_SCHEMA_VERSION,
            "migration_id": SEMANTIC_DERIVATION_MIGRATION_ID,
            "source_run_id": source_manifest["run_id"],
            "source_signal_set_id": source_manifest["signal_set_id"],
            "source_manifest_sha256": source["manifest_sha256"],
            "source_evidence_sha256": source["evidence_sha256"],
            "source_run_contract_sha256": source["contract_sha256"],
            "target_run_contract_sha256": target_contract_sha256,
            "allowed_row_fields": list(SEMANTIC_DERIVATION_ALLOWED_FIELDS),
            "native_prefix_calls_this_run": 0,
            "source_prefix_calls": source_manifest["counts"]["prefix_calls"],
            **counters,
        },
        "artifacts": artifacts,
    }


def _semantic_derivation_complete_marker(
    *,
    source: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    target_contract_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": "clx-semantic-derivation-complete-v1",
        "status": "COMPLETE",
        "run_id": manifest["run_id"],
        "signal_set_id": manifest["signal_set_id"],
        "manifest_sha256": manifest_sha256,
        "target_run_contract_sha256": target_contract_sha256,
        "migration_id": SEMANTIC_DERIVATION_MIGRATION_ID,
        "source_run_id": source["manifest"]["run_id"],
        "source_signal_set_id": source["manifest"]["signal_set_id"],
        "source_manifest_sha256": source["manifest_sha256"],
        "source_evidence_sha256": source["evidence_sha256"],
        "native_prefix_calls_this_run": 0,
    }


def _write_semantic_derivation_complete_marker(
    target_root: Path, value: Mapping[str, Any]
) -> None:
    path = target_root / ".runner" / "complete"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise SignalFactsError("semantic derivation complete marker differs")
        return
    _atomic_write_bytes(path, payload)
    if os.name != "nt":
        path.chmod(0o444)


def derive_semantic_signal_facts(
    source_run_root: str | Path,
    target_run_root: str | Path,
    *,
    spec: SemanticDerivationSpec,
    engine: Any | None = None,
    resume: bool = False,
    max_buckets: int | None = None,
) -> dict[str, Any]:
    """Derive a new S0002/e4-correct facts tree without native prefix replay."""

    started = time.perf_counter()
    if max_buckets is not None and (isinstance(max_buckets, bool) or max_buckets < 1):
        raise ValueError("max_buckets must be a positive integer")
    source = _load_semantic_recovery_source(source_run_root, spec=spec)
    target_root = _resolve_semantic_recovery_path(
        target_run_root,
        label="semantic recovery target root",
        require_exists=False,
    )
    _validate_recovery_roots(Path(source["root"]), target_root)
    if not target_root.is_dir():
        raise SignalFactsError("semantic recovery target run has not been prepared")
    target_contract, target_contract_sha256 = _load_semantic_recovery_target_contract(
        target_root, source=source, spec=spec
    )
    source_options = source["build_config"]["engine_identity"]["options"]
    options = ClxEngineOptions(
        wave_opt=int(source_options["wave_opt"]),
        stretch_opt=int(source_options["stretch_opt"]),
        trend_opt=int(source_options["ext_opt"]),
    )
    effective_engine = engine if engine is not None else FqCopilotClxEngine()
    identity = _engine_identity(effective_engine, options)
    source_native_sha256 = source["manifest"]["engine"]["native_module_sha256"]
    if identity["native_module_sha256"] != source_native_sha256:
        raise SignalFactsError(
            "semantic recovery runtime native engine differs from source"
        )
    if (
        str(target_contract["engine"]["module_sha256"]).removeprefix("sha256:")
        != identity["native_module_sha256"]
    ):
        raise SignalFactsError(
            "semantic recovery target contract engine differs from runtime"
        )
    build_config = _semantic_derivation_config(
        source=source,
        target_contract_sha256=target_contract_sha256,
        spec=spec,
        engine_identity=identity,
    )
    source_buckets = [int(value) for value in source["manifest"]["completed_buckets"]]
    source_bucket_count = int(source["build_config"]["bucket_count"])
    source_codes = source["build_config"].get("selected_codes")
    if not isinstance(source_codes, list) or any(
        not isinstance(code, str) for code in source_codes
    ):
        raise SignalFactsError("semantic recovery source selected code set is invalid")
    expected_source_buckets = sorted(
        {code_bucket(code, source_bucket_count) for code in source_codes}
    )
    if source_buckets != expected_source_buckets:
        raise SignalFactsError("semantic recovery source bucket coverage is invalid")
    facts_root = target_root / "facts"
    if not facts_root.exists():
        bootstrap = target_root / f".facts.bootstrap-{os.getpid()}"
        if bootstrap.exists():
            shutil.rmtree(bootstrap)
        bootstrap.mkdir(parents=True)
        _write_json(bootstrap / "model_registry.json", get_model_registry())
        _write_json(bootstrap / "build_config.json", build_config)
        os.replace(bootstrap, facts_root)
        _fsync_directory(target_root)
    if facts_root.is_symlink():
        raise SignalFactsError(
            "semantic recovery target facts must not be a symbolic link"
        )
    config_path = facts_root / "build_config.json"
    try:
        actual_config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SignalFactsError(
            "semantic recovery target build config is invalid"
        ) from exc
    if actual_config != build_config:
        raise SignalFactsError("semantic recovery target belongs to another derivation")
    registry_path = facts_root / "model_registry.json"
    if (
        not registry_path.is_file()
        or json.loads(registry_path.read_text(encoding="utf-8")) != get_model_registry()
    ):
        raise SignalFactsError("semantic recovery target registry differs")

    manifest_path = facts_root / "manifest.json"
    manifest_sidecar = facts_root / "manifest.sha256"
    manifest_exists = manifest_path.exists() or manifest_path.is_symlink()
    sidecar_exists = manifest_sidecar.exists() or manifest_sidecar.is_symlink()
    recover_unpublished_manifest = manifest_exists and not sidecar_exists
    if manifest_exists or sidecar_exists:
        if manifest_path.is_symlink() or manifest_sidecar.is_symlink():
            raise SignalFactsError(
                "semantic recovery target manifest must not be a symbolic link"
            )
        if manifest_exists and sidecar_exists:
            if not manifest_path.is_file() or not manifest_sidecar.is_file():
                raise SignalFactsError(
                    "semantic recovery target manifest publication is incomplete"
                )
            result = verify_signal_facts(facts_root, deep=True)
            manifest, manifest_sha256 = _load_hashed_json(manifest_path)
            derivation = manifest.get("derivation")
            expected_manifest_lineage = {
                "migration_id": spec.migration_id,
                "source_run_id": source["manifest"]["run_id"],
                "source_signal_set_id": source["manifest"]["signal_set_id"],
                "source_manifest_sha256": source["manifest_sha256"],
                "source_evidence_sha256": source["evidence_sha256"],
                "source_run_contract_sha256": source["contract_sha256"],
                "target_run_contract_sha256": target_contract_sha256,
                "native_prefix_calls_this_run": 0,
                "allowed_row_fields": list(SEMANTIC_DERIVATION_ALLOWED_FIELDS),
            }
            if not isinstance(derivation, Mapping) or (
                derivation.get("schema_version") != SEMANTIC_DERIVATION_SCHEMA_VERSION
                or any(
                    derivation.get(key) != value
                    for key, value in expected_manifest_lineage.items()
                )
            ):
                raise SignalFactsError(
                    "semantic recovery target manifest lineage differs"
                )
            for bucket in sorted(source_buckets):
                _verify_existing_semantic_recovery_bucket(
                    source=source,
                    facts_root=facts_root,
                    bucket=bucket,
                    build_config=build_config,
                    migration_id=spec.migration_id,
                )
            _write_semantic_derivation_complete_marker(
                target_root,
                _semantic_derivation_complete_marker(
                    source=source,
                    manifest=manifest,
                    manifest_sha256=manifest_sha256,
                    target_contract_sha256=target_contract_sha256,
                ),
            )
            result.update(
                {
                    "idempotent_reuse": True,
                    "native_prefix_calls_this_run": 0,
                    "elapsed_seconds": time.perf_counter() - started,
                }
            )
            return result
        if not recover_unpublished_manifest or not manifest_path.is_file():
            raise SignalFactsError(
                "semantic recovery target manifest publication is incomplete"
            )
        if not resume:
            raise SignalFactsError(
                "unpublished semantic recovery manifest requires resume=True"
            )
    if not resume and any((facts_root / "code_buckets").glob("code_bucket=*")):
        raise SignalFactsError("incomplete semantic recovery requires resume=True")

    lock_path = facts_root / ".build.lock"
    lock_descriptor = _acquire_build_lock(lock_path, build_config["signal_set_id"])
    processed_now = 0
    try:
        pending: list[int] = []
        for bucket in sorted(source_buckets):
            final_dir = facts_root / "code_buckets" / f"code_bucket={bucket:03d}"
            if final_dir.exists():
                _verify_existing_semantic_recovery_bucket(
                    source=source,
                    facts_root=facts_root,
                    bucket=bucket,
                    build_config=build_config,
                    migration_id=spec.migration_id,
                )
                continue
            pending.append(bucket)
        if recover_unpublished_manifest and pending:
            raise SignalFactsError(
                "unpublished semantic recovery manifest has incomplete buckets"
            )
        scheduled = pending[:max_buckets] if max_buckets is not None else pending
        for bucket in scheduled:
            staging = _prepare_bucket_staging(facts_root, bucket)
            try:
                checkpoint, _ = _derive_semantic_bucket(
                    source=source,
                    staging=staging,
                    bucket=bucket,
                    build_config=build_config,
                )
                _publish_bucket_staging(
                    output_root=facts_root,
                    staging=staging,
                    final_dir=facts_root / "code_buckets" / f"code_bucket={bucket:03d}",
                    bucket=bucket,
                    codes=checkpoint["codes"],
                    signal_set_id=build_config["signal_set_id"],
                    checkpoint_sha256=checkpoint["checkpoint_sha256"],
                )
                processed_now += 1
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        if max_buckets is not None and len(pending) > processed_now:
            return {
                "state": "INCOMPLETE",
                "signal_set_id": build_config["signal_set_id"],
                "processed_buckets_this_call": processed_now,
                "completed_buckets": len(
                    list((facts_root / "code_buckets").glob("code_bucket=*"))
                ),
                "native_prefix_calls_this_run": 0,
                "elapsed_seconds": time.perf_counter() - started,
            }

        checkpoints = [
            _load_checkpoint(
                facts_root,
                facts_root / "code_buckets" / f"code_bucket={bucket:03d}",
            )
            for bucket in sorted(source_buckets)
        ]
        manifest = _semantic_derivation_manifest(
            source=source,
            build_config=build_config,
            target_contract_sha256=target_contract_sha256,
            checkpoints=checkpoints,
        )
        manifest["model_registry"]["file_sha256"] = _sha256_file(registry_path)
        manifest_bytes = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        if recover_unpublished_manifest:
            if manifest_path.read_bytes() != manifest_bytes:
                raise SignalFactsError(
                    "unpublished semantic recovery manifest differs from reconstruction"
                )
        else:
            _atomic_write_bytes(manifest_path, manifest_bytes)
        manifest_sha256 = _sha256_bytes(manifest_bytes)
        _atomic_write_bytes(
            manifest_sidecar,
            f"{manifest_sha256}  manifest.json\n".encode("ascii"),
        )
    finally:
        _release_build_lock(lock_path, lock_descriptor)

    result = verify_signal_facts(facts_root, deep=True)
    _write_semantic_derivation_complete_marker(
        target_root,
        _semantic_derivation_complete_marker(
            source=source,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            target_contract_sha256=target_contract_sha256,
        ),
    )
    result.update(
        {
            "idempotent_reuse": False,
            "processed_buckets_this_call": processed_now,
            "native_prefix_calls_this_run": 0,
            "elapsed_seconds": time.perf_counter() - started,
        }
    )
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
    prepare_recovery = subparsers.add_parser("prepare-semantic-recovery-run")
    prepare_recovery.add_argument("--source-run-root", required=True)
    prepare_recovery.add_argument("--target-run-root", required=True)
    prepare_recovery.add_argument("--run-id", required=True)
    prepare_recovery.add_argument("--migration-id", required=True)
    prepare_recovery.add_argument("--expected-source-signal-set-id", required=True)
    prepare_recovery.add_argument("--expected-source-manifest-sha256", required=True)
    prepare_recovery.add_argument("--expected-source-evidence-sha256", required=True)
    prepare_recovery.add_argument("--engine-image-id", required=True)
    prepare_recovery.add_argument("--image-source-commit", required=True)
    prepare_recovery.add_argument("--image-host-source-commit", required=True)
    prepare_recovery.add_argument("--engine-module-sha256", required=True)
    prepare_recovery.add_argument("--online-module-sha256", required=True)
    derive = subparsers.add_parser("derive-semantics")
    derive.add_argument("--source-run-root", required=True)
    derive.add_argument("--target-run-root", required=True)
    derive.add_argument("--run-id", required=True)
    derive.add_argument("--migration-id", required=True)
    derive.add_argument("--expected-source-signal-set-id", required=True)
    derive.add_argument("--expected-source-manifest-sha256", required=True)
    derive.add_argument("--expected-source-evidence-sha256", required=True)
    derive.add_argument("--resume", action="store_true")
    derive.add_argument("--max-buckets", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "verify":
        result = verify_signal_facts(args.output_dir, deep=not args.shallow)
    elif args.command == "build":
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
    else:
        derivation = SemanticDerivationSpec(
            run_id=args.run_id,
            migration_id=args.migration_id,
            expected_source_signal_set_id=args.expected_source_signal_set_id,
            expected_source_manifest_sha256=args.expected_source_manifest_sha256,
            expected_source_evidence_sha256=args.expected_source_evidence_sha256,
        )
        if args.command == "prepare-semantic-recovery-run":
            result = prepare_semantic_recovery_run(
                args.source_run_root,
                args.target_run_root,
                spec=SemanticRecoveryRunSpec(
                    derivation=derivation,
                    engine_image_id=args.engine_image_id,
                    image_source_commit=args.image_source_commit,
                    image_host_source_commit=args.image_host_source_commit,
                    engine_module_sha256=args.engine_module_sha256,
                    online_module_sha256=args.online_module_sha256,
                ),
            )
        else:
            result = derive_semantic_signal_facts(
                args.source_run_root,
                args.target_run_root,
                spec=derivation,
                resume=args.resume,
                max_buckets=args.max_buckets,
            )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
