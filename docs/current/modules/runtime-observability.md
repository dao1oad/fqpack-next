# 运行观测

## 职责

Runtime Observability 负责把交易链和数据链中的 runtime 事件写入原始 JSONL 文件，并在 API 与页面中聚合成全局 Trace、组件 Event、组件健康和异常优先视图。它是排障工具，不是业务事实源。

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

只有带强关联键的事件会参与 Trace 组装，当前强关联键集合是：

- `trace_id`
- `intent_id`
- `request_id`
- `internal_order_id`

Trace 组装口径不是“单键优先分桶”，而是“强关联键图合并”：

- 任一事件只要通过上述任意强关联键与其他事件连通，就会归入同一条 Trace
- 不允许按 `symbol + 时间窗口 + action` 之类弱关联补链
- 纯 `heartbeat`、`bootstrap`、`config_resolve`、`subscription_load` 或其他无强关联键事件，只进入 Event / health / raw 视图，不进入 Trace 列表

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

页面侧当前通过 `morningglory/fqwebui/src/http.js` 的全局 Axios 响应拦截器消费已解包的 `res.data`，因此 `/runtime-observability` 直接读取顶层字段 `components`、`traces`、`trace`、`events`、`files`、`records`。如果静态资源仍按 `response.data.*` 读取，接口即使返回 `200` 且已有数据，页面也会表现为统计卡、Trace/Event 列表和 Raw Browser 全空。

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

## 页面信息架构

页面主交互固定为双视图：

- `全局 Trace`
  - 主列表默认展示最近全局 Trace，不再因为左侧组件选择而裁剪
  - Trace 返回并展示后端显式聚合字段：
    - `trace_kind`
    - `trace_status`
    - `break_reason`
    - `first_ts`
    - `last_ts`
    - `duration_ms`
    - `entry_component` / `entry_node`
    - `exit_component` / `exit_node`
    - `slowest_step`
- `组件 Event`
  - 主列表直接读取 `/api/runtime/events`
  - 左侧组件导航只决定当前 Event 视图聚焦哪个组件，不再决定主 Trace 列表范围
  - `xt_producer` / `xt_consumer` 的 `bootstrap`、`config_resolve`、`subscription_load`、`heartbeat` 在这里查看，不伪装成业务 Trace

当前页面外壳已对齐统一的 workbench density 语法：

- 顶部使用紧凑 toolbar 承载视图切换、刷新、筛选和全局摘要
- 原统计卡已压缩成摘要条与筛选标签
- 三栏结构仍保留为组件导航 / Trace(Event) 主列表 / 详情区，但外层面板语法统一
- 中间 `全局 Trace` 主区已从卡片堆切换为高密度列表，字段不减，只改变承载方式
- 组件侧栏、Trace/Event 主列表、详情区与 raw 列表都使用各自滚动条；浏览器窗口不再承担该页主滚动

## Guardian 专项视图

当全局 Trace 命中 `guardian_signal` 时，中间列表和详情会优先展示 Guardian 的结构化判断信息：

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

## Trace 元数据

当前 `/api/runtime/traces` / `/api/runtime/traces/<trace_id>` 会向后兼容地扩展以下字段：

- `trace_kind`
  - 当前至少包含：`guardian_signal`、`takeprofit`、`stoploss`、`external_reported`、`external_inferred`、`manual_api_order`、`unknown`
- `trace_status`
  - 当前至少包含：`open`、`completed`、`stalled`、`broken`
- `break_reason`
- `first_ts`
- `last_ts`
- `duration_ms`
- `entry_component` / `entry_node`
- `exit_component` / `exit_node`
- `step_count`
- `slowest_step`
- 每个 step 的 `offset_ms`、`delta_prev_ms`

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

这些 heartbeat 仍然是正式运行事件，但现在应该从 `组件 Event` 视图查看，而不是从 Trace 列表猜测。

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
- pytest 运行默认把 `FQ_RUNTIME_LOG_DIR` 指向临时目录，并在每个测试前后清空模块级 runtime logger 缓存；测试默认不得写入正式 `logs/runtime`

## 排障点

### 页面空白

- 检查日志目录是否存在
- 检查 `/api/runtime/components`
- 检查 `/api/runtime/health/summary` 是否至少返回核心组件占位卡片

### trace 数量异常少

- 检查业务进程是否真的 emit runtime event
- 检查业务事件是否带 `trace_id` / `intent_id` / `request_id` / `internal_order_id`
- 检查 logger 队列是否丢数据过多

### 组件 Event 里看不到 XT 心跳

- 先确认 `/api/runtime/events?component=xt_producer` 或 `/api/runtime/events?component=xt_consumer` 是否已有最近 `heartbeat`
- 再确认 producer / consumer 进程是否真的在输出 `bootstrap` / `config_resolve` / `subscription_load` / `heartbeat`
- 如果 health 卡片有心跳，但 Event 视图为空，优先检查页面是否仍在跑旧静态资源

### Guardian 看板看不出为什么跳过

- 先确认 Guardian runtime event 是否带 `signal_summary`
- 再确认节点里是否有 `decision_context`、`decision_expr`、`decision_outcome`
- 如果页面全局 Trace 只剩通用字段，检查后端返回里是否已有 `trace_kind=guardian_signal`

### Raw Browser 打不开

- 检查请求的 `runtime_node/component/date/file` 是否存在
- 检查路径参数是否合法
