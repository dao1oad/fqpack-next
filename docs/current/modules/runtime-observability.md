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

`/api/runtime/traces` 当前返回 Trace 摘要字段之外，还会附带：

- `steps_preview`
  - 每条 Trace 最多 12 个按时间正序排列的步骤预览
  - 直接复用 runtime event 的 `signal_summary`、`decision_context`、`decision_outcome`
  - 同时保留 `decision_branch`、`decision_expr`、`error_type`、`error_message`
  - 用途是让全局 Trace 列表在不额外发 detail 请求的情况下直接渲染节点 hover

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

当前 indexer 会把 `runtime_ingest_progress` 作为文件 offset snapshot：

- 只有当某个 JSONL 的 `offset / file_size / mtime` 发生变化时，才会写新的 progress
- 单轮扫描内多个文件的 progress 会合并成一次批量写入，避免为每个文件单独生成 ClickHouse insert part

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

恢复口径：

- 不要通过“删除 progress 后全量重扫 JSONL”来恢复已存在的 `runtime_events`
- 正式恢复入口是 `script/rebuild_runtime_ingest_progress.py`
- 该脚本会先从 `runtime_events` 读取每个 `raw_file` 已入库的最大 `raw_line`，再反推当前 JSONL 的 byte offset，重建 `runtime_ingest_progress`

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
- 全局 Trace 主表当前新增 `信号备注` 列，优先显示 Guardian `signal_summary.remark`
- 全局 Trace 主表的 `节点路径` 当前不再是纯文本；Guardian 会直接渲染中文判断节点 pill，并在 hover 时展示该节点判断上下文
- 全局 Trace 主表当前会优先把横向空间让给 `节点路径`：
  - `标的` 与 `信号备注` 列宽被刻意压缩
  - `节点数 / 总耗时 / 断裂原因` 继续保留在右侧
  - 过长链路通过中间 Trace panel 自己的横向滚动条查看，不依赖浏览器页面滚动
- 中间主表 panel 当前自己承担纵向滚动：
  - `全局 Trace` 与 `组件 Event` 都不再依赖浏览器页面主滚动查看长列表
  - 主表下方的空状态只会在当前 ledger 真正为空时显示；“没有下一页”不再错误显示为“暂无最近 Trace / Event”
- Guardian 的全局 Trace 节点 hover 当前重点展开：
  - `receive_signal`：标的、方向、周期、信号价格、触发时间、发现时间、信号备注、信号标签
  - `holding_scope_resolve`：仓位状态、是否持仓内、是否必选池内、成交次数
  - `timing_check`：触发时间、发现时间、截止时间、最大时长、最近成交时间
  - `price_threshold_check`：当前价、最近成交价、底河价格、顶河价格
  - `signal_structure_check`：成交次数、中枢数量、最近成交时间、最近成交价、候选中枢、是否分离
  - `cooldown_check`：冷却键、是否命中冷却、上次值、冷却分钟
  - `quantity_check`：下单数量、路径、网格层级、来源价格、盈利成交数
  - `position_management_check`：动作、下单数量、拒绝原因
  - `submit_intent`：动作、下单数量、盈利减仓标记
  - `finish`：最终结果、最终原因，以及最后一次判断上下文
- Guardian 节点名当前统一显示为：
  - `信号接收`
  - `范围判断`
  - `时间条件判断`
  - `价格阈值判断`
  - `中枢分离判断`
  - `冷却判断`
  - `下单数量判断`
  - `仓位门禁判断`
  - `策略下单意图`
  - `最终结论`
- 自动刷新只刷新摘要列表，不自动刷新已打开的 Trace detail
- 页面内所有标的展示统一为 `symbol / symbol_name`
- 写入 ClickHouse 与查询返回阶段都会优先复用现有 instrument lookup 补全 `symbol_name`
- 名称最终仍缺失时，前端兜底显示 `symbol / 未知名称`
- `tpsl_worker` 的组件 Event 视图与 `/api/runtime/events` 当前默认隐藏未命中止盈/止损价、空价格和盘后空跑评估；需要完整原始记录时改看 Raw Browser
- 组件 Event 视图当前会按组件切换一列中文业务语义：
  - `position_gate`: `决策结果`
  - `guardian_strategy`: `判断结果`
  - `tpsl_worker`: `触发类型`
  - `order_submit`: `提交语义`
  - `xt_report_ingest`: `回报语义`
  - `order_reconcile`: `对账语义`
  对应取值都直接来自 runtime event payload 的稳定字段，不依赖前端对 `reason_code` 做猜测翻译
- 顶部 `异常链路` 与 `异常节点` 摘要当前可直接跳转到异常 Trace/异常步骤浏览态
- 左侧组件卡片里的异常摘要当前拆成：
  - `异常链路`
  - `异常节点`
  两个直接入口，分别用于快速定位组件异常 Trace 与组件异常 Event
- 左侧组件卡片在 `异常链路 / 异常节点 = 0` 时会把这两个 badge 降成只读态，不再吞掉整张卡片的点击；此时点卡片任意常见区域都应切到对应组件 Event
- Trace 详情步骤区当前支持：
  - `首个异常`
  - `上一个异常`
  - `下一个异常`
  - `最慢节点`
  并在跳转后自动滚动到当前选中步骤
- Trace 详情的 `步骤` tab 当前不再使用卡片式节点详情头块；当前选中节点统一使用高密度表格分区展示：
  - `基础字段`
  - `Guardian 信号`
  - `判断字段`
  - `Guardian 上下文`
  - `异常信息`
  - `Payload / Metrics`
- `异常节点` 模式下，切换中间主表中的 Trace 会先清空旧链路 detail，再加载新链路 detail；旧的异步详情响应不会覆盖当前已选中的新链路
- 浏览页在 `1920x1080 / 100%` 桌面分辨率下当前会把右侧详情区下沉到第二行，避免仍然坚持三栏导致右侧详情只能靠浏览器缩放阅读
- 步骤 ledger、右侧步骤详情与 Raw JSON 都保持组件内滚动；页面壳本身不承担主滚动
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
- 如果 `runtime_ingest_progress` 因 broken parts 无法 attach，先重建这张进度表，再恢复 indexer；不要直接让 indexer 从 0 重扫所有 JSONL

### Raw Browser 正常但 summary/detail 为空

- 先看 ClickHouse 连接配置
- 再看 indexer 是否滞后
- 不要再怀疑 JSONL 文件扫描性能
