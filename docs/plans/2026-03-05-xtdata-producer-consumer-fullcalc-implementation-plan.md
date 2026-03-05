# XTData Producer/Consumer + fullcalc Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在本仓库用 XTData 的事件驱动 Producer/Consumer 替代分钟轮询链路，Consumer 统一用 `fullcalc` 产出 `1m/5m/15m/30m` 缠论结构推送给前端，并在 Mode B 输出 CLX12 + 钉钉；Guardian 在 Mode A 改为订阅结构推送触发信号。

**Architecture:** Producer 订阅 XTData tick → 合成 1m bar close →（仅当日）resample 5/15/30 → Redis List 投递 `BAR_CLOSE`。Consumer BLPOP 消费 `BAR_CLOSE` → 落库 `DBfreshquant.*_realtime` → 维护每 code+period 最多 20000 根窗口 → 多进程运行 `fullcalc` → 写 Redis cache + Pub/Sub `CHANNEL:BAR_UPDATE`。Guardian 侧订阅 `CHANNEL:BAR_UPDATE`（只看 1m）计算信号；Mode B 在 Consumer 侧只对 15/30 生成 CLX12 信号并发钉钉。

**Tech Stack:** Python 3.12、MongoDB、Redis、QUANTAXIS 分钟库、XTQuant/MiniQMT（xtquant/xtdata）、xmake + pybind11（构建 `fullcalc.pyd`）、`ProcessPoolExecutor`（fullcalc 并行）。

---

### Task 1: 定义周期/Key/事件协议（最小可迁移）

**Files:**
- Create: `freshquant/util/period.py`
- Create: `freshquant/market_data/xtdata/constants.py`
- Create: `freshquant/market_data/xtdata/schema.py`
- Test: `freshquant/tests/test_period_utils.py`

**Step 1: 写 failing tests（周期转换/Key 规则）**

```python
from freshquant.util.period import to_backend_period, to_frontend_period, get_redis_cache_key

def test_period_convert_roundtrip():
    assert to_backend_period("1m") == "1min"
    assert to_frontend_period("1min") == "1m"
    assert to_backend_period("15m") == "15min"
    assert to_frontend_period("30min") == "30m"

def test_cache_key_format():
    assert get_redis_cache_key("sz000001", "5min") == "CACHE:KLINE:sz000001:5min"
```

**Step 2: 运行测试确认失败**

Run: `pytest freshquant/tests/test_period_utils.py -q`
Expected: FAIL（模块/函数不存在）。

**Step 3: 最小实现 `period.py/constants.py/schema.py`**

实现要点：
- backend period 统一：`1min/5min/15min/30min`
- frontend period 统一：`1m/5m/15m/30m`
- Pub/Sub channel：`CHANNEL:BAR_UPDATE`
- Redis cache key：`CACHE:KLINE:<code>:<period_backend>`
- Queue key：`QUEUE:BAR_CLOSE:<shard>`（shard 基于 code hash，shards=4 默认）
- `schema.py` 提供 `BarCloseEvent`（dict 结构校验 + normalize code/period）

**Step 4: 运行测试确认通过**

Run: `pytest freshquant/tests/test_period_utils.py -q`
Expected: PASS。

---

### Task 2: 迁移 BarEventListener（Guardian 事件驱动基础设施）

**Files:**
- Create: `freshquant/signal/astock/job/bar_event_listener.py`
- Test: `freshquant/tests/test_bar_event_listener_filtering.py`

**Step 1: 写 failing test（过滤逻辑为纯函数）**

建议将“payload → (code, period, data)”解析与过滤提取为纯函数，单测不依赖 Redis。

**Step 2: 实现 `BarEventListener`（最小可用版）**

要求：
- Redis `pubsub().subscribe(PUBSUB_CHANNEL)` 监听
- 支持 `filter_codes/filter_periods`（都以 backend period + prefixed code 归一）
- 回调异常不崩溃；队列满丢弃并计数

**Step 3: 运行测试**

Run: `pytest freshquant/tests/test_bar_event_listener_filtering.py -q`
Expected: PASS。

---

### Task 3: fullcalc 源码迁移 + xmake 构建（Python 3.12）

**Files:**
- Copy from old repo:
  - `D:\fqpack\freshquant\morningglory\fqcopilot\fullcalc/binding.cpp`
  - `D:\fqpack\freshquant\morningglory\fqcopilot\fullcalc/fullcalc.cpp`
  - `D:\fqpack\freshquant\morningglory\fqcopilot\fullcalc/fullcalc.h`
  - `D:\fqpack\freshquant\morningglory\fqcopilot\fullcalc/types.h`
- Create: `freshquant/analysis/fullcalc_wrapper.py`
- Modify: `morningglory/fqcopilot/xmake.lua`
- Test: `freshquant/tests/test_fullcalc_smoke.py`

