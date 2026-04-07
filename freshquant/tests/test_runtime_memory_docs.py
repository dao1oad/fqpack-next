from __future__ import annotations

from pathlib import Path


def test_current_docs_describe_memory_layer_contract() -> None:
    readme_text = Path("README.md").read_text(encoding="utf-8")
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
    assert "codex_run/start_codex_cli.bat" in interfaces_text

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
    assert (
        "local session -> feature branch -> PR -> merge remote main -> deploy"
        in workflow_text
    )
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


def test_additional_cold_memory_files_capture_current_project_facts() -> None:
    pitfalls_text = Path(".codex/memory/pitfalls.md").read_text(encoding="utf-8")
    topology_text = Path(".codex/memory/system-topology.md").read_text(encoding="utf-8")
    runtime_text = Path(".codex/memory/runtime-surfaces.md").read_text(encoding="utf-8")
    data_text = Path(".codex/memory/data-truth-sources.md").read_text(encoding="utf-8")
    guardrails_text = Path(".codex/memory/repo-guardrails.md").read_text(
        encoding="utf-8"
    )
    product_text = Path(".codex/memory/product-surfaces.md").read_text(encoding="utf-8")

    assert "系统拓扑" in topology_text
    assert "daily_screening" in topology_text
    assert "origin/main" in topology_text
    assert "记忆编译链" in topology_text

    assert "运行面与入口" in runtime_text
    assert "fq-symphony-orchestrator" not in runtime_text
    assert "fqnext-supervisord" in runtime_text
    assert "fq_local_preflight.ps1" in runtime_text
    assert "stdio://" in runtime_text
    assert "Symphony" not in runtime_text

    assert "数据真值与存储边界" in data_text
    assert "freshquant_order_management" in data_text
    assert "fqscreening" in data_text
    assert "fq_memory" in data_text
    assert "STOCK_ORDER_QUEUE" in data_text

    assert "仓库交付护栏" in guardrails_text
    assert "fq_local_preflight.ps1" in guardrails_text
    assert "script/fq_open_pr.ps1" in guardrails_text
    assert "main-deploy-production" in guardrails_text
    assert "review threads" in guardrails_text
    assert "Symphony" not in pitfalls_text

    assert "产品与模块面" in product_text
    assert "/daily-screening" in product_text
    assert "/runtime-observability" in product_text
    assert "subject-management" in product_text
    assert "trace_id" in product_text
    assert "5 个交易日" in product_text


def test_current_deployment_docs_reference_selective_deploy_and_build_cache() -> None:
    deployment_text = Path("docs/current/deployment.md").read_text(encoding="utf-8")

    assert "fq_apply_deploy_plan.ps1" in deployment_text
    assert "FQ_DOCKER_BUILD_CACHE_ROOT" in deployment_text
    assert "fq_local_preflight.ps1" in deployment_text
    assert "check_freshquant_runtime_post_deploy.ps1" in deployment_text


def test_configuration_docs_cover_current_bootstrap_and_monitor_defaults() -> None:
    configuration_text = Path("docs/current/configuration.md").read_text(
        encoding="utf-8"
    )
    params_text = Path("docs/current/reference/system-settings-params.md").read_text(
        encoding="utf-8"
    )

    assert "mongodb.screening_db" in configuration_text
    assert "memory.reference_ref" in configuration_text

    assert "缺省值：`60`" in params_text
    assert "缺省值：`500`" in params_text
    assert "缺省值：`240`" in params_text
    assert '"max_symbols": 60' in params_text
    assert '"queue_backlog_threshold": 500' in params_text
    assert '"max_bars": 240' in params_text
