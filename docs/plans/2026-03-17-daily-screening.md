# Daily Screening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增一个“每日选股”前端工作台，支持通过 SSE 实时发起并查看 `CLXS` / `chanlun` 每日选股扫描，同时把页面来源稳定落库到共享 `stock_pre_pools`。

**Architecture:** 后端新增 daily-screening 控制层，负责 schema、run 创建、SSE 事件流和页面来源 `pre_pool` 查询；策略层补可选回调以输出实时事件；`save_a_stock_pre_pools()` 补 `remark` 与按 `code + category + remark` 的隔离 upsert。前端新增 `/daily-screening` 工作台页面，按后端 schema 动态渲染配置，实时展示扫描流、本次结果和已落库 `pre_pool`。

**Tech Stack:** Flask Blueprint、Python thread/queue、SSE、Mongo、Vue 3、Element Plus、Node test runner、pytest

---

### Task 1: 先锁定 stock_pre_pools remark 写入与隔离 upsert

**Files:**
- Modify: `freshquant/signal/a_stock_common.py`
- Modify: `freshquant/tests/test_stock_pool_service.py`
- Test: `freshquant/tests/test_stock_pool_service.py`

**Step 1: Write the failing test**

在 `freshquant/tests/test_stock_pool_service.py` 新增两个测试：

- `save_a_stock_pre_pools(..., remark="daily-screening:clxs")` 会把顶层 `remark` 写入结果文档
- 当传入 remark 时，相同 `code + category` 但不同 `remark` 可以共存，不会互相覆盖

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_stock_pool_service.py -q`
Expected: FAIL，说明 `remark` 尚未写入或 query 仍只按 `code + category`。

**Step 3: Write minimal implementation**

修改 `save_a_stock_pre_pools()`：

- 新增 `remark=None`
- remark 非空时：
  - 写入顶层 `remark`
  - `find_one` / `find_one_and_update` query 使用 `code + category + remark`
- remark 为空时保持原行为

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_stock_pool_service.py -q`
Expected: PASS

### Task 2: 给 CLXS 和 chanlun 策略补运行回调

**Files:**
- Modify: `freshquant/screening/strategies/clxs.py`
- Modify: `freshquant/screening/strategies/chanlun_service.py`
- Create: `freshquant/tests/test_daily_screening_strategy_hooks.py`
- Test: `freshquant/tests/test_daily_screening_strategy_hooks.py`

**Step 1: Write the failing test**

新增测试锁定：

- `ClxsStrategy` 在扫描 universe、每只股票完成、每条有效结果产生时能触发可选回调
- `ChanlunServiceStrategy` 在加载输入股票、每只股票完成、每条有效结果产生时能触发可选回调
- 未传回调时旧行为不变

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_daily_screening_strategy_hooks.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**

为两个策略补最小可选 hooks：

- `on_universe`
- `on_stock_progress`
- `on_hit_raw`
- `on_result_accepted`
- `on_error`

只在传入时触发，CLI 默认路径不需要改调用方式。

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_daily_screening_strategy_hooks.py -q`
Expected: PASS

### Task 3: 锁定 daily-screening service 的 schema、参数校验和结果归一

**Files:**
- Create: `freshquant/daily_screening/service.py`
- Create: `freshquant/tests/test_daily_screening_service.py`
- Test: `freshquant/tests/test_daily_screening_service.py`

**Step 1: Write the failing test**

新增测试覆盖：

- `get_schema()` 返回 `clxs` / `chanlun` 模型及其字段
- `chanlun` 动态选项会带 `pre_pool_categories` 和 `pre_pool_remarks`
- `normalize_run_payload()` 会按模型校验参数并补默认值
- `build_pre_pool_record_context()` 会生成 `remark + extra` 上下文

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_daily_screening_service.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**

在 `freshquant/daily_screening/service.py` 实现：

- schema provider
- payload normalize / validate
- code/symbol resolve helper
- result -> persist context helper

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_daily_screening_service.py -q`
Expected: PASS

### Task 4: 锁定 run manager 与 SSE 事件流

**Files:**
- Create: `freshquant/daily_screening/session_store.py`
- Create: `freshquant/tests/test_daily_screening_session_store.py`
- Test: `freshquant/tests/test_daily_screening_session_store.py`

**Step 1: Write the failing test**

新增测试覆盖：

- 创建 run 后有 `scan_id`
- 事件写入后可按顺序读取
- 历史事件可回放
- completed 后状态稳定

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_daily_screening_session_store.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**

实现一个内存态 session store：

- `create_run()`
- `append_event()`
- `snapshot()`
- `iter_events()`

内部使用 `queue.Queue` + 历史数组。

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_daily_screening_session_store.py -q`
Expected: PASS

### Task 5: 先锁定 HTTP 路由与 SSE 输出

**Files:**
- Create: `freshquant/rear/daily_screening/routes.py`
- Modify: `freshquant/rear/api_server.py`
- Create: `freshquant/tests/test_daily_screening_routes.py`
- Test: `freshquant/tests/test_daily_screening_routes.py`

**Step 1: Write the failing test**

新增测试覆盖：

- `GET /api/daily-screening/schema`
- `POST /api/daily-screening/runs`
- `GET /api/daily-screening/runs/<scan_id>`
- `GET /api/daily-screening/pre-pools`
- `GET /api/daily-screening/runs/<scan_id>/stream`

SSE 路由测试至少断言：

- response mimetype 是 `text/event-stream`
- 输出包含 `event: started`

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_daily_screening_routes.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**

最小实现：

- blueprint
- schema route
- create run route
- snapshot route
- pre-pool query route
- SSE stream route
- 注册到 `api_server.py`

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_daily_screening_routes.py -q`
Expected: PASS

