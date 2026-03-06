# KlineSlim 默认持仓标的 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 `/kline-slim` 在未提供 `symbol` 时，自动使用当前持仓列表中的第一个标的作为默认标的，并将导航栏按钮文案改为“行情图表”。

**Architecture:** 保持后端接口不变，在前端页面层实现默认标的解析。先抽离一个纯函数 helper，负责“是否需要解析默认标的、如何从持仓列表中取首个 symbol、如何构建替换路由 query、如何生成空态文案”，再把它接入 `kline-slim` 页面逻辑，最后修改 Header 按钮文案并做构建与手工验收。

**Tech Stack:** Vue 3, Vue Router, Axios, Vite, Node built-in test runner (`node --test`)

---

### Task 1: 抽离默认标的解析 helper 并补纯函数测试

**Files:**
- Create: `morningglory/fqwebui/src/views/js/kline-slim-default-symbol.mjs`
- Create: `morningglory/fqwebui/tests/kline-slim-default-symbol.test.mjs`

**Step 1: Write the failing test**

```javascript
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  shouldResolveDefaultSymbol,
  pickFirstHoldingSymbol,
  buildResolvedKlineSlimQuery,
  getKlineSlimEmptyMessage
} from '../src/views/js/kline-slim-default-symbol.mjs'

test('shouldResolveDefaultSymbol only when symbol is missing', () => {
  assert.equal(shouldResolveDefaultSymbol({ symbol: '' }), true)
  assert.equal(shouldResolveDefaultSymbol({}), true)
  assert.equal(shouldResolveDefaultSymbol({ symbol: 'sh510050' }), false)
})

test('pickFirstHoldingSymbol returns first truthy symbol', () => {
  assert.equal(
    pickFirstHoldingSymbol([{ symbol: 'sh600000' }, { symbol: 'sz000001' }]),
    'sh600000'
  )
  assert.equal(pickFirstHoldingSymbol([]), '')
  assert.equal(pickFirstHoldingSymbol([{ symbol: '' }]), '')
})

test('buildResolvedKlineSlimQuery keeps existing query and injects defaults', () => {
  assert.deepEqual(
    buildResolvedKlineSlimQuery({
      currentQuery: { endDate: '2026-03-07' },
      symbol: 'sh600000',
      period: '5m'
    }),
    { endDate: '2026-03-07', symbol: 'sh600000', period: '5m' }
  )
})

test('getKlineSlimEmptyMessage prefers resolving text before generic empty text', () => {
  assert.equal(
    getKlineSlimEmptyMessage({ resolvingDefaultSymbol: true, resolveError: '' }),
    '正在读取持仓，准备默认标的...'
  )
  assert.equal(
    getKlineSlimEmptyMessage({ resolvingDefaultSymbol: false, resolveError: '' }),
    '请输入或通过 query 传入 `symbol`，例如 `/kline-slim?symbol=sh510050`'
  )
  assert.equal(
    getKlineSlimEmptyMessage({
      resolvingDefaultSymbol: false,
      resolveError: '默认持仓解析失败'
    }),
    '默认持仓解析失败'
  )
})
```

**Step 2: Run test to verify it fails**

Run:

```bash
node --test morningglory/fqwebui/tests/kline-slim-default-symbol.test.mjs
```

Expected: FAIL with module-not-found because `kline-slim-default-symbol.mjs` does not exist yet.

**Step 3: Write minimal implementation**

```javascript
export function shouldResolveDefaultSymbol(query) {
  return !String(query?.symbol || '').trim()
}

export function pickFirstHoldingSymbol(positions) {
  const first = Array.isArray(positions)
    ? positions.find((item) => String(item?.symbol || '').trim())
    : null
  return String(first?.symbol || '').trim()
}

export function buildResolvedKlineSlimQuery({ currentQuery, symbol, period }) {
  return {
    ...(currentQuery || {}),
    symbol,
    period
  }
}

export function getKlineSlimEmptyMessage({
  resolvingDefaultSymbol,
  resolveError
}) {
  if (resolveError) {
    return resolveError
  }
  if (resolvingDefaultSymbol) {
    return '正在读取持仓，准备默认标的...'
  }
  return '请输入或通过 query 传入 `symbol`，例如 `/kline-slim?symbol=sh510050`'
}
```

**Step 4: Run test to verify it passes**

Run:

```bash
node --test morningglory/fqwebui/tests/kline-slim-default-symbol.test.mjs
```

Expected: PASS with 4 passing tests.

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim-default-symbol.mjs morningglory/fqwebui/tests/kline-slim-default-symbol.test.mjs
git commit -m "test: add kline slim default symbol helper coverage"
```

### Task 2: 接入 KlineSlim 页面默认标的解析与空态逻辑

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`
- Modify: `morningglory/fqwebui/src/api/stockApi.js`
- Test: `morningglory/fqwebui/tests/kline-slim-default-symbol.test.mjs`

**Step 1: Extend the failing test for route-query decisions**

```javascript
test('buildResolvedKlineSlimQuery preserves endDate and injects default period', () => {
  assert.deepEqual(
    buildResolvedKlineSlimQuery({
      currentQuery: { endDate: '2026-03-07' },
      symbol: 'sz000001',
      period: '5m'
    }),
    { endDate: '2026-03-07', symbol: 'sz000001', period: '5m' }
  )
})
```

