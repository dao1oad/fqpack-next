# TPSL Page Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove symbol-level takeprofit editing from `/tpsl`, surface the three takeprofit prices in the left symbol list, and add `stock_fills` comparison data to TPSL detail.

**Architecture:** Keep `/api/tpsl/management/<symbol>` as the single detail source. Extend `TpslManagementService` to aggregate `stock_fills`, then simplify the Vue page so the left list becomes a read-only takeprofit summary and the right panel adds a `stock_fills` table while removing the takeprofit editor.

**Tech Stack:** Python 3.12, Flask service layer, Vue 3, Element Plus, Node test runner, pytest

---

### Task 1: Document the approved design

**Files:**
- Create: `docs/plans/2026-03-22-tpsl-page-optimization-design.md`
- Create: `docs/plans/2026-03-22-tpsl-page-optimization.md`

**Step 1: Write the design doc**

Record the approved scope:

- remove TPSL page takeprofit editor
- show `L1/L2/L3` in the left symbol card
- add `stock_fills` to the symbol detail payload and page

**Step 2: Verify files exist**

Run: `Get-ChildItem docs/plans/2026-03-22-tpsl-page-optimization*`
Expected: both plan files are present

### Task 2: Add the failing backend regression test

**Files:**
- Modify: `freshquant/tests/test_tpsl_management_service.py`
- Modify: `freshquant/tpsl/management_service.py`

**Step 1: Write the failing test**

Add a test that calls `get_symbol_detail("600000")` with:

- a fake takeprofit profile containing three tiers
- a fake buy lot
- a stubbed `stock_fills` loader returning two fill rows

Assert that the returned detail includes:

- `takeprofit.tiers` unchanged
- `stock_fills` with the expected rows
- JSON-safe scalar values

**Step 2: Run test to verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_tpsl_management_service.py -q`
Expected: FAIL because `stock_fills` is not yet returned by the service

**Step 3: Write minimal implementation**

Update `TpslManagementService` to:

- accept an injectable `stock_fills_loader`
- default to `freshquant.data.astock.holding.get_stock_fills`
- normalize the DataFrame output into a list of dictionaries
- add `stock_fills` to `get_symbol_detail()`

**Step 4: Run test to verify it passes**

Run: `.\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_tpsl_management_service.py -q`
Expected: PASS

### Task 3: Add the failing frontend regression test

**Files:**
- Modify: `morningglory/fqwebui/src/views/tpslManagement.test.mjs`
- Modify: `morningglory/fqwebui/src/views/tpslManagement.mjs`
- Modify: `morningglory/fqwebui/src/views/tpslManagementPage.mjs`
- Modify: `morningglory/fqwebui/src/views/TpslManagement.vue`

**Step 1: Write the failing test**

Add assertions that:

- `buildOverviewRows()` exposes a `takeprofitSummary` or equivalent display-ready labels for `L1/L2/L3`
- `buildDetailViewModel()` preserves `stock_fills`
- the page source no longer contains the `标的止盈层次` editor section
- the page source contains the new `stock_fills` comparison section

**Step 2: Run test to verify it fails**

Run: `node --test src/views/tpslManagement.test.mjs`
Expected: FAIL because the new summary/data fields and template changes do not exist yet

**Step 3: Write minimal implementation**

Update the view model/controller/page to:

- expose the first three takeprofit tier prices for the left symbol cards
- drop takeprofit draft editing state and save/toggle handlers from the page
- keep `Rearm` as a detail-level action
- render a `stock_fills` comparison table in the right panel

**Step 4: Run test to verify it passes**

Run: `node --test src/views/tpslManagement.test.mjs`
Expected: PASS

### Task 4: Update current module documentation

**Files:**
- Modify: `docs/current/modules/tpsl.md`

**Step 1: Update current-state doc**

Revise the TPSL module doc so it states:

- `/tpsl` no longer edits symbol-level takeprofit tiers
- left symbol cards show the three takeprofit prices read-only
- detail includes `stock_fills` comparison data

**Step 2: Verify docs-only diff is accurate**

Run: `git diff -- docs/current/modules/tpsl.md`
Expected: only current-state wording changes relevant to this task

### Task 5: Run focused verification

**Files:**
- Test: `freshquant/tests/test_tpsl_management_service.py`
- Test: `freshquant/tests/test_tpsl_routes.py`
- Test: `morningglory/fqwebui/src/views/tpslManagement.test.mjs`

**Step 1: Run backend tests**

Run: `.\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_tpsl_management_service.py freshquant/tests/test_tpsl_routes.py -q`
Expected: PASS

**Step 2: Run frontend tests**

Run: `node --test src/views/tpslManagement.test.mjs`
Expected: PASS

**Step 3: Review diff**

Run: `git status --short`
Expected: only the planned files are modified in this worktree
