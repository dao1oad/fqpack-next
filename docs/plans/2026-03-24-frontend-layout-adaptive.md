# Frontend Layout Adaptive Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor `morningglory/fqwebui` so major workbench pages fit within a `1920x1080` browser viewport at `100%` zoom without browser-level vertical scrolling, using internal component scroll containers instead.

**Architecture:** Move the application from browser-level scrolling to a unified viewport shell. Centralize height and overflow rules in `App.vue` and `workbench-density.css`, then migrate each route page so headers stay in the page shell and long tables, ledgers, and detail panes scroll only inside dedicated containers.

**Tech Stack:** Vue 3, Vite, Element Plus, CSS/Stylus, Node test runner

---

### Task 1: Record the approved design and implementation plan

**Files:**
- Create: `docs/plans/2026-03-24-frontend-layout-adaptive-design.md`
- Create: `docs/plans/2026-03-24-frontend-layout-adaptive.md`

**Step 1: Write the approved design doc**

Capture:

- the `1920x1080 @ 100%` acceptance baseline
- the move from browser scrolling to viewport shell
- the page groups to migrate

**Step 2: Verify the plan files exist**

Run: `Get-ChildItem docs/plans/2026-03-24-frontend-layout-adaptive*`
Expected: both plan files are present

### Task 2: Add failing layout shell regression tests

**Files:**
- Modify: `morningglory/fqwebui/src/views/layoutViewportShell.test.mjs`
- Modify: `morningglory/fqwebui/src/views/legacy-route-shells.test.mjs`
- Create: `morningglory/fqwebui/src/views/workbenchViewportLayout.test.mjs`

**Step 1: Write the failing tests**

Add assertions that:

- `src/App.vue` no longer allows `body` vertical scrolling
- `workbench-density.css` defines viewport shell semantics for `.workbench-page` and `.workbench-body`
- route pages expose explicit internal scroll containers instead of page-level scrolling
- legacy pages still declare dedicated body/table shells

**Step 2: Run tests to verify they fail**

Run: `node --test src/views/layoutViewportShell.test.mjs src/views/legacy-route-shells.test.mjs src/views/workbenchViewportLayout.test.mjs`
Expected: FAIL because the new shell rules are not yet implemented

### Task 3: Refactor the root shell and shared layout CSS

**Files:**
- Modify: `morningglory/fqwebui/src/App.vue`
- Modify: `morningglory/fqwebui/src/style/workbench-density.css`

**Step 1: Write minimal implementation**

Update the root shell so:

- `body` is no longer the main scroll container
- `.app-shell` occupies the viewport
- `.workbench-page` and `.workbench-body` become the standard page skeleton
- shared scroll helper classes exist for panel/list/detail areas

**Step 2: Run tests**

Run: `node --test src/views/layoutViewportShell.test.mjs src/views/workbenchViewportLayout.test.mjs`
Expected: partial PASS or fewer failures limited to individual pages

### Task 4: Migrate the shared workbench pages to internal scrolling

**Files:**
- Modify: `morningglory/fqwebui/src/views/DailyScreening.vue`
- Modify: `morningglory/fqwebui/src/views/OrderManagement.vue`
- Modify: `morningglory/fqwebui/src/views/PositionManagement.vue`
- Modify: `morningglory/fqwebui/src/views/SubjectManagement.vue`
- Modify: `morningglory/fqwebui/src/views/SystemSettings.vue`
- Modify: `morningglory/fqwebui/src/views/TpslManagement.vue`
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Modify: `morningglory/fqwebui/src/views/GanttUnified.vue`
- Modify: `morningglory/fqwebui/src/views/GanttUnifiedStocks.vue`

**Step 1: Update page shells**

For each page:

- remove browser/page-level overflow fallbacks used at desktop widths
- ensure the page root and body are `min-height: 0`
- define which child panel actually scrolls

**Step 2: Add earlier responsive fallback points**

For multi-column layouts:

- switch to single-column before columns begin to overlap
- keep table/ledger/detail panes scrollable inside the page shell

**Step 3: Run tests**

Run: `node --test src/views/layoutViewportShell.test.mjs src/views/workbenchViewportLayout.test.mjs`
Expected: PASS for shared workbench layout assertions

### Task 5: Migrate the legacy route shells

**Files:**
- Modify: `morningglory/fqwebui/src/views/FuturesControl.vue`
- Modify: `morningglory/fqwebui/src/views/StockControl.vue`
- Modify: `morningglory/fqwebui/src/components/StockPools.vue`
- Modify: `morningglory/fqwebui/src/components/StockCjsd.vue`
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`

**Step 1: Align legacy pages with the new viewport shell**

Keep existing page-specific styles, but ensure:

- no desktop browser-level vertical scroll fallback remains
- body/table/chart panes own scrolling
- shell classes still satisfy layout test markers

**Step 2: Run tests**

Run: `node --test src/views/legacy-route-shells.test.mjs src/views/KlineSlim.layout.test.mjs`
Expected: PASS

### Task 6: Run focused verification

**Files:**
- Test: `morningglory/fqwebui/src/views/layoutViewportShell.test.mjs`
- Test: `morningglory/fqwebui/src/views/legacy-route-shells.test.mjs`
- Test: `morningglory/fqwebui/src/views/workbenchViewportLayout.test.mjs`
- Test: `morningglory/fqwebui/src/views/KlineSlim.layout.test.mjs`
- Test: `morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`
- Test: `morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs`

**Step 1: Run the layout-focused test suite**

Run: `node --test src/views/layoutViewportShell.test.mjs src/views/legacy-route-shells.test.mjs src/views/workbenchViewportLayout.test.mjs src/views/KlineSlim.layout.test.mjs src/views/shouban30Aggregation.test.mjs src/views/shouban30PoolWorkspace.test.mjs`
Expected: PASS

**Step 2: Run the frontend production build**

Run: `pnpm build`
Expected: PASS

**Step 3: Review the diff**

Run: `git status --short`
Expected: only the planned front-end and docs files are modified in this worktree
