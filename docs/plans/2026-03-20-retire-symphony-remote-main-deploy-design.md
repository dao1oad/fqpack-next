# 退役 Symphony 并收紧为远程 main 正式部署设计

## 背景

当前正式交付链路同时混有三类真值：

- 本地会话 / 本地 worktree
- `runtime/symphony/**` 与 `fq-symphony-orchestrator`
- deploy 后的 health check / runtime verify 结果

这会带来两个问题：

1. 正式 deploy 来源不够单一，容易把本地未 merge 状态和正式发布状态混淆。
2. `Symphony` 目录下同时承载治理脚本、服务脚本和通用 deploy verify 脚本，删除 `Symphony` 时容易把仍然需要的正式验收能力一起删掉。

后续项目不再使用 Symphony 治理，所有开发会话都直接从本地发起；但正式部署仍需要统一、可追溯、可验证的收口链路。

## 目标

- 退役 `Symphony` 作为治理方式、正式运行面和正式部署面。
- 把正式 deploy 真值收紧为“最新远程 `main` 已合并 SHA”。
- 保留 deploy 后 `health check + runtime verify` 能力，但迁移到中性路径和中性产物目录。
- 保证宿主机、Docker、formal deploy state 仍然可持续运行和排障。

## 非目标

- 不改变现有 Docker / 宿主机 deployment surface 的业务划分。
- 不重写 `fqnext-supervisord` 宿主机控制模型。
- 不把本次设计扩展为新的 CI/CD 平台改造。
- 不在本次设计里增加 preview environment。

## 最终口径

正式交付链路固定为：

1. 本地会话完成开发、测试、预检查。
2. 代码通过 PR merge 到远程 `main`。
3. deploy mirror 拉取最新 `origin/main`。
4. 以最新远程 `main` SHA 作为 formal deploy 输入。
5. 基于 `last_success_sha -> latest origin/main sha` 计算 deployment surfaces 并执行 deploy。
6. 执行 health check。
7. 执行 runtime verify。
8. 仅当 deploy 与 verify 成功时推进 formal deploy state。

这意味着：

- 本地 worktree 可以用于开发和预演，但不能直接作为正式 deploy 来源。
- `fq-symphony-orchestrator` 不再是正式运行真值的一部分。
- 正式发布结果以“远程 `main` SHA + formal deploy state + health/runtime verify 结果”为准。

## 方案对比

### 方案 A：严格 remote main-only formal deploy

- 本地只负责开发、测试、预检查。
- formal deploy 只能基于最新远程 `main`。
- 推荐。

优点：

- 真值单一，排障和回溯最清晰。
- 与 PR merge gate 一致，避免本地状态混入正式环境。
- 最容易替代 `Symphony` 的治理位置。

缺点：

- 需要明确区分“本地预演”和“正式部署”。

### 方案 B：保留本地 preview deploy，formal deploy 仍只认 remote main

- 比方案 A 多一层 preview deploy 语义。

优点：

- 调试灵活。

缺点：

- 文档与脚本需要维护双口径。
- 容易被误用成正式 deploy。

### 方案 C：本地和 remote main 都允许 formal deploy

- 不推荐。

缺点：

- 继续保留双真值问题。
- 与退役 `Symphony` 的目标相冲突。

## 推荐方案

采用方案 A。

对项目来说，最关键的变化不是“删掉 Symphony 文件夹”，而是把正式真值链统一成：

`local session -> merge remote main -> deploy from latest remote main -> verify -> cleanup`

## 设计细节

### 1. formal deploy state 与产物迁移

当前 formal deploy 产物位于：

- `D:\fqpack\runtime\symphony-service\artifacts\formal-deploy`

迁移后使用中性目录，例如：

- `D:\fqpack\runtime\formal-deploy`

至少保留以下产物语义：

- `production-state.json`
- `runs/<run-id>/result.json`
- `runs/<run-id>/runtime-verify.json`
- baseline / verify 中间产物

`production-state.json` 至少保留这些字段：

- `last_success_sha`
- `last_attempt_sha`
- `last_run_at`
- `last_run_url` 或等价链接字段

### 2. deploy verify 脚本迁移

当前通用 deploy verify 脚本实际位于：

- `runtime/symphony/scripts/check_freshquant_runtime_post_deploy.ps1`

虽然路径属于 `runtime/symphony/`，但职责已经是正式 deploy 的通用 baseline / verify。

迁移后建议放到：

- `script/check_freshquant_runtime_post_deploy.ps1`

迁移后要求：

- 保留 `CaptureBaseline` 与 `Verify` 两段式行为。
- 删除对 `symphony` deployment surface 的支持。
- 删除对 `fq-symphony-orchestrator` 服务的检查依赖。
- 保留 Docker 与 `fqnext-supervisord` 的检查语义。

### 3. formal deploy 输入收紧为远程 main

formal deploy 入口需要满足：

- 只能在 deploy mirror 中运行。
- 执行前必须 `fetch origin`。
- 必须解析最新远程 `origin/main` SHA。
- 只能使用 `last_success_sha -> latest origin/main sha` 的 git diff 结果生成部署计划。

