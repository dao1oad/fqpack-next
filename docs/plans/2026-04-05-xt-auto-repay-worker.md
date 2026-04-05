# XT Auto Repay Worker Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a dedicated host-side XT auto repay worker that handles ordinary financing debt repayment, exposes `xtquant.auto_repay.*` in `/system-settings`, runs low-frequency intraday checks, and performs fixed `14:55` hard settle plus `15:05` retry.

**Architecture:** Keep `xt_account_sync.worker` as the read-only broker truth sync path. Add a separate `freshquant.xt_auto_repay.worker` that reads synced credit snapshots for candidate detection, requeries XT only right before a real repay attempt, and executes `CREDIT_DIRECT_CASH_REPAY` through a dedicated executor guarded by lock, cooldown, and observe-only checks.

**Tech Stack:** Python 3.12, `xtquant` / `XtQuantTrader`, Mongo `params` + runtime collections, Redis-based lock/cooldown helpers, PowerShell host runtime scripts, Supervisor config generation, Vue 3 + Element Plus system settings UI, pytest, Node test runner, Playwright browser smoke.

---

## Pre-flight

- Create a GitHub Issue before implementation because this is a high-impact automated trading behavior change.
- Issue body must include: background, goal, scope, non-goals, acceptance criteria, deployment impact, enable/rollback plan.
- Do not merge or deploy the code path without the Issue reference in the PR body.

### Task 1: Add XT auto repay config contract to backend settings

**Files:**
- Modify: `freshquant/system_settings.py`
- Modify: `freshquant/system_config_service.py`
- Modify: `freshquant/initialize.py`
- Test: `freshquant/tests/test_system_settings.py`
- Test: `freshquant/tests/test_system_config_service.py`

**Step 1: Write the failing tests**

```python
def test_system_settings_reads_xtquant_auto_repay_defaults():
    assert settings.xtquant.auto_repay_enabled is True
    assert settings.xtquant.auto_repay_reserve_cash == 5000.0


def test_system_config_dashboard_includes_xtquant_auto_repay_items():
    xt_items = find_section(result["sections"], "xtquant")["items"]
    assert "auto_repay.enabled" in [item["field"] for item in xt_items]
    assert "auto_repay.reserve_cash" in [item["field"] for item in xt_items]
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest freshquant/tests/test_system_settings.py freshquant/tests/test_system_config_service.py -v
```

Expected:

- FAIL because `xtquant.auto_repay` fields are missing from defaults / normalization / dashboard metadata.

**Step 3: Write minimal implementation**

Add nested `auto_repay` support end-to-end:

```python
DEFAULT_XTQUANT = {
    "path": "",
    "account": "",
    "account_type": "STOCK",
    "broker_submit_mode": "normal",
    "auto_repay": {
        "enabled": True,
        "reserve_cash": 5000,
    },
}
```

Also update:

- `XtquantSettings`
- `SystemSettings.reload()`
- `SETTINGS_SECTION_META["xtquant"]["items"]`
- `_normalize_settings_values()`
- `initialize.py` default seed list for XT settings

**Step 4: Run test to verify it passes**

Run:

```bash
pytest freshquant/tests/test_system_settings.py freshquant/tests/test_system_config_service.py -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add freshquant/system_settings.py freshquant/system_config_service.py freshquant/initialize.py freshquant/tests/test_system_settings.py freshquant/tests/test_system_config_service.py
git commit -m "feat: add xt auto repay config contract"
```

### Task 2: Expose XT auto repay settings in `/system-settings`

**Files:**
- Modify: `morningglory/fqwebui/src/views/systemSettings.mjs`
- Modify: `morningglory/fqwebui/src/views/SystemSettings.vue`
- Test: `morningglory/fqwebui/src/views/systemSettings.test.mjs`
- Test: `morningglory/fqwebui/tests/system-settings.browser.spec.mjs`

**Step 1: Write the failing frontend tests**

