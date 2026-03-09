# Gantt Shouban30 默认缠论筛选 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `/gantt/shouban30` 页面增加黑名单板块过滤、基于现有 30m 缠论结构接口的默认筛选、按板块重算通过数与分组显示，并保持现有右栏热门理由详情不变。

**Architecture:** 保持后端 `shouban30` 与 `stocks/reasons` 公共接口不变，页面继续先拉现有板块和标的列表，再在前端对黑名单过滤后的候选标的去重调用 `/api/stock_data_chanlun_structure`。缠论判定、通过数重算、聚合视图重建和失败统计都收口到前端纯 helper，页面只负责请求编排、并发控制和状态绑定。

**Tech Stack:** Vue 3、Axios、Element Plus、Node `node:test`、现有 `futureApi.getChanlunStructure`、现有 Flask `/api/stock_data_chanlun_structure`、Python 3.12 pytest

---

### Task 1: 锁定黑名单板块过滤与 30m 默认缠论判定纯函数

**Files:**
- Create: `morningglory/fqwebui/src/views/shouban30ChanlunFilter.mjs`
- Create: `morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`
- Reference: `docs/plans/2026-03-09-gantt-shouban30-chanlun-filter-design.md`

**Step 1: Write the failing test**

为纯函数写失败测试，覆盖：
- `其他 / 公告 / ST股 / ST板块` 黑名单过滤
- `higher_segment` 价格倍数 `<= 3.0`
- `segment` 价格倍数 `<= 3.0`
- `bi.price_change_pct <= 30`
- 缺结构/异常结果按“不通过”处理

```javascript
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  CHANLUN_EXCLUDED_PLATE_NAMES,
  filterExcludedPlates,
  getSegmentGainMultiple,
  passesDefaultChanlunFilter
} from './shouban30ChanlunFilter.mjs'

test('filters excluded plate names', () => {
  assert.deepEqual(
    filterExcludedPlates([
      { plate_name: '机器人' },
      { plate_name: 'ST股' },
      { plate_name: '公告' }
    ]).map((item) => item.plate_name),
    ['机器人']
  )
  assert.deepEqual(
    [...CHANLUN_EXCLUDED_PLATE_NAMES].sort(),
    ['ST股', 'ST板块', '公告', '其他']
  )
})

test('passes default 30m chanlun filter only when higher segment, segment, bi all satisfy limits', () => {
  assert.equal(
    passesDefaultChanlunFilter({
      ok: true,
      structure: {
        higher_segment: { start_price: 10, end_price: 20 },
        segment: { start_price: 10, end_price: 29.9 },
        bi: { price_change_pct: 30 }
      }
    }).passed,
    true
  )
  assert.equal(
    passesDefaultChanlunFilter({
      ok: true,
      structure: {
        higher_segment: { start_price: 10, end_price: 31 },
        segment: { start_price: 10, end_price: 20 },
        bi: { price_change_pct: 10 }
      }
    }).passed,
    false
  )
})
```

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`

Expected: FAIL，提示 helper 文件或导出不存在

**Step 3: Write minimal implementation**

实现最小纯函数：
- `CHANLUN_EXCLUDED_PLATE_NAMES`
- `filterExcludedPlates(rows)`
- `getSegmentGainMultiple(item)`
- `passesDefaultChanlunFilter(response)`

返回结构至少包含：
- `passed`
- `higher_multiple`
- `segment_multiple`
- `bi_gain_percent`
- `reason`

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/shouban30ChanlunFilter.mjs morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs
git commit -m "test: lock shouban30 default chanlun filter rules"
```

### Task 2: 扩展聚合 helper，支持“通过集”重算板块与标的

**Files:**
- Modify: `morningglory/fqwebui/src/views/shouban30Aggregation.mjs`
- Modify: `morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`
- Reference: `docs/plans/2026-03-09-gantt-shouban30-chanlun-filter-design.md`

