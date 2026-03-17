# Docker 部署全链路优化设计

## 背景

PR #206 已经完成第一轮 Docker 部署提速：

- 根 `.dockerignore` 收口，降低无效构建上下文体积
- `docker/Dockerfile.rear` / `docker/Dockerfile.web` 分层，提升本机缓存命中
- `script/docker_parallel_compose.ps1` + `script/docker_parallel_compose.py` 支持基于镜像 git SHA 的 smart-build 跳过重复重建

但当前部署链路仍有三个明显缺口：

1. `dagster` / `qa` / `tdxhq` 复用 `fqnext_rear` 镜像，却没有显式的“shared rear image refresh”语义，部署计划仍可能只启动服务而没有真正刷新镜像。
2. `TradingAgents` 还未接入与 `rear` / `web` 相同的 git SHA label 与 smart-build 语义，重复部署收益不一致。
3. 正式部署仍主要依赖本机构建；即使本机缓存优化后，跨机器或冷环境部署仍偏慢，且无法把构建与部署阶段彻底解耦。

## 目标

- 修正 shared rear image 的部署语义，避免 `dagster` / `qa` 命中时误用旧镜像。
- 把 `TradingAgents` 纳入与 `rear` / `web` 一致的 smart-build / git SHA 标记体系。
- 为 Dockerfile 引入 BuildKit cache mount，进一步减少重复依赖下载与解包。
- 新增 GitHub Actions 预构建镜像 workflow，将正式部署优先收口为 `pull + up -d --no-build`，本机构建只保留为保守回退。
- 修正 Dagster 配置同步策略，避免卷中旧配置静默保留。
- 同步测试与 `docs/current/**`，把部署入口事实更新为当前实现。

## 非目标

- 不修改部署面判定的大方向，不重写 `Global Stewardship` 工作流。
- 不减少 health check、runtime ops check 或 cleanup。
- 不把宿主机运行面迁入 Docker。
- 不把正式部署强制为“只能依赖远端预构建镜像”；registry 不可用时仍允许本机构建回退。

## 方案对比

### 方案 A：继续只做本机构建优化

只补 shared rear image 语义、TradingAgents smart-build、BuildKit cache、Dagster 配置同步。

优点：

- 改动面小。
- 不引入新的 GitHub Actions 或 registry 依赖。

缺点：

- 无法把构建与部署彻底解耦。
- 冷机器、不同宿主机、清空缓存后的部署耗时仍然较高。

### 方案 B：混合型，推荐

保留本机构建通道，但新增 GitHub Actions 预构建镜像发布，正式部署优先使用 registry 中匹配当前 commit 的镜像；若不存在或不可拉取，则自动回退到本机构建。

优点：

- 同时解决 shared rear image 正确性问题和长期部署速度问题。
- 回退路径明确，不会因为 registry 异常阻塞正式部署。
- 与当前 `docker_parallel_compose.ps1` 入口兼容，迁移成本可控。

缺点：

- 需要新增镜像发布 workflow 与脚本逻辑。
- 需要在文档里明确“远端优先、本地回退”的部署事实。

### 方案 C：纯远端预构建镜像

正式部署完全禁止本机构建，只允许拉远端镜像。

优点：

- 理论上部署最快，环境最一致。

缺点：

- 对 registry、GitHub Actions、镜像权限的依赖最强。
- 当前仓库还没有对应 workflow，切换成本偏高。

## 推荐方案

采用方案 B。

## 设计细节

### 1. 部署计划补充 shared image refresh 语义

`script/freshquant_deploy_plan.py` 在当前版本里会返回：

- `docker_services`
- `host_surfaces`
- `health_checks`

但它没有区分：

- “哪些服务需要启动”
- “哪些共享镜像需要先刷新”

这会导致 `dagster` / `qa` 命中时，只能得到 `fq_dagster_webserver`、`fq_dagster_daemon`、`fq_qawebserver` 之类服务列表，而不会显式指出共享 `fqnext_rear` 镜像也要刷新。

本次调整后，部署计划将新增：

- `docker_build_targets`
- `docker_up_services`
- `registry_images`

其中：

- `api`、`dagster`、`qa`、`tdxhq` 命中任一 surface 时，都要求 `docker_build_targets` 包含 `fq_apiserver`，因为它是当前 shared rear image 的 build owner。
- `docker_up_services` 仍保持具体容器粒度，确保启动动作只覆盖受影响服务。
- `registry_images` 用于生成远端预构建镜像拉取/命中判断。

### 2. smart-build 扩展为“远端优先，本地回退”

`script/docker_parallel_compose.py` 当前能力是：

- 解析 compose services -> image
- 读取本地 image label `io.freshquant.git_sha`
- 若本地镜像已命中当前 `HEAD`，则把 `--build` 改写为 `--no-build`

本次将扩展为：