```javascript
test('xtquant auto repay fields use the expected editors', () => {
  assert.equal(resolveEditorMeta('xtquant.auto_repay.enabled').type, 'select')
  assert.equal(resolveEditorMeta('xtquant.auto_repay.reserve_cash').type, 'number')
})
```

Also extend the browser fixture payload so XTQuant rows include:

```javascript
{ key: 'xtquant.auto_repay.enabled', field: 'auto_repay.enabled', label: '自动还款', editable: true, source: 'params.xtquant', value: true }
{ key: 'xtquant.auto_repay.reserve_cash', field: 'auto_repay.reserve_cash', label: '留底现金', editable: true, source: 'params.xtquant', value: 5000 }
```

**Step 2: Run test to verify it fails**

Run:

```bash
node --experimental-default-type=module --test morningglory/fqwebui/src/views/systemSettings.test.mjs
```

Expected:

- FAIL because the new XTQuant rows and editor metadata are not present.

**Step 3: Write minimal implementation**

Update:

- `defaultSettingsForm()` in `SystemSettings.vue`
- `SELECT_FIELD_META` / `NUMBER_FIELD_META` in `systemSettings.mjs`
- XTQuant section rendering data so nested `auto_repay.*` values round-trip through the form

Suggested editor shape:

```javascript
'xtquant.auto_repay.enabled': [
  { label: 'true', value: true },
  { label: 'false', value: false },
]
'xtquant.auto_repay.reserve_cash': { min: 0, step: 1000 }
```

**Step 4: Run test to verify it passes**

Run:

```bash
node --experimental-default-type=module --test morningglory/fqwebui/src/views/systemSettings.test.mjs
npm --prefix morningglory/fqwebui run test:browser-smoke
```

Expected:

- Unit test PASS
- Browser smoke PASS, including `tests/system-settings.browser.spec.mjs`

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/systemSettings.mjs morningglory/fqwebui/src/views/SystemSettings.vue morningglory/fqwebui/src/views/systemSettings.test.mjs morningglory/fqwebui/tests/system-settings.browser.spec.mjs
git commit -m "feat: expose xt auto repay settings"
```

### Task 3: Build the auto repay decision core and persistence

**Files:**
- Create: `freshquant/xt_auto_repay/__init__.py`
- Create: `freshquant/xt_auto_repay/repository.py`
- Create: `freshquant/xt_auto_repay/service.py`
- Test: `freshquant/tests/test_xt_auto_repay_service.py`

**Step 1: Write the failing tests**

Cover at least:

```python
def test_intraday_candidate_uses_snapshot_only_until_confirmation():
    snapshot = {"available_amount": 12000, "raw": {"m_dFinDebt": 9000}}
    decision = service.evaluate_snapshot(snapshot, now=intraday_time)
    assert decision["eligible"] is True
    assert decision["candidate_amount"] == 7000


def test_intraday_skips_small_candidate_below_min_repay_amount():
    snapshot = {"available_amount": 5600, "raw": {"m_dFinDebt": 9000}}
    decision = service.evaluate_snapshot(snapshot, now=intraday_time)
    assert decision["eligible"] is False
    assert decision["reason"] == "below_min_repay_amount"


def test_hard_settle_ignores_intraday_min_repay_amount():
    confirmed = {"m_dAvailable": 5600, "m_dFinDebt": 700}
    decision = service.evaluate_confirmed_detail(confirmed, mode="hard_settle")
    assert decision["eligible"] is True
    assert decision["repay_amount"] == 600
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest freshquant/tests/test_xt_auto_repay_service.py -v
```

Expected:

- FAIL because the package does not exist yet.

**Step 3: Write minimal implementation**

Implement:

- repository helpers to load latest credit snapshot and read/write:
  - `xt_auto_repay_state`
  - `xt_auto_repay_events`
- service decision helpers:
  - intraday candidate detection
  - `14:55` hard settle mode
  - `15:05` retry mode
  - reserve cash logic
  - ordinary debt only
  - observe-only branching

Suggested skeleton:

```python
class XtAutoRepayService:
    def evaluate_snapshot(self, snapshot, *, now):
        ...

    def evaluate_confirmed_detail(self, detail, *, mode):
        ...

    def record_event(self, payload):
        ...
