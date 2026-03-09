# KlineSlim 缠论结构三行摘要 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 `KlineSlim` 的缠论结构面板从“摘要网格 + 中枢表格”调整为只保留 `高级段 / 段 / 笔` 三条单行摘要，并让 `笔` 展示当前这一笔包含的 K 线数量。

**Architecture:** 保持后端 `/api/stock_data_chanlun_structure` 契约不变，只改前端展示层。先用文件级前端测试锁定新的模板契约，再在 `kline-slim.js` 中整理三条摘要的 view-model，最后让 `KlineSlim.vue` 改为渲染单行标签摘要并删除中枢表格。

**Tech Stack:** Vue 3 Options API, Vite, Node `--test`, Stylus

---

### Task 1: 锁定新的结构面板模板契约

**Files:**
- Modify: `morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs`
- Test: `morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs`

**Step 1: Write the failing test**

在 `morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs` 增加一个新用例，锁定新的展示契约：

```js
test('KlineSlim renders chanlun structure as three inline summaries without pivot tables', async () => {
  const content = await readFile(new URL('../src/views/KlineSlim.vue', import.meta.url), 'utf8')

  assert.match(content, /高级段/)
  assert.match(content, /段/)
  assert.match(content, /笔/)
  assert.match(content, /K线数/)
  assert.doesNotMatch(content, /段 ZG/)
  assert.doesNotMatch(content, /中枢 ZG/)
  assert.doesNotMatch(content, /暂无段中枢/)
  assert.doesNotMatch(content, /暂无笔中枢/)
})
```

**Step 2: Run test to verify it fails**

Run:

```bash
node --test morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs
```

Expected:

- FAIL
- 失败点应来自旧模板里仍存在 `段 ZG` / `中枢 ZG` 或缺少 `K线数`

**Step 3: Keep only the minimal failing assertion set**

如果失败原因不是模板契约本身，而是测试语法或路径问题，先修正测试，直到它因为旧模板还未改造而稳定失败。

**Step 4: Run test again to confirm RED**

Run:

```bash
node --test morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs
```

Expected:

- FAIL
- 输出稳定指向旧展示结构

**Step 5: Commit**

```bash
git add morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs
git commit -m "test: 锁定缠论结构三行摘要契约"
```

### Task 2: 在脚本层整理三条摘要 view-model

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Test: `morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs`

**Step 1: Write the failing test for the new helper surface**

在现有文件级模板测试之外，再增加一个轻量断言，锁定脚本中存在新摘要辅助逻辑，例如：

```js
test('KlineSlim script defines helpers for inline chanlun summaries', async () => {
  const content = await readFile(new URL('../src/views/js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(content, /buildChanlunSummaryItems/)
  assert.match(content, /computeChanlunBiBarCount/)
})
```

**Step 2: Run test to verify it fails**

Run:

```bash
node --test morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs
```

Expected:

- FAIL
- 提示 `buildChanlunSummaryItems` 或 `computeChanlunBiBarCount` 尚不存在

**Step 3: Write minimal implementation**

在 `morningglory/fqwebui/src/views/js/kline-slim.js` 中新增最小辅助函数，并让组件 computed 可以消费：

```js
function computeChanlunBiBarCount(item) {
  const start = Number(item?.start_idx)
  const end = Number(item?.end_idx)
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) {
    return '--'
  }
  return String(end - start + 1)
}

function buildChanlunSummaryItems({ levelLabel, item, countLabel, countValue }) {
  if (!item) {
    return null
  }
  return {
    levelLabel,
    fields: [
      { label: '方向', value: formatDirectionLabel(item.direction) },
      { label: '价格比例', value: formatPercentValue(item.price_change_pct) },
      { label: countLabel, value: countValue },
      { label: '起始', value: `${item.start_time || '--'} (${formatPriceValue(item.start_price)})` },
      { label: '终点', value: `${item.end_time || '--'} (${formatPriceValue(item.end_price)})` }
    ]
  }
}
```

然后新增 3 个 computed，例如：

```js
chanlunHigherSegmentSummary() { ... }
chanlunSegmentSummary() { ... }
chanlunBiSummary() { ... }
```

其中：

- `高级段` 使用 `contained_duan_count` 和 `pivot_count`
- `段` 使用 `contained_bi_count` 和 `pivot_count`
- `笔` 使用 `computeChanlunBiBarCount(this.chanlunBi)`

