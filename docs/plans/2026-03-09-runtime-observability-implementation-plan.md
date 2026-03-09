# Runtime Observability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 FreshQuant 实盘核心链路落地“旁路、异步、不可阻塞主链路”的运行观测能力，首期包含链路追踪、健康看板和 raw JSONL 调试入口。

**Architecture:** 运行时只做结构化 JSONL 异步落盘，所有 trace 聚合和健康统计均在后端读路径完成，前端只消费 `/api/runtime/*` 聚合接口。`Guardian` 仅记录策略判断链，订单域、仓位域、执行域分别记录自己的节点，最终通过 `trace_id / intent_id / request_id / internal_order_id` 进行串联。

**Tech Stack:** Python 3.12, Flask Blueprint, Vue 3, Element Plus, JSONL, pytest, node --test

---

### Task 1: 搭建运行观测公共包骨架

**Files:**
- Create: `freshquant/runtime_observability/__init__.py`
- Create: `freshquant/runtime_observability/schema.py`
- Create: `freshquant/runtime_observability/ids.py`
- Create: `freshquant/runtime_observability/node_catalog.py`
- Test: `freshquant/tests/test_runtime_observability_schema.py`

**Step 1: Write the failing test**

```python
from freshquant.runtime_observability.schema import normalize_event


def test_normalize_event_sets_required_defaults():
    event = normalize_event({"component": "guardian_strategy", "node": "receive_signal"})
    assert event["event_type"] == "trace_step"
    assert event["status"] == "info"
    assert event["component"] == "guardian_strategy"
    assert event["node"] == "receive_signal"
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_observability_schema.py::test_normalize_event_sets_required_defaults -q`
Expected: FAIL with import error or missing function

**Step 3: Write minimal implementation**

```python
def normalize_event(raw):
    event = dict(raw or {})
    event.setdefault("event_type", "trace_step")
    event.setdefault("status", "info")
    event.setdefault("message", "")
    event.setdefault("reason_code", "")
    return event
```

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_observability_schema.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/runtime_observability/__init__.py freshquant/runtime_observability/schema.py freshquant/runtime_observability/ids.py freshquant/runtime_observability/node_catalog.py freshquant/tests/test_runtime_observability_schema.py
git commit -m "feat: 初始化运行观测公共包骨架"
```

### Task 2: 实现绝不阻塞主链路的异步 JSONL logger

**Files:**
- Create: `freshquant/runtime_observability/logger.py`
- Test: `freshquant/tests/test_runtime_observability_logger.py`

**Step 1: Write the failing test**

```python
from freshquant.runtime_observability.logger import RuntimeEventLogger


def test_emit_drops_when_queue_full(tmp_path):
    logger = RuntimeEventLogger("guardian_strategy", root_dir=tmp_path, queue_maxsize=1)
    assert logger.emit({"node": "receive_signal"}) is True
    logger._queue.put_nowait({"node": "occupied"})
    assert logger.emit({"node": "timing_check"}) is False
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_observability_logger.py::test_emit_drops_when_queue_full -q`
Expected: FAIL with import error or missing class

**Step 3: Write minimal implementation**

```python
class RuntimeEventLogger:
    def emit(self, event):
        try:
            self._queue.put_nowait(normalize_event(event))
            return True
        except queue.Full:
            self._dropped += 1
            return False
        except Exception:
            return False
```

要求同时实现：

- 有界队列
- 后台写线程
- 目录自动创建
- 写失败吞掉异常
- `snapshot()` 返回 `queue_size / dropped / written / path`

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_observability_logger.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/runtime_observability/logger.py freshquant/tests/test_runtime_observability_logger.py
git commit -m "feat: 添加非阻塞运行观测 JSONL logger"
```

### Task 3: 实现 ID 传播与 runtime_node 解析

**Files:**
- Modify: `freshquant/runtime_observability/ids.py`
- Modify: `freshquant/runtime_observability/schema.py`
- Create: `freshquant/runtime_observability/runtime_node.py`
- Test: `freshquant/tests/test_runtime_observability_ids.py`

**Step 1: Write the failing test**

```python
from freshquant.runtime_observability.ids import new_trace_id, new_intent_id


def test_new_trace_and_intent_ids_have_expected_prefixes():
    assert new_trace_id().startswith("trc_")
    assert new_intent_id().startswith("int_")
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_observability_ids.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
def new_trace_id():
    return f"trc_{uuid.uuid4().hex[:12]}"


def new_intent_id():
    return f"int_{uuid.uuid4().hex[:12]}"
```

同时补齐：

