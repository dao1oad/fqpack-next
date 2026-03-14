# Global Stewardship 治理优化设计

## 背景

本次 `Global Stewardship` 自动化收口暴露了几类系统性问题：

- `Merging -> Global Stewardship` 交接信息不足，主 steward 仍需靠临时推理补全 deploy/verify/cleanup 决策。
- 主仓库可能 dirty 且落后于远端 `main`，但正式 `.env` 和 runtime log 路径又绑定主仓库，导致“构建源”和“运行环境”混在一起。
- localhost 健康检查受 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` 污染，出现代理生成的假 `503`。
- `check_freshquant_runtime_post_deploy.ps1` 默认按短容器名检查，但实际 Docker compose 容器名带 project 前缀，live verify 需要人工补 snapshot。
- `docker compose up -d --build ...` 超时后，主流程缺少“命令超时但发布已完成”的复核分支。
- 前端镜像 tag 可复用，单看 tag / image time 不能证明静态资源已更新，缺少 bundle 级别的发布探针。
- 当前流程没有为子代理定义正式边界，遇到 GitHub、Docker、宿主机、前端、health check 多面问题时，无法安全并行排障。

## 目标

把 FreshQuant 的 post-merge 治理链路收敛为一个可重复、可批量、可降级、可验证的正式流程：

`Merging -> StewardshipPendingTruth -> StewardshipReady -> StewardshipDeploying -> StewardshipVerifying -> StewardshipCleanup -> Done`

同时明确：

- 主 steward 是唯一裁决者。
- 子代理只负责扩展证据，不负责最终状态迁移。
- deploy、health check、runtime ops check、cleanup 的脚本入口和输出合同固定。
- 真值不一致时自动降级并写明 blocker / clear condition / evidence / target recovery state。

## 非目标

- 不新建独立数据库或调度服务。
- 不改变 GitHub Issue / PR / merge 作为正式真值的地位。
- 不允许 Global Stewardship 直接修代码或直接创建修复 PR。
- 不把子代理升级成新的真值源。

## 设计原则

### 1. 主 steward 裁决，子代理扩展证据

允许子代理并行做以下事情：

- 读取 GitHub truth
- 生成 deploy batch 候选
- 检查 Docker / service / process / Symphony state
- 执行无代理健康检查
- 核对前端静态资源是否真的更新
- 列出 cleanup 目标

禁止子代理直接做以下事情：

- 决定 issue 是否关闭
- 最终决定 follow-up issue 是否创建
- 决定 external blocker 是否成立
- 直接执行 close issue / delete branch / delete workspace
- 在未经过父 steward 二次确认的情况下直接 deploy

### 2. handoff packet 是候选输入，不是最终真值

`Merging` 必须输出标准 handoff packet，但 `Global Stewardship` 仍要在每轮动作前重新读取最新 `origin/main`，重新跑 deploy plan，并核对：

- PR 是否真的 merged
- merge commit 是否已在当前 `main`
- 当前 `main` 是否已经超出 handoff 时刻
- open follow-up issue 是否仍阻塞 `Done`

### 3. 构建源与运行环境解耦

正式 deploy 允许在“干净 worktree + 主仓库环境文件”的模式下执行：

- 构建源：干净 worktree，固定到最新 `origin/main`
- 环境文件：主仓库 `.env`
- runtime log host dir：主仓库 `logs/runtime`

这样可以避免 dirty 主仓库阻塞正式 deploy，同时不破坏现有运行面。

### 4. 健康检查必须走 proxyless localhost

所有对 `127.0.0.1` / `localhost` 的正式健康检查都必须显式禁用代理。健康检查脚本应统一承担：

- 清空 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`
- 对 localhost 请求强制 no-proxy
- 支持文本、状态码和 JSON 字段断言
- 输出结构化 JSON

### 5. runtime verify 必须兼容 compose service 名

deploy 后运维面检查脚本必须优先按 `com.docker.compose.service` label 解析 live container，而不是默认依赖裸容器名。

### 6. 命令超时不等于 deploy 失败

正式 deploy 分三层结果：

- `command_succeeded`
- `command_timed_out_but_release_state_unknown`
- `command_failed`

当命令超时时，必须进入“结果复核”分支，检查：

- 容器创建时间
- 镜像 ID / digest
- 关键 health check
- 运行日志 / nginx assets / API version markers

只有复核失败，才视为 deploy 失败。

### 7. 前端发布必须做 bundle 级探针

对于 `web` 面，正式验证不能只看：

- 容器启动时间
- 镜像 tag
- 首页 `200`

还必须能证明当前实际服务的 bundle 确实包含本次变更的关键 marker。

## 目标状态机

### Merging

职责：

- 核对 PR merge truth
- 执行 merge
- 输出 handoff packet
- 把 issue 转入 `Global Stewardship`

禁止：

- deploy
- health check
- runtime ops check
- cleanup

### StewardshipPendingTruth

职责：

- fetch 最新 `origin/main`
- 拉 issue / PR / merge / CI 真值
- 判断 issue 是否真的进入 post-merge 治理阶段

输出：

- `ready`
- `defer`
- `rework`
- `blocked`

### StewardshipReady

职责：

- 根据 handoff packet + 当前 `main` 重新跑 `freshquant_deploy_plan.py`
- 聚合同轮可批量发布的 issues
- 决定 deployment batch

### StewardshipDeploying

职责：

- capture baseline
- 执行 docker / host deploy
- 记录 command metadata

### StewardshipVerifying

