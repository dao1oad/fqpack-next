from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.append(str(SCRIPT_DIR))

from formal_deploy_state import (  # noqa: E402
    acquire_deploy_lock,
    load_deploy_state,
    release_deploy_lock,
    write_deploy_state,
)

DEFAULT_ARTIFACTS_ROOT = Path(r"D:\fqpack\runtime\formal-deploy")


def repo_root_default() -> Path:
    return Path(__file__).resolve().parents[2]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def default_state_path(artifacts_root: Path) -> Path:
    return artifacts_root / "production-state.json"


def default_runs_root(artifacts_root: Path) -> Path:
    return artifacts_root / "runs"


def load_current_revision(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def resolve_latest_remote_main_sha(repo_root: Path) -> str:
    subprocess.run(
        ["git", "-C", str(repo_root), "fetch", "origin", "main"],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "origin/main"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def load_changed_paths(repo_root: Path, base_sha: str, head_sha: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--name-only", base_sha, head_sha],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def load_changed_paths_from_compare_api(
    repository: str,
    base_sha: str,
    head_sha: str,
    github_token: str | None,
) -> list[str]:
    if not github_token:
        raise RuntimeError(
            "GH_TOKEN is required when formal deploy runs without a local git repository"
        )

    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/compare/{base_sha}...{head_sha}",
        headers={
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "fqpack-formal-deploy",
        },
    )
    with urllib.request.urlopen(request) as response:
        payload = json.loads(response.read().decode("utf-8"))

    changed_paths: list[str] = []
    for item in payload.get("files", []):
        filename = str(item.get("filename", "")).strip()
        previous_filename = str(item.get("previous_filename", "")).strip()
        if filename:
            changed_paths.append(filename)
        if previous_filename:
            changed_paths.append(previous_filename)
    return changed_paths


def resolve_changed_paths(
    repo_root: Path,
    base_sha: str,
    head_sha: str,
    *,
    github_repository: str | None,
) -> list[str]:
    if (repo_root / ".git").exists():
        return load_changed_paths(repo_root, base_sha, head_sha)
    if not github_repository:
        raise RuntimeError(
            "incremental formal deploy requires a git repository or --github-repository"
        )
    return load_changed_paths_from_compare_api(
        github_repository,
        base_sha,
        head_sha,
        os.environ.get("GH_TOKEN"),
    )


def load_deploy_plan_module(repo_root: Path):
    module_path = repo_root / "script" / "freshquant_deploy_plan.py"
    spec = importlib.util.spec_from_file_location("freshquant_deploy_plan", module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"unable to load deploy plan module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def execute_command(
    command: list[str],
    *,
    repo_root: Path,
    output_path: Path | None = None,
) -> None:
    result = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            (result.stdout or "") + (result.stderr or ""),
            encoding="utf-8",
        )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}")


def build_capture_baseline_command(output_path: Path) -> list[str]:
    return [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "script/check_freshquant_runtime_post_deploy.ps1",
        "-Mode",
        "CaptureBaseline",
        "-OutputPath",
        str(output_path),
    ]


def build_verify_runtime_command(
    baseline_path: Path,
    output_path: Path,
    deployment_surfaces: list[str],
) -> list[str]:
    return [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "script/check_freshquant_runtime_post_deploy.ps1",
        "-Mode",
        "Verify",
        "-BaselinePath",
        str(baseline_path),
        "-OutputPath",
        str(output_path),
        "-DeploymentSurface",
        ",".join(deployment_surfaces),
    ]


def build_health_commands(plan: dict[str, Any], plan_module) -> list[list[str]]:
    commands: list[list[str]] = []
    health_surface_map = getattr(plan_module, "HEALTH_CHECK_MAP", {})
    for surface in plan["deployment_surfaces"]:
        if surface not in health_surface_map:
            continue
        commands.append(
            [
                "py",
                "-3.12",
                "script/freshquant_health_check.py",
                "--surface",
                surface,
                "--format",
                "summary",
            ]
        )
    return commands


def build_plan(
    plan_module, bootstrap: bool, changed_paths: list[str]
) -> dict[str, Any]:
    if bootstrap:
        return plan_module.build_deploy_plan(
            explicit_surfaces=list(plan_module.SURFACE_ORDER)
        )
    return plan_module.build_deploy_plan(changed_paths=changed_paths)


