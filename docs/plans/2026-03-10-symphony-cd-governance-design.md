# Symphony CD 治理设计

- 日期：2026-03-10
- 状态：Approved
- 适用范围：`D:\fqpack\freshquant-2026.2.23`
- 关联 RFC：`docs/rfcs/0028-symphony-first-governance.md`

## 背景

RFC 0028 已把 FreshQuant 的正式治理切换为 `Linear-first + Symphony-first + design-approval-first`，但当前 `Merging` 与 `Done` 的定义仍然停留在“PR 合并与收尾”层面，没有把代码部署和部署后健康检查纳入正式完成条件。

这会导致两个治理缺口：

- `Done` 可能只代表代码已合并，不代表运行环境已经更新到新版本。
- `Merging` 无法表达部署失败、部署重试和“需要回到 `Rework` 修代码”的差异。

本设计把 `CD` 作为正式治理的一部分固化到 Symphony 工作流中。

## 目标

- 把自动部署固化到 `Merging` 阶段。
- 把 `Done` 的语义改为“合并完成且部署成功”。
- 同时覆盖：
  - Docker 并行运行面
  - Symphony 宿主机正式服务运行面
- 明确部署触发矩阵、成功判定、失败回路与自动重试规则。

## 非目标

- 不把生产环境自动部署纳入第一阶段。
- 不实现自动回滚。
- 不自动修改 secrets、数据库或执行高风险实盘操作。
- 不在本次设计中直接实现新的部署脚本逻辑，只先固化治理和模板语义。

## 推荐方案

### 方案 A：PR 合并后即视为 Done，部署作为附属动作

优点：

- 实现最简单。
- 不会阻塞 issue 关闭。

缺点：

- `Done` 无法代表真实交付完成。
- 合并后未部署或部署失败的状态不可见。

### 方案 B：PR 合并后自动部署，部署成功才进入 Done

优点：

- `Done` 语义完整。
- 能把 CD 纳入正式治理闭环。
- 更符合“变更后必须重新部署”的要求。

缺点：

- 需要补齐失败分类与重试规则。
- 需要同步更新 `AGENTS.md`、RFC、workflow 模板和文档。

### 方案 C：只生成部署待办，由人工执行

优点：

- 最保守。
- 风险最低。

缺点：

- 与 `Symphony-first` 自动编排目标不一致。
- 部署会再次退回人工，不形成闭环。

## 结论

采用 **方案 B**。

正式状态机调整为：

- `Merging`
  - PR 可合并检查
  - 合并到远程 `main`
  - 自动部署
  - 部署后健康检查
- `Done`
  - 仅在“合并成功 + 部署成功 + 健康检查通过”后进入

## 部署触发矩阵

### 1. Docker 并行部署

满足任一项就触发：

- `docker/` 目录变更
- 通过 `docker/compose.parallel.yaml` 运行的业务代码、前端、API、Dagster 或相关依赖变更
- 前端构建或镜像构建链相关文件变更

默认动作：

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build
```

### 2. Symphony 宿主机运行面部署

满足任一项就触发：

- `runtime/symphony/**` 变更
- 正式 runner、workflow、prompt、template、同步/启动/安装脚本变更
- 宿主机服务部署文档对应的正式运行目录结构或启动约定变更

默认动作：

```powershell
powershell -ExecutionPolicy Bypass -File runtime\symphony\scripts\sync_freshquant_symphony_service.ps1
Restart-Service fq-symphony-orchestrator
Invoke-WebRequest http://127.0.0.1:40123/api/v1/state
```

### 3. 同时触发

如果同一 issue 同时触及业务运行模块和 `runtime/symphony/`，则两套部署都执行。

### 4. 不触发自动部署

这些情况默认不触发：

- 纯文档
- 纯 RFC / plan / migration 记录
- 不影响运行面的测试调整

## 成功判定

进入 `Done` 必须同时满足：

1. PR 已合并到远程 `main`
2. 需要执行的部署动作全部成功
3. 部署后健康检查全部成功

最小健康检查：

- Docker：
  - `docker compose` 成功
  - 关键服务处于预期运行状态
- Symphony：
  - `fq-symphony-orchestrator` 为 `Running`
  - `http://127.0.0.1:40123/api/v1/state` 返回 `200`

## 失败回路

### 默认策略

- 部署失败先留在 `Merging`
- 自动重试有限次，建议 `3` 次，带退避

### 转入 Rework 的条件

满足任一项就转 `Rework`：

- 同一错误稳定复现
- 健康检查明确指向代码或配置问题
- 需要修改仓库内容才能恢复
- 需要补丁 PR 才能继续

## 明确禁止

第一阶段继续禁止：

- 自动回滚
- 自动修改 secrets
- 自动执行高风险生产部署、删库、停服或交易动作

## 需要同步的治理文本

- `AGENTS.md`
  - `Merging` 与 `Done` 语义
  - 自动部署触发与失败回路
  - 自动化权限边界
- `docs/rfcs/0028-symphony-first-governance.md`
  - Public API / Scope / Acceptance Criteria / Breaking Changes
- `docs/agent/Symphony正式接入治理说明.md`
  - 正式工作流状态机与自动部署规则
- `docs/agent/Symphony宿主机服务部署说明.md`
  - 合并后同步/重启的治理要求
- `runtime/symphony/WORKFLOW.freshquant.md`
  - `Merging` 的正式动作定义
- `runtime/symphony/README.md`
  - 模板约束与 CD 说明

## 验收标准

- 文档层明确写清 `Merging = merge + deploy + health check`
- `Done` 明确要求部署成功
- 自动部署矩阵覆盖 Docker 与 Symphony 宿主机运行面
- 明确“失败先重试，必要时转 `Rework`”
- 第一阶段禁止自动回滚
