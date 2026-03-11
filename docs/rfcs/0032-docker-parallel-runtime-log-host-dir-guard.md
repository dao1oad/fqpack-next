# RFC 0032: Docker 并行运行观测日志挂载防呆

- **状态**：Done
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-11
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

当前并行 Docker 运行面中，`fq_apiserver` 通过 `docker/compose.parallel.yaml` 把宿主机运行观测目录挂载到容器 `/freshquant/logs/runtime`。现状使用：

- `${FQ_RUNTIME_LOG_HOST_DIR:-../logs/runtime}`

这个默认值在主仓根目录下通常可用，但在 `git worktree` 中执行 `docker compose -f docker/compose.parallel.yaml up -d --build` 时，会静默解析到 worktree 自己的 `../logs/runtime`。若宿主机 Supervisor 仍在主仓工作区运行，最终会出现：

- 宿主机真实写入 `D:\fqpack\freshquant-2026.2.23\logs\runtime`
- Docker `fq_apiserver` 读取 worktree 的空目录
- `/api/runtime/traces` 返回空数组
- `/runtime-observability` 页面空白

该问题的危险点不在于容器报错，而在于容器看起来“正常启动”，但数据源错了，导致排障成本很高。

## 2. 目标（Goals）

- 让 `docker/compose.parallel.yaml` 在未显式提供宿主机运行观测目录时直接失败，而不是静默读取错误目录
- 让 `docker/compose.parallel.yaml` 在 worktree 中也显式读取主工作区 `.env`，而不是因为缺少 worktree 本地 `.env` 造成启动失败
- 提供仓库内标准启动脚本，自动计算并设置 `FQ_RUNTIME_LOG_HOST_DIR` 与 `FQ_COMPOSE_ENV_FILE`
- 让 worktree 部署默认指向该仓库的主工作区 `logs/runtime` 与主工作区 `.env`
- 保持 `fq_apiserver` 运行观测读取路径不变：容器内仍使用 `/freshquant/logs/runtime`

## 3. 非目标（Non-Goals）

- 不修改运行观测后端 API 契约
- 不修改前端 `/runtime-observability` 查询逻辑
- 不直接改写宿主机 Supervisor 的运行目录
- 不处理 Docker 之外的部署形态

## 4. 范围（Scope）

**In Scope**
- `docker/compose.parallel.yaml` 的运行观测目录挂载语义
- 并行 Docker 启动脚本
- 文档、迁移记录与破坏性变更登记
- 与脚本直接相关的单元测试

**Out of Scope**
- 运行观测埋点本身
- 宿主机实时链路 worker 的功能语义
- Mongo/Redis/TDX 端口或其他 Docker 服务编排

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**
- 防止 `fq_apiserver` 在未设置 `FQ_RUNTIME_LOG_HOST_DIR` 时静默挂错目录
- 给出标准启动入口，统一设置 `FQ_RUNTIME_LOG_HOST_DIR`
- 在 worktree 中优先解析到该仓库主工作区的 `logs/runtime`

**不负责（Must Not）**
- 不自动修改宿主机运行中的 Mongo 参数
- 不自动停止或重启宿主机 Supervisor
- 不自动清理旧 Docker 容器或 worktree

**依赖（Depends On）**
- `docker/compose.parallel.yaml`
- Git worktree 元数据（用于解析主工作区）
- Windows PowerShell 启动环境

**禁止依赖（Must Not Depend On）**
- 不依赖人工记住额外环境变量
- 不依赖当前 shell `cwd` 的相对路径推断

## 6. 对外接口（Public API）

本 RFC 新增两个标准脚本入口：

- `script/docker_parallel_compose.ps1`
- `script/docker_parallel_up.ps1`

输入：
- `docker_parallel_compose.ps1` 接受完整 compose 子命令参数
- `docker_parallel_up.ps1` 接受可选服务列表，默认启动全部 compose 服务
- 可选覆盖环境变量 `FQ_RUNTIME_LOG_HOST_DIR`
- 可选覆盖环境变量 `FQ_COMPOSE_ENV_FILE`

输出：
- 调用 `docker compose -f docker/compose.parallel.yaml ...`
- 在脚本进程内导出正确的 `FQ_RUNTIME_LOG_HOST_DIR`
- 在脚本进程内导出正确的 `FQ_COMPOSE_ENV_FILE`

