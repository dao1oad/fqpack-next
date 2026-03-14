from pathlib import Path
import importlib.util
import sys


def load_runtime_module():
    module_path = Path("script/docker_parallel_runtime.py")
    spec = importlib.util.spec_from_file_location("docker_parallel_runtime", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def test_compose_apiserver_mounts_tdx_sync_dir() -> None:
    text = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")
    assert "${FQPACK_TDX_SYNC_DIR:-D:/tdx_biduan}" in text
    assert "target: /opt/tdx" in text


def test_ci_uses_uv_sync() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "uv sync --frozen" in text


def test_runtime_policy_parser_accepts_primary_repo_override_flags() -> None:
    module = load_runtime_module()

    args = module.build_parser().parse_args(
        [
            "--primary-worktree",
            "D:/fqpack/freshquant-2026.2.23",
            "--compose-env-file",
            "D:/fqpack/freshquant-2026.2.23/.env",
            "--runtime-log-dir",
            "D:/fqpack/freshquant-2026.2.23/logs/runtime",
            "--prefer-clean-worktree",
            "--allow-dirty-primary",
        ]
    )

    assert args.primary_worktree == Path("D:/fqpack/freshquant-2026.2.23")
    assert args.compose_env_file == Path("D:/fqpack/freshquant-2026.2.23/.env")
    assert args.runtime_log_dir == Path("D:/fqpack/freshquant-2026.2.23/logs/runtime")
    assert args.prefer_clean_worktree is True
    assert args.allow_dirty_primary is True


def test_runtime_policy_uses_clean_build_root_with_primary_env_and_logs() -> None:
    module = load_runtime_module()

    policy = module.resolve_runtime_policy(
        repo_root=Path("C:/Users/Administrator/.codex/worktrees/05c1/freshquant-2026.2.23"),
        primary_worktree=Path("D:/fqpack/freshquant-2026.2.23"),
        prefer_clean_worktree=True,
        allow_dirty_primary=True,
    )

    assert policy["repo_root"] == "C:\\Users\\Administrator\\.codex\\worktrees\\05c1\\freshquant-2026.2.23"
    assert policy["build_worktree"] == "C:\\Users\\Administrator\\.codex\\worktrees\\05c1\\freshquant-2026.2.23"
    assert policy["primary_worktree"] == "D:\\fqpack\\freshquant-2026.2.23"
    assert policy["compose_env_file"] == "D:\\fqpack\\freshquant-2026.2.23\\.env"
    assert policy["runtime_log_dir"] == "D:\\fqpack\\freshquant-2026.2.23\\logs\\runtime"
    assert policy["prefer_clean_worktree"] is True
    assert policy["allow_dirty_primary"] is True


def test_compose_wrapper_supports_explicit_runtime_overrides_and_metadata_output() -> None:
    text = Path("script/docker_parallel_compose.ps1").read_text(encoding="utf-8")

    assert "[string]$PrimaryWorktree" in text
    assert "[string]$ComposeEnvFile" in text
    assert "[string]$RuntimeLogDir" in text
    assert "[string]$EmitMetadataPath" in text
    assert "[switch]$NoProxyLocalhost" in text
    assert "[int]$BuildTimeoutSec" in text


def test_compose_wrapper_records_review_oriented_metadata_fields() -> None:
    text = Path("script/docker_parallel_compose.ps1").read_text(encoding="utf-8")

    assert "review_required" in text
    assert "timed_out" in text
    assert "docker_exit_code" in text
    assert "compose_args" in text
    assert "compose_env_file" in text
    assert "runtime_log_dir" in text
