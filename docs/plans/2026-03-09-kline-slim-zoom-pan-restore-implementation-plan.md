# KlineSlim 恢复鼠标缩放平移功能 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 恢复 `KlineSlim` 的鼠标滚轮缩放与拖拽平移功能，同时保留刷新后的窗口继承能力。

**Architecture:** 在 `kline-slim.js` 中恢复 `handleSlimDataZoom()` 和 `handleSlimDataZoomPointerUp()` 对 `scheduleRender(true)` 的调用，让 `chartDataZoomState` 的变化立即应用回图表；测试同步改回“交互期会重绘”的预期，`draw-slim.js` 不做结构调整。

**Tech Stack:** Vue 3、ECharts 6、Node test runner、Selenium 烟测

---

### Task 1: 写失败测试锁定回归

**Files:**
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: Write the failing test**

把当前测试预期改为：

- `handleSlimDataZoom()` 中存在 `scheduleRender(true)`
- `handleSlimDataZoomPointerUp()` 中存在 `scheduleRender(true)`

**Step 2: Run test to verify it fails**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: FAIL

**Step 3: Commit**

```bash
git add morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "test: lock kline slim zoom pan restore regression"
```

### Task 2: 恢复交互期即时重绘

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: Write minimal implementation**

恢复：

- `handleSlimDataZoom()` 中的 `this.scheduleRender(true)`
- `handleSlimDataZoomPointerUp()` 中的 `this.scheduleRender(true)`

**Step 2: Run focused test**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: PASS

**Step 3: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "fix: restore kline slim zoom pan interaction"
```

### Task 3: 运行聚焦验证与浏览器烟测

**Files:**
- No additional code changes required unless smoke test exposes another issue

**Step 1: Run focused frontend suite**

Run: `node --test tests/kline-slim-default-symbol.test.mjs tests/kline-slim-sidebar.test.mjs tests/kline-slim-chanlun-structure.test.mjs tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 2: Run browser smoke test**

验证：

- 滚轮缩放后 `option.dataZoom` 立即变化
- 拖拽平移后 `option.dataZoom` 立即变化
- 刷新后窗口仍保持

**Step 3: Update migration progress**

在 `docs/migration/progress.md` 追加记录这次“恢复缩放平移功能”的修复。
