# Stock / ETF Order Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在目标仓库落地 `RFC 0007`，建立独立数据库 `freshquant_order_management` 中的股票/ETF 订单管理主账本，并在不改变 Guardian 卖出语义的前提下完成逐买入跟踪、兼容投影、外部订单推断与单笔止损迁移。

**Architecture:** 采用“主账本 + 兼容投影”架构：统一下单请求与 XT 回报先进入 `om_*` 主账本，再派生 `buy_lots / lot_slices / sell_allocations` 与 `stock_fills` 兼容投影。Guardian、旧 API/UI 与后续止损模块通过兼容读模型切换，迁移期保留 dual-read compare、legacy adapter 与缓存失效守卫，确保语义不漂移。

**Tech Stack:** Python、PyMongo、Flask、Click、Redis、MiniQMT/XTQuant、pytest

---

### Task 1: 独立数据库配置与模块骨架

**Files:**
- Create: `freshquant/order_management/__init__.py`
- Create: `freshquant/order_management/db.py`
- Modify: `freshquant/db.py`
- Modify: `freshquant/database/mongodb.py`
- Modify: `freshquant/freshquant.yaml`
- Modify: `docs/agent/配置管理指南.md`
- Test: `freshquant/tests/test_order_management_db.py`

**Step 1: Write the failing test**

先写配置与数据库入口测试，覆盖独立数据库名与投影数据库名：

```python
def test_order_management_db_uses_dedicated_database(monkeypatch): ...
def test_order_management_projection_db_defaults_to_freshquant(monkeypatch): ...
```

**Step 2: Run test to verify it fails**

Run: `pytest freshquant/tests/test_order_management_db.py -q`

Expected: FAIL，因为 `freshquant.order_management.db` 与独立数据库配置尚不存在。

**Step 3: Write minimal implementation**

- 在 `freshquant/order_management/db.py` 中新增 `DBOrderManagement`、`get_order_management_db()`、`get_projection_db()`
- 在 `freshquant/db.py` 与 `freshquant/database/mongodb.py` 中暴露同一 MongoClient 下的独立数据库访问
- 在 `freshquant/freshquant.yaml` 中新增：
  - `order_management.mongo_database`
  - `order_management.projection_database`
  - `order_management.external_confirm_seconds`
  - `order_management.guardian_allocation_policy`
- 在 `docs/agent/配置管理指南.md` 中补充新库与投影库的配置说明

**Step 4: Run test to verify it passes**

Run: `pytest freshquant/tests/test_order_management_db.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/order_management/__init__.py freshquant/order_management/db.py freshquant/db.py freshquant/database/mongodb.py freshquant/freshquant.yaml docs/agent/配置管理指南.md freshquant/tests/test_order_management_db.py
git commit -m "feat: add order management database configuration"
```

### Task 2: 订单主账本写模型与幂等仓储

**Files:**
- Create: `freshquant/order_management/ids.py`
- Create: `freshquant/order_management/repository.py`
- Create: `freshquant/order_management/tracking/service.py`
- Create: `freshquant/order_management/tracking/state_machine.py`
- Test: `freshquant/tests/test_order_management_tracking_service.py`

**Step 1: Write the failing tests**

用纯单元测试先锁住主账本最小语义：

```python
def test_submit_order_creates_request_order_and_accepted_event(): ...
def test_cancel_order_creates_cancel_request_and_event(): ...
def test_ingest_trade_report_is_idempotent_by_broker_trade_id(): ...
def test_order_state_machine_rejects_invalid_transition(): ...
```

**Step 2: Run tests to verify they fail**

Run: `pytest freshquant/tests/test_order_management_tracking_service.py -q`

Expected: FAIL，因为主账本仓储、ID 生成与状态机尚不存在。

**Step 3: Write minimal implementation**

- 在 `ids.py` 中统一生成 `request_id / internal_order_id / trade_fact_id / buy_lot_id / lot_slice_id`
- 在 `repository.py` 中封装 `om_order_requests / om_orders / om_order_events / om_trade_facts` 的最小 CRUD 与幂等 upsert
- 在 `tracking/state_machine.py` 中定义 `ACCEPTED / QUEUED / SUBMITTED / PARTIAL_FILLED / FILLED / CANCEL_REQUESTED / CANCELED / FAILED / INFERRED_PENDING / INFERRED_CONFIRMED`
- 在 `tracking/service.py` 中实现：
  - `submit_order(payload)`
  - `cancel_order(payload)`
  - `ingest_order_report(report)`
  - `ingest_trade_report(report)`