**Step 1: 写 smoke test（可跳过：模块未构建时 xfail/skip）**

```python
import pytest
import pandas as pd

from freshquant.analysis.fullcalc_wrapper import run_fullcalc

def test_fullcalc_smoke():
    df = pd.DataFrame({
        "open": [1]*20,
        "high": [1.1]*20,
        "low": [0.9]*20,
        "close": [1]*20,
        "volume": [1]*20,
    })
    r = run_fullcalc(df, model_ids=[])
    assert r["ok"] is True
    assert "bi" in r and len(r["bi"]) == 20
    assert r.get("signals") == []
```

**Step 2: 调整 fullcalc 行为（结构-only 可控）**

在 `fullcalc.cpp` 中：
- `model_ids` 为空时：不跑 CLX（`signals=[]`）
- `model_ids` 非空时：过滤只保留 `10001..10012`，其余忽略（避免 `[-1]` 这种不确定语义）

**Step 3: xmake 增加 `target("fullcalc_py")`**

要求：
- 输出到 `morningglory/fqcopilot/python/fullcalc.pyd`
- 自动探测 Python 3.12 include/libdir（允许用 env 覆盖）
- 使用 `pybind11`（优先 xmake 包：`add_requires("pybind11")`）
- 复用 `morningglory/fqchan04/cpp/chanlun`，并从 `fqcopilot/cpp` 中剔除本地 `chanlun/*.cpp`

**Step 4: 构建并跑 smoke test**

Run:
- `cd morningglory/fqcopilot; xmake f -m release; xmake build fullcalc_py -v`
- `pytest freshquant/tests/test_fullcalc_smoke.py -q`

Expected:
- `morningglory/fqcopilot/python/fullcalc.pyd` 生成
- smoke test PASS（若本机缺编译工具链则记录原因）。

---

### Task 4: Consumer（BAR_CLOSE → 落库 → fullcalc → cache + Pub/Sub）

**Files:**
- Create: `freshquant/market_data/xtdata/strategy_consumer.py`
- Create: `freshquant/market_data/xtdata/history_loader.py`
- Create: `freshquant/market_data/xtdata/realtime_store.py`
- Modify: `freshquant/preset/params.py`
- Test: `freshquant/tests/test_consumer_coalesce.py`

**Step 1: 写 failing test（coalesce：积压只算最新）**

目标：同一个 `(code, period)` 连续收到 3 根 bar close，只提交 1 个 fullcalc（只算最新）。

**Step 2: 实现 realtime 落库（stock_realtime/index_realtime）**

要求：
- 写入集合：
  - STOCK → `DBfreshquant.stock_realtime`
  - ETF → `DBfreshquant.index_realtime`
- upsert key：`(datetime, code, frequence)`
- 支持批量 `bulk_write(ordered=False)`

**Step 3: 实现 HistoryLoader（prewarm + 窗口构建）**

要求：
- 每个周期最大 20000 根（不足按最多）
- 历史：从 QUANTAXIS 分钟库读取（stock min/day，etf min/day）
- 当日实时：从 realtime 集合补齐（用于重启后继续）
- ETF：使用 `freshquant.data.etf_adj.apply_qfq_to_bars`
- STOCK：确保 qfq 一致（可用 QUANTAXIS `stock_adj` 因子；策略写在实现里并补单测/日志）

**Step 4: 实现 fullcalc 多进程执行**

要求：
- `ProcessPoolExecutor` + 超时（单任务超时可丢弃并记录）
- 全局限流（例如 `max_inflight = cpu_count*2`）
- 每 `(code, period)` 只保留“最后一根 bar”提交

**Step 5: 实现 cache + Pub/Sub 推送结构**

要求：
- cache key：`CACHE:KLINE:<code>:<period_backend>` 值为完整 JSON（chanlun_data）
- channel：`CHANNEL:BAR_UPDATE` 发布同样 payload
- chanlun_data 结构尽量对齐 `get_data_v2` 输出字段（`date/open/high/low/close/bidata/duandata/zsdata...`）

**Step 6: params 增加并默认写入**

在 `freshquant/preset/params.py`：
- `monitor.xtdata.mode` 默认 `"clx_15_30"`
- `monitor.xtdata.max_symbols` 默认 `50`
- `monitor.xtdata.prewarm.max_bars` 默认 `20000`

**Step 7: 本地验证（不连 xtdata）**

Run:
- `pytest freshquant/tests/test_consumer_coalesce.py -q`

Expected: PASS（纯逻辑单测）。

---

### Task 5: Producer（XTData tick → 1m bar close → resample 5/15/30 → Redis List）

**Files:**
- Create: `freshquant/market_data/xtdata/market_producer.py`
- Create: `freshquant/market_data/xtdata/bar_generator.py`
- Create: `freshquant/market_data/xtdata/pool_provider.py`
- Test: `freshquant/tests/test_bar_resampler.py`

