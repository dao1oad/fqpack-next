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
    install = text.index("pnpm install --prefer-offline")

    assert manifest_copy < install < source_copy
    assert "ARG FQ_IMAGE_GIT_SHA=unknown" in text
    assert 'LABEL io.freshquant.git_sha="${FQ_IMAGE_GIT_SHA}"' in text


def test_dockerfile_rear_uses_dependency_and_project_sync_layers() -> None:
    text = Path("docker/Dockerfile.rear").read_text(encoding="utf-8")

    dependency_sync = text.index("python -m uv sync --frozen --no-install-project")
    final_sync = text.rindex("/usr/local/bin/python -m uv sync --frozen")

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


def test_tradingagents_compose_uses_git_sha_build_args() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")

    assert "ta_backend:" in text
    assert "ta_frontend:" in text
    assert text.count("FQ_IMAGE_GIT_SHA: ${FQ_IMAGE_GIT_SHA:-unknown}") >= 4


def test_all_dockerfiles_use_git_sha_labels_and_buildkit_cache_mounts() -> None:
    rear_text = Path("docker/Dockerfile.rear").read_text(encoding="utf-8")
    web_text = Path("docker/Dockerfile.web").read_text(encoding="utf-8")
    ta_backend_text = Path("third_party/tradingagents-cn/Dockerfile.backend").read_text(
        encoding="utf-8"
    )
    ta_frontend_text = Path(
        "third_party/tradingagents-cn/Dockerfile.frontend"
    ).read_text(encoding="utf-8")

    for text in (rear_text, web_text, ta_backend_text, ta_frontend_text):
        assert "ARG FQ_IMAGE_GIT_SHA=unknown" in text
        assert 'LABEL io.freshquant.git_sha="${FQ_IMAGE_GIT_SHA}"' in text
        assert "--mount=type=cache" in text


def test_dagster_config_sync_overwrites_existing_files() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")

    assert "cp -f /freshquant/morningglory/fqdagsterconfig/* /opt/dagster/home/" in text
    assert (
        "cp -n /freshquant/morningglory/fqdagsterconfig/* /opt/dagster/home/"
        not in text
    )


def test_dagster_services_override_container_home_paths() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")

    assert text.count("DAGSTER_HOME: /opt/dagster/home") >= 2
    assert text.count("FRESHQUANT_DAGSTER__HOME: /opt/dagster/home") >= 2


def test_docker_images_workflow_publishes_to_ghcr() -> None:
    text = Path(".github/workflows/docker-images.yml").read_text(encoding="utf-8")

    assert "ghcr.io" in text
    assert "packages: write" in text
    assert "docker/build-push-action" in text
    assert "docker/login-action" in text


def test_current_deployment_docs_cover_local_mirror_production_deploys() -> None:
    deployment_text = Path("docs/current/deployment.md").read_text(encoding="utf-8")
    runtime_text = Path("docs/current/runtime.md").read_text(encoding="utf-8")

    assert "GHCR" in deployment_text
    assert "本机 deploy mirror" in deployment_text
    assert (
        r"D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production"
        in deployment_text
    )
    assert "FQ_DOCKER_FORCE_LOCAL_BUILD" in deployment_text
    assert "本机 deploy mirror" in runtime_text


def test_powershell_compose_entry_enables_buildkit_and_env_overrides() -> None:
    text = Path("script/docker_parallel_compose.ps1").read_text(encoding="utf-8")

    assert 'DOCKER_BUILDKIT = "1"' in text
    assert 'Set-Item -Path "Env:' in text


def test_powershell_compose_entry_restores_detached_flag_swallowed_by_shell() -> None:
    text = Path("script/docker_parallel_compose.ps1").read_text(encoding="utf-8")

    assert '[Alias("d")]' in text or "[Alias('d')]" in text
    assert '"-d"' in text
    assert "$Detached" in text


def test_powershell_compose_entry_preserves_detached_flag_on_fallback() -> None:
    text = Path("script/docker_parallel_compose.ps1").read_text(encoding="utf-8")

    assert "$fallbackComposeArgs" in text
    assert "$resolvedComposeArgs = @($fallbackComposeArgs)" in text


def test_docker_images_workflow_uses_dynamic_publish_matrix() -> None:
    text = Path(".github/workflows/docker-images.yml").read_text(encoding="utf-8")

    assert "resolve-publish-plan" in text
    assert "resolve_docker_image_publish_plan.py" in text
    assert "fromJson(" in text
    assert "matrix.action == 'build'" in text
    assert "matrix.action == 'retag'" in text
    assert "docker buildx imagetools create" in text


def test_docker_images_workflow_fetches_full_history_for_diff_planning() -> None:
    text = Path(".github/workflows/docker-images.yml").read_text(encoding="utf-8")

    assert "resolve-publish-plan" in text
    assert "fetch-depth: 0" in text


