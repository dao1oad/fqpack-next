# XTData 三周期监控线正交化设计（Codex × Devin × 用户一致结论）

> 状态：设计结论（未实施）。参与方：Codex（主分析）+ Devin Ultra（第二意见评审，单轮）+ 用户最终决策。
> 结论：双方一致同意「按周期拆三条正交监控线」更优雅；模式按**用途**简化为两种：`trading`（交易：1m 做T + 5m 开新仓）与 `screening`（选股：15/30 CLX，不做交易）；超限策略为「单上限（XTData 接口限制）+ 优先级截断」，不引入兼容别名。
> 范围：方案含后端语义层（`pools.py` + producer/consumer/Guardian 三处消费点）与前端 system-settings 页面改造（详见 §4.5）。

## 1. 背景与现状（代码级事实）

当前 `monitor.xtdata.mode` 单一字符串同时承担三份职责：

1. 决定 producer 订阅池来源
2. 决定 consumer 是否启用 CLX
3. 决定 Guardian 事件监控是否运行

正式模式 3 个 + 兼容别名 1 个（`freshquant/market_data/xtdata/pools.py`）：

| 模式 | 池子 | Guardian | CLX |
|---|---|---|---|
| `guardian_1m`（默认） | `xt_positions` + `must_pool` | ✅ | ❌ |
| `guardian_and_clx_15_30` | guardian 池优先 + 未过期 `stock_pools` 补足，上限 `monitor.xtdata.max_symbols`（默认 50） | ✅ | ✅ |
| `clx_15_30_only` | 仅未过期 `stock_pools` | ❌ | ✅ |
| `clx_15_30`（旧别名） | 归一为 `guardian_and_clx_15_30` | ✅ | ✅ |

运行链：

- `market_producer.py`：whole quote 全量订阅监控池；`OneMinuteBarGenerator` 合成 1 分钟并重采样 5/15/30 分钟入 bar 队列；tick 另推 tick 分片队列。
- `strategy_consumer.py`：消费 bar close，维护 1/5/15/30 分钟窗口；CLX（S0000-S0017，`model_opt=10000..10017`）只在 15/30 分钟对 `stock_pools` 代码运行；命中写 `realtime_screen_multi_period` + TDX `clx_15_30` 分组 + DingTalk；持仓代码丢弃 CLX 信号。
- `monitor_stock_zh_a_min.py`（Guardian 事件监控）：订阅 1min/5min；1min 只处理持仓（做T）；5min 只处理 `must_pool` 且未持仓的股票，信号限定 `buy_v_reverse` / `macd_bullish_divergence`，打 `must_pool_5m_new_open` 标签 → `StrategyGuardian._handle_new_open_buy` 开新仓。
- 前端 `morningglory/fqwebui`：system-settings 页面 `SELECT_FIELD_META['monitor.xtdata.mode']` 以下拉框展示 3 个模式；`SystemSettings.vue` 默认表单 `monitor.xtdata.mode='guardian_1m'`；`systemSettings.test.mjs` 断言 3 个选项；`mySettingSanitizer.mjs` 做 monitor/guardian 旧字段清理。
- 后端配置读写：`freshquant/system_settings.py`（`xtdata_mode` 默认 `guardian_1m` + 归一）、`freshquant/system_config_service.py`（monitor 段 `xtdata.mode` 行 + 读写归一）、`freshquant/preset/params.py`（打印当前模式）。

## 2. 问题诊断（双方一致）