**Step 1: Write the failing test**

新增失败测试，覆盖：
- 左栏板块数使用“通过集唯一 code6 数”
- 数量为 0 的板块被过滤
- `agg` 视图以“通过集”而不是原始全集聚合

```javascript
test('aggregate plates use passed stock rows count and drop zero-count plates', () => {
  const plates = aggregatePlateRows({
    xgbPlates: [
      { provider: 'xgb', plate_key: '11', plate_name: 'robotics', seg_to: '2026-03-07', appear_days_30: 2, hit_trade_dates_30: ['2026-03-06', '2026-03-07'] }
    ],
    jygsPlates: [],
    stockRowsByProvider: {
      xgb: {
        '11': [
          { code6: '000001', chanlun_passed: true },
          { code6: '000002', chanlun_passed: false }
        ]
      },
      jygs: {}
    }
  })

  assert.equal(plates[0].stocks_count, 1)
})
```

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`

Expected: FAIL，当前 helper 仍按原始全集统计

**Step 3: Write minimal implementation**

在聚合 helper 中加入：
- 对股票行按 `chanlun_passed` 过滤
- `stocks_count` 基于通过集唯一 `code6` 重算
- `agg` 聚合的板块/标的都基于通过集
- 数量为 0 的板块直接不进入结果

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/shouban30Aggregation.mjs morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs
git commit -m "test: derive shouban30 counts from chanlun-passed stocks"
```

### Task 3: 接入页面缠论请求缓存、并发控制与统计状态

**Files:**
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Modify: `morningglory/fqwebui/src/api/futureApi.js`
- Modify: `morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`

**Step 1: Write the failing test**

新增失败测试，锁定页面必须存在的状态和调用点：
- 结构缓存键使用 `code6 + as_of_date + 30m`
- 复用 `futureApi.getChanlunStructure`
- 切换路由维度时会丢弃旧请求结果

```javascript
import { readFile } from 'node:fs/promises'

test('page uses chanlun cache and existing futureApi.getChanlunStructure', async () => {
  const content = await readFile(
    new URL('./GanttShouban30Phase1.vue', import.meta.url),
    'utf8'
  )

  assert.match(content, /getChanlunStructure/)
  assert.match(content, /chanlunStructureCache/)
  assert.match(content, /chanlunRequestId/)
  assert.match(content, /loadChanlunStructures/)
})
```

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`

Expected: FAIL，页面还没有缠论结构请求编排状态

**Step 3: Write minimal implementation**

在页面中新增最小状态与逻辑：
- `chanlunStructureCache`
- `chanlunStats`
- `chanlunLoading`
- `chanlunRequestId`
- `loadChanlunStructures(candidates, asOfDate)`

要求：
- 候选标的先按 `code6` 去重
- 通过 `futureApi.getChanlunStructure({ symbol, period: '30m', endDate })` 请求
- 固定小并发执行，不使用无限制 `Promise.all`
- 路由切换时旧结果不再覆盖当前状态

如果 `futureApi.js` 没有可复用的导出名，则补一个薄封装，但仍指向现有 `/api/stock_data_chanlun_structure`

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/api/futureApi.js morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs
git commit -m "feat: add shouban30 chanlun structure request orchestration"
```

### Task 4: 将默认筛选结果映射到左栏、中栏与 agg 视图

**Files:**
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Modify: `morningglory/fqwebui/src/views/shouban30Aggregation.mjs`
- Modify: `morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`

**Step 1: Write the failing test**

新增失败测试，覆盖：
- 左栏板块列表只显示“通过数 > 0”的板块
- 左栏数量字段显示通过数
- 中栏只显示通过项
- `agg` 视图不重复请求，只复用 `xgb/jygs` 的结构缓存结果

**Step 2: Run test to verify it fails**

Run:
- `node --test morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`
- `node --test morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`

Expected: FAIL

**Step 3: Write minimal implementation**

