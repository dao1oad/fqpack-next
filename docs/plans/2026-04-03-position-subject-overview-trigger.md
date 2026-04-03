# Position Subject Overview Trigger Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 `/position-management` 中栏“标的总览”正确展示最近触发类型与时间，并把门禁等已返回摘要信息直接展示在主表中。

**Architecture:** 后端先把 overview 的最近触发字段补齐为与 detail 一致的结构，前端再基于统一的 overview 行模型拆分“运行态”“门禁”“最近触发”三类展示。主表继续保留 Guardian、止盈、统一配置编辑和 entry 明细，避免为了“最大化展示”而把所有 detail 字段无差别平铺。

**Tech Stack:** Flask blueprint, Python service tests, Vue 3, Element Plus, Node test runner, Vite build

---

### Task 1: 补齐 overview 最近触发字段

**Files:**
- Modify: `freshquant/tests/test_subject_management_service.py`
- Modify: `freshquant/subject_management/dashboard_service.py`

**Step 1: Write the failing test**

- 在 overview 现有服务测试中补断言，要求 `rows[0]["runtime"]["last_trigger_kind"] == "takeprofit"`。

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_subject_management_service.py -k overview_returns_runtime_and_config_summary -q`

Expected: FAIL，提示 overview runtime 中缺少 `last_trigger_kind`。

**Step 3: Write minimal implementation**

- 在 `get_overview()` 里把 `latest_event.get("kind")` 写入 `runtime.last_trigger_kind`。

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_subject_management_service.py -k overview_returns_runtime_and_config_summary -q`

Expected: PASS

### Task 2: 同步前端 overview 行模型与主表列

**Files:**
- Modify: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- Modify: `morningglory/fqwebui/src/views/positionManagementSubjectWorkbench.test.mjs`
- Modify: `morningglory/fqwebui/src/views/subjectManagement.mjs`
- Modify: `morningglory/fqwebui/src/components/position-management/PositionSubjectOverviewPanel.vue`

**Step 1: Write the failing tests**

- 在 `subjectManagement.test.mjs` 中补 overview 行模型断言，要求：
  - `runtimeSummaryLabel` 含最近触发类型。
  - overview 行保留 `runtime.last_trigger_kind`。
- 在 `positionManagementSubjectWorkbench.test.mjs` 中补源码断言，要求主表出现：
  - `label="门禁"`
  - `label="最近触发"`
  - `row.runtime?.last_trigger_kind`

**Step 2: Run tests to verify they fail**

Run: `node --experimental-default-type=module --test src/views/subjectManagement.test.mjs src/views/positionManagementSubjectWorkbench.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui`

Expected: FAIL，说明前端模型和模板尚未消费新字段。

**Step 3: Write minimal implementation**

- `buildOverviewRows()` 增加最近触发类型摘要。
- `PositionSubjectOverviewPanel.vue`：
  - 调整“运行态”列仅展示分类/持仓/市值。
  - 新增“门禁”列，展示 `detailMap[row.symbol]?.positionManagementSummary`。
  - 新增“最近触发”列，展示 `last_trigger_kind + last_trigger_time`。

**Step 4: Run tests to verify they pass**

Run: `node --experimental-default-type=module --test src/views/subjectManagement.test.mjs src/views/positionManagementSubjectWorkbench.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui`

Expected: PASS

### Task 3: 同步正式文档并做完整验证

**Files:**
- Modify: `docs/current/modules/position-management.md`
- Modify: `docs/current/modules/subject-management.md`
- Modify: `docs/current/configuration.md`

**Step 1: Update docs**

- 说明 overview 现已直接展示门禁与最近触发类型/时间。
- 说明 overview/detail 在最近触发字段上已对齐。

**Step 2: Run verification**

Run: `py -3.12 -m pytest freshquant/tests/test_subject_management_service.py -q`

Run: `node --experimental-default-type=module --test src/views/positionManagementSubjectWorkbench.test.mjs src/views/subjectManagement.test.mjs src/views/positionManagement.test.mjs src/views/workbenchDesignSystem.test.mjs src/views/workbenchViewportLayout.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui`

Run: `npm run build`

Workdir: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui`

Expected: 全部通过，前端产物更新到最新源码结构。
