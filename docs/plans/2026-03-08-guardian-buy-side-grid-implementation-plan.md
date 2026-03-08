# Guardian Buy-Side Grid Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 RFC 0019 落到 Guardian 策略、订单域集成点和现有 stock API / CLI，确保买单数量规则、三层价格状态机和日志上下文都以新语义工作。

**Architecture:** 在 `freshquant/strategy/` 内新增 Guardian buy-side grid 服务，先通过失败测试锁住数量公式与状态机，再改造 `guardian.py`、订单受理后的状态更新与卖出成交重置，最后补齐现有 HTTP API / CLI 暴露面和迁移状态文档。

**Tech Stack:** Python、MongoDB、Flask、pytest、Dynaconf、Guardian strategy、Order Management

---

### Task 1: 切换文档状态并登记实施计划

**Files:**
- Modify: `docs/rfcs/0019-guardian-buy-side-grid-sizing.md`
- Modify: `docs/migration/progress.md`
- Create: `docs/plans/2026-03-08-guardian-buy-side-grid-design.md`
- Create: `docs/plans/2026-03-08-guardian-buy-side-grid-implementation-plan.md`

**Step 1: 将 RFC 0019 状态切到 `Implementing`**

- RFC 顶部状态从 `Approved` 改为 `Implementing`
- 在 `docs/migration/progress.md` 同步把 `0019` 状态改为 `Implementing`
- 备注补充“进入 TDD 与代码实现阶段”

**Step 2: 自检登记结果**

Run: `rg -n "0019|Implementing|guardian-buy-side-grid" docs/rfcs docs/migration/progress.md docs/plans`

Expected:
- RFC 0019 显示 `Implementing`
- `progress.md` 的 `0019` 行显示 `Implementing`
- 两份计划文档均被检索到

### Task 2: 先写 Guardian buy-side grid 服务测试

**Files:**
- Create: `freshquant/tests/test_guardian_buy_grid.py`

**Step 1: 写失败测试锁定以下行为**

- `initial_lot_amount` 默认与回退规则
- 最深命中层级优先
- 只消费仍处于 `buy_active=True` 的层级
- 受理成功后失活所有命中层级
- 无配置时按基础金额执行
- 卖出成交后重置全部 `buy_active`

**Step 2: 运行失败测试**

Run: `py -m pytest freshquant/tests/test_guardian_buy_grid.py -q`

Expected: FAIL，提示 Guardian buy-side grid 模块或函数尚不存在

### Task 3: 实现 Guardian buy-side grid 服务

**Files:**
- Create: `freshquant/strategy/guardian_buy_grid.py`

**Step 1: 实现最小服务**

- 配置/状态读取与 upsert
- 命中层级与最深层级选择
- 数量计算：
  - 新开仓使用 `initial_lot_amount ?? lot_amount ?? 150000`
  - 持仓加仓使用 `get_trade_amount()` 基础金额与 `2/3/4`
- 受理成功后失活所有命中层级
- 卖出成交后重置状态

**Step 2: 回跑测试**

Run: `py -m pytest freshquant/tests/test_guardian_buy_grid.py -q`

Expected: PASS

### Task 4: 改造 Guardian 主流程

**Files:**
- Modify: `freshquant/strategy/guardian.py`
- Add/Modify tests:
  - `freshquant/tests/test_guardian_strategy.py`

**Step 1: 先写失败测试**

- 持仓加仓命中 `BUY-3` 时按 `4x` 数量提交
- 新开仓使用 `initial_lot_amount`
- 不再依赖 `near_pattern` 和 `position_pct` 缩量
- 订单受理成功后才写冷却 key
- `remark` 与 grid 上下文透传到订单提交

**Step 2: 修改 Guardian**

- 移除旧买入缩量逻辑
- 区分新开仓 / 持仓加仓路径
- 改为在订单受理成功后写冷却 key
- 捕获仓位管理拒单并按业务结果处理

**Step 3: 回跑 Guardian 相关测试**

Run: `py -m pytest freshquant/tests/test_guardian_strategy.py freshquant/tests/test_order_management_guardian_submitter.py -q`

Expected: PASS

### Task 5: 接入订单域状态更新与卖出成交重置

**Files:**
- Modify: `freshquant/order_management/submit/service.py`
- Modify: `freshquant/order_management/ingest/xt_reports.py`
- Add/Modify tests:
  - `freshquant/tests/test_guardian_buy_grid_order_integration.py`

**Step 1: 先写失败测试**

- Guardian 买单受理成功后失活所有命中层级
- Guardian 买单被仓位管理拒绝时不失活层级
- 卖出成交事实落地后重置全部 `buy_active`

**Step 2: 实现受理成功与卖出成交后的状态更新**

**Step 3: 回跑集成测试**

Run: `py -m pytest freshquant/tests/test_guardian_buy_grid_order_integration.py -q`

Expected: PASS

### Task 6: 暴露 stock API / CLI

**Files:**
- Modify: `freshquant/rear/stock/routes.py`
- Modify: `freshquant/command/stock.py`
- Modify: `freshquant/cli.py`（如需要）
- Add/Modify tests:
  - `freshquant/tests/test_guardian_buy_grid_routes.py`
  - `freshquant/tests/test_guardian_buy_grid_cli.py`

**Step 1: 先写失败测试**

- 可读写 Guardian buy-side grid 配置
- 可读取 / 重置状态

**Step 2: 实现 API / CLI**

**Step 3: 回跑测试**

Run: `py -m pytest freshquant/tests/test_guardian_buy_grid_routes.py freshquant/tests/test_guardian_buy_grid_cli.py -q`

Expected: PASS

### Task 7: 全量回归与进度更新

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`（如行为语义已落地）

**Step 1: 运行目标测试集**

Run:
- `py -m pytest freshquant/tests/test_guardian_buy_grid.py -q`
- `py -m pytest freshquant/tests/test_guardian_strategy.py -q`
- `py -m pytest freshquant/tests/test_guardian_buy_grid_order_integration.py -q`
- `py -m pytest freshquant/tests/test_guardian_buy_grid_routes.py -q`
- `py -m pytest freshquant/tests/test_guardian_buy_grid_cli.py -q`

**Step 2: 更新迁移记录**

- `progress.md` 记录已完成内容、待跟进风险与下一步
- 如行为语义落地到默认路径，更新 `breaking-changes.md`

**Step 3: 最终自检**

Run: `git status --short`

Expected:
- 仅包含本次实现涉及文件
- 无意外改动
