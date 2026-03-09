# KlineSlim 缩放/平移卡顿性能优化 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 去掉 KlineSlim 缩放/平移热路径上的重复全量重绘，降低滚轮缩放和拖拽平移卡顿，同时继续保留刷新后的视口状态。

**Architecture:** 在 `kline-slim.js` 中把 `datazoom` 与 `mouseup` 处理器收口为“仅同步 `chartDataZoomState`”，不再在交互事件里触发 `scheduleRender()`；在 `draw-slim.js` 中继续复用显式传入的 `dataZoomState`，让数据刷新或图层切换时的正常重绘仍能继承当前窗口。保持现有多周期 legend、中枢残影修复和懒加载结构不变。

**Tech Stack:** Vue 3、ECharts 6、Node test runner、pytest、Docker Compose

---

### Task 1: 锁定缩放热路径回归测试

**Files:**
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`
- Reference: `docs/plans/2026-03-09-kline-slim-zoom-pan-performance-design.md`

**Step 1: Write the failing test**

为以下行为补充断言：

- `handleSlimDataZoom()` 更新 `chartDataZoomState`，但不再调用 `scheduleRender(true)`
- `handleSlimDataZoomPointerUp()` 同步最终窗口，但不再调用 `scheduleRender(true)`
- `drawSlim()` 仍然消费 `dataZoomState`

**Step 2: Run test to verify it fails**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-zoom-pan-performance\morningglory\fqwebui`

Expected: FAIL，表明当前实现仍在缩放事件中触发重绘

**Step 3: Write minimal implementation**

只补测试，不提前修改生产代码。

**Step 4: Run test to verify it fails for the right reason**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: FAIL，且失败点集中在 `scheduleRender(true)` 调用仍存在

**Step 5: Commit**

```bash
git add morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "test: lock kline slim zoom render hot path"
```

### Task 2: 收口 `kline-slim.js` 的缩放事件处理

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: Write the failing test**

明确锁定：

- `handleSlimDataZoom()` 只解析事件 payload 并更新 `chartDataZoomState`
- `handleSlimDataZoomPointerUp()` 只同步稳定窗口，不触发重绘
- 其他重绘路径例如 `legendselectchanged` 不受影响

**Step 2: Run test to verify it fails**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: FAIL

**Step 3: Write minimal implementation**

修改 `kline-slim.js`：

- 删除 `handleSlimDataZoom()` 里的 `this.scheduleRender(true)`
- 删除 `handleSlimDataZoomPointerUp()` 里的 `this.scheduleRender(true)`
- 保留现有的窗口签名比较，避免无效状态写入

**Step 4: Run test to verify it passes**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "fix: stop rerendering during kline slim zoom interaction"
```

### Task 3: 回归验证 `draw-slim.js` 的窗口继承语义

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/draw-slim.js`
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: Write the failing test**

锁定以下语义：

- 普通数据刷新时，`drawSlim()` 仍会使用显式传入的 `dataZoomState`
- 结构性重绘时，仍允许走 `clear + full replace`
- 不回退 legend 与中枢残影修复

**Step 2: Run test to verify it fails or stays covered**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: 如果已有覆盖则 PASS；若覆盖缺失则先补充到能稳定保护当前语义

**Step 3: Write minimal implementation**

只在必要时调整 `draw-slim.js`，确保：

- 保持 `dataZoomState` 优先级
- 不因为移除缩放事件重绘而影响正常刷新时的窗口继承

**Step 4: Run test to verify it passes**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/draw-slim.js morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "test: preserve kline slim zoom window across redraws"
```

### Task 4: 运行聚焦验证

**Files:**
- No code changes required

**Step 1: Run focused frontend tests**

Run: `node --test tests/kline-slim-default-symbol.test.mjs tests/kline-slim-sidebar.test.mjs tests/kline-slim-chanlun-structure.test.mjs tests/kline-slim-multi-period-chanlun.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-zoom-pan-performance\morningglory\fqwebui`

Expected: PASS

**Step 2: Run a targeted backend regression**

Run: `py -3.12 -m pytest freshquant/tests/test_stock_data_route_cache.py -q`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-zoom-pan-performance`

Expected: PASS

**Step 3: Run frontend production build**

Run: `npm run build`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-zoom-pan-performance\morningglory\fqwebui`

Expected: PASS

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: verify kline slim zoom performance fix"
```

### Task 5: 浏览器烟测与收尾

**Files:**
- Optionally modify: `docs/migration/progress.md`

**Step 1: Smoke test in browser**

打开：

- `http://127.0.0.1:18080/kline-slim?symbol=sh510050&period=5m`

验证：

- 滚轮缩放更顺滑
- 拖拽平移更顺滑
- 实时刷新后窗口保持不变
- `5m` legend 仍只控制 `5m` 缠论层

**Step 2: Update progress note if implementation is merged**

如果进入实现并最终合并，追加更新 `docs/migration/progress.md`

**Step 3: Commit**

```bash
git add docs/migration/progress.md
git commit -m "docs: record kline slim zoom performance optimization"
```
