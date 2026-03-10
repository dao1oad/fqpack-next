# Runtime Observability Host/Docker Unified Design

## 背景

当前 `/runtime-observability` 页面和 `/api/runtime/*` 接口已经可访问，但 Docker 并行部署下 `fq_apiserver` 容器默认读取容器内相对路径 `logs/runtime`，没有与宿主机实际落盘的 `D:\fqpack\freshquant-2026.2.23\logs\runtime` 共享目录。结果是：

- 宿主机已产生 JSONL 事件
- Docker API 容器读不到这些文件
- `/api/runtime/traces` 返回空数组
- 页面“运行观测”看起来没有内容

同时，前端组件看板当前还存在两个结构性问题：

- `xtdata_producer` / `xtdata_consumer` 与后端实际 `xt_producer` / `xt_consumer` 命名不一致
- 组件看板仅按 `component` 取第一张健康卡，无法同时展示同名组件在 `host:*` 与 `docker:*` 下的状态

## 目标

- 让 `/api/runtime/*` 能读取宿主机和 Docker 已接入模块的同一份运行观测 JSONL
- 让 `/runtime-observability` 能按 `runtime_node + component` 同时展示宿主机与 Docker 节点状态
- 保持现有后端公共接口契约不变

## 非目标

- 不新增 Mongo/Redis 作为运行观测持久层
- 不把尚未接入埋点的模块纳入本次范围
- 不把 `trace_step` 强行当作健康心跳事件

## 设计

### 1. 共享目录

- 继续使用宿主机仓库下 `logs/runtime` 作为运行观测 JSONL 根目录
- Docker `fq_apiserver` 显式挂载宿主机 `../logs/runtime` 到容器 `/freshquant/logs/runtime`
- Docker `fq_apiserver` 显式注入 `FQ_RUNTIME_LOG_DIR=/freshquant/logs/runtime`

这样容器 API 与宿主机进程读取的是同一份文件事实源。

### 2. 后端读取行为

- `freshquant/runtime_observability/logger.py` 继续使用 `FQ_RUNTIME_LOG_DIR` 优先、默认 `logs/runtime` 兜底
- `/api/runtime/traces`、`/api/runtime/events`、`/api/runtime/raw-files/*` 不改契约，只要共享目录打通，就能直接看到宿主机 JSONL
- `/api/runtime/health/summary` 继续只统计 `heartbeat` 与 `metric_snapshot`

### 3. 前端组件看板

- 组件看板从“每个 component 一张卡”改成“每个 `runtime_node + component` 一张卡”
- 点击看板卡片时，联动筛选同时带上 `component` 和 `runtime_node`
- 高级筛选抽屉增加 `runtime_node`
- 组件分布统计继续按 `component` 聚合，作为问题分布概览，不替代节点级卡片

### 4. 命名修正

- 前端 `CORE_COMPONENTS` 使用后端实际组件名：
  - `xt_producer`
  - `xt_consumer`

## 验收标准

- `fq_apiserver` 容器内 `/freshquant/logs/runtime` 存在并能看到宿主机已落盘 JSONL
- `/api/runtime/traces` 不再对宿主机已存在日志返回空数组
- `/api/runtime/raw-files/files` 与 `/api/runtime/raw-files/tail` 能读取宿主机日志
- 组件看板可同时显示同一组件的 `host:*` 与 `docker:*` 两张卡
- XT 组件命名修正后能正常进入看板
- 仅已有 `heartbeat` / `metric_snapshot` 的组件出现在健康摘要中

## 风险

- 若宿主机进程未显式统一 `FQ_RUNTIME_LOG_DIR`，未来仍可能写出到其他工作目录
- 当前并非所有模块都产出心跳事件，因此“健康看板为空”在部分模块上仍可能是事实而不是 bug
