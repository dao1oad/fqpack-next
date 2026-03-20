from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from freshquant.bootstrap_config import bootstrap_config

DEFAULT_RUNTIME_ROOT = Path("D:/fqpack/runtime").resolve()
RETIRED_RUNTIME_ROOT = Path("D:/fqpack/runtime/symphony-service").resolve()
DEFAULT_MEMORY_ARTIFACT_ROOT = (DEFAULT_RUNTIME_ROOT / "artifacts" / "memory").resolve()
RETIRED_MEMORY_ARTIFACT_ROOT = (RETIRED_RUNTIME_ROOT / "artifacts" / "memory").resolve()
WINDOWS_DRIVE_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _resolve_rooted_path(value: str | Path, *, root: Path) -> Path:
    path = Path(value)
    if path.is_absolute() or WINDOWS_DRIVE_ABSOLUTE_RE.match(str(value)):
        return path.resolve()
    return (root / path).resolve()


def _normalize_runtime_root(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == RETIRED_RUNTIME_ROOT:
        return DEFAULT_RUNTIME_ROOT
    return resolved


def _normalize_memory_artifact_root(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == RETIRED_MEMORY_ARTIFACT_ROOT:
        return DEFAULT_MEMORY_ARTIFACT_ROOT
    return resolved


@dataclass(slots=True)
class MemoryRuntimeConfig:
    repo_root: Path
    service_root: Path
    cold_memory_root: Path
    artifact_root: Path
    reference_ref: str
    mongo_host: str
    mongo_port: int
    mongo_db: str

    @classmethod
    def from_settings(
        cls,
        *,
        repo_root: str | Path,
        service_root: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "MemoryRuntimeConfig":
        env = dict(os.environ if environ is None else environ)
        repo_path = Path(repo_root).resolve()
        resolved_service_root = _normalize_runtime_root(
            Path(
                service_root
                or env.get("FRESHQUANT_MEMORY__SERVICE_ROOT")
                or DEFAULT_RUNTIME_ROOT
            )
        )

        memory_settings = bootstrap_config.memory
        memory_mongodb = memory_settings.mongodb
        mongodb_settings = bootstrap_config.mongodb

        mongo_host = (
            env.get("FRESHQUANT_MEMORY__MONGODB__HOST")
            or memory_mongodb.host
            or mongodb_settings.host
            or "127.0.0.1"
        )
        mongo_port = int(
            env.get("FRESHQUANT_MEMORY__MONGODB__PORT")
            or memory_mongodb.port
            or mongodb_settings.port
            or 27027
        )
        mongo_db = (
            env.get("FRESHQUANT_MEMORY__MONGODB__DB")
            or memory_mongodb.db
            or "fq_memory"
        )

        cold_memory_root = _resolve_rooted_path(
            env.get("FRESHQUANT_MEMORY__COLD_ROOT")
            or memory_settings.cold_root
            or ".codex/memory",
            root=repo_path,
        )
        explicit_artifact_root = env.get("FRESHQUANT_MEMORY__ARTIFACT_ROOT")
        if explicit_artifact_root:
            artifact_root = _normalize_memory_artifact_root(
                _resolve_rooted_path(
                    explicit_artifact_root,
                    root=resolved_service_root,
                )
            )
        else:
            artifact_root = _normalize_memory_artifact_root(
                _resolve_rooted_path(
                    memory_settings.artifact_root or "artifacts/memory",
                    root=resolved_service_root,
                )
            )
        reference_ref = (
            env.get("FRESHQUANT_MEMORY__REFERENCE_REF")
            or getattr(memory_settings, "reference_ref", None)
            or "origin/main"
        )

        return cls(
            repo_root=repo_path,
            service_root=resolved_service_root,
            cold_memory_root=cold_memory_root,
            artifact_root=artifact_root,
            reference_ref=str(reference_ref),
            mongo_host=str(mongo_host),
            mongo_port=mongo_port,
            mongo_db=str(mongo_db),
        )
