#!/usr/bin/env python3
"""Plan, install, or check the autonomous governance scaffold."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "1.3.0"
SKILL_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = SKILL_ROOT / "assets" / "project-governance"
PROJECT_SKILL_ROOT = Path(".agents/skills")
BOOTSTRAP_SKILL_REL = PROJECT_SKILL_ROOT / "bootstrap-project-governance"
GRILLING_SKILL_REL = PROJECT_SKILL_ROOT / "grilling"
TOOL_MARKER = 'TOOL_ID = "bootstrap-project-governance/runtime"'
BOOTSTRAP_SKILL_MARKER = "Install a small repository-local governance runtime shared by Codex and Devin"
GRILLING_SKILL_MARKER = "Project-governance startup applies this protocol inline"
AGENTS_BEGIN = "<!-- BEGIN BOOTSTRAP-PROJECT-GOVERNANCE -->"
AGENTS_END = "<!-- END BOOTSTRAP-PROJECT-GOVERNANCE -->"


class BootstrapError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "project"


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BootstrapError(f"缺少文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise BootstrapError(f"JSON 格式错误：{path}:{exc.lineno}:{exc.colno}") from exc
    if not isinstance(value, dict):
        raise BootstrapError(f"JSON 根节点应为对象：{path}")
    return value


def render(path: Path, tokens: dict[str, str]) -> bytes:
    text = path.read_text(encoding="utf-8")
    for key, value in tokens.items():
        text = text.replace("{{" + key + "}}", value)
    return text.replace("\r\n", "\n").encode("utf-8")


def governance_hook_group(host: str) -> dict[str, Any]:
    if host == "codex":
        template = load_json(ASSET_ROOT / ".codex" / "hooks.json.template")
        return template["hooks"]["Stop"][0]
    if host == "devin":
        template = load_json(ASSET_ROOT / ".devin" / "hooks.v1.json.template")
        group = template["Stop"][0]
        group["hooks"][0]["command"] = devin_stop_command()
        return group
    raise BootstrapError(f"未知 Hook 宿主：{host}")


def devin_stop_command() -> str:
    if os.name == "nt":
        return (
            'powershell.exe -NoLogo -NoProfile -NonInteractive -Command "'
            "$p=Join-Path $env:DEVIN_PROJECT_DIR 'tools/governance.py'; "
            "if(Get-Command py -ErrorAction SilentlyContinue){"
            "& py -3 -X utf8 $p hook-stop --repo $env:DEVIN_PROJECT_DIR"
            "}else{"
            "& python -X utf8 $p hook-stop --repo $env:DEVIN_PROJECT_DIR"
            '}"'
        )
    return 'python3 "$DEVIN_PROJECT_DIR/tools/governance.py" hook-stop --repo "$DEVIN_PROJECT_DIR"'


def handler_is_governance(handler: Any) -> bool:
    if not isinstance(handler, dict):
        return False
    text = f"{handler.get('command', '')} {handler.get('commandWindows', '')}"
    return "governance.py" in text and "hook-stop" in text


def hook_map(config: dict[str, Any], host: str) -> dict[str, Any] | None:
    if host == "codex":
        value = config.get("hooks")
        return value if isinstance(value, dict) else None
    if host == "devin":
        return config
    raise BootstrapError(f"未知 Hook 宿主：{host}")


def has_governance_hook(config: dict[str, Any], host: str) -> bool:
    hooks = hook_map(config, host)
    groups = hooks.get("Stop", []) if isinstance(hooks, dict) else []
    if not isinstance(groups, list):
        return False
    for group in groups:
        handlers = group.get("hooks", []) if isinstance(group, dict) else []
        for handler in handlers if isinstance(handlers, list) else []:
            if handler_is_governance(handler):
                return True
    return False


def merge_hooks(path: Path, host: str) -> str:
    if path.exists():
        config = load_json(path)
    else:
        config = {"description": "Project lifecycle hooks.", "hooks": {}} if host == "codex" else {}
    if host == "codex":
        hooks = config.setdefault("hooks", {})
    else:
        hooks = config
    if not isinstance(hooks, dict):
        raise BootstrapError(f"hooks 字段应为对象：{path}")
    stop = hooks.setdefault("Stop", [])
    if not isinstance(stop, list):
        raise BootstrapError(f"hooks.Stop 应为数组：{path}")
    expected_group = governance_hook_group(host)
    expected_handler = expected_group["hooks"][0]
    action = "merge" if len(stop) else "create"
    found = False
    for group in stop:
        handlers = group.get("hooks", []) if isinstance(group, dict) else []
        for index, handler in enumerate(handlers if isinstance(handlers, list) else []):
            if not handler_is_governance(handler):
                continue
            found = True
            if handler == expected_handler:
                return "preserve"
            handlers[index] = expected_handler
            action = "update"
            break
        if found:
            break
    if not found:
        stop.append(expected_group)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    return action


def managed_agents_block() -> str:
    return (ASSET_ROOT / "AGENTS.md.template").read_text(encoding="utf-8").strip()


def agents_action(path: Path) -> str:
    if not path.exists():
        return "create"
    text = path.read_text(encoding="utf-8", errors="replace")
    if AGENTS_BEGIN in text and AGENTS_END in text:
        return "update-managed-block"
    return "append-managed-block"


def merge_agents(path: Path) -> str:
    block = managed_agents_block()
    action = agents_action(path)
    if action == "create":
        path.write_text(block + "\n", encoding="utf-8", newline="\n")
        return action
    text = path.read_text(encoding="utf-8")
    if AGENTS_BEGIN in text and AGENTS_END in text:
        pattern = re.compile(re.escape(AGENTS_BEGIN) + r".*?" + re.escape(AGENTS_END), re.DOTALL)
        text = pattern.sub(block, text)
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    return action


def managed_tool(path: Path) -> bool:
    if not path.is_file():
        return False
    return TOOL_MARKER in path.read_text(encoding="utf-8", errors="ignore")


def managed_skill(path: Path, marker: str) -> bool:
    skill = path / "SKILL.md"
    return skill.is_file() and marker in skill.read_text(encoding="utf-8", errors="ignore")


def project_skill_action(repo: Path, relative: Path, marker: str, upgrade: bool) -> str:
    target = repo / relative
    if not target.exists():
        return "create"
    if not managed_skill(target, marker):
        return "conflict"
    return "update" if upgrade else "preserve"


def copy_bootstrap_skill(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SKILL_ROOT / "SKILL.md", target / "SKILL.md")
    for name in ("assets", "references", "scripts"):
        shutil.copytree(
            SKILL_ROOT / name,
            target / name,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )


def copy_grilling_skill(target: Path) -> None:
    source = ASSET_ROOT / ".agents" / "skills" / "grilling" / "SKILL.md.template"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target / "SKILL.md")


def build_plan(repo: Path, project_name: str, upgrade: bool) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    tool_target = repo / "tools" / "governance.py"
    if not tool_target.exists():
        tool_action = "create"
    elif managed_tool(tool_target):
        tool_action = "update" if upgrade else "preserve"
    else:
        tool_action = "conflict"
    operations.append({"path": "tools/governance.py", "action": tool_action})

    for relative in (".governance/project.json", ".governance/work.json", ".governance/events.jsonl"):
        operations.append({"path": relative, "action": "preserve" if (repo / relative).exists() else "create"})

    for relative, host in ((".codex/hooks.json", "codex"), (".devin/hooks.v1.json", "devin")):
        hooks_path = repo / relative
        if hooks_path.exists():
            try:
                hooks = load_json(hooks_path)
                hook_action = "preserve" if has_governance_hook(hooks, host) else "merge"
            except BootstrapError:
                hook_action = "conflict"
        else:
            hook_action = "create"
        operations.append({"path": relative, "action": hook_action})
    operations.append({"path": "AGENTS.md", "action": agents_action(repo / "AGENTS.md")})
    operations.append(
        {
            "path": BOOTSTRAP_SKILL_REL.as_posix(),
            "action": project_skill_action(repo, BOOTSTRAP_SKILL_REL, BOOTSTRAP_SKILL_MARKER, upgrade),
        }
    )
    operations.append(
        {
            "path": GRILLING_SKILL_REL.as_posix(),
            "action": project_skill_action(repo, GRILLING_SKILL_REL, GRILLING_SKILL_MARKER, upgrade),
        }
    )
    return {
        "schemaVersion": 1,
        "bootstrapVersion": VERSION,
        "repo": str(repo),
        "projectName": project_name,
        "projectId": slug(project_name),
        "upgrade": upgrade,
        "operations": operations,
        "applicable": not any(operation["action"] == "conflict" for operation in operations),
    }


def apply(repo: Path, project_name: str, upgrade: bool) -> dict[str, Any]:
    repo.mkdir(parents=True, exist_ok=True)
    plan = build_plan(repo, project_name, upgrade)
    conflicts = [operation for operation in plan["operations"] if operation["action"] == "conflict"]
    if conflicts:
        paths = ", ".join(operation["path"] for operation in conflicts)
        raise BootstrapError(f"以下路径存在非托管冲突：{paths}")

    tokens = {
        "PROJECT_ID": slug(project_name),
        "PROJECT_NAME": project_name,
        "INITIALIZED_AT": now_iso(),
    }
    applied: list[dict[str, str]] = []
    tool_target = repo / "tools" / "governance.py"
    tool_source = ASSET_ROOT / "tools" / "governance.py"
    tool_existed = tool_target.exists()
    if not tool_target.exists() or (upgrade and managed_tool(tool_target)):
        tool_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tool_source, tool_target)
        applied.append({"path": "tools/governance.py", "action": "update" if tool_existed else "create"})

    template_pairs = (
        (ASSET_ROOT / ".governance" / "project.json.template", repo / ".governance" / "project.json"),
        (ASSET_ROOT / ".governance" / "work.json.template", repo / ".governance" / "work.json"),
        (ASSET_ROOT / ".governance" / "events.jsonl.empty", repo / ".governance" / "events.jsonl"),
    )
    for source, target in template_pairs:
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(render(source, tokens))
        applied.append({"path": target.relative_to(repo).as_posix(), "action": "create"})
    (repo / ".governance" / "runs").mkdir(parents=True, exist_ok=True)
    for relative, host in ((".codex/hooks.json", "codex"), (".devin/hooks.v1.json", "devin")):
        hook_action = merge_hooks(repo / relative, host)
        applied.append({"path": relative, "action": hook_action})
    agent_action = merge_agents(repo / "AGENTS.md")
    applied.append({"path": "AGENTS.md", "action": agent_action})
    bootstrap_skill_action = project_skill_action(repo, BOOTSTRAP_SKILL_REL, BOOTSTRAP_SKILL_MARKER, upgrade)
    if bootstrap_skill_action in {"create", "update"}:
        copy_bootstrap_skill(repo / BOOTSTRAP_SKILL_REL)
    applied.append({"path": BOOTSTRAP_SKILL_REL.as_posix(), "action": bootstrap_skill_action})
    grilling_skill_action = project_skill_action(repo, GRILLING_SKILL_REL, GRILLING_SKILL_MARKER, upgrade)
    if grilling_skill_action in {"create", "update"}:
        copy_grilling_skill(repo / GRILLING_SKILL_REL)
    applied.append({"path": GRILLING_SKILL_REL.as_posix(), "action": grilling_skill_action})
    return {"applied": applied, "repo": str(repo), "next": ["edit project.json and work.json", "review hook trust", "governance.py ready", "governance.py start"]}


def check_install(repo: Path) -> dict[str, Any]:
    issues: list[str] = []
    tool = repo / "tools" / "governance.py"
    if not managed_tool(tool):
        issues.append("tools/governance.py 缺失或不是托管版本")
    for relative in (".governance/project.json", ".governance/work.json", ".governance/events.jsonl"):
        if not (repo / relative).is_file():
            issues.append(f"缺少 {relative}")
    for relative, host, label in (
        (".codex/hooks.json", "codex", "Codex"),
        (".devin/hooks.v1.json", "devin", "Devin"),
    ):
        hooks = repo / relative
        if not hooks.is_file() or not has_governance_hook(load_json(hooks), host):
            issues.append(f"{label} 治理 Stop Hook 缺失")
    agents = repo / "AGENTS.md"
    if not agents.is_file():
        issues.append("AGENTS.md 缺失")
    else:
        text = agents.read_text(encoding="utf-8", errors="replace")
        if AGENTS_BEGIN not in text or AGENTS_END not in text:
            issues.append("AGENTS.md 缺少治理托管区块")
    for relative, marker, label in (
        (BOOTSTRAP_SKILL_REL, BOOTSTRAP_SKILL_MARKER, "项目级 bootstrap-project-governance Skill"),
        (GRILLING_SKILL_REL, GRILLING_SKILL_MARKER, "项目级 grilling Skill"),
    ):
        if not managed_skill(repo / relative, marker):
            issues.append(f"{label} 缺失")
    return {"installed": not issues, "issues": issues, "repo": str(repo)}


def run_cli(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser().resolve()
    project_name = getattr(args, "project_name", None) or repo.name
    if args.command == "plan":
        payload = build_plan(repo, project_name, args.upgrade)
    elif args.command == "apply":
        payload = apply(repo, project_name, args.upgrade)
    else:
        payload = check_install(repo)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if getattr(args, "out", None):
        Path(args.out).expanduser().resolve().write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if payload.get("applicable", payload.get("installed", True)) else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--version", action="version", version=VERSION)
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("plan", "apply"):
        command = sub.add_parser(name)
        command.add_argument("--repo", required=True)
        command.add_argument("--project-name")
        command.add_argument("--upgrade", action="store_true")
        command.add_argument("--out")
        command.set_defaults(func=run_cli)
    check = sub.add_parser("check")
    check.add_argument("--repo", required=True)
    check.add_argument("--out")
    check.set_defaults(func=run_cli)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except BootstrapError as exc:
        print(f"bootstrap-governance: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
