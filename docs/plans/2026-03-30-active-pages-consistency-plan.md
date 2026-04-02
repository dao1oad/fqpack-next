# Active Pages Consistency Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 下线 `MyHeader` 中的废弃页面入口，将 `/` 默认页切到 `RuntimeObservability`，并把保留主导航页面统一到共享 workbench 页面 contract。

**Architecture:** 先做信息架构收口，再做删除与测试清理，最后按页面家族推进一致性治理。`RuntimeObservability.vue` 作为默认模板页；`StockControl.vue` 并入主工作台页；`KlineSlim.vue` 保留为唯一焦点页变体；`stock pool` 业务能力继续留在仍活跃的页面流里。

**Tech Stack:** Vue 3, Vue Router, Vite, Element Plus, TanStack Vue Query, Node test, Playwright smoke, docs/current

---

### Task 1: 收口默认页与主导航元信息

**Files:**
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\router\index.js`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\router\pageMeta.mjs`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\MyHeader.vue`
- Test: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\router\pageMeta.test.mjs`

**Step 1: 写失败测试，锁住新导航结构**

- 断言 `/` 重定向到 `/runtime-observability`
- 断言 `HEADER_NAV_GROUPS` 不再包含 `futures / pool / cjsd`
- 断言“运行观测”仍能解析成合法导航目标

**Step 2: 跑定向测试确认失败**

Run:

```powershell
node --test src/router/pageMeta.test.mjs
```

Expected:

- 至少一条与旧重定向或旧分组相关的断言失败

**Step 3: 做最小实现**

- 把根路由默认重定向改为 `/runtime-observability`
- 从 `pageMeta.mjs` 中删除 `futures / pool / cjsd`
- 调整 `ROUTE_TITLES_BY_NAME` 与导航分组
- 让 `MyHeader.vue` 只渲染保留页面

**Step 4: 重新运行测试**

Run:

```powershell
node --test src/router/pageMeta.test.mjs
```

Expected:

- 全部通过

**Step 5: 提交**

```powershell
git add morningglory/fqwebui/src/router/index.js morningglory/fqwebui/src/router/pageMeta.mjs morningglory/fqwebui/src/views/MyHeader.vue morningglory/fqwebui/src/router/pageMeta.test.mjs
git commit -m "frontend: retire deprecated header pages"
```

### Task 2: 安全删除废弃页面入口

**Files:**
- Delete: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\FuturesControl.vue`
- Delete: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\FuturePositionList.vue`
- Delete: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\js\future-control.js`
- Delete: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\style\futures-control.styl`
- Delete: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\components\StockPools.vue`
- Delete: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\components\StockCjsd.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\router\index.js`

**Step 1: 写失败测试，锁住页面入口被清理**

- `router/index.js` 不再导入与绑定这三条路由
- 删除页不再出现在 lazy route 清单中

**Step 2: 跑定向测试确认失败**

Run:

```powershell
node --test src/router/pageMeta.test.mjs tests/build-budget.test.mjs
```

Expected:

- 旧 route / chunk 断言失败

**Step 3: 删除页面文件并移除路由绑定**

- 删除上述页面层文件
- 从 router 中删掉三条路由及对应 import
- 不删除 `stockApi.js`、`DailyScreening.vue`、`GanttShouban30Phase1.vue`、`klineSlimController.mjs` 中仍活跃的 `stock pool` 业务逻辑

**Step 4: 重新运行定向测试**

Run:

```powershell
node --test src/router/pageMeta.test.mjs
```

Expected:

- 路由相关断言通过

**Step 5: 提交**

```powershell
git add morningglory/fqwebui/src/router/index.js morningglory/fqwebui/src/views morningglory/fqwebui/src/components morningglory/fqwebui/src/style
git commit -m "frontend: delete deprecated page entrypoints"
```

### Task 3: 清理删除页绑定的测试与预算护栏

