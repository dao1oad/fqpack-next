# Codex 全局指令（AGENTS.md）

## 0. 项目目标

本仓库（`D:\fqpack\freshquant-2026.2.23` / GitHub: `dao1oad/fqpack-next`）是 FreshQuant 的目标架构仓库。当前阶段不再以迁移过程治理为主，而是以“当前系统事实收敛、潜在 bug 修复、部署与排障可维护”为主。

允许破坏性变更，但破坏性变更必须在 Issue 中先写清影响面、验收标准与部署影响，再进入编码。

## 0.1 正式真值

- GitHub Issue：高影响、破坏性变更、需要 `Symphony` / `Global Stewardship` 跟踪的正式任务入口，也是该类任务的需求与方案真值
- GitHub PR + CI + merge gate：所有代码更新的交付真值；允许直接从 `feature branch` 开 `PR`
- Deploy + Health Check + Cleanup：运行交付真值（由单个全局 Codex 自动化收口）

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
- 若是直接在 Codex app 中打开仓库的自由会话，且 `FQ_MEMORY_CONTEXT_PATH` 不存在或目标文件缺失：
  - 先运行 `py -3.12 runtime/memory/scripts/bootstrap_freshquant_memory.py --repo-root . --service-root D:/fqpack/runtime/symphony-service`
  - 读取返回 JSON 中的 `context_pack_path`
  - 先读该 context pack，再继续通用 repo 扫描
- 若 memory context 与 GitHub、`docs/current/**` 或真实 deploy 证据冲突，以正式真值为准。

## 0.3 部署硬规则

- 代码更新后，受影响模块必须重新部署。
- 未完成部署与健康检查，不算 `Done`。
- Docker 并行部署入口：
  - `docker compose -f docker/compose.parallel.yaml up -d --build`

默认并行端口：

- Web UI：`18080`
- API Server：`15000`
- TDXHQ：`15001`
- Dagster UI：`11003`
- Redis：`6380`
- MongoDB：`27027`

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

Issue-managed 正式工作流固定为：

`Issue -> In Progress -> Rework -> Merging -> Global Stewardship -> Done`

例外状态只保留：

`Blocked`

轻量更新允许直接走 `feature branch -> PR`，不再强制先建 GitHub Issue。

走 Symphony 的新建 GitHub Issue 默认只打：

- `symphony`
- `in-progress`

### 3.1 Issue 即执行合同（仅适用于 Issue-managed 任务）

- 对走 `Symphony` / `Global Stewardship` 的 Issue-managed 任务，GitHub Issue body 即执行合同。
- 该类任务在进入 `In Progress` 前，方案应已在 Issue 中明确。
- Symphony 不再承担人工方案审批或 `Design Review` 管理。

Issue body 至少应包含：

- 背景
- 目标
- 范围
- 非目标
- 验收标准
- 部署影响

所有写入 GitHub 的正式说明默认使用简体中文，包括：

- Issue 描述
- PR 标题与正文
- PR / Issue 评论
- 部署说明
- Done / cleanup 总结

### 3.2 状态职责

- `In Progress`
  - 实现、测试、同步 `docs/current/**`
- `Rework`
  - 仅处理未 merge 前的确定性修复
- `Merging`
  - 只负责读取 GitHub merge 真值、merge、handoff 到 `Global Stewardship`
- `Global Stewardship`
  - 只负责 deploy、health check、cleanup、follow-up issue
- `Blocked`
  - 只用于真实外部阻塞

### 3.3 Rework 硬规则

进入 `Rework` 时必须记录：

- `blocker_class`
- `evidence`
- `next_action`
- `exit_condition`

允许进入 `Rework` 的原因仅包括：

- `checks_failed`
- `review_threads_unresolved`
- `merge_conflict`
- `ruleset_policy_block`
- `docs_guard_failed`

不允许把以下情况记为 `Rework`：

- 等待人工审批
- 等待检查完成
- merge 后部署问题
- 外部权限或平台故障

## 4. Symphony 与 superpowers

- Issue-managed 正式开发默认由 `Symphony` 编排。
- `Codex CLI` 会话可以触发 `Symphony` 管理流程，但 CLI 会话不是真值源。
- `Symphony` 负责：
  - 接管 GitHub Issue
  - 创建/绑定 branch、workspace、PR
  - 选择 skill chain
  - 执行单任务开发闭环直到 PR merge 到 remote `main`

- 单个全局 Codex 自动化负责：
  - 接管 `Global Stewardship`
  - 统一处理 deploy、health check、cleanup
  - 发现需要代码修复的问题时只创建 follow-up issue，由下一轮 `Symphony` 接手

推荐 skill chain：

- 普通 bugfix：
  - `using-superpowers`
  - `systematic-debugging`
  - `test-driven-development`
  - `verification-before-completion`

- 现有模块增强：
  - `using-superpowers`
  - `brainstorming`（仅用于本地梳理，不形成审批环节）
  - `test-driven-development`
  - `verification-before-completion`

- 跨模块或高影响改动：
  - `using-superpowers`
  - `brainstorming`（仅用于本地梳理，不形成审批环节）
  - `writing-plans`（必要时）
  - `test-driven-development`
  - `verification-before-completion`

## 5. Git / PR 规则

- 禁止直推 `main`
- 禁止在任何本地 `main` 上开发或提交
- 正式开发必须走 `feature branch + PR`
- 正式开发允许直接从 `feature branch` 开 `PR`，不再强制先建 GitHub Issue。
- 需要 `Symphony` / `Global Stewardship` 跟踪的任务，应先建 GitHub Issue。
- 未建 Issue 的 direct PR，PR 正文应写清背景、目标、范围、非目标、验收标准、部署影响。
- 小型明确修复允许从 CLI 触发并直接开 PR；如已有 Issue / PR，则继续绑定对应治理面。
- PR 必须满足：
  - CI 全绿（`docs-current-guard`、`pre-commit`、`pytest`）
  - 所有 review discussion 已处理

## 6. 部署矩阵

- `freshquant/rear/**`：重部署 API server
- `freshquant/order_management/**`：重部署后端/API，必要时重启相关 worker
- `freshquant/position_management/**`：重部署后端并重启 `position_management.worker`
- `freshquant/tpsl/**`：重部署后端并重启 `tpsl.tick_listener`
- `freshquant/market_data/**`：重启 producer / consumer / reference-data worker
- `freshquant/data/**` 中影响 Gantt / Shouban30 的改动：重部署 API / Dagster
- `morningglory/fqwebui/**`：重新构建并部署 Web UI
- `morningglory/fqdagster/**`：重部署 Dagster
- `third_party/tradingagents-cn/**`：重部署 `ta_backend` / `ta_frontend`
- `runtime/symphony/**`：同步宿主机并重启 `fq-symphony-orchestrator`

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
