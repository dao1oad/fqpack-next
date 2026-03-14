from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from freshquant.runtime.memory import (
    InMemoryMemoryStore,
    MemoryRuntimeConfig,
    compile_context_pack,
    refresh_memory,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_refresh_memory_populates_core_collections(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    service_root = tmp_path / "service"
    cold_root = repo_root / ".codex" / "memory"
    module_doc = repo_root / "docs" / "current" / "modules" / "runtime-observability.md"

    _write(
        cold_root / "deploy-surfaces.md",
        "# Deploy Surfaces\n\n- `runtime/symphony/**` -> restart orchestrator\n",
    )
    _write(
        cold_root / "workflow-rules.md",
        "# Workflow Rules\n\n- GitHub is the formal truth.\n",
    )
    _write(
        cold_root / "pitfalls.md",
        "# Pitfalls\n\n- Do not treat merge as done.\n",
    )
    _write(module_doc, "# Runtime Observability\n\nCurrent runtime module facts.\n")

    config = MemoryRuntimeConfig(
        repo_root=repo_root,
        service_root=service_root,
        cold_memory_root=cold_root,
        artifact_root=service_root / "artifacts" / "memory",
        mongo_host="127.0.0.1",
        mongo_port=27027,
        mongo_db="fq_memory",
    )
    store = InMemoryMemoryStore()

    summary = refresh_memory(
        config,
        store,
        issue_identifier="GH-166",
        issue_state="In Progress",
        branch_name="codex/gh-166-symphony-global-stewardship-codex",
        git_status="?? .symphony-workspace-ready",
    )

    assert summary["knowledge_items"] == 3
    assert summary["module_status"] == 1
    assert store.count("task_state") == 1
    assert store.count("task_events") >= 1
    assert store.count("deploy_runs") == 1
    assert store.count("health_results") == 1
    assert store.count("knowledge_items") == 3
    assert store.count("module_status") == 1

    task_state = store.find("task_state")[0]
    assert task_state["issue_identifier"] == "GH-166"
    assert task_state["issue_state"] == "In Progress"
    assert task_state["branch_name"] == "codex/gh-166-symphony-global-stewardship-codex"

    deploy_run = store.find("deploy_runs")[0]
    assert deploy_run["status"] == "unavailable"
    assert "No deploy artifacts found" in deploy_run["summary"]

    knowledge_titles = {item["title"] for item in store.find("knowledge_items")}
    assert knowledge_titles == {"Deploy Surfaces", "Workflow Rules", "Pitfalls"}


def test_refresh_memory_reads_deployment_comment_and_cleanup_result_artifacts(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    service_root = tmp_path / "service"
    cold_root = repo_root / ".codex" / "memory"

    _write(
        cold_root / "workflow-rules.md", "# Workflow Rules\n\n- Read memory first.\n"
    )
    _write(
        service_root / "artifacts" / "GH-166" / "deployment-comment.md",
        """当前 Issue 在合并、部署和健康检查完成后，可以进入最终 cleanup 与 `Done`。

## 部署范围

- Docker：`fq_apiserver`、`fq_webui`
- 宿主机：`position_management.worker`

## 健康检查

- `GET http://127.0.0.1:15000/api/position-management/dashboard` 返回 `200`
- `GET http://127.0.0.1:18080/position-management` 返回 `200`

## 最终部署结果

- 新 API、Web UI 路由和静态资源均已部署并通过访问验证
""",
    )
    _write(
        service_root / "artifacts" / "cleanup-results" / "GH-166.json",
        json.dumps(
            {
                "issueIdentifier": "GH-166",
                "success": True,
                "remoteBranchDeleted": False,
                "workspaceDeleted": True,
                "issueClosed": True,
                "doneTransitioned": True,
                "executedAt": "2026-03-14T10:00:00+08:00",
                "errors": [],
            },
            ensure_ascii=False,
        ),
    )

    config = MemoryRuntimeConfig(
        repo_root=repo_root,
        service_root=service_root,
        cold_memory_root=cold_root,
        artifact_root=service_root / "artifacts" / "memory",
        mongo_host="127.0.0.1",
        mongo_port=27027,
        mongo_db="fq_memory",
    )
    store = InMemoryMemoryStore()

    summary = refresh_memory(
        config,
        store,
        issue_identifier="GH-166",
        issue_state="Global Stewardship",
        branch_name="main",
        git_status="clean",
    )

    assert summary["deploy_runs"] == 1
    assert summary["health_results"] == 1
    assert summary["task_events"] >= 2

    deploy_run = store.find("deploy_runs", filters={"issue_identifier": "GH-166"})[0]
    assert deploy_run["status"] == "documented"
    assert "fq_apiserver" in deploy_run["summary"]
    assert "position_management.worker" in deploy_run["summary"]

    health_result = store.find(
        "health_results", filters={"issue_identifier": "GH-166"}
    )[0]
    assert health_result["status"] == "pass"
    assert "dashboard" in health_result["summary"]
    assert "position-management" in health_result["summary"]

    task_state = store.find("task_state", filters={"issue_identifier": "GH-166"})[0]
    assert task_state["cleanup_status"] == "success"
    assert task_state["done_transitioned"] is True

    cleanup_events = [
        item
        for item in store.find("task_events", filters={"issue_identifier": "GH-166"})
        if item["event_type"] == "cleanup_result"
    ]
    assert len(cleanup_events) == 1
    assert "issue_closed=True" in cleanup_events[0]["summary"]


def test_refresh_memory_reads_cleanup_request_metadata_into_task_state(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    service_root = tmp_path / "service"
    cold_root = repo_root / ".codex" / "memory"

    _write(
        cold_root / "workflow-rules.md", "# Workflow Rules\n\n- Read memory first.\n"
    )
    _write(
        service_root / "artifacts" / "cleanup-requests" / "GH-166.json",
        json.dumps(
            {
                "issueIdentifier": "GH-166",
                "branchName": "feature/GH-166-memory-layer",
                "repository": "dao1oad/fqpack-next",
                "issueUrl": "https://github.com/dao1oad/fqpack-next/issues/166",
                "pullRequestNumber": 188,
                "pullRequestUrl": "https://github.com/dao1oad/fqpack-next/pull/188",
                "requestedAt": "2026-03-14T12:00:00+08:00",
            },
            ensure_ascii=False,
        ),
    )

    config = MemoryRuntimeConfig(
        repo_root=repo_root,
        service_root=service_root,
        cold_memory_root=cold_root,
        artifact_root=service_root / "artifacts" / "memory",
        mongo_host="127.0.0.1",
        mongo_port=27027,
        mongo_db="fq_memory",
    )
    store = InMemoryMemoryStore()

    summary = refresh_memory(
        config,
        store,
        issue_identifier="GH-166",
        issue_state="Merging",
        branch_name="feature/GH-166-memory-layer",
        git_status="clean",
    )

    assert summary["task_events"] >= 2

    task_state = store.find("task_state", filters={"issue_identifier": "GH-166"})[0]
    assert task_state["pull_request_number"] == 188
    assert task_state["pull_request_url"].endswith("/pull/188")
    assert task_state["issue_url"].endswith("/issues/166")
    assert task_state["repository"] == "dao1oad/fqpack-next"

    cleanup_request_events = [
        item
        for item in store.find("task_events", filters={"issue_identifier": "GH-166"})
        if item["event_type"] == "cleanup_requested"
    ]
    assert len(cleanup_request_events) == 1
    assert "pr=188" in cleanup_request_events[0]["summary"]


def test_compile_context_pack_writes_markdown_and_persists_pack_record(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    service_root = tmp_path / "service"
    cold_root = repo_root / ".codex" / "memory"

    _write(
        cold_root / "workflow-rules.md", "# Workflow Rules\n\n- Read memory first.\n"
    )

    config = MemoryRuntimeConfig(
        repo_root=repo_root,
        service_root=service_root,
        cold_memory_root=cold_root,
        artifact_root=service_root / "artifacts" / "memory",
        mongo_host="127.0.0.1",
        mongo_port=27027,
        mongo_db="fq_memory",
    )
    store = InMemoryMemoryStore()

    refresh_memory(
        config,
        store,
        issue_identifier="GH-166",
        issue_state="In Progress",
        branch_name="codex/gh-166-symphony-global-stewardship-codex",
        git_status="clean",
    )

    output_path = compile_context_pack(
        config,
        store,
        issue_identifier="GH-166",
        role="codex",
    )

    assert (
        output_path
        == service_root
        / "artifacts"
        / "memory"
        / "context-packs"
        / "GH-166"
        / "codex.md"
    )
    assert output_path.exists()

    content = output_path.read_text(encoding="utf-8")
    assert "# FreshQuant Memory Context Pack" in content
    assert "Issue: `GH-166`" in content
    assert "Role: `codex`" in content
    assert "Workflow Rules" in content
    assert "Read memory first." in content

    context_packs = store.find("context_packs")
    assert len(context_packs) == 1
    assert context_packs[0]["issue_identifier"] == "GH-166"
    assert context_packs[0]["role"] == "codex"
    assert context_packs[0]["path"] == str(output_path)


def test_compile_context_pack_includes_recent_task_events(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    service_root = tmp_path / "service"
    cold_root = repo_root / ".codex" / "memory"

    _write(
        cold_root / "workflow-rules.md", "# Workflow Rules\n\n- Read memory first.\n"
    )
    _write(
        service_root / "artifacts" / "GH-166" / "deployment-comment.md",
        """当前 Issue 在合并、部署和健康检查完成后，可以进入最终 cleanup 与 `Done`。

## 健康检查

- `GET http://127.0.0.1:15000/api/runtime/components` 返回 `200`

## 最终部署结果

- 运行面检查通过
""",
    )
    _write(
        service_root / "artifacts" / "cleanup-results" / "GH-166.json",
        json.dumps(
            {
                "issueIdentifier": "GH-166",
                "success": False,
                "remoteBranchDeleted": False,
                "workspaceDeleted": False,
                "issueClosed": False,
                "doneTransitioned": False,
                "executedAt": "2026-03-14T11:00:00+08:00",
                "errors": ["Runtime ops check failed."],
            },
            ensure_ascii=False,
        ),
    )

    config = MemoryRuntimeConfig(
        repo_root=repo_root,
        service_root=service_root,
        cold_memory_root=cold_root,
        artifact_root=service_root / "artifacts" / "memory",
        mongo_host="127.0.0.1",
        mongo_port=27027,
        mongo_db="fq_memory",
    )
    store = InMemoryMemoryStore()

    refresh_memory(
        config,
        store,
        issue_identifier="GH-166",
        issue_state="Global Stewardship",
        branch_name="main",
        git_status="clean",
    )

    output_path = compile_context_pack(
        config,
        store,
        issue_identifier="GH-166",
        role="global-stewardship",
    )

    content = output_path.read_text(encoding="utf-8")
    assert "## Recent Task Events" in content
    assert "cleanup_result" in content
    assert "Runtime ops check failed." in content
    assert "Cleanup status: `failed`" in content


def test_compile_context_pack_includes_pr_metadata_from_cleanup_request(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    service_root = tmp_path / "service"
    cold_root = repo_root / ".codex" / "memory"

    _write(
        cold_root / "workflow-rules.md", "# Workflow Rules\n\n- Read memory first.\n"
    )
    _write(
        service_root / "artifacts" / "cleanup-requests" / "GH-166.json",
        json.dumps(
            {
                "issueIdentifier": "GH-166",
                "branchName": "feature/GH-166-memory-layer",
                "repository": "dao1oad/fqpack-next",
                "issueUrl": "https://github.com/dao1oad/fqpack-next/issues/166",
                "pullRequestNumber": 188,
                "pullRequestUrl": "https://github.com/dao1oad/fqpack-next/pull/188",
                "requestedAt": "2026-03-14T12:00:00+08:00",
            },
            ensure_ascii=False,
        ),
    )

    config = MemoryRuntimeConfig(
        repo_root=repo_root,
        service_root=service_root,
        cold_memory_root=cold_root,
        artifact_root=service_root / "artifacts" / "memory",
        mongo_host="127.0.0.1",
        mongo_port=27027,
        mongo_db="fq_memory",
    )
    store = InMemoryMemoryStore()

    refresh_memory(
        config,
        store,
        issue_identifier="GH-166",
        issue_state="Merging",
        branch_name="feature/GH-166-memory-layer",
        git_status="clean",
    )

    output_path = compile_context_pack(
        config,
        store,
        issue_identifier="GH-166",
        role="codex",
    )

    content = output_path.read_text(encoding="utf-8")
    assert "Pull request: `#188`" in content
    assert "Repository: `dao1oad/fqpack-next`" in content


def test_repo_declares_memory_runtime_defaults() -> None:
    config_text = Path("freshquant/freshquant.yaml").read_text(encoding="utf-8")
    env_text = Path("deployment/examples/envs.fqnext.example").read_text(
        encoding="utf-8"
    )

    assert "memory:" in config_text
    assert "db: fq_memory" in config_text
    assert "cold_root: .codex/memory" in config_text
    assert (
        "artifact_root: D:/fqpack/runtime/symphony-service/artifacts/memory"
        in config_text
    )

    assert "FRESHQUANT_MEMORY__MONGODB__DB=fq_memory" in env_text
    assert (
        "FRESHQUANT_MEMORY__ARTIFACT_ROOT=D:/fqpack/runtime/symphony-service/artifacts/memory"
        in env_text
    )


def test_memory_smoke_script_runs_from_repo_without_installed_package(
    tmp_path: Path,
) -> None:
    service_root = tmp_path / "service-root"
    result = subprocess.run(
        [
            sys.executable,
            "runtime/memory/scripts/smoke_test_freshquant_memory.py",
            "--repo-root",
            str(Path(".").resolve()),
            "--service-root",
            str(service_root),
        ],
        cwd=Path(".").resolve(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "context_pack_path" in payload
    assert payload["context_pack_path"].startswith(str(service_root))
