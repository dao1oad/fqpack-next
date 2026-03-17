# 选择性 Docker 构建与正式环境自动部署设计

## 背景

当前仓库已经具备两段相对独立的自动化能力：

- PR 阶段的 GitHub CI：`governance`、`pre-commit`、`pytest`
- `main` merge 后的 Docker 镜像发布：`rear`、`webui`、`ta-backend`、`ta-frontend` 推送到 GHCR

但仍存在两个明显缺口：

1. `docker-images.yml` 每次 `main` push 都会对 4 个镜像全部执行 build/push，虽然能命中 layer cache，但并没有做到“只有改到的服务才真正 build”。
2. merge 到 `main` 后没有正式自动部署 workflow，仍依赖 `Global Stewardship` 手动调用部署脚本完成 Docker deploy、宿主机重启、health check、runtime ops check 和 cleanup。

## 目标

- 让 `main` merge 后的镜像发布收口为“改到的服务才真正 build，未改到的服务只 retag 当前 SHA”。
- 在单一正式 Windows self-hosted runner 上实现无审批、自动部署正式环境。
- 部署范围按“上一次成功部署 SHA -> 当前 `main` HEAD”的改动并集计算，而不是只按单个 PR。
- 自动完成 `deploy -> health check -> runtime ops check -> deploy state update`。
- 失败时不自动回滚，只阻断、保留现场并保持 `last_success_sha` 不推进。

## 非目标

- 不引入多环境流水线，不先做 staging 再 promote。
- 不做自动回滚。
- 不迁移当前宿主机运行面到 Docker。
- 不改变现有 `docker_parallel_compose.ps1`、`freshquant_deploy_plan.py`、`fqnext_host_runtime_ctl.ps1` 作为正式 deploy 原语的地位。

## 方案选择

### 方案 A：继续全量 build + 新增自动部署

优点：

- workflow 改动最小。
- 不需要解决“当前 commit SHA tag 必须存在但未改服务不想重建”的问题。

缺点：

- `main` 每次 merge 都会运行 4 个 build job，长期浪费 runner 时间和 GHCR 带宽。
- 与用户目标不一致。

### 方案 B：按变更面 build，未改服务 retag，新增自动部署

优点：

- 真正做到“只有改到的服务才 build”。
- 同时保留“当前 commit SHA 对应的镜像 tag 必须存在”，不破坏现有 `registry-first` 部署逻辑。
- 与现有 `docker_parallel_compose.py` 的 SHA 命中判断天然兼容。

缺点：

- 需要引入镜像发布计划脚本。
- workflow 需要支持动态 matrix 和 retag 步骤。

### 方案 C：按变更面 build，未改服务不发布当前 SHA tag

优点：

- 最省 GHCR 操作。

缺点：

- 会直接破坏当前 deploy 侧“按当前 commit SHA 判断 remote cache”的前提。
- 需要改 deploy 逻辑去找“最近可用 tag/digest”，复杂度高，风险大。

## 推荐方案

采用方案 B。

## 架构总览

### 1. 选择性镜像发布

新增一个仓库内脚本：

- `script/ci/resolve_docker_image_publish_plan.py`

输入：

- `base_sha`
- `head_sha`

输出：

- 4 个逻辑镜像的发布动作：`build` 或 `retag`

判定逻辑：

- `rear`
  - 命中 shared rear 输入时 `build`
  - 否则把 `ghcr.io/<owner>/fqnext-rear:main` 对应 digest 复制为 `:<head_sha>`，同时刷新 `:main`
- `webui`
  - 命中 `morningglory/fqwebui/**` 或 `docker/Dockerfile.web` 时 `build`
  - 否则 `retag`
- `ta-backend`
  - 命中 `third_party/tradingagents-cn/**` 或 `Dockerfile.backend` 时 `build`
  - 否则 `retag`
- `ta-frontend`
  - 命中 `third_party/tradingagents-cn/**` 或 `Dockerfile.frontend` 时 `build`
  - 否则 `retag`

约束：

- 每次 `main` push 后，这 4 个镜像都必须具备当前 `head_sha` tag
- 只有受影响服务才真正执行 build

