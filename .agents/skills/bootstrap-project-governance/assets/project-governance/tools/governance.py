#!/usr/bin/env python3
"""Deterministic runtime for autonomous project governance."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


TOOL_ID = "bootstrap-project-governance/runtime"
TOOL_VERSION = "1.2.0"
# Stable evidence-protocol identifier. Keep it unchanged for host adapters,
# board rendering, and other changes that do not alter Gate execution or
# evidence identity semantics. Bump it deliberately when those semantics change.
RUNNER_EVIDENCE_DIGEST = "11a9f3ddac7109285e71fd492e1018a459f90a484fca830d1163b84b24cb6329"
SCHEMA_VERSION = 1
PROJECT_REL = ".governance/project.json"
WORK_REL = ".governance/work.json"
EVENTS_REL = ".governance/events.jsonl"
BOARD_REL = ".governance/board.html"
RUNS_REL = ".governance/runs"
CODEX_HOOKS_REL = ".codex/hooks.json"
DEVIN_HOOKS_REL = ".devin/hooks.v1.json"
HOOK_RELS = (CODEX_HOOKS_REL, DEVIN_HOOKS_REL)

LEVELS = {"V0": 0, "V1": 1, "V2": 2}
DATA_MODES = {"mock", "fixture", "synthetic", "real"}
BUCKETS = {"NOW", "NEXT", "LATER"}
TERMINAL_TYPES = {"PROJECT_COMPLETED", "AUTONOMY_EXHAUSTED"}
WORK_EVENT_TYPES = {
    "WORK_STARTED",
    "WORK_IMPLEMENTED",
    "WORK_DEFERRED",
    "WORK_REOPENED",
}
RUNTIME_EVENT_TYPES = {
    *WORK_EVENT_TYPES,
    "REPLAN_STARTED",
    "REPLAN_FINISHED",
    "DEGRADATION_STARTED",
    "DEGRADATION_ENDED",
    "FALLBACK_ACTIVATED",
    "FALLBACK_CLEARED",
}
PREFLIGHT_KEYS = (
    "goalAndBoundariesConfirmed",
    "repositoryRootVerified",
    "credentialsAndPermissionsVerified",
    "externalDependenciesProbed",
    "fallbacksDefined",
    "budgetsConfirmed",
    "finalAcceptanceConfirmed",
    "hookTrustReviewed",
)
SOURCE_EXCLUDED_DIRS = {
    ".git",
    ".governance",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


class GovernanceError(RuntimeError):
    """A deterministic governance failure."""


@dataclass
class Model:
    root: Path
    project: dict[str, Any]
    work: dict[str, Any]
    events: list[dict[str, Any]]

    @property
    def gates(self) -> dict[str, dict[str, Any]]:
        return {str(g.get("id")): g for g in self.work.get("gates", []) if g.get("id")}

    @property
    def items(self) -> dict[str, dict[str, Any]]:
        return {str(i.get("id")): i for i in self.work.get("items", []) if i.get("id")}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GovernanceError(f"缺少治理文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise GovernanceError(f"JSON 格式错误：{path}:{exc.lineno}:{exc.colno}") from exc
    if not isinstance(value, dict):
        raise GovernanceError(f"治理文件根节点应为对象：{path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise GovernanceError(f"缺少事件日志：{path}")
    result: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GovernanceError(f"事件日志格式错误：{path}:{line_number}:{exc.colno}") from exc
        if not isinstance(value, dict):
            raise GovernanceError(f"事件应为对象：{path}:{line_number}")
        result.append(value)
    return result


def atomic_write(path: Path, content: bytes) -> bool:
    if path.exists() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return True


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_bytes(value) + b"\n"
    with path.open("ab") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def resolve_root(raw: str | None = None) -> Path:
    start = Path(raw).expanduser() if raw else Path.cwd()
    start = start.resolve()
    if start.is_file():
        start = start.parent
    for candidate in (start, *start.parents):
        if (candidate / PROJECT_REL).is_file():
            return candidate
    if raw:
        return start
    raise GovernanceError(f"从当前目录向上未找到 {PROJECT_REL}")


def load_model(root: Path) -> Model:
    return Model(
        root=root,
        project=read_json(root / PROJECT_REL),
        work=read_json(root / WORK_REL),
        events=read_jsonl(root / EVENTS_REL),
    )


def event_id(prefix: str = "evt") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


def append_event(model: Model, event_type: str, **fields: Any) -> dict[str, Any]:
    event = {"id": event_id(), "type": event_type, "at": utc_now(), **fields}
    append_jsonl(model.root / EVENTS_REL, event)
    model.events.append(event)
    return event


def project_digest(project: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(project))


def work_digest(work: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(work))


def build_work_lock(model: Model) -> dict[str, Any]:
    claims = model.project.get("finalAcceptance", {}).get("claims", [])
    final_gate_ids = sorted(
        {
            str(claim.get("gateRef"))
            for claim in claims
            if isinstance(claim, dict) and str(claim.get("gateRef", "")).strip()
        }
    )
    required_items = [
        json.loads(json.dumps(item, ensure_ascii=False))
        for item in model.work.get("items", [])
        if isinstance(item, dict) and item.get("requiredForFinal") is True
    ]
    required_gate_ids = sorted(
        {
            str(gate_ref)
            for item in required_items
            for gate_ref in item.get("gateRefs", [])
            if str(gate_ref).strip()
        }
    )
    required_gates = []
    for gate_id in required_gate_ids:
        gate = model.gates.get(gate_id)
        if gate is not None:
            required_gates.append(json.loads(json.dumps(gate, ensure_ascii=False)))
    final_gates = []
    for gate_id in final_gate_ids:
        gate = model.gates.get(gate_id)
        if gate is not None:
            final_gates.append(json.loads(json.dumps(gate, ensure_ascii=False)))
    return {
        "requiredItems": required_items,
        "requiredGates": required_gates,
        "finalClaimGates": final_gates,
    }


def locked_work_snapshot(model: Model) -> dict[str, Any] | None:
    start = started_event(model)
    if start is None:
        return None
    value = start.get("workLock")
    return value if isinstance(value, dict) else None


def work_lock_issues(model: Model) -> list[str]:
    start = started_event(model)
    if start is None:
        return []
    locked = locked_work_snapshot(model)
    if locked is None:
        return ["AUTONOMY_STARTED 缺少 workLock"]

    issues: list[str] = []
    expected_digest = start.get("workLockDigest")
    if not isinstance(expected_digest, str) or sha256_bytes(canonical_bytes(locked)) != expected_digest:
        issues.append("AUTONOMY_STARTED workLock 摘要不匹配")
    required_items = locked.get("requiredItems")
    required_gates = locked.get("requiredGates")
    final_gates = locked.get("finalClaimGates")
    if not isinstance(required_items, list) or not isinstance(required_gates, list) or not isinstance(final_gates, list):
        return ["AUTONOMY_STARTED workLock 格式错误"]

    for locked_item in required_items:
        if not isinstance(locked_item, dict):
            issues.append("workLock.requiredItems 包含非法记录")
            continue
        item_id = str(locked_item.get("id", ""))
        current = model.items.get(item_id)
        if current is None:
            issues.append(f"锁定的 requiredForFinal 工作项缺失：{item_id}")
            continue
        if current.get("requiredForFinal") is not True:
            issues.append(f"锁定的工作项不再 requiredForFinal：{item_id}")
        locked_refs = {str(value) for value in locked_item.get("gateRefs", [])}
        current_refs = {str(value) for value in current.get("gateRefs", [])}
        missing_refs = sorted(locked_refs - current_refs)
        if missing_refs:
            issues.append(f"锁定的工作项 Gate 被移除：{item_id} -> {','.join(missing_refs)}")
        locked_scopes = {str(value) for value in locked_item.get("pathScopes", [])}
        current_scopes = {str(value) for value in current.get("pathScopes", [])}
        missing_scopes = sorted(locked_scopes - current_scopes)
        if missing_scopes:
            issues.append(f"锁定的工作项 pathScopes 被缩窄：{item_id} -> {','.join(missing_scopes)}")

    for locked_gate in required_gates:
        if not isinstance(locked_gate, dict):
            issues.append("workLock.requiredGates 包含非法记录")
            continue
        gate_id = str(locked_gate.get("id", ""))
        current = model.gates.get(gate_id)
        if current is None:
            issues.append(f"锁定的 required Gate 缺失：{gate_id}")
        elif canonical_bytes(current) != canonical_bytes(locked_gate):
            issues.append(f"锁定的 required Gate 发生漂移：{gate_id}")

    required_gate_map = {
        str(gate.get("id")): gate for gate in required_gates if isinstance(gate, dict)
    }
    for final_gate in final_gates:
        if not isinstance(final_gate, dict):
            issues.append("workLock.finalClaimGates 包含非法记录")
            continue
        gate_id = str(final_gate.get("id", ""))
        if gate_id not in required_gate_map or canonical_bytes(required_gate_map[gate_id]) != canonical_bytes(final_gate):
            issues.append(f"final-claim Gate 未被 required Gate 锁覆盖：{gate_id}")
    return issues


def started_event(model: Model) -> dict[str, Any] | None:
    matches = [event for event in model.events if event.get("type") == "AUTONOMY_STARTED"]
    return matches[0] if matches else None


def terminal_event(model: Model) -> dict[str, Any] | None:
    matches = [event for event in model.events if event.get("type") in TERMINAL_TYPES]
    return matches[-1] if matches else None


def contract_drifted(model: Model) -> bool:
    start = started_event(model)
    return bool(start and start.get("contractDigest") != project_digest(model.project))


def latest_event(model: Model, event_type: str) -> dict[str, Any] | None:
    for event in reversed(model.events):
        if event.get("type") == event_type:
            return event
    return None


def safe_repo_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise GovernanceError(f"引用越出仓库：{relative}") from exc
    return candidate


def git_root(root: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return Path(result.stdout.decode("utf-8", errors="strict").strip()).resolve()
    except (UnicodeDecodeError, OSError):
        return None


def parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise GovernanceError(f"时间格式应为 ISO-8601：{value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def hook_has_governance_stop(path: Path, host: str) -> bool:
    if not path.is_file():
        return False
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(config, dict):
        return False
    hooks = config.get("hooks") if host == "codex" else config
    groups = hooks.get("Stop", []) if isinstance(hooks, dict) else []
    if not isinstance(groups, list):
        return False
    for group in groups:
        handlers = group.get("hooks", []) if isinstance(group, dict) else []
        for handler in handlers if isinstance(handlers, list) else []:
            if not isinstance(handler, dict):
                continue
            commands = f"{handler.get('command', '')} {handler.get('commandWindows', '')}"
            if "governance.py" in commands and "hook-stop" in commands:
                return True
    return False


def structural_issues(model: Model) -> list[str]:
    issues: list[str] = []
    project = model.project
    work = model.work

    if project.get("schemaVersion") != SCHEMA_VERSION:
        issues.append("project.json schemaVersion 应为 1")
    if work.get("schemaVersion") != SCHEMA_VERSION:
        issues.append("work.json schemaVersion 应为 1")
    if not isinstance(project.get("projectId"), str) or not project.get("projectId", "").strip():
        issues.append("projectId 缺失")
    if not isinstance(project.get("projectName"), str) or not project.get("projectName", "").strip():
        issues.append("projectName 缺失")
    if not isinstance(project.get("outcome"), str):
        issues.append("outcome 应为字符串")
    if not isinstance(project.get("nonGoals"), list):
        issues.append("nonGoals 应为数组")
    if not isinstance(project.get("hardConstraints"), list):
        issues.append("hardConstraints 应为数组")

    interaction = project.get("interactionPolicy")
    if not isinstance(interaction, dict):
        issues.append("interactionPolicy 缺失")
    else:
        if interaction.get("decisionPhase") != "bootstrap_only":
            issues.append("decisionPhase 应为 bootstrap_only")
        if interaction.get("runtimeQuestions") is not False:
            issues.append("runtimeQuestions 应为 false")
        if interaction.get("escalationAllowlist") != []:
            issues.append("escalationAllowlist 应为空数组")

    authority = project.get("agentAuthority")
    if not isinstance(authority, dict):
        issues.append("agentAuthority 缺失")
    else:
        if not isinstance(authority.get("fixed"), list) or not authority.get("fixed"):
            issues.append("agentAuthority.fixed 缺失")
        if not isinstance(authority.get("mutable"), list) or not authority.get("mutable"):
            issues.append("agentAuthority.mutable 缺失")

    budgets = project.get("budgets")
    if not isinstance(budgets, dict):
        issues.append("budgets 缺失")
    preflight = project.get("preflight")
    if not isinstance(preflight, dict):
        issues.append("preflight 缺失")
    claims = project.get("finalAcceptance", {}).get("claims") if isinstance(project.get("finalAcceptance"), dict) else None
    if not isinstance(claims, list):
        issues.append("finalAcceptance.claims 应为数组")

    gates = work.get("gates")
    items = work.get("items")
    if not isinstance(gates, list):
        issues.append("work.gates 应为数组")
        gates = []
    if not isinstance(items, list):
        issues.append("work.items 应为数组")
        items = []

    gate_ids: set[str] = set()
    for index, gate in enumerate(gates):
        label = f"gates[{index}]"
        if not isinstance(gate, dict):
            issues.append(f"{label} 应为对象")
            continue
        gate_id = gate.get("id")
        if not isinstance(gate_id, str) or not gate_id.strip():
            issues.append(f"{label}.id 缺失")
        elif gate_id in gate_ids:
            issues.append(f"Gate ID 重复：{gate_id}")
        else:
            gate_ids.add(gate_id)
        if gate.get("level") not in LEVELS:
            issues.append(f"{label}.level 应为 V0/V1/V2")
        if gate.get("dataMode") not in DATA_MODES:
            issues.append(f"{label}.dataMode 非法")
        command = gate.get("command")
        command_windows = gate.get("commandWindows")
        if not command and not command_windows:
            issues.append(f"{label} 缺少 command")
        for field in ("command", "commandWindows"):
            value = gate.get(field)
            if value is not None and not isinstance(value, (str, list)):
                issues.append(f"{label}.{field} 应为字符串或参数数组")
            if isinstance(value, list) and not all(isinstance(part, str) for part in value):
                issues.append(f"{label}.{field} 参数应为字符串")
        if not isinstance(gate.get("subjectPaths", []), list):
            issues.append(f"{label}.subjectPaths 应为数组")
        timeout = gate.get("timeoutSeconds", 600)
        if not isinstance(timeout, int) or timeout <= 0:
            issues.append(f"{label}.timeoutSeconds 应为正整数")

    item_ids: set[str] = set()
    for index, item in enumerate(items):
        label = f"items[{index}]"
        if not isinstance(item, dict):
            issues.append(f"{label} 应为对象")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            issues.append(f"{label}.id 缺失")
        elif item_id in item_ids:
            issues.append(f"Work item ID 重复：{item_id}")
        else:
            item_ids.add(item_id)
        if item.get("bucket") not in BUCKETS:
            issues.append(f"{label}.bucket 应为 NOW/NEXT/LATER")
        if not isinstance(item.get("requiredForFinal"), bool):
            issues.append(f"{label}.requiredForFinal 应显式设为 true/false")
        refs = item.get("gateRefs", [])
        if not isinstance(refs, list):
            issues.append(f"{label}.gateRefs 应为数组")
            refs = []
        for ref in refs:
            if ref not in gate_ids:
                issues.append(f"{label} 引用了未知 Gate：{ref}")
        if not isinstance(item.get("pathScopes", []), list):
            issues.append(f"{label}.pathScopes 应为数组")
        if not refs and not str(item.get("verificationExemption", "")).strip():
            issues.append(f"{label} 需要 Gate 或 verificationExemption")

    claim_ids: set[str] = set()
    for index, claim in enumerate(claims or []):
        label = f"claims[{index}]"
        if not isinstance(claim, dict):
            issues.append(f"{label} 应为对象")
            continue
        claim_id = claim.get("id")
        if not isinstance(claim_id, str) or not claim_id.strip():
            issues.append(f"{label}.id 缺失")
        elif claim_id in claim_ids:
            issues.append(f"Final claim ID 重复：{claim_id}")
        else:
            claim_ids.add(claim_id)
        if claim.get("itemRef") not in item_ids:
            issues.append(f"{label}.itemRef 未引用有效工作项")
        else:
            bound_item = next(
                (item for item in items if isinstance(item, dict) and item.get("id") == claim.get("itemRef")),
                None,
            )
            if bound_item and bound_item.get("requiredForFinal") is not True:
                issues.append(f"{label}.itemRef 应指向 requiredForFinal=true 的工作项")
        gate_ref = claim.get("gateRef")
        if gate_ref not in gate_ids:
            issues.append(f"{label}.gateRef 未引用有效 Gate")
        if claim.get("level") not in LEVELS:
            issues.append(f"{label}.level 应为 V0/V1/V2")
        if claim.get("dataMode") not in DATA_MODES:
            issues.append(f"{label}.dataMode 非法")
        gate = next((g for g in gates if isinstance(g, dict) and g.get("id") == gate_ref), None)
        if gate and claim.get("level") in LEVELS and LEVELS[gate.get("level")] < LEVELS[claim.get("level")]:
            issues.append(f"{label} 要求的证据层级高于 Gate")
        if gate and claim.get("dataMode") and gate.get("dataMode") != claim.get("dataMode"):
            issues.append(f"{label} 的 dataMode 与 Gate 不一致")

    ids: set[str] = set()
    start_count = 0
    terminal_seen: dict[str, Any] | None = None
    for event in model.events:
        identifier = event.get("id")
        if not isinstance(identifier, str) or not identifier:
            issues.append("事件缺少 id")
        elif identifier in ids:
            issues.append(f"事件 ID 重复：{identifier}")
        else:
            ids.add(identifier)
        if event.get("type") == "AUTONOMY_STARTED":
            start_count += 1
        if event.get("type") in TERMINAL_TYPES:
            if terminal_seen is not None:
                issues.append("存在多个终态事件")
            terminal_seen = event
        elif terminal_seen is not None and event.get("type") != "FINAL_REPORT_REQUESTED":
            issues.append(f"终态后出现运行事件：{event.get('type')}")
    if start_count > 1:
        issues.append("AUTONOMY_STARTED 只能出现一次")
    start = started_event(model)
    if start and start.get("contractDigest") != project_digest(project):
        issues.append("启动后 project.json 与锁定契约摘要不一致")
    if start:
        issues.extend(work_lock_issues(model))
    return issues


def readiness_issues(model: Model) -> list[str]:
    issues = structural_issues(model)
    project = model.project
    work = model.work
    outcome = str(project.get("outcome", "")).strip()
    if not outcome or outcome.startswith("REPLACE_"):
        issues.append("outcome 尚未写入已确认目标")
    preflight = project.get("preflight", {})
    if isinstance(preflight, dict):
        for key in PREFLIGHT_KEYS:
            if preflight.get(key) is not True:
                issues.append(f"preflight.{key} 尚未确认")
    budgets = project.get("budgets", {})
    if isinstance(budgets, dict):
        for key in ("maxCheckRuns", "maxStopContinuations", "maxNoProgressStops", "sameFailureLimit"):
            value = budgets.get(key)
            if not isinstance(value, int) or value <= 0:
                issues.append(f"budgets.{key} 应为已确认的正整数")
        deadline = budgets.get("deadlineAt")
        if deadline is not None:
            try:
                parse_iso(deadline)
            except GovernanceError as exc:
                issues.append(str(exc))
    claims = project.get("finalAcceptance", {}).get("claims", [])
    if not claims:
        issues.append("至少需要一个最终验收 claim")
    elif not any(
        isinstance(claim, dict) and claim.get("level") == "V2" and claim.get("dataMode") == "real"
        for claim in claims
    ):
        issues.append("最终验收至少包含一个 V2/real claim")
    items = work.get("items", [])
    gates = work.get("gates", [])
    if not gates:
        issues.append("至少需要一个已登记 Gate")
    if not items:
        issues.append("至少需要一个工作项")
    elif not any(isinstance(item, dict) and item.get("bucket") == "NOW" for item in items):
        issues.append("至少需要一个 NOW 工作项")
    if not hook_has_governance_stop(model.root / CODEX_HOOKS_REL, "codex"):
        issues.append("Codex Stop Hook 尚未安装")
    if not hook_has_governance_stop(model.root / DEVIN_HOOKS_REL, "devin"):
        issues.append("Devin Stop Hook 尚未安装")
    detected_git_root = git_root(model.root)
    if detected_git_root is None:
        issues.append("仓库尚未完成 Git 根目录预检")
    elif detected_git_root != model.root.resolve():
        issues.append(f"治理根目录与 Git 根目录不同：{detected_git_root}")
    return list(dict.fromkeys(issues))


def git_visible_files(root: Path) -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return [part.decode("utf-8", errors="surrogateescape") for part in result.stdout.split(b"\0") if part]


def fallback_visible_files(root: Path) -> list[str]:
    result: list[str] = []
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        rel_dir = current_path.relative_to(root)
        dirs[:] = [
            name
            for name in dirs
            if name not in SOURCE_EXCLUDED_DIRS and not (rel_dir == Path("tools") and name == "governance.py")
        ]
        for name in files:
            path = current_path / name
            rel = path.relative_to(root).as_posix()
            result.append(rel)
    return sorted(result)


def is_source_excluded(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    if not parts:
        return True
    if any(part in SOURCE_EXCLUDED_DIRS for part in parts):
        return True
    if relative == "tools/governance.py":
        return True
    if relative in HOOK_RELS:
        return True
    return False


def path_matches(relative: str, patterns: Iterable[str]) -> bool:
    normalized = relative.replace("\\", "/")
    pattern_list = [str(pattern).replace("\\", "/").lstrip("./") for pattern in patterns if str(pattern).strip()]
    if not pattern_list:
        return True
    path = PurePosixPath(normalized)
    for pattern in pattern_list:
        if fnmatch.fnmatchcase(normalized, pattern) or path.match(pattern):
            return True
        if pattern.endswith("/**") and normalized.startswith(pattern[:-3].rstrip("/") + "/"):
            return True
        if pattern.endswith("/") and normalized.startswith(pattern):
            return True
    return False


def subject_snapshot(root: Path, patterns: Iterable[str]) -> tuple[str, list[dict[str, Any]]]:
    visible = git_visible_files(root)
    if visible is None:
        visible = fallback_visible_files(root)
    records: list[dict[str, Any]] = []
    for relative in sorted(set(visible)):
        normalized = relative.replace("\\", "/")
        if is_source_excluded(normalized) or not path_matches(normalized, patterns):
            continue
        path = root / relative
        if path.is_symlink():
            target = os.readlink(path)
            records.append({"path": normalized, "type": "symlink", "target": target})
        elif path.is_file():
            records.append(
                {
                    "path": normalized,
                    "type": "file",
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return sha256_bytes(canonical_bytes(records)), records


def item_gate_patterns(item: dict[str, Any], gate: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for value in (item.get("pathScopes", []), gate.get("subjectPaths", [])):
        if isinstance(value, list):
            result.extend(str(part) for part in value if str(part).strip())
    return sorted(set(result))


def runner_digest() -> str:
    return RUNNER_EVIDENCE_DIGEST


def gate_digest(gate: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(gate))


def inspect_result_record(model: Model, event: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    issues: list[str] = []
    run_id = event.get("runId")
    reference = event.get("resultRef")
    if not isinstance(reference, str) or not reference:
        return None, [f"CHECK_FINISHED 事件缺少 resultRef：{event.get('id')}"]
    expected_ref = f"{RUNS_REL}/{run_id}/result.json"
    if reference != expected_ref:
        issues.append(f"检查结果路径不符合 runId：{run_id}")
    try:
        path = safe_repo_path(model.root, reference)
        result = read_json(path)
    except GovernanceError as exc:
        return None, [f"检查结果缺失或损坏：{run_id}: {exc}"]

    expected_sha = event.get("resultSha256")
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        issues.append(f"CHECK_FINISHED 缺少 resultSha256：{run_id}")
    elif sha256_file(path) != expected_sha:
        issues.append(f"检查结果摘要不匹配：{run_id}")

    bindings = (
        ("runId", run_id),
        ("workItemRef", event.get("itemRef")),
        ("gateRef", event.get("gateRef")),
        ("outcome", event.get("outcome")),
        ("gateSpecDigest", event.get("gateSpecDigest")),
        ("lockedContractDigest", event.get("lockedContractDigest")),
        ("runnerDigest", event.get("runnerDigest")),
    )
    for field, expected in bindings:
        if result.get(field) != expected:
            issues.append(f"检查结果 {field} 与事件不匹配：{run_id}")

    start = started_event(model)
    if start and event.get("lockedContractDigest") != start.get("contractDigest"):
        issues.append(f"检查结果未绑定当前锁定契约：{run_id}")
    for field in ("gateSpecDigest", "lockedContractDigest", "runnerDigest"):
        if not isinstance(event.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", str(event.get(field))):
            issues.append(f"CHECK_FINISHED 缺少有效 {field}：{run_id}")

    for name, field in (("stdout.log", "stdoutSha256"), ("stderr.log", "stderrSha256")):
        log_path = safe_repo_path(model.root, str(PurePosixPath(reference).parent / name))
        if not log_path.is_file():
            issues.append(f"检查日志缺失：{log_path.relative_to(model.root).as_posix()}")
        elif sha256_file(log_path) != result.get(field):
            issues.append(f"检查日志摘要不匹配：{log_path.relative_to(model.root).as_posix()}")
    return result, issues


def load_result(model: Model, event: dict[str, Any]) -> dict[str, Any] | None:
    result, issues = inspect_result_record(model, event)
    return None if issues else result


def latest_run_events(model: Model, item_id: str, gate_id: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    result: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for event in model.events:
        if event.get("type") != "CHECK_FINISHED":
            continue
        if event.get("itemRef") != item_id or event.get("gateRef") != gate_id:
            continue
        run = load_result(model, event)
        if run is not None:
            result.append((event, run))
    return result


def current_identity(model: Model, item: dict[str, Any], gate: dict[str, Any]) -> dict[str, str]:
    start = started_event(model)
    if start is None:
        raise GovernanceError("自主运行尚未开始")
    digest, _ = subject_snapshot(model.root, item_gate_patterns(item, gate))
    return {
        "subjectDigest": digest,
        "gateSpecDigest": gate_digest(gate),
        "lockedContractDigest": str(start.get("contractDigest", "")),
        "runnerDigest": runner_digest(),
    }


def run_identity_matches(run: dict[str, Any], identity: dict[str, str], gate: dict[str, Any]) -> bool:
    for key, expected in identity.items():
        if run.get(key) != expected:
            return False
    if run.get("dataMode") != gate.get("dataMode"):
        return False
    max_age = gate.get("maxAgeSeconds")
    if max_age is not None:
        if not isinstance(max_age, int) or max_age <= 0:
            return False
        try:
            finished = parse_iso(str(run.get("finishedAt")))
        except GovernanceError:
            return False
        if (datetime.now(timezone.utc) - finished).total_seconds() > max_age:
            return False
    return True


def verification_state(model: Model, item: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    item_id = str(item.get("id"))
    gate_id = str(gate.get("id"))
    history = latest_run_events(model, item_id, gate_id)
    identity = current_identity(model, item, gate)
    for event, run in reversed(history):
        if not run_identity_matches(run, identity, gate):
            continue
        outcome = run.get("outcome")
        if outcome == "pass" and run.get("subjectDigestBefore") == run.get("subjectDigestAfter"):
            status = "passed"
        elif outcome in {"fail", "timeout", "error"}:
            status = "failed"
        else:
            status = "stale"
        return {"status": status, "event": event, "run": run, "identity": identity}
    return {
        "status": "stale" if history else "missing",
        "event": history[-1][0] if history else None,
        "run": history[-1][1] if history else None,
        "identity": identity,
    }


def work_states(model: Model) -> dict[str, str]:
    result = {item_id: "planned" for item_id in model.items}
    for event in model.events:
        item_id = event.get("itemRef")
        if item_id not in result:
            continue
        event_type = event.get("type")
        if event_type == "WORK_STARTED":
            result[item_id] = "in_progress"
        elif event_type == "WORK_IMPLEMENTED":
            result[item_id] = "implemented"
        elif event_type == "WORK_DEFERRED":
            result[item_id] = "deferred"
        elif event_type == "WORK_REOPENED":
            result[item_id] = "in_progress"
    return result


def runtime_flag_open(model: Model, opened: set[str], closed: set[str]) -> bool:
    active = False
    for event in model.events:
        event_type = str(event.get("type"))
        if event_type in opened:
            active = True
        elif event_type in closed:
            active = False
    return active


def runtime_state(model: Model) -> str:
    terminal = terminal_event(model)
    if terminal:
        return "COMPLETED" if terminal.get("type") == "PROJECT_COMPLETED" else "EXHAUSTED"
    if started_event(model):
        if runtime_flag_open(model, {"REPLAN_STARTED"}, {"REPLAN_FINISHED"}):
            return "REPLANNING"
        if runtime_flag_open(
            model,
            {"DEGRADATION_STARTED", "FALLBACK_ACTIVATED"},
            {"DEGRADATION_ENDED", "FALLBACK_CLEARED"},
        ):
            return "DEGRADED"
        return "RUNNING"
    return "READY" if not readiness_issues(model) else "SETUP"


def completion_report(model: Model) -> dict[str, Any]:
    if started_event(model) is None:
        return {
            "eligible": False,
            "runtimeState": runtime_state(model),
            "issues": [{"kind": "not_started", "message": "自主运行尚未开始"}],
            "items": [],
            "claims": [],
        }
    item_states = work_states(model)
    governance_issues = structural_issues(model) + evidence_integrity_issues(model)
    issues: list[dict[str, Any]] = [
        {"kind": "governance", "status": "invalid", "message": message}
        for message in dict.fromkeys(governance_issues)
    ]
    item_views: list[dict[str, Any]] = []
    verification_cache: dict[tuple[str, str], dict[str, Any]] = {}

    for item_id, item in model.items.items():
        gate_views: list[dict[str, Any]] = []
        for gate_ref in item.get("gateRefs", []):
            gate = model.gates.get(str(gate_ref))
            if gate is None:
                continue
            state = verification_state(model, item, gate)
            verification_cache[(item_id, str(gate_ref))] = state
            run = state.get("run") or {}
            gate_view = {
                "id": gate_ref,
                "level": gate.get("level"),
                "dataMode": gate.get("dataMode"),
                "status": state.get("status"),
                "runId": run.get("runId"),
                "finishedAt": run.get("finishedAt"),
                "resultRef": state.get("event", {}).get("resultRef") if state.get("event") else None,
                "failureSignature": run.get("failureSignature"),
            }
            gate_views.append(gate_view)
            if item.get("requiredForFinal", True) and state.get("status") != "passed":
                issues.append(
                    {
                        "kind": "verification",
                        "item": item_id,
                        "gate": gate_ref,
                        "status": state.get("status"),
                        "message": f"{item_id}/{gate_ref} 验证状态为 {state.get('status')}",
                    }
                )
        if item.get("requiredForFinal", True) and item_states.get(item_id) != "implemented":
            issues.append(
                {
                    "kind": "work",
                    "item": item_id,
                    "status": item_states.get(item_id),
                    "message": f"{item_id} 尚未记录为 implemented",
                }
            )
        item_views.append(
            {
                "id": item_id,
                "title": item.get("title", item_id),
                "bucket": item.get("bucket"),
                "requiredForFinal": item.get("requiredForFinal", True),
                "workStatus": item_states.get(item_id),
                "checks": gate_views,
                "nextCheckpoint": item.get("nextCheckpoint", ""),
            }
        )

    claim_views: list[dict[str, Any]] = []
    claims = model.project.get("finalAcceptance", {}).get("claims", [])
    for claim in claims:
        item_id = str(claim.get("itemRef"))
        gate_id = str(claim.get("gateRef"))
        item = model.items.get(item_id)
        gate = model.gates.get(gate_id)
        state = verification_cache.get((item_id, gate_id))
        if state is None and item and gate:
            state = verification_state(model, item, gate)
        run = (state or {}).get("run") or {}
        passed = bool(
            state
            and state.get("status") == "passed"
            and gate
            and LEVELS.get(str(gate.get("level")), -1) >= LEVELS.get(str(claim.get("level")), 99)
            and run.get("dataMode") == claim.get("dataMode")
        )
        claim_view = {
            "id": claim.get("id"),
            "description": claim.get("description", ""),
            "itemRef": item_id,
            "gateRef": gate_id,
            "requiredLevel": claim.get("level"),
            "requiredDataMode": claim.get("dataMode"),
            "status": "passed" if passed else (state or {}).get("status", "missing"),
            "runId": run.get("runId"),
        }
        claim_views.append(claim_view)
        if not passed:
            issues.append(
                {
                    "kind": "final_claim",
                    "claim": claim.get("id"),
                    "item": item_id,
                    "gate": gate_id,
                    "status": claim_view["status"],
                    "message": f"最终 claim {claim.get('id')} 尚无当前 {claim.get('level')}/{claim.get('dataMode')} 证据",
                }
            )

    return {
        "eligible": not issues,
        "runtimeState": runtime_state(model),
        "issues": issues,
        "items": item_views,
        "claims": claim_views,
    }


def command_for_gate(gate: dict[str, Any]) -> str | list[str]:
    if os.name == "nt" and gate.get("commandWindows"):
        command = gate.get("commandWindows")
    else:
        command = gate.get("command") or gate.get("commandWindows")
    if not isinstance(command, (str, list)) or not command:
        raise GovernanceError(f"Gate {gate.get('id')} 缺少当前平台命令")
    if isinstance(command, list) and not all(isinstance(part, str) and part for part in command):
        raise GovernanceError(f"Gate {gate.get('id')} 命令参数非法")
    return command


def check_working_directory(root: Path, gate: dict[str, Any]) -> Path:
    raw = str(gate.get("cwd", "."))
    path = safe_repo_path(root, raw)
    if not path.is_dir():
        raise GovernanceError(f"Gate 工作目录不存在：{raw}")
    return path


def normalize_failure_signature(exit_code: int | None, stdout: bytes, stderr: bytes, outcome: str) -> str | None:
    if outcome == "pass":
        return None
    sample = stderr[-4096:] if stderr.strip() else stdout[-4096:]
    value = {
        "outcome": outcome,
        "exitCode": exit_code,
        "tailSha256": sha256_bytes(sample),
    }
    return sha256_bytes(canonical_bytes(value))


def unchanged_failure_count(
    model: Model,
    item_id: str,
    gate_id: str,
    identity: dict[str, str],
    gate: dict[str, Any],
) -> tuple[int, str | None]:
    count = 0
    signature: str | None = None
    for _, run in reversed(latest_run_events(model, item_id, gate_id)):
        if not run_identity_matches(run, identity, gate):
            break
        current_signature = run.get("failureSignature")
        if run.get("outcome") not in {"fail", "timeout", "error"} or not current_signature:
            break
        if signature is None:
            signature = str(current_signature)
        if current_signature != signature:
            break
        count += 1
    return count, signature


def execute_gate(model: Model, item_id: str, gate_id: str) -> dict[str, Any]:
    start = started_event(model)
    if start is None:
        raise GovernanceError("请先执行 governance.py start")
    if contract_drifted(model):
        raise GovernanceError("启动契约发生漂移；请先执行 governance.py restore-contract")
    integrity_issues = runtime_integrity_issues(model)
    if integrity_issues:
        raise GovernanceError(f"治理完整性检查失败：{'；'.join(integrity_issues)}")
    if terminal_event(model):
        raise GovernanceError("项目已进入终态")
    item = model.items.get(item_id)
    if item is None:
        raise GovernanceError(f"未知工作项：{item_id}")
    if gate_id not in [str(value) for value in item.get("gateRefs", [])]:
        raise GovernanceError(f"Gate {gate_id} 未登记到工作项 {item_id}")
    gate = model.gates.get(gate_id)
    if gate is None:
        raise GovernanceError(f"未知 Gate：{gate_id}")

    identity_before = current_identity(model, item, gate)
    same_count, signature = unchanged_failure_count(model, item_id, gate_id, identity_before, gate)
    limit = int(model.project.get("budgets", {}).get("sameFailureLimit", 2))
    if same_count >= limit:
        raise GovernanceError(
            f"相同失败已连续出现 {same_count} 次，签名 {signature[:12] if signature else '-'}；"
            "请先修改产品、Gate、Verifier 或实施路线，再产生新的检查证据"
        )

    command = command_for_gate(gate)
    cwd = check_working_directory(model.root, gate)
    timeout = int(gate.get("timeoutSeconds", 600))
    run_id = event_id("run")
    started_at = utc_now()
    monotonic_start = time.monotonic()
    stdout = b""
    stderr = b""
    exit_code: int | None = None
    outcome = "error"
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=isinstance(command, str),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        exit_code = completed.returncode
        outcome = "pass" if completed.returncode == 0 else "fail"
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        outcome = "timeout"
    except OSError as exc:
        stderr = str(exc).encode("utf-8", errors="replace")
        outcome = "error"
    finished_at = utc_now()
    duration_ms = int((time.monotonic() - monotonic_start) * 1000)
    subject_after, _ = subject_snapshot(model.root, item_gate_patterns(item, gate))
    if outcome == "pass" and subject_after != identity_before["subjectDigest"]:
        outcome = "stale_after_run"
    failure_signature = normalize_failure_signature(exit_code, stdout, stderr, outcome)

    run_dir_rel = f"{RUNS_REL}/{run_id}"
    run_dir = safe_repo_path(model.root, run_dir_rel)
    run_dir.mkdir(parents=True, exist_ok=False)
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "workItemRef": item_id,
        "gateRef": gate_id,
        "level": gate.get("level"),
        "dataMode": gate.get("dataMode"),
        "startedAt": started_at,
        "finishedAt": finished_at,
        "durationMs": duration_ms,
        "command": command,
        "cwd": cwd.relative_to(model.root).as_posix() or ".",
        "exitCode": exit_code,
        "outcome": outcome,
        "subjectDigest": identity_before["subjectDigest"],
        "subjectDigestBefore": identity_before["subjectDigest"],
        "subjectDigestAfter": subject_after,
        "gateSpecDigest": identity_before["gateSpecDigest"],
        "lockedContractDigest": identity_before["lockedContractDigest"],
        "runnerDigest": identity_before["runnerDigest"],
        "stdoutSha256": sha256_bytes(stdout),
        "stderrSha256": sha256_bytes(stderr),
        "failureSignature": failure_signature,
    }
    result_path = run_dir / "result.json"
    result_bytes = canonical_bytes(result) + b"\n"
    result_path.write_bytes(result_bytes)
    result_ref = result_path.relative_to(model.root).as_posix()
    append_event(
        model,
        "CHECK_FINISHED",
        runId=run_id,
        itemRef=item_id,
        gateRef=gate_id,
        outcome=outcome,
        resultRef=result_ref,
        resultSha256=sha256_bytes(result_bytes),
        gateSpecDigest=identity_before["gateSpecDigest"],
        lockedContractDigest=identity_before["lockedContractDigest"],
        runnerDigest=identity_before["runnerDigest"],
    )
    derive_board(model)
    return result


def progress_digest(model: Model, report: dict[str, Any] | None = None) -> str:
    report = report or completion_report(model)
    source, _ = subject_snapshot(model.root, [])
    latest_runs: dict[str, dict[str, Any]] = {}
    for event in model.events:
        if event.get("type") == "CHECK_FINISHED":
            key = f"{event.get('itemRef')}::{event.get('gateRef')}"
            latest_runs[key] = {
                "runId": event.get("runId"),
                "outcome": event.get("outcome"),
            }
    value = {
        "sourceDigest": source,
        "workDigest": work_digest(model.work),
        "workStatus": {view["id"]: view["workStatus"] for view in report.get("items", [])},
        "runs": latest_runs,
        "claims": {view["id"]: view["status"] for view in report.get("claims", [])},
    }
    return sha256_bytes(canonical_bytes(value))


def budget_exhaustion_reason(model: Model, report: dict[str, Any], next_progress: str) -> str | None:
    if report.get("eligible"):
        return None
    budgets = model.project.get("budgets", {})
    deadline = budgets.get("deadlineAt")
    if deadline is not None and datetime.now(timezone.utc) >= parse_iso(str(deadline)):
        return f"到达锁定截止时间 {deadline}"
    check_runs = sum(1 for event in model.events if event.get("type") == "CHECK_FINISHED")
    if check_runs >= int(budgets.get("maxCheckRuns", 0)):
        return f"检查运行预算已用尽：{check_runs}/{budgets.get('maxCheckRuns')}"
    continuations = [event for event in model.events if event.get("type") == "STOP_CONTINUED"]
    if len(continuations) >= int(budgets.get("maxStopContinuations", 0)):
        return f"Stop continuation 预算已用尽：{len(continuations)}/{budgets.get('maxStopContinuations')}"
    streak = 1
    for event in reversed(continuations):
        if event.get("progressDigest") == next_progress:
            streak += 1
        else:
            break
    if streak >= int(budgets.get("maxNoProgressStops", 0)):
        return f"连续 {streak} 次 Stop 未观察到实质进展"
    return None


def next_action(model: Model, report: dict[str, Any]) -> str:
    issues = report.get("issues", [])
    if not issues:
        return "继续完成锁定目标，并通过 governance.py 记录实现与检查证据。"
    issue = issues[0]
    kind = issue.get("kind")
    item = issue.get("item")
    gate = issue.get("gate")
    status = issue.get("status")
    if kind in {"verification", "final_claim"} and status in {"missing", "stale"} and item and gate:
        return (
            f"{item}/{gate} 缺少当前证据。继续执行："
            f"python tools/governance.py run --item {item} --gate {gate}。"
        )
    if kind in {"verification", "final_claim"} and status == "failed":
        return (
            f"{item}/{gate} 的最新当前证据失败。检查对应 run 记录，"
            "自主修改产品、Gate、Verifier 或实施路线；发生实质变化后再运行该 Gate。"
        )
    if kind == "work" and item:
        return (
            f"继续推进 {item}；实现完成后执行："
            f"python tools/governance.py record --type WORK_IMPLEMENTED --item {item}。"
        )
    return f"继续处理：{issue.get('message', '当前完成条件尚未闭合')}。"


def board_source_files(model: Model) -> list[Path]:
    result = [model.root / PROJECT_REL, model.root / WORK_REL, model.root / EVENTS_REL]
    for event in model.events:
        if event.get("type") == "CHECK_FINISHED" and isinstance(event.get("resultRef"), str):
            path = safe_repo_path(model.root, event["resultRef"])
            if path.is_file():
                result.append(path)
    return sorted(set(result), key=lambda path: path.relative_to(model.root).as_posix())


def board_input_digest(model: Model) -> str:
    digest = hashlib.sha256()
    digest.update(f"generator:{TOOL_VERSION}\0".encode("utf-8"))
    for path in board_source_files(model):
        relative = path.relative_to(model.root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(relative)
        digest.update(b"\0")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def short_digest(value: Any) -> str:
    text = str(value or "")
    return text[:12] if text else "—"


def status_class(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", value.lower())


def event_facts_through(model: Model) -> str:
    values = [str(event.get("at")) for event in model.events if event.get("at")]
    return max(values) if values else str(model.project.get("initializedAt", ""))


def repeated_failure_count(model: Model, item_id: str, gate_id: str) -> int:
    count = 0
    signature: str | None = None
    for _, run in reversed(latest_run_events(model, item_id, gate_id)):
        current = run.get("failureSignature")
        if run.get("outcome") not in {"fail", "timeout", "error"} or not current:
            break
        if signature is None:
            signature = str(current)
        if current != signature:
            break
        count += 1
    return count


def render_board(model: Model, report: dict[str, Any] | None = None) -> bytes:
    if readiness_issues(model) and started_event(model) is None:
        raise GovernanceError("readiness 尚未通过，暂不生成运行看板")
    digest = board_input_digest(model)
    report = report if report is not None else (completion_report(model) if started_event(model) else {
        "eligible": False,
        "items": [
            {
                "id": item.get("id"),
                "title": item.get("title", item.get("id")),
                "bucket": item.get("bucket"),
                "requiredForFinal": item.get("requiredForFinal", True),
                "workStatus": "planned",
                "checks": [],
                "nextCheckpoint": item.get("nextCheckpoint", ""),
            }
            for item in model.work.get("items", [])
        ],
        "claims": [],
        "issues": [],
    })
    state = runtime_state(model)
    items = report.get("items", [])
    claims = report.get("claims", [])
    required_items = [item for item in items if item.get("requiredForFinal")]
    implemented = sum(1 for item in required_items if item.get("workStatus") == "implemented")
    required_checks = [check for item in required_items for check in item.get("checks", [])]
    passed_checks = sum(1 for check in required_checks if check.get("status") == "passed")
    passed_claims = sum(1 for claim in claims if claim.get("status") == "passed")

    constraints = "".join(f"<li>{esc(value)}</li>" for value in model.project.get("hardConstraints", []))
    if not constraints:
        constraints = "<li>已确认无额外硬约束</li>"

    warnings = report.get("issues", [])
    warning_html = "".join(
        f'<li><span class="tag {status_class(str(issue.get("status", issue.get("kind", "info"))))}">'
        f'{esc(issue.get("status", issue.get("kind", "info")))}</span>{esc(issue.get("message"))}</li>'
        for issue in warnings
    )
    if not warning_html:
        warning_html = "<li>当前没有完成条件告警。</li>"

    item_by_bucket: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in ("NOW", "NEXT", "LATER")}
    for view in items:
        item_by_bucket.setdefault(str(view.get("bucket")), []).append(view)

    bucket_sections: list[str] = []
    for bucket in ("NOW", "NEXT", "LATER"):
        cards: list[str] = []
        for view in item_by_bucket.get(bucket, []):
            check_rows: list[str] = []
            for check in view.get("checks", []):
                failures = repeated_failure_count(model, str(view.get("id")), str(check.get("id")))
                check_rows.append(
                    '<div class="check-row">'
                    f'<span class="mono">{esc(check.get("id"))}</span>'
                    f'<span>{esc(check.get("level"))}/{esc(check.get("dataMode"))}</span>'
                    f'<span class="tag {status_class(str(check.get("status")))}">{esc(check.get("status"))}</span>'
                    f'<span class="muted">run {esc(check.get("runId") or "—")} · repeated {failures}</span>'
                    "</div>"
                )
            if not check_rows:
                check_rows.append('<div class="muted">显式验证豁免或尚未进入运行态</div>')
            cards.append(
                '<article class="work-card">'
                '<div class="work-head">'
                f'<span class="mono">{esc(view.get("id"))}</span>'
                f'<span class="tag {status_class(str(view.get("workStatus")))}">{esc(view.get("workStatus"))}</span>'
                "</div>"
                f'<h3>{esc(view.get("title"))}</h3>'
                f'<p class="checkpoint">下一检查点：{esc(view.get("nextCheckpoint") or "未填写")}</p>'
                f'<div class="checks">{"".join(check_rows)}</div>'
                "</article>"
            )
        if not cards:
            cards.append('<div class="empty">暂无工作项</div>')
        bucket_sections.append(
            f'<section class="bucket"><h2>{bucket}</h2><div class="bucket-cards">{"".join(cards)}</div></section>'
        )

    claim_rows = "".join(
        "<tr>"
        f'<td class="mono">{esc(claim.get("id"))}</td>'
        f'<td>{esc(claim.get("description"))}</td>'
        f'<td class="mono">{esc(claim.get("itemRef"))}/{esc(claim.get("gateRef"))}</td>'
        f'<td>{esc(claim.get("requiredLevel"))}/{esc(claim.get("requiredDataMode"))}</td>'
        f'<td><span class="tag {status_class(str(claim.get("status")))}">{esc(claim.get("status"))}</span></td>'
        f'<td class="mono">{esc(claim.get("runId") or "—")}</td>'
        "</tr>"
        for claim in claims
    )
    if not claim_rows:
        claim_rows = '<tr><td colspan="6" class="empty">尚无最终 claim</td></tr>'

    recent_events = model.events[-10:]
    event_rows = "".join(
        "<tr>"
        f'<td class="mono">{esc(event.get("at"))}</td>'
        f'<td>{esc(event.get("type"))}</td>'
        f'<td class="mono">{esc(" / ".join(str(value) for value in (event.get("itemRef"), event.get("gateRef"), event.get("outcome"), event.get("reason")) if value) or "—")}</td>'
        "</tr>"
        for event in reversed(recent_events)
    )
    if not event_rows:
        event_rows = '<tr><td colspan="3" class="empty">尚无运行事件</td></tr>'

    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="governance-input-digest" content="sha256:{digest}">
  <meta name="governance-generator-version" content="{TOOL_VERSION}">
  <title>{esc(model.project.get('projectName'))} · Governance Board</title>
  <style>
    :root {{ color-scheme: dark; --bg:#07111f; --panel:#0d1b2d; --line:#203550; --text:#e8f0f8; --muted:#91a4b8; --accent:#5dd6c0; --warn:#ffbd66; --bad:#ff7b88; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font:14px/1.55 Inter, ui-sans-serif, system-ui, sans-serif; background:radial-gradient(circle at top right,#12314b 0,#07111f 38%); color:var(--text); }}
    main {{ width:min(1440px,94vw); margin:0 auto; padding:34px 0 64px; }}
    header {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-start; border-bottom:1px solid var(--line); padding-bottom:22px; }}
    h1 {{ margin:0 0 6px; font-size:28px; }} h2 {{ margin:0 0 12px; font-size:16px; letter-spacing:.08em; }} h3 {{ margin:10px 0 8px; font-size:16px; }}
    .state {{ font-size:15px; font-weight:750; letter-spacing:.08em; padding:8px 13px; border:1px solid var(--accent); color:var(--accent); border-radius:999px; }}
    .meta,.muted {{ color:var(--muted); }} .mono {{ font-family:ui-monospace,SFMono-Regular,Consolas,monospace; }}
    .grid {{ display:grid; grid-template-columns:1.25fr .75fr; gap:18px; margin-top:20px; }}
    .panel,.metric,.work-card,.empty {{ background:color-mix(in srgb,var(--panel) 92%,transparent); border:1px solid var(--line); border-radius:14px; }}
    .panel {{ padding:20px; }} .panel p {{ margin:0; }} .panel ul {{ margin:10px 0 0; padding-left:20px; }}
    .metrics {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:18px; }}
    .metric {{ padding:16px; }} .metric strong {{ display:block; font-size:26px; color:var(--accent); }}
    .warnings {{ margin-top:18px; }} .warnings li {{ margin:7px 0; display:flex; gap:10px; align-items:center; }}
    .board {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-top:24px; }}
    .bucket-cards {{ display:grid; gap:12px; }} .work-card {{ padding:16px; }} .work-head {{ display:flex; justify-content:space-between; align-items:center; }}
    .checkpoint {{ color:var(--muted); margin:0 0 12px; }} .checks {{ display:grid; gap:7px; }}
    .check-row {{ display:grid; grid-template-columns:minmax(90px,1fr) auto auto; gap:8px 12px; align-items:center; border-top:1px solid var(--line); padding-top:8px; }}
    .check-row .muted {{ grid-column:1/-1; font-size:12px; }}
    .tag {{ display:inline-block; padding:2px 8px; border-radius:999px; border:1px solid var(--line); font-size:11px; text-transform:uppercase; }}
    .tag.passed,.tag.implemented,.tag.completed {{ color:var(--accent); border-color:var(--accent); }}
    .tag.failed,.tag.exhausted {{ color:var(--bad); border-color:var(--bad); }}
    .tag.missing,.tag.stale,.tag.in_progress,.tag.in-progress {{ color:var(--warn); border-color:var(--warn); }}
    .events {{ margin-top:24px; }} table {{ width:100%; border-collapse:collapse; }} th,td {{ text-align:left; padding:9px; border-top:1px solid var(--line); vertical-align:top; }}
    .empty {{ padding:18px; color:var(--muted); }} footer {{ margin-top:22px; color:var(--muted); font-size:12px; }}
    @media (max-width:900px) {{ .grid,.board,.metrics {{ grid-template-columns:1fr; }} header {{ flex-direction:column; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div><h1>{esc(model.project.get('projectName'))}</h1><div class="meta">事实截至 {esc(event_facts_through(model))} · source {short_digest(digest)}</div></div>
    <div class="state">{esc(state)}</div>
  </header>
  <div class="grid">
    <section class="panel"><h2>OUTCOME</h2><p>{esc(model.project.get('outcome'))}</p></section>
    <section class="panel"><h2>HARD BOUNDARIES</h2><ul>{constraints}</ul></section>
  </div>
  <section class="metrics">
    <div class="metric"><span>Work implemented</span><strong>{implemented}/{len(required_items)}</strong></div>
    <div class="metric"><span>Checks current-pass</span><strong>{passed_checks}/{len(required_checks)}</strong></div>
    <div class="metric"><span>Final real-chain</span><strong>{passed_claims}/{len(claims)}</strong></div>
  </section>
  <section class="panel warnings"><h2>EVIDENCE GAPS</h2><ul>{warning_html}</ul></section>
  <div class="board">{"".join(bucket_sections)}</div>
  <section class="panel events"><h2>FINAL CLAIMS</h2><table><thead><tr><th>Claim</th><th>Description</th><th>Binding</th><th>Required</th><th>Status</th><th>Run</th></tr></thead><tbody>{claim_rows}</tbody></table></section>
  <section class="panel events"><h2>RECENT EVENTS</h2><table><thead><tr><th>Time</th><th>Type</th><th>Subject</th></tr></thead><tbody>{event_rows}</tbody></table></section>
  <footer>GENERATED · READ ONLY · input sha256:{digest} · generator {TOOL_VERSION}</footer>
</main>
</body>
</html>
<!-- governance-board generator={TOOL_VERSION} input=sha256:{digest} -->
"""
    return document.replace("\r\n", "\n").encode("utf-8")


