# Gantt Shouban30 筛选结果落库 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 `/gantt/shouban30` 页面增加“保存当前筛选结果/单板块结果到预选池、同步 `30RYZT.blk`、预选池加入自选股、自选股加入 must_pool”的工作区能力，并把写入范围安全收敛到 `shouban30` 专用分类。

**Architecture:** 后端新增 `shouban30_pool_service` 作为页面工作区编排层，负责把当前页面结果映射到 `stock_pre_pools / stock_pools / must_pool`，并按 `extra.shouban30_order` 维护 `30RYZT.blk` 顺序。前端继续以盘后快照为读模型真相源，只在用户点击按钮时调用新增工作区写接口，并在 `pre_pool / stockpools` 标签页中管理这两个专用分类。

**Tech Stack:** Python 3.12、Flask、PyMongo、pytest、Vue 3、Element Plus、Node test runner、Vite build

---

## Task Checklist

- [x] Task 1: 为 `shouban30` 工作区服务写失败测试
- [x] Task 2: 实现工作区服务与 blk writer
- [x] Task 3: 暴露 `shouban30` 工作区 HTTP 接口
- [x] Task 4: 增加前端 API 与工作区状态 helper
- [x] Task 5: 改造 `/gantt/shouban30` 页面按钮与标签页
- [x] Task 6: 跑后端/前端回归与构建验证
- [x] Task 7: 更新迁移记录与 breaking change 说明

### Task 1: 为 `shouban30` 工作区服务写失败测试

**Files:**
- Create: `freshquant/tests/test_shouban30_pool_service.py`
- Reference: `freshquant/tests/test_stock_pool_service.py`

**Step 1: 写失败测试**

至少覆盖：

- `replace_pre_pool()` 只替换 `三十涨停Pro预选` 分类，不影响其他分类
- 保存顺序会落到 `extra.shouban30_order`
- `sync_pre_pool_to_blk()` 输出顺序与输入顺序一致
- `add_pre_pool_item_to_stock_pool()` 会写入 `三十涨停Pro自选`
- `add_stock_pool_item_to_must_pool()` 会按默认参数调用 `must_pool.import_pool`

**Step 2: 运行测试确认失败**

Run: `py -3.12 -m pytest freshquant/tests/test_shouban30_pool_service.py -q`

Expected:

- FAIL，因为 `shouban30_pool_service` 还不存在

### Task 2: 实现工作区服务与 blk writer

**Files:**
- Create: `freshquant/shouban30_pool_service.py`
- Reference: `freshquant/signal/a_stock_common.py`
- Reference: `freshquant/data/astock/must_pool.py`
- Reference: `freshquant/stock_service.py`

**Step 1: 写最小实现**

实现：

- `SHOUBAN30_PRE_POOL_CATEGORY = "三十涨停Pro预选"`
- `SHOUBAN30_STOCK_POOL_CATEGORY = "三十涨停Pro自选"`
- `SHOUBAN30_MUST_POOL_CATEGORY = "三十涨停Pro"`
- `replace_pre_pool(items, context)`
- `list_pre_pool()`
- `add_pre_pool_item_to_stock_pool(code6)`
- `delete_pre_pool_item(code6)`
- `list_stock_pool()`
- `add_stock_pool_item_to_must_pool(code6)`
- `delete_stock_pool_item(code6)`
- `sync_pre_pool_to_blk()`

blk writer 规则：

- 读取 `TDX_HOME`
- 输出到 `T0002/blocknew/30RYZT.blk`
- 上海代码前缀 `1`
- 深圳代码前缀 `0`
- 使用 GBK 编码

**Step 2: 运行聚焦测试**

Run: `py -3.12 -m pytest freshquant/tests/test_shouban30_pool_service.py -q`

Expected: PASS

### Task 3: 暴露 `shouban30` 工作区 HTTP 接口

**Files:**
- Modify: `freshquant/rear/gantt/routes.py`
- Modify: `freshquant/tests/test_gantt_routes.py`

**Step 1: 先补失败测试**

新增/扩展测试：

- `test_replace_shouban30_pre_pool_requires_items`
- `test_replace_shouban30_pre_pool_returns_blk_sync_meta`
- `test_list_shouban30_pre_pool_reads_workspace_items`
- `test_add_shouban30_pre_pool_item_to_stock_pool`
- `test_add_shouban30_stock_pool_item_to_must_pool`

