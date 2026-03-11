---
name: symphony-formal-governance-guide
description: FreshQuant 将 Symphony 作为正式开发编排器接入时的治理规则、Linear 状态机、审批门、分支策略与自动化边界说明。
---

# Symphony 正式接入治理说明

- 更新日期：2026-03-10
- 适用仓库：`D:\fqpack\freshquant-2026.2.23`
- 对应 RFC：`docs/rfcs/0028-symphony-first-governance.md`

## 1. 结论

FreshQuant 已把 `Symphony` 从“本机演示工具”提升为**正式开发编排器**，治理基线改为：

- `Linear issue` 是唯一任务入口
- `Symphony` 是默认执行编排器
- 一个开发需求对应一个 `Linear issue`
- 唯一人工门是设计批准
- 默认执行模式是 `subagent-driven-development + TDD`

## 2. 正式工作流状态机

Linear 正式状态机如下：

- `Todo`
  - `Symphony` 可调度
  - 只允许调研、设计、RFC、implementation plan
  - 禁止编码
- `Human Review`
  - 唯一人工门
  - 设计审批暂停态
  - 负责关闭全部待决策项
- `In Progress`
  - 设计已批准
  - 允许编码、测试、PR、CI 跟踪
- `Rework`
  - 返工态
- `Merging`
  - 自动收尾、合并、部署与部署后健康检查
- `Done`
  - 仅在部署成功后进入的终态

运行时状态如 `Retrying / Waiting approval / Waiting input / Blocked / Network error` 仍属于 Symphony 运行态，不进入 Linear 工作流状态。

## 3. 批准与人工交互

唯一批准真值是：

- `Human Review -> In Progress`

`Linear comment` 只承载意见，不承载批准真值。

补充规则：

- `Human Review` 评论必须一次性列出全部待决策项
- 每个待决策项都必须带推荐方案和推荐理由
- 如果没有待决策项，也必须明确写出 `No open decision items`
- 只要仍有待决策项未明确结论，就不允许进入 `In Progress`

进入 `Human Review` 前，必须先产出：

- RFC
- implementation plan
- implementation plan 内的 `task checklist`
- `docs/migration/progress.md` 更新
- 一条结构化 `Linear comment`

进入 `Merging` 前，还必须在 `Linear` 留一条结构化 PR 结果评论，至少包含：

- 解决的问题
- 解决方案及理由
- 修改的文件
- 测试与验证结果
- 经验积累 / 后续注意事项
- PR 链接

进入 `Done` 前，还必须在 `Linear` 留一条结构化部署评论，至少包含：

- 部署范围
- 执行的部署动作
- 健康检查结果
- 重试 / 失败情况
- 最终部署结果

设计阶段不开 PR，避免形成第二审批面。

## 4. 分支与 PR 策略

- issue 被 Symphony 领取时，立即创建：
  - `Symphony-managed workspace/repo copy`
  - 对应远端 `feature branch`
- 设计与实现都在同一个 issue 分支上连续提交
- 只有进入 `In Progress` 后，才自动创建 `Draft PR`
- 合并前仍要求：
  - CI 全绿
  - review discussion 已解决

GitHub reviewer approve 不再是仓内强制人工门。

## 4.1 自动部署与 Done 语义

- `Merging` 不是单纯的 merge 收尾，而是：
  - PR 合并
  - 自动部署
  - 部署后健康检查
- `Done` 的真值是：
  - PR 已合并
  - 所需部署动作全部成功
  - 部署后健康检查全部通过
  - 部署留痕已写回 `Linear`

部署矩阵如下：

- Docker 并行运行面变更：
  - `docker compose -f docker/compose.parallel.yaml up -d --build`
- `runtime/symphony/**` 变更：
  - `sync_freshquant_symphony_service.ps1`
  - `Restart-Service fq-symphony-orchestrator`
  - `Invoke-WebRequest http://127.0.0.1:40123/api/v1/state`

部署失败默认留在 `Merging` 自动重试；若失败稳定复现且需要改代码或配置，才回到 `Rework`。

`Merging -> Done` 的额外硬门禁：

- 没有结构化部署评论，不允许 `Done`
- 这条评论必须足够让人类从 `Linear` 直接复盘部署动作与结果

## 5. 默认执行模式

`In Progress / Rework` 阶段默认使用：

- `subagent-driven-development`
- `test-driven-development`

每个实现任务都必须留下：

- failing test
- `RED` 证据
- minimal implementation
- `GREEN` 证据
- 回归验证结果

没有 `RED -> GREEN` 证据，不允许推进到 `Merging`。

## 6. 自动化权限边界

### 6.1 默认可自动修改

- `freshquant/`
- `morningglory/fqwebui/`
- `docs/`
- 常规测试文件

### 6.2 RFC 明确列入范围后才可自动修改

- `docker/`
- `.github/`
- `morningglory/fqdagsterconfig/`
- `script/`
- `third_party/`
- 根目录构建/安装/部署脚本

### 6.3 `Merging` 阶段允许自动执行

- Docker 并行环境的 `docker compose -f docker/compose.parallel.yaml up -d --build`
- Symphony 宿主机运行面的同步、服务重启与健康检查

### 6.4 第一阶段默认禁止自动执行

- `.env` 与其他 secrets 文件修改
- 直接改线上或并行环境 MongoDB / Redis 数据
- 生产环境自动部署、自动回滚、停服、删库、强杀等高风险运行操作
- 实盘/券商/交易直连高风险动作

## 7. 轮询与任务感知

第一阶段继续使用当前 `30s` Linear 轮询，不强制先接 webhook。

正式运行面当前采用单实例 orchestrator，并按 issue 状态限流：

- `Todo = 1`
- `In Progress = 2`
- `Rework = 1`
- `Merging = 1`

这意味着：

- 设计阶段保持串行，避免多个设计票同时读取大量仓库上下文
- 实现阶段最多允许两个 issue 同时运行
- 返工与部署阶段保持单槽，避免 review、部署和宿主机服务操作互相抢占

只要 issue 进入 active states：

- `Todo`
- `In Progress`
- `Rework`
- `Merging`

Symphony 就会在下一个轮询周期内感知并调度它。

## 8. 你需要记住的最小规则

- 新任务：新建一个新的 `Linear issue`
- 设计批准前：不编码
- 设计批准：靠 `Human Review -> In Progress`
- 正式开发：默认由 Symphony 自动执行
- 正式并发：最多同时处理 2 个 issue，且只有 `In Progress` 允许双并发
- 正式完成：必须是 merge + deploy + health check 全部成功
- 高风险路径：必须在 RFC 里明确列入范围

宿主机服务部署与 `NSSM` 安装方式见：

- `docs/agent/Symphony宿主机服务部署说明.md`