若 `last_success_sha` 为空：

- 允许 bootstrap 全量 deploy。
- 但 bootstrap 的真值仍然是“最新远程 `main`”，不是本地会话状态。

若本地会话存在未 merge 改动：

- 允许本地预检查。
- 不允许正式 deploy。

### 4. 删除 Symphony deployment surface

需要从 deploy 计划与正式文档中删除：

- `symphony` deployment surface
- `runtime/symphony/** -> symphony` path rule
- `40123/api/v1/state` 健康检查
- `symphony_sync_restart` pre-deploy step
- `fq-symphony-orchestrator` 的 runtime verify 依赖

迁移后保留的 deployment surfaces：

- `api`
- `web`
- `dagster`
- `qa`
- `tradingagents`
- `market_data`
- `guardian`
- `position_management`
- `tpsl`
- `order_management`

### 5. 文档真值更新

需要同步改写：

- `docs/current/deployment.md`
- `docs/current/runtime.md`
- `docs/current/overview.md`
- `docs/current/troubleshooting.md`
- `docs/index.md`
- `AGENTS.md`

文档要明确：

- 正式 deploy 只认最新远程 `main`
- 本地会话不是正式 deploy 真值
- `Symphony` 已不再承担治理或正式运行职责
- deploy 后仍然必须执行 health check 与 runtime verify

### 6. 删除 Symphony 专属仓库内容

在通用能力迁移完成后，删除：

- `runtime/symphony/**` 中仍然只服务于 Symphony 的脚本、模板、prompts、README、WORKFLOW
- `.github/ISSUE_TEMPLATE/symphony_task.yml`
- `freshquant/tests/test_symphony_*` 中仅验证 Symphony 治理/服务契约的测试
- `.codex/memory` 中仍把 `runtime/symphony/**` 视为正式部署面的记忆内容

## 实施阶段

### 阶段 1：迁 formal deploy 产物根目录

- 先迁 `formal-deploy` state / runs 目录。
- 确保新的 `production-state.json` 可被正式入口读写。
- 确保旧目录删除前不会丢失发布历史。

### 阶段 2：迁通用 verify 脚本

- 迁 `check_freshquant_runtime_post_deploy.ps1` 到中性路径。
- 切换所有调用方到新路径。
- 先保证行为等价，再删除旧路径。

### 阶段 3：收紧 formal deploy 真值

- formal deploy 强制使用最新远程 `main` SHA。
- 改写 deploy plan 输入口径。
- 本地会话仅保留预检查语义。

### 阶段 4：删除 Symphony deploy surface

- 删除 `symphony` surface、`40123` 健康检查、service verify 依赖。
- 更新相关测试和文档。

### 阶段 5：删除 Symphony 代码与系统对象

- 删除 `runtime/symphony/**` 与相关测试/模板/文档。
- 删除 Windows service、scheduled task、旧运行目录。

## 验收标准

- 仓库不再把 `Symphony` 描述为正式治理方式或正式运行面。
- `docs/current/deployment.md` 明确声明 formal deploy only from latest remote `main`。
- deploy plan 不再生成 `symphony` surface。
- health check 不再访问 `http://127.0.0.1:40123/api/v1/state`。
- runtime verify 不再检查 `fq-symphony-orchestrator`。
- formal deploy state 从中性路径成功读写。
- 至少一次真实远程 `main` SHA 的 formal deploy 能完成：
  - deploy
  - health check
  - runtime verify
  - state update

## 系统清理顺序

只有在正式 deploy state、verify 脚本和调用方都完成迁移后，才允许删除系统对象。

删除顺序：

1. 停止并删除服务。
2. 删除计划任务。
3. 确认服务与任务均不存在。
4. 删除旧的 `D:\fqpack\runtime\symphony-service`。

参考命令：

```powershell
Stop-Service fq-symphony-orchestrator -ErrorAction SilentlyContinue
sc.exe delete fq-symphony-orchestrator
Unregister-ScheduledTask -TaskName 'fq-symphony-orchestrator-restart' -Confirm:$false -ErrorAction SilentlyContinue
Get-Service fq-symphony-orchestrator -ErrorAction SilentlyContinue
Get-ScheduledTask -TaskName 'fq-symphony-orchestrator-restart' -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force D:\fqpack\runtime\symphony-service
```

## 风险与缓解

- 风险：先删旧目录导致 formal deploy state 丢失。
  缓解：先迁 state/runs，再删目录。

- 风险：把通用 verify 脚本和 Symphony 一起删除，导致 deploy 后验收链断裂。
  缓解：先迁脚本并切换调用方，再删旧路径。

- 风险：本地 worktree 仍被误用为正式部署来源。
  缓解：在 formal deploy 入口和文档中明确限制 remote main-only。

- 风险：多个 PR 在上次成功发布后合并，导致 deployment surface 漏算。
  缓解：统一按 `last_success_sha -> latest origin/main sha` 的变更并集计算。

## 结论

本次设计的核心不是简单删除 `Symphony`，而是用“远程 `main` 已合并 SHA”替代它在正式治理链上的真值位置，同时保留 deploy、health check 与 runtime verify 作为正式发布验收手段。