**Step 1: 写 failing test（resample 对齐）**

输入 1m bar（09:31..09:35）应产出 5min bar close（09:35）。

**Step 2: 实现 `OneMinuteBarGenerator`（tick → 1m bar close）**

要求：
- tick keys：`time(ms) / lastPrice / volume / amount`
- bar end timestamp（秒）对齐到 minute end（right label）
- 不中断：回调线程只做轻量 coalesce，重活放后台线程
- tick 不下推（本阶段不实现 tick event push）

**Step 3: 实现 `MultiPeriodResamplerFrom1m`（仅当日）**

要求：
- 只生成 `5min/15min/30min` 的 bar close event（跨日不做）

**Step 4: 实现 pool provider（按 mode 取标的 + 动态增量订阅）**

要求：
- Mode A：`持仓 + must_pool`
- Mode B：`stock_pools`
- 每 `POOL_CHECK_INTERVAL` 刷新一次，发现新增立即订阅（无需重启）
- 总标的数 <= 50（超过则按稳定排序截断并告警）

**Step 5: 实现 producer main**

要求：
- xtquant 不存在时给出可读错误（引导安装/启动 MiniQMT）
- 连接 xtdata（支持端口 env）
- `subscribe_whole_quote(codes, callback=...)`
- 将 `BAR_CLOSE` JSON 投递到 redis list（按 shard）

**Step 6: 跑单测**

Run:
- `pytest freshquant/tests/test_bar_resampler.py -q`
Expected: PASS。

---

### Task 6: Guardian（Mode A）从轮询改为订阅结构推送

**Files:**
- Modify: `freshquant/signal/astock/job/monitor_stock_zh_a_min.py`
- Create: `freshquant/signal/astock/job/monitor_helpers_event.py`（按需迁移）
- Test: `freshquant/tests/test_guardian_signal_from_push.py`

**Step 1: 加入 `--mode event`**

要求：
- event 模式订阅 `CHANNEL:BAR_UPDATE`
- 仅处理 period=`1min`（或前端 `1m` 归一后）

**Step 2: 迁移最小信号计算**

从旧仓库按需迁移：
- `calculate_signals_from_push_data`（及其最小依赖）
- 只保留 Guardian 当前需要的信号类型：
  - `buy_zs_huila/sell_zs_huila`
  - `buy_v_reverse/sell_v_reverse`
  - `macd_bullish_divergence/macd_bearish_divergence`

**Step 3: 保存信号**

复用 `freshquant/signal/a_stock_common.py:save_a_stock_signal`，确保 StrategyGuardian 仍能收到。

---

### Task 7: CLX12（Mode B）筛选 + 落库 + 钉钉

**Files:**
- Modify: `freshquant/market_data/xtdata/strategy_consumer.py`
- Modify: `freshquant/message/dingtalk.py`（如需支持聚合/去重）
- Test: `freshquant/tests/test_clx_dedupe.py`

**Step 1: 只对 15/30 产出 CLX**

要求：
- Mode B 下：`period in {"15min","30min"}` 才跑 model_ids=10001..10012
- 其余周期 model_ids=[]（结构-only）

**Step 2: 去重（允许错过积压期间信号）**

建议：
- Redis `SETNX` 锁：`FQ:LOCK:CLX:<YYYYMMDDHHMMSS>:<code>:<period>:<model>`
- 锁 TTL 3600s

**Step 3: 落库**

集合建议（沿用旧逻辑命名即可）：`DBfreshquant.realtime_screen_multi_period`

**Step 4: 钉钉聚合发送**

最低可行：
- 按分钟/周期聚合成一条 markdown
- 使用现有 `market_data_alert` 或 `send_private_message`

---

### Task 8: 运行/部署说明 + 停用 TDX realtime

**Files:**
- Modify: `docs/migration/breaking-changes.md`
- Modify: `docs/migration/progress.md`（状态流转）
- Modify: `docs/agent/项目目标与代码现状调研.md`（若需补入口说明）
- (Optional) Modify: `docker/compose.parallel.yaml`

**Step 1: 记录破坏性变更**

- 轮询分钟监控改为事件订阅
- 不再依赖/启动 TDX realtime 采集链路（由 XTData 写入 `*_realtime`）

**Step 2: 写运行方式**

给出最小命令（示例）：
- Producer：`python -m freshquant.market_data.xtdata.market_producer`
- Consumer：`python -m freshquant.market_data.xtdata.strategy_consumer`
- Guardian（Mode A）：`python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event`

---

# 执行建议

Plan complete and saved to `docs/plans/2026-03-05-xtdata-producer-consumer-fullcalc-implementation-plan.md`. Two execution options:

1. Subagent-Driven (this session) — dispatch per task, review between tasks
2. Parallel Session (separate) — new session uses superpowers:executing-plans

Which approach?

