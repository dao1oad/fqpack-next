# 本机 Mirror 正式部署设计

## 背景

当前正式自动部署依赖生产机在线下载源码归档，并在正式 runner 上动态准备部署工作区。实际运行中，`github.com`、`codeload.github.com`、GHCR 下载链路都出现过明显的不稳定和长时间阻塞，导致正式 deploy 频繁卡在前置准备阶段，而不是卡在真正的部署逻辑。

用户要求把正式 CD 改成单机本地构建模式：生产机以 `D:\fqpack\freshquant-2026.2.23` 作为唯一 `deploy mirror`，该目录的 `main` 分支负责同步远程 `main`，正式 deploy 直接在这个目录中构建和部署，不再下载线上源码归档或线上预构建产物。

## 目标

- 正式 deploy 不再下载 GitHub zipball。
- 正式 deploy 不再依赖 GHCR 镜像命中。
- 正式 deploy 在 `D:\fqpack\freshquant-2026.2.23` 的 `main` 分支上完成同步、依赖准备、本地构建与部署。
- 保留当前 `run_formal_deploy.py -> deploy plan -> docker/host deploy -> health/runtime ops` 的收口链路。

## 非目标

- 不引入多机构建或外部 build agent。
- 不重写 `freshquant_deploy_plan.py` 的部署面语义。
- 不改变 `production-state.json` 的状态语义。
- 不在本轮处理 Node 20 action deprecation。

## 约束

- 生产机只有一台，没有额外构建机。
- 正式 deploy mirror 固定为 `D:\fqpack\freshquant-2026.2.23`。
- 正式 deploy 仍需要通过 GitHub 检查 `main` tip 真值，并把本机 mirror 快进到触发 SHA。
- deploy mirror 是正式目录，不允许自动 destructive cleanup；发现脏工作树或非 fast-forward 场景时应直接失败。

## 方案对比

### 方案 A：继续下载 zipball，只增强重试

- 优点：改动最小。
- 缺点：仍然把正式 deploy 建立在外网下载成功之上，不满足“不要把产物放在线上下载”的目标。

### 方案 B：保留 GHCR registry-first，只把源码切到本机

- 优点：能减少部分源码下载。
- 缺点：Docker 仍依赖线上镜像拉取；一旦 GHCR 不稳定，仍会卡在 deploy 前置。

### 方案 C：本机 mirror + 本机构建部署

- 优点：正式 deploy 只依赖本机目录和 `git fetch origin main`；不再下载 zipball/GHCR 大产物，符合目标。
- 缺点：production 机本地构建时间会回升，且对本机 mirror 洁净度要求更高。

采用方案 C。

## 架构

### 1. 正式 deploy mirror

- 固定目录：`D:\fqpack\freshquant-2026.2.23`
- 固定分支：`main`
- `deploy-production.yml` 不再使用 `GITHUB_WORKSPACE` 的临时下载目录作为部署根目录。
- 正式 deploy 前先同步本机 mirror，再以 mirror 目录作为 `repo_root` 调用 `run_formal_deploy.py`。

### 2. Mirror 同步步骤

新增一个同步脚本，职责是：

- 校验 mirror 目录存在且是 git repo。
- 校验当前没有脏工作树。
- 执行 `git fetch origin main`。
- 校验 `origin/main` 等于 workflow 触发 SHA。
- 在 clean 状态下执行：
  - `git checkout main`
  - `git merge --ff-only origin/main`
- 再次校验 `HEAD` 等于目标 SHA。

该脚本失败时，正式 deploy 立即失败，不尝试自动 reset 或清理本机 mirror。

### 3. 正式 workflow 触发与执行

`deploy-production.yml` 调整为：

- 直接 `on: push` 监听 `main`
- 不再等待 `Docker Images` 的 `workflow_run`
- 在 production runner 上：
  - 校验当前远程 `main` tip 仍等于 `github.sha`
  - 同步 deploy mirror
  - 在 deploy mirror 下执行 `py -3.12 -m uv sync --frozen`
  - 调用 `run_formal_deploy.py --repo-root D:\fqpack\freshquant-2026.2.23 --head-sha <sha>`

### 4. Docker 策略

正式 deploy 的 Docker 动作改回本地构建优先：

- `script/docker_parallel_compose.py` / `script/docker_parallel_compose.ps1` 仍保留 smart-build 能力
- 但 `run_formal_deploy.py` 走的正式入口不再依赖 GHCR 预构建是 deploy 前置
- 部署文档语义改为：正式环境以 deploy mirror 本地源码为真值，本地 compose build 是正式路径

### 5. Docker Images workflow 的地位

`.github/workflows/docker-images.yml` 可以保留，但从“正式 deploy 前置”降为“辅助镜像发布/缓存链路”。本轮不删除它，只把正式 deploy 从它的触发链路中解耦。

## 数据流

1. PR merge 到远程 `main`
2. GitHub 触发 `deploy-production.yml` push run
3. production runner 校验 `github.sha` 仍是远程 `main` tip
4. 同步本机 `D:\fqpack\freshquant-2026.2.23` mirror 到该 SHA
5. 在 mirror 目录执行依赖准备
6. `run_formal_deploy.py` 基于 mirror 的 `.git` 直接计算 `last_success_sha..HEAD` changed paths
7. 执行 docker/host deploy、health check、runtime ops check
8. 写入 `production-state.json`

## 失败处理

- mirror 目录不存在或不是 git repo：失败
- mirror 工作树脏：失败
- `origin/main` 与 workflow SHA 不一致：失败
- mirror 无法 fast-forward 到 `origin/main`：失败
- `uv sync` 失败：失败
- deploy/health/runtime ops 任一步失败：保持现有语义，只更新 `last_attempt_*`，不推进 `last_success_sha`

## 测试

- workflow 契约测试：
  - `deploy-production.yml` 改为 `push` 触发 `main`
  - 不再包含源码 zipball 下载逻辑
  - 使用固定 mirror 路径
- mirror 同步脚本测试：
  - clean + fast-forward 成功
  - dirty repo 失败
  - `origin/main` 与目标 SHA 不一致失败
  - fast-forward 失败
- orchestrator 测试：
  - 使用 git repo changed paths，不再要求 compare API
- 文档守卫：
  - `docs/current/deployment.md`
  - `docs/current/runtime.md`

