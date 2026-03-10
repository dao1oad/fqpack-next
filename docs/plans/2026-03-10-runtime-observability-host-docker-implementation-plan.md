# Runtime Observability Host/Docker Unified Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让运行观测页面和 API 同时读取宿主机与 Docker 已接入模块的 JSONL，并按 `runtime_node + component` 展示节点状态。

**Architecture:** Docker `fq_apiserver` 改为读取宿主机共享的 `logs/runtime` 目录；后端接口契约保持不变；前端组件看板改为节点级卡片，并修正 XT 组件命名与筛选联动。

**Tech Stack:** Docker Compose、Flask、Vue 3、Node test runner、pytest

---

### Task 1: Docker 共享目录回归测试与修复

**Files:**
- Modify: `docker/compose.parallel.yaml`
- Test: 手工验证 `docker exec fqnext_20260223-fq_apiserver-1 sh -lc "find /freshquant/logs/runtime -maxdepth 4 -type f | head"`

**Step 1: 写出期望状态**

- `fq_apiserver` 需要：
  - 新增 `FQ_RUNTIME_LOG_DIR=/freshquant/logs/runtime`
  - 挂载 `../logs/runtime:/freshquant/logs/runtime`

**Step 2: 先人工验证当前状态确实不满足**

Run: `docker exec fqnext_20260223-fq_apiserver-1 sh -lc "find /freshquant/logs/runtime -maxdepth 4 -type f | head"`

Expected: 当前为空或提示目录不存在。

**Step 3: 修改 Compose**

- 给 `fq_apiserver` 增加 `environment` 和 `volumes`

**Step 4: 重启并验证**

Run: `docker compose -f docker/compose.parallel.yaml up -d --build fq_apiserver`
Run: `docker exec fqnext_20260223-fq_apiserver-1 sh -lc "find /freshquant/logs/runtime -maxdepth 4 -type f | head"`

Expected: 能列出宿主机 JSONL 文件。

### Task 2: 前端节点级组件看板失败测试

**Files:**
- Modify: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`
- Reference: `morningglory/fqwebui/src/views/runtimeObservability.mjs`

**Step 1: 写失败测试**

- 断言 `buildComponentBoard()` 在同一 `component` 存在两个不同 `runtime_node` 的健康卡时，返回两张卡
- 断言 `xt_producer` / `xt_consumer` 能出现在卡片列表中

**Step 2: 运行失败测试**

Run: `node --test src/views/runtime-observability.test.mjs`

Expected: 失败，当前实现只会取第一张健康卡，且 XT 命名不匹配。

### Task 3: 前端实现节点级卡片与筛选联动

**Files:**
- Modify: `morningglory/fqwebui/src/views/runtimeObservability.mjs`
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`

**Step 1: 最小实现**

- `CORE_COMPONENTS` 改为后端真实组件名
- `buildComponentBoard()` 改为按 `runtime_node + component` 生成卡片
- `boardFilter` 增加 `runtime_node`
- 点击组件卡片时同时筛选 `component` 与 `runtime_node`
- 高级筛选抽屉增加 `runtime_node`
- `buildTraceQuery()` 支持 `runtime_node`

**Step 2: 运行前端测试**

Run: `node --test src/views/runtime-observability.test.mjs`

Expected: PASS

### Task 4: 后端运行观测 API 回归验证

**Files:**
- Modify: `freshquant/tests/test_runtime_observability_routes.py`（仅当需要增加环境路径回归用例）

**Step 1: 若现有测试不足，补一个环境变量路径读取用例**

- 断言设置 `FQ_RUNTIME_LOG_DIR` 后，`/api/runtime/traces` 能读取对应目录

**Step 2: 运行后端测试**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_observability_routes.py -q`

Expected: PASS

### Task 5: 文档与迁移进度更新

**Files:**
- Modify: `docs/agent/Docker并行部署指南.md`
- Modify: `docs/migration/progress.md`

**Step 1: 更新部署文档**

- 写明运行观测目录在并行 Docker 模式下需要共享到 `fq_apiserver`

**Step 2: 更新 progress**

- 在对应迁移记录中追加本次修复内容与日期

**Step 3: 运行最小验证命令**

Run: `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/traces`

Expected: 返回非空 `traces`

### Task 6: 端到端验证

**Files:**
- None

**Step 1: 重建 API 容器**

Run: `docker compose -f docker/compose.parallel.yaml up -d --build fq_apiserver`

**Step 2: 验证后端接口**

Run: `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/traces`
Run: `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/health/summary`

Expected:
- `traces` 非空
- `health/summary` 至少对已有 heartbeat 组件返回数据；若当前无 heartbeat，返回空数组也要与现有落盘事实一致

**Step 3: 验证前端页面**

- 打开 `http://127.0.0.1:18080/runtime-observability`
- 确认同一组件的 `host:*` 与 `docker:*` 可以同时显示为独立卡片
