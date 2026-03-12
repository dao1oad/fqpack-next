# 运行观测

## 职责

Runtime Observability 负责把交易链和数据链中的 runtime 事件写入原始 JSONL 文件，并在 API 与页面中聚合成 trace、组件健康和异常优先视图。它是排障工具，不是业务事实源。

## 入口

- 页面
  - `/runtime-observability`
- API
  - `/api/runtime/components`
  - `/api/runtime/health/summary`
  - `/api/runtime/traces`
  - `/api/runtime/traces/<trace_id>`
  - `/api/runtime/events`
  - `/api/runtime/raw-files/files`
  - `/api/runtime/raw-files/tail`

## 依赖

- `RuntimeEventLogger`
- 原始日志目录 `logs/runtime` 或 `FQ_RUNTIME_LOG_DIR`
- trace assembler
- component/node catalog

## 数据流

`业务模块 emit runtime event -> queue-based logger -> logs/runtime/<runtime_node>/<component>/<date>/*.jsonl -> runtime routes -> RuntimeObservability.vue`

只有带 `trace_id`、`request_id` 或 `internal_order_id` 的事件会参与 trace 组装；纯 `heartbeat` 或无关联键事件只进入 health / raw 视图，不进入 trace 列表。

当前 catalog 中的核心组件：

- `xt_producer`
- `xt_consumer`
- `guardian_strategy`
- `tpsl_worker`
- `position_gate`
- `order_submit`
- `broker_gateway`
- `puppet_gateway`
- `xt_report_ingest`
- `order_reconcile`

## Guardian 专项视图

当组件看板选中 `guardian_strategy` 时，页面不再只显示通用 trace 摘要，而是优先展示 Guardian 的结构化判断信息：

- 最近链路流直接显示信号摘要
  - `signal_summary.code/name/position/period/price/fire_time/discover_time/remark/tags`
- Trace / 节点详情直接显示判断依据
  - `decision_branch`
  - `decision_expr`
  - `decision_context`
  - `decision_outcome`
  - `reason_code`
- Raw Browser 仍保留，但只作为补充排查工具

Guardian 当前 catalog 节点口径：

- `receive_signal`
- `holding_scope_resolve`
- `timing_check`
- `price_threshold_check`
- `signal_structure_check`
- `cooldown_check`
- `quantity_check`
- `position_management_check`
- `submit_intent`
- `finish`

## 存储

- 原始文件：JSONL
- 路径结构：`<root>/<runtime_node>/<component>/<date>/<component>_<date>_<pid>.jsonl`
- 不写 Mongo，不写 Redis

该模块允许丢事件：当队列满时，logger 会增加 dropped 计数，而不是阻塞主交易链。

## 配置

- `FQ_RUNTIME_LOG_DIR`
- 页面自动刷新开关
- 页面筛选参数
  - `trace_id`
  - `request_id`
  - `internal_order_id`
  - `intent_id`
  - `symbol`
  - `component`
  - `runtime_node`

## 部署/运行

- API / 页面改动：重建 `fq_apiserver` 与 `fq_webui`
- 业务侧只要使用 `RuntimeEventLogger` 即可写入，不需要单独部署 runtime worker

## 排障点

### 页面空白

- 检查日志目录是否存在
- 检查 `/api/runtime/components`

### trace 数量异常少

- 检查业务进程是否真的 emit runtime event
- 检查业务事件是否带 `trace_id` / `request_id` / `internal_order_id`
- 检查 logger 队列是否丢数据过多

### Guardian 看板看不出为什么跳过

- 先确认 Guardian runtime event 是否带 `signal_summary`
- 再确认节点里是否有 `decision_context`、`decision_expr`、`decision_outcome`
- 如果页面 recent trace 只剩通用字段，检查是否选中了 `guardian_strategy` 组件看板

### Raw Browser 打不开

- 检查请求的 `runtime_node/component/date/file` 是否存在
- 检查路径参数是否合法
