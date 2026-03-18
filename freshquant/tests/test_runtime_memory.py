from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from freshquant.runtime.memory import (
    InMemoryMemoryStore,
    MemoryRuntimeConfig,
    bootstrap_memory_context,
    compile_context_pack,
    derive_issue_identifier,
)
from freshquant.runtime.memory import refresh as refresh_module
from freshquant.runtime.memory import (
    refresh_memory,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _seed_origin_main_reference_repo(
    tmp_path: Path, *, cold_root_relative: str = ".codex/memory"
) -> Path:
    remote_path = tmp_path / "remote.git"
    init_remote = _run_git("init", "--bare", str(remote_path), cwd=tmp_path)
    assert init_remote.returncode == 0, init_remote.stderr

    seed_path = tmp_path / "seed"
    clone_remote = _run_git("clone", str(remote_path), str(seed_path), cwd=tmp_path)
    assert clone_remote.returncode == 0, clone_remote.stderr
    assert (
        _run_git("config", "user.email", "test@example.com", cwd=seed_path).returncode
        == 0
    )
    assert _run_git("config", "user.name", "Test User", cwd=seed_path).returncode == 0

    _write(
        seed_path / Path(cold_root_relative) / "workflow-rules.md",
        "# Workflow Rules\n\n- Read memory from origin/main.\n",
    )
    _write(
        seed_path / "docs" / "current" / "modules" / "runtime-observability.md",
        "# Runtime Observability\n\nMain branch module facts.\n",
    )

    assert _run_git("add", cold_root_relative, "docs", cwd=seed_path).returncode == 0
    commit_result = _run_git("commit", "-m", "seed memory reference", cwd=seed_path)
    assert commit_result.returncode == 0, commit_result.stderr

    push_result = _run_git("push", "origin", "HEAD:main", cwd=seed_path)
    assert push_result.returncode == 0, push_result.stderr

    repo_root = tmp_path / "repo"
    clone_worktree = _run_git("clone", str(remote_path), str(repo_root), cwd=tmp_path)
    assert clone_worktree.returncode == 0, clone_worktree.stderr
    checkout_result = _run_git("checkout", "-b", "feature/local-drift", cwd=repo_root)
    assert checkout_result.returncode == 0, checkout_result.stderr

    return repo_root


def _advance_origin_main_reference_repo(tmp_path: Path) -> str:
    seed_path = tmp_path / "seed"
    _write(
        seed_path / ".codex" / "memory" / "workflow-rules.md",
        "# Workflow Rules\n\n- Updated from the latest origin/main.\n",
    )
    _write(
        seed_path / "docs" / "current" / "modules" / "runtime-observability.md",
        "# Runtime Observability Updated\n\nLatest main branch module facts.\n",
    )

    assert _run_git("add", ".codex", "docs", cwd=seed_path).returncode == 0
    commit_result = _run_git(
        "commit",
        "-m",
        "advance memory reference",
        cwd=seed_path,
    )
    assert commit_result.returncode == 0, commit_result.stderr

    push_result = _run_git("push", "origin", "HEAD:main", cwd=seed_path)
    assert push_result.returncode == 0, push_result.stderr

    remote_head = _run_git("rev-parse", "HEAD", cwd=seed_path)
    assert remote_head.returncode == 0, remote_head.stderr
    return remote_head.stdout.strip()


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
        reference_ref="origin/main",
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


def test_refresh_memory_uses_origin_main_reference_snapshot_instead_of_working_tree(
    tmp_path: Path,
) -> None:
    repo_root = _seed_origin_main_reference_repo(tmp_path)
    service_root = tmp_path / "service"

    _write(
        repo_root / ".codex" / "memory" / "feature-only.md",
        "# Feature Only\n\n- Local branch drift.\n",
    )
    _write(
        repo_root / "docs" / "current" / "modules" / "subject-management.md",
        "# Subject Management\n\nFeature branch only.\n",
    )

    config = MemoryRuntimeConfig(
        repo_root=repo_root,
        service_root=service_root,
        cold_memory_root=repo_root / ".codex" / "memory",
        artifact_root=service_root / "artifacts" / "memory",
        reference_ref="origin/main",
        mongo_host="127.0.0.1",
        mongo_port=27027,
        mongo_db="fq_memory",
    )
    store = InMemoryMemoryStore()

    summary = refresh_memory(
        config,
        store,
        issue_identifier="LOCAL-memory-origin-main",
        issue_state="Local Session",
        branch_name="feature/local-drift",
        git_status="M docs/current/modules/subject-management.md",
    )

    assert summary["knowledge_items"] == 1
    assert summary["module_status"] == 1

    output_path = compile_context_pack(
        config,
        store,
        issue_identifier="LOCAL-memory-origin-main",
        role="codex",
    )

    content = output_path.read_text(encoding="utf-8")
    assert "Workflow Rules" in content
    assert "Feature Only" not in content
    assert "runtime-observability" in content
    assert "- `subject-management`:" not in content


def test_refresh_memory_uses_configured_cold_root_from_reference_snapshot(
    tmp_path: Path,
) -> None:
    repo_root = _seed_origin_main_reference_repo(
        tmp_path,
        cold_root_relative=".memory/cold",
    )
    service_root = tmp_path / "service"

    config = MemoryRuntimeConfig(
        repo_root=repo_root,
        service_root=service_root,
        cold_memory_root=repo_root / ".memory" / "cold",
        artifact_root=service_root / "artifacts" / "memory",
        reference_ref="origin/main",
        mongo_host="127.0.0.1",
        mongo_port=27027,
        mongo_db="fq_memory",
    )
    store = InMemoryMemoryStore()

    summary = refresh_memory(
        config,
        store,
        issue_identifier="LOCAL-memory-configured-cold-root",
        issue_state="Local Session",
        branch_name="feature/local-drift",
        git_status="clean",
    )

    assert summary["knowledge_items"] == 1

    output_path = compile_context_pack(
        config,
        store,
        issue_identifier="LOCAL-memory-configured-cold-root",
        role="codex",
    )

    content = output_path.read_text(encoding="utf-8")
    assert "Workflow Rules" in content
    knowledge_item = store.find("knowledge_items")[0]
    assert knowledge_item["source_path"] == "origin/main:.memory/cold/workflow-rules.md"


def test_compile_context_pack_ignores_stale_module_records_from_other_worktrees(
    tmp_path: Path,
) -> None:
    repo_root = _seed_origin_main_reference_repo(tmp_path)
    service_root = tmp_path / "service"

    config = MemoryRuntimeConfig(
        repo_root=repo_root,
        service_root=service_root,
        cold_memory_root=repo_root / ".codex" / "memory",
        artifact_root=service_root / "artifacts" / "memory",
        reference_ref="origin/main",
        mongo_host="127.0.0.1",
        mongo_port=27027,
        mongo_db="fq_memory",
    )
    store = InMemoryMemoryStore()
    store.upsert_many(
        "module_status",
        [
            {
                "module_id": "subject-management",
                "title": "标的管理",
                "source_path": "D:/fqpack/freshquant-2026.2.23/.worktrees/legacy/docs/current/modules/subject-management.md",
                "status": "documented",
                "generated_at": "2026-03-16T17:49:20+00:00",
            }
        ],
        key_fields=("module_id",),
    )

    refresh_memory(
        config,
        store,
        issue_identifier="LOCAL-memory-origin-main",
        issue_state="Local Session",
        branch_name="feature/local-drift",
        git_status="clean",
    )

    output_path = compile_context_pack(
        config,
        store,
        issue_identifier="LOCAL-memory-origin-main",
        role="codex",
    )

    content = output_path.read_text(encoding="utf-8")
    assert "runtime-observability" in content
    assert "- `subject-management`:" not in content


def test_refresh_memory_updates_origin_main_remote_tracking_ref_before_reading(
    tmp_path: Path,
) -> None:
    repo_root = _seed_origin_main_reference_repo(tmp_path)
    service_root = tmp_path / "service"
    latest_main_commit = _advance_origin_main_reference_repo(tmp_path)

    stale_origin_main = _run_git("rev-parse", "origin/main", cwd=repo_root)
    assert stale_origin_main.returncode == 0, stale_origin_main.stderr
    assert stale_origin_main.stdout.strip() != latest_main_commit

    config = MemoryRuntimeConfig(
        repo_root=repo_root,
        service_root=service_root,
        cold_memory_root=repo_root / ".codex" / "memory",
        artifact_root=service_root / "artifacts" / "memory",
        reference_ref="origin/main",
        mongo_host="127.0.0.1",
        mongo_port=27027,
        mongo_db="fq_memory",
    )
    store = InMemoryMemoryStore()

    refresh_memory(
        config,
        store,
        issue_identifier="LOCAL-memory-origin-main-latest",
        issue_state="Local Session",
        branch_name="feature/local-drift",
        git_status="clean",
    )

    refreshed_origin_main = _run_git("rev-parse", "origin/main", cwd=repo_root)
    assert refreshed_origin_main.returncode == 0, refreshed_origin_main.stderr
    assert refreshed_origin_main.stdout.strip() == latest_main_commit

    output_path = compile_context_pack(
        config,
        store,
        issue_identifier="LOCAL-memory-origin-main-latest",
        role="codex",
    )

    content = output_path.read_text(encoding="utf-8")
    assert "Updated from the latest origin/main." in content
    assert "Runtime Observability Updated" in content


def test_fetch_reference_ref_updates_remote_tracking_ref_explicitly(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run_git(repo_root: Path, *args: str):
        calls.append(args)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(refresh_module, "_run_git", fake_run_git)

    assert refresh_module._fetch_reference_ref(tmp_path, "origin/main") is True

    assert calls == [
        (
            "fetch",
            "origin",
            "+refs/heads/main:refs/remotes/origin/main",
        )
    ]


def test_fetch_reference_ref_returns_false_when_git_fetch_fails(
    tmp_path: Path, monkeypatch
) -> None:
    def fake_run_git(repo_root: Path, *args: str):
        class _Result:
            returncode = 1
            stdout = ""
            stderr = "fetch failed"

        return _Result()

    monkeypatch.setattr(refresh_module, "_run_git", fake_run_git)

    assert refresh_module._fetch_reference_ref(tmp_path, "origin/main") is False


def test_refresh_memory_falls_back_to_working_tree_when_reference_fetch_fails(
    tmp_path: Path,
) -> None:
    repo_root = _seed_origin_main_reference_repo(tmp_path)
    service_root = tmp_path / "service"
    checkout_seed_result = _run_git(
        "checkout",
        "origin/main",
        "--",
        ".codex",
        "docs",
        cwd=repo_root,
    )
    assert checkout_seed_result.returncode == 0, checkout_seed_result.stderr

    _write(
        repo_root / ".codex" / "memory" / "feature-only.md",
        "# Feature Only\n\n- Local fallback when fetch fails.\n",
    )
    _write(
        repo_root / "docs" / "current" / "modules" / "subject-management.md",
        "# Subject Management\n\nFeature branch fallback.\n",
    )
    set_remote_result = _run_git(
        "remote",
        "set-url",
        "origin",
        str(tmp_path / "missing-remote.git"),
        cwd=repo_root,
    )
    assert set_remote_result.returncode == 0, set_remote_result.stderr

    config = MemoryRuntimeConfig(
        repo_root=repo_root,
        service_root=service_root,
        cold_memory_root=repo_root / ".codex" / "memory",
        artifact_root=service_root / "artifacts" / "memory",
        reference_ref="origin/main",
        mongo_host="127.0.0.1",
        mongo_port=27027,
        mongo_db="fq_memory",
    )
    store = InMemoryMemoryStore()

    summary = refresh_memory(
        config,
        store,
        issue_identifier="LOCAL-memory-fetch-fallback",
        issue_state="Local Session",
        branch_name="feature/local-drift",
        git_status="M docs/current/modules/subject-management.md",
    )

    assert summary["knowledge_items"] == 2
    assert summary["module_status"] == 2

    output_path = compile_context_pack(
        config,
        store,
        issue_identifier="LOCAL-memory-fetch-fallback",
        role="codex",
    )

    content = output_path.read_text(encoding="utf-8")
    assert "Feature Only" in content
    assert "- `subject-management`:" in content


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
        reference_ref="origin/main",
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
        reference_ref="origin/main",
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
        reference_ref="origin/main",
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
        reference_ref="origin/main",
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


def test_compile_context_pack_orders_recent_task_events_by_actual_timestamp(
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
        reference_ref="origin/main",
        mongo_host="127.0.0.1",
        mongo_port=27027,
        mongo_db="fq_memory",
    )
    store = InMemoryMemoryStore()
    store.upsert_many(
        "task_state",
        [
            {
                "issue_identifier": "GH-166",
                "issue_state": "Rework",
                "branch_name": "feature/GH-166-memory-layer",
                "git_status": "clean",
            }
        ],
        key_fields=("issue_identifier",),
    )
    store.upsert_many(
        "task_events",
        [
            {
                "event_id": "older-local-offset",
                "issue_identifier": "GH-166",
                "event_type": "cleanup_result",
                "summary": "older local-offset event",
                "generated_at": "2026-03-14T11:00:00+08:00",
            },
            {
                "event_id": "newer-utc",
                "issue_identifier": "GH-166",
                "event_type": "deployment_summary",
                "summary": "newer utc event",
                "generated_at": "2026-03-14T04:30:00+00:00",
            },
        ],
        key_fields=("event_id",),
    )

    output_path = compile_context_pack(
        config,
        store,
        issue_identifier="GH-166",
        role="codex",
    )

    content = output_path.read_text(encoding="utf-8")
    assert content.index("newer utc event") < content.index("older local-offset event")


def test_compile_context_pack_uses_latest_deploy_run_for_runtime_snapshot(
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
        reference_ref="origin/main",
        mongo_host="127.0.0.1",
        mongo_port=27027,
        mongo_db="fq_memory",
    )
    store = InMemoryMemoryStore()
    store.upsert_many(
        "task_state",
        [
            {
                "issue_identifier": "GH-166",
                "issue_state": "Rework",
                "branch_name": "feature/GH-166-memory-layer",
                "git_status": "clean",
            }
        ],
        key_fields=("issue_identifier",),
    )
    store.upsert_many(
        "deploy_runs",
        [
            {
                "deploy_run_id": "deploy-old",
                "issue_identifier": "GH-166",
                "status": "failed",
                "summary": "old deploy summary",
                "generated_at": "2026-03-14T10:00:00+08:00",
            },
            {
                "deploy_run_id": "deploy-new",
                "issue_identifier": "GH-166",
                "status": "documented",
                "summary": "new deploy summary",
                "generated_at": "2026-03-14T11:30:00+08:00",
            },
        ],
        key_fields=("deploy_run_id",),
    )

    output_path = compile_context_pack(
        config,
        store,
        issue_identifier="GH-166",
        role="codex",
    )

    content = output_path.read_text(encoding="utf-8")
    assert "Deploy: `documented` - new deploy summary" in content


def test_refresh_memory_marks_failed_health_checks_from_deployment_comment(
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

## 健康检查

- `GET http://127.0.0.1:15000/api/runtime/health/summary` 返回 `500`
""",
    )

    config = MemoryRuntimeConfig(
        repo_root=repo_root,
        service_root=service_root,
        cold_memory_root=cold_root,
        artifact_root=service_root / "artifacts" / "memory",
        reference_ref="origin/main",
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

    health_result = store.find(
        "health_results", filters={"issue_identifier": "GH-166"}
    )[0]
    assert health_result["status"] == "fail"
    assert "500" in health_result["summary"]


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
        reference_ref="origin/main",
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
    assert "reference_ref: origin/main" in config_text
    assert (
        "artifact_root: D:/fqpack/runtime/symphony-service/artifacts/memory"
        in config_text
    )

    assert "FRESHQUANT_MEMORY__MONGODB__DB=fq_memory" in env_text
    assert "FRESHQUANT_MEMORY__REFERENCE_REF=origin/main" in env_text
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


def test_derive_issue_identifier_prefers_workspace_issue_directory() -> None:
    issue_identifier = derive_issue_identifier(
        workspace_path=Path("D:/fqpack/runtime/symphony-service/workspaces/GH-166"),
        branch_name="main",
    )

    assert issue_identifier == "GH-166"


def test_derive_issue_identifier_falls_back_to_issue_number_in_branch_name() -> None:
    issue_identifier = derive_issue_identifier(
        workspace_path=Path("D:/fqpack/freshquant-2026.2.23"),
        branch_name="codex/gh-166-symphony-global-stewardship-codex",
    )

    assert issue_identifier == "GH-166"


def test_derive_issue_identifier_falls_back_to_local_workspace_name() -> None:
    issue_identifier = derive_issue_identifier(
        workspace_path=Path("D:/fqpack/freshquant-2026.2.23"),
        branch_name="main",
    )

    assert issue_identifier == "LOCAL-freshquant-2026.2.23"


def test_bootstrap_memory_context_refreshes_and_compiles_pack(tmp_path: Path) -> None:
    repo_root = tmp_path / "freshquant-workspace"
    service_root = tmp_path / "service"
    cold_root = repo_root / ".codex" / "memory"
    module_doc = repo_root / "docs" / "current" / "modules" / "runtime-observability.md"

    _write(
        cold_root / "workflow-rules.md",
        "# 工作流规则\n\n- 直开会话先读 memory。\n",
    )
    _write(
        module_doc,
        "# 运行观测\n\n当前模块事实。\n",
    )

    config = MemoryRuntimeConfig(
        repo_root=repo_root,
        service_root=service_root,
        cold_memory_root=cold_root,
        artifact_root=service_root / "artifacts" / "memory",
        reference_ref="origin/main",
        mongo_host="127.0.0.1",
        mongo_port=27027,
        mongo_db="fq_memory",
    )
    store = InMemoryMemoryStore()

    result = bootstrap_memory_context(
        config,
        store,
        workspace_path=repo_root,
        branch_name="main",
        git_status="clean",
        issue_state="Local Session",
        role="codex",
    )

    assert result["issue_identifier"] == "LOCAL-freshquant-workspace"
    assert result["role"] == "codex"
    assert Path(result["context_pack_path"]).exists()
    assert result["refresh_summary"]["knowledge_items"] == 1

    content = Path(result["context_pack_path"]).read_text(encoding="utf-8")
    assert "工作流规则" in content
    assert "Local Session" in content


def test_bootstrap_memory_script_runs_from_repo_without_installed_package(
    tmp_path: Path,
) -> None:
    service_root = tmp_path / "service-root"
    result = subprocess.run(
        [
            sys.executable,
            "runtime/memory/scripts/bootstrap_freshquant_memory.py",
            "--repo-root",
            str(Path(".").resolve()),
            "--service-root",
            str(service_root),
            "--in-memory",
        ],
        cwd=Path(".").resolve(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["role"] == "codex"
    assert Path(payload["context_pack_path"]).exists()
    assert payload["context_pack_path"].startswith(str(service_root))