### 2. 自动正式部署 workflow

新增 workflow：

- `.github/workflows/deploy-production.yml`

触发方式：

- `workflow_run` 监听 `Docker Images`
- 仅在 `main` 分支、上游 workflow 成功时执行

运行环境：

- `runs-on: [self-hosted, windows, production]`

该 workflow 不直接堆叠复杂 shell，而是调用一个仓库内正式 orchestrator：

- `script/ci/run_formal_deploy.py`

### 3. 正式 deploy orchestrator

`run_formal_deploy.py` 负责：

1. 读取正式部署状态文件
2. 解析 `last_success_sha`
3. 计算 `last_success_sha..current_main_sha` 的 changed paths
4. 调用 `script/freshquant_deploy_plan.py`
5. 执行 Docker deploy
6. 执行宿主机 deployment surfaces
7. 执行 health check
8. 执行 deploy 后 runtime ops check
9. 仅在全通过时推进 `last_success_sha`

状态文件建议使用宿主机稳定路径，而不是 repo 工作区：

- `D:\fqpack\runtime\symphony-service\artifacts\formal-deploy\production-state.json`

每次部署 artifacts：

- `D:\fqpack\runtime\symphony-service\artifacts\formal-deploy\runs\<timestamp>-<sha>\`

### 4. 首次 bootstrap 规则

如果状态文件不存在，或不存在 `last_success_sha`：

- 选择性镜像发布退化为 4 个镜像全量 `build`
- 自动部署退化为所有 Docker surface 与宿主机 surface 的一次全量 deploy
- 仅在 bootstrap 全通过后写入 `last_success_sha`

### 5. 失败语义

失败分类：

- 镜像发布失败：不触发正式 deploy
- 部署计划解析失败：不做任何部署动作，直接失败
- Docker/宿主机执行失败：中止后续动作，保留现场
- health check / runtime ops check 失败：失败退出，不推进 `last_success_sha`

不做自动回滚。

### 6. 幂等与并发保护

自动部署链路增加两层保护：

- workflow `concurrency`：`deploy-production`
- 本地 deploy lock file：避免 runner 重入或人工重复触发

### 7. 与当前部署体系的关系

这次改动不重写正式 deploy 原语，而是编排现有入口：

- Docker：`script/docker_parallel_compose.ps1`
- 宿主机：`script/fqnext_host_runtime_ctl.ps1`
- 健康检查：`script/freshquant_health_check.py`
- deploy 后运行面校验：`runtime/symphony/scripts/check_freshquant_runtime_post_deploy.ps1`

因此自动化只是把现有手动 `Global Stewardship` 收口链路程序化，而不是引入第二套部署体系。

## 验证策略

### 单元 / 契约测试

- 镜像发布计划：
  - rear/web/ta 的 `build` 判定
  - 未改服务的 `retag` 判定
  - bootstrap 全量 `build`
- 正式 deploy orchestrator：
  - `last_success_sha` 读取
  - `last_success..HEAD` changed path 聚合
  - 失败不推进 state
  - 成功才推进 state
- workflow 契约：
  - `docker-images.yml` 的动态 matrix / retag
  - `deploy-production.yml` 的触发条件、Windows runner、orchestrator 调用

### 本地验证

- 本地运行镜像发布计划脚本
- 用 stub state/artifact 目录执行 deploy orchestrator
- 验证生成的 deploy plan、state、artifacts 正确

### 正式验证

- merge 到 `main`
- GitHub 自动发布镜像
- GitHub 自动触发正式 deploy workflow
- deploy 完成后：
  - `health check` 通过
  - `runtime ops check` 通过
  - `production-state.json` 更新到新 SHA

## 风险与缓解

- 自托管 runner 断连：workflow 失败并保留现场，不推进 deploy state
- retag 源镜像不存在：镜像发布计划应回退到对应镜像 `build`
- bootstrap 首次全量 deploy 风险高：在文档中明确 bootstrap 行为，并保留完整 artifacts
- 宿主机链路波动导致偶发失败：依赖现有 health check + runtime ops check 阻断，不推进成功状态
