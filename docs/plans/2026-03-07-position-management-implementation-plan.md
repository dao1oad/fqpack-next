# 仓位管理模块 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增独立的仓位管理模块，基于信用账户“可用保证金”持续产出三态仓位状态，并只对策略订单执行准入控制。

**Architecture:** 先完成 RFC 与迁移登记，再参照订单管理模块建立独立分库 `freshquant_position_management`、仓位状态仓库与 worker。worker 使用独立 xtquant 查询连接周期拉取 `query_credit_detail(account)`，将 `m_dEnableBailBalance` 落库并更新唯一状态源 `pm_current_state`；策略订单通过 `OrderSubmitService` 仅读取该状态做决策，人工单保持旁路。

**Tech Stack:** Python、xtquant、Dynaconf、MongoDB、pytest、Flask/OrderSubmitService

---

### Task 1: 起草 RFC 并登记迁移进度

**Files:**
- Create: `docs/rfcs/0013-position-management.md`
- Modify: `docs/migration/progress.md`
- Reference: `docs/plans/2026-03-07-position-management-design.md`

**Step 1: 按设计稿起草 RFC 0013**

```markdown
# RFC 0013: 融资账户仓位管理模块

- **状态**：Draft
- **负责人**：Codex
- **创建日期**：2026-03-07

## 1. 背景与问题
- `XtAsset.cash` 只是可用金额，不是可用保证金。
- 当前仓库缺少独立仓位管理模块，策略单无法按融资账户可用保证金进行三态管控。

## 2. 目标
- 独立分库 `freshquant_position_management`
- 独立 worker 持续查询 `query_credit_detail(account)`
- 三态：`ALLOW_OPEN` / `HOLDING_ONLY` / `FORCE_PROFIT_REDUCE`
- 只控制 `source=strategy` 的订单
```

**Step 2: 在迁移进度表登记 RFC 0013**

在 `docs/migration/progress.md` 新增一行，状态先写 `Draft`，备注中引用设计稿：

```markdown
| 0013 | 融资账户仓位管理模块 | Draft | Codex | 2026-03-07 | `D:\fqpack\freshquant\freshquant\strategy\toolkit\position_manager.py` / `position_risk_guard.py` / xtquant `query_credit_detail` | 设计稿已确认：独立分库、独立 worker、唯一状态源 `pm_current_state`、默认兜底状态 `HOLDING_ONLY`。 |
```

**Step 3: 自检 RFC 与进度登记**

Run: `rg -n "0013|position-management|仓位管理模块" docs/rfcs docs/migration/progress.md`

Expected:
- 输出 `docs/rfcs/0013-position-management.md`
- 输出 `docs/migration/progress.md` 中的 RFC 0013 行

**Step 4: Commit**

```bash
git add docs/rfcs/0013-position-management.md docs/migration/progress.md
git commit -m "docs: draft rfc for position management module"
```

### Task 2: 建立独立分库与仓位模块仓库层

**Files:**
- Create: `freshquant/position_management/__init__.py`
- Create: `freshquant/position_management/db.py`
- Create: `freshquant/position_management/models.py`
- Create: `freshquant/position_management/repository.py`
- Test: `freshquant/tests/test_position_management_db.py`

**Step 1: 先写失败测试，锁定独立分库与集合名**

```python
from freshquant.position_management.db import DEFAULT_POSITION_MANAGEMENT_DB
from freshquant.position_management.repository import PositionManagementRepository


def test_position_management_uses_dedicated_database():
    assert DEFAULT_POSITION_MANAGEMENT_DB == "freshquant_position_management"


def test_repository_exposes_expected_collections():
    repo = PositionManagementRepository(database={})
    assert repo.config_collection_name == "pm_configs"
    assert repo.snapshot_collection_name == "pm_credit_asset_snapshots"
    assert repo.current_state_collection_name == "pm_current_state"
    assert repo.decision_collection_name == "pm_strategy_decisions"
```

**Step 2: 跑测试确认失败**

Run: `py -3 -m pytest freshquant/tests/test_position_management_db.py -q`

Expected: FAIL，提示 `freshquant.position_management` 模块不存在。

**Step 3: 写最小实现**

```python
DEFAULT_POSITION_MANAGEMENT_DB = "freshquant_position_management"


class PositionManagementRepository:
    config_collection_name = "pm_configs"
    snapshot_collection_name = "pm_credit_asset_snapshots"
    current_state_collection_name = "pm_current_state"
    decision_collection_name = "pm_strategy_decisions"
```