- `resolve_runtime_node()`，优先读取显式配置，其次按宿主机/容器环境推断
- `normalize_event()` 自动补齐 `runtime_node`

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_observability_ids.py freshquant/tests/test_runtime_observability_schema.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/runtime_observability/ids.py freshquant/runtime_observability/runtime_node.py freshquant/runtime_observability/schema.py freshquant/tests/test_runtime_observability_ids.py
git commit -m "feat: 添加运行观测 ID 与 runtime_node 解析"
```

### Task 4: 先做后端 trace/health 聚合器，不把规则堆到前端

**Files:**
- Create: `freshquant/runtime_observability/assembler.py`
- Create: `freshquant/runtime_observability/health.py`
- Test: `freshquant/tests/test_runtime_observability_assembler.py`
- Test: `freshquant/tests/test_runtime_observability_health.py`

**Step 1: Write the failing test**

```python
from freshquant.runtime_observability.assembler import assemble_traces


def test_assemble_traces_groups_by_trace_id():
    events = [
        {"trace_id": "trc_1", "component": "guardian_strategy", "node": "receive_signal", "ts": "2026-03-09T10:00:00+08:00"},
        {"trace_id": "trc_1", "component": "order_submit", "node": "tracking_create", "ts": "2026-03-09T10:00:01+08:00"},
    ]
    traces = assemble_traces(events)
    assert len(traces) == 1
    assert traces[0]["trace_id"] == "trc_1"
    assert len(traces[0]["steps"]) == 2
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_observability_assembler.py::test_assemble_traces_groups_by_trace_id -q`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
def assemble_traces(events):
    groups = {}
    for event in events:
        trace_id = str(event.get("trace_id") or "").strip()
        if not trace_id:
            continue
        groups.setdefault(trace_id, []).append(event)
    return [{"trace_id": k, "steps": sorted(v, key=_sort_ts)} for k, v in groups.items()]
```

同时实现：

- `assemble_traces()` 支持 `trace_id / request_id / internal_order_id` 三种入口聚合
- `build_health_summary()` 只消费 `heartbeat` 和 `metric_snapshot`
- 规则全部写成纯函数，禁止依赖 Flask request

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_observability_assembler.py freshquant/tests/test_runtime_observability_health.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/runtime_observability/assembler.py freshquant/runtime_observability/health.py freshquant/tests/test_runtime_observability_assembler.py freshquant/tests/test_runtime_observability_health.py
git commit -m "feat: 添加运行观测 trace 与 health 聚合器"
```

### Task 5: 提供 Flask 只读接口并挂到 api_server

**Files:**
- Create: `freshquant/rear/runtime/__init__.py`
- Create: `freshquant/rear/runtime/routes.py`
- Modify: `freshquant/rear/api_server.py`
- Test: `freshquant/tests/test_runtime_observability_routes.py`

**Step 1: Write the failing test**

```python
def test_runtime_components_route(client):
    resp = client.get("/api/runtime/components")
    assert resp.status_code == 200
    assert "components" in resp.get_json()
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_observability_routes.py::test_runtime_components_route -q`
Expected: FAIL with 404

**Step 3: Write minimal implementation**

```python
runtime_bp = Blueprint("runtime", __name__, url_prefix="/api/runtime")


@runtime_bp.get("/components")
def list_components():
    return jsonify({"components": []})
