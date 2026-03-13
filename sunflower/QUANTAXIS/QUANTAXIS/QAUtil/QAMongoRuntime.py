import os
from urllib.parse import urlparse

LOCAL_MONGO_HOSTS = {"localhost", "127.0.0.1", "::1"}


class MongoRuntimeConfig:
    def __init__(self, host, port, uri):
        self.host = host
        self.port = port
        self.uri = uri


def _normalize_candidate(candidate):
    value = (candidate or "").strip()
    return value or None


def _default_port_for_host(host):
    return 27027 if (host or "").lower() in LOCAL_MONGO_HOSTS else 27017


def _parse_candidate(candidate):
    value = _normalize_candidate(candidate)
    if value is None:
        return None

    if "://" in value:
        parsed = urlparse(value)
        host = parsed.hostname or "localhost"
        port = parsed.port or _default_port_for_host(host)
        return MongoRuntimeConfig(host=host, port=port, uri=value)

    if ":" in value:
        host, raw_port = value.rsplit(":", 1)
        if raw_port.isdigit():
            port = int(raw_port)
            return MongoRuntimeConfig(
                host=host,
                port=port,
                uri=f"mongodb://{host}:{port}",
            )

    host = value
    port = _default_port_for_host(host)
    return MongoRuntimeConfig(host=host, port=port, uri=f"mongodb://{host}:{port}")


def QA_util_resolve_mongo_runtime(legacy_uri=None):
    explicit_uri = _normalize_candidate(
        os.getenv("MONGOURI") or os.getenv("FRESHQUANT_MONGODB__URI")
    )
    if explicit_uri is not None:
        return _parse_candidate(explicit_uri)

    host_env = _normalize_candidate(
        os.getenv("FRESHQUANT_MONGODB__HOST") or os.getenv("MONGODB")
    )
    port_env = _normalize_candidate(
        os.getenv("FRESHQUANT_MONGODB__PORT") or os.getenv("MONGODB_PORT")
    )
    if host_env is not None or port_env is not None:
        host = host_env or "localhost"
        port = int(port_env) if port_env is not None else _default_port_for_host(host)
        return MongoRuntimeConfig(
            host=host,
            port=port,
            uri=f"mongodb://{host}:{port}",
        )

    parsed_legacy = _parse_candidate(legacy_uri)
    if parsed_legacy is not None:
        if (
            parsed_legacy.host.lower() in LOCAL_MONGO_HOSTS
            and parsed_legacy.port == 27017
        ):
            return MongoRuntimeConfig(
                host=parsed_legacy.host,
                port=27027,
                uri=f"mongodb://{parsed_legacy.host}:27027",
            )
        return parsed_legacy

    host = "localhost"
    port = _default_port_for_host(host)
    return MongoRuntimeConfig(host=host, port=port, uri=f"mongodb://{host}:{port}")