1. **命名掩盖语义**：`guardian_1m` 名义是 1 分钟，实际还包含 5 分钟 `must_pool` 开新仓线；用户心智模型与配置名不匹配。
2. **预算静默挤占**：`guardian_and_clx_15_30` 下持仓 + `must_pool` 接近 50 时，`stock_pools` 会被完全挤出且无告警，CLX 15/30 选股静默失效。
3. **池子定义双轨漂移**：订阅池在 `pools.py` 定义，Guardian 监控又在 `monitor_stock_zh_a_min.py` 里独立计算 `holding_codes` / `must_pool_codes` scope，producer / consumer / Guardian 三处对“池子”的口径存在漂移风险。
4. **能力不可独立表达**：5 分钟监控挂在“Guardian 能力”下，若只想跑 `must_pool` 5m 开新仓 + CLX、不跑 1 分钟做T，现有 mode 无法表达。
5. **认知不匹配**：用户的三条周期线（1m 做T / 5m 开新仓 / 15-30m 选股）被压扁成 mode 字符串枚举，理解与扩展成本高。
6. **前端枚举与后端耦合**：system-settings 下拉框直接枚举 3 个 mode 字符串，模式改名后前端必须同步改造，否则页面与运行真值脱节。

## 3. 目标形态（双方一致）

保持现有架构骨架（单 producer + 单 consumer + 独立 Guardian 事件进程），把「模式字符串」收口为「三条正交监控线」的语义层：

| 监控线 | 周期 | 池子 | 行为 | 排除 |
|---|---|---|---|---|
| `line_1m_t` | 1m | `xt_positions`（持仓） | Guardian 做T | 非持仓 |
| `line_5m_new_open` | 5m | `must_pool` | 开新仓（`buy_v_reverse` / `macd_bullish_divergence` + `must_pool_5m_new_open` 标签） | 持仓 |
| `line_15_30_clx` | 15m/30m | `stock_pools`（未过期） | CLX S0000-S0017 选股 | 持仓 |

**订阅形态确认（Devin 明确认可）**：“订阅并集、消费按周期过滤”是最优形态，不需要按周期细分订阅。

- producer 订阅 = 三条线池子的并集（全量 whole quote，1m 合成 + 5/15/30 重采样不变）
- consumer 侧按周期 + 线归属决定 fullcalc / CLX model_ids
- Guardian 事件监控按线过滤（替代现在硬编码的 1min/5min 分支）

## 4. 推荐方案（三方一致）

### 4.1 配置形状（后端）

在 `monitor.xtdata` 下只保留**两种模式**，按用途命名，彼此独立可同时开启：

```text
monitor.xtdata.trading_mode    # 交易模式：true/false，默认 true
monitor.xtdata.screening_mode  # 选股模式：true/false，默认 false
```

模式与监控线的映射：

| 模式 | 用途 | 启用的监控线 |
|---|---|---|
| `trading_mode=true` | 交易（含开新仓） | `line_1m_t`（1m 做T，仅持仓）+ `line_5m_new_open`（5m must_pool 开新仓，排除持仓） |
| `screening_mode=true` | 选股（不做交易） | `line_15_30_clx`（15/30 CLX 选股，排除持仓） |

两种模式独立开关，组合关系：

| trading | screening | 语义 | 对应旧 3 模式 |
|---|---|---|---|
| true | false | 只做交易（做T + 开新仓） | `guardian_1m` |
| true | true | 交易 + 选股 | `guardian_and_clx_15_30` |
| false | true | 只做选股 | `clx_15_30_only` |

### 4.2 超限策略（用户最终决策）

- 监控最大数量由 **XTData 接口限制**决定，`monitor.xtdata.max_symbols` 表达该上限。
- 并集装配按**优先级**依次填入，达到上限即截断：
  - `line_1m_t` > `line_5m_new_open` > `line_15_30_clx`
- 先保证高优先级集合完整监控；容量不足时低优先级集合被截断（按排序去重后从低优先级末尾截断）。
- 截断发生时写 runtime 事件（`reason_code=line_codes_truncated`，含被截断的 line 与数量）并记日志告警，保持可观测、不静默。
- 不再引入 per-line 独立预算；单一上限 + 优先级截断即为容量模型。

### 4.3 后端组件职责

