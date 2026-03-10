# Codex 全局指令（AGENTS.md）

## 0. 项目目标（迁移与重构）

本仓库（`D:\fqpack\freshquant-2026.2.23` / GitHub: `dao1oad/fqpack-next`）是 **目标架构**。
需要在“重构与去冗余”的前提下，逐步迁移并整合旧分支仓库 `D:\fqpack\freshquant` 的功能。

迁移过程中 **允许破坏性变更（Breaking Changes）**，但必须先写清需求与边界，经评审后才能编码。

当前仓库的正式治理已切换为 **`Linear-first + Symphony-first + design-approval-first`**：

- 正式开发需求的唯一入口是 `Linear issue`
- 默认执行编排器是 `Symphony`
- 唯一人工门是设计批准
- 默认合法工作区是 `Symphony-managed workspace/repo copy`
- 远端 `feature branch` 与 `PR` 仍是代码交付真相源

## 0.1 必读入口（给后续 agent）

- 文档索引：`docs/agent/index.md`
- 本次代码调研结果（目标 + 现状 + 关键入口/依赖/CI 门禁）：`docs/agent/项目目标与代码现状调研.md`
- 旧仓库重点迁移模块调研（模块 1-10：入口/数据流/存储/接口，含订单管理）：`docs/agent/旧仓库freshquant-重点迁移模块调研.md`

## 0.2 运行与部署（Docker 并行）

当宿主机 `D:\\fqpack\\freshquant` 已运行并占用端口（80/5000/5001/6379/27017/10003 等）时，本仓库可用 Docker **并行启动**（端口隔离），入口文档：

- `docs/agent/Docker并行部署指南.md`

默认并行端口（本机 localhost）：

- Web UI：`18080`
- API Server：`15000`
- TDXHQ：`15001`
- Dagster UI：`11003`
- Dagster daemon（自动调度）：默认启用（无端口）
- Redis：`6380`
- MongoDB：`27027`

合并后部署规则：

- 模块代码合并到 `main` 后，必须重新构建新代码并部署该模块（Docker 并行模式示例：`docker compose -f docker/compose.parallel.yaml up -d --build`）。

## 1. 语言与风格

- 默认使用简体中文回复（除非用户明确要求英文）。
- 代码、命令、文件路径、标识符保持原样（通常为英文）。
- 表达直接、简洁、可执行；避免空话。

## 2. 文档优先级

- “需求/边界/RFC” > “实现细节”。
- 所有新增模块/子系统：先写 RFC（需求+边界），评审通过后再写代码。
- 项目文档优先中文；需要时在括号中保留关键英文术语。

## 3. 强制流程（Linear issue -> Symphony -> PR）

所有正式开发需求必须先落到 `Linear issue`，并遵守“一需求一 issue”。

正式工作流状态机如下：

- `Todo`
  - `Symphony` 自动领取
  - 只允许调研、设计、RFC、implementation plan
  - **禁止编码**
- `Human Review`
  - 唯一人工门
  - 流程暂停，等待人类审阅设计
- `In Progress`
  - 只有当 issue 从 `Human Review` 进入 `In Progress`，才允许编码
- `Rework`
  - 处理 review/CI/验证失败返工
- `Merging`
  - 自动收尾、合并、部署与部署后健康检查
- `Done`
  - 仅在合并与部署都成功后进入的终态

审批真值只有一个：

- **`Human Review -> In Progress` 的状态迁移**

`Linear comment` 只承载意见，不承载批准真值。

以下任一情况 **必须** 先写 RFC 并通过评审：
- 新增顶级模块（例如新增 `freshquant/<module>/` 目录，或新增稳定公共 API 面）。
- 新增对外入口（CLI/API/worker/service/scheduler）。
- 需要跨多个目录的大重构/重命名/拆分合并。
- 引入新的外部依赖（服务、存储、消息系统、第三方 API）。
- 任何破坏性变更（接口、配置、数据结构、行为语义）。

评审通过的最低标准：
- 目标/非目标明确（不做什么要写清楚）。
- 范围与边界明确（职责/不负责什么/依赖什么/禁止依赖什么）。
- 对外接口与数据/配置明确（输入输出、错误语义、兼容/迁移策略）。
- 验收标准明确（如何验证“做对了”）。

进入 `Human Review` 前必须至少产出：

- 对应 RFC
- implementation plan
- implementation plan 内的 `task checklist`
- `docs/migration/progress.md` 更新
- 一条结构化 `Linear comment`

落地顺序（严格执行）：
1) 新建/领取 `Linear issue`
2) `Todo` 阶段写 RFC 与 implementation plan
3) 人工把 issue 从 `Human Review` 改到 `In Progress`
4) `Symphony` 自动编码、TDD、PR、CI、merge、deploy
5) 更新进度与破坏性变更记录（`docs/migration/`）

## 4. RFC（需求/边界）规范

- 目录：`docs/rfcs/`
- 模板：`docs/rfcs/0000-template.md`
- 命名：`docs/rfcs/NNNN-<topic>.md`（NNNN 为 4 位递增编号；topic 用短横线）
- 状态：Draft / Review / Approved / Rejected / Superseded