### Task 6: 接上真实策略执行和结果落库

**Files:**
- Modify: `freshquant/daily_screening/service.py`
- Modify: `freshquant/rear/daily_screening/routes.py`
- Create: `freshquant/tests/test_daily_screening_execution.py`
- Test: `freshquant/tests/test_daily_screening_execution.py`

**Step 1: Write the failing test**

新增测试锁定：

- `clxs` run 会生成 `started/progress/accepted/completed`
- `chanlun` run 会根据 `input_mode` 读取正确输入
- `save_pre_pools=true` 时会把 `remark` 和 `extra.screening_*` 写入 `stock_pre_pools`
- `save_signal` / `save_pools` 仅在 `chanlun` 且显式开启时落库

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_daily_screening_execution.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**

在 service 中：

- 启动后台线程
- 选择对应策略
- 注入 hooks，把策略事件转成 session events
- 对 accepted 结果执行页面落库
- 归一 summary

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_daily_screening_execution.py -q`
Expected: PASS

### Task 7: 先锁定前端 schema 驱动表单与 SSE 状态机

**Files:**
- Create: `morningglory/fqwebui/src/api/dailyScreeningApi.js`
- Create: `morningglory/fqwebui/src/views/dailyScreening.mjs`
- Create: `morningglory/fqwebui/src/views/dailyScreeningPage.mjs`
- Create: `morningglory/fqwebui/src/views/dailyScreening.test.mjs`
- Create: `morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`
- Test: `morningglory/fqwebui/src/views/dailyScreening.test.mjs`
- Test: `morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`

**Step 1: Write the failing test**

新增测试锁定：

- schema 返回后能正确生成动态字段
- `clxs` / `chanlun` 切换时字段正确显隐
- `chanlun.input_mode` 变化时分类/remark/code 字段正确显隐
- SSE 事件流可以驱动日志、摘要和结果表更新

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/dailyScreening.test.mjs morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`
Expected: FAIL

**Step 3: Write minimal implementation**

实现：

- `dailyScreeningApi.js`
- schema/form helper
- page state controller
- EventSource 事件处理 helper

先不写 `.vue`，先把状态和 schema 逻辑锁定。

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/dailyScreening.test.mjs morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`
Expected: PASS

### Task 8: 实现 Daily Screening 页面与导航

**Files:**
- Create: `morningglory/fqwebui/src/views/DailyScreening.vue`
- Modify: `morningglory/fqwebui/src/router/index.js`
- Modify: `morningglory/fqwebui/src/router/pageMeta.mjs`
- Modify: `morningglory/fqwebui/src/views/MyHeader.vue`
- Test: `morningglory/fqwebui/src/views/dailyScreening.test.mjs`
- Test: `morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`

**Step 1: Write the failing test**

补测试锁定：

- 新路由 `/daily-screening`
- Header 出现“每日选股”
- 页面源码包含 schema 动态字段和 SSE 状态区关键标记

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/dailyScreening.test.mjs morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`
Expected: FAIL

**Step 3: Write minimal implementation**

实现 `DailyScreening.vue`：

- 顶部摘要
- 左侧参数区
- 中间 SSE 日志区
- 右侧结果区
- 已落库 pre_pool 表格与动作

并补 router、page meta、MyHeader。

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/dailyScreening.test.mjs morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`
Expected: PASS

### Task 9: 同步 current docs

**Files:**
- Modify: `docs/current/overview.md`
- Modify: `docs/current/interfaces.md`
- Modify: `docs/current/architecture.md`
- Create: `docs/current/modules/daily-screening.md`
- Test: `py -3.12 -m pytest freshquant/tests/test_check_current_docs.py -q`（若仓库中已有 current docs 守卫）

**Step 1: Write the failing test**

若已有 docs guard，先运行它确认当前文档尚未覆盖新页面/接口。

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_check_current_docs.py -q`
Expected: FAIL 或当前文档缺新模块事实。

**Step 3: Write minimal implementation**

同步写入：

- 新模块职责、路由、接口
- SSE 与 `remark` 来源语义
- 页面和共享 `stock_pre_pools` 的边界

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_check_current_docs.py -q`
Expected: PASS

### Task 10: 完整验证

**Files:**
- No manual edits
- Test:
  - `py -3.12 -m pytest freshquant/tests/test_stock_pool_service.py freshquant/tests/test_daily_screening_strategy_hooks.py freshquant/tests/test_daily_screening_service.py freshquant/tests/test_daily_screening_session_store.py freshquant/tests/test_daily_screening_routes.py freshquant/tests/test_daily_screening_execution.py -q`
  - `node --test morningglory/fqwebui/src/views/dailyScreening.test.mjs morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`

**Step 1: Run targeted backend tests**

Run the backend command above and confirm all PASS.

**Step 2: Run targeted frontend tests**

Run the frontend command above and confirm all PASS.

**Step 3: Run any existing related regression tests**

至少补跑：

- `py -3.12 -m pytest freshquant/tests/test_stock_pool_service.py freshquant/tests/test_gantt_routes.py -q`

**Step 4: Inspect git diff**

Run:

```bash
git status --short
git diff --stat
```

确认只包含本次变更。
