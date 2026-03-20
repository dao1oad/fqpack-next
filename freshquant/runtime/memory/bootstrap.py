from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping

from .compiler import compile_context_pack
from .config import MemoryRuntimeConfig
from .refresh import refresh_memory

_ISSUE_IDENTIFIER_PATTERN = re.compile(r"(?i)([A-Z]+-\d+)")
_SANITIZE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def derive_issue_identifier(
    *,
    workspace_path: str | Path,
    branch_name: str,
    issue_identifier: str | None = None,
) -> str:
    if issue_identifier and issue_identifier.strip():
        return issue_identifier.strip()

    workspace_name = Path(workspace_path).resolve().name
    workspace_match = _ISSUE_IDENTIFIER_PATTERN.fullmatch(workspace_name)
    if workspace_match:
        return workspace_match.group(1).upper()

    branch_match = _ISSUE_IDENTIFIER_PATTERN.search(branch_name or "")
    if branch_match:
        return branch_match.group(1).upper()

    sanitized_name = _SANITIZE_PATTERN.sub("-", workspace_name).strip("-")
    if not sanitized_name:
        sanitized_name = "workspace"
    return f"LOCAL-{sanitized_name}"


def derive_memory_role(
    *,
    issue_state: str | None,
    role: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    if role and role.strip():
        return role.strip()

    env = os.environ if environ is None else environ
    env_role = env.get("FQ_MEMORY_CONTEXT_ROLE")
    if env_role and env_role.strip():
        return env_role.strip()

    return "codex"


def bootstrap_memory_context(
    config: MemoryRuntimeConfig,
    store: Any,
    *,
    workspace_path: str | Path,
    branch_name: str,
    git_status: str,
    issue_state: str | None = None,
    role: str | None = None,
    issue_identifier: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    resolved_issue_identifier = derive_issue_identifier(
        workspace_path=workspace_path,
        branch_name=branch_name,
        issue_identifier=issue_identifier,
    )
    resolved_issue_state = (issue_state or "").strip() or "Local Session"
    resolved_role = derive_memory_role(
        issue_state=resolved_issue_state,
        role=role,
        environ=environ,
    )

    refresh_summary = refresh_memory(
        config,
        store,
        issue_identifier=resolved_issue_identifier,
        issue_state=resolved_issue_state,
        branch_name=branch_name,
        git_status=git_status,
    )
    context_pack_path = compile_context_pack(
        config,
        store,
        issue_identifier=resolved_issue_identifier,
        role=resolved_role,
    )

    return {
        "issue_identifier": resolved_issue_identifier,
        "issue_state": resolved_issue_state,
        "role": resolved_role,
        "context_pack_path": str(context_pack_path),
        "refresh_summary": refresh_summary,
    }
