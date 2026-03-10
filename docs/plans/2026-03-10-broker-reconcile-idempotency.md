# Broker Reconcile Idempotency Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复外部成交 reconcile 的重复入账问题，并让重复终态 order report 幂等化，避免 broker 再次触发切片超卖和 `FILLED -> FILLED` 异常。

**Architecture:** 保持现有 `xt_reports -> tracking -> reconcile -> guardian allocations` 链路不变，只在 `ExternalOrderReconcileService` 和 `OrderTrackingService` 增加最小幂等收口。先用回归测试锁定重复 externalize 与重复 FILLED 行为，再做最小代码改动。

**Tech Stack:** Python 3.12, pytest, Mongo repository abstractions, supervisor-hosted XT broker

---

### Task 1: 建立回归测试基线

**Files:**
- Test: `freshquant/tests/test_order_management_tracking_service.py`
- Test: `freshquant/tests/test_order_management_xt_ingest.py`

**Step 1: 运行聚焦基线测试**

Run: `D:/fqpack/miniconda3/envs/fqkit/python.exe -m pytest freshquant/tests/test_order_management_tracking_service.py freshquant/tests/test_order_management_xt_ingest.py -q`

Expected: 现有测试通过，作为修复前基线。

**Step 2: 记录当前问题不在已有测试覆盖内**

确认现有测试没有覆盖：

- candidate 被部分外部成交命中后仍在超时阶段再次确认
- 重复 `FILLED` order report no-op

### Task 2: 先写失败测试覆盖重复 FILLED

**Files:**
- Modify: `freshquant/tests/test_order_management_tracking_service.py`
- Modify: `freshquant/order_management/tracking/service.py`

**Step 1: 写失败测试**

添加一个测试，先把 order 状态置为 `FILLED`，再重复 ingest 同样的 `FILLED` report，断言不抛异常且不新增重复 event。

**Step 2: 运行单测并确认失败**

Run: `D:/fqpack/miniconda3/envs/fqkit/python.exe -m pytest freshquant/tests/test_order_management_tracking_service.py -q`

Expected: 新增用例失败，失败原因为当前实现会抛 `InvalidOrderTransition`。

**Step 3: 写最小实现**

在 `OrderTrackingService.ingest_order_report()` 中对 `current_state == report["state"]` 直接返回当前 order，不再走状态机。

**Step 4: 重新运行单测确认通过**

Run: `D:/fqpack/miniconda3/envs/fqkit/python.exe -m pytest freshquant/tests/test_order_management_tracking_service.py -q`

Expected: 全部通过。

### Task 3: 先写失败测试覆盖 candidate 重复确认

**Files:**
- Modify: `freshquant/tests/test_order_management_xt_ingest.py`
- Modify: `freshquant/order_management/reconcile/service.py`

**Step 1: 写失败测试**

新增一个 reconcile 回归测试：

- 先造一个 `INFERRED_PENDING` 的 sell candidate
- 再喂入一笔匹配 candidate 的 XT sell trade，数量小于 candidate
- 再执行 `confirm_expired_candidates()`
- 断言 confirm 只会确认剩余量，不会把原始整单再次外部化

再新增一个整单匹配场景：

- XT trade 数量等于 candidate 数量
- confirm 阶段不再生成任何 inferred trade

**Step 2: 运行单测并确认失败**

Run: `D:/fqpack/miniconda3/envs/fqkit/python.exe -m pytest freshquant/tests/test_order_management_xt_ingest.py -q`

Expected: 新增用例失败，失败原因为 candidate 仍保留原始整单并再次 confirm。

**Step 3: 写最小实现**

在 `ExternalOrderReconcileService.reconcile_trade_reports()` 中：

- 命中 candidate 时，按真实成交量更新 candidate
- 全额命中则标记 `MATCHED`
- 部分命中则收缩 `quantity_delta` 并延续 `INFERRED_PENDING`
- 创建 external order 前先复用同 `broker_order_id` 的 existing external order

**Step 4: 重新运行单测确认通过**

Run: `D:/fqpack/miniconda3/envs/fqkit/python.exe -m pytest freshquant/tests/test_order_management_xt_ingest.py -q`

Expected: 新增用例通过。

### Task 4: 更新迁移进度记录

**Files:**
- Modify: `docs/migration/progress.md`

**Step 1: 在 RFC 0007 条目追加修复说明**

记录 2026-03-10 的补丁说明：

- 修复 external candidate 在部分外部成交后仍会超时重复确认的问题
- 修复重复终态 XT order report 触发 `FILLED -> FILLED` 异常的问题

**Step 2: 校验文档更新**

Run: `git diff -- docs/migration/progress.md`

Expected: 只新增本次修复说明。

### Task 5: 聚焦验证

**Files:**
- Test: `freshquant/tests/test_order_management_tracking_service.py`
- Test: `freshquant/tests/test_order_management_xt_ingest.py`

**Step 1: 运行聚焦测试**

Run: `D:/fqpack/miniconda3/envs/fqkit/python.exe -m pytest freshquant/tests/test_order_management_tracking_service.py freshquant/tests/test_order_management_xt_ingest.py -q`

Expected: 全部通过。

**Step 2: 验证 supervisor broker 仍正常**

Run: `D:/fqpack/supervisord/supervisord.exe ctl -c D:/fqpack/config/supervisord.fqnext.conf status fqnext_xtquant_broker`

Expected: `Running`

**Step 3: Commit**

```bash
git add docs/plans/2026-03-10-broker-reconcile-idempotency-design.md docs/plans/2026-03-10-broker-reconcile-idempotency.md docs/migration/progress.md freshquant/order_management/reconcile/service.py freshquant/order_management/tracking/service.py freshquant/tests/test_order_management_tracking_service.py freshquant/tests/test_order_management_xt_ingest.py
git commit -m "修复 broker reconcile 重复入账幂等问题"
```
