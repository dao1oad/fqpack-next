# Docker 并行运行观测日志挂载防呆 Design

## 背景

`fq_apiserver` 需要从宿主机读取 `logs/runtime` 才能给 `/api/runtime/*` 和 `/runtime-observability` 提供数据。当前 Compose 用 `${FQ_RUNTIME_LOG_HOST_DIR:-../logs/runtime}` 作为宿主机挂载源，这在主仓可用，但在 `git worktree` 里会静默解析到 worktree 自己的空目录。

联机实现时又暴露出第二个同类问题：Compose 里的 `env_file: ../.env` 也会在 worktree 下解析到不存在的 worktree 本地 `.env`，导致标准修复脚本即使解决了 runtime log 挂载，仍可能在重建容器时失败。

这个问题的关键不是代码没写，而是部署没有 fail-fast：

- 容器能正常起来
- API 返回空数组
- 前端页面空白
- 排障时不容易直接看出是挂载错目录

## 方案选择

### 方案 A：只补文档

- 成本最低
- 但对人有强依赖
- 下次仍然可能被直接 `docker compose up` 触发

### 方案 B：Compose 强制要求 `FQ_RUNTIME_LOG_HOST_DIR`

- 能阻止静默误部署
- 但每次都要人工设置环境变量

### 方案 C：Compose fail-fast + 标准启动脚本自动设置

- Compose 负责防呆
- 启动脚本负责可用性
- 即使在 worktree 中执行，也能统一解析到主工作区 `logs/runtime` 与主工作区 `.env`

推荐采用方案 C。

## 设计

### 1. Compose fail-fast

修改 `docker/compose.parallel.yaml`：

- 取消 `${FQ_RUNTIME_LOG_HOST_DIR:-../logs/runtime}`
- 改为必须显式提供 `FQ_RUNTIME_LOG_HOST_DIR`
- 所有 `env_file` 改为必须显式提供 `FQ_COMPOSE_ENV_FILE`

效果：

- 如果用户绕过标准脚本直接执行 `docker compose`，会在变量展开阶段直接失败
- 不再允许“容器正常但读空目录”的静默错误
- 不再允许 worktree `.env` 缺失时到部署阶段才暴露

### 2. 标准启动脚本

新增：

- `script/docker_parallel_compose.ps1`
- `script/docker_parallel_up.ps1`
- `script/docker_parallel_runtime.py`

职责分工：

- `docker_parallel_runtime.py`
  - 解析 `git worktree list --porcelain`
  - 识别主工作区路径
  - 输出 `<主工作区>\logs\runtime`
  - 输出 `<主工作区>\.env`
- `docker_parallel_compose.ps1`
  - 统一解析或读取 `FQ_RUNTIME_LOG_HOST_DIR`
  - 统一解析或读取 `FQ_COMPOSE_ENV_FILE`
  - 透传任意 `docker compose` 子命令
- `docker_parallel_up.ps1`
  - 作为 `up -d --build` 的薄包装
  - 委托 `docker_parallel_compose.ps1`

### 3. 主工作区解析规则

解析规则要稳定、可测试：

- 优先取 `git worktree list --porcelain` 中第一个 `worktree ` 条目
- 视其为该仓库主工作区
- 若解析失败，则直接报错，不做相对路径猜测
- 允许通过现有环境变量 `FQ_RUNTIME_LOG_HOST_DIR` 与 `FQ_COMPOSE_ENV_FILE` 人工覆盖

### 4. 测试策略

聚焦测试放在 Python helper：

- 给一段 `git worktree list --porcelain` 样本
- 断言能解析出主工作区
- 断言最终 runtime 目录是 `<主工作区>\logs\runtime`
- 断言最终 compose env file 是 `<主工作区>\.env`

联机验证：

- 用标准脚本重建 `fq_apiserver`
- 验证容器内 `/freshquant/logs/runtime` 有文件
- 验证 `http://127.0.0.1:15000/api/runtime/traces` 返回非空

### 5. 迁移与回滚

迁移后新的推荐入口变成：

```powershell
powershell -File script/docker_parallel_up.ps1
```

查询/日志/停止等其他 compose 子命令统一改用：

```powershell
powershell -File script/docker_parallel_compose.ps1 ps
```

保留显式覆盖：

```powershell
$env:FQ_RUNTIME_LOG_HOST_DIR="D:\fqpack\freshquant-2026.2.23\logs\runtime"
$env:FQ_COMPOSE_ENV_FILE="D:\fqpack\freshquant-2026.2.23\.env"
docker compose -f docker/compose.parallel.yaml up -d --build
```

若需回滚，只需回退：

- compose 变量校验
- 启动脚本
- helper 测试与文档
