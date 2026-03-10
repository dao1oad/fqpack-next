# RFC 0028: Symphony First 全仓治理切换

- **状态**：Approved
- **负责人**：Codex
- **评审人**：TBD
- **创建日期**：2026-03-10
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

FreshQuant 当前仓库治理以根 [`AGENTS.md`](D:/fqpack/freshquant-2026.2.23/.worktrees/brainstorm-symphony-governance/AGENTS.md) 为中心，核心特征是：

- 本地开发强制 `git worktree + feature branch`
- 破坏性变更、外部依赖、新入口必须先写 RFC
- GitHub PR 与 reviewer 语义承担主要人工门禁

本机已经验证 OpenAI `Symphony` 参考实现可运行，并且已经完成以下认知闭环：

- `Symphony` 适合作为 `Linear issue -> workspace -> Codex session` 的任务编排器
- `Linear` 是最自然的真实任务源
- 一个真实开发需求应当对应一个 `Linear issue`
- 编码阶段可以默认采用 `subagent-driven-development + TDD`
- 唯一需要保留的人类门禁是设计批准

当前仓库治理与 Symphony 默认模式存在根本冲突：

- 工作区模型冲突：仓库要求 `git worktree`，Symphony 更偏向 `repo copy/workspace`
- 审批模型冲突：仓库当前存在多处人工门，Symphony 更适合以少数状态门驱动
- 任务入口冲突：当前更偏人工仓内工作流，而 Symphony 天然以 `Linear issue` 为执行单元

本 RFC 解决的问题是：将 FreshQuant 正式切换为 `Linear-first + Symphony-first + design-approval-first` 的全仓统一治理。

## 2. 目标（Goals）

- 将 `Linear issue` 确立为全仓唯一任务入口。
- 将 `Symphony` 确立为全仓默认任务编排器。
- 将唯一人工门收敛为设计批准，即 `Human Review -> In Progress`。
- 保留 `RFC -> feature branch -> PR -> merge` 这一交付链，但废止全仓强制 `git worktree` 与 reviewer-first 审批模式。
- 为正式接入提供 repo-versioned workflow 模板、Linear 状态机、评论模板与高风险边界。

## 3. 非目标（Non-Goals）

- 本 RFC 不要求第一阶段改成 webhook 驱动；继续使用当前 30 秒轮询即可。
- 本 RFC 不把同一 issue 内的 checklist/comment 条目升级为独立任务单元。
- 本 RFC 不允许自动修改 `.env` 或其他 secrets 文件。
- 本 RFC 不允许第一阶段自动执行部署、停服、删库、强杀等高风险运行操作。
- 本 RFC 不允许第一阶段自动执行实盘/券商/交易直连高风险动作。

## 4. 范围（Scope）

**In Scope**

- `Linear` 状态机：`Todo / Human Review / In Progress / Rework / Merging / Done`
- `Symphony-managed workspace/repo copy` 作为合法工作区
- 设计阶段审批包：RFC、implementation plan、task checklist、Linear 结构化评论
- 远端 `feature branch`、`Draft PR`、CI 与 merge 的正式策略
- `subagent-driven-development + TDD` 的默认实现期方法论
- `AGENTS.md`、`docs/agent/*`、`docs/migration/*` 与 repo-versioned `runtime/symphony/*` 模板改写
- 宿主机正式运行目录、正式 runner、启动脚本与 `NSSM` 服务安装脚本

**Out of Scope**

- 生产环境自动部署
- secrets 自动修改
- webhook 接入实现
- 对 `Symphony` 上游 Elixir 代码做产品级功能扩展

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- 规定 FreshQuant 的正式治理入口、状态机、审批门与交付链。
- 规定 Symphony 在仓内的合法工作区模型、分支/PR 策略与文档模板。
- 规定哪些目录默认可自动修改、哪些路径需要 RFC 显式放行、哪些动作默认禁止自动执行。

**不负责（Must Not）**

- 不负责替代 GitHub 作为代码托管平台。
- 不负责替代 CI，只负责与 CI 结合。
- 不负责自动授权高风险基础设施或实盘交易动作。

**依赖（Depends On）**

- `Linear`
- `Symphony`
- GitHub 分支与 PR
- 仓内 RFC / progress / breaking-changes 文档体系

**禁止依赖（Must Not Depend On）**

- 不能依赖“人工本地创建 worktree”作为正式工作流前提。
- 不能依赖 GitHub reviewer approve 作为仓内唯一批准真值。
- 不能依赖 issue 内 checklist 或 comment 文本解析作为正式任务单元。

## 6. 对外接口（Public API）

### 6.1 Linear 工作流状态

- `Todo`
  - Symphony 可调度
  - 只允许调研、设计、RFC、计划
- `Human Review`
  - 暂停态
  - 唯一人工审批门
- `In Progress`
  - 设计已批准
  - 允许编码与交付
- `Rework`
  - 自动返工态
- `Merging`
  - 自动收尾与合并态
- `Done`
  - 终态

### 6.2 批准真值

