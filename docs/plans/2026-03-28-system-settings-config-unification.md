# System Settings Config Unification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `/system-settings` show the complete system-level formal config set, including the missing global `single_symbol_position_limit`, and regroup the three columns by module instead of by mixed storage origin.

**Architecture:** Treat [`freshquant/system_config_service.py`](D:/fqpack/freshquant-2026.2.23/freshquant/system_config_service.py) as the formal system-config aggregation contract and extend it so `pm_configs.thresholds` is complete. Then update the Vue page helpers to consume that richer payload, add the new PM field editor, and remap the three columns so storage, runtime linkage, and trading-control settings are grouped coherently.

**Tech Stack:** Python, pytest, Vue 3, Element Plus, Node test runner

---

### Task 1: Lock the approved design into plan artifacts

**Files:**
- Create: `docs/plans/2026-03-28-system-settings-config-unification-design.md`
- Create: `docs/plans/2026-03-28-system-settings-config-unification.md`

**Step 1: Write the design document**

Capture:

- the page boundary: system-level truth only
- the missing `pm_configs.thresholds.single_symbol_position_limit`
- the new three-column grouping
- the backend contract change and doc sync requirement

**Step 2: Verify the design and plan files exist**

Run: `Get-ChildItem docs/plans/2026-03-28-system-settings-config-unification*`
Expected: both the design and plan markdown files are listed

### Task 2: Add failing backend tests for complete PM thresholds

**Files:**
- Modify: `freshquant/tests/test_system_settings.py`
- Modify: `freshquant/tests/test_system_config_service.py`

**Step 1: Add a failing `SystemSettings` coverage test**

Write a test that seeds `pm_configs.thresholds.single_symbol_position_limit` and asserts:

```python
assert settings.position_management.single_symbol_position_limit == 950000.0
```

**Step 2: Add a failing dashboard contract test**

Extend the system-config service test fixture and assertions so `settings.position_management.single_symbol_position_limit` must be present in:

- `dashboard["settings"]["values"]`
- `dashboard["settings"]["sections"]`
- `update_settings()` persisted payload

**Step 3: Run tests to verify they fail**

Run: `py -m pytest freshquant/tests/test_system_settings.py freshquant/tests/test_system_config_service.py -q`
Expected: FAIL because `single_symbol_position_limit` is not yet part of `SystemSettings` or `SystemConfigService`

### Task 3: Implement complete PM threshold support in backend aggregation

**Files:**
- Modify: `freshquant/system_settings.py`
- Modify: `freshquant/system_config_service.py`
- Test: `freshquant/tests/test_system_settings.py`
- Test: `freshquant/tests/test_system_config_service.py`

**Step 1: Extend `SystemSettings`**

Add:

- `DEFAULT_PM_CONFIG.thresholds.single_symbol_position_limit`
- `PositionManagementSettings.single_symbol_position_limit`
- reload logic to read the field from `pm_configs.thresholds`

**Step 2: Extend `SystemConfigService`**

Update:

- `SETTINGS_SECTION_META["position_management"]["items"]`
- `_settings_values_from_provider()`
- `_normalize_settings_values()`
- `update_settings()`

The persisted `pm_configs.thresholds` object should include:

```python
{
    "allow_open_min_bail": ...,
    "holding_only_min_bail": ...,
    "single_symbol_position_limit": ...,
}
```

**Step 3: Run backend tests**

Run: `py -m pytest freshquant/tests/test_system_settings.py freshquant/tests/test_system_config_service.py -q`
Expected: PASS

### Task 4: Add failing frontend tests for the missing field and regrouped columns

**Files:**
- Modify: `morningglory/fqwebui/src/views/systemSettings.test.mjs`

**Step 1: Extend the test fixture**

Add `position_management.single_symbol_position_limit` to the payload fixture values and section items.

**Step 2: Add failing assertions**

Assert that:

- the flattened row exists for `position_management.single_symbol_position_limit`
- the row uses a number editor
- the `position_management` settings section lands in the right column
- the bootstrap storage sections land together in the left column

Example shape:

```js
const rows = flattenLedgerRows(sections)
assert.equal(rows.find((row) => row.key === 'position_management.single_symbol_position_limit').editor.type, 'number')
```

**Step 3: Run the frontend helper test**

Run: `node --test src/views/systemSettings.test.mjs`
Workdir: `morningglory/fqwebui`
Expected: FAIL because the field metadata and regrouped column mapping do not exist yet

### Task 5: Update frontend row helpers and page defaults

**Files:**
- Modify: `morningglory/fqwebui/src/views/systemSettings.mjs`
- Modify: `morningglory/fqwebui/src/views/SystemSettings.vue`
- Test: `morningglory/fqwebui/src/views/systemSettings.test.mjs`

**Step 1: Extend editor metadata**

Add number editor config for:

```js
'position_management.single_symbol_position_limit': { min: 0, step: 10000 }
```

**Step 2: Regroup the three columns**

Adjust the section-to-column mapping so:

- left column: `mongodb`, `redis`, `order_management`, bootstrap `position_management`, `memory`
- middle column: `xtquant`, `monitor`, `tdx`, `xtdata`, `api`, `runtime`, `notification`
- right column: `guardian`, settings `position_management`, `strategies`

**Step 3: Extend page form defaults**

Add to `defaultSettingsForm()`:

```js
single_symbol_position_limit: 800000,
```

**Step 4: Run the frontend helper test**

Run: `node --test src/views/systemSettings.test.mjs`
Workdir: `morningglory/fqwebui`
Expected: PASS

### Task 6: Verify page-level static tests and documentation

**Files:**
- Modify: `docs/current/configuration.md`
- Test: `morningglory/fqwebui/src/views/system-settings.test.mjs`

**Step 1: Update formal configuration docs**

Revise the `/system-settings` section so it no longer claims only two PM thresholds are editable. The docs should reflect that the page now covers the complete `pm_configs.thresholds`.

**Step 2: Run the page-level static test**

Run: `node --test src/views/system-settings.test.mjs`
Workdir: `morningglory/fqwebui`
Expected: PASS

### Task 7: Run focused end verification

**Files:**
- Modify: `freshquant/system_settings.py`
- Modify: `freshquant/system_config_service.py`
- Modify: `freshquant/tests/test_system_settings.py`
- Modify: `freshquant/tests/test_system_config_service.py`
- Modify: `morningglory/fqwebui/src/views/systemSettings.mjs`
- Modify: `morningglory/fqwebui/src/views/SystemSettings.vue`
- Modify: `morningglory/fqwebui/src/views/systemSettings.test.mjs`
- Modify: `docs/current/configuration.md`

**Step 1: Run backend verification**

Run: `py -m pytest freshquant/tests/test_system_settings.py freshquant/tests/test_system_config_service.py -q`
Expected: PASS

**Step 2: Run frontend verification**

Run: `node --test src/views/systemSettings.test.mjs src/views/system-settings.test.mjs`
Workdir: `morningglory/fqwebui`
Expected: PASS

**Step 3: Run final diff inspection**

Run: `git status --short`
Expected: only the planned system-settings docs, backend files, frontend files, and tests are modified by this task