- 继续保留本地镜像命中判断
- 新增 registry manifest 命中判断
- 为 `up -d ...` 提供三种路径：
  - `remote_cached`: 先 `docker pull` 命中镜像，再 `up -d --no-build`
  - `local_cached`: 直接 `up -d --no-build`
  - `build_required`: 保持 `--build`

安全约束：

- worktree 脏文件只要命中目标 build context / Dockerfile 输入，就禁止 skip build。
- registry 探测失败、镜像不存在、pull 失败时，不报错中断，而是退回本机构建。

### 3. TradingAgents 接入统一镜像标记

`ta_backend` / `ta_frontend` 当前没有 `FQ_IMAGE_GIT_SHA` build arg，也没有统一 label，导致 smart-build 只能保守对待。

本次调整后：

- `docker/compose.parallel.yaml` 为 `ta_backend` / `ta_frontend` 注入 `FQ_IMAGE_GIT_SHA`
- `third_party/tradingagents-cn/Dockerfile.backend`
- `third_party/tradingagents-cn/Dockerfile.frontend`

统一补：

- `ARG FQ_IMAGE_GIT_SHA=unknown`
- `LABEL org.opencontainers.image.revision=...`
- `LABEL io.freshquant.git_sha=...`

### 4. BuildKit cache mount

在当前 Dockerfile 分层基础上，继续加入 BuildKit cache mount：

- `docker/Dockerfile.rear`
  - pip / uv cache mount
- `docker/Dockerfile.web`
  - pnpm store cache mount
- `third_party/tradingagents-cn/Dockerfile.backend`
  - pip / uv cache mount
- `third_party/tradingagents-cn/Dockerfile.frontend`
  - yarn cache mount

目标不是改变镜像内容，而是减少同机重复构建时的下载与解包成本。

### 5. Dagster 配置同步改成显式覆盖

当前 Dagster command 在容器启动时执行：

- `cp -n /freshquant/morningglory/fqdagsterconfig/* /opt/dagster/home/`

`cp -n` 的语义是目标存在时不覆盖，这会让卷中旧配置在镜像更新后继续保留，形成“已经部署，但配置没更新”的错觉。

本次调整为显式覆盖同步：

- 保留 `/opt/dagster/home` volume
- 启动时使用 `cp -f` 覆盖 repo 中的当前配置

这样既不改变 Dagster home 的持久化结构，也能保证配置文件随部署刷新。

### 6. GitHub Actions 预构建镜像发布

新增 `.github/workflows/docker-images.yml`：

- 触发条件：
  - `push` 到 `main`
  - `workflow_dispatch`
- 构建并推送：
  - `ghcr.io/<owner>/fqnext-rear:<sha>`
  - `ghcr.io/<owner>/fqnext-webui:<sha>`
  - `ghcr.io/<owner>/fqnext-ta-backend:<sha>`
  - `ghcr.io/<owner>/fqnext-ta-frontend:<sha>`
- 同时写入 `main` 浮动 tag，供人工调试使用

部署脚本默认优先使用 `<sha>` tag，不依赖 `main` 浮动 tag 作为正式真值。

### 7. 文档同步

更新 `docs/current/deployment.md`：

- 正式 Docker 入口继续是 `script/docker_parallel_compose.ps1`
- 入口优先拉取 registry 中与当前 commit 匹配的镜像
- 不命中时自动回退到本机构建
- `api/dagster/qa/tdxhq` 命中时会统一刷新 shared rear image

必要时补 `docs/current/runtime.md`：

- 说明 `GHCR` 预构建镜像只是部署提速手段，不改变运行真值

## 错误处理

- registry 不可用：记录 warning，回退本机构建
- 本地镜像 label 缺失：不跳过重建
- worktree dirty 且命中目标构建输入：不跳过重建
- `docker pull` 失败：不直接失败，改走本机构建
- BuildKit 不可用：Dockerfile 保持兼容，允许回退到常规构建

## 验证策略

### 单元 / 契约测试

- `freshquant/tests/test_freshquant_deploy_plan.py`
  - shared rear image refresh 语义
- `freshquant/tests/test_docker_parallel_compose.py`
  - remote/local/build 三类决策
  - dirty worktree 路径感知
- `freshquant/tests/test_deploy_build_cache_policy.py`
  - TradingAgents label / build arg / cache mount 契约
- `freshquant/tests/test_check_current_docs.py`
  - 当前文档同步

### 构建验证

- `powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 build fq_apiserver`
- `powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 build fq_webui`
- `powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 build ta_backend`
- `powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 build ta_frontend`

### 运行验证

- `powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 up -d --no-build fq_apiserver fq_webui`
- API / Web / TradingAgents health check

### CI 验证

- `ci.yml` 现有 required checks 继续通过
- 新增 `docker-images.yml` workflow 语法与 buildx 配置可执行
