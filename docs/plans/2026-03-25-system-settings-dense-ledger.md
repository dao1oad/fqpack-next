# System Settings Dense Ledger Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor `/system-settings` into a three-column dense ledger workspace that shows all formal settings at once, supports direct inline editing, and keeps Bootstrap and Mongo saves separate.

**Architecture:** Keep `/api/system-config/dashboard` and the existing save endpoints as the data contract. Move the front-end from hardcoded form sections to a row-based rendering pipeline: flatten backend sections into dense ledger rows, map each field path to an inline editor, compute dirty/inactive states, and render the page as three independently scrolling columns plus a readonly strategies ledger.

**Tech Stack:** Vue 3, Element Plus, Stylus, Node test runner, Vite

---

### Task 1: Record the approved design and plan

**Files:**
- Create: `docs/plans/2026-03-25-system-settings-dense-ledger-design.md`
- Create: `docs/plans/2026-03-25-system-settings-dense-ledger.md`

**Step 1: Write the approved design doc**

Capture:

- the three-column dense ledger target
- the inline editing requirement
- the row-based rendering model
- the Guardian all-fields-visible rule

**Step 2: Verify the plan files exist**

Run: `Get-ChildItem docs/plans/2026-03-25-system-settings-dense-ledger*`
Expected: both design and implementation plan files are present

### Task 2: Add failing row-schema and layout regression tests

**Files:**
- Modify: `morningglory/fqwebui/src/views/systemSettings.test.mjs`
- Modify: `morningglory/fqwebui/src/views/system-settings.test.mjs`

**Step 1: Write the failing data-shaping tests**

Add assertions that:

- backend `sections` can flatten into stable dense rows
- rows expose column assignment and editor type metadata
- Guardian `percent` and `atr.*` rows remain present regardless of active mode

Example assertion shape:

```js
const rows = buildSettingsLedgerRows(payload)
assert.equal(rows.find((row) => row.key === 'guardian.stock.threshold.percent').inactive, false)
assert.equal(rows.find((row) => row.key === 'guardian.stock.threshold.atr.period').present, true)
```

**Step 2: Write the failing structure test**

Add assertions that [`morningglory/fqwebui/src/views/SystemSettings.vue`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/SystemSettings.vue):

- declares a three-column dense workspace
- uses ledger row/header classes
- does not contain legacy `panel-card` markup

**Step 3: Run tests to verify they fail**

Run: `node --test src/views/systemSettings.test.mjs src/views/system-settings.test.mjs`
Expected: FAIL because row schema helpers and the new dense layout do not exist yet

### Task 3: Build dense row helpers in `systemSettings.mjs`

**Files:**
- Modify: `morningglory/fqwebui/src/views/systemSettings.mjs`
- Test: `morningglory/fqwebui/src/views/systemSettings.test.mjs`

**Step 1: Add row flatten helpers**

Implement helpers that:

- read `bootstrap.sections` and `settings.sections`
- flatten items into dense rows
- attach section meta, field path, source, restart mode, readonly flag, and column id

Example shape:

```js
{
  key: 'guardian.stock.threshold.atr.period',
  scope: 'settings',
  section: 'guardian',
  column: 'right',
  label: '阈值 ATR 周期',
  field: 'stock.threshold.atr.period',
  full_path: 'guardian.stock.threshold.atr.period',
}
```

**Step 2: Add editor mapping and state helpers**

Implement:

- `resolveEditorType(row)`
- `isGuardianRowInactive(row, formState)`
- `buildDirtyLookup(current, baseline)`
- `groupRowsByColumn(rows)`

**Step 3: Run tests**

Run: `node --test src/views/systemSettings.test.mjs`
Expected: PASS

### Task 4: Replace the page shell with a dense three-column workspace

**Files:**
- Modify: `morningglory/fqwebui/src/views/SystemSettings.vue`
- Test: `morningglory/fqwebui/src/views/system-settings.test.mjs`

**Step 1: Remove the old hero + dual-section card structure**

Replace:

- hero banner
- editor pane cards
- summary pane blocks

with:

- compact toolbar
- three fixed columns
- per-column section dividers and sticky ledger headers

**Step 2: Render inline ledger rows**

For editable rows, render:

- label + field path
- inline `el-input`, `el-input-number`, or `el-select`
- source/restart columns
- row status

For readonly strategy rows, render plain text cells.

**Step 3: Run tests**

Run: `node --test src/views/system-settings.test.mjs`
Expected: PASS

### Task 5: Wire dirty state, Guardian inactive rows, and save actions

**Files:**
- Modify: `morningglory/fqwebui/src/views/SystemSettings.vue`
- Modify: `morningglory/fqwebui/src/views/systemSettings.mjs`
- Test: `morningglory/fqwebui/src/views/systemSettings.test.mjs`

**Step 1: Add baseline snapshots**

Track:

- initial Bootstrap values from dashboard
- initial Mongo values from dashboard

Compute:

- row-level dirty flags
- toolbar dirty counts for Bootstrap and Mongo

**Step 2: Keep Guardian rows visible across mode changes**

Render all threshold/grid rows continuously and mark inactive rows with UI state instead of removing them.

**Step 3: Preserve existing save protocol**

Keep:

- `systemConfigApi.getDashboard()`
- `systemConfigApi.updateBootstrap(...)`
- `systemConfigApi.updateSettings(...)`

and keep the existing PM threshold validation:

```js
if (Number(settingsForm.position_management.allow_open_min_bail) <= Number(settingsForm.position_management.holding_only_min_bail)) {
  ElMessage.error('允许开新仓最低保证金必须大于仅允许持仓内买入最低保证金')
  return
}
```

**Step 4: Run tests**

Run: `node --test src/views/systemSettings.test.mjs src/views/system-settings.test.mjs`
Expected: PASS

### Task 6: Tune dense ledger styles for viewport fit

**Files:**
- Modify: `morningglory/fqwebui/src/views/SystemSettings.vue`

**Step 1: Implement compact ledger styling**

Add styles for:

- three equal columns at desktop widths
- sticky section titles and ledger headers
- compact row height
- inline control sizing
- row dirty/inactive/readonly states
- internal column scrolling

**Step 2: Add responsive fallback**

Implement:

- `>= 1600px` three columns
- `< 1280px` two columns
- `< 900px` one column

without reintroducing card layout.

**Step 3: Run the structure tests again**

Run: `node --test src/views/system-settings.test.mjs`
Expected: PASS

### Task 7: Run focused verification

**Files:**
- Test: `morningglory/fqwebui/src/views/systemSettings.test.mjs`
- Test: `morningglory/fqwebui/src/views/system-settings.test.mjs`
- Modify: `morningglory/fqwebui/src/views/SystemSettings.vue`
- Modify: `morningglory/fqwebui/src/views/systemSettings.mjs`

**Step 1: Run the focused frontend tests**

Run: `node --test src/views/systemSettings.test.mjs src/views/system-settings.test.mjs`
Expected: PASS

**Step 2: Run the frontend build**

Run: `npm run build`
Workdir: `morningglory/fqwebui`
Expected: PASS

**Step 3: Review the final diff**

Run: `git status --short`
Expected: only the planned docs and system-settings frontend files are modified
