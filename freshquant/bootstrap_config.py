from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dynaconf import Dynaconf
from pydash import get

BASE_DIR = Path(__file__).resolve().parent
EXE_DIR = Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] else Path.cwd()
CWD_DIR = Path.cwd()
HOME_CONFIG_DIR = Path.home() / ".freshquant"
HOST_CONFIG_DIR = Path(os.environ.get("FQ_PACK_DIR", "D:/fqpack")) / "config"
BOOTSTRAP_FILE_NAMES = (
    "freshquant_bootstrap.yaml",
    "freshquant_bootstrap.yml",
    "freshquant_bootstrap.json",
)


@dataclass(frozen=True)
class MongoBootstrapConfig:
    host: str = "127.0.0.1"
    port: int = 27027
    db: str = "freshquant"
    gantt_db: str = "freshquant_gantt"
    screening_db: str = "fqscreening"


@dataclass(frozen=True)
class RedisBootstrapConfig:
    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 1
    password: str = ""


@dataclass(frozen=True)
class MemoryMongoBootstrapConfig:
    host: str = "127.0.0.1"
    port: int = 27027
    db: str = "fq_memory"


@dataclass(frozen=True)
class MemoryBootstrapConfig:
    mongodb: MemoryMongoBootstrapConfig = MemoryMongoBootstrapConfig()
    cold_root: str = ".codex/memory"
    artifact_root: str = "D:/fqpack/runtime/symphony-service/artifacts/memory"


@dataclass(frozen=True)
class OrderManagementBootstrapConfig:
    mongo_database: str = "freshquant_order_management"
    projection_database: str = "freshquant"


@dataclass(frozen=True)
class PositionManagementBootstrapConfig:
    mongo_database: str = "freshquant_position_management"


@dataclass(frozen=True)
class TdxBootstrapConfig:
    home: str = ""
    hq_endpoint: str = "http://127.0.0.1:15001"


@dataclass(frozen=True)
class ApiBootstrapConfig:
    base_url: str = "http://127.0.0.1:15000"


@dataclass(frozen=True)
class XtdataBootstrapConfig:
    port: int = 58610


@dataclass(frozen=True)
class RuntimeBootstrapConfig:
    log_dir: str = "logs/runtime"


@dataclass(frozen=True)
class BootstrapConfig:
    mongodb: MongoBootstrapConfig = MongoBootstrapConfig()
    redis: RedisBootstrapConfig = RedisBootstrapConfig()
    memory: MemoryBootstrapConfig = MemoryBootstrapConfig()
    order_management: OrderManagementBootstrapConfig = OrderManagementBootstrapConfig()
    position_management: PositionManagementBootstrapConfig = (
        PositionManagementBootstrapConfig()
    )
    tdx: TdxBootstrapConfig = TdxBootstrapConfig()
    api: ApiBootstrapConfig = ApiBootstrapConfig()
    xtdata: XtdataBootstrapConfig = XtdataBootstrapConfig()
    runtime: RuntimeBootstrapConfig = RuntimeBootstrapConfig()


def _resolve_settings_files() -> list[str]:
    explicit = str(os.environ.get("FRESHQUANT_BOOTSTRAP_FILE", "") or "").strip()
    if explicit:
        return [explicit]

    directories = [BASE_DIR, EXE_DIR, HOME_CONFIG_DIR, HOST_CONFIG_DIR, CWD_DIR]
    return [
        str(directory / file_name)
        for directory in directories
        for file_name in BOOTSTRAP_FILE_NAMES
    ]


def resolve_bootstrap_file_path() -> Path:
    explicit = str(os.environ.get("FRESHQUANT_BOOTSTRAP_FILE", "") or "").strip()
    if explicit:
        return Path(explicit)

    for candidate in _resolve_settings_files():
        path = Path(candidate)
        if path.exists():
            return path
    return HOST_CONFIG_DIR / BOOTSTRAP_FILE_NAMES[0]


def _load_raw_settings() -> Dynaconf:
    return Dynaconf(
        settings_files=_resolve_settings_files(),
        envvar_prefix="freshquant",
    )


def _as_str(value, default="") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_bootstrap_config() -> BootstrapConfig:
    settings = _load_raw_settings()
    mongodb = MongoBootstrapConfig(
        host=_as_str(get(settings, "mongodb.host"), "127.0.0.1"),
        port=_as_int(get(settings, "mongodb.port"), 27027),
        db=_as_str(get(settings, "mongodb.db"), "freshquant"),
        gantt_db=_as_str(get(settings, "mongodb.gantt_db"), "freshquant_gantt"),
        screening_db=_as_str(get(settings, "mongodb.screening_db"), "fqscreening"),
    )
    redis = RedisBootstrapConfig(
        host=_as_str(get(settings, "redis.host"), "127.0.0.1"),
        port=_as_int(get(settings, "redis.port"), 6379),
        db=_as_int(get(settings, "redis.db"), 1),
        password=_as_str(get(settings, "redis.password"), ""),
    )
    memory = MemoryBootstrapConfig(
        mongodb=MemoryMongoBootstrapConfig(
            host=_as_str(get(settings, "memory.mongodb.host"), "127.0.0.1"),
            port=_as_int(get(settings, "memory.mongodb.port"), 27027),
            db=_as_str(get(settings, "memory.mongodb.db"), "fq_memory"),
        ),
        cold_root=_as_str(get(settings, "memory.cold_root"), ".codex/memory"),
        artifact_root=_as_str(
            get(settings, "memory.artifact_root"),
            "D:/fqpack/runtime/symphony-service/artifacts/memory",
        ),
    )
    order_management = OrderManagementBootstrapConfig(
        mongo_database=_as_str(
            get(settings, "order_management.mongo_database"),
            "freshquant_order_management",
        ),
        projection_database=_as_str(
            get(settings, "order_management.projection_database"),
            mongodb.db,
        ),
    )
    position_management = PositionManagementBootstrapConfig(
        mongo_database=_as_str(
            get(settings, "position_management.mongo_database"),
            "freshquant_position_management",
        )
    )
    tdx = TdxBootstrapConfig(
        home=_as_str(get(settings, "tdx.home"), _as_str(os.environ.get("TDX_HOME"))),
        hq_endpoint=_as_str(
            get(settings, "tdx.hq.endpoint"),
            _as_str(
                os.environ.get("FRESHQUANT_TDX__HQ__ENDPOINT"), "http://127.0.0.1:15001"
            ),
        ),
    )
    api = ApiBootstrapConfig(
        base_url=_as_str(get(settings, "api.base_url"), "http://127.0.0.1:15000")
    )
    xtdata = XtdataBootstrapConfig(
        port=_as_int(
            get(settings, "xtdata.port"), _as_int(os.environ.get("XTQUANT_PORT"), 58610)
        )
    )
    runtime = RuntimeBootstrapConfig(
        log_dir=_as_str(
            get(settings, "runtime.log_dir"),
            _as_str(os.environ.get("FQ_RUNTIME_LOG_DIR"), "logs/runtime"),
        )
    )
    return BootstrapConfig(
        mongodb=mongodb,
        redis=redis,
        memory=memory,
        order_management=order_management,
        position_management=position_management,
        tdx=tdx,
        api=api,
        xtdata=xtdata,
        runtime=runtime,
    )


bootstrap_config = load_bootstrap_config()


def reload_bootstrap_config() -> BootstrapConfig:
    global bootstrap_config
    bootstrap_config = load_bootstrap_config()
    return bootstrap_config
