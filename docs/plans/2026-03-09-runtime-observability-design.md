# FreshQuant 运行观测与日志可视化设计

- 日期：2026-03-09
- 状态：Design Approved
- 范围：FreshQuant 实盘核心链路
- 覆盖对象：
  - `XTData Producer/Consumer`
  - `Guardian` 策略
  - `TPSL` 止盈止损
  - `Position Management`
  - `Order Management`
  - `Broker/Puppet` 下单网关
- 当前部署边界：本机单节点，兼容 Docker/宿主机混合运行

## 1. 背景

旧仓已经存在一套可用的结构化日志与网页可视化链路：

- 结构化 JSONL 落盘
- 本机 `/api/system_logs/*` 只读接口
- `SystemLogs.vue` 做 trace 聚合与页面展示

但目标仓当前状态是：

- 运行链路已经重构为策略域、订单域、仓位域、止盈止损域、执行网关分层
- `api_server` 未注册旧仓的 `system_logs/cluster` 蓝图
- Web UI 没有旧仓 `SystemLogs` 页面
- 当前架构下，旧仓 `Guardian` 的很多节点语义已经失真，不能原样复用

因此需要围绕当前目标仓架构重新设计运行观测与日志可视化能力。

## 2. 目标

本设计目标：

1. 提供面向实盘核心链路的统一结构化事件模型。
2. 优先支持“链路追踪（trace）”，能看清一笔信号/订单卡在哪个节点。
3. 同步提供“健康看板”，用于观察 Producer/Consumer、仓位管理、订单桥接、下单网关的运行状态。
4. 保留 raw JSONL tail 作为底层排障后门。
5. 兼容本机单节点和 Docker/宿主机混合运行场景。
6. 后续可以平滑扩展为“JSONL -> Mongo 读模型”，但首期不引入该复杂度。

## 3. 非目标

首期明确不做：

- 多机器 cluster 聚合
- TradingAgents-CN、Dagster、Huey 的全量接入
- Mongo 事件库存储
- 复杂拓扑动画或全量历史报表
- 让日志系统参与业务控制流或业务决策

## 4. 最高优先级约束

### 4.1 绝不阻塞主链路

这是首要硬约束，不可退让：

- 日志模块绝不能阻塞主进程。
- 日志模块绝不能阻塞 `Guardian -> OrderSubmit -> Broker/Puppet` 下单主链路。
- 日志模块绝不能因为文件 IO、JSON 序列化、目录创建、接口聚合、下游异常而影响实盘交易执行。

### 4.2 强制设计要求

为满足上述硬约束，首期实现必须满足：

1. 业务线程只允许调用非阻塞 `emit()` 接口。
2. 结构化日志采用有界内存队列 + 后台异步写线程。
3. 队列满时允许丢日志，不允许阻塞业务线程。
4. 所有日志异常必须吞掉，只能降级，不得向业务抛出异常。
5. 首期不允许在交易关键路径直接写 Mongo、HTTP、Redis 以外的新观测依赖。
6. 任何 trace 聚合、健康统计、页面查询均在读路径执行，不回写业务链路。
7. UI 和 API 均为只读能力，不得参与业务控制流。

推荐策略：

- 默认 drop newest（丢当前事件）即可，避免额外锁竞争。
- 每个组件提供 `dropped_count` 自身监控，便于发现观测丢失。

## 5. 总体方案

首期采用：

- `JSONL 异步落盘 + 后端聚合 + Web UI 展示`

不采用：

- `前端聚合为主`
- `直接写 Mongo 事件库`

原因：

- 对实盘链路侵入最小
- 最适合宿主机/容器混合进程
- 最容易保证“不阻塞交易”
- 可以保留旧仓 raw tail 的排障体验
- 后续若需要入库，只需新增异步消费层，不推翻首期

## 6. 组件边界

新增统一模块：

- `freshquant/runtime_observability/`
  - `schema.py`
  - `ids.py`
  - `logger.py`
  - `node_catalog.py`
  - `assembler.py`
  - `health.py`

新增后端只读 API：

- `freshquant/rear/runtime/routes.py`

新增前端页面：

- `morningglory/fqwebui/src/views/RuntimeObservability.vue`

业务接入点：

- `freshquant/strategy/guardian.py`
- `freshquant/market_data/xtdata/market_producer.py`
- `freshquant/market_data/xtdata/strategy_consumer.py`
- `freshquant/tpsl/*`
- `freshquant/position_management/service.py`
- `freshquant/order_management/submit/service.py`
- `freshquant/order_management/*`
- `morningglory/fqxtrade/fqxtrade/xtquant/broker.py`
- `morningglory/fqxtrade/fqxtrade/xtquant/puppet.py`

## 7. 运行节点模型

### 7.1 一级组件

首期一级组件固定为：

- `xt_producer`
- `xt_consumer`
- `strategy_monitor`
- `guardian_strategy`
- `tpsl_worker`
- `position_worker`
- `position_gate`
- `order_submit`
- `execution_bridge`
- `broker_gateway`
- `puppet_gateway`
- `xt_report_ingest`
- `order_reconcile`

