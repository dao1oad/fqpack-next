# 运行观测

## 职责

Runtime Observability 当前采用“双存储”：

- JSONL：原始证据、Raw Browser、回放
- ClickHouse：页面/API 的热查询仓

它负责把交易链和数据链中的 runtime 事件写入原始 JSONL，并通过独立 `runtime indexer` 增量写入 ClickHouse，供 `/runtime-observability` 和 `/api/runtime/*` 查询。

## 页面与 API

- 页面
  - `/runtime-observability`
- API
  - `/api/runtime/components`
  - `/api/runtime/health/summary`
  - `/api/runtime/traces`
  - `/api/runtime/traces/<trace_key>`
  - `/api/runtime/traces/<trace_key>/steps`
  - `/api/runtime/events`
  - `/api/runtime/raw-files/files`
  - `/api/runtime/raw-files/tail`

`/api/runtime/traces`、`/api/runtime/traces/<trace_key>`、`/api/runtime/traces/<trace_key>/steps`、`/api/runtime/events`、`/api/runtime/health/summary` 都支持：

- `start_time`
- `end_time`

`/api/runtime/traces` 额外支持：

- `trace_id`
- `intent_id`
- `request_id`
- `internal_order_id`
- `trace_kind`
- `symbol`
- `component`
- `runtime_node`
- `cursor_ts`
- `cursor_trace_key`
- `limit`

`/api/runtime/traces/<trace_key>/steps` 与 `/api/runtime/events` 额外支持：

- `cursor_ts`
- `cursor_event_id`
- `limit`

## 当前架构

### 写入链

`业务模块 -> RuntimeEventLogger -> logs/runtime/<runtime_node>/<component>/<date>/*.jsonl`

原始写入链不直接依赖 ClickHouse。

### 索引链

`logs/runtime/**/*.jsonl -> fq_runtime_indexer -> ClickHouse(runtime_observability.runtime_events)`

`fq_runtime_indexer` 维护文件 offset 状态，只做增量读取，不改写原始 JSONL。

### 查询链

`ClickHouse -> Flask runtime routes -> RuntimeObservability.vue`

当前 `/runtime-observability` 不再直扫 `logs/runtime` 聚合 Trace/Event/Health。只有 Raw Browser 继续读原始文件。

## Trace 会话语义

当前不再做“强关联键图无限合并”。会话 key 规则固定为：

- 有 `trace_id`：`trace__<trace_id>`
- 无 `trace_id` 但有 `intent_id`：`intent__<intent_id>`
- 无显式链路 ID，仅有 `request_id`：`request__<request_id>__m__<yyyyMMddHHmm>`
- 无显式链路 ID，仅有 `internal_order_id`：`order__<internal_order_id>__m__<yyyyMMddHHmm>`

这样可以保留显式链路，同时阻断 `xt_report_ingest` 这类长生命周期回报把一整天事件并进单条 Trace。

## ClickHouse 表

### `runtime_events`

热查询主表，至少包含：

- `event_id`
- `ts`
- `event_day`
- `runtime_node`
- `component`
- `node`
- `event_type`
- `status`
- `trace_id`
- `intent_id`
- `request_id`
- `internal_order_id`
- `session_key`
- `session_type`
- `symbol`
- `symbol_name`
- `message`
- `reason_code`
- `error_type`
- `error_message`
- `payload_json`
- `metrics_json`
- `raw_json`
- `raw_file`
- `raw_line`
- `ingest_ts`

### `runtime_ingest_progress`

索引器进度表，记录：

- `raw_file`
- `offset_bytes`
- `file_size`
- `mtime`
- `updated_at`

## 页面信息架构

页面当前是 summary/detail 模式：

- 首屏拉：
  - 组件健康摘要
  - Trace 摘要第一页
  - 当前组件 Event 摘要第一页
- 点击 Trace 后才请求：
  - `/api/runtime/traces/<trace_key>`
  - 必要时 `/api/runtime/traces/<trace_key>/steps`
- Event 与 Trace 列表都走分页 cursor
- 全局 Trace 顶部的类型按钮会带 `trace_kind` 重新请求最新 Trace；不是在当前已加载列表上做本地筛选
- 自动刷新只刷新摘要列表，不自动刷新已打开的 Trace detail
- 页面内所有标的展示统一为 `symbol / symbol_name`
- 写入 ClickHouse 与查询返回阶段都会优先复用现有 instrument lookup 补全 `symbol_name`
- 名称最终仍缺失时，前端兜底显示 `symbol / 未知名称`
- 顶部 `异常链路` 与 `异常节点` 摘要当前可直接跳转到异常 Trace/异常步骤浏览态
- 左侧组件卡片里的异常摘要当前拆成：
  - `异常链路`
  - `异常节点`
  两个直接入口，分别用于快速定位组件异常 Trace 与组件异常 Event
- Trace 详情步骤区当前支持：
  - `首个异常`
  - `上一个异常`
  - `下一个异常`
  - `最慢节点`
  并在跳转后自动滚动到当前选中步骤
- Raw Browser 继续按 `runtime_node/component/date/file` 直接读 JSONL

## 组件健康

`/api/runtime/health/summary` 当前从 ClickHouse 聚合：

- 最新 heartbeat 时间
- 最新 metrics
- `trace_count`
- `issue_trace_count`
- `issue_step_count`
- `last_issue_ts`

左侧组件导航仍固定展示核心组件全集：

- `xt_producer`
- `xt_consumer`
- `guardian_strategy`
- `position_gate`
- `order_submit`
- `broker_gateway`
- `puppet_gateway`
- `xt_report_ingest`
- `order_reconcile`
- `tpsl_worker`

## 存储与保留

- 原始文件：JSONL
- 热查询：ClickHouse
- 路径结构：`<root>/<runtime_node>/<component>/<date>/<component>_<date>_<pid>.jsonl`
- `logs/runtime/**` 仍只保留最近 5 个交易日
- logger 允许丢事件：队列满时增加 dropped 计数，不阻塞主交易链

## 配置

- `FQ_RUNTIME_LOG_DIR`
- `FQ_RUNTIME_CLICKHOUSE_URL`
- `FQ_RUNTIME_CLICKHOUSE_DATABASE`
- `FQ_RUNTIME_CLICKHOUSE_USER`
- `FQ_RUNTIME_CLICKHOUSE_PASSWORD`

## 部署/运行

- Docker 服务：
  - `fq_runtime_clickhouse`
  - `fq_runtime_indexer`
  - `fq_apiserver`
  - `fq_webui`
- 运行观测相关改动上线时，至少要同步发布：
  - API
  - Web UI
  - ClickHouse schema/indexer

## 排障点

### 页面无 Trace

- 先查 `/api/runtime/traces`
- 再查 ClickHouse `runtime_events` 是否已持续入库
- 最后才看 Raw Browser

### 页面有原始日志但无摘要

- 先查 `fq_runtime_indexer` 是否在跑
- 再查 `runtime_ingest_progress` 是否推进
- 再查 `fq_runtime_clickhouse` 健康

### Raw Browser 正常但 summary/detail 为空

- 先看 ClickHouse 连接配置
- 再看 indexer 是否滞后
- 不要再怀疑 JSONL 文件扫描性能
