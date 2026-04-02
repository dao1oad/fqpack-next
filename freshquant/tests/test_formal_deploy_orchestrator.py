from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_module():
    module_path = Path("script/ci/run_formal_deploy.py")
    spec = importlib.util.spec_from_file_location("run_formal_deploy", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_plan(
    *,
    surfaces: list[str],
    docker_command: list[str] | None = None,
    host_command: list[str] | None = None,
) -> dict[str, object]:
    docker_command = docker_command or []
    host_command = host_command or []
    return {
        "changed_paths": [],
        "deployment_required": bool(surfaces),
        "deployment_surfaces": surfaces,
        "docker_build_targets": [],
        "docker_up_services": [],
        "docker_services": docker_command[8:] if docker_command else [],
        "host_surfaces": surfaces if host_command else [],
        "host_programs": [],
        "runtime_ops_surfaces": surfaces,
        "health_checks": [],
        "pre_deploy_steps": [],
        "docker_command": docker_command,
        "host_command": host_command,
        "notes": [],
    }


def write_state(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_state(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_bootstrap_without_state_deploys_all_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    commands: list[list[str]] = []

    surface_order = (
        "api",
        "web",
        "dagster",
        "qa",
        "tradingagents",
        "market_data",
        "guardian",
        "position_management",
        "tpsl",
        "order_management",
    )
    fake_plan_module = SimpleNamespace(
        SURFACE_ORDER=surface_order,
        HEALTH_CHECK_MAP={
            "api": ["http://127.0.0.1:15000/api/runtime/health/summary"],
            "web": ["http://127.0.0.1:18080/"],
            "tradingagents": ["http://127.0.0.1:13000/api/health"],
        },
        build_deploy_plan=lambda changed_paths=None, explicit_surfaces=None: make_plan(
            surfaces=list(explicit_surfaces or []),
            docker_command=[
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                "script/docker_parallel_compose.ps1",
                "up",
                "-d",
                "--build",
                "fq_apiserver",
                "fq_webui",
                "fq_dagster_webserver",
                "fq_dagster_daemon",
                "fq_qawebserver",
                "ta_backend",
                "ta_frontend",
            ],
            host_command=[
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                "script/fqnext_host_runtime_ctl.ps1",
                "-Mode",
                "EnsureServiceAndRestartSurfaces",
                "-DeploymentSurface",
                "market_data,guardian,position_management,tpsl,order_management",
                "-BridgeIfServiceUnavailable",
            ],
        ),
    )
    monkeypatch.setattr(
        module,
        "load_current_revision",
        lambda _: (_ for _ in ()).throw(
            AssertionError("local HEAD should not be used")
        ),
    )
    monkeypatch.setattr(module, "resolve_latest_remote_main_sha", lambda _: "newsha")
    monkeypatch.setattr(module, "load_deploy_plan_module", lambda _: fake_plan_module)
    monkeypatch.setattr(
        module,
        "execute_command",
        lambda command, **_: commands.append(command),
    )
    monkeypatch.setattr(
        module,
        "utcnow",
        lambda: datetime(2026, 3, 17, 8, 0, 0, tzinfo=timezone.utc),
    )

    state_path = tmp_path / "production-state.json"
    result = module.run_formal_deploy(
        repo_root=Path("."),
        state_path=state_path,
        runs_root=tmp_path / "runs",
        run_url="https://example.invalid/runs/1",
    )

    assert result["bootstrap"] is True
    assert result["plan"]["deployment_surfaces"] == list(surface_order)
    assert read_state(state_path)["last_success_sha"] == "newsha"
    assert commands[0][4] == "script/check_freshquant_runtime_post_deploy.ps1"


def test_successful_run_updates_last_success_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    commands: list[list[str]] = []

    write_state(
        tmp_path / "production-state.json",
        {
            "last_success_sha": "oldsha",
            "last_attempt_sha": "oldsha",
            "last_attempt_at": "2026-03-16T00:00:00+00:00",
            "last_success_at": "2026-03-16T00:00:00+00:00",
            "last_deployed_surfaces": ["api"],
            "last_run_url": "https://example.invalid/runs/0",
        },
    )

    fake_plan_module = SimpleNamespace(
        SURFACE_ORDER=("api", "web"),
        HEALTH_CHECK_MAP={"web": ["http://127.0.0.1:18080/"]},
        build_deploy_plan=lambda changed_paths=None, explicit_surfaces=None: make_plan(
            surfaces=["web"],
            docker_command=[
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                "script/docker_parallel_compose.ps1",
                "up",
                "-d",
                "--build",
                "fq_webui",
            ],
        ),
    )
    monkeypatch.setattr(
        module,
        "load_current_revision",
        lambda _: (_ for _ in ()).throw(
            AssertionError("local HEAD should not be used")
        ),
    )
    monkeypatch.setattr(module, "resolve_latest_remote_main_sha", lambda _: "newsha")
    monkeypatch.setattr(
        module,
        "load_changed_paths",
        lambda repo_root, base_sha, head_sha: ["morningglory/fqwebui/src/App.vue"],
    )
    monkeypatch.setattr(module, "load_deploy_plan_module", lambda _: fake_plan_module)
    monkeypatch.setattr(
        module,
        "execute_command",
        lambda command, **_: commands.append(command),
    )
    monkeypatch.setattr(
        module,
        "utcnow",
        lambda: datetime(2026, 3, 17, 8, 30, 0, tzinfo=timezone.utc),
    )

    state_path = tmp_path / "production-state.json"
    result = module.run_formal_deploy(
        repo_root=Path("."),
        state_path=state_path,
        runs_root=tmp_path / "runs",
        run_url="https://example.invalid/runs/2",
    )

    state = read_state(state_path)
    assert result["changed_paths"] == ["morningglory/fqwebui/src/App.vue"]
    assert state["last_success_sha"] == "newsha"
    assert state["last_attempt_sha"] == "newsha"
    assert state["last_deployed_surfaces"] == ["web"]
    assert state["last_run_url"] == "https://example.invalid/runs/2"
    assert any(
        "freshquant_health_check.py" in " ".join(command) for command in commands
    )


def test_failed_health_check_does_not_advance_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()

    state_path = tmp_path / "production-state.json"
    write_state(
        state_path,
        {
            "last_success_sha": "oldsha",
            "last_attempt_sha": "oldsha",
            "last_attempt_at": "2026-03-16T00:00:00+00:00",
            "last_success_at": "2026-03-16T00:00:00+00:00",
            "last_deployed_surfaces": ["api"],
            "last_run_url": "https://example.invalid/runs/0",
        },
    )

    fake_plan_module = SimpleNamespace(
        SURFACE_ORDER=("api", "web"),
        HEALTH_CHECK_MAP={"api": ["http://127.0.0.1:15000/api/runtime/health/summary"]},
        build_deploy_plan=lambda changed_paths=None, explicit_surfaces=None: make_plan(
            surfaces=["api"],
            docker_command=[
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                "script/docker_parallel_compose.ps1",
                "up",
                "-d",
                "--build",
                "fq_apiserver",
            ],
        ),
    )

    def fail_on_health(command: list[str], **_: object) -> None:
        if "freshquant_health_check.py" in " ".join(command):
            raise RuntimeError("health check failed")

    monkeypatch.setattr(
        module,
        "load_current_revision",
        lambda _: (_ for _ in ()).throw(
            AssertionError("local HEAD should not be used")
        ),
    )
    monkeypatch.setattr(module, "resolve_latest_remote_main_sha", lambda _: "newsha")
    monkeypatch.setattr(
        module,
        "load_changed_paths",
        lambda repo_root, base_sha, head_sha: ["freshquant/rear/api_server.py"],
    )
    monkeypatch.setattr(module, "load_deploy_plan_module", lambda _: fake_plan_module)
    monkeypatch.setattr(module, "execute_command", fail_on_health)
    monkeypatch.setattr(
        module,
        "utcnow",
        lambda: datetime(2026, 3, 17, 9, 0, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(RuntimeError, match="health check failed"):
        module.run_formal_deploy(
            repo_root=Path("."),
            state_path=state_path,
            runs_root=tmp_path / "runs",
            run_url="https://example.invalid/runs/3",
        )

    state = read_state(state_path)
    assert state["last_success_sha"] == "oldsha"
    assert state["last_attempt_sha"] == "newsha"


def test_orchestrator_runs_docker_and_host_surfaces_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    commands: list[list[str]] = []

    state_path = tmp_path / "production-state.json"
    write_state(
        state_path,
        {
            "last_success_sha": "oldsha",
            "last_attempt_sha": "oldsha",
            "last_attempt_at": "2026-03-16T00:00:00+00:00",
            "last_success_at": "2026-03-16T00:00:00+00:00",
            "last_deployed_surfaces": ["api"],
            "last_run_url": "https://example.invalid/runs/0",
        },
    )

    fake_plan_module = SimpleNamespace(
        SURFACE_ORDER=("api", "market_data"),
        HEALTH_CHECK_MAP={"api": ["http://127.0.0.1:15000/api/runtime/health/summary"]},
        build_deploy_plan=lambda changed_paths=None, explicit_surfaces=None: make_plan(
            surfaces=["api", "market_data"],
            docker_command=[
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                "script/docker_parallel_compose.ps1",
                "up",
                "-d",
                "--build",
                "fq_apiserver",
            ],
            host_command=[
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                "script/fqnext_host_runtime_ctl.ps1",
                "-Mode",
                "EnsureServiceAndRestartSurfaces",
                "-DeploymentSurface",
                "market_data",
                "-BridgeIfServiceUnavailable",
            ],
        ),
    )
    monkeypatch.setattr(
        module,
        "load_current_revision",
        lambda _: (_ for _ in ()).throw(
            AssertionError("local HEAD should not be used")
        ),
    )
    monkeypatch.setattr(module, "resolve_latest_remote_main_sha", lambda _: "newsha")
    monkeypatch.setattr(
        module,
        "load_changed_paths",
        lambda repo_root, base_sha, head_sha: [
            "freshquant/rear/api_server.py",
            "freshquant/market_data/xtdata/market_producer.py",
        ],
    )
    monkeypatch.setattr(module, "load_deploy_plan_module", lambda _: fake_plan_module)
    monkeypatch.setattr(
        module,
        "execute_command",
        lambda command, **_: commands.append(command),
    )
    monkeypatch.setattr(
        module,
        "utcnow",
        lambda: datetime(2026, 3, 17, 9, 30, 0, tzinfo=timezone.utc),
    )

    module.run_formal_deploy(
        repo_root=Path("."),
        state_path=state_path,
        runs_root=tmp_path / "runs",
        run_url="https://example.invalid/runs/4",
    )

    baseline_command = commands[0]
    verify_command = commands[-1]
    assert baseline_command[:5] == [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "script/check_freshquant_runtime_post_deploy.ps1",
    ]
    assert commands[1] == [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "script/docker_parallel_compose.ps1",
        "up",
        "-d",
        "--build",
        "fq_apiserver",
    ]
    assert commands[2][:10] == [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "script/fqnext_host_runtime_ctl.ps1",
        "-Mode",
        "EnsureServiceAndRestartSurfaces",
        "-DeploymentSurface",
        "market_data",
        "-BridgeIfServiceUnavailable",
    ]
    assert commands[2][-2:] == [
        "-SupervisorConfigRepoRoot",
        str(Path(".").resolve()),
    ]
    assert commands[3] == [
        sys.executable,
        "script/freshquant_health_check.py",
        "--surface",
        "api",
        "--format",
        "summary",
    ]
    assert verify_command[:5] == [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "script/check_freshquant_runtime_post_deploy.ps1",
    ]
    assert verify_command[-1] == "api,market_data"


def test_health_checks_use_current_python_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    commands: list[list[str]] = []

    state_path = tmp_path / "production-state.json"
    write_state(
        state_path,
        {
            "last_success_sha": "oldsha",
            "last_attempt_sha": "oldsha",
            "last_attempt_at": "2026-03-16T00:00:00+00:00",
            "last_success_at": "2026-03-16T00:00:00+00:00",
            "last_deployed_surfaces": ["api"],
            "last_run_url": "https://example.invalid/runs/0",
        },
    )

    fake_plan_module = SimpleNamespace(
        SURFACE_ORDER=("api",),
        HEALTH_CHECK_MAP={"api": ["http://127.0.0.1:15000/api/runtime/health/summary"]},
        build_deploy_plan=lambda changed_paths=None, explicit_surfaces=None: make_plan(
            surfaces=["api"]
        ),
    )

    monkeypatch.setattr(module, "resolve_latest_remote_main_sha", lambda _: "newsha")
    monkeypatch.setattr(
        module,
        "load_changed_paths",
        lambda repo_root, base_sha, head_sha: ["freshquant/rear/api_server.py"],
    )
    monkeypatch.setattr(module, "load_deploy_plan_module", lambda _: fake_plan_module)
    monkeypatch.setattr(
        module,
        "execute_command",
        lambda command, **_: commands.append(command),
    )
    monkeypatch.setattr(
        module,
        "utcnow",
        lambda: datetime(2026, 3, 17, 11, 0, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(module.sys, "executable", r"C:\tooling\mirror-python.exe")

    module.run_formal_deploy(
        repo_root=Path("."),
        state_path=state_path,
        runs_root=tmp_path / "runs",
        run_url="https://example.invalid/runs/7",
    )

    assert commands[1] == [
        r"C:\tooling\mirror-python.exe",
        "script/freshquant_health_check.py",
        "--surface",
        "api",
        "--format",
        "summary",
    ]


def test_noop_run_skips_deploy_commands_and_advances_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    commands: list[list[str]] = []

    state_path = tmp_path / "production-state.json"
    write_state(
        state_path,
        {
            "last_success_sha": "oldsha",
            "last_attempt_sha": "oldsha",
            "last_attempt_at": "2026-03-16T00:00:00+00:00",
            "last_success_at": "2026-03-16T00:00:00+00:00",
            "last_deployed_surfaces": ["api"],
            "last_run_url": "https://example.invalid/runs/0",
        },
    )

    fake_plan_module = SimpleNamespace(
        SURFACE_ORDER=("api", "web"),
        HEALTH_CHECK_MAP={},
        build_deploy_plan=lambda changed_paths=None, explicit_surfaces=None: make_plan(
            surfaces=[]
        ),
    )

    monkeypatch.setattr(
        module,
        "load_current_revision",
        lambda _: (_ for _ in ()).throw(
            AssertionError("local HEAD should not be used")
        ),
    )
    monkeypatch.setattr(module, "resolve_latest_remote_main_sha", lambda _: "newsha")
    monkeypatch.setattr(
        module,
        "load_changed_paths",
        lambda repo_root, base_sha, head_sha: ["docs/current/deployment.md"],
    )
    monkeypatch.setattr(module, "load_deploy_plan_module", lambda _: fake_plan_module)
    monkeypatch.setattr(
        module,
        "execute_command",
        lambda command, **_: commands.append(command),
    )
    monkeypatch.setattr(
        module,
        "utcnow",
        lambda: datetime(2026, 3, 17, 10, 0, 0, tzinfo=timezone.utc),
    )

    result = module.run_formal_deploy(
        repo_root=Path("."),
        state_path=state_path,
        runs_root=tmp_path / "runs",
        run_url="https://example.invalid/runs/5",
    )

    state = read_state(state_path)
    assert result["plan"]["deployment_required"] is False
    assert commands == []
    assert state["last_success_sha"] == "newsha"
    assert state["last_deployed_surfaces"] == []


def test_incremental_run_without_git_dir_uses_compare_api_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    commands: list[list[str]] = []
    repo_root = tmp_path / "archive-repo"
    repo_root.mkdir()

    state_path = tmp_path / "production-state.json"
    write_state(
        state_path,
        {
            "last_success_sha": "oldsha",
            "last_attempt_sha": "oldsha",
            "last_attempt_at": "2026-03-16T00:00:00+00:00",
            "last_success_at": "2026-03-16T00:00:00+00:00",
            "last_deployed_surfaces": ["api"],
            "last_run_url": "https://example.invalid/runs/0",
        },
    )

    fake_plan_module = SimpleNamespace(
        SURFACE_ORDER=("web",),
        HEALTH_CHECK_MAP={},
        build_deploy_plan=lambda changed_paths=None, explicit_surfaces=None: make_plan(
            surfaces=["web"]
        ),
    )

    def unexpected_git_diff(*_args: object, **_kwargs: object) -> list[str]:
        raise AssertionError("git diff should not run without .git")

    monkeypatch.setattr(module, "load_current_revision", lambda _: "newsha")
    monkeypatch.setattr(module, "load_changed_paths", unexpected_git_diff)
    monkeypatch.setattr(
        module,
        "load_changed_paths_from_compare_api",
        lambda repository, base_sha, head_sha, github_token: [
            "morningglory/fqwebui/src/App.vue"
        ],
    )
    monkeypatch.setattr(module, "load_deploy_plan_module", lambda _: fake_plan_module)
    monkeypatch.setattr(
        module,
        "execute_command",
        lambda command, **_: commands.append(command),
    )
    monkeypatch.setattr(
        module,
        "utcnow",
        lambda: datetime(2026, 3, 17, 10, 30, 0, tzinfo=timezone.utc),
    )

    result = module.run_formal_deploy(
        repo_root=repo_root,
        state_path=state_path,
        runs_root=tmp_path / "runs",
        head_sha="newsha",
        run_url="https://example.invalid/runs/6",
        github_repository="dao1oad/fqpack-next",
    )

    assert result["changed_paths"] == ["morningglory/fqwebui/src/App.vue"]
    assert result["plan"]["deployment_surfaces"] == ["web"]
    assert read_state(state_path)["last_success_sha"] == "newsha"


def test_default_artifacts_paths_use_neutral_runtime_root() -> None:
    module = load_module()

    assert module.DEFAULT_ARTIFACTS_ROOT == Path(r"D:\fqpack\runtime\formal-deploy")
    assert module.default_state_path(module.DEFAULT_ARTIFACTS_ROOT) == (
        module.DEFAULT_ARTIFACTS_ROOT / "production-state.json"
    )
    assert module.default_runs_root(module.DEFAULT_ARTIFACTS_ROOT) == (
        module.DEFAULT_ARTIFACTS_ROOT / "runs"
    )


def test_formal_deploy_source_no_longer_references_runtime_symphony() -> None:
    text = Path("script/ci/run_formal_deploy.py").read_text(encoding="utf-8")

    assert "runtime/symphony" not in text
    assert "build_symphony_commands" not in text


def test_formal_deploy_cli_accepts_head_sha() -> None:
    module = load_module()

    args = module.build_parser().parse_args(["--head-sha", "abc123"])

    assert args.head_sha == "abc123"
