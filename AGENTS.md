# Codex 全局指令（AGENTS.md）

## 0. 项目目标

本仓库（`D:\fqpack\freshquant-2026.2.23` / GitHub: `dao1oad/fqpack-next`）是 FreshQuant 的目标架构仓库。当前阶段以“当前系统事实收敛、潜在 bug 修复、部署与排障可维护”为主。

允许破坏性变更，但破坏性变更必须在 GitHub Issue 中先写清影响面、验收标准与部署影响，再进入编码。

## 0.1 正式真值

- GitHub Issue：高影响、破坏性变更的正式任务入口与需求真值
- GitHub PR + CI + merge gate：所有代码更新的交付真值；允许直接从 `feature branch` 开 `PR`
- 最新远程 `main` + formal deploy + health check + runtime ops check：运行交付真值

`Linear` 不再作为正式任务入口、评审面或批准真值来源。

## 0.2 必读入口

- 文档索引：`docs/index.md`
- 当前总览：`docs/current/overview.md`
- 当前架构：`docs/current/architecture.md`
- 当前运行面：`docs/current/runtime.md`
- 当前部署：`docs/current/deployment.md`
- 当前排障：`docs/current/troubleshooting.md`

## 0.2.1 记忆自举

- 若当前会话已经有 `FQ_MEMORY_CONTEXT_PATH` 且文件存在，先读该 context pack，再继续仓库探索。
- 自由 `Codex CLI` / `codex app-server` 会话的正式硬入口是：
  - `codex_run/start_codex_cli.bat`
  - `codex_run/start_codex_app_server.bat`
- 这两个入口会先调用 `codex_run/start_freshquant_codex.ps1` 自动执行 memory bootstrap，再启动对应 `codex` 命令。
- 若是直接在 Codex app 中打开仓库的自由会话，且 `FQ_MEMORY_CONTEXT_PATH` 不存在或目标文件缺失：
  - 先运行 `py -3.12 runtime/memory/scripts/bootstrap_freshquant_memory.py --repo-root . --service-root D:/fqpack/runtime`
  - 读取返回 JSON 中的 `context_pack_path`
  - 先读该 context pack，再继续通用 repo 扫描
- 若 memory context 与 GitHub、`docs/current/**` 或真实 deploy 证据冲突，以正式真值为准。

## 0.3 部署硬规则

- 代码更新后，受影响模块必须重新部署。
- 未完成部署与健康检查，不算 `Done`。
- 本地会话完成之后要同步到远程 `main`。
- 正式 deploy 只能基于最新远程 `main` 已合并 SHA。

## 1. 语言与风格

- 默认使用简体中文回复（除非用户明确要求英文）。
- 代码、命令、文件路径、标识符保持原样。
- 表达直接、简洁、可执行。

## 2. 正式文档

正式文档只保留：

- `docs/index.md`
- `docs/current/**`

文档规则：

- 只记录当前设计、当前实现、当前运行方式、当前排障方式。
- 不记录 RFC、实施计划、迁移进度、破坏性变更清单、复盘过程。
- 当前系统事实变化时，必须在同一 PR 同步更新 `docs/current/**`。

## 3. 正式工作流（GitHub-first）

默认工作流固定为：

`local session -> feature branch -> PR -> merge remote main -> deploy`

- 轻量更新允许直接走 `feature branch -> PR`，不再强制先建 GitHub Issue。
- 高影响、破坏性变更应先建 GitHub Issue。
- GitHub Issue body 仍应写清背景、目标、范围、非目标、验收标准、部署影响。

## 4. 推荐 skill chain

- 普通 bugfix：
  - `using-superpowers`
  - `systematic-debugging`
  - `test-driven-development`
  - `verification-before-completion`

- 现有模块增强：
  - `using-superpowers`
  - `brainstorming`
  - `test-driven-development`
  - `verification-before-completion`

- 跨模块或高影响改动：
  - `using-superpowers`
  - `brainstorming`
  - `writing-plans`
  - `test-driven-development`
  - `verification-before-completion`

## 5. Git / PR 规则

- 禁止直推 `main`
- 禁止在任何本地 `main` 上开发或提交
- 正式开发必须走 `feature branch + PR`
- 允许直接从 `feature branch` 开 `PR`
- 不再强制先建 GitHub Issue
- 高影响、破坏性变更应先建 GitHub Issue
- PR 正文应写清背景、目标、范围、非目标、验收标准、部署影响
- PR 必须满足：
  - CI 全绿（`docs-current-guard`、`pre-commit`、`pytest`）
  - 所有 review discussion 已处理

## 6. 部署矩阵

- `freshquant/rear/**`：重部署 API server
- `freshquant/order_management/**`：重部署后端/API，必要时重启相关 worker
- `freshquant/position_management/**`：重部署后端并重启 `xt_account_sync.worker`
- `freshquant/tpsl/**`：重部署后端并重启 `tpsl.tick_listener`
- `freshquant/market_data/**`：重启 producer / consumer / reference-data worker
- `freshquant/data/**` 中影响 Gantt / Shouban30 的改动：重部署 API / Dagster
- `morningglory/fqwebui/**`：重新构建并部署 Web UI
- `morningglory/fqdagster/**`：重部署 Dagster
- `third_party/tradingagents-cn/**`：重部署 `ta_backend` / `ta_frontend`

## 7. Cleanup

Cleanup 是 `Done` 的组成部分。

必须清理：

- 已合并远端 `feature branch`
- 当前任务 workspace / repo copy
- 当前任务临时脚本、截图、scratch 文件、临时 artifacts
- 临时 compose override、临时镜像标签

明确不清理：

- `.venv`
- Mongo / Redis 正式数据
- 正式日志目录
- 在线正式服务
- `docs/current/**`

## 8. Done 定义

只有同时满足以下条件，任务才算 `Done`：

- PR 已合并
- CI 通过
- `docs/current/**` 已同步
- 受影响模块已重新部署
- 健康检查通过
- cleanup 完成

即：

`Done = merge + ci + docs sync + deploy + health check + cleanup`