def run_formal_deploy(
    *,
    repo_root: Path,
    state_path: Path,
    runs_root: Path,
    head_sha: str | None = None,
    run_url: str | None = None,
    github_repository: str | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    state_path = Path(state_path)
    runs_root = Path(runs_root)
    lock_path = state_path.with_name(state_path.name + ".lock")
    lock = acquire_deploy_lock(lock_path)
    try:
        previous_state = load_deploy_state(state_path)
        current_sha = head_sha or resolve_latest_remote_main_sha(repo_root)
        attempt_at = utcnow()
        attempt_at_iso = isoformat(attempt_at)
        run_dir = (
            runs_root / f"{attempt_at.strftime('%Y%m%dT%H%M%SZ')}-{current_sha[:12]}"
        )
        run_dir.mkdir(parents=True, exist_ok=True)

        state = dict(previous_state)
        state["last_attempt_sha"] = current_sha
        state["last_attempt_at"] = attempt_at_iso
        state["last_run_url"] = run_url or previous_state.get("last_run_url")
        write_deploy_state(state_path, state)

        plan_module = load_deploy_plan_module(repo_root)
        bootstrap = not previous_state.get("last_success_sha")
        changed_paths = (
            []
            if bootstrap
            else resolve_changed_paths(
                repo_root,
                str(previous_state["last_success_sha"]),
                current_sha,
                github_repository=github_repository,
            )
        )
        plan = build_plan(plan_module, bootstrap, changed_paths)

        write_json(
            run_dir / "plan.json",
            {
                "bootstrap": bootstrap,
                "changed_paths": changed_paths,
                "plan": plan,
            },
        )

        commands: list[list[str]] = []
        if plan["deployment_required"]:
            baseline_path = run_dir / "runtime-baseline.json"
            verify_path = run_dir / "runtime-verify.json"

            capture_command = build_capture_baseline_command(baseline_path)
            commands.append(capture_command)
            execute_command(
                capture_command,
                repo_root=repo_root,
                output_path=run_dir / "01-runtime-baseline.log",
            )

            if plan["docker_command"]:
                commands.append(list(plan["docker_command"]))
                execute_command(
                    list(plan["docker_command"]),
                    repo_root=repo_root,
                    output_path=run_dir / "10-docker-deploy.log",
                )

            if plan["host_command"]:
                commands.append(list(plan["host_command"]))
                execute_command(
                    list(plan["host_command"]),
                    repo_root=repo_root,
                    output_path=run_dir / "11-host-deploy.log",
                )

            for index, health_command in enumerate(
                build_health_commands(plan, plan_module),
                start=20,
            ):
                commands.append(health_command)
                execute_command(
                    health_command,
                    repo_root=repo_root,
                    output_path=run_dir / f"{index:02d}-health.log",
                )

            verify_command = build_verify_runtime_command(
                baseline_path,
                verify_path,
                list(plan["runtime_ops_surfaces"]),
            )
            commands.append(verify_command)
            execute_command(
                verify_command,
                repo_root=repo_root,
                output_path=run_dir / "30-runtime-verify.log",
            )

        success_state = dict(state)
        success_state["last_success_sha"] = current_sha
        success_state["last_success_at"] = attempt_at_iso
        success_state["last_deployed_surfaces"] = list(plan["deployment_surfaces"])
        success_state["last_run_url"] = run_url or state.get("last_run_url")
        write_deploy_state(state_path, success_state)

        result = {
            "ok": True,
            "bootstrap": bootstrap,
            "current_sha": current_sha,
            "changed_paths": changed_paths,
            "plan": plan,
            "commands": commands,
            "run_dir": str(run_dir),
            "state_path": str(state_path),
        }
        write_json(run_dir / "result.json", result)
        return result
    except Exception as exc:
        failure_result = {
            "ok": False,
            "error": str(exc),
            "state_path": str(state_path),
        }
        if "run_dir" in locals():
            write_json(run_dir / "result.json", failure_result)
        raise
    finally:
        release_deploy_lock(lock)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run formal FreshQuant production deploy."
    )
    parser.add_argument("--repo-root", default=str(repo_root_default()))
    parser.add_argument("--artifacts-root", default=str(DEFAULT_ARTIFACTS_ROOT))
    parser.add_argument("--state-path")
    parser.add_argument("--runs-root")
    parser.add_argument("--run-url")
    parser.add_argument("--github-repository")
    parser.add_argument("--format", choices=("json", "summary"), default="json")
    return parser


def render_summary(result: dict[str, Any]) -> str:
    plan = result["plan"]
    lines = [
        "formal deploy",
        f"ok: {str(result['ok']).lower()}",
        f"bootstrap: {str(result['bootstrap']).lower()}",
        f"current_sha: {result['current_sha']}",
        "deployment_surfaces: " + (", ".join(plan["deployment_surfaces"]) or "none"),
        f"run_dir: {result['run_dir']}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.repo_root)
    artifacts_root = Path(args.artifacts_root)
    state_path = (
        Path(args.state_path) if args.state_path else default_state_path(artifacts_root)
    )
    runs_root = (
        Path(args.runs_root) if args.runs_root else default_runs_root(artifacts_root)
    )
    try:
        result = run_formal_deploy(
            repo_root=repo_root,
            state_path=state_path,
            runs_root=runs_root,
            run_url=args.run_url,
            github_repository=args.github_repository,
        )
    except Exception as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        return 1

    if args.format == "summary":
        print(render_summary(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