def derive_board(model: Model, report: dict[str, Any] | None = None) -> bool:
    expected = render_board(model, report=report)
    return atomic_write(model.root / BOARD_REL, expected)


def board_integrity_issue(model: Model) -> str | None:
    if started_event(model) is None and readiness_issues(model):
        return None
    path = model.root / BOARD_REL
    if not path.is_file():
        return "BOARD_MISSING"
    actual = path.read_bytes()
    expected = render_board(model)
    if actual == expected:
        return None
    match = re.search(br'<meta name="governance-input-digest" content="sha256:([0-9a-f]{64})">', actual)
    current = board_input_digest(model)
    if not match or match.group(1).decode("ascii") == current:
        return "BOARD_MODIFIED"
    return "BOARD_STALE"


def evidence_integrity_issues(model: Model) -> list[str]:
    issues: list[str] = []
    seen_runs: set[str] = set()
    for event in model.events:
        if event.get("type") != "CHECK_FINISHED":
            continue
        run_id = event.get("runId")
        if not isinstance(run_id, str) or not run_id:
            issues.append(f"CHECK_FINISHED 事件缺少 runId：{event.get('id')}")
            continue
        if run_id in seen_runs:
            issues.append(f"runId 重复：{run_id}")
        seen_runs.add(run_id)
        _, record_issues = inspect_result_record(model, event)
        issues.extend(record_issues)
    return issues


