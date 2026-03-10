# KlineSlim Zoom/Pan Performance Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 `KlineSlim` 页面缩放和平移卡顿，恢复为可正常缩放/平移且在轮询刷新后保留当前视口。

**Architecture:** 回退当前 `KlineSlim` 的手工 `datazoom` 热路径，恢复旧仓可用版本的交互模式: 缩放/平移由 ECharts 自身维护，前端只在真实数据刷新或 legend 可见性变化时重绘，并在 `draw-slim.js` 中继承当前 `dataZoom` 窗口。自动化验证使用浏览器拦截 API 返回固定 fixture，对本地 Vite 页面执行滚轮缩放、底部 slider 平移和刷新后状态保持检查。

**Tech Stack:** Vue 3, ECharts, Node test runner, Vite, Playwright (通过 `npx --package` 临时运行，不写入仓库依赖)

---

### Task 1: 锁定失败测试

**Files:**
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: 写失败测试**

- 增加断言，要求当前 `kline-slim.js`:
  - 不再在 `handleSlimDataZoom()` 中调用 `chart.clear()` 或 `chart.setOption(currentOption, ...)`
  - 不再绑定 `datazoom` 事件作为缩放热路径的手工回放入口
  - 不再持有 `replayingDataZoom` / `dataZoomReplayFrameId` 这类回放状态
- 保留断言，要求 `draw-slim.js` 继续从 `previousOption.dataZoom` 继承视口。

**Step 2: 跑失败测试**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: 新增断言失败，明确指向当前 `handleSlimDataZoom()` 的整图回放逻辑。

**Step 3: 提交点**

- 不提交，只进入实现。

### Task 2: 最小实现回退

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/src/views/js/draw-slim.js`

**Step 1: 写最小实现**

- 删除 `kline-slim.js` 中当前手工 `datazoom` 回放链路:
  - `handleSlimDataZoom()`
  - `pickDataZoomWindow()` / `extractDataZoomWindow()` 如仅供该链路使用则一并删除
  - `replayingDataZoom` / `dataZoomReplayFrameId`
  - `chart.on('datazoom', ...)`
- 恢复旧仓有效模式:
  - 缩放/平移仅由 ECharts 自己处理
  - `scheduleRender()` 只由真实数据刷新和 legend 变化驱动
  - `draw-slim.js` 在 `keepState` 刷新时继续继承 `previousOption.dataZoom`

**Step 2: 跑聚焦测试**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: 通过。

### Task 3: 浏览器自动化回归

**Files:**
- Add: `morningglory/fqwebui/tests/kline-slim-zoom-pan.browser.mjs`

**Step 1: 写浏览器自动化脚本**

- 启动本地 `vite` dev server。
- 在 Playwright 中拦截:
  - `/api/stock_data`
  - `/api/get_stock_position_list`
  - `/api/get_stock_must_pools_list`
  - `/api/get_stock_pools_list`
  - `/api/get_stock_pre_pools_list`
  - `/api/gantt/stocks/reasons`
  - `/api/stock_data_chanlun_structure`
- 返回固定 fixture，让页面稳定进入 `/kline-slim?symbol=sz002262&period=5m`。
- 自动执行:
  - 记录初始 `dataZoom.start/end`
  - 鼠标滚轮缩放
  - 拖动底部 slider 平移
  - 等待一轮轮询/强制刷新后再次读取 `dataZoom`
- 断言:
  - 缩放后窗口变化
  - 平移后窗口继续变化
  - 刷新后窗口保持，不回到初始值
  - 页面无前端异常

**Step 2: 跑自动化**

Run:

```powershell
$env:CI='1'
pnpm dev --host 127.0.0.1 --port 18086
```

另一个进程运行:

```powershell
npx --yes --package=playwright node tests/kline-slim-zoom-pan.browser.mjs
```

Expected: 自动化断言全部通过。

### Task 4: 收尾与文档

**Files:**
- Modify: `docs/migration/progress.md`

**Step 1: 更新进度**

- 在 `RFC 0022` 备注里追加本次“移除手工 datazoom 回放、回退到旧仓稳定视口语义”的说明。

**Step 2: 最终验证**

Run:

```powershell
node --test tests/kline-slim-multi-period-chanlun.test.mjs
pnpm build
npx --yes --package=playwright node tests/kline-slim-zoom-pan.browser.mjs
```

Expected: 全部通过。
