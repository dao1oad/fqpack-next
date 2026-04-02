# Subject Management Overview Scope Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restrict subject management overview rows to holdings and must-pool symbols only.

**Architecture:** Keep `SubjectManagementDashboardService.get_overview()` as the single aggregation point, but change its seed symbol set from a multi-source union to `must_pool + positions`. Guardian, takeprofit, stoploss, and limit summaries remain supplemental data for those seed symbols.

**Tech Stack:** Python, pytest, Flask API, Vue frontend docs

---

### Task 1: Lock the overview scope with failing tests

**Files:**
- Modify: `freshquant/tests/test_subject_management_service.py`

**Step 1: Write the failing test**

- Add a regression test proving that a symbol sourced only from `guardian_buy_grid_configs` and `om_takeprofit_profiles` does not appear in `get_overview()`.

**Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest freshquant/tests/test_subject_management_service.py -k overview -q`

Expected: FAIL because overview still includes config-only symbols.

**Step 3: Write minimal implementation**

- Update `freshquant/subject_management/dashboard_service.py` so overview only seeds rows from `must_pool_rows` and `positions`.

**Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest freshquant/tests/test_subject_management_service.py -k overview -q`

Expected: PASS.

### Task 2: Sync current docs

**Files:**
- Modify: `docs/current/modules/subject-management.md`

**Step 1: Update the overview section**

- State clearly that left-table symbols only come from current holdings and `must_pool`.

**Step 2: Verify docs reflect code**

Run: `Select-String -Path 'docs/current/modules/subject-management.md' -Pattern 'must_pool|持仓'`

Expected: Updated wording present.

### Task 3: Final verification

**Files:**
- Verify only

**Step 1: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest freshquant/tests/test_subject_management_service.py freshquant/tests/test_subject_management_overview_orphan_state.py -q`

Expected: PASS.

**Step 2: Summarize residual risk**

- Confirm this change only affects overview list membership, not detail payloads or stored data.
