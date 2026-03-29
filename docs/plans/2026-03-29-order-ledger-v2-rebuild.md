# Order Ledger V2 Rebuild Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 清空现有订单账本集合，并以 `xt_orders + xt_trades + xt_positions` 为唯一输入重建正式 V2 账本，让 TPSL、SubjectManagement、KlineSlim、PositionManagement 全部重新对齐到 `entry / reconciliation`。

**Architecture:** 实现一个可 dry-run、可 execute、可 rollback 的重建脚本，先冻结券商输入快照，再备份并清空 `om_*` 集合，随后按 `broker order -> execution fill -> position entry -> entry slice -> exit allocation -> reconciliation` 顺序重建。读侧不再依赖 legacy `buy_lot / stock_fills` 真值，只保留兼容投影。

**Tech Stack:** Python 3.12、PyMongo、现有 `freshquant.order_management` repository / guardian / reconcile 代码、PowerShell 运维脚本、pytest。

---

### Task 1: 治理与重建测试骨架

**Files:**
- Create: `freshquant/tests/test_order_ledger_v2_rebuild.py`
- Modify: `docs/current/modules/order-management.md`
- Modify: `docs/current/troubleshooting.md`

**Step 1: Write the failing test**

```python
def test_rebuild_plan_requires_broker_truth_only():
    state = build_rebuild_state(
        xt_orders=[{"order_id": 1}],
        xt_trades=[{"traded_id": "t1"}],
        xt_positions=[{"stock_code": "600000.SH", "volume": 100}],
    )
    assert state["input_collections"] == ["xt_orders", "xt_trades", "xt_positions"]
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m uv run pytest freshquant/tests/test_order_ledger_v2_rebuild.py::test_rebuild_plan_requires_broker_truth_only -q`
Expected: FAIL because rebuild helper does not exist yet.

**Step 3: Write minimal implementation**

