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


def test_compose_builds_rear_image_once() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")
    assert text.count("dockerfile: docker/Dockerfile.rear") == 1


def test_ci_uses_uv_sync() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "uv sync --frozen" in text