def runtime_integrity_issues(model: Model) -> list[str]:
    issues: list[str] = []
    if contract_drifted(model):
        issues.append("启动契约发生漂移")
    issues.extend(work_lock_issues(model))
    issues.extend(evidence_integrity_issues(model))
    return list(dict.fromkeys(issues))


def validate_model(model: Model, include_board: bool = True) -> list[str]:
    issues = structural_issues(model)
    issues.extend(evidence_integrity_issues(model))
    if include_board:
        board_issue = board_integrity_issue(model)
        if board_issue:
            issues.append(board_issue)
    return list(dict.fromkeys(issues))


def command_ready(args: argparse.Namespace) -> int:
    model = load_model(resolve_root(args.repo))
    issues = readiness_issues(model)
    payload = {"ready": not issues, "issues": issues, "runtimeState": runtime_state(model)}
    print_json(payload)
    return 0 if not issues else 1


def command_start(args: argparse.Namespace) -> int:
    model = load_model(resolve_root(args.repo))
    issues = readiness_issues(model)
    if issues:
        print_json({"started": False, "issues": issues})
        return 1
    digest = project_digest(model.project)
    existing = started_event(model)
    if existing:
        if existing.get("contractDigest") != digest:
            raise GovernanceError("现有 AUTONOMY_STARTED 与当前契约摘要不同")
        if not isinstance(existing.get("workLock"), dict):
            raise GovernanceError("现有 AUTONOMY_STARTED 缺少 workLock；需在提交前重新初始化治理证据")
        derive_board(model)
        print_json({"started": True, "idempotent": True, "contractDigest": digest})
        return 0
    work_lock = build_work_lock(model)
    append_event(
        model,
        "AUTONOMY_STARTED",
        contractDigest=digest,
        contractSnapshot=model.project,
        workLock=work_lock,
        workLockDigest=sha256_bytes(canonical_bytes(work_lock)),
        budgets=model.project.get("budgets", {}),
        interactionPolicy=model.project.get("interactionPolicy", {}),
    )
    derive_board(model)
    print_json({"started": True, "idempotent": False, "contractDigest": digest})
    return 0