Also add a browser-facing checklist comment at the bottom of the test file so the engineer keeps the runtime scenarios in view:

```javascript
// Manual checklist:
// 1. /kline-slim -> auto replace to first holding symbol when positions exist
// 2. /kline-slim with empty holdings -> stay on empty state
// 3. /kline-slim?symbol=sh510050 -> unchanged behavior
```

**Step 2: Run test to verify it fails if the helper contract changed**

Run:

```bash
node --test morningglory/fqwebui/tests/kline-slim-default-symbol.test.mjs
```

Expected: FAIL until helper behavior and call sites agree on the query shape.

**Step 3: Write minimal implementation**

In `stockApi.js`, add a tiny wrapper:

```javascript
getHoldingPositionList() {
  return axios({
    url: '/api/get_stock_position_list',
    method: 'get'
  })
}
```

In `kline-slim.js`:

- import the helper functions from `kline-slim-default-symbol.mjs`
- add state fields:

```javascript
resolvingDefaultSymbol: false,
defaultSymbolResolveError: ''
```

- add a method similar to:

```javascript
async resolveDefaultSymbol(token) {
  this.resolvingDefaultSymbol = true
  this.defaultSymbolResolveError = ''
  try {
    const positions = await stockApi.getHoldingPositionList()
    if (token !== this.routeToken) return
    const symbol = pickFirstHoldingSymbol(positions)
    if (!symbol) {
      this.resolvingDefaultSymbol = false
      return
    }
    this.$router.replace({
      path: '/kline-slim',
      query: buildResolvedKlineSlimQuery({
        currentQuery: this.$route.query,
        symbol,
        period: this.currentPeriod
      })
    })
  } catch (error) {
    if (token === this.routeToken) {
      this.defaultSymbolResolveError = '默认持仓解析失败'
      this.resolvingDefaultSymbol = false
    }
  }
}
```

- in `handleRouteChange()`:
  - clear `defaultSymbolResolveError`
  - if `shouldResolveDefaultSymbol(this.$route.query)` is true, clear chart state, call `resolveDefaultSymbol(this.routeToken)`, and return early
  - when a real `symbol` exists, make sure `resolvingDefaultSymbol = false`

In `KlineSlim.vue`, replace the hard-coded empty text with a computed string, for example:

```vue
<div v-if="!routeSymbol" class="kline-slim-empty">
  {{ emptyMessage }}
</div>
```

and add the computed field in `kline-slim.js`:

```javascript
emptyMessage() {
  return getKlineSlimEmptyMessage({
    resolvingDefaultSymbol: this.resolvingDefaultSymbol,
    resolveError: this.defaultSymbolResolveError
  })
}
```

**Step 4: Run tests and build**

Run:

```bash
node --test morningglory/fqwebui/tests/kline-slim-default-symbol.test.mjs
npm --prefix morningglory/fqwebui run build
```

Expected:

- `node --test` PASS
- `vite build` PASS with no import or template errors

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/src/api/stockApi.js morningglory/fqwebui/src/views/js/kline-slim-default-symbol.mjs morningglory/fqwebui/tests/kline-slim-default-symbol.test.mjs
git commit -m "feat: default kline slim symbol from holdings"
```

### Task 3: 修改导航栏文案并做手工验收

**Files:**
- Modify: `morningglory/fqwebui/src/views/MyHeader.vue`
- Test: `morningglory/fqwebui/tests/kline-slim-default-symbol.test.mjs`

**Step 1: Write the failing verification target**

Add this note to the manual checklist section in the test file so the engineer must explicitly verify the navigation label and entry behavior:

```javascript
// 4. Header button label is "行情图表"
// 5. Clicking the header button still routes to /kline-slim
```

**Step 2: Run the existing automated checks first**

Run:

```bash
node --test morningglory/fqwebui/tests/kline-slim-default-symbol.test.mjs
npm --prefix morningglory/fqwebui run build
```

Expected: PASS before the label-only change, establishing a safe baseline.

**Step 3: Write minimal implementation**

In `MyHeader.vue`, change only the button text:

```vue
<el-button type="warning" @click="jumpToControl('klineSlim')" size="small">
  行情图表
</el-button>
```

Do not change the routing target.

**Step 4: Run final verification**

Run:

```bash
node --test morningglory/fqwebui/tests/kline-slim-default-symbol.test.mjs
npm --prefix morningglory/fqwebui run build
```

Manual verification:

1. Open `http://127.0.0.1:18080/kline-slim?symbol=sh510050`
Expected: chart page behaves as before

2. Open `http://127.0.0.1:18080/kline-slim`
Expected with non-empty holdings: auto replace to `/kline-slim?symbol=<first>&period=5m`

3. Open `http://127.0.0.1:18080/kline-slim`
Expected with current environment's empty holdings: empty state remains visible

4. Open the main page header
Expected: button label shows `行情图表`

5. Click `行情图表`
Expected: route goes to `/kline-slim`, then follows the same default-symbol logic as direct access

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/MyHeader.vue morningglory/fqwebui/tests/kline-slim-default-symbol.test.mjs
git commit -m "feat: rename kline slim nav entry"
```

### Completion Checklist

- Run `@superpowers:verification-before-completion`
- Confirm no backend interface contract changed
- Confirm empty holdings still render a stable empty state
- Confirm existing `/kline-slim?symbol=...` behavior did not regress
