# Runtime Observability Dense Ledger Follow-up Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Tighten the runtime-observability dense ledger so the global Trace table prioritizes node-path visibility, the selected-step detail becomes a compact table layout, and the issue-step trace switching bug is fixed.

**Architecture:** Keep the current runtime-observability page shell and API contract, but rebalance the front-end around two changes: a scroll-prioritized trace ledger in the center panel and a table-only selected-step inspector in the right panel. Fix trace switching by resetting stale detail state before loading a new trace and ignoring stale async responses.

**Tech Stack:** Vue 3, Element Plus, CSS grid, Node test runner, Python pytest

---

### Task 1: Record the approved design and plan

**Files:**
- Create: `docs/plans/2026-03-25-runtime-observability-density-fix-design.md`
- Create: `docs/plans/2026-03-25-runtime-observability-density-fix.md`

**Step 1: Write the approved design doc**

Capture:

- the trace-ledger width rebalance
- the right-panel dense table detail target
- the trace-switch stale payload bug root cause

**Step 2: Verify the plan files exist**

Run: `Get-ChildItem docs/plans/2026-03-25-runtime-observability-density-fix*`
Expected: both design and implementation plan files are present

### Task 2: Add failing frontend regression tests for layout and trace switching

**Files:**
- Modify: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: Write the failing layout assertions**

Add assertions that [`morningglory/fqwebui/src/views/RuntimeObservability.vue`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/RuntimeObservability.vue):

- uses a narrower `标的` column
- uses a narrower `信号备注` column
- wraps the trace ledger in a horizontal scroll container
- gives `节点路径` a larger primary track
- keeps `节点数 / 总耗时 / 断裂原因` on the same ledger row

**Step 2: Write the failing selected-step detail assertions**

Add assertions that the `steps` tab:

- no longer depends on `step-inspector-head`
- renders dense table sections for step detail
- keeps the detail area internally scrollable

**Step 3: Write the failing trace-switch bug regression**

Add a state-level regression that proves:

- when `onlyIssues` is true
- and the user clicks a different trace row
- the selected step and detail data must switch to the new trace instead of reusing stale payload

**Step 4: Run the tests to verify they fail**

Run: `node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs`
Expected: FAIL because the new layout hooks and trace reset behavior do not exist yet

### Task 3: Add step-detail table helpers and trace-switch guardrails

**Files:**
- Modify: `morningglory/fqwebui/src/views/runtimeObservability.mjs`
- Modify: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: Add dense selected-step detail row helpers**

Implement helpers that convert the selected step into grouped table rows, for example:

```js
{
  section: 'basic',
  rows: [
    { key: 'component', label: '组件', value: 'guardian_strategy' },
    { key: 'node', label: '节点', value: '价格阈值判断' },
  ],
}
```

**Step 2: Add trace ledger width metadata if needed**

Keep `buildTraceLedgerRows()` compatible with the current API response, but expose any new row fields needed by the denser center ledger.

**Step 3: Run the focused test subset**

Run: `node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs`
Expected: still FAIL on Vue structure/state behavior until the component is updated

### Task 4: Rebalance the center Trace ledger for node-path priority

**Files:**
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Test: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: Introduce a ledger scroll container**

Wrap the center trace ledger in a panel-local horizontal scroll container so the page shell itself does not scroll.

**Step 2: Shrink the `标的` and `信号备注` columns**

Change the grid widths so both columns are roughly 60% of their current width.

**Step 3: Expand `节点路径`**

Give `节点路径` the dominant flexible track and keep the tail stats visible through horizontal scrolling instead of squeezing the whole row.

**Step 4: Run the tests**

Run: `node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs`
Expected: layout assertions PASS

### Task 5: Replace the selected-step inspector with dense tables

**Files:**
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Modify: `morningglory/fqwebui/src/views/runtimeObservability.mjs`
- Test: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: Remove card-style detail head usage from the `steps` tab**

Replace the existing `step-inspector-head` + chip-heavy structure with grouped `detail-kv-table` sections.

**Step 2: Render grouped detail sections**

Render:

- `基础字段`
- `判断字段`
- `Guardian 上下文`
- `异常信息`
- `原始 JSON`

using the new helper output.

**Step 3: Keep detail scrolling inside the right panel**

Ensure the detail table container uses internal vertical scrolling and still fits in `1920x1080 / 100%` without browser-level page scroll.

**Step 4: Run the tests**

Run: `node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs`
Expected: selected-step detail assertions PASS

### Task 6: Fix stale trace detail when switching traces in issue-step mode

**Files:**
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Test: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: Reset stale detail state before loading a new trace**

When `handleTraceClick()` changes to a different trace key:

- call `resetSelectedTraceDetailState()`
- set the new `selectedTrace`
- load the new detail

**Step 2: Guard async detail responses**

Add a request token or trace-key check inside `loadTraceDetail()` so an earlier slow response cannot overwrite a newer trace selection.

**Step 3: Keep default selected-step behavior aligned with the current filtered steps**

After the new trace detail arrives, reselect from the current trace only, respecting `onlyIssues`.

**Step 4: Run the tests**

Run: `node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs`
Expected: issue-step trace switching regression PASS

### Task 7: Sync docs and run focused verification

**Files:**
- Modify: `docs/current/modules/runtime-observability.md`
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Modify: `morningglory/fqwebui/src/views/runtimeObservability.mjs`
- Modify: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: Update current docs**

Document:

- the tighter trace-ledger width priorities
- the right-panel dense step-detail tables
- the fixed trace-switch behavior in issue-step mode

**Step 2: Run focused verification**

Run:

- `node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs`
- `D:\\fqpack\\freshquant-2026.2.23\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_runtime_observability_routes.py freshquant/tests/test_runtime_observability_clickhouse.py freshquant/tests/test_runtime_observability_docs.py -q`

Expected: PASS

**Step 3: Review the final diff**

Run: `git status --short`
Expected: only the planned runtime-observability docs and frontend files are modified
