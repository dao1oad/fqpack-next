# Order Ledger Truth Reset Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复运行期 reconcile 双计数，并通过 destructive rebuild 把订单账本、仓位和 entry stoploss 真值重新收敛。

**Architecture:** 先用测试锁定 reconcile 主口径，再修复运行期对账代码，随后对 `freshquant_order_management` 执行备份、清理、重建与校准，最后用服务层和数据库校验各视图一致。

**Tech Stack:** Python 3.12, pytest, MongoDB, FreshQuant order ledger V2, PowerShell

---

### Task 1: 锁定双计数回归测试

**Files:**
- Modify: `freshquant/tests/test_order_management_reconcile.py`

**Step 1: 写失败测试**

- 构造一个同时拥有 open V2 entry 与 open legacy buy_lot 的 symbol
- 给 `detect_external_candidates()` 传入与 broker 仓位一致的 `xt_positions`
- 断言不会产生 `sell gap`

**Step 2: 跑单测并确认失败**

Run: `D:\\fqpack\\freshquant-2026.2.23\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_order_management_reconcile.py -q`

**Step 3: 最小修复**

- 只修改 reconcile 运行期内部仓位聚合逻辑

**Step 4: 跑单测并确认通过**

Run: `D:\\fqpack\\freshquant-2026.2.23\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_order_management_reconcile.py -q`

### Task 2: 补充重建/运行期一致性验证

**Files:**
- Modify: `freshquant/tests/test_order_management_reconcile.py`
- Optional Modify: `freshquant/tests/test_order_ledger_v2_rebuild.py`

**Step 1: 加回归场景**

- 覆盖 V2 为主、legacy 仅兼容时的对账行为
- 覆盖 auto-open 后再次 detect 不会被 legacy open lot 反向 auto-close

**Step 2: 跑相关测试**

Run: `D:\\fqpack\\freshquant-2026.2.23\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_order_management_reconcile.py freshquant/tests/test_order_ledger_v2_rebuild.py -q`

### Task 3: destructive rebuild 执行脚本与数据校验

**Files:**
- Reuse existing maintenance scripts where possible

**Step 1: 备份并 dry-run**

- 先备份 `freshquant_order_management`
- 再执行 rebuild dry-run

**Step 2: 清理并 execute rebuild**

- 清理 OM 运行期集合与 compat 投影
- 仅基于 `xt_orders / xt_trades / xt_positions` 重建

**Step 3: 运行 reconcile 校准**

- 让当前 broker 仓位与 rebuilt ledger 再收敛一次

**Step 4: 跑服务层校验**

- 校验 `SubjectManagementDashboardService`
- 校验 `TpslManagementService`
- 校验 `PositionManagementDashboardService`

### Task 4: 最终验证

**Files:**
- Optional Modify: `docs/current/modules/order-management.md`
- Optional Modify: `docs/current/modules/position-management.md`
- Optional Modify: `docs/current/modules/subject-management.md`
- Optional Modify: `docs/current/modules/tpsl.md`

**Step 1: 跑完整相关测试**

Run: `D:\\fqpack\\freshquant-2026.2.23\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_order_management_reconcile.py freshquant/tests/test_order_ledger_v2_rebuild.py freshquant/tests/test_order_management_db.py -q`

**Step 2: 跑数据库/服务层真值检查**

- `xt_positions > 0` 的 symbol 必须恢复为 open entry 或 open gap
- `subject/tpsl/kline` 明细返回非空 entries

**Step 3: 如有代码语义变更，同步模块文档**

