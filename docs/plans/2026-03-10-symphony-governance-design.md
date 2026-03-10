# Symphony First 全仓治理设计稿

**目标**：将 FreshQuant 从当前 `AGENTS.md` 主导的 `worktree-first + reviewer-first` 治理，切换为 `Linear-first + Symphony-first + design-approval-first` 的统一开发模式；`Symphony` 成为全仓默认编排器，`Linear issue` 成为唯一任务入口，唯一人工门收敛为“设计批准”。

## 1. 背景与问题

### 1.1 当前现状

- FreshQuant 当前治理要求：
  - 禁止在本地 `main` 直接开发
  - 强制 `git worktree + feature branch`
  - 破坏性变更、新入口、新依赖必须先写 RFC
  - PR 合并前默认强调 GitHub reviewer / CI 门禁
- 已完成的 Symphony 本机演示表明：
  - `Symphony` 适合作为任务编排器与观测层
  - `Linear issue -> worker -> workspace -> Codex session` 这条链路可以稳定运行
  - UI 与 JSON API 能够展示运行状态、计划任务和子任务结果
- 但本仓当前治理与上游 Symphony 默认模型仍存在根本冲突：
  - 工作区模型：当前是 `git worktree`，上游更偏 `repo copy/workspace`
  - 人工门位置：当前是多门禁，Symphony 更适合少数状态门
  - 任务入口：当前偏人工/仓内流程，Symphony 天然偏 `Linear issue`

### 1.2 本次设计结论

本方案不再把 Symphony 当“旁路试点”，而是把它提升为全仓默认开发编排器。治理需要随之改写，而不是继续要求 Symphony 去适配旧治理。

## 2. 设计原则

### 2.1 单一任务单元

- 一个真实开发需求对应一个 `Linear issue`
- Symphony 只把 `issue` 当执行单元
- 不把同一 issue 内的 checklist、评论条目或临时备注解释成独立任务

### 2.2 单一人工门

- 唯一强制人工门是设计批准
- 审批真值只有一个：`Human Review -> In Progress`
- `Linear comment` 只承载意见，不承载批准真值

### 2.3 远端分支是真相源

- 本地 `Symphony-managed workspace/repo copy` 只是执行场所
- 远端 `feature branch` 才是代码交付真相源
- PR 与 merge 继续保留，但 GitHub reviewer 不再是强制人工门

### 2.4 保留 RFC / PR / CI，废止 worktree-first

- 保留：
  - RFC 前置
  - 禁止直推 `main`
  - `feature branch -> PR -> merge`
  - `docs/migration/progress.md` 与 `docs/migration/breaking-changes.md`
- 废止：
  - 全仓强制 `git worktree + feature branch`
  - reviewer-first 的人工审批模型

## 3. 正式工作流状态机

### 3.1 Linear 工作流状态

- `Todo`
  - Symphony 自动领取
  - 只允许调研、设计、RFC、实施计划
  - 不允许编码
- `Human Review`
  - 设计审批暂停态
  - 唯一人工门
- `In Progress`
  - 人工批准后自动进入实现阶段
  - 允许编码、TDD、提交、PR、CI 跟踪
- `Rework`
  - 处理 review comment、CI 失败、自动验证失败
- `Merging`
  - 自动收尾、合并、状态同步
- `Done`
  - 终态

### 3.2 Symphony 运行时状态

下列状态不进入 Linear workflow，而是保留为 Symphony 运行时观测态：

- `Retrying`
- `Waiting approval`
- `Waiting input`
- `Blocked`
- `Network error`

这样可以避免把“业务流状态”和“编排器运行态”混在同一套 issue 状态机里。

### 3.3 轮询策略

- 第一阶段继续使用当前默认 `30s` Linear 轮询
- 不强制先上 webhook
- 后续若需要再增量引入 `webhook + 低频轮询兜底`

## 4. 任务生命周期

### 4.1 进入 `Todo`

当新 Linear issue 进入受 Symphony 管理的 project 且状态为 `Todo` 时：

1. Symphony 领取 issue
2. 创建该 issue 的 `workspace/repo copy`
3. 创建并绑定远端 `feature branch`
4. 在该分支上产出设计审批包

### 4.2 设计审批包

进入 `Human Review` 前必须产出并提交：

- `RFC`
- `implementation plan`
- 实施计划内必须包含 `task checklist`
- `docs/migration/progress.md` 状态更新
- 一条结构化 `Linear comment`

设计阶段不开 PR，避免引入第二审批面。

### 4.3 `Human Review -> In Progress`

- 人工在 Linear 中阅读设计包
- 如需修改，直接在 issue 评论提出意见，Symphony 回到设计修订
- 如批准，人工把 issue 从 `Human Review` 改为 `In Progress`
- 这次状态迁移是唯一批准真值

### 4.4 实现与交付

进入 `In Progress` 后：

