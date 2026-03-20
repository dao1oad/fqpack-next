from __future__ import annotations

from pathlib import Path


def test_current_docs_describe_memory_layer_contract() -> None:
    runtime_text = Path("docs/current/runtime.md").read_text(encoding="utf-8")
    architecture_text = Path("docs/current/architecture.md").read_text(encoding="utf-8")
    interfaces_text = Path("docs/current/interfaces.md").read_text(encoding="utf-8")
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
    assert "origin/main" in runtime_text
    assert "最新远程 `main`" in runtime_text
    assert "fq-symphony-orchestrator" not in runtime_text
    assert "40123" not in runtime_text
    assert "runtime/symphony/" not in runtime_text

    assert "冷记忆" in architecture_text
    assert "热记忆" in architecture_text
    assert "context pack" in architecture_text
    assert "origin/main" in architecture_text
    assert "最新远程 `main`" in architecture_text
    assert "所有代码更新的 PR + CI" in architecture_text
    assert "Draft PR" not in architecture_text
    assert "Symphony" not in architecture_text

    assert "FQ_MEMORY_CONTEXT_PATH" in configuration_text
    assert "FQ_MEMORY_CONTEXT_ROLE" in configuration_text
    assert "bootstrap_freshquant_memory.py" in architecture_text
    assert "bootstrap_freshquant_memory.py" in runtime_text
    assert "bootstrap_freshquant_memory.py" in interfaces_text
    assert "codex_run/start_codex_cli.bat" in runtime_text
    assert "codex_run/start_codex_app_server.bat" in runtime_text
    assert "stdio://" in runtime_text
    assert "Ctrl+C" in runtime_text
    assert "codex_run/start_codex_cli.bat" in interfaces_text
    assert "关闭该窗口即停止服务" in interfaces_text

    assert "refresh_freshquant_memory.py" in troubleshooting_text
    assert "compile_freshquant_context_pack.py" in troubleshooting_text
    assert "bootstrap_freshquant_memory.py" in troubleshooting_text
    assert "codex_run/start_codex_cli.bat" in troubleshooting_text
    assert "没有客户端接入前可以保持静默" in troubleshooting_text
    assert "FQ_MEMORY_CONTEXT_PATH" in troubleshooting_text
    assert "FQ_MEMORY_CONTEXT_ROLE" in troubleshooting_text
    assert "最新远程 `main`" in troubleshooting_text
    assert "fq-symphony-orchestrator" not in troubleshooting_text


def test_global_governance_allows_direct_pr_without_mandatory_issue() -> None:
    agents_text = Path("AGENTS.md").read_text(encoding="utf-8")
    overview_text = Path("docs/current/overview.md").read_text(encoding="utf-8")

    assert "允许直接从 `feature branch` 开 `PR`" in agents_text
    assert "不再强制先建 GitHub Issue" in agents_text
    assert "高影响、破坏性变更应先建 GitHub Issue" in agents_text
    assert "本地会话完成之后要同步到远程 `main`" in agents_text
    assert "正式任务优先从 GitHub Issue 启动" not in agents_text
    assert "Symphony" not in agents_text
    assert "Global Stewardship" not in agents_text

    assert "轻量更新允许直接走 `feature branch -> PR`" in overview_text
    assert "本地会话完成后先合并到远程 `main`" in overview_text
    assert "运行真相源：最新远程 `origin/main` 的正式 deploy 结果" in overview_text
    assert "Symphony" not in overview_text
    assert "bootstrap_freshquant_memory.py" in agents_text
    assert "codex_run/start_codex_cli.bat" in agents_text
    assert "FQ_MEMORY_CONTEXT_PATH" in agents_text


def test_troubleshooting_scopes_issue_state_machine_to_issue_managed_tasks() -> None:
    troubleshooting_text = Path("docs/current/troubleshooting.md").read_text(
        encoding="utf-8"
    )

    assert "正式 deploy 只允许基于最新远程 `main`" in troubleshooting_text
    assert "本地未 merge 的 worktree 不能直接当正式 deploy 来源" in troubleshooting_text
    assert "Symphony" not in troubleshooting_text


def test_cold_memory_workflow_rules_match_current_governance() -> None:
    workflow_text = Path(".codex/memory/workflow-rules.md").read_text(encoding="utf-8")

    assert "工作流规则" in workflow_text
    assert "GitHub Issue" in workflow_text
    assert "GitHub PR + CI + merge gate" in workflow_text
    assert "最新远程 `main`" in workflow_text
    assert "local session -> feature branch -> PR -> merge remote main -> deploy" in workflow_text
    assert "正式真值" in workflow_text

    assert "Design Review" not in workflow_text
    assert "Draft PR" not in workflow_text
    assert "human approval" not in workflow_text
    assert "Symphony" not in workflow_text
    assert "Global Stewardship" not in workflow_text


def test_cold_memory_deploy_surfaces_cover_current_release_matrix() -> None:
    deploy_text = Path(".codex/memory/deploy-surfaces.md").read_text(encoding="utf-8")

    assert "部署影响面" in deploy_text

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
    ):
        assert expected in deploy_text

    assert "runtime/symphony/**" not in deploy_text

    assert (
        "`freshquant/position_management/**` -> 重部署 API，并重启 `position_management` 宿主机运行面。"
        in deploy_text
    )
    assert (
        "`freshquant/tpsl/**` -> 重部署 API，并重启 `tpsl` 宿主机运行面。"
        in deploy_text
    )