def command_run(args: argparse.Namespace) -> int:
    model = load_model(resolve_root(args.repo))
    result = execute_gate(model, args.item, args.gate)
    print_json(result)
    return 0 if result.get("outcome") == "pass" else 1


def command_record(args: argparse.Namespace) -> int:
    model = load_model(resolve_root(args.repo))
    if started_event(model) is None:
        raise GovernanceError("请先执行 governance.py start")
    if contract_drifted(model):
        raise GovernanceError("启动契约发生漂移；请先执行 governance.py restore-contract")
    integrity_issues = runtime_integrity_issues(model)
    if integrity_issues:
        raise GovernanceError(f"治理完整性检查失败：{'；'.join(integrity_issues)}")
    if terminal_event(model):
        raise GovernanceError("项目已进入终态")
    event_type = args.type.upper()
    if event_type not in RUNTIME_EVENT_TYPES:
        raise GovernanceError(f"不支持的运行事件：{event_type}")
    fields: dict[str, Any] = {}
    if event_type in WORK_EVENT_TYPES:
        if not args.item or args.item not in model.items:
            raise GovernanceError("工作事件需要有效的 --item")
        fields["itemRef"] = args.item
    elif args.item:
        if args.item not in model.items:
            raise GovernanceError(f"未知工作项：{args.item}")
        fields["itemRef"] = args.item
    if args.message:
        fields["message"] = args.message
    if args.details:
        try:
            details = json.loads(args.details)
        except json.JSONDecodeError as exc:
            raise GovernanceError("--details 应为 JSON 对象") from exc
        if not isinstance(details, dict):
            raise GovernanceError("--details 应为 JSON 对象")
        fields["details"] = details
    event = append_event(model, event_type, **fields)
    derive_board(model)
    print_json(event)
    return 0