def test_deploy_production_workflow_runs_on_push_to_main_via_single_entrypoint() -> (
    None
):
    text = Path(".github/workflows/deploy-production.yml").read_text(encoding="utf-8")

    assert "push:" in text
    assert "branches: [main]" in text
    assert "workflow_run" not in text
    assert "Docker Images" not in text
    assert "self-hosted" in text
    assert "windows" in text
    assert "production" in text
    assert "script/ci/run_production_deploy.ps1" in text
    assert '-TargetSha "${{ github.sha }}"' in text
    assert '-GitHubRepository "${{ github.repository }}"' in text
    assert (
        '-RunUrl "${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"'
        in text
    )
    assert r"FQ_DEPLOY_CANONICAL_REPO_ROOT: D:\fqpack\freshquant-2026.2.23" in text
    assert (
        r"FQ_DEPLOY_BOOTSTRAP_ROOT: D:\fqpack\freshquant-2026.2.23\.worktrees\production-deploy-bootstrap"
        in text
    )
    assert (
        r"FQ_DEPLOY_MIRROR_ROOT: D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production"
        in text
    )
    assert 'FQ_DEPLOY_MIRROR_BRANCH: "deploy-production-main"' in text
    assert 'FQ_DOCKER_FORCE_LOCAL_BUILD: "1"' in text
    assert "working-directory: ${{ env.FQ_DEPLOY_CANONICAL_REPO_ROOT }}" in text
    assert "shell: powershell -NoProfile -ExecutionPolicy Bypass -File {0}" in text
    assert "$ErrorActionPreference = 'Stop'" in text
    assert "actions/checkout@v4" not in text
    assert "actions/setup-python@v5" not in text
    assert "sync_local_deploy_mirror.py" not in text
    assert "run_formal_deploy.py" not in text
    assert "py -3.12 -m uv sync --frozen" not in text
    assert "pip install --upgrade pip uv" not in text
    assert "pull --ff-only origin main" not in text
    assert (
        'git -C $env:FQ_DEPLOY_BOOTSTRAP_ROOT reset --hard "${{ github.sha }}"' in text
    )
    assert 'git -C $env:FQ_DEPLOY_BOOTSTRAP_ROOT clean -ffd' in text


def test_deploy_production_workflow_rejects_stale_main_sha() -> None:
    workflow_text = Path(".github/workflows/deploy-production.yml").read_text(
        encoding="utf-8"
    )
    entrypoint_text = Path("script/ci/run_production_deploy.ps1").read_text(
        encoding="utf-8"
    )

    assert '-TargetSha "${{ github.sha }}"' in workflow_text
    assert (
        'Invoke-Git -RepoRoot $CanonicalRoot -Arguments @("fetch", "origin", "main")'
        in entrypoint_text
    )
    assert (
        '$remoteMainSha = Get-GitOutput -RepoRoot $CanonicalRoot -Arguments @("rev-parse", "origin/main")'
        in entrypoint_text
    )
    assert "stale push deploy trigger" in entrypoint_text
    assert "production-deploy-bootstrap" in entrypoint_text
    assert '$entrypoint = Join-Path $BootstrapRoot ' in entrypoint_text
    assert '"-SkipBootstrapReexec"' in entrypoint_text
    assert "api.github.com/repos/" not in workflow_text
    assert "api.github.com/repos/" not in entrypoint_text


def test_current_docs_cover_automatic_production_deploy_state() -> None:
    deployment_text = Path("docs/current/deployment.md").read_text(encoding="utf-8")
    runtime_text = Path("docs/current/runtime.md").read_text(encoding="utf-8")

    assert "deploy-production.yml" in deployment_text
    assert "production-state.json" in deployment_text
    assert "上一次成功部署" in deployment_text
    assert "script/ci/run_production_deploy.ps1" in deployment_text
    assert "runner Python 3.12" in deployment_text
    assert "python -m pip install uv --break-system-packages" in deployment_text
    assert (
        r"D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production"
        in deployment_text
    )
    assert r"D:\fqpack\freshquant-2026.2.23" in deployment_text
    assert "safe.directory" in deployment_text
    assert "本机 deploy mirror" in deployment_text
    assert "bootstrap worktree" in deployment_text
    assert "当前 entrypoint repo" in deployment_text
    assert "quiesce 宿主机 surfaces" in deployment_text
    assert "pyvenv.cfg" in deployment_text
    assert "FQ_DOCKER_FORCE_LOCAL_BUILD" in deployment_text
    assert r".venv\Scripts\python.exe" in deployment_text
    assert "保留 live deploy mirror 的 `.venv\\`" in deployment_text
    assert "deploy-production.yml" in runtime_text
    assert "formal-deploy" in runtime_text
    assert "script/ci/run_production_deploy.ps1" in runtime_text
    assert "per-user / system Python 3.12" in runtime_text
    assert "python -m uv" in runtime_text
    assert (
        r"D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production"
        in runtime_text
    )
    assert (
        r"D:\fqpack\freshquant-2026.2.23\.worktrees\production-deploy-bootstrap"
        in runtime_text
    )
    assert r"D:\fqpack\freshquant-2026.2.23" in runtime_text
    assert "当前 entrypoint repo" in runtime_text
    assert "quiesce 宿主机 surfaces" in runtime_text
    assert "pyvenv.cfg" in runtime_text
    assert "FQ_DOCKER_FORCE_LOCAL_BUILD" in runtime_text
    assert r".venv\Scripts\python.exe" in runtime_text