- `db.py` 参照 `freshquant/order_management/db.py`，通过 `settings.get("position_management.mongo_database", DEFAULT_POSITION_MANAGEMENT_DB)` 获取独立分库名
- `repository.py` 先提供 4 张集合的基础 CRUD 包装
- `models.py` 先定义状态常量：
  - `ALLOW_OPEN`
  - `HOLDING_ONLY`
  - `FORCE_PROFIT_REDUCE`

**Step 4: 回跑测试**

Run: `py -3 -m pytest freshquant/tests/test_position_management_db.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/position_management/__init__.py freshquant/position_management/db.py freshquant/position_management/models.py freshquant/position_management/repository.py freshquant/tests/test_position_management_db.py
git commit -m "feat: add position management db and repository"
```

### Task 3: 实现信用资产查询、快照落库与 worker

**Files:**
- Create: `freshquant/position_management/credit_client.py`
- Create: `freshquant/position_management/snapshot_service.py`
- Create: `freshquant/position_management/worker.py`
- Test: `freshquant/tests/test_position_management_worker.py`
- Reference: `morningglory/fqxtrade/fqxtrade/xtquant/account.py`
- Reference: `freshquant/tests/test_xtquant_account_config.py`

**Step 1: 写失败测试，锁定查询成功与失败时的行为**

```python
from freshquant.position_management.models import HOLDING_ONLY
from freshquant.position_management.snapshot_service import PositionSnapshotService


class FakeCreditClient:
    def query_credit_detail(self):
        return [{
            "m_dEnableBailBalance": 865432.12,
            "m_dAvailable": 102345.67,
            "m_dFetchBalance": 92345.67,
            "m_dBalance": 1432100.0,
            "m_dMarketValue": 1210000.0,
            "m_dTotalDebt": 530000.0,
        }]


def test_refresh_writes_snapshot_and_current_state(fake_repo):
    service = PositionSnapshotService(repository=fake_repo, credit_client=FakeCreditClient())
    result = service.refresh_once()
    assert result["state"] == "ALLOW_OPEN"
    assert fake_repo.snapshots[-1]["available_bail_balance"] == 865432.12


def test_worker_keeps_previous_state_when_query_fails(fake_repo):
    fake_repo.current_state = {"state": HOLDING_ONLY, "evaluated_at": "2026-03-07T12:00:00+08:00"}
    service = PositionSnapshotService(repository=fake_repo, credit_client=Exception("timeout"))
    result = service.refresh_once()
    assert result["state"] == HOLDING_ONLY
    assert result["data_source"] == "mongo_fallback"
```

**Step 2: 跑测试确认失败**

Run: `py -3 -m pytest freshquant/tests/test_position_management_worker.py -q`

Expected: FAIL，提示 `PositionSnapshotService` 不存在。

**Step 3: 写最小实现**

```python
class PositionCreditClient:
    def query_credit_detail(self):
        xt_trader, account = self._ensure_credit_connection()
        return xt_trader.query_credit_detail(account)


class PositionSnapshotService:
    def refresh_once(self):
        details = self.credit_client.query_credit_detail()
        available_bail = float(details[0]["m_dEnableBailBalance"])
        snapshot = self.repository.insert_snapshot({...})
        state = self.policy.evaluate_from_bail(available_bail)
        return self.repository.upsert_current_state({...})
```

- `credit_client.py` 必须使用独立 session，不复用 broker 连接
- 账号类型必须校验为 `CREDIT`，否则抛出明确错误
- `worker.py` 先提供：
  - `python -m freshquant.position_management.worker --once`
  - `python -m freshquant.position_management.worker`

**Step 4: 回跑测试**

Run: `py -3 -m pytest freshquant/tests/test_position_management_worker.py -q`

Expected: PASS

**Step 5: 手工 smoke 验证单次刷新**

Run: `py -3 -m freshquant.position_management.worker --once`

Expected:
- 控制台打印刷新结果
- Mongo 中出现一条 `pm_credit_asset_snapshots`
- `pm_current_state` 被更新

**Step 6: Commit**

```bash
git add freshquant/position_management/credit_client.py freshquant/position_management/snapshot_service.py freshquant/position_management/worker.py freshquant/tests/test_position_management_worker.py
git commit -m "feat: add position management worker and snapshot refresh"
```

