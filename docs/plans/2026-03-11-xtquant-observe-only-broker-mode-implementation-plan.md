# XTQuant Observe-Only Broker 模式 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为完整交易链增加 `xtquant.value.broker_submit_mode=observe_only`，让 Guardian/Position/OrderSubmit/Broker 全链路运行并可观测，但 `buy / sell / cancel` 全部不与券商交互，也不污染真实持仓、真实仓位和真实 TPSL 事实。

**Architecture:** 通过 Mongo `params.xtquant` 增加 `broker_submit_mode`，broker 在启动时解析执行模式；`normal` 保持真实提交；`observe_only` 只消费队列、写订单事件与运行观测，订单落到 `BROKER_BYPASSED`，不初始化真实券商执行路径、不做同步、不走 XT 回报链。宿主机 Supervisor 同时补齐 `guardian / position_management / tpsl` 三个常驻进程，形成完整交易链运行面。

**Tech Stack:** Python 3.12、PyMongo、Redis、XTQuant broker worker、Go-Supervisor、pytest

---

### Task 1: 配置解析 helper 与参数回归测试

**Files:**
- Modify: `morningglory/fqxtrade/fqxtrade/xtquant/account.py`
- Modify: `freshquant/tests/test_xtquant_account_config.py`

**Step 1: 增加 submit mode 解析 helper**

- 新增 `resolve_broker_submit_mode()` 或等价 helper
- 读取 `freshquant.params(code="xtquant").value.broker_submit_mode`
- 缺失 / 空值 / 非法值统一回落到 `normal`

**Step 2: 写回归测试**

- 缺失字段 -> `normal`
- `observe_only` -> `observe_only`
- 非法值 -> `normal`

**Step 3: 运行聚焦测试**

Run: `py -3.12 -m pytest freshquant/tests/test_xtquant_account_config.py -q`

Expected: PASS

### Task 2: 扩展订单状态机与执行桥接

**Files:**
- Modify: `freshquant/order_management/tracking/state_machine.py`
- Modify: `freshquant/order_management/tracking/service.py`
- Modify: `freshquant/order_management/submit/execution_bridge.py`
- Modify: `freshquant/tests/test_order_management_execution_bridge.py`
- Modify: `freshquant/tests/test_order_management_tracking_service.py`

**Step 1: 定义新状态与事件**

- 增加 `BROKER_BYPASSED`
- 增加 `broker_submit_bypassed`
- 增加 `broker_cancel_bypassed`

**Step 2: 收口状态迁移**

- `ACCEPTED / QUEUED / SUBMITTING` 在演练模式下可推进到 `BROKER_BYPASSED`
- `BROKER_BYPASSED` 不应再被当成 `SUBMITTED`

**Step 3: 写失败测试后实现**

- 断言演练模式下 submit execution 最终状态是 `BROKER_BYPASSED`
- 断言 cancel bypass 不会推进到真实撤单状态

**Step 4: 运行聚焦测试**

Run: `py -3.12 -m pytest freshquant/tests/test_order_management_execution_bridge.py freshquant/tests/test_order_management_tracking_service.py -q`

Expected: PASS

### Task 3: Broker observe_only 分支与运行观测

**Files:**
- Modify: `morningglory/fqxtrade/fqxtrade/xtquant/broker.py`
- Modify: `freshquant/tests/test_xtquant_runtime_observability.py`
- Modify: `freshquant/tests/test_order_submit_runtime_observability.py`

**Step 1: 增加 broker 执行模式分支**

- broker 启动时解析 `broker_submit_mode`
- `normal` 保持现状
- `observe_only`：
  - 不初始化真实券商执行路径
  - 消费订单队列后直接写 bypass 事件
  - 不调用 `puppet.buy / puppet.sell / cancel_order_stock`
  - 不执行 `sync_positions / sync_orders / sync_trades / sync_summary`

**Step 2: 增加运行观测节点**

