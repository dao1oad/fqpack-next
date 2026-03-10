# XTData Supervisor 启动修复 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 XTData producer/consumer 的模块入口回归、屏蔽 adj refresh 的代理环境陷阱，并把宿主机 supervisor 切回项目 `.venv`。

**Architecture:** 先用失败测试锁定真实 `python -m ...` 启动路径和代理环境语义，再做最小代码修复，最后更新宿主机 `supervisord` 配置并做运行验证。配置修复只覆盖本次涉及的 3 个进程与共享 Python 口径，不扩大到其它运行时治理。

**Tech Stack:** Python 3.12、pytest、runpy/subprocess 模块入口回归测试、akshare、Go-Supervisor、Windows 宿主机 `.venv`

---

### Task 1: 锁定 XTData 模块入口回归

**Files:**
- Modify: `freshquant/tests/test_xtdata_runtime_observability.py`
- Modify: `freshquant/market_data/xtdata/market_producer.py`
- Modify: `freshquant/market_data/xtdata/strategy_consumer.py`

**Step 1: 写失败测试**

- 为 `market_producer` 增加一个真实模块入口测试，执行 `runpy.run_module(..., run_name="__main__")`，并用 stub `xtquant.xtdata.connect()` 抛出 sentinel 异常。
- 期望失败前的现象是 `NameError: _emit_runtime`；修复后应变成 sentinel 异常。
- 为 `strategy_consumer` 增加一个真实模块入口测试，stub `ProcessPoolExecutor` 抛 sentinel 异常，避免进入长期运行循环。
- 期望失败前的现象是 `NameError: _get_runtime_logger`；修复后应变成 sentinel 异常。

**Step 2: 跑测试确认失败**

Run: `.\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_xtdata_runtime_observability.py -q`

**Step 3: 写最小实现**

- 调整 `market_producer.py` 的 helper 定义顺序，确保 `_emit_runtime()` / `_get_runtime_logger()` 在 `main()` 被调用前已绑定。
- 调整 `strategy_consumer.py` 的 `_get_runtime_logger()` 定义顺序，确保模块入口执行时已可用。

**Step 4: 跑测试确认通过**

Run: `.\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_xtdata_runtime_observability.py -q`

### Task 2: 锁定交易日拉取的代理屏蔽语义

**Files:**
- Add: `freshquant/tests/test_trading_dt_proxy.py`
- Modify: `freshquant/trading/dt.py`

**Step 1: 写失败测试**

- 构造带 `ALL_PROXY` / `all_proxy` / `HTTP_PROXY` / `HTTPS_PROXY` 的环境。
- monkeypatch `ak.tool_trade_date_hist_sina()`，在函数体内记录这些环境变量的可见性。
- 断言调用期间这些代理变量被清空，调用后恢复原值。

**Step 2: 跑测试确认失败**

Run: `.\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_trading_dt_proxy.py -q`

**Step 3: 写最小实现**

- 在 `freshquant.trading.dt` 中增加最小范围的代理环境屏蔽 helper。
- 仅对交易日历拉取路径生效，不扩大到其它 HTTP 调用。

**Step 4: 跑测试确认通过**

Run: `.\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_trading_dt_proxy.py -q`

### Task 3: 修复宿主机 supervisor 配置并验证

**Files:**
- Modify: `D:\fqpack\config\supervisord.fqnext.conf`

**Step 1: 更新配置**

- 将 `program-default.environment` 中的 `PATH` 切到当前验证 worktree 的 `.venv` 与 `Scripts`。
- 将 `directory`、`PYTHONPATH` 与 3 个相关 `command=` 统一切到当前验证 worktree。

**Step 2: 静态检查**

- 复核配置内不再出现 `D:/fqpack/miniconda3/envs/fqkit/python.exe`。

**Step 3: 重载并验证**

Run:
- `Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:10011/supervisor/reload' -Method Post`
- `(Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:10011/program/list').Content`

**Step 4: 验收**

- `fqnext_realtime_xtdata_producer`
- `fqnext_realtime_xtdata_consumer`
- `fqnext_xtdata_adj_refresh_worker`

以上 3 个进程状态稳定为 `Running`，不再反复 `Starting/Fatal`。

### Task 4: 全量相邻验证

**Files:**
- Modify: `freshquant/tests/test_xtdata_runtime_observability.py`
- Add: `freshquant/tests/test_trading_dt_proxy.py`
- Modify: `freshquant/market_data/xtdata/market_producer.py`
- Modify: `freshquant/market_data/xtdata/strategy_consumer.py`
- Modify: `freshquant/trading/dt.py`
- Modify: `D:\fqpack\config\supervisord.fqnext.conf`

**Step 1: 跑相邻测试**

Run: `.\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_xtdata_runtime_observability.py freshquant/tests/test_xtdata_mode_defaults.py freshquant/tests/test_trading_dt_proxy.py -q`

**Step 2: 跑语法检查**

Run: `.\\.venv\\Scripts\\python.exe -m py_compile freshquant/market_data/xtdata/market_producer.py freshquant/market_data/xtdata/strategy_consumer.py freshquant/trading/dt.py`

**Step 3: 验证 supervisor 运行状态**

Run: `(Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:10011/program/list').Content`

**Step 4: 记录结果**

- 若 3 个进程全部稳定为 `Running`，记录 PID 与启动时间。
- 若仍有失败，停止继续修改，回到失败日志重新定位。
