# Subject Entry Slice Pane Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 `subject-management` 与 `kline-slim` 中 open entry 的剩余市值真值，并把 `subject-management` 的止损区改成聚合买入主从两栏切片视图。

**Architecture:** 后端在 `subject_management.dashboard_service` 中统一解析 entry 级有效最新价，过滤 `close_price <= 0` 的脏值，并在需要时用 `market_value / quantity` 推导最新价；前端继续共用 `subjectManagement.mjs` 的 entry 摘要构造逻辑，对 `remaining_market_value <= 0` 和 `latest_price <= 0` 做兜底。`SubjectManagement.vue` 不再使用行内展开，而是把聚合买入列表和切片详情拆成左右两栏 master-detail。

**Tech Stack:** Python, pytest, Vue 3, Element Plus, Node.js test runner

---

### Task 1: 后端 latest price 真值

**Files:**
- Modify: `freshquant/subject_management/dashboard_service.py`
- Test: `freshquant/tests/test_subject_management_service.py`

**Step 1: Write the failing test**

已有 `test_subject_management_detail_derives_latest_price_from_market_value_when_close_price_is_zero` 作为红灯。

**Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest freshquant/tests/test_subject_management_service.py::test_subject_management_detail_derives_latest_price_from_market_value_when_close_price_is_zero -q`
Expected: FAIL because `close_price = 0` is still treated as a valid latest price.

**Step 3: Write minimal implementation**

- 新增 helper 解析有效最新价
- `close_price > 0` 才视为有效
- 若无有效最新价且 `market_value > 0 && quantity > 0`，返回 `market_value / quantity`
- 若仍不可用，`remaining_market_value` 回退 `avg_price * remaining_quantity`

**Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest freshquant/tests/test_subject_management_service.py::test_subject_management_detail_derives_latest_price_from_market_value_when_close_price_is_zero -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/subject_management/dashboard_service.py freshquant/tests/test_subject_management_service.py
git commit -m "fix: derive subject entry latest price from market value"
```

### Task 2: 统一前端剩余市值兜底

**Files:**
- Modify: `morningglory/fqwebui/src/views/subjectManagement.mjs`
- Test: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- Test: `morningglory/fqwebui/src/views/js/kline-slim-subject-panel.test.mjs`

**Step 1: Write the failing test**

已有两个红灯：
- `buildDetailViewModel ignores zero latest-price market values and keeps non-zero fallback labels`
- `normalizeKlineSlimSubjectPanelDetail ignores zero latest-price market values and falls back to avg-price labels`

**Step 2: Run test to verify it fails**

Run: `node --test src/views/subjectManagement.test.mjs src/views/js/kline-slim-subject-panel.test.mjs`
Expected: FAIL with `0.00 万` instead of avg-price fallback label.

**Step 3: Write minimal implementation**

- `remaining_market_value <= 0` 视为无效
- `latest_price <= 0` 视为无效
- open entry 展示优先使用有效后端值，否则回退 `latest_price * remaining_quantity`，再回退 `avg_price * remaining_quantity`

**Step 4: Run test to verify it passes**

Run: `node --test src/views/subjectManagement.test.mjs src/views/js/kline-slim-subject-panel.test.mjs`
Expected: relevant tests PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/subjectManagement.mjs morningglory/fqwebui/src/views/subjectManagement.test.mjs morningglory/fqwebui/src/views/js/kline-slim-subject-panel.test.mjs
git commit -m "fix: guard zero market value entry summaries"
```

### Task 3: Subject Management 止损主从两栏

**Files:**
- Modify: `morningglory/fqwebui/src/views/SubjectManagement.vue`
- Test: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`

**Step 1: Write the failing test**

已有 `SubjectManagement view uses a master-detail stoploss layout instead of expandable slice toggles` 作为红灯。

**Step 2: Run test to verify it fails**

Run: `node --test src/views/subjectManagement.test.mjs`
Expected: FAIL because template still contains `查看切片/收起切片` expandable rows.

**Step 3: Write minimal implementation**

- 删除 `expandedEntrySlices` 和 toggle 逻辑
- 新增 `selectedStoplossEntryId`、`selectedStoplossEntry`、`selectStoplossEntry`
- 左栏显示聚合买入列表与止损编辑保存
- 右栏显示选中聚合买入的 `aggregation_members` 与 `entry_slices`

**Step 4: Run test to verify it passes**

Run: `node --test src/views/subjectManagement.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/SubjectManagement.vue morningglory/fqwebui/src/views/subjectManagement.test.mjs
git commit -m "feat: show aggregated entry slices in master detail pane"
```

### Task 4: 文档与整体验证

**Files:**
- Modify: `docs/current/modules/subject-management.md`
- Modify: `docs/current/modules/kline-webui.md`

**Step 1: Update docs**

- 记录 `subject-management` 止损区改成左右两栏主从结构
- 记录剩余市值的有效价优先级与兜底

**Step 2: Run backend tests**

Run: `.venv\Scripts\python.exe -m pytest freshquant/tests/test_subject_management_service.py -q`
Expected: PASS

**Step 3: Run frontend tests**

Run: `node --test src/views/subjectManagement.test.mjs src/views/js/kline-slim-subject-panel.test.mjs src/views/klineSlim.test.mjs`
Expected: PASS

**Step 4: Commit**

```bash
git add docs/current/modules/subject-management.md docs/current/modules/kline-webui.md
git commit -m "docs: update subject entry slice inspection docs"
```

### Task 5: 合并与部署

**Files:**
- No code changes expected

**Step 1: Push feature branch**

Run: `git push -u origin codex/subject-entry-slice-pane`

**Step 2: Open and merge PR**

- 创建 PR
- 等 CI 通过
- 合并到远程 `main`

**Step 3: Deploy**

- 基于最新远程 `main` SHA 执行 formal deploy
- 受影响面至少包括 API server 和 Web UI

**Step 4: Health check**

- 验证 `/api/subject-management/overview`
- 验证 `/api/subject-management/<symbol>`
- 验证 Web UI 页面加载与数据展示
