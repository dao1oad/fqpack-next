# Order Management Entry Aggregation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement conservative buy-entry aggregation, rebuild entry slices from aggregated entries with `50000` lot slicing, align SubjectManagement/KlineSlim stoploss summaries, and add audit-driven rebuild support.

**Architecture:** Keep broker truth untouched in `om_broker_orders / om_execution_fills`, then introduce a shared aggregation layer that merges eligible buy execution groups into clustered `om_position_entries`. Both realtime ingest and rebuild must call the same aggregation rule, and both UIs must render entry stoploss summaries from the same derived view model.

**Tech Stack:** Python, pytest, Mongo repository layer, Vue 3, Node test runner

---

### Task 1: Lock conservative aggregation rules with failing backend tests

**Files:**
- Modify: `freshquant/tests/test_order_management_xt_ingest.py`
- Modify: `freshquant/tests/test_order_ledger_v2_rebuild.py`

**Step 1: Write the failing tests**

- Add ingest tests covering:
  - same symbol + same Beijing trading day + <= 5 minutes + <= 0.3% price deviation => merge into one entry
  - > 5 minutes => new entry
  - > 0.3% => new entry
  - sell between two buy groups => later buy opens a new entry
- Add rebuild tests covering the same scenarios.

**Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_management_xt_ingest.py freshquant/tests/test_order_ledger_v2_rebuild.py -k "aggregate or cluster or 50000" -q`

Expected: FAIL because runtime ingest and rebuild still group buys only by `broker_order`.

**Step 3: Write minimal implementation**

- Add a shared aggregation helper under `freshquant/order_management/` that:
  - evaluates candidate open entries
  - applies the conservative merge rules
  - returns either an updated clustered entry or a new clustered entry payload

**Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_management_xt_ingest.py freshquant/tests/test_order_ledger_v2_rebuild.py -k "aggregate or cluster or 50000" -q`

Expected: PASS.

### Task 2: Switch realtime ingest to clustered entries

**Files:**
- Modify: `freshquant/order_management/ingest/xt_reports.py`
- Modify: `freshquant/order_management/guardian/arranger.py`
- Modify: `freshquant/order_management/repository.py` only if helper queries are needed

**Step 1: Wire ingest through the shared aggregation helper**

- Replace the current “one broker order -> one entry” upsert path with:
  - build broker execution group from buy fills
  - merge into an eligible clustered entry when rules match
  - regenerate that entry’s slices with `arrange_entry(...)`

**Step 2: Preserve traceability**

- Persist cluster metadata such as `aggregation_members` and `aggregation_window`.
- Keep sell-side allocation logic unchanged except that it now targets clustered entries.

**Step 3: Run focused ingest tests**

Run: `.\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_management_xt_ingest.py -q`

Expected: PASS.

### Task 3: Switch rebuild to clustered entries and `50000` slicing

**Files:**
- Modify: `freshquant/order_management/rebuild/service.py`
- Modify: `freshquant/tests/test_order_ledger_v2_rebuild.py`

**Step 1: Rebuild buy entries via the shared aggregation helper**

- Convert replayed buy execution groups into clustered entries using the same conservative rules as realtime ingest.
- Ensure every clustered entry slice set is rebuilt from the clustered quantity and entry price.

**Step 2: Add audit details to rebuild summary**

- Extend rebuild output with audit-friendly fields for:
  - cluster member count
  - non-`50000` slice count
  - replay warnings related to cluster boundaries when needed

**Step 3: Run rebuild tests**

Run: `.\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_ledger_v2_rebuild.py -q`

Expected: PASS.

### Task 4: Align SubjectManagement with KlineSlim stoploss summaries

**Files:**
- Modify: `morningglory/fqwebui/src/views/SubjectManagement.vue`
- Modify: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- Modify: `morningglory/fqwebui/src/views/klineSlim.test.mjs` only if consistency coverage belongs there

**Step 1: Write the failing frontend test**

- Add a regression test proving SubjectManagement stoploss rows show:
  - buy price
  - original quantity
  - remaining quantity
  - buy time
  - remaining market value

**Step 2: Run test to verify it fails**

Run: `cd morningglory/fqwebui; node --test src/views/subjectManagement.test.mjs`

Expected: FAIL because SubjectManagement still renders a compact table row.

**Step 3: Write minimal implementation**

- Reuse the same `entrySummaryDisplay` fields already consumed by `KlineSlim.vue`.
- Update SubjectManagement markup so both pages expose the same summary semantics.

**Step 4: Run frontend tests**

Run: `cd morningglory/fqwebui; node --test src/views/subjectManagement.test.mjs src/views/klineSlim.test.mjs`

Expected: PASS.

### Task 5: Add rebuild audit command output for current-data inspection

**Files:**
- Modify: `script/maintenance/rebuild_order_ledger_v2.py`
- Modify: `freshquant/tests/test_order_ledger_v2_rebuild.py`
- Modify: `docs/current/modules/order-management.md`

**Step 1: Extend dry-run summary**

- Include enough counts in dry-run output to identify:
  - aggregated entry count
  - entries that would be merged
  - non-`50000` slices after replay

**Step 2: Verify the CLI contract**

Run: `.\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_ledger_v2_rebuild.py -k "dry_run or command" -q`

Expected: PASS.

### Task 6: Sync current docs

**Files:**
- Modify: `docs/current/modules/order-management.md`
- Modify: `docs/current/modules/subject-management.md`
- Modify: `docs/current/modules/kline-webui.md`

**Step 1: Update docs to reflect current behavior**

- Document conservative clustered entries, `50000` slicing, and SubjectManagement/KlineSlim summary parity.

**Step 2: Verify docs mention the new runtime facts**

Run: `Select-String -Path 'docs/current/modules/order-management.md','docs/current/modules/subject-management.md','docs/current/modules/kline-webui.md' -Pattern '50000|聚合|剩余市值'`

Expected: Updated wording present.

### Task 7: Verify implementation end-to-end

**Files:**
- Verify only

**Step 1: Run focused backend and frontend tests**

Run: `.\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_management_xt_ingest.py freshquant/tests/test_order_ledger_v2_rebuild.py freshquant/tests/test_system_settings.py freshquant/tests/test_strategy_common.py -q`

Run: `cd morningglory/fqwebui; node --test src/views/subjectManagement.test.mjs src/views/klineSlim.test.mjs src/views/systemSettings.test.mjs`

Expected: PASS.

**Step 2: Inspect current data with dry-run rebuild**

Run: `py -3.12 -m uv run script/maintenance/rebuild_order_ledger_v2.py --dry-run`

Expected: JSON summary clearly shows clustered-entry and slice counts for the live broker-truth snapshot.

**Step 3: Prepare destructive rebuild gate**

- Before any real `--execute`, create the required GitHub Issue describing impact, acceptance criteria, and deployment impact.