**Step 4: Run tests to verify they pass**

Run: `pytest freshquant/tests/test_order_management_tracking_service.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/order_management/ids.py freshquant/order_management/repository.py freshquant/order_management/tracking/service.py freshquant/order_management/tracking/state_machine.py freshquant/tests/test_order_management_tracking_service.py
git commit -m "feat: add order management write model"
```

### Task 3: Guardian 语义核心与逐买入卖出分摊

**Files:**
- Create: `freshquant/order_management/guardian/__init__.py`
- Create: `freshquant/order_management/guardian/arranger.py`
- Create: `freshquant/order_management/guardian/allocation_policy.py`
- Create: `freshquant/order_management/guardian/read_model.py`
- Test: `freshquant/tests/test_order_management_guardian_semantics.py`
- Test: `freshquant/tests/assets/order_management_guardian_cases.json`

**Step 1: Write the failing tests**

先用黄金样本锁住当前 `accStockTrades()` / `accArrangedStockTrades()` 的业务语义，而不是直接照搬实现：

```python
def test_arranger_splits_buy_into_guardian_slices_using_current_grid_rules(): ...
def test_sell_allocation_consumes_lowest_guardian_price_first(): ...
def test_partial_sell_updates_buy_lot_remaining_and_sell_history(): ...
def test_guardian_read_model_matches_legacy_sell_quantity_cases(): ...
```

**Step 2: Run tests to verify they fail**

Run: `pytest freshquant/tests/test_order_management_guardian_semantics.py -q`

Expected: FAIL，因为 `buy_lots / lot_slices / sell_allocations` 尚未建模。

**Step 3: Write minimal implementation**

- 在 `arranger.py` 中实现买入 lot 到 Guardian slices 的拆层逻辑，并固化 `arrange_snapshot`
- 在 `allocation_policy.py` 中实现 `guardian_compat_low_price_first`
- 在 `read_model.py` 中输出与当前 `get_arranged_stock_fill_list()` 兼容的结构
- 黄金样本至少覆盖：
  - 单笔大买单递归拆层
  - 多笔买入后部分卖出
  - 卖出只扣低价层
  - 原始 lot 的卖出历史可追踪

**Step 4: Run tests to verify they pass**

Run: `pytest freshquant/tests/test_order_management_guardian_semantics.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/order_management/guardian/__init__.py freshquant/order_management/guardian/arranger.py freshquant/order_management/guardian/allocation_policy.py freshquant/order_management/guardian/read_model.py freshquant/tests/test_order_management_guardian_semantics.py freshquant/tests/assets/order_management_guardian_cases.json
git commit -m "feat: add guardian-compatible lot slicing and allocation"
```

### Task 4: XT 回报接入与 `stock_fills` 兼容投影

**Files:**
- Create: `freshquant/order_management/ingest/__init__.py`
- Create: `freshquant/order_management/ingest/xt_reports.py`
- Create: `freshquant/order_management/projection/__init__.py`
- Create: `freshquant/order_management/projection/stock_fills.py`
- Modify: `morningglory/fqxtrade/fqxtrade/xtquant/puppet.py`
- Modify: `morningglory/fqxtrade/fqxtrade/xtquant/broker.py`
- Test: `freshquant/tests/test_order_management_xt_ingest.py`

**Step 1: Write the failing tests**

覆盖“XT 回报 -> 主账本 -> lots/slices -> projection”链路：

```python
def test_trade_report_creates_trade_fact_buy_lot_and_slices(): ...
def test_sell_trade_report_creates_sell_allocations_and_updates_projection(): ...
def test_repeated_callback_does_not_duplicate_trade_fact_or_projection(): ...
```

**Step 2: Run tests to verify they fail**

Run: `pytest freshquant/tests/test_order_management_xt_ingest.py -q`

Expected: FAIL，因为 XT 回报尚未进入新账本，也没有投影器。

**Step 3: Write minimal implementation**

- 在 `xt_reports.py` 中将 XT `order/trade` 回报转换成 `tracking.service` 可接收的标准载荷
- 在 `projection/stock_fills.py` 中实现：
  - `raw fills view`
  - `open buy fills view`
  - `arranged fills view`