### 7.2 Guardian 节点

`Guardian` 不再承担完整交易链，只保留策略自身判断链：

- `receive_signal`
- `holding_scope_resolve`
- `timing_check`
- `fill_context_load`
- `threshold_fetch`
- `separating_zs_check`
- `buy_grid_decision`
- `profitable_slice_calc`
- `cooldown_check`
- `submit_intent`
- `summary`

以下旧仓节点不再留在 `Guardian` 内：

- `position_check`
- `lock_check`
- `order_preparation`
- `order_push`

它们迁移到：

- `position_gate`
- `order_submit`
- `execution_bridge`

### 7.3 信号到下单主链

- `strategy_monitor.detect_signal`
- `guardian_strategy.receive_signal`
- `guardian_strategy.holding_scope_resolve`
- `guardian_strategy.timing_check`
- `guardian_strategy.fill_context_load`
- `guardian_strategy.threshold_fetch`
- `guardian_strategy.separating_zs_check` 或 `guardian_strategy.profitable_slice_calc`
- `guardian_strategy.buy_grid_decision`
- `guardian_strategy.cooldown_check`
- `guardian_strategy.submit_intent`
- `position_gate.state_load`
- `position_gate.freshness_check`
- `position_gate.policy_eval`
- `order_submit.intent_normalize`
- `order_submit.credit_mode_resolve`
- `order_submit.tracking_create`
- `order_submit.queue_payload_build`
- `execution_bridge.queue_write`
- `broker_gateway.queue_consume`
- `broker_gateway.action_dispatch`
- `puppet_gateway.submit_prepare`
- `puppet_gateway.submit_decision`
- `puppet_gateway.submit_result`
- `xt_report_ingest.report_receive`
- `xt_report_ingest.order_match`
- `xt_report_ingest.trade_match`
- `order_reconcile.internal_match`
- `order_reconcile.projection_update`

### 7.4 TPSL 主链

- `xt_producer.tick_quote_emit`
- `tpsl_worker.tick_match`
- `tpsl_worker.profile_load`
- `tpsl_worker.trigger_eval`
- `tpsl_worker.batch_create`
- `tpsl_worker.submit_intent`
- 并入：
  - `position_gate`
  - `order_submit`
  - `execution_bridge`
  - `broker_gateway`
  - `puppet_gateway`
  - `xt_report_ingest`
  - `order_reconcile`

### 7.5 Producer/Consumer 主链

- `xt_producer.bootstrap`
- `xt_producer.config_resolve`
- `xt_producer.xtdata_connect`
- `xt_producer.subscription_load`
- `xt_producer.tick_pump`
- `xt_producer.minute_bar_build`
- `xt_producer.redis_enqueue`
- `xt_consumer.redis_pop`
- `xt_consumer.batch_group`
- `xt_consumer.fullcalc_run`
- `xt_consumer.cache_write`
- `xt_consumer.pubsub_publish`

### 7.6 仓位状态主链

- `position_worker.account_query`
- `position_worker.policy_state_compute`
- `position_worker.snapshot_save`
- `position_worker.state_publish`
- `position_gate.state_load`
- `position_gate.freshness_check`
- `position_gate.policy_eval`
- `position_gate.decision_record`

## 8. Trace ID 与关联 ID 设计

统一使用四层关联：

- `trace_id`
  - 一条完整业务链 ID
  - 从信号源或 TPSL 触发源开始生成
- `intent_id`
  - 一次策略下单意图 ID
  - 由 `Guardian/TPSL` 生成
- `request_id`
  - 订单域受理 ID
  - 对接当前 `OrderSubmitService`
- `internal_order_id`
  - 订单域事实主键

原则：

- 策略域之前至少有 `trace_id`
- 提交订单意图后必须带 `intent_id`
- 订单域受理后必须带 `request_id`
- 执行回报与对账链尽量补齐 `internal_order_id`

## 9. runtime_node 设计

虽然首期是本机单节点，但必须在逻辑上区分运行面：

- `host:guardian`
- `host:broker`
- `host:xt_producer`
- `host:xt_consumer`
- `docker:api`
- `docker:rear`

目的：

- 区分宿主机进程与容器进程
- 为后续扩展多节点保留字段语义
- 在 UI 上准确展示链路跨越了哪个运行面

## 10. 统一事件 Schema

事件分为四类：

- `trace_step`
- `heartbeat`
- `metric_snapshot`
- `exception`

### 10.1 公共字段

- `ts`
- `runtime_node`
- `component`
- `node`
- `event_type`
- `status`
- `message`
- `reason_code`
- `trace_id`
- `intent_id`
- `request_id`
- `internal_order_id`
- `symbol`
- `action`
- `strategy_name`
- `source`
- `decision_branch`
- `decision_expr`
- `payload`
- `metrics`

### 10.2 语义要求

- `trace_step` 必须有 `component/node/status`
- 进入订单域后必须带 `request_id`
- `heartbeat` 不要求 `trace_id`
- `reason_code` 必须短码化，不使用长自然语言
- `payload` 放上下文
- `metrics` 放数值指标
- `decision_branch` 与 `decision_expr` 专门描述分支判断结果

