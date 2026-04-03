# Order Ledger Runtime Rebuild Runbook

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在最新远程 `main` 已正式部署后，冻结订单写入面，基于最新 broker truth 重建当前系统的订单账本与 compat 投影，并定点验收 `300760`、`600570`、`672137219`。

**Architecture:** 先把代码真值收敛到最新远程 `main`，并通过 formal deploy 让 Docker API 与宿主机 supervisor program 都切到同一正式 SHA。随后暂停 API 与宿主机写入面，主动刷新一次 `xt_orders / xt_trades / xt_positions`，只用这三组 broker truth 执行 destructive rebuild，再重建 `stock_fills_compat`，最后做 symbol / order 级验收；若失败则按备份库整库恢复。

**Tech Stack:** PowerShell, Python 3.12, `uv`, MongoDB, Docker Compose, FreshQuant order ledger V2, `fqnext-supervisord`

---

### Task 1: 收敛代码与部署真值

**Files:**
- Review: `docs/current/deployment.md`
- Review: `docs/current/modules/order-management.md`
- Review: `script/fq_local_preflight.ps1`
- Review: `script/fq_open_pr.ps1`
- Review: `script/ci/run_production_deploy.ps1`

**Step 1: 确认 destructive rebuild 治理前置**

- GitHub Issue 必须已经存在，并写清影响面、验收标准、部署影响。
- 本次 rebuild 的正式输入只能是 `xt_orders / xt_trades / xt_positions`。
- 不允许把 `om_*`、`stock_fills`、`stock_fills_compat` 当主真值。

**Step 2: 跑本地预检**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File script/fq_local_preflight.ps1 -Mode Ensure
```

Expected:
- governance / pre-commit / pytest / review threads 全部通过。

**Step 3: 开 PR 并合并到远程 `main`**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File script/fq_open_pr.ps1 -- --fill
```

Expected:
- 修复代码经 CI 全绿后合并到远程 `main`。

**Step 4: 对最新远程 `main` 执行 formal deploy**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File script/ci/run_production_deploy.ps1 -CanonicalRoot D:\fqpack\freshquant-2026.2.23 -MirrorRoot D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production -MirrorBranch deploy-production-main
```

Expected:
- `D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/result.json` 显示 `ok=true`。
- 若 `plan.json` 显示 `deployment_required=true`，同目录下 `runtime-verify.json` 必须 `passed=true`。
- 宿主机 supervisor 配置与 import source 已切到 `main-deploy-production`。

**Step 5: 记录正式 deploy 证据**

- 保留本轮 `run_dir` 下的 `plan.json`、`result.json`。
- 若命中实际 deploy，同时保留 `runtime-baseline.json`、`runtime-verify.json`。

### Task 2: Freeze 写入面并刷新 broker truth

**Files:**
- Review: `script/fqnext_host_runtime_ctl.ps1`
- Review: `script/fqnext_host_runtime.py`
- Review: `script/docker_parallel_compose.ps1`
- Review: `freshquant/xt_account_sync/worker.py`
- Review: `freshquant/xt_account_sync/service.py`

**Step 1: 记录 freeze 前运行面状态**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status
powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 ps fq_apiserver
powershell -ExecutionPolicy Bypass -File script/check_freshquant_runtime_post_deploy.ps1 -Mode CaptureBaseline -OutputPath D:\fqpack\runtime\artifacts\order-ledger-rebuild\baseline-2026-04-03.json
```

Expected:
- `fqnext_xtquant_broker`、`fqnext_xt_account_sync_worker`、`fqnext_tpsl_worker`、`fq_apiserver` 当前都可见且健康。

