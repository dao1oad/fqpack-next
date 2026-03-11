# Docker 并行运行观测日志挂载防呆 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 防止并行 Docker 在 worktree 中静默挂错运行观测目录，并同步收敛 `.env` 读取路径，提供标准脚本自动设置正确的 `FQ_RUNTIME_LOG_HOST_DIR` 与 `FQ_COMPOSE_ENV_FILE`。

**Architecture:** 通过 Python helper 解析 Git 主工作区路径；PowerShell compose wrapper 自动导出 `FQ_RUNTIME_LOG_HOST_DIR` 与 `FQ_COMPOSE_ENV_FILE`；Compose 取消危险默认值并改为 fail-fast。这样即使从 worktree 部署，`fq_apiserver` 也会读取主工作区的 `logs/runtime`，所有服务也会统一读取主工作区 `.env`。

**Tech Stack:** Docker Compose、PowerShell、Python 3.12、pytest

---

### Task 1: 写 RFC、设计稿与迁移记录

**Files:**
- Create: `docs/rfcs/0032-docker-parallel-runtime-log-host-dir-guard.md`
- Create: `docs/plans/2026-03-11-docker-parallel-runtime-log-host-dir-guard-design.md`
- Create: `docs/plans/2026-03-11-docker-parallel-runtime-log-host-dir-guard-implementation-plan.md`
- Modify: `docs/migration/progress.md`

**Step 1: 登记 RFC 0032**

- 状态先写 `Approved`
- 备注写清“Compose fail-fast + 标准启动脚本”

### Task 2: 先写失败测试，覆盖主工作区解析 helper

**Files:**
- Create: `freshquant/tests/test_docker_parallel_runtime.py`
- Create: `script/docker_parallel_runtime.py`

**Step 1: 写失败测试**

- 给定 `git worktree list --porcelain` 的样例输出
- 断言 helper 能解析出主工作区
- 断言最终 runtime 目录是 `<主工作区>\\logs\\runtime`

**Step 2: 运行测试并确认失败**

Run: `py -3.12 -m pytest freshquant/tests/test_docker_parallel_runtime.py -q`

Expected: FAIL

**Step 3: 写最小实现**

- 实现 `parse_primary_worktree_path()`
- 实现 `resolve_runtime_log_host_dir()`

**Step 4: 运行测试并确认通过**

Run: `py -3.12 -m pytest freshquant/tests/test_docker_parallel_runtime.py -q`

Expected: PASS

### Task 3: 实现标准脚本

**Files:**
- Create: `script/docker_parallel_compose.ps1`
- Create: `script/docker_parallel_up.ps1`

**Step 1: compose wrapper 逻辑**

- 读取当前仓根目录
- 若已显式设置 `FQ_RUNTIME_LOG_HOST_DIR`，直接使用
- 否则调用 `script/docker_parallel_runtime.py`
- 若已显式设置 `FQ_COMPOSE_ENV_FILE`，直接使用
- 否则调用 `script/docker_parallel_runtime.py`
- 校验目录与 `.env` 都存在
- 执行 `docker compose -f docker/compose.parallel.yaml ...`

**Step 2: `up` 脚本参数**

- 支持可选服务名透传
- 默认不改变原 `up -d --build` 语义
- 内部委托通用 compose wrapper

### Task 4: 修改 Compose 为 fail-fast

**Files:**
- Modify: `docker/compose.parallel.yaml`

**Step 1: 去掉危险默认值**

- 将 `${FQ_RUNTIME_LOG_HOST_DIR:-../logs/runtime}` 改为必填变量语义
- 将所有 `env_file: ../.env` 改为必填 `FQ_COMPOSE_ENV_FILE`

**Step 2: 保持容器内语义不变**

- `FQ_RUNTIME_LOG_DIR=/freshquant/logs/runtime`
- 容器内路径仍是 `/freshquant/logs/runtime`

### Task 5: 更新文档与破坏性变更记录

**Files:**
- Modify: `docs/agent/Docker并行部署指南.md`
- Modify: `docs/migration/breaking-changes.md`
- Modify: `docs/migration/progress.md`

**Step 1: 文档改成标准脚本入口**

- 主要示例改为 `script/docker_parallel_up.ps1`
- 其他 `ps/logs/down` 示例改为 `script/docker_parallel_compose.ps1`
- 保留显式 `FQ_RUNTIME_LOG_HOST_DIR` 与 `FQ_COMPOSE_ENV_FILE` 的手工入口

**Step 2: 记录 breaking change**

- 写明以后直接执行 `docker compose` 且不设置 `FQ_RUNTIME_LOG_HOST_DIR` / `FQ_COMPOSE_ENV_FILE` 会失败

### Task 6: 联机验证

**Files:**
- None

**Step 1: 用标准脚本重建 API**

Run: `powershell -ExecutionPolicy Bypass -File script/docker_parallel_up.ps1 fq_apiserver fq_webui`

**Step 2: 验证挂载**

Run: `docker inspect fqnext_20260223-fq_apiserver-1 --format "{{json .Mounts}}"`
Run: `docker exec fqnext_20260223-fq_apiserver-1 sh -lc "find /freshquant/logs/runtime -maxdepth 4 -type f | head"`

Expected: 容器能看到主工作区 runtime 文件

**Step 3: 验证 API**

Run: `curl.exe --noproxy "*" -s http://127.0.0.1:15000/api/runtime/traces`

Expected: `traces` 非空

### Task 7: 聚焦回归与收尾

Run: `py -3.12 -m pytest freshquant/tests/test_docker_parallel_runtime.py -q`

Expected: PASS