- 唯一批准真值：`Human Review -> In Progress`
- `Linear comment` 只承载意见，不承载批准真值

### 6.3 PR 语义

- 设计阶段不开 PR
- 进入 `In Progress` 后创建并持续更新同一个 `Draft PR`
- Merge 仍要求 CI 全绿和 review discussion 已解决

## 7. 数据与配置（Data / Config）

- 任务源：`Linear`
- 轮询模式：默认 30 秒
- repo-versioned workflow 模板目录：`runtime/symphony/`
- 正式工作流文件：`runtime/symphony/WORKFLOW.freshquant.md`
- 宿主机运行根目录：`D:\fqpack\runtime\symphony-service\`
- 正式 runner：`runtime/symphony/scripts/freshquant_runner.exs`
- 正式启动脚本：`runtime/symphony/scripts/start_freshquant_symphony.ps1`
- 正式安装脚本：`runtime/symphony/scripts/install_freshquant_symphony_service.ps1`
- 正式部署同步脚本：`runtime/symphony/scripts/sync_freshquant_symphony_service.ps1`
- 分阶段 prompt：
  - `runtime/symphony/prompts/todo.md`
  - `runtime/symphony/prompts/in_progress.md`
- 审批评论模板：
  - `runtime/symphony/templates/human_review_comment.md`
- secrets 只允许通过环境变量或外部安全注入，不入仓：
  - `LINEAR_API_KEY`
  - 其他 Codex / GitHub 凭据

## 8. 破坏性变更（Breaking Changes）

- 废止“全仓强制 `git worktree + feature branch`”作为唯一合法工作区模型。
- 废止“GitHub reviewer approve 是主要人工门”的治理语义。
- 正式切换到 `Linear issue -> Symphony workspace -> feature branch -> PR -> merge` 的开发路径。

**影响面**

- 所有开发者/agent 的日常工作流
- `AGENTS.md`
- `docs/agent/*`
- `docs/migration/*`
- 任何依赖旧 worktree-first 说明的脚本、文档和培训材料

**迁移步骤**

1. 新增并批准本 RFC。
2. 改写 `AGENTS.md` 为 Symphony-first 治理。
3. 更新 `docs/agent` 中的 Symphony 正式接入说明。
4. 新增 repo-versioned `runtime/symphony/*` workflow 模板。
5. 在 Linear 中创建并启用正式状态机。

**回滚方案**

- 回退 `AGENTS.md`、`docs/agent`、`docs/migration` 和 `runtime/symphony` 的治理改写。
- 恢复原有 worktree-first 说明。
- 停止使用 Linear 状态机作为唯一入口，回到旧的人主导开发流程。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

本 RFC 不是把旧仓 `D:\fqpack\freshquant` 的某个单一模块迁入目标仓，而是为目标仓建立正式的多 agent 编排治理。因此迁移映射主要体现为“旧仓无正式 Symphony 治理能力，目标仓新增该治理层”。

- `D:\fqpack\freshquant`：无正式 Symphony / Linear 工作流治理
  - 映射到：目标仓 `Linear-first + Symphony-first` 治理
- 当前目标仓 `AGENTS.md` 中的 worktree-first / reviewer-first 规则
  - 映射到：本 RFC 定义的新治理模型
- 现有 `docs/agent/Symphony本地安装与使用指南.md` 中“正式接入当前不做”
  - 映射到：正式接入治理文档与 repo-versioned workflow 模板

## 10. 测试与验收（Acceptance Criteria）

- [ ] 仓内存在正式 RFC，明确状态机、审批门、分支/PR 策略、自动化边界。
- [ ] `AGENTS.md` 已改写为 `Linear-first + Symphony-first + design-approval-first`。
- [ ] `docs/agent` 已补充正式接入治理说明，并更新原本“当前不做”的结论。
- [ ] `runtime/symphony/WORKFLOW.freshquant.md` 与阶段 prompt 模板已入仓。
- [ ] 宿主机正式 runner、启动脚本、同步脚本与 `NSSM` 安装脚本已入仓。
- [ ] Linear 状态机已能表达 `Todo -> Human Review -> In Progress -> Rework -> Merging -> Done`。
- [ ] 设计批准前不会进入编码。
- [ ] 设计批准后默认使用 `subagent-driven-development + TDD`。
- [ ] 高风险目录与操作边界在治理文档中被明确约束。

## 11. 风险与回滚（Risks / Rollback）

- 风险点：治理切换范围大，旧文档、旧培训口径、旧自动化假设会同时失效。
- 缓解：先以 RFC + 文档 + 模板方式落地，再逐步切换实际运行面。
- 回滚：若正式接入受阻，可回退到本 RFC 之前的 `AGENTS.md` 与文档状态，同时停用 `runtime/symphony` 正式模板。

## 12. 里程碑与拆分（Milestones）

- M1：RFC 0028 起草并通过
- M2：`AGENTS.md`、`docs/agent`、`docs/migration` 同步改写
- M3：repo-versioned `runtime/symphony` 正式模板入仓
- M4：Linear 状态机在真实项目中启用
