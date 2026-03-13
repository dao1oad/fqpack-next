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

`/api/runtime/health/summary` 与 `/runtime-observability` 的左侧组件侧栏固定展示核心组件全集，顺序固定为：

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

没有最新 health 数据的组件不会消失，而是返回占位项：`status=unknown`、`heartbeat_age_s=null`、`is_placeholder=true`，页面显示为 `unknown / no data`。组件的详细健康、异常链路数、异常节点数和 highlights 默认通过 hover popover 查看，而不是直接铺在主区域。

页面侧当前通过 `morningglory/fqwebui/src/http.js` 的全局 Axios 响应拦截器消费已解包的 `res.data`，因此 `/runtime-observability` 直接读取顶层字段 `components`、`traces`、`trace`、`files`、`records`。如果静态资源仍按 `response.data.*` 读取，接口即使返回 `200` 且已有数据，页面也会表现为统计卡、trace 列表和 Raw Browser 全空。

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

页面主交互路径固定为：`组件侧栏 -> 最近链路流 -> 单条链路详情`。

当左侧组件侧栏选中 `guardian_strategy` 时，中间的最近链路流不再只显示通用 trace 摘要，而是优先展示 Guardian 的结构化判断信息：

- 最近链路流直接显示信号摘要
  - `signal_summary.code/name/position/period/price/fire_time/discover_time/remark/tags`
- 最近链路流中的节点路径支持 hover
  - 优先显示 `decision_branch`、`decision_expr`、`reason_code`、`decision_outcome`、`decision_context`
  - 其他组件字段不足时，降级显示 `message/status/payload/metrics` 摘要
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

## 心跳口径

- `xt_producer`
  - 固定每 5 分钟输出 1 次 `heartbeat`
  - 关键指标：
    - `rx_age_s`：距最近一次 tick 回调的年龄
    - `tick_count_5m`：最近 5 分钟收到的 tick 数
    - `tick_batches_5m`：最近 5 分钟收到的 callback 批次数
    - `subscribed_codes`：当前订阅股票数
    - `connected`：是否已连上 XTData
- `xt_consumer`
  - 固定每 5 分钟输出 1 次 `heartbeat`
  - 关键指标：
    - `last_bar_age_s`：距最近一次成功处理 bar 的年龄
    - `processed_bars_5m`：最近 5 分钟处理的 bar 数
    - `backlog_sum`：Redis tick 队列 backlog 总量
    - `scheduler_pending`：等待 fullcalc 的聚合任务数
    - `catchup_mode`：是否处于 catchup 模式

页面上的组件卡片直接显示最近心跳年龄与这些关键指标，用于人工判断：

- `xt_producer` 是否活着，以及最近 5 分钟是否还在收 tick
- `xt_consumer` 是否活着，以及最近 5 分钟是否仍在处理队列

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
- 检查 `/api/runtime/health/summary` 是否至少返回核心组件占位卡片

### trace 数量异常少

- 检查业务进程是否真的 emit runtime event
- 检查业务事件是否带 `trace_id` / `request_id` / `internal_order_id`
- 检查 logger 队列是否丢数据过多

### Guardian 看板看不出为什么跳过

- 先确认 Guardian runtime event 是否带 `signal_summary`
- 再确认节点里是否有 `decision_context`、`decision_expr`、`decision_outcome`
- 如果页面 recent trace 只剩通用字段，检查左侧组件侧栏是否选中了 `guardian_strategy`

### Raw Browser 打不开

- 检查请求的 `runtime_node/component/date/file` 是否存在
- 检查路径参数是否合法