Create a minimal helper in the future rebuild module that returns the accepted truth-source list and rejects legacy `om_*` inputs as primary truth.

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m uv run pytest freshquant/tests/test_order_ledger_v2_rebuild.py::test_rebuild_plan_requires_broker_truth_only -q`
Expected: PASS

**Step 5: Document destructive-governance prerequisite**

Update:
- `docs/current/modules/order-management.md`
- `docs/current/troubleshooting.md`

Add a short current-state note that destructive order-ledger rebuild must be driven from broker truth and must be preceded by a GitHub Issue.

**Step 6: Commit**

```bash
git add freshquant/tests/test_order_ledger_v2_rebuild.py docs/current/modules/order-management.md docs/current/troubleshooting.md
git commit -m "test: add order ledger rebuild governance baseline"
```

### Task 2: 实现重建核心服务

**Files:**
- Create: `freshquant/order_management/rebuild/__init__.py`
- Create: `freshquant/order_management/rebuild/service.py`
- Modify: `freshquant/order_management/repository.py`
- Test: `freshquant/tests/test_order_ledger_v2_rebuild.py`

**Step 1: Write the failing test**

```python
def test_rebuild_service_builds_broker_orders_and_execution_fills():
    service = OrderLedgerV2RebuildService(repository=repo)
    result = service.build_from_truth(
        xt_orders=[sample_order()],
        xt_trades=[sample_trade()],
        xt_positions=[],
        now_ts=1775000000,
    )
    assert result["broker_orders"] == 1
    assert result["execution_fills"] == 1
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m uv run pytest freshquant/tests/test_order_ledger_v2_rebuild.py::test_rebuild_service_builds_broker_orders_and_execution_fills -q`
Expected: FAIL because the service does not exist yet.

**Step 3: Write minimal implementation**

Implement:
- broker-order normalization from `xt_orders`
- trade-to-order matching from `xt_trades`
- `trade_only` broker-order fallback
- Beijing `trade_time -> date/time` derivation

Add repository helpers only if needed:
- collection backup helper
- collection purge helper
- bulk replace / insert helper

**Step 4: Run focused tests**

Run: `py -3.12 -m uv run pytest freshquant/tests/test_order_ledger_v2_rebuild.py -q`
Expected: PASS for broker-order / execution-fill reconstruction cases.

**Step 5: Commit**

```bash
git add freshquant/order_management/rebuild/__init__.py freshquant/order_management/rebuild/service.py freshquant/order_management/repository.py freshquant/tests/test_order_ledger_v2_rebuild.py
git commit -m "feat: add order ledger rebuild core service"
```

### Task 3: 实现 entry / slice / allocation 回放

**Files:**
- Modify: `freshquant/order_management/rebuild/service.py`
- Modify: `freshquant/order_management/guardian/arranger.py`
- Modify: `freshquant/order_management/guardian/allocation_policy.py`
- Test: `freshquant/tests/test_order_ledger_v2_rebuild.py`
- Test: `freshquant/tests/test_order_management_guardian_semantics.py`

**Step 1: Write the failing test**

```python
def test_rebuild_service_replays_buy_and_sell_into_open_entries():
    service = OrderLedgerV2RebuildService(repository=repo)
    result = service.build_from_truth(
        xt_orders=[buy_order(), sell_order()],
        xt_trades=[buy_trade(), sell_trade()],
        xt_positions=[],
        now_ts=1775000000,
    )
    assert result["position_entries"] == 1
    assert result["exit_allocations"] == 1
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m uv run pytest freshquant/tests/test_order_ledger_v2_rebuild.py::test_rebuild_service_replays_buy_and_sell_into_open_entries -q`
Expected: FAIL because entry replay is not implemented yet.

**Step 3: Write minimal implementation**

Implement:
- buy fills aggregated into one `position_entry` per broker order
- `arrange_entry()` invocation for `entry_slices`
- sell replay through `allocate_sell_to_entry_slices()`
- status transitions for `OPEN / PARTIALLY_EXITED / CLOSED`
- complete `date/time` propagation onto entries and slices

**Step 4: Run focused tests**

Run:
- `py -3.12 -m uv run pytest freshquant/tests/test_order_ledger_v2_rebuild.py -q`
- `py -3.12 -m uv run pytest freshquant/tests/test_order_management_guardian_semantics.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/order_management/rebuild/service.py freshquant/order_management/guardian/arranger.py freshquant/order_management/guardian/allocation_policy.py freshquant/tests/test_order_ledger_v2_rebuild.py freshquant/tests/test_order_management_guardian_semantics.py
git commit -m "feat: rebuild entry ledger from broker fills"
```

### Task 4: 实现 reconciliation 与 odd-lot 拒绝

**Files:**
- Modify: `freshquant/order_management/rebuild/service.py`
- Test: `freshquant/tests/test_order_ledger_v2_rebuild.py`
- Test: `freshquant/tests/test_order_management_reconcile.py`

**Step 1: Write the failing test**

```python
def test_rebuild_service_creates_auto_reconciled_open_entry_from_xt_positions_gap():
    service = OrderLedgerV2RebuildService(repository=repo)
    result = service.build_from_truth(
        xt_orders=[],
        xt_trades=[],
        xt_positions=[{"stock_code": "300760.SZ", "volume": 3900, "avg_price": 195.32}],
        now_ts=1775000000,
    )
    assert result["reconciliation_gaps"] == 1
    assert result["auto_open_entries"] == 1
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m uv run pytest freshquant/tests/test_order_ledger_v2_rebuild.py::test_rebuild_service_creates_auto_reconciled_open_entry_from_xt_positions_gap -q`
Expected: FAIL because reconciliation rebuild is not implemented yet.

**Step 3: Add more failing tests**

Add tests for:
- odd-lot delta goes to `REJECTED`
- odd-lot trade writes `om_ingest_rejections`
- `ledger > broker` triggers auto close allocation

**Step 4: Write minimal implementation**

Implement:
- per-symbol ledger vs broker diff
- `auto_reconciled_open entry`
- `auto_reconciled_close allocation`
- `board_lot_rejected` gap and rejection records
- minimal `om_reconciliation_resolutions`

**Step 5: Run focused tests**

Run:
- `py -3.12 -m uv run pytest freshquant/tests/test_order_ledger_v2_rebuild.py -q`
- `py -3.12 -m uv run pytest freshquant/tests/test_order_management_reconcile.py -q`

Expected: PASS

**Step 6: Commit**

```bash
git add freshquant/order_management/rebuild/service.py freshquant/tests/test_order_ledger_v2_rebuild.py freshquant/tests/test_order_management_reconcile.py
git commit -m "feat: rebuild reconciliation from broker truth"
```

### Task 5: 实现 CLI/maintenance 脚本与备份清库流程

**Files:**
- Create: `script/maintenance/rebuild_order_ledger_v2.py`
- Modify: `freshquant/order_management/db.py`
- Test: `freshquant/tests/test_order_ledger_v2_rebuild.py`
- Test: `freshquant/tests/test_order_management_cli.py`

**Step 1: Write the failing test**

```python
def test_rebuild_cli_dry_run_reports_counts_without_mutation():
    result = run_cli("--dry-run")
    assert result.exit_code == 0
    assert "broker_orders" in result.stdout
    assert "would_purge_collections" in result.stdout
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m uv run pytest freshquant/tests/test_order_ledger_v2_rebuild.py::test_rebuild_cli_dry_run_reports_counts_without_mutation -q`
Expected: FAIL because CLI does not exist yet.

**Step 3: Write minimal implementation**

Implement a script with:
- `--dry-run`
- `--execute`
- `--backup-db <name>`
- `--account-id`
- explicit collection list logging
- summary JSON output

Reject destructive execution unless `--execute` is passed.

**Step 4: Run focused tests**

Run:
- `py -3.12 -m uv run pytest freshquant/tests/test_order_ledger_v2_rebuild.py -q`
- `py -3.12 -m uv run pytest freshquant/tests/test_order_management_cli.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add script/maintenance/rebuild_order_ledger_v2.py freshquant/order_management/db.py freshquant/tests/test_order_ledger_v2_rebuild.py freshquant/tests/test_order_management_cli.py
git commit -m "feat: add order ledger v2 rebuild maintenance cli"
```

### Task 6: 校准读侧与兼容投影

**Files:**
- Modify: `freshquant/order_management/entry_adapter.py`
- Modify: `freshquant/order_management/projection/stock_fills.py`
- Modify: `freshquant/data/astock/holding.py`
- Test: `freshquant/tests/test_order_management_holding_adapter.py`
- Test: `freshquant/tests/test_subject_management_service.py`
- Test: `freshquant/tests/test_tpsl_management_service.py`
- Test: `freshquant/tests/test_position_management_dashboard.py`

**Step 1: Write the failing test**

```python
def test_holding_adapter_prefers_rebuilt_v2_entries_without_legacy_lots():
    repo = FakeRepo(position_entries=[sample_entry()], buy_lots=[])
    rows = get_stock_fill_list(repository=repo)
    assert rows[0]["date"] == 20260329
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m uv run pytest freshquant/tests/test_order_management_holding_adapter.py::test_holding_adapter_prefers_rebuilt_v2_entries_without_legacy_lots -q`
Expected: FAIL if read-side still depends on legacy lot presence.

**Step 3: Write minimal implementation**

Ensure:
- `entry_adapter` fully prefers v2 entries/slices when present
- `stock_fills` compat view derives from rebuilt v2 data
- holding adapters and service layers no longer require legacy `om_buy_lots`

**Step 4: Run focused tests**

Run:
- `py -3.12 -m uv run pytest freshquant/tests/test_order_management_holding_adapter.py -q`
- `py -3.12 -m uv run pytest freshquant/tests/test_subject_management_service.py freshquant/tests/test_tpsl_management_service.py freshquant/tests/test_position_management_dashboard.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/order_management/entry_adapter.py freshquant/order_management/projection/stock_fills.py freshquant/data/astock/holding.py freshquant/tests/test_order_management_holding_adapter.py freshquant/tests/test_subject_management_service.py freshquant/tests/test_tpsl_management_service.py freshquant/tests/test_position_management_dashboard.py
git commit -m "refactor: read rebuilt entry ledger from v2 collections"
```

### Task 7: 执行 live 重建与部署验收

**Files:**
- Modify: `docs/current/modules/order-management.md`
- Modify: `docs/current/deployment.md`
- Modify: `docs/current/troubleshooting.md`

**Step 1: Dry-run live rebuild**

Run:

```bash
py -3.12 -m uv run script/maintenance/rebuild_order_ledger_v2.py --dry-run --account-id 068000076370
```

Expected:
- 输出当前 `xt_orders / xt_trades / xt_positions` 计数
- 输出将清理的 `om_*` 集合
- 输出将重建的 `broker_orders / execution_fills / position_entries / reconciliation` 计数预测

**Step 2: Stop writers and capture backup**

Run the documented host-runtime stop flow for:
- `fqnext_xtquant_broker`
- `fqnext_xt_account_sync_worker`
- `fqnext_tpsl_worker`
- API order-write surface

Then run:

```bash
py -3.12 -m uv run script/maintenance/rebuild_order_ledger_v2.py --execute --backup-db freshquant_order_management_backup_20260329 --account-id 068000076370
```

Expected:
- destructive purge succeeds
- v2 collections are recreated
- no `position_entry / entry_slice` is missing `date/time`

**Step 3: Run full verification**

Run:

```bash
py -3.12 -m uv run pytest freshquant/tests/test_order_ledger_v2_rebuild.py freshquant/tests/test_order_management_db.py freshquant/tests/test_order_management_reconcile.py freshquant/tests/test_order_management_holding_adapter.py freshquant/tests/test_subject_management_service.py freshquant/tests/test_tpsl_management_service.py freshquant/tests/test_position_management_dashboard.py -q
```

Expected: PASS

**Step 4: Deploy affected surfaces**

Run the formal deploy flow for:
- `api`
- `web`
- `position_management`
- `tpsl`
- `order_management`

**Step 5: Run post-deploy checks**

Run:

```bash
py -3.12 script/freshquant_health_check.py --surface api --surface web --format summary
powershell -ExecutionPolicy Bypass -File script/check_freshquant_runtime_post_deploy.ps1 -Mode Verify -BaselinePath <baseline.json> -DeploymentSurface api,web,position_management,tpsl,order_management
```

Expected: PASS

**Step 6: Update current docs**

Update current docs to reflect:
- rebuild command
- current truth boundaries
- rollback procedure
- troubleshooting for rejected odd-lot / auto-reconciled entries

**Step 7: Commit**

```bash
git add docs/current/modules/order-management.md docs/current/deployment.md docs/current/troubleshooting.md
git commit -m "docs: document order ledger v2 rebuild operations"
```

### Task 8: Final landing checks

**Files:**
- Review only

**Step 1: Run branch-wide verification**

Run the full agreed verification matrix for backend, frontend, docs-current-guard, and rebuild-specific tests.

**Step 2: Create PR**

Include:
- background
- destructive scope
- acceptance criteria
- deployment impact
- backup / rollback plan

**Step 3: Wait for CI and review**

Do not merge until:
- CI is green
- review threads are resolved
- live rebuild evidence is attached

**Step 4: Merge, deploy from latest remote main, cleanup**

Follow:
- remote `main` merge
- formal deploy on merged SHA
- health check
- delete feature branch
- remove worktree