**Step 2: 运行失败测试**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_routes.py -k "shouban30 and pool" -q`

Expected:

- FAIL，因为新路由还不存在

**Step 3: 写最小实现**

在 `gantt_bp` 下新增：

- `POST /shouban30/pre-pool/replace`
- `GET /shouban30/pre-pool`
- `POST /shouban30/pre-pool/add-to-stock-pools`
- `POST /shouban30/pre-pool/delete`
- `GET /shouban30/stock-pool`
- `POST /shouban30/stock-pool/add-to-must-pool`
- `POST /shouban30/stock-pool/delete`

要求：

- 参数错误返回 `400`
- `TDX_HOME` 缺失等运行错误返回 `500`
- 成功时统一返回 `{ data, meta? }`

**Step 4: 重新运行聚焦测试**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_routes.py -k "shouban30 and pool" -q`

Expected: PASS

### Task 4: 增加前端 API 与工作区状态 helper

**Files:**
- Modify: `morningglory/fqwebui/src/api/ganttShouban30.js`
- Create: `morningglory/fqwebui/src/views/shouban30PoolWorkspace.mjs`
- Create: `morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs`

**Step 1: 写失败测试**

`shouban30PoolWorkspace.test.mjs` 至少覆盖：

- 当前筛选结果到 `replace pre-pool` payload 的归一化
- 单板块保存时只保留当前板块标的
- `pre_pool` / `stockpools` 列表映射与行按钮文案

**Step 2: 运行失败测试**

Run: `node --test morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs`

Expected:

- FAIL，因为 helper 还不存在

**Step 3: 写最小实现**

在 `ganttShouban30.js` 增加：

- `replaceShouban30PrePool`
- `getShouban30PrePool`
- `addShouban30PrePoolToStockPool`
- `deleteShouban30PrePoolItem`
- `getShouban30StockPool`
- `addShouban30StockPoolToMustPool`
- `deleteShouban30StockPoolItem`

在 `shouban30PoolWorkspace.mjs` 增加：

- 请求 payload builder
- tab row mapper
- 行动作后的局部状态刷新 helper

**Step 4: 重新运行测试**

Run: `node --test morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs`

Expected: PASS

### Task 5: 改造 `/gantt/shouban30` 页面按钮与标签页

**Files:**
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Reference: `morningglory/fqwebui/src/views/shouban30StockFilters.mjs`
- Reference: `morningglory/fqwebui/src/views/shouban30Aggregation.mjs`

**Step 1: 写最小页面实现**

增加：

- 条件筛选按钮组后的 `筛选` 按钮
- 板块表格中的 `保存到 pre_pools` 操作列
- `pre_pool / stockpools` 标签页
- 标签页行按钮：
  - `加入 stockpools`
  - `删除`
  - `加入 must_pools`
  - `删除`

要求：

- 页面继续读取现有 `plates/stocks` 快照
- 点击保存时只提交当前可见行
- 保存成功后自动刷新工作区标签页
- 删除 `pre_pool` 后同步反映 blk 重写结果

**Step 2: 跑前端状态测试**

Run: `node --test morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs morningglory/fqwebui/src/views/shouban30StockFilters.test.mjs morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`

Expected: PASS

**Step 3: 跑前端构建**

Run: `npm --prefix morningglory/fqwebui run build`

Expected: PASS

### Task 6: 跑后端/前端回归与构建验证

**Files:**
- Test only

**Step 1: 跑后端聚焦回归**

Run: `py -3.12 -m pytest freshquant/tests/test_shouban30_pool_service.py freshquant/tests/test_stock_pool_service.py freshquant/tests/test_gantt_routes.py -q`

Expected: PASS

**Step 2: 跑前端聚焦回归**

Run: `node --test morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs morningglory/fqwebui/src/views/shouban30StockFilters.test.mjs morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`

Expected: PASS

**Step 3: 跑前端构建**

Run: `npm --prefix morningglory/fqwebui run build`

Expected: PASS

### Task 7: 更新迁移记录与 breaking change 说明

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`

**Step 1: 更新进度**

- RFC 0031 状态从 `Review` 切到 `Implementing` / `Done` 时同步更新
- 备注写清：
  - 专用分类
  - `30RYZT.blk` 只镜像 `三十涨停Pro预选`
  - must_pool 默认参数

**Step 2: 记录 breaking change**

落地时补：

- `/gantt/shouban30` 不再是纯只读页
- `stock_pre_pools / stock_pools` 新增 `三十涨停Pro预选 / 三十涨停Pro自选`
- `30RYZT.blk` 由当前仓正式接管

Plan complete and saved to `docs/plans/2026-03-11-gantt-shouban30-pool-persistence-implementation-plan.md`. Two execution options:

1. Subagent-Driven (this session) - 我在当前会话里逐任务执行并复核
2. Parallel Session (separate) - 新开会话按 `executing-plans` 批量执行
