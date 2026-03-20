# Guardian Disable buy_zs_huila Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 Guardian 正式事件链不再保存、展示或响应 `buy_zs_huila`，同时保持其他 5 类信号不变。

**Architecture:** 在 `monitor_stock_zh_a_min.py` 的事件入口过滤 `buy_zs_huila`，避免进入 `save_a_stock_signal()`。测试覆盖只验证正式 Guardian 事件链路，不修改通用信号 helper 的返回集合。

**Tech Stack:** Python 3.12、pytest、click CLI、现有 Guardian 事件监控链路

---

### Task 1: 落设计与计划文档

**Files:**
- Create: `docs/plans/2026-03-20-guardian-disable-buy-zs-huila-design.md`
- Create: `docs/plans/2026-03-20-guardian-disable-buy-zs-huila.md`

**Step 1: 写设计文档**

记录关闭范围、过滤位置和非目标。

**Step 2: 写实现计划**

把测试、实现、验证拆成独立步骤。

### Task 2: 为 Guardian 事件入口补失败测试

**Files:**
- Modify: `freshquant/tests/test_guardian_monitor_cli.py`

**Step 1: 写失败测试**

新增测试，直接检查 `monitor_stock_zh_a_min.py` 已声明 Guardian 事件链会过滤 `buy_zs_huila`。

**Step 2: 运行测试确认失败**

Run: `py -3.12 -m pytest freshquant/tests/test_guardian_monitor_cli.py -q`

Expected: FAIL，因为过滤逻辑尚未存在。

**Step 3: 写最小实现**

在 `freshquant/signal/astock/job/monitor_stock_zh_a_min.py` 中过滤 `buy_zs_huila`。

**Step 4: 运行测试确认通过**

Run: `py -3.12 -m pytest freshquant/tests/test_guardian_monitor_cli.py -q`

Expected: PASS

### Task 3: 验证相关 Guardian 回归

**Files:**
- No file changes required

**Step 1: 运行目标测试**

Run: `py -3.12 -m pytest freshquant/tests/test_guardian_monitor_cli.py -q`

Expected: PASS

**Step 2: 运行一组相关回归**

Run: `py -3.12 -m pytest freshquant/tests/test_guardian_strategy.py -q`

Expected: PASS；如果环境缺依赖，则记录真实阻塞，不虚报通过。