- Symphony 自动创建 `Draft PR`
- 默认走 `subagent-driven-development`
- 每个实现任务必须遵守 TDD
- 自动完成：
  - 编码
  - 测试
  - commit / push
  - PR 更新
  - CI 观察
  - merge 准备

进入 `Rework` 后，沿用同一实现栈；进入 `Merging` 后，自动完成最终收尾并推进 `Done`。

## 5. 编码期方法论约束

### 5.1 默认 subagent 模式

`In Progress / Rework` 阶段默认使用 `subagent-driven-development`：

- 主 agent 读取已批准设计
- 主 agent 拆分任务清单
- implementer subagent 按任务执行
- spec reviewer subagent 与 code quality reviewer subagent 做收尾审视

仅在任务强耦合且无法安全拆分时，才允许降级为单 agent 实现。

### 5.2 TDD 必须保留

自动化不意味着跳过 TDD，而是把确认动作流程化。每个实现任务都必须留下：

- failing test
- `RED` 证据
- minimal implementation
- `GREEN` 证据
- 回归验证结果

没有 `RED -> GREEN` 证据，不允许从 `In Progress / Rework` 推进到 `Merging`。

## 6. 分支、Workspace 与 PR 策略

### 6.1 Workspace 模型

全仓治理切换后，默认合法工作区改为：

- `Symphony-managed workspace/repo copy`

不再要求每次开发都先由人工创建本地 `git worktree`。

### 6.2 分支策略

- issue 一旦被领取，就创建远端 `feature branch`
- 设计阶段与实现阶段都在同一个 issue 分支上连续提交
- 这样能形成稳定的审计链：
  - `Linear issue`
  - `RFC / implementation plan`
  - `session`
  - `feature branch`
  - `PR`
  - `merge commit`

### 6.3 PR 策略

- 设计阶段不开 PR
- 进入 `In Progress` 后自动创建 `Draft PR`
- 合并前仍保留：
  - CI 全绿
  - review discussion 已解决
- 不再把 GitHub reviewer approve 当作仓内强制人工门

## 7. 自动化权限边界

### 7.1 默认可自动修改

- `freshquant/`
- `morningglory/fqwebui/`
- `docs/`
- 常规测试文件

### 7.2 RFC 明确列入范围后才可自动修改

- `docker/`
- `.github/`
- `morningglory/fqdagsterconfig/`
- `script/`
- `third_party/`
- 根目录构建/安装/部署脚本

这些路径不是永远禁止，但必须在 RFC 中明确列入，并写清回滚方案。

### 7.3 第一阶段默认禁止自动执行

- `.env` 与其他 secrets 文件修改
- 直接改线上或并行环境的 MongoDB / Redis 数据
- 自动执行部署、停服、删库、强杀等基础设施高风险动作
- 实盘/券商/交易直连高风险运行操作

这些动作可以生成设计、脚本和 PR，但不进入自动执行范围。

## 8. 文档与治理改写范围

### 8.1 `AGENTS.md`

需要从“人工主导 + worktree-first”改写为：

- `Linear issue` 是唯一任务入口
- `Symphony` 是默认编排器
- 唯一人工门是设计批准
- `Symphony-managed workspace` 是合法工作区

### 8.2 RFC 与迁移记录

本次治理变更本身是破坏性变更，必须新增 RFC，并在落地时同步更新：

- `docs/migration/progress.md`
- `docs/migration/breaking-changes.md`

### 8.3 现有 Symphony 指南

`docs/agent/Symphony本地安装与使用指南.md` 中“正式接入当前不做”的结论需要改写为新的正式方案，并补充：

- Linear 状态机
- 设计批准门
- 分支/PR 策略
- 自动化权限边界

## 9. 非目标

本次设计明确不做：

- 第一阶段强制接入 webhook
- 一个 issue 下再拆 issue 内 checklist 作为官方任务单元
- 自动修改 `.env` 或 secrets
- 自动执行生产/并行环境部署
- 自动执行实盘高风险操作

## 10. 分阶段落地建议

### Phase 1：治理与文档切换

- 新增治理 RFC
- 改写 `AGENTS.md`
- 更新 `docs/agent` 与迁移记录

### Phase 2：正式 Workflow 与运行时接入

- 配置真实 `Linear` project
- 固化 `WORKFLOW.freshquant.md`
- 将状态机、评论模板、分支策略写入 Symphony prompt / hooks

### Phase 3：观测与运营补强

- 补充阻塞态、重试态、审计视图
- 如有必要，再引入 webhook 以缩短 issue 感知延迟

## 11. 验收标准

当以下条件全部满足时，可视为本次方案落地：

- FreshQuant 仓内治理文档已改写为 `Symphony-first`
- 存在正式 RFC，明确工作流、边界、回滚
- Linear 中新增并启用正式状态机
- Symphony 能基于真实 Linear issue 运行 `Todo -> Human Review -> In Progress -> Rework -> Merging -> Done`
- 设计批准前不会编码
- 设计批准后能够自动执行 `subagent + TDD + PR + merge`
- 高风险目录与操作仍受明确边界约束