- 修改 `puppet.saveTrades()` / `puppet.saveOrders()`：保留当前 `xt_trades / xt_orders / stock_orders` 写入，同时追加调用新订单域入口
- 修改 `broker.py` 中的 callback：回报进来后统一进入新订单域

**Step 4: Run tests to verify they pass**

Run: `pytest freshquant/tests/test_order_management_xt_ingest.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/order_management/ingest/__init__.py freshquant/order_management/ingest/xt_reports.py freshquant/order_management/projection/__init__.py freshquant/order_management/projection/stock_fills.py morningglory/fqxtrade/fqxtrade/xtquant/puppet.py morningglory/fqxtrade/fqxtrade/xtquant/broker.py freshquant/tests/test_order_management_xt_ingest.py
git commit -m "feat: ingest xt reports into order management ledger"
```

### Task 5: 持仓读模型切换、Dual-Read Compare 与缓存失效

**Files:**
- Create: `freshquant/order_management/projection/cache_invalidator.py`
- Modify: `freshquant/data/astock/holding.py`
- Modify: `freshquant/position/stock.py`
- Modify: `freshquant/database/cache.py`
- Test: `freshquant/tests/test_order_management_holding_adapter.py`

**Step 1: Write the failing tests**

优先锁住“新读模型输出 == 旧语义输出”与缓存刷新行为：

```python
def test_get_stock_fill_list_reads_open_buy_projection(): ...
def test_get_arranged_stock_fill_list_matches_legacy_case_output(): ...
def test_projection_refresh_invalidates_holding_code_cache(): ...
```

**Step 2: Run tests to verify they fail**

Run: `pytest freshquant/tests/test_order_management_holding_adapter.py -q`

Expected: FAIL，因为 `holding.py` 仍直接依赖 `stock_fills` 原始重算逻辑。

**Step 3: Write minimal implementation**

- 在 `holding.py` 中引入新订单域读模型，并保留 legacy reader 作为 dual-read compare
- 新增差异日志：当新旧 `arranged fills` 不一致时按 symbol 输出可排查日志
- 在 `cache_invalidator.py` 中实现 `get_stock_holding_codes()` 相关缓存失效；如果 `Memoizer` 无精确删除能力，就补一个版本化 key 方案
- 同步修正 `position/stock.py` 与持仓查询，避免继续直接拼 raw `stock_fills`

**Step 4: Run tests to verify they pass**

Run: `pytest freshquant/tests/test_order_management_holding_adapter.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/order_management/projection/cache_invalidator.py freshquant/data/astock/holding.py freshquant/position/stock.py freshquant/database/cache.py freshquant/tests/test_order_management_holding_adapter.py
git commit -m "feat: switch holding reads to order management projections"
```

### Task 6: 统一下单入口接管策略、HTTP API 与 CLI

**Files:**
- Create: `freshquant/order_management/submit/__init__.py`
- Create: `freshquant/order_management/submit/service.py`
- Create: `freshquant/rear/order/__init__.py`
- Create: `freshquant/rear/order/routes.py`
- Create: `freshquant/command/om_order.py`
- Modify: `freshquant/rear/api_server.py`
- Modify: `freshquant/strategy/guardian.py`
- Modify: `freshquant/cli.py`
- Test: `freshquant/tests/test_order_management_submit_service.py`
- Test: `freshquant/tests/test_order_management_routes.py`
- Test: `freshquant/tests/test_order_management_cli.py`

**Step 1: Write the failing tests**

先锁住三类系统内入口统一接管：

```python
def test_guardian_buy_signal_submits_order_request_instead_of_direct_queue_write(): ...
def test_http_manual_order_creates_request_and_returns_request_id(): ...
def test_cli_manual_order_submits_via_order_management_service(): ...
```

**Step 2: Run tests to verify they fail**

Run: `pytest freshquant/tests/test_order_management_submit_service.py freshquant/tests/test_order_management_routes.py freshquant/tests/test_order_management_cli.py -q`

Expected: FAIL，因为当前策略/API/CLI 还没有统一走订单域受理层。

**Step 3: Write minimal implementation**

- 在 `submit/service.py` 中统一封装 `buy / sell / cancel`
- 修改 `guardian.py`：不再直接 `lpush STOCK_ORDER_QUEUE`，改为调用订单域受理层，由订单域决定投递执行消息
- 在 `freshquant/rear/order/routes.py` 中新增：
  - `POST /api/order/submit`
  - `POST /api/order/cancel`
  - 兼容入口 `POST /api/stock_order`
