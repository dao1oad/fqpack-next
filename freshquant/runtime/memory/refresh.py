from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cold_memory import load_cold_memory_items
from .config import MemoryRuntimeConfig


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _extract_title(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return path.stem.replace("-", " ").title()


def _collect_module_status(
    config: MemoryRuntimeConfig, *, generated_at: str
) -> list[dict[str, Any]]:
    modules_root = config.repo_root / "docs" / "current" / "modules"
    if not modules_root.exists():
        return []

    items: list[dict[str, Any]] = []
    for path in sorted(modules_root.glob("*.md")):
        items.append(
            {
                "module_id": path.stem,
                "title": _extract_title(path),
                "source_path": str(path),
                "status": "documented",
                "generated_at": generated_at,
            }
        )
    return items


def _normalize_runtime_document(
    payload: dict[str, Any],
    *,
    source_path: Path,
    id_field: str,
) -> dict[str, Any]:
    key_aliases = {
        "issueIdentifier": "issue_identifier",
        "deployRunId": "deploy_run_id",
        "healthResultId": "health_result_id",
        "sourcePath": "source_path",
        "generatedAt": "generated_at",
        "executedAt": "executed_at",
    }
    normalized = {key_aliases.get(key, key): value for key, value in payload.items()}
    normalized.setdefault("source_path", str(source_path))
    normalized.setdefault(id_field, source_path.stem)
    return normalized


def _load_json_documents(root: Path, *, id_field: str) -> list[dict[str, Any]]:
    if not root.exists():
        return []

    documents: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            documents.append(
                _normalize_runtime_document(
                    payload,
                    source_path=path,
                    id_field=id_field,
                )
            )
    return documents


def _parse_markdown_sections(content: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current_section = stripped[3:].strip()
            sections.setdefault(current_section, [])
            continue
        if current_section is not None:
            sections[current_section].append(line.rstrip())
    return sections


def _extract_markdown_bullets(lines: list[str]) -> list[str]:
    bullets: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
    return bullets


def _join_summary(parts: list[str], *, fallback: str) -> str:
    cleaned = [part for part in parts if part]
    if not cleaned:
        return fallback
    return " | ".join(cleaned)


def _classify_health_check(check: str) -> str:
    lowered = check.lower()
    codes = [int(match) for match in re.findall(r"(?<!\d)([1-5]\d{2})(?!\d)", check)]
    if any(code >= 400 for code in codes):
        return "fail"
    if any(code < 400 for code in codes):
        return "pass"

    failure_tokens = (
        "failed",
        "failure",
        "error",
        "timeout",
        "timed out",
        "unhealthy",
        "exception",
        "refused",
        "失败",
        "未通过",
        "错误",
        "异常",
        "超时",
        "不可用",
    )
    if any(token in lowered for token in failure_tokens):
        return "fail"

    success_tokens = (
        "passed",
        "pass",
        "success",
        "healthy",
        "ok",
        "通过",
        "成功",
        "正常",
    )
    if any(token in lowered for token in success_tokens):
        return "pass"

    return "documented"


def _derive_health_status(health_checks: list[str]) -> str:
    statuses = {_classify_health_check(check) for check in health_checks}
    statuses.discard("documented")
    if "fail" in statuses:
        return "fail"
    if "pass" in statuses:
        return "pass"
    return "documented"


def _load_issue_deployment_artifacts(
    config: MemoryRuntimeConfig,
    *,
    issue_identifier: str,
    generated_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    deployment_comment_path = (
        config.service_root / "artifacts" / issue_identifier / "deployment-comment.md"
    )
    if not deployment_comment_path.exists():
        return [], [], []

    content = deployment_comment_path.read_text(encoding="utf-8")
    sections = _parse_markdown_sections(content)
    deploy_scope = _extract_markdown_bullets(sections.get("部署范围", []))
    health_checks = _extract_markdown_bullets(sections.get("健康检查", []))
    deploy_results = _extract_markdown_bullets(sections.get("最终部署结果", []))

    deploy_summary = _join_summary(
        [
            f"surfaces={'; '.join(deploy_scope)}" if deploy_scope else "",
            f"result={'; '.join(deploy_results)}" if deploy_results else "",
        ],
        fallback=f"Deployment comment captured from {deployment_comment_path}",
    )
    deploy_runs = [
        {
            "deploy_run_id": f"{issue_identifier}:deployment-comment",
            "issue_identifier": issue_identifier,
            "status": "documented",
            "summary": deploy_summary,
            "deployment_scope": deploy_scope,
            "deployment_results": deploy_results,
            "source_path": str(deployment_comment_path),
            "generated_at": generated_at,
        }
    ]

    health_results: list[dict[str, Any]] = []
    if health_checks:
        health_results.append(
            {
                "health_result_id": f"{issue_identifier}:deployment-comment",
                "issue_identifier": issue_identifier,
                "status": _derive_health_status(health_checks),
                "summary": "; ".join(health_checks),
                "checks": health_checks,
                "source_path": str(deployment_comment_path),
                "generated_at": generated_at,
            }
        )

    task_events = [
        {
            "event_id": f"{issue_identifier}:deployment-summary:{generated_at}",
            "issue_identifier": issue_identifier,
            "event_type": "deployment_summary",
            "summary": deploy_summary,
            "generated_at": generated_at,
            "source_path": str(deployment_comment_path),
        }
    ]
    return deploy_runs, health_results, task_events


def _load_cleanup_result(
    config: MemoryRuntimeConfig,
    *,
    issue_identifier: str,
    generated_at: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cleanup_result_path = (
        config.service_root
        / "artifacts"
        / "cleanup-results"
        / f"{issue_identifier}.json"
    )
    if not cleanup_result_path.exists():
        return {}, []

    try:
        payload = json.loads(cleanup_result_path.read_text(encoding="utf-8"))
    except Exception:
        return {}, []

    if not isinstance(payload, dict):
        return {}, []

    success = bool(payload.get("success"))
    issue_closed = bool(payload.get("issueClosed"))
    done_transitioned = bool(payload.get("doneTransitioned"))
    workspace_deleted = bool(payload.get("workspaceDeleted"))
    remote_branch_deleted = bool(payload.get("remoteBranchDeleted"))
    executed_at = str(payload.get("executedAt") or generated_at)
    errors = payload.get("errors") or []
    error_summary = " | ".join(str(item) for item in errors if item)

    task_state_patch = {
        "cleanup_status": "success" if success else "failed",
        "cleanup_executed_at": executed_at,
        "issue_closed": issue_closed,
        "done_transitioned": done_transitioned,
    }
    summary = _join_summary(
        [
            f"success={success}",
            f"issue_closed={issue_closed}",
            f"done_transitioned={done_transitioned}",
            f"workspace_deleted={workspace_deleted}",
            f"remote_branch_deleted={remote_branch_deleted}",
            f"errors={error_summary}" if error_summary else "",
        ],
        fallback=f"Cleanup result captured from {cleanup_result_path}",
    )
    task_events = [
        {
            "event_id": f"{issue_identifier}:cleanup:{executed_at}",
            "issue_identifier": issue_identifier,
            "event_type": "cleanup_result",
            "summary": summary,
            "generated_at": executed_at,
            "source_path": str(cleanup_result_path),
        }
    ]
    return task_state_patch, task_events


def _load_cleanup_request(
    config: MemoryRuntimeConfig,
    *,
    issue_identifier: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cleanup_request_path = (
        config.service_root
        / "artifacts"
        / "cleanup-requests"
        / f"{issue_identifier}.json"
    )
    if not cleanup_request_path.exists():
        return {}, []

    try:
        payload = json.loads(cleanup_request_path.read_text(encoding="utf-8"))
    except Exception:
        return {}, []

    if not isinstance(payload, dict):
        return {}, []

    requested_at = str(payload.get("requestedAt") or _utc_now())
    pull_request_number = payload.get("pullRequestNumber")
    task_state_patch = {
        "repository": payload.get("repository"),
        "issue_url": payload.get("issueUrl"),
        "pull_request_number": pull_request_number,
        "pull_request_url": payload.get("pullRequestUrl"),
        "cleanup_requested_at": requested_at,
    }
    task_event_summary = _join_summary(
        [
            f"pr={pull_request_number}" if pull_request_number else "",
            f"branch={payload.get('branchName')}" if payload.get("branchName") else "",
            (
                f"repository={payload.get('repository')}"
                if payload.get("repository")
                else ""
            ),
        ],
        fallback=f"Cleanup requested from {cleanup_request_path}",
    )
    task_events = [
        {
            "event_id": f"{issue_identifier}:cleanup-request:{requested_at}",
            "issue_identifier": issue_identifier,
            "event_type": "cleanup_requested",
            "summary": task_event_summary,
            "generated_at": requested_at,
            "source_path": str(cleanup_request_path),
        }
    ]
    return task_state_patch, task_events


def refresh_memory(
    config: MemoryRuntimeConfig,
    store: Any,
    *,
    issue_identifier: str,
    issue_state: str,
    branch_name: str,
    git_status: str,
) -> dict[str, int]:
    generated_at = _utc_now()
    knowledge_items = load_cold_memory_items(
        config.cold_memory_root,
        generated_at=generated_at,
    )
    module_status = _collect_module_status(config, generated_at=generated_at)
    cleanup_request_state_patch, cleanup_request_events = _load_cleanup_request(
        config,
        issue_identifier=issue_identifier,
    )
    cleanup_state_patch, cleanup_events = _load_cleanup_result(
        config,
        issue_identifier=issue_identifier,
        generated_at=generated_at,
    )
    task_state_payload = {
        "issue_identifier": issue_identifier,
        "issue_state": issue_state,
        "branch_name": branch_name,
        "git_status": git_status,
        "repo_root": str(config.repo_root),
        "service_root": str(config.service_root),
        "generated_at": generated_at,
    }
    task_state_payload.update(cleanup_request_state_patch)
    task_state_payload.update(cleanup_state_patch)

    task_state = [task_state_payload]
    task_events = [
        {
            "event_id": f"{issue_identifier}:refresh:{generated_at}",
            "issue_identifier": issue_identifier,
            "event_type": "memory_refresh",
            "summary": "Refreshed cold memory, task state, and runtime summaries.",
            "generated_at": generated_at,
        }
    ]

    artifacts_root = config.service_root / "artifacts"
    deploy_runs = _load_json_documents(
        artifacts_root / "deploy-runs",
        id_field="deploy_run_id",
    )
    health_results = _load_json_documents(
        artifacts_root / "health-results",
        id_field="health_result_id",
    )
    issue_deploy_runs, issue_health_results, issue_events = (
        _load_issue_deployment_artifacts(
            config,
            issue_identifier=issue_identifier,
            generated_at=generated_at,
        )
    )
    deploy_runs.extend(issue_deploy_runs)
    health_results.extend(issue_health_results)
    task_events.extend(issue_events)
    task_events.extend(cleanup_request_events)
    task_events.extend(cleanup_events)

    if not deploy_runs:
        deploy_runs = [
            {
                "deploy_run_id": f"{issue_identifier}:deploy-unavailable",
                "issue_identifier": issue_identifier,
                "status": "unavailable",
                "summary": f"No deploy artifacts found under {artifacts_root / 'deploy-runs'}",
                "generated_at": generated_at,
            }
        ]

    if not health_results:
        health_results = [
            {
                "health_result_id": f"{issue_identifier}:health-unavailable",
                "issue_identifier": issue_identifier,
                "status": "unavailable",
                "summary": f"No health artifacts found under {artifacts_root / 'health-results'}",
                "generated_at": generated_at,
            }
        ]

    store.upsert_many("task_state", task_state, key_fields=("issue_identifier",))
    store.upsert_many("task_events", task_events, key_fields=("event_id",))
    store.upsert_many("deploy_runs", deploy_runs, key_fields=("deploy_run_id",))
    store.upsert_many(
        "health_results", health_results, key_fields=("health_result_id",)
    )
    if knowledge_items:
        store.upsert_many(
            "knowledge_items",
            knowledge_items,
            key_fields=("knowledge_item_id",),
        )
    if module_status:
        store.upsert_many("module_status", module_status, key_fields=("module_id",))

    return {
        "task_state": len(task_state),
        "task_events": len(task_events),
        "deploy_runs": len(deploy_runs),
        "health_results": len(health_results),
        "knowledge_items": len(knowledge_items),
        "module_status": len(module_status),
    }