- `freshquant/market_data/xtdata/pools.py`：单一真值源。提供 per-line code loader + `模式（trading/screening）→ 监控线` 映射 + 并集/优先级截断 + 触顶告警事件；废弃 `normalize_xtdata_mode` 的旧枚举逻辑，改为按两个布尔推导。
- `market_producer.py`：只订阅并集（行为不变，继续全量 whole quote）。
- `strategy_consumer.py`：`_model_ids_for` 只对 `line_15_30_clx` 的 15/30 分钟返回 CLX model ids；prewarm/window 维护仍按 1/5/15/30 全周期。
- `monitor_stock_zh_a_min.py`：1min 分支只对 `line_1m_t` 池（持仓），5min 分支只对 `line_5m_new_open` 池（must_pool 且未持仓），信号类型与标签逻辑不变。
- `freshquant/system_settings.py`、`freshquant/system_config_service.py`、`freshquant/preset/params.py`：配置读写从 `xtdata_mode` 单字段改为 `xtdata_trading_mode` / `xtdata_screening_mode` 双字段，并提供一次性迁移（见 §4.4）。

### 4.4 兼容与迁移

- **不需要兼容别名**：正式配置仅两种模式（`trading_mode` / `screening_mode`）；旧 `monitor.xtdata.mode` 字段退役，由一次性迁移映射到新模式组合：
  - `guardian_1m` → `trading_mode=true, screening_mode=false`
  - `guardian_and_clx_15_30` → `trading_mode=true, screening_mode=true`
  - `clx_15_30_only` → `trading_mode=false, screening_mode=true`
  - `clx_15_30` → `trading_mode=true, screening_mode=true`（原归一语义）
  - 迁移后运行时不保留任何旧值归一/别名逻辑，未知值回退默认（`trading_mode=true, screening_mode=false`）。
- 一期只落设计与语义层（`pools.py` + 三处消费点 + 配置读写），不引入第二套 producer / consumer。
- Guardian 交易语义（时间窗、阈值、网格、cooldown、止盈止损、仓位管理）一律不动。

### 4.5 前端改造（system-settings 页面）—— 本次补充

**结论：方案包含前端改造。** 当前页面直接以内嵌列表编辑正式设置项，`monitor.xtdata.mode` 是其中唯一一个 3 值下拉；模式改为两个布尔后，前端必须同步。具体改动：

1. **`morningglory/fqwebui/src/views/systemSettings.mjs`**
   - `SELECT_FIELD_META`：删除 `'monitor.xtdata.mode'` 的 3 值下拉定义。
   - 新增 `'monitor.xtdata.trading_mode'` 与 `'monitor.xtdata.screening_mode'` 布尔选择（`{ label: '开启', value: true }` / `{ label: '关闭', value: false }`，复用现有 `xtquant.auto_repay.enabled` 的布尔选项形态）。
   - `NUMBER_FIELD_META` 中 `monitor.xtdata.max_symbols` / `queue_backlog_threshold` / `prewarm.max_bars` 保持不变（语义未变）。
2. **`morningglory/fqwebui/src/views/SystemSettings.vue`**
   - `defaultSettingsForm()` 中 `monitor.xtdata` 由 `{ mode: 'guardian_1m', max_symbols: 60, queue_backlog_threshold: 500, prewarm: { max_bars: 240 } }` 改为 `{ trading_mode: true, screening_mode: false, max_symbols: 60, queue_backlog_threshold: 500, prewarm: { max_bars: 240 } }`。
   - 行渲染模板无需结构性改动（`el-select` 对布尔选项通用）。
3. **`morningglory/fqwebui/src/views/systemSettings.test.mjs`**
   - `resolveEditorMeta('monitor.xtdata.mode')` 断言（当前断言 3 个旧值）改为分别断言 `monitor.xtdata.trading_mode` / `monitor.xtdata.screening_mode` 返回布尔选项。
4. **`morningglory/fqwebui/src/components/mySettingSanitizer.mjs`**
   - `monitor` 分支增加一次性迁移：若 `sanitized.xtdata.mode` 存在，按 §4.4 映射写 `trading_mode` / `screening_mode` 并删除 `mode` 键；迁移后不保留别名逻辑。
   - 对应补 `mySettingSanitizer.test.mjs` 用例（旧 mode → 双布尔迁移）。