- 在 `freshquant/command/om_order.py` 中新增 CLI 手工下单与撤单命令
- 在 `freshquant/cli.py` 与 `api_server.py` 中注册新入口

**Step 4: Run tests to verify they pass**

Run: `pytest freshquant/tests/test_order_management_submit_service.py freshquant/tests/test_order_management_routes.py freshquant/tests/test_order_management_cli.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/order_management/submit/__init__.py freshquant/order_management/submit/service.py freshquant/rear/order/__init__.py freshquant/rear/order/routes.py freshquant/command/om_order.py freshquant/rear/api_server.py freshquant/strategy/guardian.py freshquant/cli.py freshquant/tests/test_order_management_submit_service.py freshquant/tests/test_order_management_routes.py freshquant/tests/test_order_management_cli.py
git commit -m "feat: unify order submission ingress"
```

### Task 7: 外部订单对账、推断态与 120 秒自动确认

**Files:**
- Create: `freshquant/order_management/reconcile/__init__.py`
- Create: `freshquant/order_management/reconcile/service.py`
- Create: `freshquant/order_management/reconcile/matcher.py`
- Modify: `morningglory/fqxtrade/fqxtrade/xtquant/puppet.py`
- Modify: `morningglory/fqxtrade/fqxtrade/xtquant/broker.py`
- Test: `freshquant/tests/test_order_management_reconcile.py`

**Step 1: Write the failing tests**

覆盖两类场景：有回报的外部订单、只有仓位变化的外部订单。

```python
def test_reconcile_matches_external_trade_report_to_existing_candidate(): ...
def test_position_delta_creates_inferred_pending_trade_fact(): ...
def test_inferred_pending_auto_confirms_after_120_seconds(): ...
def test_late_trade_report_merges_and_corrects_provisional_record(): ...
```

**Step 2: Run tests to verify they fail**

Run: `pytest freshquant/tests/test_order_management_reconcile.py -q`

Expected: FAIL，因为当前没有外部订单候选与自动确认逻辑。

**Step 3: Write minimal implementation**

- 在 `matcher.py` 中实现按 `broker_order_id / broker_trade_id / symbol + side + time window` 的匹配规则
- 在 `service.py` 中实现：
  - `reconcile_account(account_id)`
  - `detect_external_candidates(positions, assets, xt_orders, xt_trades)`
  - `confirm_expired_candidates(now)`
- 修改 `puppet.sync_positions()` / `sync_orders()` / `sync_trades()` 的空闲轮询路径，使其在同步后触发新订单域对账

**Step 4: Run tests to verify they pass**

Run: `pytest freshquant/tests/test_order_management_reconcile.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/order_management/reconcile/__init__.py freshquant/order_management/reconcile/service.py freshquant/order_management/reconcile/matcher.py morningglory/fqxtrade/fqxtrade/xtquant/puppet.py morningglory/fqxtrade/fqxtrade/xtquant/broker.py freshquant/tests/test_order_management_reconcile.py
git commit -m "feat: add external order reconciliation"
```

### Task 8: 单笔止损迁移到 `buy_lot_id`

**Files:**
- Create: `freshquant/order_management/stoploss/__init__.py`
- Create: `freshquant/order_management/stoploss/service.py`
- Create: `freshquant/order_management/stoploss/legacy_adapter.py`
- Modify: `freshquant/rear/order/routes.py`
- Test: `freshquant/tests/test_order_management_stoploss.py`

**Step 1: Write the failing tests**

优先覆盖“部分卖出后只止损剩余部分”的关键语义：

```python
def test_stoploss_binds_to_buy_lot_not_projection_row(): ...
def test_stoploss_only_acts_on_remaining_quantity_of_partially_sold_lot(): ...
def test_buy_lot_detail_returns_sell_history_and_stoploss_state(): ...
```

**Step 2: Run tests to verify they fail**

Run: `pytest freshquant/tests/test_order_management_stoploss.py -q`

Expected: FAIL，因为当前没有 `buy_lot_id` 绑定的止损服务。

**Step 3: Write minimal implementation**

- 在 `stoploss/service.py` 中实现：
  - `bind_stoploss(buy_lot_id, ...)`
  - `evaluate_stoploss(symbol, price)`
  - `build_stoploss_sell_request(buy_lot_id, quantity)`
