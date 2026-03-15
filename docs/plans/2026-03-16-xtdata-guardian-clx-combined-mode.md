# XTData Guardian + CLX 联合模式 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 `monitor.xtdata.mode` 支持正式联合模式 `guardian_and_clx_15_30`，同时运行 Guardian 1 分钟链和 CLX 15/30 筛选，并保持 Guardian 池优先、总订阅数不超过 `monitor.xtdata.max_symbols`。

**Architecture:** 以 `freshquant/market_data/xtdata/pools.py` 为模式语义与订阅池真值源，把原本按单一字符串分叉的逻辑改成按“Guardian 能力 / CLX 能力 / 池子组合规则”判断。producer、consumer、Guardian event、配置读写、初始化和 UI 都改为依赖这层语义，并补齐兼容旧值 `clx_15_30` 的测试与文档。

**Tech Stack:** Python 3.12, pytest, Vue 3, Node test runner, Mongo-backed system settings docs

---

### Task 1: 收口 XTData 模式语义与联合池规则

**Files:**
- Modify: `freshquant/market_data/xtdata/pools.py`
- Test: `freshquant/tests/test_xtdata_mode_defaults.py`

**Step 1: Write the failing tests**

增加这些断言：

```python
assert pools.normalize_xtdata_mode("clx_15_30") == "guardian_and_clx_15_30"
assert pools.normalize_xtdata_mode("guardian_and_clx_15_30") == "guardian_and_clx_15_30"
assert pools.xtdata_mode_enables_guardian("guardian_and_clx_15_30") is True
assert pools.xtdata_mode_enables_clx("guardian_and_clx_15_30") is True
```

再补一个联合池测试，验证：

- guardian 池先返回
- clx 池后补
- 去重
- 最终数量不超过 `max_symbols`

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_xtdata_mode_defaults.py -q`

Expected: 当前代码不认识 `guardian_and_clx_15_30`，新断言失败。

**Step 3: Write minimal implementation**

在 `pools.py` 中：

- 扩展正式模式集合
- 兼容 `clx_15_30 -> guardian_and_clx_15_30`
- 新增能力判断函数
- 把 `load_monitor_codes()` 改成支持联合池拼装

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_xtdata_mode_defaults.py -q`

Expected: 所有模式归一和联合池测试通过。

### Task 2: 改造 producer / consumer / Guardian event 运行链

**Files:**
- Modify: `freshquant/market_data/xtdata/market_producer.py`
- Modify: `freshquant/market_data/xtdata/strategy_consumer.py`
- Modify: `freshquant/signal/astock/job/monitor_stock_zh_a_min.py`
- Test: `freshquant/tests/test_xtdata_market_producer_subscription_pool.py`
- Test: `freshquant/tests/test_xtdata_consumer_runtime_config.py`
- Test: `freshquant/tests/test_guardian_monitor_cli.py`
- Create or Modify: `freshquant/tests/test_guardian_monitor_mode.py`

**Step 1: Write the failing tests**

补测试验证：

- producer 在联合模式下返回规范化 mode，并装载联合池
- consumer 在联合模式下仍给 15/30 分钟返回 CLX model ids
- Guardian event 在联合模式下不退出

示例断言：

```python
assert config["mode"] == "guardian_and_clx_15_30"
assert consumer._model_ids_for("15min") == list(range(10001, 10013))
```

**Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest freshquant/tests/test_xtdata_market_producer_subscription_pool.py freshquant/tests/test_xtdata_consumer_runtime_config.py -q`

Expected: 当前代码仍按旧字符串判断，联合模式相关断言失败。

**Step 3: Write minimal implementation**

实现这些改动：

- producer 继续读取 mode，但订阅池直接走新的 `load_monitor_codes()`
- consumer 把 `_model_ids_for()` 改成基于 CLX 能力判断
- Guardian event 改成基于 Guardian 能力判断是否允许运行

**Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest freshquant/tests/test_xtdata_market_producer_subscription_pool.py freshquant/tests/test_xtdata_consumer_runtime_config.py freshquant/tests/test_guardian_monitor_cli.py -q`

Expected: 运行链模式判断相关测试通过。

### Task 3: 收口系统设置、初始化与前端选项

**Files:**
- Modify: `freshquant/system_settings.py`
- Modify: `freshquant/system_config_service.py`
- Modify: `freshquant/preset/params.py`
- Modify: `freshquant/initialize.py`
- Modify: `morningglory/fqwebui/src/views/SystemSettings.vue`
- Test: `freshquant/tests/test_initialize.py`
- Test: `freshquant/tests/test_system_settings.py`
- Test: `freshquant/tests/test_system_config_service.py`
- Test: `morningglory/fqwebui/src/components/mySettingSanitizer.test.mjs`
- Test: `morningglory/fqwebui/src/views/systemSettings.test.mjs`

**Step 1: Write the failing tests**

补测试验证：

- settings / config service 读到旧值 `clx_15_30` 时，运行态得到的是联合模式
- `initialize.py` 在联合模式下仍只按 Guardian 池做默认 Guardian 策略绑定
- UI 下拉只显示：
  - `guardian_1m`
  - `guardian_and_clx_15_30`

**Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest freshquant/tests/test_initialize.py freshquant/tests/test_system_settings.py freshquant/tests/test_system_config_service.py -q`

Run: `node --test morningglory/fqwebui/src/components/mySettingSanitizer.test.mjs morningglory/fqwebui/src/views/systemSettings.test.mjs`

Expected: Python 侧在联合模式兼容和初始化边界上失败；前端旧 option 文案也需更新。

**Step 3: Write minimal implementation**

实现这些改动：

- 后端配置读取统一走模式归一
- 初始化默认 Guardian 策略绑定固定按 Guardian 池
- 系统设置页 option 改成两个正式值
- 相关展示文案改成联合模式语义

**Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest freshquant/tests/test_initialize.py freshquant/tests/test_system_settings.py freshquant/tests/test_system_config_service.py -q`

Run: `node --test morningglory/fqwebui/src/components/mySettingSanitizer.test.mjs morningglory/fqwebui/src/views/systemSettings.test.mjs`

Expected: 配置兼容、初始化边界和前端展示测试通过。

### Task 4: 同步当前文档并做最终验证

**Files:**
- Modify: `docs/current/modules/market-data-xtdata.md`
- Modify: `docs/current/modules/strategy-guardian.md`
- Modify: `docs/current/reference/system-settings-params.md`
- Modify: 其它命中旧模式语义的 `docs/current/**`

**Step 1: Update docs**

把当前文档中的旧二选一表述改成：

- 正式模式：`guardian_1m` / `guardian_and_clx_15_30`
- 兼容旧值：`clx_15_30`
- 联合模式语义：Guardian 池优先、CLX 池补足、功能共存

**Step 2: Run focused verification**

Run: `py -3.12 -m pytest freshquant/tests/test_xtdata_mode_defaults.py freshquant/tests/test_xtdata_market_producer_subscription_pool.py freshquant/tests/test_xtdata_consumer_runtime_config.py freshquant/tests/test_initialize.py -q`

Run: `node --test morningglory/fqwebui/src/components/mySettingSanitizer.test.mjs morningglory/fqwebui/src/views/systemSettings.test.mjs`

Expected: 相关后端 / 前端测试通过。

**Step 3: Check worktree diff**

Run: `git status --short`

Expected: 只包含本需求相关改动。
