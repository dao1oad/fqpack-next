# KlineSlim MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 交付 `KlineSlim` MVP：默认 `5m` 主图、默认叠加 `30m` 缠论结构，使用 Redis-first `/api/stock_data` 与无闪屏轮询刷新。

**Architecture:** 后端在实时请求路径优先命中 Redis `CACHE:KLINE:*`，前端新增独立 `KlineSlim` 页面，轮询拉取 `5m` 主图与 `30m` 叠加结构，并通过裁剪迁移的 `draw-slim.js` 进行单图叠加渲染。图表实例全生命周期复用，通过版本号比较与 merge 更新避免闪屏。

**Tech Stack:** Flask、Redis、Vue 3、Vue Router、@tanstack/vue-query、ECharts。

---

### Task 1: 文档与治理登记

**Files:**
- Create: `docs/rfcs/0005-kline-slim-mvp-5m-30m-overlay.md`
- Create: `docs/plans/2026-03-06-kline-slim-mvp-design.md`
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`

**Step 1: 写 RFC 与设计稿**

补齐目标、非目标、接口边界、轮询策略、验收标准。

**Step 2: 更新治理记录**

在 `progress.md` 登记 `0005`，在 `breaking-changes.md` 记录 `/api/stock_data` 的实时路径调整与“无破坏性变更”说明。

### Task 2: 为 Redis-first `/api/stock_data` 写回归测试

**Files:**
- Create: `freshquant/tests/test_stock_data_route_cache.py`
- Modify: `freshquant/rear/stock/routes.py`

**Step 1: 写失败测试**

覆盖 3 个场景：

```python
def test_stock_data_reads_redis_for_realtime_period(...): ...
def test_stock_data_falls_back_when_cache_missing(...): ...
def test_stock_data_skips_redis_when_end_date_present(...): ...
```

**Step 2: 跑定向测试确认失败**

Run: `pytest freshquant/tests/test_stock_data_route_cache.py -q`

**Step 3: 实现最小逻辑**

- 归一化 `period`
- 构造 Redis key
- 读取并解析 JSON
- 失败时 fallback `get_data_v2()`

**Step 4: 重新运行测试**

Run: `pytest freshquant/tests/test_stock_data_route_cache.py -q`

### Task 3: 新增 KlineSlim 页面与路由

**Files:**
- Create: `morningglory/fqwebui/src/views/KlineSlim.vue`
- Create: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/src/router/index.js`

**Step 1: 复用现有页面骨架**

沿用 `KlineBig` 的头部与容器结构，但只保留单图。

**Step 2: 建立双 query 轮询**

- 主图 `5m`：`refetchInterval = 5000`
- 叠加 `30m`：`refetchInterval = 15000`
- 页面不可见时返回 `false`

**Step 3: 增加渲染调度**

把主图数据、叠加数据、错误状态统一收敛到一次 `scheduleRender()`。

### Task 4: 迁移并裁剪 `draw-slim.js`

**Files:**
- Create: `morningglory/fqwebui/src/views/js/draw-slim.js`

**Step 1: 从旧仓库迁移单图渲染核心**

保留：
- K 线主图
- `extraChanlunMap`
- `remapChanlunToAxis`
- legend 分组
- `keepLegendState`

删除或禁用：
- WebSocket 相关逻辑
- grid mode
- 侧栏联动
- 非 MVP 周期集

**Step 2: 调整默认叠加周期**

把旧默认 `120m` 改成 `30m`，并把周期顺序收敛到 `1m/5m/15m/30m`。

**Step 3: 确保增量渲染**

- 仅在版本变化时 `setOption`
- 继承 `dataZoom`
- 继承 `legend.selected`
- 不主动 `clear()`

### Task 5: 验证与收尾

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`

**Step 1: 运行后端定向测试**

Run: `pytest freshquant/tests/test_stock_data_route_cache.py -q`

**Step 2: 运行前端构建或最小校验**

Run: `npm run build` 或仓库现有前端校验命令。

**Step 3: 更新进度状态**

若实现与验证完成，将 `0005` 状态改为 `Done`，补充“完成项/风险/下一步”。
