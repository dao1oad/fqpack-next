# XTData 订阅池收敛、前复权语义统一与盘前参考数据刷新 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 收敛 XTData Producer 订阅池、统一股票/ETF qfq 语义为 raw+merge+single-qfq，并补上宿主机盘前 intraday override refresh。

**Architecture:** Producer 只订阅 `monitor_codes`；Consumer 与查询链路统一将历史/realtime 都视为 raw/bfq，先拼接窗口，再应用本地盘后 `adj` 与当日 intraday override。宿主机新增 `adj_refresh_worker` 负责盘前生成 `stock_adj_intraday/etf_adj_intraday`，并与现有 `credit_subjects.worker` 在 supervisor 中归到同一参考数据组。

**Tech Stack:** Python 3.12、MongoDB、Redis、XTData/xtquant、QUANTAXIS、pytest、supervisor。

---

### Task 1: 锁定 Producer 订阅池行为

**Files:**
- Modify: `freshquant/market_data/xtdata/market_producer.py`
- Test: `freshquant/tests/test_xtdata_market_producer_subscription_pool.py`

**Step 1: Write the failing test**

覆盖两件事：
- Producer 只调用 `load_monitor_codes()`
- 即使 `load_active_tpsl_codes()` 返回额外标的，也不会进入最终订阅集

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_xtdata_market_producer_subscription_pool.py -q`
Expected: FAIL，当前实现仍会并入 TPSL 标的。

**Step 3: Write minimal implementation**

在 `market_producer.py` 删除 `load_active_tpsl_codes()` 的并集逻辑，只保留 `load_monitor_codes(...)`。

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_xtdata_market_producer_subscription_pool.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/market_data/xtdata/market_producer.py freshquant/tests/test_xtdata_market_producer_subscription_pool.py
git commit -m "test: lock xtdata producer subscription pool"
```

---

### Task 2: 先写 qfq 统一语义的失败测试

**Files:**
- Modify: `freshquant/tests/test_xtdata_strategy_consumer_history.py`
- Create: `freshquant/tests/test_intraday_adj_override.py`

**Step 1: Write the failing tests**

至少覆盖：
- 股票 realtime 写库改为 raw 后，不再依赖“已 qfq realtime”
- 股票与 ETF 都通过“历史 raw + realtime raw + single qfq”得到连续窗口
- intraday override 存在时，除权日当天窗口连续
- intraday override 缺失时，回退 base adj，不写混合语义数据

**Step 2: Run tests to verify they fail**

Run:
- `py -3.12 -m pytest freshquant/tests/test_xtdata_strategy_consumer_history.py -q`
- `py -3.12 -m pytest freshquant/tests/test_intraday_adj_override.py -q`

Expected: FAIL，当前股票路径仍是假设 realtime 已 qfq。

**Step 3: Commit**

```bash
git add freshquant/tests/test_xtdata_strategy_consumer_history.py freshquant/tests/test_intraday_adj_override.py
git commit -m "test: define unified qfq semantics"
```

---

### Task 3: 统一 intraday 窗口构建与 realtime raw 写库

**Files:**
- Modify: `freshquant/market_data/xtdata/strategy_consumer.py`
- Modify: `freshquant/data/stock.py`
- Modify: `freshquant/quote/etf.py`
- Create: `freshquant/data/adj_intraday.py`

**Step 1: Implement raw-only realtime writes**

在 `strategy_consumer.py`：
- `handle_bar_close()` 股票/ETF 都写 raw/bfq
- `_backfill_from_xtdata()` 也统一写 raw/bfq
- 删除股票写库时 `_apply_qfq_to_bar()` 的调用

**Step 2: Implement unified window loader**

在 `strategy_consumer.py`：
- 历史读取改为 raw/bfq
- realtime 读取按 raw/bfq 处理
- merge / dedupe / sort 之后，统一调用一次 qfq

在 `freshquant/data/stock.py`：
- 不再直接对历史 `to_qfq()` 后再拼 realtime
- 改为 raw history + raw realtime + 统一 qfq helper

在 `freshquant/quote/etf.py`：
- 对齐到同一个 helper，避免股票/ETF 继续分裂实现

**Step 3: Implement intraday override helper**

在 `freshquant/data/adj_intraday.py`：
- 读取 `stock_adj_intraday/etf_adj_intraday`
- 给 base adj 应用 `anchor_scale`
- 对当前交易日返回 `adj=1`

**Step 4: Run tests to verify they pass**

Run:
- `py -3.12 -m pytest freshquant/tests/test_xtdata_strategy_consumer_history.py -q`
- `py -3.12 -m pytest freshquant/tests/test_intraday_adj_override.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/market_data/xtdata/strategy_consumer.py freshquant/data/stock.py freshquant/quote/etf.py freshquant/data/adj_intraday.py freshquant/tests/test_xtdata_strategy_consumer_history.py freshquant/tests/test_intraday_adj_override.py
git commit -m "feat: unify qfq semantics around raw merged windows"
```

---

### Task 4: 实现宿主机盘前 adj refresh worker

**Files:**
- Create: `freshquant/market_data/xtdata/adj_refresh_worker.py`
- Create: `freshquant/market_data/xtdata/adj_refresh_service.py`
- Test: `freshquant/tests/test_adj_refresh_service.py`

**Step 1: Write the failing test**

覆盖：
- 根据 XTData `front/raw` 的前一锚点日价格计算 `anchor_scale`
- 写入 `stock_adj_intraday/etf_adj_intraday`
- 调度默认 `09:20 Asia/Shanghai`

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_adj_refresh_service.py -q`
Expected: FAIL，worker/service 尚不存在。

**Step 3: Write minimal implementation**

`adj_refresh_service.py`：
- 选择 base anchor date
- 读取 XTData raw/front 对照
- 计算 `anchor_scale`
- upsert `*_adj_intraday`

`adj_refresh_worker.py`：
- `--once`
- 常驻默认 `09:20`
- 启动即跑一次

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_adj_refresh_service.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/market_data/xtdata/adj_refresh_worker.py freshquant/market_data/xtdata/adj_refresh_service.py freshquant/tests/test_adj_refresh_service.py
git commit -m "feat: add host-side intraday adj refresh worker"
```

---

### Task 5: 运维管理面与文档收尾

**Files:**
- Modify: `docs/配置文件模板/supervisord.fqnext.example.conf`
- Modify: `docs/实盘对接说明.md`
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`

**Step 1: Add supervisor entries**

新增：
- `fqnext_xtdata_adj_refresh_worker`
- `group:fqnext_reference_data`

**Step 2: Update docs**

明确：
- `credit_subjects.worker` 与 `adj_refresh_worker` 同属 reference-data 组
- 切换到 raw-only realtime 需要清理/重建当日 realtime 数据

**Step 3: Update migration records**

- `progress.md`：RFC 0024 状态更新
- `breaking-changes.md`：记录 realtime 语义与订阅池语义变更

**Step 4: Run focused verification**

Run:
- `py -3.12 -m pytest freshquant/tests/test_xtdata_market_producer_subscription_pool.py freshquant/tests/test_xtdata_strategy_consumer_history.py freshquant/tests/test_intraday_adj_override.py freshquant/tests/test_adj_refresh_service.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add docs/配置文件模板/supervisord.fqnext.example.conf docs/实盘对接说明.md docs/migration/progress.md docs/migration/breaking-changes.md
git commit -m "docs: document qfq refresh and reference-data operations"
```