**Files:**
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\legacy-route-shells.test.mjs`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\legacyTemplateCompat.test.mjs`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\workbenchDesignSystem.test.mjs`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\tests\build-budget.test.mjs`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\tests\frontend-quality-gates.test.mjs`

**Step 1: 先写失败测试或让现有测试暴露旧依赖**

Run:

```powershell
npm run test:unit
```

Expected:

- 出现删除页相关失败

**Step 2: 调整测试与预算基线**

- 从 route shell / design system / legacy compat 断言中移除废弃页面
- 从 bundle budget 的 legacy route chunk 清单里移除 `FuturesControl / StockPools / StockCjsd`
- 从 frontend quality gates 的 legacy futures 专项约束中删去不再存在的文件引用

**Step 3: 重新跑单测**

Run:

```powershell
npm run test:unit
```

Expected:

- 单测恢复通过

**Step 4: 提交**

```powershell
git add morningglory/fqwebui/src/views/*.test.mjs morningglory/fqwebui/tests/*.test.mjs
git commit -m "test: drop deprecated page coverage baselines"
```

### Task 4: 把 RuntimeObservability 设为主工作台模板页

**Files:**
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\workbenchDesignSystem.test.mjs`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\layoutViewportShell.test.mjs`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\RuntimeObservability.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\components\workbench\*.vue`（仅当缺共享原语时）

**Step 1: 增加模板页 contract 测试**

- 锁住 `RuntimeObservability` 的页头、toolbar、summary、sidebar/ledger/detail 结构
- 锁住页面级 error / empty / loading 的标准写法

**Step 2: 跑定向测试**

Run:

```powershell
node --test src/views/workbenchDesignSystem.test.mjs src/views/layoutViewportShell.test.mjs
```

**Step 3: 若缺少共享原语，再补最小公共抽象**

- 只抽“重复块”，不重写整页
- 优先考虑 `PageHeader`、`ErrorState`、`EmptyState`、`PaginationStrip` 这类轻原语

**Step 4: 重跑测试**

Run:

```powershell
node --test src/views/workbenchDesignSystem.test.mjs src/views/layoutViewportShell.test.mjs src/views/runtime-observability.test.mjs
```

**Step 5: 提交**

```powershell
git add morningglory/fqwebui/src/views/RuntimeObservability.vue morningglory/fqwebui/src/components/workbench morningglory/fqwebui/src/views/*.test.mjs
git commit -m "frontend: lock runtime observability as the default page contract"
```

### Task 5: 把 StockControl 并入主工作台页 contract

**Files:**
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\StockControl.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\workbenchDesignSystem.test.mjs`
- Test: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\stockControlLedger.test.mjs`

**Step 1: 写失败测试**

- 断言 `StockControl` 具备统一页头、副标题、摘要区与 panel header 语法
- 断言不再被当成特殊类别对待

**Step 2: 跑定向测试**

Run:

```powershell
node --test src/views/workbenchDesignSystem.test.mjs src/views/stockControlLedger.test.mjs
```

**Step 3: 做最小改造**

- 用统一 toolbar/header 语言对齐 `RuntimeObservability`
- 保留三栏工作台结构，不重写业务子表

**Step 4: 复跑测试**

Run:

```powershell
node --test src/views/workbenchDesignSystem.test.mjs src/views/stockControlLedger.test.mjs
```

**Step 5: 提交**

```powershell
git add morningglory/fqwebui/src/views/StockControl.vue morningglory/fqwebui/src/views/workbenchDesignSystem.test.mjs morningglory/fqwebui/src/views/stockControlLedger.test.mjs
git commit -m "frontend: align stock control with the active workbench contract"
```

### Task 6: 对齐主工作台管理页的一致性 contract

**Files:**
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\OrderManagement.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\PositionManagement.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\SubjectManagement.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\TpslManagement.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\SystemSettings.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\workbenchDesignSystem.test.mjs`

**Step 1: 增加 contract 测试**

- 页头标题/副标题
- toolbar 操作区
- 页面级 `el-alert`
- `workbench-empty` 或 `el-empty`
- panel header 统一结构

**Step 2: 跑定向测试**

Run:

```powershell
node --test src/views/workbenchDesignSystem.test.mjs
```

**Step 3: 按最小改动对齐**

- 不重写数据流
- 只统一结构、状态反馈和交互位置

**Step 4: 验证**

Run:

```powershell
npm run test:unit
```

**Step 5: 提交**

```powershell
git add morningglory/fqwebui/src/views/OrderManagement.vue morningglory/fqwebui/src/views/PositionManagement.vue morningglory/fqwebui/src/views/SubjectManagement.vue morningglory/fqwebui/src/views/TpslManagement.vue morningglory/fqwebui/src/views/SystemSettings.vue morningglory/fqwebui/src/views/workbenchDesignSystem.test.mjs
git commit -m "frontend: normalize active management page shells"
```

### Task 7: 对齐研究/筛选页的一致性 contract

**Files:**
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\DailyScreening.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\GanttUnified.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\GanttUnifiedStocks.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\GanttShouban30Phase1.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\workbenchDesignSystem.test.mjs`

**Step 1: 写失败测试**

- 锁住筛选页的 toolbar、结果区、详情区与工作区面板结构
- 锁住空态与 loading 语义

**Step 2: 跑定向测试**

Run:

```powershell
node --test src/views/workbenchDesignSystem.test.mjs src/views/shouban30*.test.mjs src/views/dailyScreening*.test.mjs
```

**Step 3: 实现**

- 统一筛选页标题和摘要语法
- 统一结果区 panel 结构
- 保留各自业务差异，不强行做成相同布局

**Step 4: 验证**

Run:

```powershell
npm run test:unit
npm run test:browser-smoke
```

**Step 5: 提交**

```powershell
git add morningglory/fqwebui/src/views/DailyScreening.vue morningglory/fqwebui/src/views/GanttUnified.vue morningglory/fqwebui/src/views/GanttUnifiedStocks.vue morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/views/*.test.mjs
git commit -m "frontend: align active research pages with the workbench contract"
```

### Task 8: 收口 KlineSlim 作为唯一焦点页变体

**Files:**
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\KlineSlim.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\KlineSlim.layout.test.mjs`
- Modify: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui\src\views\workbenchDesignSystem.test.mjs`

**Step 1: 写失败测试**

- 锁住它是焦点页而不是普通管理页
- 同时锁住 header、status chip、empty/error 仍使用共享语法

**Step 2: 跑定向测试**

Run:

```powershell
node --test src/views/KlineSlim.layout.test.mjs src/views/klineSlim.test.mjs src/views/workbenchDesignSystem.test.mjs
```

**Step 3: 实现最小收口**

- 保留图表中心布局
- 统一顶部信息区与状态反馈
- 不重做图表业务逻辑

**Step 4: 验证**

Run:

```powershell
node --test src/views/KlineSlim.layout.test.mjs src/views/klineSlim.test.mjs
```

**Step 5: 提交**

```powershell
git add morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/src/views/KlineSlim.layout.test.mjs morningglory/fqwebui/src/views/klineSlim.test.mjs morningglory/fqwebui/src/views/workbenchDesignSystem.test.mjs
git commit -m "frontend: keep kline slim as the single focus-page variant"
```

### Task 9: 更新正式文档并完成整体验证

**Files:**
- Modify: `D:\fqpack\freshquant-2026.2.23\docs\current\overview.md`
- Modify: `D:\fqpack\freshquant-2026.2.23\docs\current\architecture.md`
- Modify: `D:\fqpack\freshquant-2026.2.23\docs\current\modules\runtime-observability.md`
- Modify: `D:\fqpack\freshquant-2026.2.23\docs\current\modules\kline-webui.md`
- Modify: 任何仍描述旧导航与旧默认页的 `docs/current/**`

**Step 1: 文档同步**

- 说明默认页已改为 `RuntimeObservability`
- 说明 `期货 / 股票池 / 超级赛道` 已下线
- 说明 active pages 的一致性 contract 以 runtime workbench 为基准

**Step 2: 运行最终验证**

Run:

```powershell
npm run lint
npm run test:unit
npm run test:browser-smoke
npm run build
```

Expected:

- 全部通过

**Step 3: 提交**

```powershell
git add docs/current morningglory/fqwebui
git commit -m "docs: document the active page consistency contract"
```
