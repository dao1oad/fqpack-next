# 订单对账真值解耦与价格冻结设计

## 背景

`300760` 在 `2026-03-31 17:21:09` 的 `AUTO_OPENED` 暴露了两类问题：

- external reconcile 的 `buy gap` 会在持续观测中不断刷新 `price_estimate`，最终确认价会漂移到更晚的持仓推导价，而不是保持首次发现时的价格快照。
- `AUTO_OPENED` 的确认流程和 entry slice 排布强耦合。`grid_interval` 或 `lot_amount` 这类运行期辅助元数据解析失败时，gap 无法确认，真值收敛会被无关依赖长时间阻塞。

同类问题已经在 `300760 / 600570 / 600104` 等标的上出现过，说明这不是单标的偶发问题，而是 current reconcile 语义存在结构性耦合。

## 目标

- 冻结 external reconcile gap 的首次价格快照，避免长时间观测导致确认价漂移。
- 把 external reconcile 的“真值确认”和“运营切片排布”拆开，保证 broker truth / 持仓 truth 可以先收敛。
- 将 `grid_interval`、`lot_amount` 解析收口为统一的 reconcile runtime params 解析器，并提供稳定 fallback。
- 在 Guardian 和 runtime observability 中显式区分：
  - `entry 已确认`
  - `entry 已降级`
  - `entry slice 仍待排布`
- 保持 `xt_positions / om_position_entries / arranged_fills / compat` 的真值一致性。

## 非目标

- 本轮不重写整个 order ledger v2。
- 本轮不改写 XT 原始回报格式。
- 本轮不一次性移除全部 legacy compat 逻辑。
- 本轮不做外部回报匹配策略的大规模语义重构，只在当前链路上补充 partial match 支撑。

## 约束

- 运行真值仍以 `xt_positions + om_*` 为准，compat 只是投影视图。
- Guardian、TPSL、兼容视图仍依赖切片结果，因此不能简单“只存 entry 不管排布”，必须有可解释的降级状态。
- 正式部署后需要重启 `order_management`、`xt_account_sync.worker`、Guardian 相关运行面。
- 当前仓库有脏主工作树，本轮实现必须在隔离 worktree 中完成。

## 根因归纳

### 1. gap 价格快照会在观测期持续漂移

`detect_external_candidates()` 每次轮询都重新构造 `price_snapshot`，并在 `_build_gap_observation_updates()` 中对同一 gap 覆写 `price_estimate / source / asof`。同优先级下，代码使用更新的 `price_asof`，导致长时间未确认的 gap 最终价格变成更晚一轮的持仓推导价。

### 2. 真值确认和切片排布耦合

`_confirm_open_gap()` 在把 gap 变为 `AUTO_OPENED` 之前，必须先生成 `auto_open_entry` 对应的 entry slices。`grid_interval` 或 `lot_amount` 解析异常时，整个确认过程直接抛错，gap 只能保持 `OPEN`，等待下一轮重试。

### 3. runtime 只保留包装异常，缺少原始故障上下文

旧版 `_safe_grid_interval_lookup()` 把内层异常统一包装成 `RuntimeError("grid interval unavailable ...")`，运行日志缺少底层失败点，难以区分配置缺失、Mongo 读失败、strategy helper 异常还是其他环境问题。

### 4. Guardian 没有“entry 已存在但排布降级”的语义

Guardian 当前主要看 `xt_positions + arranged_fills`。一旦 entry 已确认但 slices 尚未排布或降级，运行上会更接近“持仓已存在，但运营排布还未就绪”，而不是“无持仓”。当前日志和分支语义不足以表达这一层。

## 方案对比

### 方案 A：保留现有结构，只补 fallback

- 优点：改动小，上线快。
- 缺点：真值确认与运营排布仍耦合，未来仍会被其他辅助依赖卡住。

### 方案 B：两阶段确认，推荐

- 第一阶段：确认 external position truth，落 `om_position_entries`
- 第二阶段：尝试生成 slices；失败时保留 entry，但把排布状态标为 `DEGRADED`

- 优点：真值先收敛，辅助元数据失败不会阻塞确认；更符合 broker truth 优先原则。
- 缺点：要补 entry/arrangement 状态语义与下游适配。

### 方案 C：引入完整 external holdings event ledger

- 优点：长期结构最清晰。
- 缺点：范围过大，不适合当前上线窗口。

采用方案 B，并吸收方案 A 中的低风险增强。

## 架构设计

### 1. gap 价格双快照

在 reconciliation gap 上拆成两组价格字段：

- `initial_price_estimate`
- `initial_price_source`
- `initial_price_asof`
- `latest_price_estimate`
- `latest_price_source`
- `latest_price_asof`
- `chosen_price_estimate`
- `chosen_price_policy`

规则：

- gap 首次创建时，同时写入 `initial_*` 和 `latest_*`
- 后续观测只更新 `latest_*`
- `chosen_price_estimate` 在默认策略下固定等于 `initial_price_estimate`
- runtime event 明确展示 `initial / latest / chosen`

这样可以冻结确认价，同时保留调试所需的后续漂移信息。