5. **后端配置服务配套**（前端保存链路的写侧真值）
   - `freshquant/system_config_service.py`：monitor 段 `("xtdata.mode", "XTData 模式")` 改为 `("xtdata.trading_mode", "交易模式")` + `("xtdata.screening_mode", "选股模式")`；读写归一从 `normalize_xtdata_mode` 改为双布尔校验。
   - `freshquant/system_settings.py`：`MonitorSettings` 的 `xtdata_mode: str` 改为 `xtdata_trading_mode: bool = True` + `xtdata_screening_mode: bool = False`，读取时对旧 `mode` 文档做一次性迁移。
   - `freshquant/preset/params.py`：打印行改为两种模式。
6. **验收**：`node --test morningglory/fqwebui/src/views/systemSettings.test.mjs morningglory/fqwebui/src/components/mySettingSanitizer.test.mjs` 全绿；页面中列仍为「运行接入 / 系统链路」，monitor 段展示「交易模式 / 选股模式」两个开关与既有数字项。

## 5. 一致点与分歧点

### 一致点

- 按周期拆三条正交监控线比单一 mode 字符串更优雅。
- “订阅并集、消费按周期过滤”是最优形态，不需按周期细分订阅。
- 池子定义收敛到 `pools.py` 单真值，消除三处双轨漂移。
- 超限/截断必须可见（runtime 事件 + 日志告警），不静默。
- 模式按用途命名：`trading`（交易：1m 做T + 5m 开新仓）与 `screening`（选股：15/30 CLX，不做交易），两种模式独立可同时开启。
- 前端 system-settings 必须同步改造为两个布尔开关（本次确认）。

### 分歧点（已消解）

- Codex 初始方案侧重“mode → 三条线”语义拆解；Devin 指出 `max_symbols` 静默挤占必须升级为一等公民（per-line 预算 + 触顶告警），并确认池子三处双轨定义是漂移风险点。
- **用户最终决策**：不引入 per-line 预算与兼容别名；改为「单上限（XTData 接口限制）+ 优先级截断 `line_1m_t` > `line_5m_new_open` > `line_15_30_clx`」。告警与池子单真值保留。per-line 预算方案不采用。
- **用户最终决策（模式命名）**：不保留 3 个旧模式字符串，简化为两种按用途命名的模式——`trading`（交易）与 `screening`（选股）；两者独立可同时开启，等价覆盖旧 3 模式组合。

## 6. 落盘结论摘要

1. 现状的混淆根因：单一 mode 承担订阅池 / 周期能力 / 监控行为三份职责，且 `guardian_1m` 命名掩盖 5m 开新仓线。
2. 目标：三条正交监控线（1m 持仓做T / 5m must_pool 开新仓 / 15-30m stock_pools CLX），订阅并集、消费按周期过滤。
3. 超限策略：单上限 = XTData 接口限制；按 `line_1m_t` > `line_5m_new_open` > `line_15_30_clx` 优先级装配，高优先级集合优先完整，低优先级可截断；截断告警不静默。
4. 模式简化：正式配置仅两种按用途命名的模式——`trading`（交易：1m 做T + 5m 开新仓）与 `screening`（选股：15/30 CLX，不做交易），独立可同时开启；旧 `monitor.xtdata.mode` 一次性迁移后退役，不保留运行时兼容别名。
5. 前端改造：system-settings 页面的 `monitor.xtdata.mode` 3 值下拉改为「交易模式 / 选股模式」两个布尔开关，涉及 `systemSettings.mjs`、`SystemSettings.vue`、`systemSettings.test.mjs`、`mySettingSanitizer.mjs`（+测试）与后端配置服务双字段读写（§4.5）。
6. 范围：不改 Guardian 交易语义，不引入第二套 producer / consumer；实施走 feature branch + PR，并同步 `docs/current/modules/market-data-xtdata.md`。
