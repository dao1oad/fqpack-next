# KlineSlim 缩放平移与当前周期 Legend 状态修复 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 `KlineSlim` 主图的鼠标缩放、拖拽平移和当前主周期 legend 状态保持问题，并确保刷新后仍保留用户当前视图。

**Architecture:** 在 `kline-slim.js` 中把 `datazoom` 事件 payload 作为缩放窗口状态的唯一真值来源，并让当前 legend 状态稳定参与重绘版本签名；在 `draw-slim.js` 中继续消费显式传入的 `dataZoomState`，同时避免普通刷新重建 `dataZoom` 组件。整套修复保持当前多周期缠论 renderer，不回退到旧版单周期实现。

**Tech Stack:** Vue 3、ECharts 6、Node test runner、Selenium 手工烟测、Docker 并行部署

---

### Task 1: 锁定当前回归点的失败测试

**Files:**
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`
- Reference: `docs/plans/2026-03-09-kline-slim-zoom-pan-interaction-design.md`

**Step 1: Write the failing test**

增加文件级断言，锁定以下行为：

- `handleSlimDataZoom` 使用事件参数而不是 `chart.getOption().dataZoom`
- `buildRenderVersion` 或等价逻辑包含当前 legend 选择状态
- `drawSlim` 的普通刷新不替换 `dataZoom`

**Step 2: Run test to verify it fails**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\fix-kline-slim-zoom-pan-interaction\morningglory\fqwebui`

Expected: FAIL，提示当前实现仍依赖 `chart.getOption().dataZoom` 或未锁定 `replaceMerge`

**Step 3: Write minimal implementation**

仅写最小量测试断言，不提前改生产代码。

**Step 4: Run test to verify it passes/fails as intended**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: 失败点稳定且指向本次要修的行为

**Step 5: Commit**

```bash
git add morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "test: lock kline slim zoom interaction regressions"
```

### Task 2: 修复 `kline-slim.js` 的交互状态保存

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: Write the failing test**

确保测试明确要求：

- `handleSlimDataZoom(params)` 直接解析 `params.batch`
- 普通刷新不清空 `chartDataZoomState`
- 当前周期 legend 选择状态参与重绘签名

**Step 2: Run test to verify it fails**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: FAIL

**Step 3: Write minimal implementation**

- 改写 `handleSlimDataZoom`
- 收口 `renderVersion` 的生成
- 保留结构性切换时的重置逻辑

**Step 4: Run test to verify it passes**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "fix: persist kline slim zoom state from datazoom events"
```

### Task 3: 修复 `draw-slim.js` 的普通刷新行为

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/draw-slim.js`
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: Write the failing test**

确保测试明确要求：

- `dataZoomState` 是优先输入
- 普通刷新不把 `dataZoom` 放进 `replaceMerge`
- 结构性重绘仍允许全量替换

**Step 2: Run test to verify it fails**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: FAIL

**Step 3: Write minimal implementation**

- 调整 `drawSlim` 的 `setOption` 策略
- 保留现有中枢残影修复路径

**Step 4: Run test to verify it passes**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/draw-slim.js morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "fix: preserve kline slim zoom components across refreshes"
```

### Task 4: 全量验证与手工冒烟

**Files:**
- Modify: `docs/migration/progress.md`

**Step 1: Run automated verification**

Run:

- `node --test tests/kline-slim-default-symbol.test.mjs tests/kline-slim-sidebar.test.mjs tests/kline-slim-chanlun-structure.test.mjs tests/kline-slim-multi-period-chanlun.test.mjs`
- `npm run build`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\fix-kline-slim-zoom-pan-interaction\morningglory\fqwebui`

Expected: PASS

**Step 2: Run browser smoke test**

验证：

- 滚轮缩放可用
- 拖拽平移可用
- 刷新后视图保持
- `5m` legend 只影响 `5m` 缠论层

**Step 3: Update migration progress**

在 `docs/migration/progress.md` 同一分支记录本次修复内容与验证结果。

**Step 4: Commit**

```bash
git add docs/migration/progress.md
git commit -m "docs: record kline slim zoom interaction fix"
```
