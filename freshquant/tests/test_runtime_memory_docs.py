from __future__ import annotations

from pathlib import Path


def test_current_docs_describe_memory_layer_contract() -> None:
    runtime_text = Path("docs/current/runtime.md").read_text(encoding="utf-8")
    architecture_text = Path("docs/current/architecture.md").read_text(encoding="utf-8")
    configuration_text = Path("docs/current/configuration.md").read_text(
        encoding="utf-8"
    )
    troubleshooting_text = Path("docs/current/troubleshooting.md").read_text(
        encoding="utf-8"
    )

    assert "FQ_MEMORY_CONTEXT_PATH" in runtime_text
    assert "FQ_MEMORY_CONTEXT_ROLE" in runtime_text
    assert "fq_memory" in runtime_text
    assert ".codex/memory" in runtime_text
    assert "cleanup-requests" in runtime_text

    assert "冷记忆" in architecture_text
    assert "热记忆" in architecture_text
    assert "context pack" in architecture_text
    assert "Issue-managed 任务的 GitHub Issue" in architecture_text
    assert "所有代码更新的 PR+CI" in architecture_text
    assert "Draft PR" not in architecture_text

    assert "FQ_MEMORY_CONTEXT_PATH" in configuration_text
    assert "FQ_MEMORY_CONTEXT_ROLE" in configuration_text

    assert "refresh_freshquant_memory.py" in troubleshooting_text
    assert "compile_freshquant_context_pack.py" in troubleshooting_text
    assert "FQ_MEMORY_CONTEXT_PATH" in troubleshooting_text
    assert "FQ_MEMORY_CONTEXT_ROLE" in troubleshooting_text
    assert "cleanup-requests" in troubleshooting_text


def test_global_governance_allows_direct_pr_without_mandatory_issue() -> None:
    agents_text = Path("AGENTS.md").read_text(encoding="utf-8")
    overview_text = Path("docs/current/overview.md").read_text(encoding="utf-8")

    assert "允许直接从 `feature branch` 开 `PR`" in agents_text
    assert "不再强制先建 GitHub Issue" in agents_text
    assert (
        "需要 `Symphony` / `Global Stewardship` 跟踪的任务，应先建 GitHub Issue"
        in agents_text
    )
    assert "正式任务优先从 GitHub Issue 启动" not in agents_text

    assert "轻量更新允许直接走 `feature branch -> PR`" in overview_text
    assert "Issue-managed" in overview_text


def test_troubleshooting_scopes_issue_state_machine_to_issue_managed_tasks() -> None:
    troubleshooting_text = Path("docs/current/troubleshooting.md").read_text(
        encoding="utf-8"
    )

    assert (
        "本节仅适用于走 `Symphony` / `Global Stewardship` 的 Issue-managed 任务"
        in troubleshooting_text
    )
    assert (
        "仓库级 direct `feature branch -> PR` 不进入这条状态机" in troubleshooting_text
    )
    assert "需要 Symphony 接管的新建 GitHub issue 时默认只打" in troubleshooting_text


def test_cold_memory_workflow_rules_match_current_governance() -> None:
    workflow_text = Path(".codex/memory/workflow-rules.md").read_text(encoding="utf-8")

    assert "GitHub Issue" in workflow_text
    assert "GitHub PR + CI + merge gate" in workflow_text
    assert "Issue body" in workflow_text
    assert "Global Stewardship" in workflow_text
    assert "follow-up issue" in workflow_text
    assert "formal truth" in workflow_text

    assert "Design Review" not in workflow_text
    assert "Draft PR" not in workflow_text
    assert "human approval" not in workflow_text


def test_cold_memory_deploy_surfaces_cover_current_release_matrix() -> None:
    deploy_text = Path(".codex/memory/deploy-surfaces.md").read_text(encoding="utf-8")

    for expected in (
        "freshquant/rear/**",
        "freshquant/order_management/**",
        "freshquant/position_management/**",
        "freshquant/tpsl/**",
        "freshquant/market_data/**",
        "freshquant/strategy/**",
        "freshquant/signal/**",
        "morningglory/fqwebui/**",
        "morningglory/fqdagster/**",
        "third_party/tradingagents-cn/**",
        "runtime/symphony/**",
    ):
        assert expected in deploy_text

    assert (
        "`freshquant/position_management/**` -> redeploy API and restart the `position_management` host surface."
        in deploy_text
    )
    assert (
        "`freshquant/tpsl/**` -> redeploy API and restart the `tpsl` host surface."
        in deploy_text
    )
