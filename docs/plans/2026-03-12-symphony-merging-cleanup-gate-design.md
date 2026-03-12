# Symphony Merging Cleanup 硬门禁设计

## 背景

FreshQuant 当前已经把 `Merging` 定义为：

- 合并到远程 `main`
- 自动部署
- 部署后健康检查
- 部署留痕写回 `Linear`

但合并后的运行残留还没有被正式治理覆盖：

1. `Symphony-managed workspace/repo copy` 会一直留在宿主机 `workspaces/` 下。
2. 已合并 PR 的远端 `feature branch` 没有统一清理语义。
3. `artifacts/` 目录缺少受控保留期与清理规则。

这会导致两个问题：

- `Done` 只代表“代码与运行面已收口”，不代表“执行残留已收口”。
- 工作区、远端分支和历史 artifacts 会持续堆积，增加宿主机治理成本。

## 目标

- 把 cleanup 正式纳入 `Merging -> Done` 的硬门禁。
- 在不新增 Linear 状态的前提下，补齐：
  - 已完成 issue 的 `workspace/repo copy` 删除
  - 已合并 PR 的远端 `feature branch` 删除
  - `artifacts/` 旧条目按保留期清理
- 保持 cleanup 结果可审计、可重试、可幂等。

## 非目标

- 不新增 `Cleanup` 这个 Linear 状态。
- 不自动执行 `docker system prune`、`docker image prune` 等高风险环境清理。
- 不清空 `logs/`。
- 不删除最近失败 issue 的 workspace。
- 不删除 `main` 或任何受保护分支。

## 设计

### 1. 状态机语义

`Merging` 的正式语义扩展为：

- PR 合并
- 自动部署
- 健康检查
- cleanup

`Done` 的正式真值扩展为：

- PR 已合并到远程 `main`
- 所需部署动作全部成功
- 部署后健康检查全部通过
- cleanup 全部成功
- 最终部署/cleanup 留痕已写回 `Linear`

不新增 `Cleanup` 状态，仍由 `Merging` 统一承载。

### 2. Cleanup 范围

本次只纳入三类 cleanup：

1. 远端分支删除
   - 目标：本 issue 对应、且已经 merge 的远端 `feature branch`
   - 幂等语义：分支已不存在视为成功
   - 守卫：禁止删除 `main`、禁止删除空分支名

2. workspace 删除
   - 目标：`workspace.root/<ISSUE_IDENTIFIER>`
   - 守卫：
     - 目标路径必须位于 `workspace.root` 下
     - 目标目录名必须严格等于当前 issue identifier
     - 只删除目录，不处理任意上级路径

3. artifacts 清理
   - 目标：`artifacts/` 根下 top-level 的 issue-scoped 历史条目
   - 默认保留期：14 天
   - 守卫：
     - 排除 cleanup 系统目录
     - 排除仍处于 active states 的 issue 标识条目
     - 仅删除超过保留期的条目

### 3. 为什么不能在当前 Merging session 内直接删 workspace

当前 Codex session 就运行在 issue workspace 内。Windows 下，当前进程或其子进程仍持有 workspace 作为当前目录时，删除该目录不可靠。

因此不能要求当前 Merging session 直接执行：

- `Remove-Item ...\\workspaces\\<ISSUE_IDENTIFIER> -Recurse -Force`

这类删除必须在 Codex 子进程退出后，由宿主机外层 finalizer 执行。

### 4. 两段式 cleanup 方案

采用“两段式 cleanup”：

#### 4.1 Merging session 内

Merging agent 负责：

- merge
- deploy
- health check
- 生成最终 deployment comment 草稿
- 写入 cleanup request

cleanup request 至少包含：

- issue identifier
- remote branch name
- workspace path
- artifacts root
- artifacts retention days
- deployment comment body
- request created time

#### 4.2 宿主机 wrapper / finalizer

宿主机 wrapper 在 Codex 子进程退出后执行 finalizer，负责：

- 读取当前 issue 的 cleanup request
- 删除远端 `feature branch`
- 删除 `workspace.root/<ISSUE_IDENTIFIER>`
- 清理符合条件的旧 artifacts
- 将 cleanup 结果追加到 deployment comment
- 通过 Linear GraphQL：
  - 写入最终 deployment comment
  - 将 issue 状态推进到 `Done`

如果 finalizer 失败，则 issue 保持在 `Merging`。

### 5. Linear 审计语义

现有 deployment comment 扩展新增：

- `Cleanup Results`

最终 comment 由宿主机 finalizer 在 cleanup 成功后一次性落地，避免出现：

- 先写“ready for Done”
- 但 cleanup 实际失败

这样的审计假阳性。

### 6. 失败回路

cleanup 失败默认策略：

- 留在 `Merging`
- 自动重试有限次，默认 3 次

转回 `Rework` 的条件：

- 失败稳定复现
- 需要修改仓库脚本或 workflow 模板
- 需要调整宿主机权限、路径守卫或 API 调用逻辑

### 7. 文件改动范围

- 治理文档：
  - `AGENTS.md`
  - `docs/rfcs/0028-symphony-first-governance.md`
  - `docs/agent/Symphony正式接入治理说明.md`
  - `docs/agent/Symphony宿主机服务部署说明.md`
- 运行模板：
  - `runtime/symphony/WORKFLOW.freshquant.md`
  - `runtime/symphony/README.md`
  - `runtime/symphony/prompts/merging.md`
  - `runtime/symphony/templates/deployment_comment.md`
- 宿主机脚本：
  - 新增 Codex wrapper
  - 新增 cleanup request/finalizer 脚本
  - 更新同步脚本
- 迁移记录：
  - `docs/migration/progress.md`
  - `docs/migration/breaking-changes.md`

## 验收标准

- 治理文档明确写出 `Done = merge + deploy + health check + cleanup`。
- `runtime/symphony` 中存在 cleanup request/finalizer 方案与相应脚本。
- `WORKFLOW.freshquant.md` 不再直接调用裸 `codex`，而是通过 wrapper 承接 post-session finalizer。
- 远端分支删除、workspace 删除、artifacts 保留期清理都有明确守卫与幂等语义。
- cleanup 成功后由宿主机 finalizer 写入最终 deployment comment 并推进 `Done`。
- cleanup 失败时 issue 保持 `Merging`，不会出现“cleanup 失败但 Linear 已 Done”的假阳性。