```

**Step 4: Run test to verify it passes**

Run:

```bash
pytest freshquant/tests/test_xt_auto_repay_service.py -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add freshquant/xt_auto_repay/__init__.py freshquant/xt_auto_repay/repository.py freshquant/xt_auto_repay/service.py freshquant/tests/test_xt_auto_repay_service.py
git commit -m "feat: add xt auto repay decision core"
```

### Task 4: Add XT executor and worker loop

**Files:**
- Create: `freshquant/xt_auto_repay/executor.py`
- Create: `freshquant/xt_auto_repay/worker.py`
- Modify: `freshquant/position_management/credit_client.py`
- Test: `freshquant/tests/test_xt_auto_repay_worker.py`
- Test: `freshquant/tests/test_xt_auto_repay_executor.py`

**Step 1: Write the failing tests**

Cover:

```python
def test_worker_uses_snapshot_for_intraday_candidate_and_requeries_before_submit():
    ...


def test_worker_skips_real_submit_in_observe_only_mode():
    ...


def test_worker_runs_hard_settle_at_1455_and_retry_at_1505():
    ...


def test_executor_submits_credit_direct_cash_repay():
    assert trader.order_calls[0]["order_type"] == xtconstant.CREDIT_DIRECT_CASH_REPAY
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest freshquant/tests/test_xt_auto_repay_worker.py freshquant/tests/test_xt_auto_repay_executor.py -v
```

Expected:

- FAIL because worker loop and executor do not exist yet.

**Step 3: Write minimal implementation**

Implement:

- a dedicated executor that:
  - opens a CREDIT XT connection
  - requeries `query_credit_detail()`
  - submits `order_stock(..., xtconstant.CREDIT_DIRECT_CASH_REPAY, ...)`
- a worker loop that:
  - polls every `1800` seconds intraday
  - triggers fixed `14:55` and `15:05`
  - applies lock / cooldown / observe-only / idempotent event recording

Keep the request-shaping logic isolated:

```python
class XtAutoRepayExecutor:
    def query_credit_detail(self):
        ...

    def submit_direct_cash_repay(self, *, repay_amount, remark):
        ...
