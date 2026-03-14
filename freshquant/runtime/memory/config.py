from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from freshquant.config import settings


def _resolve_rooted_path(value: str | Path, *, root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (root / path).resolve()


@dataclass(slots=True)
class MemoryRuntimeConfig:
    repo_root: Path
    service_root: Path
    cold_memory_root: Path
    artifact_root: Path
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
        resolved_service_root = Path(
            service_root
            or env.get("SYMPHONY_SERVICE_ROOT")
            or env.get("FRESHQUANT_MEMORY__SERVICE_ROOT")
            or "D:/fqpack/runtime/symphony-service"
        ).resolve()

        memory_settings = settings.get("memory", {}) or {}
        memory_mongodb = memory_settings.get("mongodb", {}) or {}
        mongodb_settings = settings.get("mongodb", {}) or {}

        mongo_host = (
            env.get("FRESHQUANT_MEMORY__MONGODB__HOST")
            or memory_mongodb.get("host")
            or mongodb_settings.get("host")
            or "127.0.0.1"
        )
        mongo_port = int(
            env.get("FRESHQUANT_MEMORY__MONGODB__PORT")
            or memory_mongodb.get("port")
            or mongodb_settings.get("port")
            or 27027
        )
        mongo_db = (
            env.get("FRESHQUANT_MEMORY__MONGODB__DB")
            or memory_mongodb.get("db")
            or memory_settings.get("db")
            or "fq_memory"
        )

        cold_memory_root = _resolve_rooted_path(
            env.get("FRESHQUANT_MEMORY__COLD_ROOT")
            or memory_settings.get("cold_root")
            or ".codex/memory",
            root=repo_path,
        )
        explicit_artifact_root = env.get("FRESHQUANT_MEMORY__ARTIFACT_ROOT")
        if explicit_artifact_root:
            artifact_root = _resolve_rooted_path(
                explicit_artifact_root,
                root=resolved_service_root,
            )
        elif service_root is not None:
            artifact_root = _resolve_rooted_path(
                "artifacts/memory",
                root=resolved_service_root,
            )
        else:
            artifact_root = _resolve_rooted_path(
                memory_settings.get("artifact_root") or "artifacts/memory",
                root=resolved_service_root,
            )

        return cls(
            repo_root=repo_path,
            service_root=resolved_service_root,
            cold_memory_root=cold_memory_root,
            artifact_root=artifact_root,
            mongo_host=str(mongo_host),
            mongo_port=mongo_port,
            mongo_db=str(mongo_db),
        )
