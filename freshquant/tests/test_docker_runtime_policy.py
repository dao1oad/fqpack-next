import re
from pathlib import Path


def test_dockerfile_rear_uses_uv_sync_frozen() -> None:
    text = Path("docker/Dockerfile.rear").read_text(encoding="utf-8")
    assert "uv sync --frozen" in text


def test_compose_python_services_use_project_venv() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")
    assert "/freshquant/.venv/bin/python" in text


def test_compose_images_support_env_overrides() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")
    assert "${FQNEXT_REAR_IMAGE:-fqnext_rear:2026.2.23}" in text
    assert "${FQNEXT_WEBUI_IMAGE:-fqnext_webui:2026.2.23}" in text
    assert "${FQNEXT_TA_BACKEND_IMAGE:-fqnext_ta_backend:2026.2.23}" in text
    assert "${FQNEXT_TA_FRONTEND_IMAGE:-fqnext_ta_frontend:2026.2.23}" in text


def test_compose_core_rear_services_override_container_redis_host() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")

    for service_name in (
        "fq_apiserver",
        "fq_runtime_indexer",
        "fq_tdxhq",
        "fq_dagster_webserver",
        "fq_dagster_daemon",
        "fq_qawebserver",
    ):
        match = re.search(
            rf"^  {service_name}:\n(?P<body>.*?)(?=^  [a-z0-9_]+:\n|\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        assert match, service_name
        body = match.group("body")
        assert "FRESHQUANT_REDIS__HOST: fq_redis" in body
        assert 'FRESHQUANT_REDIS__PORT: "6379"' in body


def test_compose_builds_rear_image_once() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")
    assert text.count("dockerfile: docker/Dockerfile.rear") == 1


def test_compose_apiserver_mounts_tdx_sync_dir() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")
    assert "${FQPACK_TDX_SYNC_DIR:-D:/tdx_biduan}" in text
    assert "target: /opt/tdx" in text


def test_ci_uses_uv_sync() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "uv sync --frozen" in text


def test_compose_uses_buildkit_local_cache_for_build_services() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")

    assert "cache_from:" in text
    assert "cache_to:" in text
    assert "FQ_DOCKER_BUILD_CACHE_ROOT" in text


def test_docker_parallel_compose_enables_buildkit_environment() -> None:
    text = Path("script/docker_parallel_compose.ps1").read_text(encoding="utf-8")

    assert "DOCKER_BUILDKIT" in text
    assert "COMPOSE_BAKE" in text


def test_compose_includes_runtime_clickhouse_and_indexer_services() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")

    assert "fq_runtime_clickhouse:" in text
    assert "fq_runtime_indexer:" in text
    assert "FQ_RUNTIME_CLICKHOUSE_URL" in text
    assert "CLICKHOUSE_USER" in text
    assert "FQ_RUNTIME_CLICKHOUSE_USER" in text