### 10.3 示例

```json
{
  "event_type": "trace_step",
  "ts": "2026-03-09T10:21:33.120+08:00",
  "runtime_node": "host:guardian",
  "component": "guardian_strategy",
  "node": "timing_check",
  "trace_id": "trc_20260309_abc123",
  "intent_id": "int_20260309_def456",
  "request_id": null,
  "internal_order_id": null,
  "symbol": "002594",
  "action": "buy",
  "status": "skipped",
  "reason_code": "signal_too_old",
  "decision_branch": "holding_add",
  "decision_expr": "discover_time-fire_time > 1800s",
  "message": "signal outside allowed window",
  "metrics": {
    "delta_seconds": 1850
  },
  "payload": {
    "fire_time": "2026-03-09T09:30:01+08:00",
    "discover_time": "2026-03-09T10:00:51+08:00"
  }
}
```

## 11. 存储与读接口

### 11.1 JSONL 文件布局

首期建议：

- `<root>/<runtime_node>/<component>/<YYYY-MM-DD>/<component>_<YYYY-MM-DD>_<pid>.jsonl`

### 11.2 API

首期新增只读接口：

- `GET /api/runtime/health/summary`
- `GET /api/runtime/components`
- `GET /api/runtime/traces`
- `GET /api/runtime/traces/<trace_id>`
- `GET /api/runtime/events`
- `GET /api/runtime/raw-files/*`

要求：

- `traces` 和 `health` 聚合必须在后端完成
- 前端不再自己硬编码聚合规则
- 保留 raw tail，作为保底排障入口

## 12. Web UI 设计

页面结构建议：

1. 总览页
   - 组件健康卡片
   - 最近 5 分钟心跳、错误数、关键指标
2. 链路追踪页
   - 支持按 `trace_id/request_id/internal_order_id/symbol/time range` 查询
   - 展示完整步骤链
3. 组件明细页
   - 按组件聚合节点统计
4. 原始记录页
   - 浏览 JSONL raw records

### 12.1 健康卡片关注指标

- Producer：
  - `heartbeat age`
  - `rx_age_s`
  - `bar_push_age_s`
  - `reconnect_count`
- Consumer：
  - `backlog_sum`
  - `max_lag_s`
  - `batches`
- Position Worker：
  - `last_snapshot_at`
  - `current_state`
- Broker：
  - `queue_len`
  - `current_action`
  - `last_consume_ts`

### 12.2 Trace 详情

每个步骤至少展示：

- `component`
- `node`
- `status`
- `reason_code`
- `message`
- `duration`
- 关键 `metrics`

支持一键跳转查看该步骤对应 raw records。

## 13. 与旧仓的取舍

保留：

- JSONL 异步落盘
- 结构化字段
- `Guardian` 分阶段记录思路
- Producer/Consumer 心跳与异常分离
- raw tail 调试入口

不保留：

- 前端主导 trace 聚合
- 把 `Guardian` 当作完整交易链容器
- 只按 `component` 浏览，不按 `trace` 浏览
- 无 `runtime_node` 的单机思维

## 14. 实施顺序

建议顺序：

1. 公共日志 SDK
   - `runtime_event_logger`
   - `trace_id/intent_id`
   - 异步 JSONL
2. 先接核心五组件
   - `xt_producer`
   - `xt_consumer`
   - `guardian_strategy`
   - `order_submit`
   - `broker_gateway`
3. 再接执行尾部与风控
   - `puppet_gateway`
   - `position_gate`
   - `position_worker`
   - `xt_report_ingest`
   - `order_reconcile`
4. 再接 `TPSL`
5. 最后接 Web UI

## 15. 验收标准

首期验收通过条件：

1. 能从 `strategy_monitor/guardian` 生成 `trace_id`
2. 一笔 Guardian 买单能展示完整跨组件链路
3. 一笔 Guardian 卖单能展示盈利切片/减仓分支
4. 一笔 TPSL 触发单能并入同一执行链
5. Producer/Consumer 健康卡片能显示关键指标
6. 单机环境能区分 `host:*` 与 `docker:*`
7. API 能按 `trace_id/request_id/internal_order_id/symbol/time range` 过滤
8. raw JSONL tail 仍可用

## 16. 风险

主要风险：

- 当前链路还没有统一 ID 传播
- 业务代码分散，接入点多
- 若直接复用旧前端聚合逻辑，会重新形成不可维护的大组件
- `Guardian` 已经偏离旧仓语义，边界必须重新定义
- 宿主机与 Docker 混合运行时，必须显式标注 `runtime_node`

## 17. 结论

本设计采用：

- `JSONL + 后端聚合 + Web UI`

并明确以下原则：

- 链路追踪优先，健康看板同步提供
- `Guardian` 仅作为策略链起点，不再承担完整交易链
- 所有观测能力必须旁路、异步、可丢弃
- 日志系统绝不允许阻塞下单或主业务线程
