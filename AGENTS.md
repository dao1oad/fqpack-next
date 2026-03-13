# Codex 全局指令（AGENTS.md）

## 0. 项目目标

本仓库（`D:\fqpack\freshquant-2026.2.23` / GitHub: `dao1oad/fqpack-next`）是 FreshQuant 的目标架构仓库。当前阶段不再以迁移过程治理为主，而是以“当前系统事实收敛、潜在 bug 修复、部署与排障可维护”为主。

允许破坏性变更，但破坏性变更必须先通过唯一人工门 `Design Review`，再进入编码。

## 0.1 正式真值

- GitHub Issue：正式任务入口
- GitHub Draft PR：唯一 `Design Review` 评审面
- GitHub PR + CI：代码交付真值
- Deploy + Health Check + Cleanup：运行交付真值

`Linear` 不再作为正式任务入口、评审面或批准真值来源。

## 0.2 必读入口

- 文档索引：`docs/index.md`
- 当前总览：`docs/current/overview.md`
- 当前架构：`docs/current/architecture.md`
- 当前运行面：`docs/current/runtime.md`
- 当前部署：`docs/current/deployment.md`
- 当前排障：`docs/current/troubleshooting.md`

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

正式工作流固定为：

`Issue -> Draft PR -> Design Review(仅高风险) -> In Progress -> CI -> Deploy -> Health Check -> Cleanup -> Done`

低风险任务可跳过 `Design Review`：

`Issue -> In Progress -> CI -> Deploy -> Health Check -> Cleanup -> Done`

新建 GitHub Issue 默认只打：

- `symphony`
- `todo`

不要在创建时预贴 `design-review`。只有在首轮风险判定后确认命中高风险条件时，才补 `design-review` 并进入 `Design Review` / Draft PR 路径。

### 3.1 唯一人工门

唯一人工评审点是：

- `Design Review`

人工评审唯一地点：

- GitHub Draft PR

批准真值：

- PR review `Approve`
- 或 PR 评论中明确回复 `APPROVED`

除审批信号 `APPROVED` / `REVISE:` / `REJECTED:` 外，所有写入 GitHub 的正式说明默认使用简体中文，包括：

- Issue 描述
- Draft PR 标题与正文
- PR / Issue 评论
- 部署说明
- Done / cleanup 总结

### 3.2 哪些任务必须先做 Design Review

命中以下任一条件时，必须先进行 `Design Review`，批准前不得编码：

- public API / CLI 变化
- 配置语义变化
- 存储/schema/读写边界变化
- 部署/运行面变化
- 跨模块且改变用户可见行为

普通 bugfix、现有模块内的小范围修复和局部优化，不需要人工评审。

### 3.3 Design Review Packet 硬规则

`brainstorming` 进入评审时，必须一次性提交完整 `Design Review Packet`。

每个待评审点必须包含：

- 决策问题
- 推荐方案
- 推荐理由
- 备选方案
- 影响面
- 需要人工明确给出的结论

如果没有待评审点，也必须明确写出：

- `无待评审点，按推荐方案执行`

除非后续出现新的真实约束，否则不允许零碎多轮提审。

## 4. Symphony 与 superpowers

- 正式开发默认由 `Symphony` 编排。
- `Codex CLI` 会话可以触发 `Symphony` 管理流程，但 CLI 会话不是真值源。
- `Symphony` 负责：
  - 接管 GitHub Issue
  - 创建/绑定 branch、workspace、Draft PR
  - 选择 skill chain
  - 在 `Design Review` 处暂停与恢复
  - 执行 deploy、health check、cleanup

推荐 skill chain：

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

- 跨模块或高风险改动：
  - `using-superpowers`
  - `brainstorming`
  - `writing-plans`（必要时）
  - `test-driven-development`
  - `verification-before-completion`

## 5. Git / PR 规则

- 禁止直推 `main`
- 禁止在任何本地 `main` 上开发或提交
- 正式开发必须走 `feature branch + Draft PR`
- 正式任务优先从 GitHub Issue 启动
- 小型明确修复允许从 CLI 触发，但应绑定到对应 GitHub Issue / PR
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