页面内做以下修改：
- `loadViewData()` 完成板块/标的原始加载后，再触发结构筛选
- 左栏数据源切换为“通过集板块”
- 中栏数据源切换为“通过集标的”
- 板块数量列标题改为明确文案，例如 `通过数`
- 补一列简短缠论摘要：
  - `高级段倍数`
  - `段倍数`
  - `笔涨幅%`

**Step 4: Run test to verify it passes**

Run:
- `node --test morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`
- `node --test morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/views/shouban30Aggregation.mjs morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs
git commit -m "feat: show only chanlun-passed shouban30 stocks by plate"
```

### Task 5: 保持右栏详情与异常统计可观察

**Files:**
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Modify: `morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`

**Step 1: Write the failing test**

新增失败测试，覆盖：
- 右栏仍使用 `getGanttStockReasons`
- 页面显示：
  - 原始候选总数
  - 缠论通过数
  - 缠论失败或不可用数
- 失败项不会出现在中栏，但会计入统计

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`

Expected: FAIL

**Step 3: Write minimal implementation**

在页面中：
- 保持右栏详情加载链路不变
- 新增轻量统计展示文案
- 明确区分 `candidate_total / passed_total / failed_total`

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs
git commit -m "feat: add shouban30 chanlun filter stats"
```

### Task 6: 回归测试、构建与迁移文档更新

**Files:**
- Modify: `docs/migration/progress.md`
- Verify only: `freshquant/tests/test_chanlun_structure_service.py`
- Verify only: `freshquant/tests/test_stock_data_chanlun_structure_route.py`
- Verify only: `freshquant/tests/test_gantt_routes.py`
- Verify only: `freshquant/tests/test_gantt_readmodel.py`

**Step 1: Run targeted backend tests before final docs update**

Run:
- `py -3.12 -m pytest freshquant/tests/test_chanlun_structure_service.py freshquant/tests/test_stock_data_chanlun_structure_route.py -q`
- `py -3.12 -m pytest freshquant/tests/test_gantt_routes.py freshquant/tests/test_gantt_readmodel.py -q`

Expected: PASS

**Step 2: Run frontend tests**

Run:
- `node --test morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`
- `node --test morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`

Expected: PASS

**Step 3: Run frontend build**

Run: `npm run build`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-gantt-shouban30-optimization\morningglory\fqwebui`

Expected: PASS

**Step 4: Update migration progress**

在 `docs/migration/progress.md` 对应 `0017` 备注中补充：
- 黑名单板块过滤
- 默认 30m 缠论筛选
- 左栏通过数重算
- 按板块展示通过集

**Step 5: Commit**

```bash
git add docs/migration/progress.md
git commit -m "docs: record shouban30 default chanlun filter rollout"
```

### Task 7: 页面级验收

**Files:**
- Verify only

**Step 1: Rebuild the Web UI container**

Run:
- `docker compose -f docker/compose.parallel.yaml build fq_webui`
- `docker compose -f docker/compose.parallel.yaml up -d --force-recreate --no-deps fq_webui`

Expected: PASS

**Step 2: Verify the page in headless Edge**

Run:

```bash
& 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' --headless --disable-gpu --virtual-time-budget=12000 --dump-dom 'http://localhost:18080/gantt/shouban30?p=agg&stock_window_days=30'
```

Expected:
- 页面可打开
- 不再出现 `其他 / 公告 / ST股 / ST板块`
- 左栏存在“通过数”列
- 中栏显示缠论摘要列

**Step 3: Manual spot checks**

手工核对：
- 切换 `xgb / jygs / agg`
- 切换 `30 / 45 / 60 / 90`
- 观察左栏数量是否随筛选结果变化
- 观察右栏详情仍返回历史全量热门理由

**Step 4: Final commit**

```bash
git add .
git commit -m "feat: add shouban30 default chanlun filtering"
```
