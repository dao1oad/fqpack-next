# Subject Entry Slices Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an entry-level slice inspection view to `subject-management` and unify “remaining market value” to latest-price-based semantics.

**Architecture:** Enrich `SubjectManagementDashboardService.get_detail()` with per-entry slice and pricing fields, then render those fields in `subject-management` while keeping `kline-slim` on the same summary model. Use TDD for both the backend payload shape and the frontend rendering/formatting behavior.

**Tech Stack:** Python service layer, Vue view-model modules, Vue SFC templates, pytest, Node test runner

---

### Task 1: Subject Detail Payload

**Files:**
- Modify: `freshquant/subject_management/dashboard_service.py`
- Test: `freshquant/tests/test_subject_management_service.py`

**Step 1: Write the failing test**

- Add a backend test that asserts `get_detail()` returns:
  - `entry_slices` grouped per entry
  - `aggregation_members`
  - `latest_price`
  - latest-price-based `remaining_market_value`
  - avg-price fallback when latest price is unavailable

**Step 2: Run test to verify it fails**

Run: `D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_subject_management_service.py -k "entry_slices or remaining_market_value" -q`

Expected: FAIL because detail payload does not yet include the new fields.

**Step 3: Write minimal implementation**

- Load open entry slices for the symbol.
- Map slices back to each entry.
- Resolve latest price from symbol snapshot `close_price`.
- Compute `remaining_market_value` with latest price first, avg price fallback second.

**Step 4: Run test to verify it passes**

Run the same pytest command and expect PASS.

**Step 5: Commit**

```bash
git add freshquant/subject_management/dashboard_service.py freshquant/tests/test_subject_management_service.py
git commit -m "feat: enrich subject detail entry slice payload"
```

### Task 2: Subject View Model

**Files:**
- Modify: `morningglory/fqwebui/src/views/subjectManagement.mjs`
- Modify: `morningglory/fqwebui/src/views/js/kline-slim-subject-panel.mjs`
- Test: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- Test: `morningglory/fqwebui/src/views/js/kline-slim-subject-panel.test.mjs`

**Step 1: Write the failing test**

- Add frontend tests that assert:
  - `remainingMarketValueLabel` reads from backend-provided latest-price-based field
  - entry rows carry `aggregation_members` and `entry_slices`
  - `kline-slim` normalization stays aligned with `subject-management`

**Step 2: Run test to verify it fails**

Run: `node --test src/views/subjectManagement.test.mjs src/views/js/kline-slim-subject-panel.test.mjs`

Expected: FAIL because the current view-model still derives market value from `runtimeSummary.avg_price`.

**Step 3: Write minimal implementation**

- Stop recomputing market value from `avg_price` in the frontend when the backend field exists.
- Normalize entry-level member/slice arrays into the shared detail view model.

**Step 4: Run test to verify it passes**

Run the same Node test command and expect PASS.

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/subjectManagement.mjs morningglory/fqwebui/src/views/js/kline-slim-subject-panel.mjs morningglory/fqwebui/src/views/subjectManagement.test.mjs morningglory/fqwebui/src/views/js/kline-slim-subject-panel.test.mjs
git commit -m "feat: align subject entry summary pricing fields"
```

### Task 3: Subject Management UI

**Files:**
- Modify: `morningglory/fqwebui/src/views/SubjectManagement.vue`
- Test: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`

**Step 1: Write the failing test**

- Add a UI-level test that asserts each entry row can expose:
  - aggregation member summary
  - slice list table / expanded section
  - latest-price-based remaining market value label

**Step 2: Run test to verify it fails**

Run: `node --test src/views/subjectManagement.test.mjs`

Expected: FAIL because the current template has no slice expansion area.

**Step 3: Write minimal implementation**

- Add a compact expandable section under each entry row.
- Render aggregation members first, then slices.
- Keep the default row height compact when collapsed.

**Step 4: Run test to verify it passes**

Run the same Node test command and expect PASS.

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/SubjectManagement.vue morningglory/fqwebui/src/views/subjectManagement.test.mjs
git commit -m "feat: show entry slice details in subject management"
```

### Task 4: Kline Summary Consistency

**Files:**
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`
- Test: `morningglory/fqwebui/src/views/klineSlim.test.mjs`

**Step 1: Write the failing test**

- Add a test asserting `kline-slim` still shows the same updated entry summary field labels and does not regress into local avg-price-only wording.

**Step 2: Run test to verify it fails**

Run: `node --test src/views/klineSlim.test.mjs`

Expected: FAIL if the template still relies on the old local wording or misses the new field shape.

**Step 3: Write minimal implementation**

- Keep summary field usage aligned with the shared detail model.
- Do not add the full slice table here.

**Step 4: Run test to verify it passes**

Run the same Node test command and expect PASS.

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/src/views/klineSlim.test.mjs
git commit -m "test: lock kline slim entry summary consistency"
```

### Task 5: Docs And Verification

**Files:**
- Modify: `docs/current/modules/subject-management.md`
- Modify: `docs/current/modules/kline-webui.md`
- Modify: `docs/current/modules/order-management.md`

**Step 1: Update current docs**

- Document that `subject-management` is the primary entry-level slice inspection page.
- Document that remaining market value now prefers latest price.

**Step 2: Run verification**

Run:

```bash
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_subject_management_service.py freshquant/tests/test_symbol_position_service.py -q
node --test src/views/subjectManagement.test.mjs src/views/klineSlim.test.mjs src/views/js/kline-slim-subject-panel.test.mjs
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pre_commit run --files freshquant/subject_management/dashboard_service.py freshquant/tests/test_subject_management_service.py morningglory/fqwebui/src/views/SubjectManagement.vue morningglory/fqwebui/src/views/subjectManagement.mjs morningglory/fqwebui/src/views/subjectManagement.test.mjs morningglory/fqwebui/src/views/js/kline-slim-subject-panel.mjs morningglory/fqwebui/src/views/js/kline-slim-subject-panel.test.mjs morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/src/views/klineSlim.test.mjs docs/current/modules/subject-management.md docs/current/modules/kline-webui.md docs/current/modules/order-management.md
```

Expected: all pass.

**Step 3: Commit**

```bash
git add docs/current/modules/subject-management.md docs/current/modules/kline-webui.md docs/current/modules/order-management.md
git commit -m "docs: document entry slice inspection semantics"
```
