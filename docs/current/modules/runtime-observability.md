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

`/api/runtime/health/summary`、`/api/runtime/traces`、`/api/runtime/traces/<trace_id>`、`/api/runtime/events` 当前都支持可选查询参数：

- `start_time`
- `end_time`

取值格式固定为 ISO datetime；页面默认按北京时间今日 `00:00:00 -> 23:59:59` 请求，也允许手动改成任意时间区间。

## 依赖

- `RuntimeEventLogger`
- 原始日志目录 `logs/runtime` 或 `FQ_RUNTIME_LOG_DIR`
- trace assembler
- component/node catalog

## 数据流

`业务模块 emit runtime event -> queue-based logger -> logs/runtime/<runtime_node>/<component>/<date>/*.jsonl -> runtime routes -> RuntimeObservability.vue`

当 API 显式传入 `start_time/end_time` 时，后端会先把文件扫描范围收敛到命中的日期目录，再按事件时间二次过滤；不再对整个 `logs/runtime/**` 做全量 `rglob("*.jsonl")`。

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

没有最新 health 数据的组件不会消失，而是返回占位项：`status=unknown`、`heartbeat_age_s=null`、`is_placeholder=true`，页面显示为 `unknown / no data`。左侧组件导航当前改成与 TPSL 标的列表一致的卡片切换语法，每张卡片直接展示组件中文名、健康状态、主 runtime node、异常 Trace/Step 计数；长文本统一走截断加鼠标悬浮提示。

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
  - 主列表默认展示当前可见的全部全局 Trace，不再因为左侧组件选择而裁剪，也不再默认截断到固定 50 条
  - 页面首次进入默认只看“今日”时间窗口；顶部时间区间框默认填充北京时间当天起止，切换区间后会重载 Trace / Event / health
  - 页面首次进入时，如果当前结果集中存在 `guardian_signal`，`trace_kind` 默认锁定到 `guardian_signal`；只有不存在 Guardian 链路时才回退到 `全部链路`
  - `trace_kind`、强关联键和关键词筛选都基于当前保留窗口内的全量 Trace 集合执行，不再先截断最近 500 条再做页面筛选
  - 主表列统一使用中文语义，当前展示：
    - `最近时间`
    - `标的代码`
    - `标的名称`
    - `链路类型`
    - `链路状态`
    - `节点路径`
    - `节点数`
    - `总耗时`
    - `断裂原因`
  - `节点路径` 会把整条 Trace 的全部节点按组件/节点中文映射串联起来，不再只显示 entry/exit 两端
  - 主表支持按 `trace_kind` 下拉筛选，并直接展示中文 kind 标签
- `组件 Event`
  - 主列表直接读取 `/api/runtime/events`
  - 左侧组件切换会把当前 `component/runtime_node` 并入 Event 请求，避免被其他组件的最近事件窗口挤掉
  - 左侧组件导航只决定当前 Event 视图聚焦哪个组件，不再决定主 Trace 列表范围
  - Event 主表列统一使用中文语义：`运行时间 / 运行节点 / 组件 / 节点 / 状态 / 标的 / 摘要 / 指标`
  - 如果事件带 `symbol` 与名称字段，主表会按 `代码 / 名称` 合成显示在 `标的` 列
  - `xt_producer` / `xt_consumer` 的 `bootstrap`、`config_resolve`、`subscription_load`、`heartbeat` 在这里查看，不伪装成业务 Trace

当前页面外壳已对齐统一的 workbench density 语法：

- 顶部使用紧凑 toolbar 承载视图切换、刷新、筛选和全局摘要
- 原先右上角的视图切换、仅异常、高级筛选与刷新按钮，当前统一挪到左上标题区，与时间区间框并排
- 页面默认开启最新运行状态自动刷新，固定每 15 秒重拉一次 health / trace / event 摘要；不再显示单独的“自动刷新”开关，只保留手动刷新按钮作为兜底
- 时间区间控件使用北京时间 `datetimerange`，默认今天，可显式切换到任意区间查看对应 runtime 中断信息
- 时间区间一旦变更，摘要条会直接回显当前实际生效的 `开始 -> 结束` 时间，避免只在 picker 内部可见
- 原统计卡已压缩成摘要条与筛选标签
- 三栏结构仍保留为组件导航 / Trace(Event) 主列表 / 详情区，但外层面板语法统一
- 左侧组件区采用卡片式导航，而不是折叠面板；卡片显示中文组件名、状态、心跳摘要和异常计数
- 中间 `全局 Trace` 与 `组件 Event` 主区都采用 dense ledger，而不是 card/feed row
- 所有页面时间统一格式化为北京时间（`Asia/Shanghai`）并精确到秒
- `全局 Trace` 主表新增 `标的名称` 列，并移除中间表格的 `identity` / `slowest` 列
- `标的名称` 优先读 trace/event 顶层 `symbol_name` 与 step 内联名称字段；默认不再在 `/api/runtime/**` 热路径里同步查询 instrument 信息
- 只有显式传 `include_symbol_name=1` 调 `/api/runtime/traces`、`/api/runtime/traces/<trace_id>` 或 `/api/runtime/events` 时，后端才会按需回填缺失的 `symbol_name`
- 右侧详情区统一改成 tab 语法：
  - Trace：`步骤 / 摘要 / 原始数据`
  - Event：`事件 / 载荷 / 原始数据`
- 右侧详情区的 `Summary` / `Event` / `Payload` 视图统一使用高密度 ledger table，而不是堆叠卡片；Trace 摘要、异常慢点、Guardian 结论、事件元数据、payload/metrics 字段都按键值表展开
- `组件 Event` 右侧 `事件` tab 当前不再只显示轻量摘要，而是对齐 Trace 节点详情的节点级视图：
  - `事件摘要`
  - `判断与关联字段`
  - `Guardian 判断`
  - `Guardian 信号`
  - `上下文`
  - `Payload / Metrics`