### Task 4: 实现状态策略、过旧保护与订单决策服务

**Files:**
- Create: `freshquant/position_management/policy.py`
- Create: `freshquant/position_management/service.py`
- Create: `freshquant/position_management/errors.py`
- Test: `freshquant/tests/test_position_management_policy.py`
- Reference: `freshquant/data/astock/holding.py`

**Step 1: 写失败测试，锁定三态、边界值和默认兜底**

```python
from freshquant.position_management.models import (
    ALLOW_OPEN,
    HOLDING_ONLY,
    FORCE_PROFIT_REDUCE,
)
from freshquant.position_management.policy import PositionPolicy


def test_bail_above_800k_allows_open():
    policy = PositionPolicy(allow_open_min_bail=800000, holding_only_min_bail=100000)
    assert policy.state_from_bail(800001) == ALLOW_OPEN


def test_bail_equal_800k_falls_into_holding_only():
    policy = PositionPolicy(allow_open_min_bail=800000, holding_only_min_bail=100000)
    assert policy.state_from_bail(800000) == HOLDING_ONLY


def test_missing_or_stale_state_defaults_to_holding_only():
    policy = PositionPolicy(state_stale_after_seconds=15, default_state=HOLDING_ONLY)
    assert policy.effective_state(None, now_ts=100) == HOLDING_ONLY
```

**Step 2: 跑测试确认失败**

Run: `py -3 -m pytest freshquant/tests/test_position_management_policy.py -q`

Expected: FAIL，提示 `PositionPolicy` 不存在。

**Step 3: 写最小实现**

```python
class PositionPolicy:
    def state_from_bail(self, available_bail_balance: float) -> str:
        if available_bail_balance > self.allow_open_min_bail:
            return ALLOW_OPEN
        if available_bail_balance > self.holding_only_min_bail:
            return HOLDING_ONLY
        return FORCE_PROFIT_REDUCE
```

- `service.py` 提供 `evaluate_strategy_order(payload)`：
  - 读取 `pm_current_state`
  - 若状态缺失或 `evaluated_at` 过旧，则有效状态回退为 `HOLDING_ONLY`
  - 结合 `get_stock_holding_codes()` 判定是否允许该策略单
  - 生成 `pm_strategy_decisions` 审计记录
- `errors.py` 定义：
  - `PositionManagementRejectedError`
  - `PositionManagementUnavailableError`

**Step 4: 补充失败测试，锁定下单矩阵**

```python
def test_holding_only_blocks_new_symbol_buy(service):
    result = service.evaluate_strategy_order(
        {"source": "strategy", "action": "buy", "symbol": "000001"},
        current_state={"state": HOLDING_ONLY, "evaluated_at": "2026-03-07T12:00:00+08:00"},
        holding_codes=["000002"],
    )
    assert result.allowed is False


def test_force_profit_reduce_blocks_all_buys(service):
    result = service.evaluate_strategy_order(
        {"source": "strategy", "action": "buy", "symbol": "000001"},
        current_state={"state": FORCE_PROFIT_REDUCE, "evaluated_at": "2026-03-07T12:00:00+08:00"},
        holding_codes=["000001"],
    )
    assert result.allowed is False
```

**Step 5: 回跑测试**

Run: `py -3 -m pytest freshquant/tests/test_position_management_policy.py -q`

Expected: PASS

**Step 6: Commit**

```bash
git add freshquant/position_management/policy.py freshquant/position_management/service.py freshquant/position_management/errors.py freshquant/tests/test_position_management_policy.py
git commit -m "feat: add position management policy and decision service"
```

### Task 5: 接入策略订单提交流程，只控制 `source=strategy`

**Files:**
- Modify: `freshquant/order_management/submit/service.py`
- Test: `freshquant/tests/test_position_management_submit_gate.py`
- Reference: `freshquant/tests/test_order_management_submit_service.py`

**Step 1: 写失败测试，锁定策略单受控、人工单旁路**

