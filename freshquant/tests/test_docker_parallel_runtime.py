import importlib.util
from pathlib import Path


def load_runtime_helper():
    module_path = Path("script/docker_parallel_runtime.py")
    spec = importlib.util.spec_from_file_location(
        "docker_parallel_runtime", module_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_primary_worktree_path_prefers_main_worktree_entry() -> None:
    helper = load_runtime_helper()
    output = "\n".join(
        [
            "worktree D:/fqpack/freshquant-2026.2.23",
            "HEAD 428d11c6922cdb727b73ee6569200baec5d7b1e9",
            "branch refs/heads/main",
            "",
            "worktree D:/fqpack/freshquant-2026.2.23/.worktrees/deploy-main-f1add78",
            "HEAD 87bf4679b8da5ae5017f7e8ca8c40c72099c5f25",
            "branch refs/heads/deploy-main-f1add78",
        ]
    )

    primary = helper.parse_primary_worktree_path(output)

    assert primary == Path("D:/fqpack/freshquant-2026.2.23")


def test_resolve_runtime_log_host_dir_uses_primary_worktree_logs_directory() -> None:
    helper = load_runtime_helper()

    runtime_dir = helper.resolve_runtime_log_host_dir(
        Path("D:/fqpack/freshquant-2026.2.23")
    )

    assert runtime_dir == Path("D:/fqpack/freshquant-2026.2.23/logs/runtime")


def test_resolve_compose_env_file_uses_primary_worktree_dotenv() -> None:
    helper = load_runtime_helper()

    env_file = helper.resolve_compose_env_file(Path("D:/fqpack/freshquant-2026.2.23"))

    assert env_file == Path("D:/fqpack/freshquant-2026.2.23/.env")
