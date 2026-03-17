from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import MemoryRuntimeConfig


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _format_knowledge_items(items: list[dict[str, Any]]) -> str:
    if not items:
        return "- No cold-memory knowledge items were loaded.\n"

    sections: list[str] = []
    for item in items:
        sections.append(f"### {item['title']}\n\n{item['content']}\n")
    return "\n".join(sections)


def _format_module_status(items: list[dict[str, Any]]) -> str:
    if not items:
        return "- No module documents were discovered.\n"

    lines = [
        f"- `{item['module_id']}`: {item['title']} ({item['source_path']})"
        for item in items
    ]
    return "\n".join(lines) + "\n"


def _format_task_snapshot_extras(task_state: dict[str, Any]) -> str:
    lines: list[str] = []
    reference_ref = task_state.get("reference_ref")
    if reference_ref:
        lines.append(f"- Reference ref: `{reference_ref}`")
    repository = task_state.get("repository")
    if repository:
        lines.append(f"- Repository: `{repository}`")
    issue_url = task_state.get("issue_url")
    if issue_url:
        lines.append(f"- Issue URL: `{issue_url}`")
    pull_request_number = task_state.get("pull_request_number")
    if pull_request_number:
        lines.append(f"- Pull request: `#{pull_request_number}`")
    pull_request_url = task_state.get("pull_request_url")
    if pull_request_url:
        lines.append(f"- Pull request URL: `{pull_request_url}`")
    cleanup_status = task_state.get("cleanup_status")
    if cleanup_status:
        lines.append(f"- Cleanup status: `{cleanup_status}`")
    if "issue_closed" in task_state:
        lines.append(f"- Issue closed: `{task_state['issue_closed']}`")
    if "done_transitioned" in task_state:
        lines.append(f"- Done transitioned: `{task_state['done_transitioned']}`")
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _record_timestamp(
    item: dict[str, Any],
    *,
    fields: tuple[str, ...] = ("executed_at", "generated_at"),
) -> datetime:
    for field in fields:
        parsed = _parse_timestamp(item.get(field))
        if parsed is not None:
            return parsed
    return datetime.min.replace(tzinfo=UTC)


def _latest_record(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    return max(items, key=_record_timestamp)


def _format_task_events(items: list[dict[str, Any]]) -> str:
    if not items:
        return "- No task events were recorded.\n"

    lines = []
    for item in sorted(
        items,
        key=_record_timestamp,
        reverse=True,
    )[:5]:
        lines.append(
            f"- `{item['event_type']}` @ `{item.get('generated_at', 'unknown')}`: {item['summary']}"
        )
    return "\n".join(lines) + "\n"


def compile_context_pack(
    config: MemoryRuntimeConfig,
    store: Any,
    *,
    issue_identifier: str,
    role: str,
) -> Path:
    generated_at = _utc_now()
    task_state = store.find(
        "task_state", filters={"issue_identifier": issue_identifier}
    )
    task_events = store.find(
        "task_events", filters={"issue_identifier": issue_identifier}
    )
    deploy_runs = store.find(
        "deploy_runs", filters={"issue_identifier": issue_identifier}
    )
    health_results = store.find(
        "health_results", filters={"issue_identifier": issue_identifier}
    )
    knowledge_items = store.find(
        "knowledge_items", filters={"source_ref": config.reference_ref}
    )
    module_status = store.find(
        "module_status", filters={"source_ref": config.reference_ref}
    )

    if not task_state:
        raise ValueError(f"No task_state found for issue {issue_identifier}")

    current_task_state = task_state[0]
    current_deploy = _latest_record(deploy_runs) or {
        "status": "unknown",
        "summary": "No deploy summary available.",
    }
    current_health = _latest_record(health_results) or {
        "status": "unknown",
        "summary": "No health summary available.",
    }

    content = f"""# FreshQuant Memory Context Pack

- Generated at: `{generated_at}`
- Issue: `{issue_identifier}`
- Role: `{role}`

This pack is derived context. It does not replace GitHub, `docs/current/**`, or deploy/health results.
If any conflict appears, formal truth wins over memory context.

## Task Snapshot

- Issue state: `{current_task_state['issue_state']}`
- Branch: `{current_task_state['branch_name']}`
- Git status: `{current_task_state['git_status']}`
{_format_task_snapshot_extras(current_task_state)}

## Runtime Snapshot

- Deploy: `{current_deploy['status']}` - {current_deploy['summary']}
- Health: `{current_health['status']}` - {current_health['summary']}

## Recent Task Events

{_format_task_events(task_events)}

## Cold Memory

{_format_knowledge_items(knowledge_items)}
## Module Status

{_format_module_status(module_status)}"""

    output_path = (
        config.artifact_root / "context-packs" / issue_identifier / f"{role}.md"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

    store.upsert_many(
        "context_packs",
        [
            {
                "context_pack_id": f"{issue_identifier}:{role}",
                "issue_identifier": issue_identifier,
                "role": role,
                "path": str(output_path),
                "generated_at": generated_at,
            }
        ],
        key_fields=("context_pack_id",),
    )

    return output_path