```

同时完成：

- `GET /api/runtime/components`
- `GET /api/runtime/health/summary`
- `GET /api/runtime/traces`
- `GET /api/runtime/traces/<trace_id>`
- `GET /api/runtime/events`
- `GET /api/runtime/raw-files/*`
- 在 `create_app()` 里注册新蓝图

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_observability_routes.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/rear/runtime/__init__.py freshquant/rear/runtime/routes.py freshquant/rear/api_server.py freshquant/tests/test_runtime_observability_routes.py
git commit -m "feat: 添加运行观测后端只读接口"
```

### Task 6: 接入 Guardian、订单受理、仓位门禁

**Files:**
- Modify: `freshquant/strategy/guardian.py`
- Modify: `freshquant/order_management/submit/guardian.py`
- Modify: `freshquant/order_management/submit/service.py`
- Modify: `freshquant/position_management/service.py`
- Test: `freshquant/tests/test_guardian_runtime_observability.py`
- Test: `freshquant/tests/test_order_submit_runtime_observability.py`
- Test: `freshquant/tests/test_position_management_runtime_observability.py`

**Step 1: Write the failing tests**

```python
def test_guardian_submit_intent_emits_trace_step():
    events = []
    logger = FakeRuntimeLogger(events)
    strategy = StrategyGuardian(runtime_logger=logger)
    # 构造最小 buy signal
    strategy.on_signal(signal)
    assert any(e["component"] == "guardian_strategy" and e["node"] == "submit_intent" for e in events)
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_guardian_runtime_observability.py freshquant/tests/test_order_submit_runtime_observability.py freshquant/tests/test_position_management_runtime_observability.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**

关键实现要求：

- `Guardian` 只发自己的节点：
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
- `submit_guardian_order()` 负责把 `trace_id/intent_id` 继续传给订单域
- `OrderSubmitService.submit_order()` 发：
  - `intent_normalize`
  - `credit_mode_resolve`
  - `tracking_create`
  - `queue_payload_build`
- `PositionManagementService.evaluate_strategy_order()` 发：
  - `state_load`
  - `freshness_check`
  - `policy_eval`
  - `decision_record`

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_guardian_runtime_observability.py freshquant/tests/test_order_submit_runtime_observability.py freshquant/tests/test_position_management_runtime_observability.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/strategy/guardian.py freshquant/order_management/submit/guardian.py freshquant/order_management/submit/service.py freshquant/position_management/service.py freshquant/tests/test_guardian_runtime_observability.py freshquant/tests/test_order_submit_runtime_observability.py freshquant/tests/test_position_management_runtime_observability.py
git commit -m "feat: 接入策略与订单域运行观测事件"
```

### Task 7: 接入 Producer/Consumer，先打通健康看板主数据源

**Files:**
- Modify: `freshquant/market_data/xtdata/market_producer.py`
- Modify: `freshquant/market_data/xtdata/strategy_consumer.py`
- Test: `freshquant/tests/test_xtdata_runtime_observability.py`

**Step 1: Write the failing test**

```python
def test_producer_heartbeat_emits_metric_snapshot():
    events = []
    logger = FakeRuntimeLogger(events)
    emit_producer_heartbeat(runtime_logger=logger, rx_age_s=1.2, codes=20)
    assert any(e["component"] == "xt_producer" and e["event_type"] == "heartbeat" for e in events)
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_xtdata_runtime_observability.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**

要求：

- Producer 发：
  - `bootstrap`
  - `config_resolve`
  - `xtdata_connect`
  - `subscription_load`
  - `tick_pump`
  - `minute_bar_build`
  - `redis_enqueue`
  - `heartbeat`
  - `exception`
- Consumer 发：
  - `redis_pop`
  - `batch_group`
  - `fullcalc_run`
  - `cache_write`
  - `pubsub_publish`
  - `heartbeat`
  - `exception`
- 将旧 `BarMonitorLogger` 语义映射到新的 schema，而不是双系统长期并存

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_xtdata_runtime_observability.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/market_data/xtdata/market_producer.py freshquant/market_data/xtdata/strategy_consumer.py freshquant/tests/test_xtdata_runtime_observability.py
git commit -m "feat: 接入 producer consumer 运行观测"
```

### Task 8: 接入 Broker/Puppet、XT 回报、对账链

**Files:**
- Modify: `morningglory/fqxtrade/fqxtrade/xtquant/broker.py`
- Modify: `morningglory/fqxtrade/fqxtrade/xtquant/puppet.py`
- Modify: `freshquant/order_management/ingest/xt_reports.py`
- Modify: `freshquant/order_management/reconcile/service.py`
- Test: `freshquant/tests/test_broker_runtime_observability.py`
- Test: `freshquant/tests/test_puppet_runtime_observability.py`
- Test: `freshquant/tests/test_xt_reports_runtime_observability.py`

**Step 1: Write the failing tests**

```python
def test_broker_queue_consume_emits_trace_step():
    events = []
    broker = make_broker(runtime_logger=FakeRuntimeLogger(events))
    broker._emit_queue_consume(fake_payload)
    assert any(e["component"] == "broker_gateway" and e["node"] == "queue_consume" for e in events)
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_broker_runtime_observability.py freshquant/tests/test_puppet_runtime_observability.py freshquant/tests/test_xt_reports_runtime_observability.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**

要求：

- `broker_gateway` 发：
  - `queue_consume`
  - `action_dispatch`
  - `submit_result`
  - `order_callback`
  - `trade_callback`
  - `watchdog`
- `puppet_gateway` 发：
  - `submit_prepare`
  - `submit_decision`
  - `submit_result`
- `xt_report_ingest` 发：
  - `report_receive`
  - `order_match`
  - `trade_match`
- `order_reconcile` 发：
  - `internal_match`
  - `externalize`
  - `projection_update`

确保把 `request_id/internal_order_id` 一路补齐，不得退化成只能看 `req_id` 字符串。

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_broker_runtime_observability.py freshquant/tests/test_puppet_runtime_observability.py freshquant/tests/test_xt_reports_runtime_observability.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqxtrade/fqxtrade/xtquant/broker.py morningglory/fqxtrade/fqxtrade/xtquant/puppet.py freshquant/order_management/ingest/xt_reports.py freshquant/order_management/reconcile/service.py freshquant/tests/test_broker_runtime_observability.py freshquant/tests/test_puppet_runtime_observability.py freshquant/tests/test_xt_reports_runtime_observability.py
git commit -m "feat: 接入执行网关与回报链运行观测"
```

### Task 9: 接入 TPSL 与前端运行观测页

**Files:**
- Modify: `freshquant/tpsl/tick_listener.py`
- Modify: `freshquant/tpsl/consumer.py`
- Create: `morningglory/fqwebui/src/api/runtimeObservabilityApi.js`
- Create: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Modify: `morningglory/fqwebui/src/router/index.js`
- Modify: `morningglory/fqwebui/src/views/MyHeader.vue`
- Test: `freshquant/tests/test_tpsl_runtime_observability.py`
- Test: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: Write the failing tests**

```python
def test_tpsl_submit_intent_emits_trace_step():
    events = []
    consumer = make_tpsl_consumer(runtime_logger=FakeRuntimeLogger(events))
    consumer.handle_tick(fake_tick)
    assert any(e["component"] == "tpsl_worker" and e["node"] == "submit_intent" for e in events)
```

```js
test('runtime observability view renders trace list and health cards', async () => {
  const wrapper = mount(RuntimeObservability)
  expect(wrapper.text()).toContain('运行观测')
})
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_tpsl_runtime_observability.py -q`
Expected: FAIL

Run: `node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs`
Expected: FAIL

**Step 3: Write minimal implementation**

要求：

- TPSL 发：
  - `tick_match`
  - `profile_load`
  - `trigger_eval`
  - `batch_create`
  - `submit_intent`
- 新前端页至少包含：
  - 健康卡片
  - trace 列表
  - trace 详情
  - raw records 抽屉
- 通过头部导航进入新页面

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_tpsl_runtime_observability.py -q`
Expected: PASS

Run: `node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs`
Expected: PASS

Run: `npm run build`
Expected: build success

**Step 5: Commit**

```bash
git add freshquant/tpsl/tick_listener.py freshquant/tpsl/consumer.py morningglory/fqwebui/src/api/runtimeObservabilityApi.js morningglory/fqwebui/src/views/RuntimeObservability.vue morningglory/fqwebui/src/router/index.js morningglory/fqwebui/src/views/MyHeader.vue freshquant/tests/test_tpsl_runtime_observability.py morningglory/fqwebui/src/views/runtime-observability.test.mjs
git commit -m "feat: 添加 TPSL 与运行观测页面"
```

### Task 10: 完整回归、文档补充与治理收口

**Files:**
- Modify: `docs/agent/项目目标与代码现状调研.md`
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`
- Modify: `docs/agent/index.md`

**Step 1: Write the documentation updates**

需要补充：

- 新运行观测模块入口
- `/api/runtime/*` 对外接口
- Web UI 页面入口
- “日志绝不阻塞主链路”的非功能约束
- 与旧 `system_logs` 的差异

**Step 2: Run targeted verification**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_observability_schema.py freshquant/tests/test_runtime_observability_logger.py freshquant/tests/test_runtime_observability_assembler.py freshquant/tests/test_runtime_observability_health.py freshquant/tests/test_runtime_observability_routes.py freshquant/tests/test_guardian_runtime_observability.py freshquant/tests/test_order_submit_runtime_observability.py freshquant/tests/test_position_management_runtime_observability.py freshquant/tests/test_xtdata_runtime_observability.py freshquant/tests/test_broker_runtime_observability.py freshquant/tests/test_puppet_runtime_observability.py freshquant/tests/test_xt_reports_runtime_observability.py freshquant/tests/test_tpsl_runtime_observability.py -q`
Expected: PASS

**Step 3: Run frontend verification**

Run: `node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs`
Expected: PASS

Run: `npm run build`
Expected: build success

**Step 4: Run governance-adjacent checks**

Run: `git status --short`
Expected: only intended files changed

Run: `py -3.12 -m py_compile freshquant/runtime_observability/*.py freshquant/rear/runtime/routes.py`
Expected: no output

**Step 5: Commit**

```bash
git add docs/agent/项目目标与代码现状调研.md docs/migration/progress.md docs/migration/breaking-changes.md docs/agent/index.md
git commit -m "docs: 更新运行观测模块文档与迁移记录"
```
