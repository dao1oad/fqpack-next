# Gantt Shouban30 聚合视图 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `/gantt/shouban30` 增加 `XGB / JYGS / 聚合` 三标签视图、左栏统计和新的板块排序/列展示，并保持现有下钻交互。

**Architecture:** 在前端新增纯聚合 helper，Vue 页面并行拉取 `xgb/jygs` 两份数据后按当前标签计算展示结果。后端接口保持不变，测试优先覆盖 helper 规则和页面数据流，再回归构建与页面级验证。

**Tech Stack:** Vue 3、Vite、Axios、Element Plus、Node `node:test`、pytest、Docker Compose、Edge headless

---

### Task 1: 设计前端聚合 helper 与测试入口

**Files:**
- Create: `morningglory/fqwebui/src/views/shouban30Aggregation.js`
- Create: `morningglory/fqwebui/src/views/shouban30Aggregation.test.js`
- Modify: `morningglory/fqwebui/package.json`

**Step 1: Write the failing test**

为 helper 写失败测试，覆盖：
- `sortPlateRows()` 按 `seg_to desc`
- `buildAggregatedPlates()` 对同名板块合并
- `buildAggregatedStocks()` 对同 `code6` 去重
- `buildStats()` 统计去重后的板块数与个股数

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/shouban30Aggregation.test.js`
Expected: FAIL，提示 helper 未实现或导出缺失

**Step 3: Write minimal implementation**

实现最小纯函数，输入原始 `xgb/jygs` 板块和标的数据，输出：
- 排序后的单源板块
- 聚合板块
- 聚合标的
- 统计对象

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/shouban30Aggregation.test.js`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/package.json morningglory/fqwebui/src/views/shouban30Aggregation.js morningglory/fqwebui/src/views/shouban30Aggregation.test.js
git commit -m "feat: add shouban30 aggregation helpers"
```

### Task 2: 接入页面状态与布局调整

**Files:**
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`

**Step 1: Write the failing test**

在 `shouban30Aggregation.test.js` 增补一个面向页面状态的失败用例，验证：
- 切到聚合标签时板块和标的是聚合结果
- 单源标签仍保持单源排序结果

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/shouban30Aggregation.test.js`
Expected: FAIL，说明当前页面所需 helper 输出不完整

**Step 3: Write minimal implementation**

在页面中：
- 把标签和窗口按钮移到左栏上方
- 新增 `agg` 标签
- 并行拉取 `xgb/jygs` 板块
- 依据当前标签切换 `plates`、统计信息和下钻来源
- 将左栏“连续段”列改为“最后上板”

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/shouban30Aggregation.test.js`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/GanttShouban30Phase1.vue
git commit -m "feat: add shouban30 aggregate tab and layout"
```

### Task 3: 接入聚合标的下钻与统计

**Files:**
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Modify: `morningglory/fqwebui/src/views/shouban30Aggregation.js`
- Modify: `morningglory/fqwebui/src/views/shouban30Aggregation.test.js`

**Step 1: Write the failing test**

新增失败测试，验证：
- 聚合板块下钻时会按 `code6` 聚合标的
- 中栏排序为 `latest_trade_date desc -> hit_count_window desc -> code6 asc`
- 标签统计使用去重后的 `code6`

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/shouban30Aggregation.test.js`
Expected: FAIL

**Step 3: Write minimal implementation**

实现：
- 聚合板块下钻的来源映射
- 并行拉取原始标的列表并聚合
- 中栏统计和默认选中

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/shouban30Aggregation.test.js`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/views/shouban30Aggregation.js morningglory/fqwebui/src/views/shouban30Aggregation.test.js
git commit -m "feat: aggregate shouban30 stocks by code6"
```

### Task 4: 更新进度文档与构建产物

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `morningglory/fqwebui/web/index.html`
- Modify: `morningglory/fqwebui/web/assets/*`

**Step 1: Write the failing test**

这里没有单独代码测试，使用构建和页面验证作为回归门禁。

**Step 2: Run verification before implementation**

Run: `npm run build`
Expected: PASS，但页面仍未包含新交互前不作为完工依据

**Step 3: Write minimal implementation**

更新 `progress.md` 的 0017 备注，记录聚合标签、排序和统计扩展；重新生成 `web/` 构建产物。

**Step 4: Run build to verify it passes**

Run: `npm run build`
Expected: PASS

**Step 5: Commit**

```bash
git add docs/migration/progress.md morningglory/fqwebui/web
git commit -m "docs: record shouban30 aggregate ui update"
```

### Task 5: 全量验证与页面级验收

**Files:**
- Verify only

**Step 1: Run targeted backend tests**

Run: `py -m pytest freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py freshquant/tests/test_gantt_dagster_ops.py -q`
Expected: PASS

**Step 2: Run frontend tests**

Run: `node --test morningglory/fqwebui/src/views/shouban30Aggregation.test.js`
Expected: PASS

**Step 3: Run frontend build**

Run: `npm run build`
Expected: PASS

**Step 4: Rebuild and verify page**

Run:
- `docker compose -f docker/compose.parallel.yaml build --no-cache fq_webui`
- `docker compose -f docker/compose.parallel.yaml up -d --force-recreate --no-deps fq_webui`
- `& 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' --headless --disable-gpu --virtual-time-budget=12000 --dump-dom 'http://localhost:18080/gantt/shouban30?p=agg&stock_window_days=30'`

Expected:
- 页面出现 `聚合`
- 左栏显示统计信息
- 左栏按最后上板时间排序

**Step 5: Commit**

```bash
git add .
git commit -m "feat: add shouban30 aggregate tab"
```
