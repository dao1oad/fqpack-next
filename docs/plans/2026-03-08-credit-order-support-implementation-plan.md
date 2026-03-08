# Credit Account Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在目标架构下为 `CREDIT` 账户补齐信用订单决策、融资标的同步、自动报价和正确回报归因。

**Architecture:** 继续以 `order_management` 作为统一订单受理边界，在订单域内新增信用决策与融资标的同步能力；`broker/puppet` 只保留 XT 执行适配；`ingest` 统一把信用订单类型归并为买卖方向写回主账本。实现顺序先文档后代码，先测试后实现。

**Tech Stack:** Python, pytest, MongoDB, Redis, XT/MiniQMT, supervisor, RFC docs

---

### Task 1: Draft RFC and Migration Records

**Files:**
- Create: `docs/rfcs/NNNN-credit-account-order-support.md`
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`
- Reference: `docs/rfcs/0000-template.md`
- Reference: `docs/plans/2026-03-08-credit-order-support-design.md`

**Step 1: Draft the RFC from the approved design**

Write the RFC with these required points:

```markdown
- Goals: CREDIT buy/sell support in order_management
- Non-Goals: no short selling / no special credit business
- In Scope: financing subject sync, buy/sell credit decision, auto quote, ingest mapping
- Out of Scope: position_management rewrite, frontend, xt_credit_details
- Runtime rules:
  - finance buy decided from stored subject list
  - sell repay when m_dAvailable > 10000 and m_dFinDebt > 0
  - auto quote uses SH/SZ convert 5 cancel in continuous auction
  - no freshness gate for financing subject list
```

**Step 2: Pick the next RFC number**

Run: `Get-ChildItem docs/rfcs | Sort-Object Name`
Expected: Identify the next unused `NNNN` before creating the RFC file.

**Step 3: Update migration progress**

Add the RFC entry to `docs/migration/progress.md` with:

```markdown
- RFC number
- status = Draft or Review
- short scope summary
- next step = implementation after approval
```

**Step 4: Register the breaking-change intent**

Update `docs/migration/breaking-changes.md` with:

```markdown
- CREDIT account orders now use order-domain credit semantics
- broker no longer owns credit business decision logic
- host worker required for financing subject sync
```

**Step 5: Verify document formatting**

Run: `git diff --check`
Expected: No whitespace or conflict-marker errors.

**Step 6: Commit**

```bash
git add docs/rfcs/NNNN-credit-account-order-support.md docs/migration/progress.md docs/migration/breaking-changes.md
git commit -m "docs: draft RFC for credit account order support"
```

### Task 2: Add Financing Subject Storage and Host Worker

**Files:**
- Create: `freshquant/order_management/credit_subjects/__init__.py`
- Create: `freshquant/order_management/credit_subjects/models.py`
- Create: `freshquant/order_management/credit_subjects/repository.py`
- Create: `freshquant/order_management/credit_subjects/service.py`
- Create: `freshquant/order_management/credit_subjects/worker.py`
- Modify: `freshquant/order_management/repository.py`
- Modify: `freshquant/preset/index.py`
- Test: `freshquant/tests/test_order_management_credit_subjects_worker.py`

**Step 1: Write the failing worker test**

```python
def test_worker_syncs_credit_subjects_into_order_management_collection():
    client = FakeXtClient(subjects=[FakeSubject("600000.SH", fin_status=48)])
    repo = InMemoryCreditSubjectRepository()
    result = sync_credit_subjects_once(client=client, repository=repo)
    assert result["count"] == 1
    assert repo.find_one("600000.SH")["fin_status"] == 48
```

**Step 2: Run the new test to confirm failure**

Run: `pytest freshquant/tests/test_order_management_credit_subjects_worker.py -q`
Expected: FAIL because the worker/service does not exist yet.

**Step 3: Add the minimal repository and worker implementation**

Implement:

```python
def sync_credit_subjects_once(client, repository):
    subjects = client.query_credit_subjects()
    for subject in subjects:
        repository.upsert_subject({
            "instrument_id": subject.instrument_id,
            "fin_status": subject.fin_status,
            "slo_status": subject.slo_status,
            "updated_at": now_iso(),
        })
    return {"count": len(subjects)}
