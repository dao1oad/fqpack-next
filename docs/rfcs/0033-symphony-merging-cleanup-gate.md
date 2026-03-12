# RFC 0033: Symphony Merging Cleanup 硬门禁

- **状态**：Done
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-12
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

RFC 0028 已把 FreshQuant 的正式治理切换为 `Linear-first + Symphony-first + design-approval-first`，并进一步把 `Merging -> Done` 的核心语义收口为：

- PR 合并
- 自动部署
- 健康检查
- Linear 部署留痕

但当前合并后的运行残留没有纳入正式治理：

- `D:\fqpack\runtime\symphony-service\workspaces\<ISSUE_IDENTIFIER>\` 会持续堆积
- 已合并 PR 的远端 `feature branch` 没有强制清理
- `D:\fqpack\runtime\symphony-service\artifacts\` 缺少正式保留期和清理规则

这意味着当前 `Done` 还不是完整的“交付已收口”真值。

## 2. 目标（Goals）

- 把 cleanup 纳入 `Merging -> Done` 的正式硬门禁。
- 固化三类 cleanup：
  - 删除已合并 PR 的远端 `feature branch`
  - 删除已完成 issue 的 `Symphony-managed workspace/repo copy`
  - 清理 `artifacts/` 下超过保留期的旧条目
- 保证 cleanup 具备幂等、守卫、审计留痕和失败回路。

## 3. 非目标（Non-Goals）

- 不新增 `Cleanup` 这个 Linear 状态。
- 不自动执行 `docker system prune`、`docker image prune` 或其他高风险环境清理。
- 不清理 `logs/`。
- 不删除最近失败 issue 的 workspace。
- 不自动回滚。

## 4. 范围（Scope）

**In Scope**
- `Done` 真值扩展为 `merge + deploy + health check + cleanup`
- `runtime/symphony` 的 wrapper / cleanup request / finalizer 脚本
- 远端分支删除、workspace 删除、旧 artifacts 保留期清理
- 部署评论扩展 `Cleanup Results`
- 文档、RFC、迁移记录与 breaking changes 同步更新

**Out of Scope**
- 生产环境自动清理
- `logs/` 轮转或压缩
- Docker 全局镜像/容器回收
- 扩展 Linear 状态机

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**
- 在宿主机正式运行面落地 cleanup 硬门禁。
- 确保 cleanup 失败时 issue 不会错误进入 `Done`。
- 确保 workspace 删除只作用于当前 issue 目录。
- 确保 artifacts 清理具备保留期与 active issue 排除能力。

**不负责（Must Not）**
- 不负责替代 GitHub 的分支保护策略。
- 不负责管理全局 Docker 垃圾回收。
- 不负责删除日志或其他与 issue 无关的宿主机目录。

**依赖（Depends On）**
- `runtime/symphony/WORKFLOW.freshquant.md`
- Windows 宿主机 PowerShell 脚本
- Git SSH 远端
- Linear GraphQL API

**禁止依赖（Must Not Depend On）**
- 不能依赖当前 Merging session 直接删除自身 workspace。
- 不能依赖 GitHub 后台自动删分支设置作为唯一清理机制。
- 不能依赖人工在 `Done` 后再补清理。

## 6. 对外接口（Public API）

新增/调整的正式接口语义：

1. `runtime/symphony/scripts/request_freshquant_symphony_cleanup.ps1`
   - 输入：
     - issue identifier
     - remote branch name
     - workspace path
     - deployment comment body
     - artifacts retention days
   - 输出：
     - `artifacts/cleanup-requests/<ISSUE>.json`
   - 错误语义：
     - 参数缺失、workspace 路径不安全、branch 名非法时直接失败

2. `runtime/symphony/scripts/invoke_freshquant_symphony_cleanup_finalizer.ps1`
   - 输入：
     - service root
     - workspace path
     - issue identifier
   - 输出：
     - 删除远端分支
     - 删除 workspace
     - 清理旧 artifacts
     - Linear deployment comment
     - `Done` 状态推进
     - `artifacts/cleanup-results/<ISSUE>.json`
   - 错误语义：
     - 任一 cleanup 失败时返回非零，并保持 issue 在 `Merging`

3. `runtime/symphony/scripts/run_freshquant_codex_session.ps1`
   - 作为正式 `codex.command` wrapper
   - 负责在 Codex child 退出后触发 finalizer

兼容性策略：

- 不改变 `Todo / Human Review / In Progress / Rework / Merging / Done` 这套状态机
- 不改变已有 Docker/Symphony deployment matrix
- 只扩展 `Done` 门禁和 `deployment comment` 内容

## 7. 数据与配置（Data / Config）

- Service root：`D:\fqpack\runtime\symphony-service`
- workspace root：`D:\fqpack\runtime\symphony-service\workspaces`
- artifacts root：`D:\fqpack\runtime\symphony-service\artifacts`
- cleanup request root：`artifacts\cleanup-requests`
- cleanup result root：`artifacts\cleanup-results`
- 默认 artifacts 保留期：`14` 天
- 运行依赖：
  - `LINEAR_API_KEY`
  - Git SSH 远端可用

## 8. 破坏性变更（Breaking Changes）

- `Done` 的正式语义从“merge + deploy + health check + deployment trace”进一步收紧为“merge + deploy + health check + cleanup + final deployment/cleanup trace”。
- 已合并 PR 的远端 `feature branch` 将默认被删除。
- 已完成 issue 的 Symphony workspace 将默认被删除。
- `artifacts/` 下超过保留期的旧 issue 条目将默认被清理。

**影响面**

- Symphony 宿主机运行面
- `runtime/symphony/*` workflow 模板与脚本
- Linear `Merging -> Done` 的判定
- 依赖保留远端 feature branch 或历史 workspace 的人工排障习惯

**迁移步骤**

1. 部署包含 RFC 0033 的 `runtime/symphony` 模板和宿主机脚本。
2. 确认宿主机具备 `LINEAR_API_KEY`、Git SSH 与 PowerShell 执行环境。
3. 让 Merging session 改为生成 cleanup request，而不是直接把 issue 标为 `Done`。
4. 由宿主机 wrapper/finalizer 执行 cleanup，并在成功后写回 Linear 与推进 `Done`。

**回滚方案**

- 回退 `runtime/symphony/WORKFLOW.freshquant.md`、wrapper/finalizer/request 脚本与相关文档。
- 恢复“cleanup 不作为 Done 硬门禁”的旧治理。
- 停止自动删除远端分支、workspace 和旧 artifacts。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

本 RFC 不对应旧仓某个业务模块迁移，而是目标仓 Symphony 正式治理的增量完善：

- 旧仓：无正式 Symphony cleanup gate
  - 映射到：目标仓 `Merging -> Done` cleanup 硬门禁
- 现状目标仓：`Done` 只覆盖 merge/deploy/health check
  - 映射到：`Done` 覆盖 merge/deploy/health check/cleanup

## 10. 测试与验收（Acceptance Criteria）

- [x] `AGENTS.md`、RFC 0028、治理说明与宿主机部署说明明确写出 cleanup 硬门禁。
- [x] `runtime/symphony/WORKFLOW.freshquant.md` 改为通过 wrapper 启动 Codex。
- [x] 仓库内存在 cleanup request 与 cleanup finalizer 脚本。
- [x] 远端分支删除具备幂等语义和保护 `main` 的守卫。
- [x] workspace 删除具备“必须位于 workspace root 下且目录名等于 issue identifier”的守卫。
- [x] `artifacts/` 清理默认按 14 天保留期执行，并排除 active issues。
- [x] cleanup 成功后会把最终 deployment/cleanup comment 写回 Linear，并将 issue 推进到 `Done`。
- [x] cleanup 失败时 issue 保持 `Merging`，不会产生 `Done` 假阳性。

## 11. 风险与回滚（Risks / Rollback）

- 风险点：Linear GraphQL 写评论/改状态失败，会阻塞 `Done`。
- 缓解：对 cleanup finalizer 加有限次重试，并把失败结果写入 `cleanup-results/<ISSUE>.json`。
- 风险点：workspace 路径守卫不足会带来误删风险。
- 缓解：严格校验 workspace root 与 issue identifier。
- 回滚：回退 wrapper/finalizer/request 脚本与文档，恢复旧 `Done` 语义。

## 12. 里程碑与拆分（Milestones）

- M1：RFC 0033 批准
- M2：治理文档与 workflow 模板更新
- M3：wrapper / request / finalizer 脚本入仓
- M4：cleanup hard gate 联机验证通过