错误语义：
- 如果无法解析主工作区路径、宿主机运行观测目录不存在或主工作区 `.env` 不存在，脚本直接退出非零
- 如果直接运行 `docker compose` 且未设置 `FQ_RUNTIME_LOG_HOST_DIR` 或 `FQ_COMPOSE_ENV_FILE`，Compose 在变量展开阶段直接失败

兼容性策略：
- 已显式设置 `FQ_RUNTIME_LOG_HOST_DIR` 时，保留人工覆盖能力
- 已显式设置 `FQ_COMPOSE_ENV_FILE` 时，保留人工覆盖能力
- 容器内 `FQ_RUNTIME_LOG_DIR=/freshquant/logs/runtime` 语义保持不变

## 7. 数据与配置（Data / Config）

- 新增强制环境变量：`FQ_RUNTIME_LOG_HOST_DIR`
- 新增强制环境变量：`FQ_COMPOSE_ENV_FILE`
- 标准值：`<主工作区>\logs\runtime`
- 标准值：`<主工作区>\.env`
- `docker/compose.parallel.yaml` 中不再使用 `../logs/runtime` 作为默认回退
- `docker/compose.parallel.yaml` 中所有 `env_file` 统一改为显式读取 `FQ_COMPOSE_ENV_FILE`
- 启动脚本通过 Git worktree 信息解析主工作区，再拼出 `logs/runtime` 与 `.env`

## 8. 破坏性变更（Breaking Changes）

- 影响面：
  - 直接执行 `docker compose -f docker/compose.parallel.yaml ...` 且未设置 `FQ_RUNTIME_LOG_HOST_DIR` 或 `FQ_COMPOSE_ENV_FILE` 的旧习惯将不再工作
- 迁移步骤：
  1. 优先改用 `script/docker_parallel_compose.ps1` 或 `script/docker_parallel_up.ps1`
  2. 或显式设置 `FQ_RUNTIME_LOG_HOST_DIR` 与 `FQ_COMPOSE_ENV_FILE` 后再执行 `docker compose`
- 回滚方案：
  - 回退 compose 变量校验与启动脚本，恢复旧的相对路径默认值

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- 旧部署习惯：人工从任意工作区执行 `docker compose`
- 新归属：仓库标准启动脚本 + compose fail-fast 变量校验

## 10. 测试与验收（Acceptance Criteria）

- [x] 单元测试覆盖“从 worktree 输出解析主工作区路径并拼出 `logs/runtime` 与 `.env`”
- [x] 启动脚本在未显式传入 `FQ_RUNTIME_LOG_HOST_DIR` / `FQ_COMPOSE_ENV_FILE` 时能自动设置正确路径
- [x] `docker/compose.parallel.yaml` 在缺少 `FQ_RUNTIME_LOG_HOST_DIR` 或 `FQ_COMPOSE_ENV_FILE` 时直接失败
- [x] 使用标准脚本重建 `fq_apiserver` 后，容器内 `/freshquant/logs/runtime` 能看到宿主机 JSONL
- [x] `http://127.0.0.1:15000/api/runtime/traces` 返回非空 `traces`

## 11. 风险与回滚（Risks / Rollback）

- 风险点：主工作区路径解析错误，导致脚本阻塞部署
- 缓解：保留 `FQ_RUNTIME_LOG_HOST_DIR` / `FQ_COMPOSE_ENV_FILE` 显式覆盖，并为解析逻辑补单元测试

- 风险点：现有运维仍直接执行原始 `docker compose`
- 缓解：Compose 层 fail-fast，文档和脚本统一切换

- 回滚：回退本 RFC 引入的脚本、Compose 变量校验和文档更新，恢复旧相对路径默认值

## 12. 里程碑与拆分（Milestones）

- M1：RFC/设计稿/implementation plan 完成并批准
- M2：主工作区路径解析 helper 与测试完成，覆盖 `logs/runtime` 与 `.env`
- M3：Compose fail-fast + 通用 compose wrapper + `up` 启动脚本完成
- M4：联机修复当前 `fq_apiserver` 挂载并验证 `/api/runtime/traces` 非空