职责：

- 运行 proxyless health checks
- 运行 runtime ops verify
- 运行前端 bundle probe（命中 `web` 时）

### StewardshipCleanup

职责：

- 删除远端 feature branch
- 删除 Symphony workspace / 临时 worktree
- 删除临时 artifacts

### Done

进入条件：

- 当前 `main` 已包含目标 merge commit
- deploy 成功
- health check 成功
- runtime ops verify 成功
- cleanup 成功
- 没有 open follow-up issue 阻塞

## Handoff Packet 合同

`merge_handoff_comment.md` 升级为结构化字段，至少包含：

- Source Issue
- Source PR
- Merge Commit
- Merged At
- PR Head SHA
- Base SHA
- Changed Paths
- Suggested Deployment Surfaces
- Suggested Docker Services
- Suggested Host Surfaces
- Docs Synced
- Cleanup Targets
- Verification Hints
- Contract Version

`Global Stewardship` 不得直接信任 `Suggested Deployment Surfaces`，必须重新基于最新 `main` 计算本轮实际 deploy 面。

## 子代理角色

### truth-agent

输入：

- issue number
- repo

输出：

- issue state
- PR merge state
- merge commit
- CI 状态
- remote branch 是否仍存在

### deploy-agent

输入：

- merge commit / changed paths / current main

输出：

- deploy batch 候选
- docker services
- host surfaces
- health checks

### runtime-agent

输出：

- Docker container state
- Windows service state
- critical process state
- Symphony state API 结果

### health-agent

输出：

- proxyless health check 结果
- 代理污染检测结果

### frontend-agent

输出：

- index.html 实际引用 bundle
- bundle marker 命中情况
- 静态资源时间戳

### cleanup-agent

输出：

- branch / workspace / artifact 清单
- 删除可行性判断

## 脚本改造

### `script/freshquant_deploy_plan.py`

新增能力：

- 支持 `--base-sha` / `--head-sha`
- 支持 `--issue-number` / `--merge-commit`
- 输出 `effective_release_scope`
- 输出 `health_check_mode=proxyless`
- 输出 `verification_markers`
- 输出 `cleanup_targets`

### `script/docker_parallel_runtime.py`

新增能力：

- 显式解析 primary worktree
- 支持“干净 worktree 构建 + 主仓库环境文件”
- 暴露 `primary-worktree` / `compose-env-file` / `runtime-log-dir` 的正式接口

### `script/docker_parallel_compose.ps1`

新增能力：

- 支持显式指定 primary worktree / compose env / runtime log dir
- 输出 metadata 文件
- 支持 timeout 后复核
- 记录 compose project / container / image 信息

### `runtime/symphony/scripts/check_freshquant_runtime_post_deploy.ps1`

改造为：

- 默认 live 解析 compose service container
- snapshot 仅作为回放与测试入口
- 输出 `resolved_container_name` / `compose_service` / `check_source`
- 不再把 compose 前缀容器名视为 missing

### 新增 `script/freshquant_health_check.ps1`

职责：

- proxyless localhost 健康检查
- 状态码 / 文本 / JSON 字段断言
- 输出 JSON 报告

### 新增 `script/freshquant_frontend_release_probe.py`

职责：

- 下载 index.html
- 提取实际 bundle 路径
- 读取 bundle 内容
- 验证 marker 命中
- 输出结构化 JSON

## Prompt / Template 改造

### `runtime/symphony/prompts/merging.md`

新增规则：

- merge 后必须写标准 handoff packet
- 不得把 merge 视为 `Done`
- 不得替 Global Stewardship 提前注册 cleanup 成功

### `runtime/symphony/prompts/global_stewardship.md`

新增规则：

- 每处理完一张票后必须重新 fetch `origin/main`
- 必须使用 proxyless health check
- 命令超时必须进入结果复核分支
- 子代理只能用于证据收集

### `runtime/symphony/templates/*`

统一升级为能承载：

- handoff contract version
- runtime ops summary
- blocker / clear condition / evidence / target recovery state
- frontend probe summary

## 文档同步

需要同步更新：

- `docs/current/deployment.md`
- `docs/current/runtime.md`
- `docs/current/troubleshooting.md`

文档必须明确：

- dirty primary repo 下的正式 deploy 口径
- proxyless health check 是正式口径
- runtime verify 的 compose service 解析方式
- frontend release probe 是 `web` 面正式验证的一部分

## 测试策略

需要新增或更新以下测试：

- prompt contract tests
- deploy plan tests
- docker runtime path resolution tests
- runtime post-deploy check tests
- health check script tests
- frontend release probe tests

## 风险与降级

### GitHub truth 不一致

- 不 deploy
- 写 progress comment
- 记录 exact sha / timestamp / missing condition

### localhost 健康检查异常

- 先重跑 proxyless
- proxyless 成功则记录“代理污染”而不是 blocker

### deploy 命令超时

- 进入结果复核
- 若复核成功，继续 verify
- 若复核失败，转 external blocker 或 follow-up

### runtime verify 失败

- 先区分脚本解析问题 vs 真实运行问题
- 脚本解析问题属于治理缺口，创建 follow-up issue
- 真实运行问题按 code-fix / external 分流

## 推荐实施顺序

1. prompt / template / handoff contract
2. deploy plan / runtime path resolution
3. proxyless health check 脚本
4. runtime post-deploy check compose service 兼容
5. frontend release probe
6. docs/current 同步
7. 回归测试与 prompt contract tests