```python
from freshquant.order_management.submit.service import OrderSubmitService


def test_strategy_order_is_blocked_when_position_management_rejects(fake_repo, fake_queue):
    service = OrderSubmitService(
        repository=fake_repo,
        queue_client=fake_queue,
        position_management_service=RejectingPositionService(),
    )
    try:
        service.submit_order({
            "action": "buy",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 100,
            "source": "strategy",
        })
    except ValueError as exc:
        assert "position management rejected" in str(exc)


def test_api_order_bypasses_position_management(fake_repo, fake_queue):
    service = OrderSubmitService(
        repository=fake_repo,
        queue_client=fake_queue,
        position_management_service=RejectingPositionService(),
    )
    result = service.submit_order({
        "action": "buy",
        "symbol": "000001",
        "price": 10.0,
        "quantity": 100,
        "source": "api",
    })
    assert result["internal_order_id"]
```

**Step 2: 跑测试确认失败**

Run: `py -3 -m pytest freshquant/tests/test_position_management_submit_gate.py -q`

Expected: FAIL，`OrderSubmitService` 还不支持注入仓位管理服务。

**Step 3: 写最小实现**

```python
if payload.get("source") == "strategy":
    decision = self.position_management_service.evaluate_strategy_order(payload)
    if not decision.allowed:
        raise ValueError(f"position management rejected: {decision.reason_code}")
```

- 允许通过依赖注入传入 `position_management_service`
- 被允许的策略单将决策摘要透传到 `queue_payload`：
  - `position_management_state`
  - `position_management_decision_id`
- 人工单完全跳过该逻辑

**Step 4: 回跑测试**

Run: `py -3 -m pytest freshquant/tests/test_position_management_submit_gate.py freshquant/tests/test_order_management_submit_service.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/order_management/submit/service.py freshquant/tests/test_position_management_submit_gate.py
git commit -m "feat: gate strategy submits with position management state"
```

### Task 6: 为 `FORCE_PROFIT_REDUCE` 接入 Guardian 占位语义并完成部署文档

**Files:**
- Modify: `freshquant/position_management/service.py`
- Modify: `freshquant/strategy/guardian.py`
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`
- Modify: `docs/agent/项目目标与代码现状调研.md`
- Test: `freshquant/tests/test_position_management_guardian_placeholder.py`

**Step 1: 写失败测试，锁定 Guardian 占位标志**

```python
from freshquant.position_management.models import FORCE_PROFIT_REDUCE
from freshquant.position_management.service import PositionManagementService


def test_force_profit_reduce_marks_guardian_placeholder():
    decision = PositionManagementService(...).build_sell_decision(
        payload={"source": "strategy", "strategy_name": "Guardian", "action": "sell", "symbol": "000001"},
        current_state={"state": FORCE_PROFIT_REDUCE},
        is_profitable=True,
    )
    assert decision.meta["force_profit_reduce"] is True
    assert decision.meta["profit_reduce_mode"] == "guardian_placeholder"
```

**Step 2: 跑测试确认失败**

Run: `py -3 -m pytest freshquant/tests/test_position_management_guardian_placeholder.py -q`

Expected: FAIL

**Step 3: 写最小实现**

```python
if state == FORCE_PROFIT_REDUCE and action == "sell" and is_profitable:
    meta["force_profit_reduce"] = True
    meta["profit_reduce_mode"] = "guardian_placeholder"
```

- `freshquant/strategy/guardian.py` 本轮只读取并记录该占位标志，不改变卖出数量算法
- 更新迁移文档：
  - `progress.md`：RFC 状态从 `Draft` -> `Approved` -> `Implementing/Done`
  - `breaking-changes.md`：登记“新增独立分库 `freshquant_position_management`，策略单接入仓位状态门禁，人工单不受影响”
  - `项目目标与代码现状调研.md`：补充该模块已落地后的入口与依赖

**Step 4: 回跑测试**

Run: `py -3 -m pytest freshquant/tests/test_position_management_guardian_placeholder.py -q`

Expected: PASS

**Step 5: 回归测试**

Run:
- `py -3 -m pytest freshquant/tests/test_position_management_db.py freshquant/tests/test_position_management_worker.py freshquant/tests/test_position_management_policy.py freshquant/tests/test_position_management_submit_gate.py freshquant/tests/test_position_management_guardian_placeholder.py -q`

Expected: PASS

**Step 6: Commit**

```bash
git add freshquant/position_management/service.py freshquant/strategy/guardian.py docs/migration/progress.md docs/migration/breaking-changes.md docs/agent/项目目标与代码现状调研.md freshquant/tests/test_position_management_guardian_placeholder.py
git commit -m "feat: add guardian placeholder for profit reduce state"
```