**Step 2: 停止 API order-write surface**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 stop fq_apiserver
```

Expected:
- `fq_apiserver` 已停止，不再接受 `/api/order/*` 写请求。

**Step 3: 停止宿主机写入面**

Run:

```powershell
@'
import xmlrpc.client

server = xmlrpc.client.ServerProxy("http://127.0.0.1:10011/RPC2")
for name in [
    "fqnext_xtquant_broker",
    "fqnext_xt_account_sync_worker",
    "fqnext_tpsl_worker",
]:
    info = server.supervisor.getProcessInfo(name)
    state = str(info.get("statename", "")).upper()
    print(name, "before=", state)
    if state == "RUNNING":
        server.supervisor.stopProcess(name, True)
        print(name, "stopped")
'@ | py -3.12 -
```

Expected:
- 三个宿主机写入程序进入 `STOPPED` 或 `EXITED`。

**Step 4: 主动刷新一次 XT truth**

Run:

```powershell
py -3.12 -m uv run -m freshquant.xt_account_sync.worker --once
```

Expected:
- 单次同步正常退出。
- 本轮会刷新 `assets / credit_detail / positions / incremental orders / incremental trades`。

**Step 5: 冻结后记录 broker truth 快照**

Run:

```powershell
@'
from pprint import pprint
from freshquant.db import DBfreshquant

for name in ("xt_orders", "xt_trades", "xt_positions"):
    print(name, DBfreshquant[name].count_documents({}))

for order_id in (672137219, 672137221):
    print("=" * 80)
    print("xt_trades order_id", order_id)
    pprint(
        list(
            DBfreshquant["xt_trades"]
            .find({"order_id": {"$in": [order_id, str(order_id)]}}, {"_id": 0})
            .sort([("traded_time", 1)])
        )
    )
'@ | py -3.12 -m uv run -
```

Expected:
- `xt_orders / xt_trades / xt_positions` 已是本轮 rebuild 的唯一输入真值。
- `672137219`、`672137221` 对应的 `xt_trades` 已完整可见。

### Task 3: 执行 destructive rebuild 与 compat rebuild

**Files:**
- Review: `script/maintenance/rebuild_order_ledger_v2.py`
- Review: `freshquant/order_management/db.py`
- Review: `freshquant/data/astock/fill.py`

**Step 1: 先跑全量 dry-run**

Run:

```powershell
py -3.12 -m uv run script/maintenance/rebuild_order_ledger_v2.py --dry-run
```

Expected:
- 输出 JSON summary。
- 重点记录：`broker_orders`、`execution_fills`、`position_entries`、`clustered_entries`、`mergeable_entry_gap`、`non_default_lot_slices`。

**Step 2: 如需单账户演练，追加一次 account dry-run**

Run:

```powershell
py -3.12 -m uv run script/maintenance/rebuild_order_ledger_v2.py --dry-run --account-id <broker_account_id>
```

Expected:
- 单账户 summary 与全量口径一致，不做任何写入。

**Step 3: 执行 destructive rebuild**

Run:

```powershell
py -3.12 -m uv run script/maintenance/rebuild_order_ledger_v2.py --execute --backup-db freshquant_order_management_backup_20260403_rebuild1
```

Expected:
- `backup_performed=true`
- `purged_collections` 非空
- 新 `om_*` 集合已由 rebuild 结果重写

**Step 4: 重建 `stock_fills_compat`**

Run:

```powershell
py -3.12 -m uv run -m freshquant.cli stock.fill rebuild --all
```

Expected:
- 返回 JSON，包含 `synced_symbols` 与 `rows_by_symbol`。

**Step 5: 定点比较 compat 投影**

Run:

```powershell
py -3.12 -m uv run -m freshquant.cli stock.fill compare --code 300760
py -3.12 -m uv run -m freshquant.cli stock.fill compare --code 600570
```

Expected:
- `quantity_consistent=true`
- `amount_adjusted_consistent=true`

### Task 4: 定点验收 `300760`、`600570`、`672137219`

**Files:**
- Review: `freshquant/order_management/repository.py`
- Review: `freshquant/order_management/rebuild/service.py`

**Step 1: 查询 symbol 级 rebuild 结果**

Run:

```powershell
@'
from pprint import pprint
from freshquant.db import DBfreshquant
from freshquant.order_management.repository import OrderManagementRepository

repo = OrderManagementRepository()

for symbol in ("300760", "600570"):
    print("=" * 100)
    print("symbol", symbol)
    xt_positions = list(
        DBfreshquant["xt_positions"].find(
            {"stock_code": {"$regex": f"^{symbol}(\\..*)?$", "$options": "i"}},
            {"_id": 0},
        )
    )
    broker_orders = repo.list_broker_orders(symbol=symbol)
    fills = repo.list_execution_fills(symbol=symbol)
    entries = repo.list_position_entries(symbol=symbol)
    gaps = repo.list_reconciliation_gaps(symbol=symbol)
    resolutions = repo.list_reconciliation_resolutions(
        gap_ids=[item["gap_id"] for item in gaps]
    )
    print("xt_positions")
    pprint(xt_positions)
    print("broker_orders")
    pprint(broker_orders)
    print("execution_fills")
    pprint(fills)
    print("position_entries")
    pprint(entries)
    print("reconciliation_gaps")
    pprint(gaps)
    print("reconciliation_resolutions")
    pprint(resolutions)
'@ | py -3.12 -m uv run -
```

Expected:
- `300760` 不应再保留“第 1 笔 / 第 2 笔入口本应聚合却未聚合”的错误拆分。
- `600570` 同样不应再出现同日同窗口买入被错误拆分。
- rebuild 后若仍存在 gap / resolution，应能解释为 broker truth 差异，而不是 callback 丢失副作用。

**Step 2: 查询 `672137219` 与 `672137221` 的 order/fill 对齐情况**

Run:

```powershell
@'
from pprint import pprint
from freshquant.db import DBfreshquant
from freshquant.order_management.db import DBOrderManagement

for order_id in ("672137219", "672137221"):
    print("=" * 100)
    print("order_id", order_id)
    print("xt_trades")
    pprint(
        list(
            DBfreshquant["xt_trades"]
            .find({"order_id": {"$in": [int(order_id), order_id]}}, {"_id": 0})
            .sort([("traded_time", 1)])
        )
    )
    print("om_broker_orders")
    pprint(
        list(
            DBOrderManagement["om_broker_orders"]
            .find({"broker_order_id": order_id}, {"_id": 0})
            .sort([("submitted_at", 1)])
        )
    )
    print("om_execution_fills")
    pprint(
        list(
            DBOrderManagement["om_execution_fills"]
            .find({"broker_order_id": order_id}, {"_id": 0})
            .sort([("filled_at", 1)])
        )
    )
'@ | py -3.12 -m uv run -
```

Expected:
- `672137219`：`om_execution_fills` 数量应与 `xt_trades` 里该 `order_id` 的记录数一致，不再只剩一笔 fill。
- `672137221`：若 `xt_*` 横跨多个交易日复用了同一 `order_id`，`om_broker_orders` 应拆成多条 `broker_order_key`，不能再把跨日事实混成一单。

**Step 3: 人工验收结论**

- 若上面两组查询都符合预期，可以判定这次修复属于“历史数据问题已通过 broker-truth rebuild 修复”。
- 若仍不符合预期，先不要恢复写入面，直接进入 rollback。

### Task 5: 恢复写入面并做运行验证

**Files:**
- Review: `script/docker_parallel_compose.ps1`
- Review: `script/fqnext_host_runtime_ctl.ps1`
- Review: `script/check_freshquant_runtime_post_deploy.ps1`

**Step 1: 恢复 API**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 start fq_apiserver
```

Expected:
- `fq_apiserver` 恢复运行。

**Step 2: 恢复宿主机写入面**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface order_management -DeploymentSurface position_management -DeploymentSurface tpsl -BridgeIfServiceUnavailable
```

Expected:
- `fqnext_xtquant_broker`、`fqnext_xt_account_sync_worker`、`fqnext_tpsl_worker` 全部恢复 `RUNNING`。

**Step 3: 做接口健康检查与 runtime verify**

Run:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/components
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/health/summary
powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status
powershell -ExecutionPolicy Bypass -File script/check_freshquant_runtime_post_deploy.ps1 -Mode Verify -BaselinePath D:\fqpack\runtime\artifacts\order-ledger-rebuild\baseline-2026-04-03.json -OutputPath D:\fqpack\runtime\artifacts\order-ledger-rebuild\verify-2026-04-03.json -DeploymentSurface api,order_management,position_management,tpsl
```

Expected:
- API 健康接口返回正常。
- `fqnext_host_runtime_ctl.ps1 -Mode Status` 中目标 program 全部为 `Running`。
- `verify-2026-04-03.json` 显示 `passed=true`。

### Task 6: 回滚预案

**Files:**
- Review: `freshquant/order_management/db.py`

**Step 1: 仅在验证失败时执行**

- 先保持 API 与宿主机写入面继续停止。
- 不做局部修补；只接受整库恢复。

**Step 2: 用 backup DB 整库恢复**

Run:

```powershell
@'
from freshquant.order_management.db import (
    ORDER_LEDGER_REBUILD_PURGE_COLLECTIONS,
    get_order_management_db,
)

active = get_order_management_db()
backup = active.client["freshquant_order_management_backup_20260403_rebuild1"]

for name in ORDER_LEDGER_REBUILD_PURGE_COLLECTIONS:
    docs = list(backup[name].find({}))
    active[name].delete_many({})
    if docs:
        active[name].insert_many(docs, ordered=False)
    print(name, len(docs))
'@ | py -3.12 -m uv run -
```

Expected:
- 活跃库恢复到 rebuild 前状态。

**Step 3: 恢复写入面并重新诊断**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 start fq_apiserver
powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface order_management -DeploymentSurface position_management -DeploymentSurface tpsl -BridgeIfServiceUnavailable
```

Expected:
- 系统回到 freeze 前运行态，再单独开新 Issue 继续排查。
