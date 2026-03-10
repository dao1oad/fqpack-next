# KlineSlim 中枢/段中枢残影修复 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

> **2026-03-11 执行修正**：进入实现后，直接对当前并行环境 `18080/15000` 的真实页面做多轮切标的探测，未再复现 issue 描述中的残影；因此原先“在 controller 结构性切换时显式 `chart.clear()`”的假设被否定。本票实际落地改为：补 `@playwright/test` 依赖、把当前稳定行为固化为 ghosting 浏览器回归，并修复 ghosting / zoom-pan 规格合并运行时的 `vite build` 并发冲突；不做新的生产逻辑改动。

**Goal:** 修复 `KlineSlim` 在重复切换 `symbol` 后累积的 `中枢 / 段中枢 / 高级段中枢` 残影，并用浏览器自动化回归锁住这一行为。

**Architecture:** 保持现有 `drawSlim()` steady-state 渲染路径不变，把修复点收敛到 `kline-slim.js` 的结构性路由切换生命周期：当 `symbol / period / endDate` 变化时先显式 `chart.clear()`，再等待新数据首帧；同 identity 的普通轮询刷新、legend 开关、缩放和平移不清图。测试上同时增加文件级断言和 Playwright 浏览器回归，验证重复切换标的后回到原标的的截图稳定一致。

**Tech Stack:** Vue 3、ECharts 6、Node test runner、Playwright、pnpm

---

## Task Checklist

- [ ] Task 1: 写失败测试，稳定复现“切标的后中枢残影”
- [ ] Task 2: 在 controller 中实现结构性切换显式清图
- [ ] Task 3: 复跑 ghosting 与 zoom/pan 浏览器回归
- [ ] Task 4: 更新文档证据并准备进入 `In Progress`

### Task 1: 锁定切标的残影的 RED 证据

**Files:**
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`
- Create: `morningglory/fqwebui/tests/kline-slim-ghosting.browser.spec.mjs`
- Reference: `docs/rfcs/0029-kline-slim-zhongshu-ghosting-fix.md`

**Step 1: Write the failing test**

在文件级测试里增加断言，锁定以下行为：

```js
assert.match(content, /handleRouteChange\(\)/)
assert.match(content, /this\.chart\.clear\(\)/)
assert.doesNotMatch(content, /fetchMainData[\s\S]*this\.chart\.clear\(\)/)
```

新增 Playwright 回归，主流程如下：

```js
await page.goto('/kline-slim?symbol=sz002262&period=5m')
const baselineHash = await captureChartHash(page)
await switchSymbol(page, 'sh510050')
await switchSymbol(page, 'sz000001')
await switchSymbol(page, 'sz002262')
const replayHash = await captureChartHash(page)
expect(replayHash).toBe(baselineHash)
```

**Step 2: Run test to verify it fails**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Run: `node node_modules/@playwright/test/cli.js test tests/kline-slim-ghosting.browser.spec.mjs`

Workdir: `D:\fqpack\runtime\symphony-service\workspaces\FRE-6\morningglory\fqwebui`

Expected: FAIL，原因是当前 controller 在结构性切换时还没有显式清图，且浏览器回归能观察到切回原标的后的截图漂移。

**Step 3: Write minimal implementation**

此任务只写测试，不修改生产代码。

**Step 4: Run test to verify it fails as intended**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Expected: FAIL，失败点稳定指向本票目标行为。

**Step 5: Commit**

```bash
git add morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs morningglory/fqwebui/tests/kline-slim-ghosting.browser.spec.mjs
git commit -m "test: reproduce kline slim zhongshu ghosting on symbol switch"
```

### Task 2: 在 `kline-slim.js` 实现结构性切换显式清图

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`
- Modify: `morningglory/fqwebui/tests/kline-slim-ghosting.browser.spec.mjs`

**Step 1: Write the failing test**

沿用 Task 1 的 RED 结果，不新增第二套失败场景。

**Step 2: Run test to verify it fails**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Run: `node node_modules/@playwright/test/cli.js test tests/kline-slim-ghosting.browser.spec.mjs`

Expected: FAIL

**Step 3: Write minimal implementation**

在 `data()` 中增加结构性 identity 记录，例如：

```js
lastStructuralRouteKey: ''
```

在 `handleRouteChange()` 中：

```js
const nextStructuralRouteKey = JSON.stringify({
  symbol: this.routeSymbol || '',
  period: this.currentPeriod,
  endDate: this.endDateModel || ''
})
const shouldHardResetChart =
  !!this.chart &&
  !!this.routeSymbol &&
  !!this.lastStructuralRouteKey &&
  this.lastStructuralRouteKey !== nextStructuralRouteKey

this.lastStructuralRouteKey = nextStructuralRouteKey

if (shouldHardResetChart) {
  this.chart.clear()
}
this.chart.showLoading(echartsConfig.loadingOption)
```

要求：

- 只在结构性切换时清图；
- 普通 `fetchMainData()`、`refreshVisibleChanlunPeriods()` 和 legend 开关不清图；
- 不改 `drawSlim()` 的 steady-state `setOption` 路径。

**Step 4: Run test to verify it passes**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Run: `node node_modules/@playwright/test/cli.js test tests/kline-slim-ghosting.browser.spec.mjs`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs morningglory/fqwebui/tests/kline-slim-ghosting.browser.spec.mjs
git commit -m "fix: clear kline slim chart on structural route switches"
```

### Task 3: 复跑 ghosting 与 zoom/pan 回归

**Files:**
- Modify: `morningglory/fqwebui/tests/kline-slim-ghosting.browser.spec.mjs` (only if selectors or stubs need stabilization)

**Step 1: Run focused verification**

Run: `node node_modules/@playwright/test/cli.js test tests/kline-slim-ghosting.browser.spec.mjs tests/kline-slim-zoom-pan.browser.spec.mjs`

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Run: `pnpm build`

Workdir: `D:\fqpack\runtime\symphony-service\workspaces\FRE-6\morningglory\fqwebui`

Expected: PASS

**Step 2: If any regression fails, make the smallest possible fix**

允许的最小修复范围：

- `kline-slim.js`
- `tests/kline-slim-multi-period-chanlun.test.mjs`
- `tests/kline-slim-ghosting.browser.spec.mjs`

不允许在这个任务里顺手重写 `draw-slim.js`；若必须动 renderer，先回到根因分析并单独记录。

**Step 3: Run verification again**

Run: `node node_modules/@playwright/test/cli.js test tests/kline-slim-ghosting.browser.spec.mjs tests/kline-slim-zoom-pan.browser.spec.mjs`

Run: `pnpm build`

Expected: PASS

**Step 4: Commit**

```bash
git add morningglory/fqwebui
git commit -m "test: verify kline slim ghosting and zoom regressions"
```

### Task 4: 更新文档证据并准备 Draft PR

**Files:**
- Modify: `docs/migration/progress.md`

**Step 1: Update progress evidence**

把 RFC 0029 对应行从 `Review` 更新为实现阶段的最新状态，并补上：

- RED 命令与结果摘要
- GREEN 命令与结果摘要
- Playwright 验证口径

**Step 2: Run a final diff sanity check**

Run: `git diff --stat`

Run: `git status --short`

Expected: 只包含本票相关文件。

**Step 3: Commit**

```bash
git add docs/migration/progress.md
git commit -m "docs: record kline slim ghosting fix evidence"
```
