# Stock Control Signal Lists Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 清理废弃 `poll` 模式，并让 `/stock-control` 同时展示 `must_pools` 买入信号和 `stock_pools` 模型信号。

**Architecture:** 后端为 Guardian 信号和模型信号分别提供清晰查询接口，前端保留原 Guardian 列表组件，同时新增专用模型信号列表组件，避免字段语义混用。实现过程严格按 TDD，先补失败测试，再做最小实现，最后同步文档。

**Tech Stack:** Python, Flask, pytest, Vue 3, axios, @tanstack/vue-query

---

### Task 1: 设计冻结与文档落盘

**Files:**
- Create: `docs/plans/2026-03-15-stock-control-signal-lists-design.md`
- Create: `docs/plans/2026-03-15-stock-control-signal-lists.md`

**Step 1: 确认设计文档已写入**

检查：
- `docs/plans/2026-03-15-stock-control-signal-lists-design.md`
- `docs/plans/2026-03-15-stock-control-signal-lists.md`

**Step 2: 提交文档**

Run: `git add docs/plans/2026-03-15-stock-control-signal-lists-design.md docs/plans/2026-03-15-stock-control-signal-lists.md`

Run: `git commit -m "docs: add stock control signal list design"`

### Task 2: 为后端新查询语义写失败测试

**Files:**
- Modify: `freshquant/tests/test_stock_pool_service.py`
- Test: `freshquant/tests/test_stock_pool_service.py`

**Step 1: 写 `must_pool_buys` 的失败测试**

覆盖：
- 只返回 `BUY_LONG`
- 只返回 `is_holding=False`
- 只返回当前存在于 `must_pool` 的 code

**Step 2: 运行失败测试**

Run: `D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_stock_pool_service.py -q`

Expected: 新增用例失败，提示查询语义未实现。

**Step 3: 写 `realtime_screen_multi_period` 查询的失败测试**

覆盖：
- 排序
- 时间字符串格式化
- 8 个字段返回

**Step 4: 再次运行失败测试**

Run: `D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_stock_pool_service.py -q`

Expected: 新增模型信号查询用例失败。

### Task 3: 实现后端查询与路由

**Files:**
- Modify: `freshquant/stock_service.py`
- Modify: `freshquant/rear/stock/routes.py`

**Step 1: 最小实现 `must_pool_buys` 查询**

在 `get_stock_signal_list()` 中增加新分支，读取 `must_pool` 当前 code 集合并过滤 `stock_signals`。

**Step 2: 运行后端测试确认通过**

Run: `D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_stock_pool_service.py -q`

Expected: `must_pool_buys` 相关测试通过，其余保持绿。

**Step 3: 最小实现 `realtime_screen_multi_period` 查询与接口**

- 在 `stock_service.py` 新增读取函数
- 在 `routes.py` 新增 API

**Step 4: 再次运行后端测试确认通过**

Run: `D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_stock_pool_service.py freshquant/tests/test_guardian_buy_grid_routes.py freshquant/tests/test_stock_position_list_route.py -q`

Expected: 新老接口相关测试全绿。

### Task 4: 为废弃 poll 写失败测试并删除

**Files:**
- Modify: `freshquant/tests/test_guardian_buy_grid_cli.py`
- Modify: `freshquant/signal/astock/job/monitor_stock_zh_a_min.py`

**Step 1: 写 CLI 失败测试**

覆盖：
- 不再接受 `--mode poll`
- 默认/唯一正式口径为 event

**Step 2: 运行失败测试**

Run: `D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_guardian_buy_grid_cli.py -q`

Expected: 因 `poll` 仍存在而失败。

**Step 3: 删除 `poll` 相关代码和选项**

保留 event 主路径，清理旧分支。

**Step 4: 运行 CLI 测试确认通过**

Run: `D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_guardian_buy_grid_cli.py -q`

Expected: 全绿。

### Task 5: 为前端列表改动写失败测试

**Files:**
- Modify: `morningglory/fqwebui/tests/`
- Modify: `morningglory/fqwebui/src/views/StockControl.vue`
- Modify: `morningglory/fqwebui/src/api/stockApi.js`

**Step 1: 写失败测试**

覆盖：
- 左侧标题变为“must_pools买入信号”
- 页面存在“stock_pools模型信号”
- 模型信号列表请求新 API

**Step 2: 运行前端失败测试**

Run: `npm test -- --runInBand`

Expected: 新增断言失败。

### Task 6: 实现前端展示

**Files:**
- Modify: `morningglory/fqwebui/src/views/StockControl.vue`
- Modify: `morningglory/fqwebui/src/api/stockApi.js`
- Create: `morningglory/fqwebui/src/views/ModelSignalList.vue`

**Step 1: 保持 `SignalList` 用于 Guardian 信号**

将左侧查询参数改为 `must_pool_buys`，标题改为“must_pools买入信号”。

**Step 2: 新增 `ModelSignalList`**

展示字段：
- `datetime`
- `created_at`
- `code`
- `name`
- `period`
- `model`
- `close`
- `stop_loss_price`
- `source`

**Step 3: 运行前端测试确认通过**

Run: `npm test -- --runInBand`

Expected: 新增前端测试通过。

### Task 7: 同步当前文档

**Files:**
- Modify: `docs/current/runtime.md`
- Modify: `docs/current/modules/strategy-guardian.md`
- Modify: `docs/current/modules/kline-webui.md`
- Modify: `docs/current/reference/stock-pools-and-positions.md`

**Step 1: 更新运行与页面口径**

写明：
- `poll` 已废弃
- `/stock-control` 左列是 `must_pools买入信号`
- 页面新增 `stock_pools模型信号`

**Step 2: 运行最小文档相关验证**

Run: `D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_xtdata_mode_defaults.py -q`

Expected: 相关系统口径测试仍通过。

### Task 8: 全量验证

**Files:**
- Modify: 本次所有改动文件

**Step 1: 运行后端回归**

Run: `D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests -q`

Expected: 全绿。

**Step 2: 运行前端相关测试**

Run: `npm test -- --runInBand`

Expected: 目标前端测试通过。

**Step 3: 检查工作树**

Run: `git status --short`

Expected: 仅包含本次改动文件。