```

**Step 4: Run test to verify it passes**

Run:

```bash
pytest freshquant/tests/test_xt_auto_repay_worker.py freshquant/tests/test_xt_auto_repay_executor.py -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add freshquant/xt_auto_repay/executor.py freshquant/xt_auto_repay/worker.py freshquant/position_management/credit_client.py freshquant/tests/test_xt_auto_repay_worker.py freshquant/tests/test_xt_auto_repay_executor.py
git commit -m "feat: add xt auto repay worker and executor"
```

### Task 5: Wire the worker into host runtime, supervisor, deploy, and health checks

**Files:**
- Modify: `deployment/examples/supervisord.fqnext.example.conf`
- Modify: `script/fqnext_supervisor_config.py`
- Modify: `script/fqnext_host_runtime.py`
- Modify: `script/freshquant_deploy_plan.py`
- Modify: `script/check_freshquant_runtime_post_deploy.ps1`
- Test: `freshquant/tests/test_fqnext_supervisor_config.py`
- Test: `freshquant/tests/test_fqnext_host_runtime.py`
- Test: `freshquant/tests/test_freshquant_deploy_plan.py`
- Test: `freshquant/tests/test_runtime_post_deploy_check.py`

**Step 1: Write the failing host runtime tests**

Add expectations for:

- new supervisor program `fqnext_xt_auto_repay_worker`
- new process pattern `python -m freshquant.xt_auto_repay.worker`
- `order_management` host surface including the new worker
- runtime verify recognizing the new worker as part of the trading surface

**Step 2: Run test to verify it fails**

Run:

```bash
pytest freshquant/tests/test_fqnext_supervisor_config.py freshquant/tests/test_fqnext_host_runtime.py freshquant/tests/test_freshquant_deploy_plan.py freshquant/tests/test_runtime_post_deploy_check.py -v
```

Expected:

- FAIL because host runtime metadata does not know about the new worker.

**Step 3: Write minimal implementation**

Update the generated supervisor config and host surface maps:

```python
SURFACE_PROGRAMS["order_management"] = [
    "fqnext_xtquant_broker",
    "fqnext_xt_account_sync_worker",
    "fqnext_xt_auto_repay_worker",
]
```

Add a dedicated supervisor program entry:

```ini
[program:fqnext_xt_auto_repay_worker]
command=... -m freshquant.xt_auto_repay.worker
```

**Step 4: Run test to verify it passes**

Run:

```bash
pytest freshquant/tests/test_fqnext_supervisor_config.py freshquant/tests/test_fqnext_host_runtime.py freshquant/tests/test_freshquant_deploy_plan.py freshquant/tests/test_runtime_post_deploy_check.py -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add deployment/examples/supervisord.fqnext.example.conf script/fqnext_supervisor_config.py script/fqnext_host_runtime.py script/freshquant_deploy_plan.py script/check_freshquant_runtime_post_deploy.ps1 freshquant/tests/test_fqnext_supervisor_config.py freshquant/tests/test_fqnext_host_runtime.py freshquant/tests/test_freshquant_deploy_plan.py freshquant/tests/test_runtime_post_deploy_check.py
git commit -m "feat: wire xt auto repay worker into host runtime"
```

### Task 6: Update formal docs and run focused verification

**Files:**
- Modify: `docs/current/configuration.md`
- Modify: `docs/current/deployment.md`
- Modify: `docs/current/runtime.md`
- Modify: `docs/current/interfaces.md`
- Modify: `docs/current/storage.md`
- Modify: `docs/current/architecture.md`
- Modify: `docs/current/troubleshooting.md`

**Step 1: Write the doc updates**

Document:

- new `xtquant.auto_repay.*` config
- new host worker entrypoint
- `14:55` hard settle and `15:05` retry behavior
- new state/event collections
- deploy / restart / health-check expectations
- observe-only behavior

**Step 2: Run focused verification**

Run:

```bash
pytest freshquant/tests/test_system_settings.py freshquant/tests/test_system_config_service.py freshquant/tests/test_xt_auto_repay_service.py freshquant/tests/test_xt_auto_repay_worker.py freshquant/tests/test_xt_auto_repay_executor.py freshquant/tests/test_fqnext_supervisor_config.py freshquant/tests/test_fqnext_host_runtime.py freshquant/tests/test_freshquant_deploy_plan.py freshquant/tests/test_runtime_post_deploy_check.py -v
npm --prefix morningglory/fqwebui run test:unit
npm --prefix morningglory/fqwebui run test:browser-smoke
```

Expected:

- All targeted pytest suites PASS
- Frontend Node tests PASS
- Browser smoke PASS

**Step 3: Commit**

```bash
git add docs/current/configuration.md docs/current/deployment.md docs/current/runtime.md docs/current/interfaces.md docs/current/storage.md docs/current/architecture.md docs/current/troubleshooting.md
git commit -m "docs: document xt auto repay worker"
```

### Task 7: Final integration verification before PR

**Files:**
- Modify: none
- Test: repository-wide verification commands only

**Step 1: Run final verification**

Run:

```bash
pytest -v
npm --prefix morningglory/fqwebui run test:unit
npm --prefix morningglory/fqwebui run test:browser-smoke
```

Expected:

- Required backend tests PASS
- Frontend unit tests PASS
- Browser smoke PASS

**Step 2: Prepare PR**

Include in PR body:

- linked GitHub Issue
- scope
- non-goals
- acceptance criteria
- deployment impact
- enable/rollback notes

**Step 3: Commit any final fixups**

```bash
git status --short
git add -A
git commit -m "chore: finalize xt auto repay worker rollout"
```