```

**Step 4: Add host-worker CLI entry**

Support:

```python
python -m freshquant.order_management.credit_subjects.worker --once
python -m freshquant.order_management.credit_subjects.worker
```

**Step 5: Run the worker test again**

Run: `pytest freshquant/tests/test_order_management_credit_subjects_worker.py -q`
Expected: PASS

**Step 6: Commit**

```bash
git add freshquant/order_management/credit_subjects freshquant/order_management/repository.py freshquant/preset/index.py freshquant/tests/test_order_management_credit_subjects_worker.py
git commit -m "feat: add credit subject sync worker"
```

### Task 3: Add Credit Buy Decision to Order Submit Service

**Files:**
- Create: `freshquant/order_management/submit/credit_order_resolver.py`
- Modify: `freshquant/order_management/submit/service.py`
- Modify: `freshquant/order_management/tracking/service.py`
- Test: `freshquant/tests/test_order_management_submit_service.py`
- Test: `freshquant/tests/test_order_management_credit_order_resolver.py`

**Step 1: Write the failing resolver tests**

```python
def test_credit_buy_uses_finance_buy_when_symbol_is_margin_target():
    result = resolve_submit_credit_order(
        account_type="CREDIT",
        action="buy",
        symbol="600000",
        credit_subject_lookup=lambda symbol: {"fin_status": 48},
    )
    assert result["credit_trade_mode_resolved"] == "finance_buy"
    assert result["broker_order_type"] == 27
```

```python
def test_credit_buy_uses_collateral_buy_when_symbol_not_margin_target():
    result = resolve_submit_credit_order(
        account_type="CREDIT",
        action="buy",
        symbol="000001",
        credit_subject_lookup=lambda symbol: None,
    )
    assert result["credit_trade_mode_resolved"] == "collateral_buy"
    assert result["broker_order_type"] == 23
```

**Step 2: Run the resolver tests to confirm failure**

Run: `pytest freshquant/tests/test_order_management_credit_order_resolver.py -q`
Expected: FAIL because the resolver is missing.

**Step 3: Implement the minimal submit-time resolver**

```python
if account_type != "CREDIT":
    return {"broker_order_type": None}
if action == "buy" and requested_mode in (None, "auto"):
    subject = credit_subject_lookup(symbol)
    if subject and subject.get("fin_status") == 48:
        return {"credit_trade_mode_resolved": "finance_buy", "broker_order_type": 27}
    return {"credit_trade_mode_resolved": "collateral_buy", "broker_order_type": 23}
```

**Step 4: Thread the resolved fields through submit/tracking**

Persist these fields into request/order docs:

```python
"account_type"
"credit_trade_mode"
"price_mode"
"credit_trade_mode_requested"
"credit_trade_mode_resolved"
"broker_order_type"
```

**Step 5: Extend existing submit-service tests**

Update the queue/assertion tests so they check resolved credit metadata on queued orders.

**Step 6: Run related tests**

Run: `pytest freshquant/tests/test_order_management_submit_service.py freshquant/tests/test_order_management_credit_order_resolver.py -q`
Expected: PASS

**Step 7: Commit**

```bash
git add freshquant/order_management/submit/credit_order_resolver.py freshquant/order_management/submit/service.py freshquant/order_management/tracking/service.py freshquant/tests/test_order_management_submit_service.py freshquant/tests/test_order_management_credit_order_resolver.py
git commit -m "feat: add submit-time credit buy resolution"
```

### Task 4: Add Runtime Sell-Repay and Auto Quote Resolution

**Files:**
- Modify: `freshquant/order_management/submit/execution_bridge.py`
- Modify: `morningglory/fqxtrade/fqxtrade/xtquant/broker.py`
- Modify: `morningglory/fqxtrade/fqxtrade/xtquant/puppet.py`
- Test: `freshquant/tests/test_order_management_execution_bridge.py`
- Create: `freshquant/tests/test_order_management_credit_runtime_resolution.py`

**Step 1: Write the failing runtime-resolution tests**

```python
def test_credit_sell_uses_sell_repay_when_available_gt_10000_and_fin_debt_gt_0():
    result = resolve_runtime_credit_execution(
        account_type="CREDIT",
        action="sell",
        credit_detail={"m_dAvailable": 10001, "m_dFinDebt": 1},
    )
    assert result["broker_order_type"] == 31
```

```python
def test_auto_quote_uses_sh_convert_5_cancel_during_continuous_auction():
    result = resolve_price_mode(
        symbol="600000.SH",
        action="buy",
        price_mode="auto",
        input_price=10.0,
        continuous_auction=True,
    )
    assert result["broker_price_type"] == 42
    assert result["price_to_use"] == 10.08
```

**Step 2: Run the new tests to confirm failure**

Run: `pytest freshquant/tests/test_order_management_execution_bridge.py freshquant/tests/test_order_management_credit_runtime_resolution.py -q`
Expected: FAIL because runtime resolution does not exist.

**Step 3: Implement runtime sell decision**

```python
if account_type == "CREDIT" and action == "sell":
    if available_amount > 10000 and fin_debt > 0:
        broker_order_type = 31
    else:
        broker_order_type = 24