- 使用 `sell_allocations` 计算 `buy_lot.remaining_quantity`
- 在 `legacy_adapter.py` 中提供从旧 `fill_id` 查询迁移到 `buy_lot_id` 的兼容查询
- 在 `freshquant/rear/order/routes.py` 中增加：
  - `GET /api/order-management/buy-lots/<buy_lot_id>`
  - `POST /api/order-management/stoploss/bind`

**Step 4: Run tests to verify they pass**

Run: `pytest freshquant/tests/test_order_management_stoploss.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/order_management/stoploss/__init__.py freshquant/order_management/stoploss/service.py freshquant/order_management/stoploss/legacy_adapter.py freshquant/rear/order/routes.py freshquant/tests/test_order_management_stoploss.py
git commit -m "feat: migrate per-lot stoploss to buy_lot ids"
```

### Task 9: 收口 `stock_fills` 直写路径与治理收尾

**Files:**
- Modify: `freshquant/data/astock/fill.py`
- Modify: `freshquant/toolkit/import_deals.py`
- Modify: `freshquant/rear/stock/routes.py`
- Modify: `freshquant/data/astock/holding.py`
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`
- Test: `freshquant/tests/test_order_management_manual_projection_writes.py`

**Step 1: Write the failing tests**

锁住人工导入、reset、cleanup/compact 不再直接写主事实：

```python
def test_import_fill_creates_manual_trade_fact_and_projection(): ...
def test_reset_stock_fills_creates_manual_locked_buy_lots(): ...
def test_compact_or_cleanup_no_longer_mutates_order_management_ledger(): ...
```

**Step 2: Run tests to verify they fail**

Run: `pytest freshquant/tests/test_order_management_manual_projection_writes.py -q`

Expected: FAIL，因为当前这些入口仍直接写 `stock_fills`。

**Step 3: Write minimal implementation**

- 修改 `freshquant/data/astock/fill.py`：`import_fill()` 改为写手工 `trade_fact / buy_lot / sell_allocation`
- 修改 `freshquant/toolkit/import_deals.py`：Excel 导入改为调订单域服务
- 修改 `freshquant/rear/stock/routes.py`：`/stock_fills/reset` 改为生成 `manual_locked buy_lots`
- 修改 `holding.py` 中 `clean_stock_fills()` / `compact_stock_fills()`：只处理兼容投影或归档，不再直接破坏主账本
- 实现落地时同步更新：
  - `docs/migration/progress.md`
  - `docs/migration/breaking-changes.md`

**Step 4: Run tests to verify they pass**

Run: `pytest freshquant/tests/test_order_management_manual_projection_writes.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/data/astock/fill.py freshquant/toolkit/import_deals.py freshquant/rear/stock/routes.py freshquant/data/astock/holding.py docs/migration/progress.md docs/migration/breaking-changes.md freshquant/tests/test_order_management_manual_projection_writes.py
git commit -m "feat: route legacy stock fill writes through order management"
```

### Task 10: 全链路验证与迁移文档收口

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`
- Reference: `docs/rfcs/0007-stock-etf-order-management.md`

**Step 1: Run targeted tests**

Run: `pytest freshquant/tests/test_order_management_db.py freshquant/tests/test_order_management_tracking_service.py freshquant/tests/test_order_management_guardian_semantics.py freshquant/tests/test_order_management_xt_ingest.py freshquant/tests/test_order_management_holding_adapter.py freshquant/tests/test_order_management_submit_service.py freshquant/tests/test_order_management_routes.py freshquant/tests/test_order_management_cli.py freshquant/tests/test_order_management_reconcile.py freshquant/tests/test_order_management_stoploss.py freshquant/tests/test_order_management_manual_projection_writes.py -q`

Expected: PASS

**Step 2: Run broader suite**

Run: `pytest freshquant/tests -q`

Expected: PASS，或仅存在与本 RFC 无关的既有失败。

**Step 3: Update governance docs**

- `docs/migration/progress.md`：按 `Approved -> Implementing -> Done` 更新 `0007`
- `docs/migration/breaking-changes.md`：记录独立数据库、`stock_fills` 兼容投影化、`buy_lot_id` 止损绑定等变更
- 若出现语义差异残留，明确记录为阻塞项，不要带病合并

**Step 4: Commit**

```bash
git add docs/migration/progress.md docs/migration/breaking-changes.md
git commit -m "docs: finalize order management migration records"
```