- `组件 Event` 详情中的标的显示当前会优先回填为 `代码 / 名称`；即使顶层事件未直接携带 `symbol/symbol_name`，只要 payload 或 signal summary 中已有代码/名称，也会补齐到详情页与中间台账
- Trace 与 Event 的详情 tab 使用固定高度与固定内边距的标签样式，激活态只改变颜色与边框，不再因为点击后文案或边框变化出现异形尺寸
- `步骤` tab 默认展示 step dense ledger，直接暴露 `branch/expr/reason/outcome/context/error`
- `全局 Trace` 的 `entry -> exit` 列和右侧详情区列宽已显式放大，避免关键链路信息被状态标签或冗余留白挤压
- 右侧详情列内部使用两列 ledger grid 和 full-span section 混排；当 Guardian、payload 或 metrics 数据存在时，会主动占满右侧详情面板，避免顶部摘要下方留下大片空白
- 右侧详情 tab 在 100% 浏览器缩放下必须完整可用；内容超出时改由详情面板自身滚动，不再要求浏览器缩放到 80%
- 组件侧栏、Trace/Event 主列表、详情区与 raw 列表都使用各自滚动条；浏览器窗口不再承担该页主滚动
- 当视口低于三栏最小宽度时，外层布局允许受控横向滚动，而不是直接裁掉中间或右侧内容
- 点击 Trace 行时直接复用 `/api/runtime/traces` 已返回的完整 step 明细，不再为同一条 Trace 追加一次 `/api/runtime/traces/<trace_id>` 冗余请求
- 在 `全局 Trace` 视图点击左侧组件卡片时，页面会自动切换到 `组件 Event` 并按当前组件重载事件列表

TPSL 观测口径当前固定为：

- `takeprofit` 与 `stoploss` 始终分开显示为两类 Trace
- 只有真正创建并提交 TPSL 批次的链路才会进入全局 Trace
- 未设置止盈/止损价格、价格未命中、或命中后因 `can_use_volume` / `board_lot` 等原因未形成真实卖出操作的事件，只保留在 Event，不进入 Trace
- TPSL step 详情只在 Guardian 组件节点上展示 `Guardian 判断 / Guardian 信号`，止盈止损链路不再显示空表格

## Guardian 专项视图

当全局 Trace 命中 `guardian_signal` 时，中间列表和详情会优先展示 Guardian 的结构化判断信息：

- 最近链路流直接显示信号摘要
  - `signal_summary.code/name/position/period/price/fire_time/discover_time/remark/tags`
- Step dense ledger 直接显示判断列
  - `decision_branch`
  - `decision_expr`
  - `reason_code`
  - `decision_outcome`
  - `decision_context` 摘要
  - `payload.error_type` / `payload.error_message`
- Trace / 节点详情继续显示完整判断依据
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
  - 当前至少包含：`open`、`completed`、`failed`、`stalled`、`broken`
  - 当最后一个有效 step 是异常 `error/failed` 节点时，Trace 会被判定为 `failed`
- `break_reason`
  - 异常终止时会形如 `unexpected_exception@component.node:ErrorType`
- `first_ts`
- `last_ts`
- `duration_ms`
- `entry_component` / `entry_node`
- `exit_component` / `exit_node`
- `step_count`
- `slowest_step`
- 每个 step 的 `offset_ms`、`delta_prev_ms`

异常终止节点的 runtime payload 当前会保留：

- `payload.error_type`
- `payload.error_message`

因此 `/runtime-observability` 不再只显示“停在上一跳”，而是直接显示真实异常节点和异常类型。

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

页面上的组件健康台账直接显示最近心跳年龄与这些关键指标，用于人工判断：

- `xt_producer` 是否活着，以及最近 5 分钟是否还在收 tick
- `xt_consumer` 是否活着，以及最近 5 分钟是否仍在处理队列

这些 heartbeat 仍然是正式运行事件，但现在应该从 `组件 Event` 视图查看，而不是从 Trace 列表猜测。

## 存储

- 原始文件：JSONL
- 路径结构：`<root>/<runtime_node>/<component>/<date>/<component>_<date>_<pid>.jsonl`
- `logs/runtime/**` 只保留最近 5 个交易日的日期目录；logger 在写新文件前会先按交易日窗口清理更旧目录，交易日历不可用时退化为保留最新 5 个日期目录
- 不写 Mongo，不写 Redis

该模块允许丢事件：当队列满时，logger 会增加 dropped 计数，而不是阻塞主交易链。

## 配置

- `FQ_RUNTIME_LOG_DIR`
- 页面默认 15 秒自动刷新 latest 状态；原始日志文件列表与 tail 仍是手动请求
- 页面筛选参数
  - `trace_id`
  - `request_id`
  - `internal_order_id`
  - `intent_id`
  - `symbol`
  - `component`
  - `runtime_node`
  - `start_time`
  - `end_time`
  - `include_symbol_name`

## 部署/运行

- API / 页面改动：重建 `fq_apiserver` 与 `fq_webui`
- 业务侧只要使用 `RuntimeEventLogger` 即可写入，不需要单独部署 runtime worker
- pytest 运行默认把 `FQ_RUNTIME_LOG_DIR` 指向临时目录，并在每个测试前后清空模块级 runtime logger 缓存；测试默认不得写入正式 `logs/runtime`
- Runtime Observability 相关测试默认 stub 掉 instrument lookup 与交易日历来源；需要补充 `symbol_name` 或交易日历分支时必须在测试里显式 monkeypatch

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