建议把 `高级段/段` 的“计数”作为两个独立字段保留：

```js
{ label: '包含段数', value: item.contained_duan_count ?? '--' }
{ label: '中枢数', value: item.pivot_count ?? '--' }
```

以及：

```js
{ label: '包含笔数', value: item.contained_bi_count ?? '--' }
{ label: '中枢数', value: item.pivot_count ?? '--' }
```

`笔` 只保留一个：

```js
{ label: 'K线数', value: computeChanlunBiBarCount(item) }
```

**Step 4: Run test to verify it passes**

Run:

```bash
node --test morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs
```

Expected:

- 脚本 helper 相关断言 PASS
- 模板契约相关断言仍 FAIL

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs
git commit -m "feat: 整理缠论结构三行摘要数据"
```

### Task 3: 将模板改为单行摘要并删除中枢表格

**Files:**
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Test: `morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs`

**Step 1: Extend the failing template test if needed**

如果当前模板测试还没覆盖“标签样式”和“无中枢表格”，补齐断言：

```js
assert.match(content, /chanlun-summary-line/)
assert.match(content, /chanlun-summary-chip/)
assert.doesNotMatch(content, /chanlun-pivot-table/)
```

**Step 2: Run test to verify it fails**

Run:

```bash
node --test morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs
```

Expected:

- FAIL
- 失败指向模板仍使用旧类名或旧表格结构

**Step 3: Write minimal template and style changes**

在 `morningglory/fqwebui/src/views/KlineSlim.vue` 中：

- 删除 `高级段` 与 `段` 下方的中枢表格和 “暂无段中枢/暂无笔中枢” 文案
- 删除 3 个 section 中旧的 `chanlun-summary-grid` 结构
- 改为统一渲染单行摘要，例如：

```vue
<div v-if="chanlunHigherSegmentSummary" class="chanlun-summary-line">
  <span class="chanlun-summary-line__title">高级段</span>
  <span
    v-for="field in chanlunHigherSegmentSummary.fields"
    :key="`higher:${field.label}`"
    class="chanlun-summary-chip"
  >
    <span class="chanlun-summary-chip__label">{{ field.label }}</span>
    <span class="chanlun-summary-chip__value">{{ field.value }}</span>
  </span>
</div>
```

`段` 与 `笔` 采用同一结构。

同时新增最小样式：

```stylus
.chanlun-summary-line
  display flex
  align-items center
  flex-wrap wrap
  gap 8px

.chanlun-summary-line__title
  min-width 48px
  font-weight 600
  color #f8fafc

.chanlun-summary-chip
  display inline-flex
  align-items center
  gap 4px
  padding 4px 8px
  border-radius 999px
  background rgba(30, 41, 59, 0.72)
  border 1px solid rgba(127, 127, 122, 0.18)
```

保留原有 section 和空态节点，不修改 header、刷新、关闭按钮。

**Step 4: Run test to verify it passes**

Run:

```bash
node --test morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs
```

Expected:

- PASS
- 输出确认 `K线数` 与新类名存在
- 输出确认 `段 ZG` / `中枢 ZG` / `chanlun-pivot-table` 已不存在

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs
git commit -m "feat: 调整缠论结构为三行摘要"
```

### Task 4: 完整验证前端构建面

**Files:**
- Verify: `morningglory/fqwebui/src/views/KlineSlim.vue`
- Verify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Verify: `morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs`

**Step 1: Run targeted test**

Run:

```bash
node --test morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs
```

Expected:

- PASS

**Step 2: Run frontend build**

Run:

```bash
npm run build
```

Workdir:

```bash
morningglory/fqwebui
```

Expected:

- exit code 0
- Vite build 完成，无模板或脚本语法错误

**Step 3: Inspect git diff**

Run:

```bash
git diff --stat HEAD~3..HEAD
git status --short
```

Expected:

- 只有 `KlineSlim.vue`、`kline-slim.js`、测试文件以及需要时的构建产物变更
- 工作树干净，或只剩明确要提交的构建产物

**Step 4: Final commit if build output changed**

```bash
git add morningglory/fqwebui
git commit -m "build: 更新缠论结构三行摘要产物"
```

仅在 `npm run build` 产出发生变更时执行。