def command_restore_contract(args: argparse.Namespace) -> int:
    model = load_model(resolve_root(args.repo))
    start = started_event(model)
    if start is None:
        raise GovernanceError("自主运行尚未开始")
    if terminal_event(model):
        raise GovernanceError("项目已进入终态")
    snapshot = start.get("contractSnapshot")
    if not isinstance(snapshot, dict):
        raise GovernanceError("AUTONOMY_STARTED 缺少 contractSnapshot")
    expected = str(start.get("contractDigest", ""))
    if project_digest(snapshot) != expected:
        raise GovernanceError("锁定契约快照摘要不匹配")
    changed = atomic_write(model.root / PROJECT_REL, json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    model.project = snapshot
    if changed:
        append_event(model, "CONTRACT_RESTORED", contractDigest=expected)
    derive_board(model)
    print_json({"restored": changed, "contractDigest": expected})
    return 0


def command_restore_work_contract(args: argparse.Namespace) -> int:
    model = load_model(resolve_root(args.repo))
    start = started_event(model)
    if start is None:
        raise GovernanceError("自主运行尚未开始")
    if terminal_event(model):
        raise GovernanceError("项目已进入终态")
    locked = locked_work_snapshot(model)
    if locked is None:
        raise GovernanceError("AUTONOMY_STARTED 缺少 workLock")
    expected = start.get("workLockDigest")
    if not isinstance(expected, str) or sha256_bytes(canonical_bytes(locked)) != expected:
        raise GovernanceError("锁定工作契约摘要不匹配")

    work = json.loads(json.dumps(model.work, ensure_ascii=False))
    locked_gates = {
        str(gate.get("id")): gate
        for gate in locked.get("requiredGates", [])
        if isinstance(gate, dict) and str(gate.get("id", "")).strip()
    }
    current_gates = work.get("gates", [])
    restored_gates: list[dict[str, Any]] = []
    seen_gates: set[str] = set()
    for gate in current_gates if isinstance(current_gates, list) else []:
        if not isinstance(gate, dict):
            continue
        gate_id = str(gate.get("id", ""))
        restored_gates.append(json.loads(json.dumps(locked_gates.get(gate_id, gate), ensure_ascii=False)))
        seen_gates.add(gate_id)
    for gate_id, gate in locked_gates.items():
        if gate_id not in seen_gates:
            restored_gates.append(json.loads(json.dumps(gate, ensure_ascii=False)))
    work["gates"] = restored_gates

    locked_items = {
        str(item.get("id")): item
        for item in locked.get("requiredItems", [])
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    current_items = work.get("items", [])
    restored_items: list[dict[str, Any]] = []
    seen_items: set[str] = set()
    for item in current_items if isinstance(current_items, list) else []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", ""))
        locked_item = locked_items.get(item_id)
        if locked_item is not None:
            item["requiredForFinal"] = True
            for field in ("gateRefs", "pathScopes"):
                current_values = [str(value) for value in item.get(field, [])]
                for value in locked_item.get(field, []):
                    if str(value) not in current_values:
                        current_values.append(str(value))
                item[field] = current_values
        restored_items.append(item)
        seen_items.add(item_id)
    for item_id, item in locked_items.items():
        if item_id not in seen_items:
            restored_items.append(json.loads(json.dumps(item, ensure_ascii=False)))
    work["items"] = restored_items

    changed = canonical_bytes(work) != canonical_bytes(model.work)
    if changed:
        work["revision"] = max(int(model.work.get("revision", 0)) + 1, int(work.get("revision", 0)))
        atomic_write(model.root / WORK_REL, json.dumps(work, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
        model.work = work
        append_event(model, "WORK_CONTRACT_RESTORED", workLockDigest=expected)
    derive_board(model)
    print_json({"restored": changed, "workLockDigest": expected})
    return 0


def command_check(args: argparse.Namespace) -> int:
    model = load_model(resolve_root(args.repo))
    report = completion_report(model)
    integrity_issues = runtime_integrity_issues(model) if started_event(model) else []
    if integrity_issues:
        report["eligible"] = False
        report["integrityIssues"] = integrity_issues
        report["issues"] = [
            {
                "kind": "integrity",
                "status": "failed",
                "message": message,
            }
            for message in integrity_issues
        ] + report.get("issues", [])
    if args.completion and report.get("eligible") and started_event(model) and terminal_event(model) is None:
        append_event(model, "PROJECT_COMPLETED", completionDigest=sha256_bytes(canonical_bytes(report)))
        derive_board(model)
        report = completion_report(model)
    report["boardIntegrity"] = board_integrity_issue(model) or "current"
    print_json(report)
    return 0 if report.get("eligible") else 1


def command_status(args: argparse.Namespace) -> int:
    model = load_model(resolve_root(args.repo))
    readiness = readiness_issues(model)
    report = completion_report(model) if started_event(model) else None
    payload = {
        "projectId": model.project.get("projectId"),
        "projectName": model.project.get("projectName"),
        "runtimeState": runtime_state(model),
        "ready": not readiness,
        "readinessIssues": readiness,
        "contractDigest": started_event(model).get("contractDigest") if started_event(model) else None,
        "completion": report,
        "integrityIssues": runtime_integrity_issues(model) if started_event(model) else [],
        "board": str(model.root / BOARD_REL) if (model.root / BOARD_REL).exists() else None,
    }
    print_json(payload)
    return 0


def command_derive(args: argparse.Namespace) -> int:
    model = load_model(resolve_root(args.repo))
    changed = derive_board(model)
    print_json(
        {
            "changed": changed,
            "board": str(model.root / BOARD_REL),
            "inputDigest": board_input_digest(model),
        }
    )
    return 0


def command_validate(args: argparse.Namespace) -> int:
    model = load_model(resolve_root(args.repo))
    issues = validate_model(model)
    print_json({"valid": not issues, "issues": issues})
    return 0 if not issues else 1


def final_report_requested(model: Model) -> bool:
    return latest_event(model, "FINAL_REPORT_REQUESTED") is not None


def hook_payload(model: Model, hook_input: dict[str, Any]) -> dict[str, Any]:
    if started_event(model) is None:
        return {"continue": True, "decision": "approve"}
    terminal = terminal_event(model)
    if terminal:
        if terminal.get("type") == "AUTONOMY_EXHAUSTED" and not final_report_requested(model):
            append_event(model, "FINAL_REPORT_REQUESTED", reason=terminal.get("reason"))
            derive_board(model)
            return {
                "decision": "block",
                "reason": "项目已达到 EXHAUSTED。整理最终证据报告：已完成结果、运行命令与结果、未闭合项、耗尽原因、残余风险和恢复入口；随后结束本轮自主运行。",
            }
        derive_board(model)
        terminal_state = "EXHAUSTED" if terminal.get("type") == "AUTONOMY_EXHAUSTED" else "COMPLETED"
        return {
            "continue": True,
            "decision": "approve",
            "systemMessage": f"Governance state: {terminal_state}",
        }
    if contract_drifted(model):
        return {
            "decision": "block",
            "reason": "启动契约发生漂移。继续执行：python tools/governance.py restore-contract；随后依据锁定契约恢复自主运行。",
        }
    integrity_issues = runtime_integrity_issues(model)
    if integrity_issues:
        return {
            "decision": "block",
            "reason": (
                "治理完整性检查失败："
                + "；".join(integrity_issues)
                + "。检查 evidence 文件；若是工作契约漂移，执行 python tools/governance.py restore-work-contract。"
            ),
        }

    report = completion_report(model)
    if report.get("eligible"):
        append_event(model, "PROJECT_COMPLETED", completionDigest=sha256_bytes(canonical_bytes(report)))
        derive_board(model, report=report)
        return {"continue": True, "decision": "approve", "systemMessage": "Governance state: COMPLETED"}

    progress = progress_digest(model, report)
    exhaustion = budget_exhaustion_reason(model, report, progress)
    if exhaustion:
        append_event(model, "AUTONOMY_EXHAUSTED", reason=exhaustion, progressDigest=progress)
        append_event(model, "FINAL_REPORT_REQUESTED", reason=exhaustion)
        derive_board(model, report=report)
        return {
            "decision": "block",
            "reason": f"项目已达到 EXHAUSTED：{exhaustion}。整理最终证据报告：已完成结果、运行命令与结果、未闭合项、残余风险和恢复入口；随后结束本轮自主运行。",
        }

    action = next_action(model, report)
    append_event(
        model,
        "STOP_CONTINUED",
        progressDigest=progress,
        stopHookActive=bool(hook_input.get("stop_hook_active")),
        nextAction=action,
    )
    derive_board(model, report=report)
    return {
        "decision": "block",
        "reason": f"项目处于自主运行期。{action} 依据锁定契约继续推进，直至 COMPLETED 或 EXHAUSTED；运行期保持零用户提问。",
    }


def command_hook_stop(args: argparse.Namespace) -> int:
    try:
        raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
        if not isinstance(hook_input, dict):
            hook_input = {}
        model = load_model(resolve_root(args.repo))
        payload = hook_payload(model, hook_input)
    except Exception as exc:  # Hook stdout must remain valid JSON.
        payload = {
            "decision": "block",
            "reason": f"治理检查出现错误：{type(exc).__name__}: {exc}。修复治理数据或脚本后继续自主运行。",
        }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    sys.stdout.write("\n")
    return 0


def add_repo_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", help="Repository root; defaults to searching upward from cwd")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=TOOL_VERSION)
    sub = parser.add_subparsers(dest="command", required=True)

    ready = sub.add_parser("ready", help="Validate the startup boundary")
    add_repo_argument(ready)
    ready.set_defaults(func=command_ready)

    start = sub.add_parser("start", help="Freeze the contract and begin autonomy")
    add_repo_argument(start)
    start.set_defaults(func=command_start)

    run = sub.add_parser("run", help="Execute a registered Gate and record evidence")
    add_repo_argument(run)
    run.add_argument("--item", required=True)
    run.add_argument("--gate", required=True)
    run.set_defaults(func=command_run)

    record = sub.add_parser("record", help="Append an autonomous runtime event")
    add_repo_argument(record)
    record.add_argument("--type", required=True)
    record.add_argument("--item")
    record.add_argument("--message")
    record.add_argument("--details", help="JSON object")
    record.set_defaults(func=command_record)

    restore = sub.add_parser("restore-contract", help="Restore the project contract frozen at start")
    add_repo_argument(restore)
    restore.set_defaults(func=command_restore_contract)

    restore_work = sub.add_parser("restore-work-contract", help="Restore locked final Gates and required work bindings")
    add_repo_argument(restore_work)
    restore_work.set_defaults(func=command_restore_work_contract)

    check = sub.add_parser("check", help="Evaluate current completion evidence")
    add_repo_argument(check)
    check.add_argument("--completion", action="store_true", help="Compatibility flag; completion is the V1 check")
    check.set_defaults(func=command_check)

    status = sub.add_parser("status", help="Print deterministic project status")
    add_repo_argument(status)
    status.set_defaults(func=command_status)

    derive = sub.add_parser("derive", help="Regenerate the single-file HTML board")
    add_repo_argument(derive)
    derive.set_defaults(func=command_derive)

    validate = sub.add_parser("validate", help="Validate governance and evidence integrity")
    add_repo_argument(validate)
    validate.set_defaults(func=command_validate)

    hook = sub.add_parser("hook-stop", help="Codex/Devin Stop hook protocol")
    add_repo_argument(hook)
    hook.set_defaults(func=command_hook_stop)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except GovernanceError as exc:
        print(f"governance: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("governance: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