- `broker_gateway.execution_bypassed`
- payload 至少包含：
  - `broker_submit_mode`
  - `reason`
  - `action`
  - `symbol`
  - `request_id`
  - `internal_order_id`

**Step 3: 写聚焦测试**

- 断言 observe_only 下不会触发券商调用
- 断言会写入 bypass runtime 事件

**Step 4: 运行聚焦测试**

Run: `py -3.12 -m pytest freshquant/tests/test_xtquant_runtime_observability.py freshquant/tests/test_order_submit_runtime_observability.py -q`

Expected: PASS

### Task 4: 宿主机完整交易链 Supervisor 配置

**Files:**
- Modify: `docs/配置文件模板/supervisord.fqnext.example.conf`
- Modify: `D:/fqpack/config/supervisord.fqnext.conf`
- Reference: `freshquant/signal/astock/job/monitor_stock_zh_a_min.py`
- Reference: `freshquant/position_management/worker.py`
- Reference: `freshquant/tpsl/tick_listener.py`

**Step 1: 补齐常驻进程**

- 新增 `guardian --mode event`
- 新增 `position_management.worker`
- 新增 `tpsl.tick_listener`

**Step 2: 保持现有进程不变**

- 继续保留 `xtdata producer / consumer / broker / credit_subjects.worker / adj_refresh_worker`
- 不新增 `order_management.worker`

**Step 3: 同步运维要求**

- `monitor.xtdata.mode = guardian_1m`
- `xtquant.broker_submit_mode = observe_only` 时修改参数后需要重启 `fqnext_xtquant_broker`

### Task 5: 文档与迁移记录

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `docs/agent/项目目标与代码现状调研.md`（若需要补充完整交易链运行面说明）
- Modify: `docs/agent/旧仓库freshquant-重点迁移模块调研.md`（若需要补充 broker observe_only 迁移说明）

**Step 1: 更新进度表**

- 新增 RFC 0030 行
- 状态标记为 `Review`
- 备注写清参数位置、完整链路模式与 `BROKER_BYPASSED` 语义

**Step 2: 必要时补充 agent 调研文档**

- 让后续 agent 清楚知道：
  - 订单管理主链不是独立 Supervisor worker
  - 完整交易链模式需要 `guardian / position_management / tpsl`
  - `observe_only` 只保证 broker 前后链路可观测，不生成 XT 回报

### Task 6: 联机验收

**Files:**
- None

**Step 1: 设置 Mongo 参数**

- `freshquant.params(code="monitor").value.xtdata.mode = guardian_1m`
- `freshquant.params(code="xtquant").value.broker_submit_mode = observe_only`

**Step 2: 重启宿主机 Supervisor 相关进程**

Run: `supervisorctl -c D:/fqpack/config/supervisord.fqnext.conf reread`
Run: `supervisorctl -c D:/fqpack/config/supervisord.fqnext.conf update`
Run: `supervisorctl -c D:/fqpack/config/supervisord.fqnext.conf restart fqnext_xtquant_broker`

Expected:
- `guardian / position_management / tpsl / broker` 均为 `RUNNING`

**Step 3: 触发一笔策略单并验收**

Expected:
- `/runtime-observability` 中 trace 能看到 `guardian_strategy -> position_gate -> order_submit -> broker_gateway.execution_bypassed`
- Mongo 订单状态为 `BROKER_BYPASSED`
- 券商终端没有真实委托
- `xt_report_ingest / order_reconcile` 没有该笔单的新回报推进
- 真实持仓、真实仓位、真实 TPSL 状态不变

### Task 7: 回归测试集合

Run: `py -3.12 -m pytest freshquant/tests/test_xtquant_account_config.py freshquant/tests/test_order_management_execution_bridge.py freshquant/tests/test_order_management_tracking_service.py freshquant/tests/test_xtquant_runtime_observability.py freshquant/tests/test_order_submit_runtime_observability.py -q`

Expected: PASS