```

**Step 4: Implement auto quote resolution**

```python
if continuous_auction and price_mode == "auto":
    if symbol.endswith(".SH"):
        price_type = 42
    elif symbol.endswith(".SZ"):
        price_type = 47
    price_to_use = input_price * (1.008 if action == "buy" else 0.992)
else:
    price_type = 11
    price_to_use = input_price
```

**Step 5: Change broker/puppet to consume resolved values**

Remove buy/sell business branching from `puppet` and pass through the already-resolved order type and price type.

**Step 6: Run tests again**

Run: `pytest freshquant/tests/test_order_management_execution_bridge.py freshquant/tests/test_order_management_credit_runtime_resolution.py -q`
Expected: PASS

**Step 7: Commit**

```bash
git add freshquant/order_management/submit/execution_bridge.py morningglory/fqxtrade/fqxtrade/xtquant/broker.py morningglory/fqxtrade/fqxtrade/xtquant/puppet.py freshquant/tests/test_order_management_execution_bridge.py freshquant/tests/test_order_management_credit_runtime_resolution.py
git commit -m "feat: add runtime sell repay and auto quote resolution"
```

### Task 5: Fix XT Ingest and Compatibility Projection for Credit Order Types

**Files:**
- Modify: `freshquant/order_management/ingest/xt_reports.py`
- Modify: `morningglory/fqxtrade/fqxtrade/xtquant/puppet.py`
- Test: `freshquant/tests/test_order_management_xt_ingest.py`

**Step 1: Write the failing ingest tests**

```python
def test_normalize_xt_trade_report_treats_credit_fin_buy_as_buy():
    normalized = normalize_xt_trade_report({
        "order_id": "O-200",
        "traded_id": "T-200",
        "stock_code": "600000.SH",
        "order_type": 27,
        "traded_volume": 100,
        "traded_price": 10.0,
        "traded_time": 1710000000,
    })
    assert normalized["side"] == "buy"
```

```python
def test_normalize_xt_trade_report_treats_sell_repay_as_sell():
    normalized = normalize_xt_trade_report({
        "order_id": "O-201",
        "traded_id": "T-201",
        "stock_code": "600000.SH",
        "order_type": 31,
        "traded_volume": 100,
        "traded_price": 10.0,
        "traded_time": 1710000000,
    })
    assert normalized["side"] == "sell"
```

**Step 2: Run the ingest tests to confirm failure**

Run: `pytest freshquant/tests/test_order_management_xt_ingest.py -q`
Expected: FAIL because only order type `23` is treated as buy.

**Step 3: Implement minimal side mapping fix**

```python
BUY_ORDER_TYPES = {23, 27, "23", "27", "buy", "BUY"}
SELL_ORDER_TYPES = {24, 31, "24", "31", "sell", "SELL"}
```

If an order can be resolved by `internal_order_id`, prefer the order-domain stored `broker_order_type` over raw callback fallback.

**Step 4: Align compatibility projection**

Update `puppet.saveTrades()` and `puppet.saveOrders()` so credit buy/sell types are grouped into the same buy/sell buckets as ordinary stock orders.

**Step 5: Run tests again**

Run: `pytest freshquant/tests/test_order_management_xt_ingest.py -q`
Expected: PASS

**Step 6: Commit**

```bash
git add freshquant/order_management/ingest/xt_reports.py morningglory/fqxtrade/fqxtrade/xtquant/puppet.py freshquant/tests/test_order_management_xt_ingest.py
git commit -m "fix: map credit order types in xt ingest"
```

### Task 6: Update Host Deployment Docs and Verify End-to-End

**Files:**
- Modify: `docs/实盘对接说明.md`
- Modify: `docs/agent/Docker并行部署指南.md`
- Modify: `docs/配置文件模板/supervisord.fqnext.example.conf`
- Modify: `docs/migration/progress.md`

**Step 1: Document the new host worker**

Add the new supervisor program and host requirement:

```text
python -m freshquant.order_management.credit_subjects.worker
```

### Step 2: Document runtime rules

Document:

```text
- financing subject sync runs on Windows host
- buy decision reads stored financing subject list
- sell repay threshold = available > 10000 and fin_debt > 0
- no freshness gate on financing subject list
```

**Step 3: Run focused verification**

Run:

```bash
pytest freshquant/tests/test_order_management_submit_service.py \
       freshquant/tests/test_order_management_execution_bridge.py \
       freshquant/tests/test_order_management_xt_ingest.py -q
```

Expected: PASS

**Step 4: Run whitespace verification**

Run: `git diff --check`
Expected: PASS

**Step 5: Commit**

```bash
git add docs/实盘对接说明.md docs/agent/Docker并行部署指南.md docs/配置文件模板/supervisord.fqnext.example.conf docs/migration/progress.md
git commit -m "docs: add host runtime instructions for credit order support"
```
