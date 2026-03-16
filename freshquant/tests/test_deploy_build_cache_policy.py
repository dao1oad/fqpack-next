from pathlib import Path


def test_dockerignore_excludes_large_non_build_inputs() -> None:
    text = Path(".dockerignore").read_text(encoding="utf-8")

    assert ".git" in text
    assert ".worktrees" in text
    assert "runtime" in text
    assert "logs" in text
    assert ".artifacts" in text
    assert ".tmp" in text


def test_web_context_has_local_dockerignore_for_build_outputs() -> None:
    text = Path("morningglory/fqwebui/.dockerignore").read_text(encoding="utf-8")

    assert "node_modules" in text
    assert "web" in text
    assert "test-results" in text


def test_dockerfile_web_installs_dependencies_before_copying_sources() -> None:
    text = Path("docker/Dockerfile.web").read_text(encoding="utf-8")

    manifest_copy = text.index("COPY package.json pnpm-lock.yaml ./")
    source_copy = text.index("COPY src ./src")
    install = text.index("RUN pnpm install")

    assert manifest_copy < install < source_copy
    assert "ARG FQ_IMAGE_GIT_SHA=unknown" in text
    assert 'LABEL io.freshquant.git_sha="${FQ_IMAGE_GIT_SHA}"' in text


def test_dockerfile_rear_uses_dependency_and_project_sync_layers() -> None:
    text = Path("docker/Dockerfile.rear").read_text(encoding="utf-8")

    dependency_sync = text.index("RUN python -m uv sync --frozen --no-install-project")
    final_sync = text.rindex("RUN /usr/local/bin/python -m uv sync --frozen")

    assert dependency_sync < final_sync
    assert "COPY pyproject.toml uv.lock jupyter_server_config.json ./" in text
    assert "COPY morningglory/fqchan03 ./morningglory/fqchan03" in text
    assert "COPY morningglory/fqcopilot ./morningglory/fqcopilot" in text
    assert "COPY . ." in text
    assert 'LABEL io.freshquant.git_sha="${FQ_IMAGE_GIT_SHA}"' in text


def test_compose_uses_web_scoped_context_and_git_sha_build_args() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")

    assert "context: ../morningglory/fqwebui" in text
    assert "dockerfile: ../../docker/Dockerfile.web" in text
    assert "FQ_IMAGE_GIT_SHA: ${FQ_IMAGE_GIT_SHA:-unknown}" in text