### 2. external reconcile 两阶段确认

`_confirm_open_gap()` 拆为：

- `stage 1: _materialize_open_entry_truth()`
  - 创建 `om_position_entries`
  - 落 reconciliation resolution
  - 更新 gap 为 `AUTO_OPENED`
- `stage 2: _materialize_open_entry_arrangement()`
  - 解析 `grid_interval` 与 `lot_amount`
  - 尝试生成 entry slices
  - 成功则 `arrange_status=READY`
  - 失败则 `arrange_status=DEGRADED`，记录 `arrange_error_*`

entry 新增字段：

- `arrange_status`: `READY | DEGRADED | PENDING`
- `arrange_degraded`
- `arrange_error_code`
- `arrange_error_type`
- `arrange_error_message`
- `grid_interval`
- `lot_amount`
- `price_policy`

### 3. 统一 reconcile runtime params 解析

新增统一 helper，例如：

- `resolve_reconcile_runtime_params(symbol, trade_fact)`

返回：

- `grid_interval`
- `lot_amount`
- `grid_source`
- `lot_source`
- `degraded`
- `errors`

优先级：

1. `instrument_strategy`
2. Guardian params
3. 默认值

默认值：

- `grid_interval = 1.03`
- `lot_amount = 3000`

这层要把原始异常保留下来，而不是只返回包装后的大类错误。

### 4. Guardian 降级语义

Guardian 的 holding/arranged fill 适配层补充区分：

- `entry_absent`
- `entry_present_without_slices`
- `entry_present_arrangement_degraded`
- `entry_present_ready`

对交易决策的默认策略：

- 有持仓范围判断仍以 `xt_positions` 为准
- `entry_present_without_slices` 或 `degraded` 不再记录为“无持仓”
- 卖出路径可继续保守跳过，但要输出明确原因：
  - `no_arranged_fills`
  - `arrangement_degraded`

### 5. external trade partial match

当前 `_match_inflight_internal_order()` 要求数量全等，导致 `intent=600`、`external_reported=300` 这种场景无法挂回内部单。

本轮补成：

- 允许 `external_reported.quantity < internal_request.quantity`
- 记录 `partial_match_quantity`
- 内部单保留剩余未匹配数量
- reconcile gap 只保留真正未解释的 residual delta

这能减少无意义的 externalization，同时不破坏现有精确匹配路径。

## 数据流

### buy gap

1. `xt_account_sync` 轮询 positions
2. `detect_external_candidates()` 创建或刷新 buy gap
3. gap 首次创建时冻结 `initial_price_*`
4. `confirm_expired_candidates()` 到期后执行真值确认
5. `om_position_entries` 落库，gap -> `AUTO_OPENED`
6. arrangement 尝试生成 slices
7. 若失败：
   - entry 仍保持 `OPEN`
   - `arrange_status=DEGRADED`
   - compat / holdings cache 仍同步
8. 后续可通过 repair/rebuild 或下轮 helper 修复重新排布

### runtime observability

需要在 reconcile event payload 中增加：

- `gap_id`
- `initial_price_estimate`
- `latest_price_estimate`
- `chosen_price_estimate`
- `chosen_price_policy`
- `arrange_status`
- `arrange_degraded`
- `grid_source`
- `lot_source`
- `raw_exception`

## 失败处理

- 价格快照解析失败：仍创建 gap，价格降为 `0`，明确 `price_source=missing`
- grid/lot 解析失败：entry truth 正常确认，arrangement 降级
- partial match 歧义：保留现有 defer 语义，不做冒进匹配
- Guardian 遇到 degraded entry：跳过依赖 slices 的操作，但不写“无持仓”

## 测试设计

### reconcile

- 首次价格冻结后，后续观测只更新 `latest_*`，`chosen_price` 不漂移
- `grid_interval` 解析失败时，gap 仍能 `AUTO_OPENED`
- `lot_amount` 解析失败时，gap 仍能 `AUTO_OPENED`
- `arrange_status=DEGRADED` 时 entry 已落库、slice 可为空
- partial match 时内部单和 external report 正确挂接

### guardian

- `entry 已确认但无 slices` 不再误写成“无持仓”
- degraded arrangement 时输出明确 reason code

### runtime docs / observability

- event payload 新字段存在
- docs/current 与新语义一致

## 验收标准

- `AUTO_OPENED` 不再因为 `grid_interval` 或 `lot_amount` 异常而卡死。
- gap 确认价默认冻结在首次发现时刻，不再因长时间观测漂移。
- `300760` 这类“部分回报数量不等于意图数量”的场景不再一律 externalize。
- Guardian 能正确识别“有 entry 但排布降级”的状态，不再误导为“无持仓”。
- `xt_positions / om_position_entries / arranged_fills / compat` 在正常路径与降级路径下都保持一致。

## 部署影响

- `freshquant/order_management/**`：重部署 API / 相关 worker
- `freshquant/xt_account_sync/**`：重启 `xt_account_sync.worker`
- `freshquant/strategy/**`：重启 Guardian monitor
- 更新 `docs/current/modules/order-management.md`
- 更新 `docs/current/runtime.md`