RFC 必含内容（至少）：
- 背景与问题
- 目标 / 非目标
- 范围（In/Out）
- 模块边界（负责/不负责）
- 依赖与集成点（Dependencies）
- Public API（对外接口、错误语义）
- 数据与配置（Data/Config）
- 破坏性变更（影响面、迁移步骤、回滚）
- 测试与验收（Acceptance Criteria）
- 迁移映射（从 `D:\fqpack\freshquant` 的哪些路径/能力迁到哪里）

## 5. 迁移进度记录（文件化，不依赖插件）

本仓库以文件方式记录迁移进度（等价于 “planning-with-files” 的效果）：
- 进度总表：`docs/migration/progress.md`
- 破坏性变更清单：`docs/migration/breaking-changes.md`

规则：
- 每个迁移单元必须关联一个 RFC（在进度表里写 RFC 编号/链接）。
- 任何破坏性变更落地时，必须在 `breaking-changes.md` 追加记录，并引用对应 RFC。
- 正式工作流下，这些文件默认由 `Symphony` 在对应 issue 分支上自动更新；人工介入时也必须在同一分支/同一 PR 中保持同步。

强制更新频率（必须遵守）：
- **RFC 状态变更即更新**：RFC 从 Draft/Review/Approved/Implementing/Done/Blocked 任意变更时，必须在**同一提交**更新 `docs/migration/progress.md`。
- **迁移代码合并即更新**：任何涉及迁移/重构/删改功能的合并到 `main`，必须在**同一提交**更新 `docs/migration/progress.md`（含“做了什么/下一步/风险”简述）。
- **Implementing 每日更新**：处于 Implementing 的 RFC，按 Asia/Shanghai 自然日 **每天至少更新一次**进度（哪怕只是“无进展 + 原因”）。
- **破坏性变更同提交登记**：任何破坏性变更（接口/配置/数据/行为语义）落地时，必须在**同一提交**更新 `docs/migration/breaking-changes.md` 并引用 RFC。
- **未更新视为未完成**：未按上述规则更新进度/变更记录的工作，视为未完成，不应合并。

## 6. Git/GitHub

- 默认使用 SSH 远端（本项目）：`ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git`
- 如必须走 HTTPS 且需要代理，可按命令级别注入（示例）：`git -c http.proxy=http://127.0.0.1:10809 -c https.proxy=http://127.0.0.1:10809 <cmd>`
- 不要提交密钥/Token；`.env` 等敏感文件保持在 `.gitignore` 中。
- Git commit message、PR 标题、PR 描述、merge 说明默认使用简体中文编写（除非用户明确要求英文）。

PR 合并策略（项目强制约束）：
- **禁止直推 `main`**：所有改动在 feature 分支完成后提交 PR。
- **禁止在任何本地 `main` 分支直接开发或提交**：`main` 只能用于同步远程 `origin/main`，不能承载需求开发、修复、实验性改动或临时提交。
- **默认使用 `Symphony-managed workspace/repo copy` 开展修改**：正式开发由 `Symphony` 根据 `Linear issue` 创建工作区、远端 `feature branch` 与后续 `Draft PR`。若需要人工介入，只能在该 issue 对应的 feature 分支/PR 上修改。
- **合并顺序固定**：仅允许“`Linear issue` -> `Symphony workspace` -> `feature branch` -> `Draft PR` -> 合并到远程 `main` -> 本地 `main` fast-forward 同步远程 `main`”这一条路径。
- **设计阶段不开 PR**：只有 issue 进入 `In Progress` 后才创建 `Draft PR`。
- **`Done` 必须包含部署成功**：`Merging` 阶段必须完成合并、按变更矩阵执行自动部署，并通过部署后健康检查；部署失败先在 `Merging` 自动重试，必要时回到 `Rework`。
- PR 必须满足：
  - CI 全绿（`CI / governance`、`CI / pre-commit`、`CI / pytest`）
  - 解决所有 review discussion 后再合并

### 6.1 自动化权限边界

- 默认可自动修改：业务代码、前端、测试、普通文档
- 需要 RFC 明确列入范围后才可自动修改：`docker/`、`.github/`、`morningglory/fqdagsterconfig/`、`script/`、`third_party/`、根目录构建/安装/部署脚本
- `Merging` 阶段允许自动执行：
  - Docker 并行环境 `docker compose -f docker/compose.parallel.yaml up -d --build`
  - `runtime/symphony/` 相关变更的宿主机同步、`fq-symphony-orchestrator` 重启与健康检查
- 第一阶段默认禁止自动执行：
  - `.env` / secrets 修改
  - 直接改线上或并行环境数据库
  - 生产环境自动部署、自动回滚、停服、删库、强杀
  - 实盘/券商/交易直连高风险操作

## 7. Skills（可选）

- 本环境支持在本机 Codex skills 目录下按需加载 `SKILL.md`，并遵循其中工作流。
- 若用户点名技能，或任务明显匹配技能描述，则优先使用该技能。
