# RFC 0007: 股票/ETF 系统化订单管理与逐买入跟踪

- **状态**：Approved
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-06
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）
目标仓库当前股票/ETF 下单链路已经具备“能下单、能收回报、能生成 `stock_fills`”的基础能力，但订单事实、策略视图、持仓推导、单笔止损口径仍然混杂在一起，主要问题如下：

- 新仓库当前的 `xt_trades -> stock_fills` 会按“同日/同价/同方向”聚合写入，丢失原始买入订单身份，无法支撑逐买入跟踪与卖出归因。
- `stock_fills` 同时承担了成交汇总、剩余持仓、Guardian 策略递归拆层三种职责，导致它既不是稳定账本，也不是纯视图。
- Guardian 卖出数量依赖 `accStockTrades()` / `accArrangedStockTrades()` 运行时重建的“剩余买入层 + 递归拆层层级”，这套语义必须保留，但当前没有持久化的“卖出到底扣减了哪笔买入/哪一层”的关系。
- 旧仓库的 `fill_stoploss_helper.py`、`position_sync.py`、`strategy_tracker.py`、`order_manager.py` 已经分别解决了部分问题，但仍然没有统一的“订单主账本 + 买入 lot + 卖出分摊账本”。
- 外部订单场景下，系统可能只能观察到仓位变化，无法直接获得完整回报；若没有统一的推断与对账模型，则策略视图、仓位视图与订单视图会长期不一致。

本 RFC 以 `D:\fqpack\freshquant` 中以下能力为迁移来源，并在目标仓库中进行统一重构：

- 订单创建与入队：`freshquant\strategy\toolkit\order_manager.py`
- 订单跟踪：`freshquant\strategy\toolkit\order_tracking_service.py`、`freshquant\strategy\toolkit\strategy_tracker.py`
- 单笔止损 remaining 计算：`freshquant\strategy\toolkit\fill_stoploss_helper.py`
- 持仓/成交同步与 prune：`morningglory\fqxtrade\fqxtrade\util\position_sync.py`
- Guardian 递归拆层与卖出数量计算：`freshquant\strategy\guardian.py`、`freshquant\data\astock\holding.py`

## 2. 目标（Goals）
- 统一接管股票/ETF 的 `buy / sell / cancel` 入口，覆盖策略自动单、Web/API 手工单、CLI/脚本手工单以及系统外订单。
- 建立独立的订单域主账本，完整记录订单、委托事件、成交事实、取消事件、外部推断与自动确认过程。
- 将订单管理新增主数据集合统一存放在独立 Mongo 数据库中，与现有 `freshquant` 业务库分离，方便账本边界、排障与运维区分。
- 将“原始买入 lot”“Guardian 策略拆层 slice”“卖出分摊 allocation”显式建模，支持逐买入订单的完整生命周期跟踪。
- 保持 Guardian 当前卖出数量计算语义不变，包括现有递归拆层与“按当前策略层级扣减”的行为。
- 支持“某笔买入订单已经被部分卖出后，仅对剩余数量做单笔止损”，并能展示该笔买入的卖出历史。
- 保留 `stock_fills` 对旧 API/UI/策略兼容的能力，但将其降级为兼容投影视图，不再作为主账本。
- 支持外部订单推断：允许先进入推断态，若 120 秒内未获得正式回报，则自动确认为外部订单事实。

## 3. 非目标（Non-Goals）
- 不处理期货、数字货币、债券回购等非股票/ETF 品种。
- 不重写 MiniQMT/XTQuant SDK 或 broker 通讯协议。
- 不引入新的外部消息系统、中间件或新的数据库服务实例；仅在现有 Mongo 基础设施内新增独立数据库。
- 不在本 RFC 内重构所有历史 UI，只要求通过兼容投影与兼容接口维持现有能力。
- 不在本 RFC 内解决配置体系总收敛问题（另行治理）。

## 4. 范围（Scope）
**In Scope**
- 股票/ETF 的统一订单受理、跟踪、查询与对账。
- `orders / order_events / trade_facts / buy_lots / lot_slices / sell_allocations / stoploss_bindings / external_candidates` 数据模型。
- Guardian 兼容读模型与 `stock_fills` 兼容投影。
- 外部订单的回报补齐、仓位差异推断与 120 秒自动确认。
- 将旧的单笔止损从 `fill_id` 语义迁移到 `buy_lot_id` 语义。

**Out of Scope**
- 期货订单管理。
- 全量事件溯源平台化改造。
- 风控规则大一统改造。
- 前端全面改版。

## 5. 模块边界（Responsibilities / Boundaries）
**负责（Must）**
- 提供统一的订单受理层，生成内部 `request_id`、`internal_order_id`、`req_id`。
- 维护订单状态机与事件流。
- 维护原始成交事实（不可变）、买入 lot、策略拆层 slice、卖出分摊 allocation。
- 将新增订单域主账本集合落在独立数据库中，并明确兼容投影与主账本的跨库边界。
- 提供 Guardian 兼容视图、单笔止损绑定与剩余量查询。
- 提供外部订单推断、自动确认与仓位主动查询对账。
- 维护 `stock_fills` 兼容投影与投影缓存失效策略。

**不负责（Must Not）**
- 不直接实现新的券商执行通道。
- 不承担期货交易领域建模。
- 不将 `stock_fills` 继续作为主账本。

**依赖（Depends On）**
- 现有 XT 执行层与回报链路：`morningglory/fqxtrade/fqxtrade/xtquant/`
- 现有 Mongo / Redis 基础设施
- 现有 Guardian 策略语义与网格参数计算能力
- 现有 `xt_positions / xt_orders / xt_trades` 同步能力

**禁止依赖（Must Not Depend On）**
- 不允许新业务继续直接写 `stock_fills` 作为事实源。
- 不允许单笔止损继续以 `stock_fills._id` 作为长期稳定主键。
- 不允许 Guardian 的卖出分摊再依赖“仅运行时重算但不落库”的隐式扣减。

## 6. 对外接口（Public API）
> 本 RFC 同时包含稳定 Python API、兼容 HTTP API 与内部执行层对接协议。

### 6.1 稳定内部 API
- `submit_order(payload) -> request_id`
- `cancel_order(payload) -> request_id`
- `ingest_order_report(report) -> None`
- `ingest_trade_report(report) -> None`
- `reconcile_account(account_id) -> summary`
- `list_orders(filters) -> list`
- `get_order_detail(internal_order_id) -> dict`
- `list_buy_lots(symbol) -> list`
- `get_buy_lot_detail(buy_lot_id) -> dict`
- `list_arranged_fill_slices(symbol) -> list`
- `list_stock_fills_raw(symbol) -> list`
- `list_stock_fills_open(symbol) -> list`

### 6.2 兼容接口策略
- 现有依赖 `get_stock_fill_list()` / `get_arranged_stock_fill_list()` / `/api/stock_fills` / `/api/stock_fills/raw` / `/api/fill_stoploss_*` 的调用方，在迁移期继续保留原接口名。
- 这些接口的底层数据来源将切换为新订单模块的读模型与兼容投影，而非直接读取旧式 `stock_fills` 主逻辑。
- API 目标为“语义兼容、字段尽量不变”，但底层存储与内部主键允许重构。

### 6.3 错误语义
- 订单受理失败：返回明确的参数错误/风控错误/执行不可用错误。
- 回报补齐失败：保留订单事实，追加异常事件，不丢失原始数据。
- 外部订单推断失败：记录异常事件，不阻断正常订单链路。
- 投影失败：不得影响主账本写入，但必须可监控、可重试。

## 7. 数据与配置（Data / Config）
### 7.1 数据库存放边界
- 新增订单管理主账本集合统一存放于独立 Mongo 数据库，默认库名为 `freshquant_order_management`。
- 上述主账本集合不得直接落入现有 `freshquant` 主业务库，避免与历史 `stock_fills / xt_orders / xt_trades / xt_positions` 混放。
- 兼容投影 `stock_fills` 在迁移期仍允许保留在现有 `freshquant` 业务库中，以维持旧接口与旧查询路径不变。
- 新旧库之间只通过业务键关联（如 `internal_order_id`、`buy_lot_id`、`trade_fact_id`），不使用 Mongo DBRef。

### 7.2 主数据集合
- `om_order_requests`
- `om_orders`
- `om_order_events`
- `om_trade_facts`
- `om_buy_lots`
- `om_lot_slices`
- `om_sell_allocations`
- `om_stoploss_bindings`
- `om_external_candidates`

### 7.3 核心对象定义
#### `om_order_requests`
- 统一入口请求。
- 关键字段：`request_id`、`source`、`action`、`symbol`、`price`、`quantity`、`strategy_name`、`remark`、`scope_type`、`scope_ref_id`、`req_id`、`state`。

#### `om_orders`
- 统一订单对象。
- 关键字段：`internal_order_id`、`request_id`、`broker_order_id`、`symbol`、`side`、`state`、`source_type`、`submitted_at`、`filled_quantity`、`avg_filled_price`。

#### `om_order_events`
- 追加式事件流。
- 事件示例：`accepted`、`queued`、`submit_started`、`submitted`、`trade_reported`、`cancel_requested`、`canceled`、`rejected`、`failed`、`inferred_pending`、`inferred_confirmed`。

#### `om_trade_facts`
- 不可变成交事实。
- 关键字段：`trade_fact_id`、`internal_order_id`、`broker_trade_id`、`symbol`、`side`、`quantity`、`price`、`trade_time`、`source`、`provisional`。

#### `om_buy_lots`
- 原始买入 lot。
- 关键字段：`buy_lot_id`、`origin_trade_fact_id`、`symbol`、`account_id`、`buy_price_real`、`original_quantity`、`remaining_quantity`、`amount_adjust`、`source`、`status`、`arrange_mode`。

#### `om_lot_slices`
- Guardian 策略拆层。
- 关键字段：`lot_slice_id`、`buy_lot_id`、`slice_seq`、`guardian_price`、`original_quantity`、`remaining_quantity`、`sort_key`、`arrange_snapshot`、`status`。
- `arrange_snapshot` 负责冻结当时的 `trade_amount`、grid interval、ATR 参数等，保证历史 lot 不因后续参数变化而重排。

#### `om_sell_allocations`
- 卖出分摊。
- 关键字段：`allocation_id`、`sell_trade_fact_id`、`buy_lot_id`、`lot_slice_id`、`allocated_quantity`、`allocation_policy`、`source`。

#### `om_stoploss_bindings`
- 单笔止损绑定。
- 关键字段：`binding_id`、`buy_lot_id`、`symbol`、`stop_price`、`ratio`、`enabled`、`state`、`last_trigger_*`、`last_error`、`last_block_reason`。

#### `om_external_candidates`
- 外部订单候选。
- 关键字段：`candidate_id`、`symbol`、`side`、`quantity_delta`、`price_estimate`、`detected_at`、`pending_until`、`state`、`matched_order_id`。

### 7.4 配置项
- `order_management.mongo_database = freshquant_order_management`
- `order_management.projection_database = freshquant`
- `order_management.external_confirm_seconds = 120`
- `order_management.guardian_allocation_policy = guardian_compat_low_price_first`
- `order_management.enable_stock_fills_projection = true`
- `order_management.enable_dual_read_compare = true`（迁移期）
- `order_management.enable_legacy_fill_stoploss_adapter = true`（迁移期）

### 7.5 `stock_fills` 新职责
`stock_fills` 在本 RFC 下被重新定义为**兼容投影**，而非主账本：

- `raw fills view`：从 `om_trade_facts` 投影，用于 `/api/stock_fills/raw`、KlineSlim 原始成交展示、人工排障。
- `open buy fills view`：从 `om_buy_lots` 投影，对齐当前 `get_stock_fill_list()` 语义。
- `arranged fills view`：从 `om_lot_slices` 投影，对齐当前 `get_arranged_stock_fill_list()` 语义，继续服务 Guardian 与旧 UI。

迁移期允许保留物理 `stock_fills` 集合作为兼容投影，但禁止将其作为事实源继续被业务直写。

## 8. 破坏性变更（Breaking Changes）
本 RFC 预期包含以下破坏性变更；实现落地时必须同步更新 `docs/migration/breaking-changes.md`：

- 新增订单管理主账本独立数据库 `freshquant_order_management`，新主数据不再进入 `freshquant` 业务库。
- `stock_fills` 从“事实 + 视图混合表”转为“兼容投影视图”。
- 单笔止损的主绑定对象从 `fill_id` 迁移到 `buy_lot_id`。
- 现有直写 `stock_fills` 的逻辑（如 import/reset/cleanup/compact）需要迁移到订单域主账本与投影器。
- 依赖 `stock_fills._id` 作为长期业务标识的逻辑将失效，必须改用新域对象标识。

### 迁移步骤
1. 新增订单域主账本与兼容投影，保留旧读接口。
2. 对 `get_stock_fill_list()` / `get_arranged_stock_fill_list()` 做双轨比对，验证 Guardian 语义一致。
3. 先切 Guardian 读路径，再切单笔止损绑定对象。
4. 最后收口所有直写 `stock_fills` 的路径。

### 回滚方案
- 保留旧 `stock_fills` 兼容读逻辑，回滚时切回 legacy reader。
- 保留 dual-read compare 期间的差异日志，便于快速定位语义漂移。
- 在完全切换前，不删除旧集合与旧接口。

## 9. 迁移映射（From `D:\fqpack\freshquant`）
- `freshquant\strategy\toolkit\order_manager.py` → `freshquant/order_management/submit/`
- `freshquant\strategy\toolkit\order_tracking_service.py` → `freshquant/order_management/tracking/`
- `freshquant\strategy\toolkit\strategy_tracker.py` → `freshquant/order_management/tracking/legacy_strategy_adapter.py`
- `freshquant\strategy\toolkit\fill_stoploss_helper.py` → `freshquant/order_management/stoploss/`
- `morningglory\fqxtrade\fqxtrade\util\position_sync.py` → `freshquant/order_management/reconcile/`
- `freshquant\data\astock\holding.py` 的 `accStockTrades/accArrangedStockTrades` 语义 → `freshquant/order_management/guardian/arranger.py` 与 `allocation_policy.py`
- `freshquant\strategy\guardian.py` 继续保留策略入口，但其底层读模型改为新订单域提供的 arranged slice 视图

## 10. 测试与验收（Acceptance Criteria）
- [ ] `om_*` 主数据集合全部落在独立数据库 `freshquant_order_management`（或其配置值）中，未写入 `freshquant` 业务库。
- [ ] 同一组样本成交输入下，新读模型产出的 arranged fills 与旧 `get_arranged_stock_fill_list()` 的卖出数量计算结果一致。
- [ ] Guardian 在迁移前后对同一组历史样本生成的卖出数量保持一致。
- [ ] 一笔原始买入被递归拆层后，发生部分卖出，系统能准确展示：
  - [ ] 原始买入 lot
  - [ ] 该 lot 的卖出历史
  - [ ] 当前剩余数量
  - [ ] 该 lot 的单笔止损配置与状态
- [ ] 单笔止损只会作用于指定 `buy_lot` 的剩余部分，不影响其他 lot。
- [ ] 外部订单在“有回报”和“无回报但 120 秒后自动确认”两种场景下，都能进入统一订单链路并反映到 Guardian 兼容视图。
- [ ] `stock_fills` 兼容接口在迁移期继续可用，KlineSlim、持仓展示、Guardian 不因底层主账本切换而中断。
- [ ] `get_stock_holding_codes()` 等缓存读取路径在投影刷新后具备明确失效策略，不出现长期脏读。

## 11. 风险与回滚（Risks / Rollback）
- 风险点：Guardian 语义漂移，导致卖出数量偏差。
  - 缓解：dual-read compare + 样本回放 + 逐标的差异日志。
- 风险点：外部订单推断误配，影响 lot 剩余量。
  - 缓解：`provisional` 标识、120 秒自动确认窗口、后续回报合并修正。
- 风险点：新旧双轨期间投影延迟，导致 UI 与策略看到不同结果。
  - 缓解：主账本优先、投影失败告警、幂等重放。
- 风险点：`stock_fills` 旧写入口未完全收口，破坏主账本一致性。
  - 缓解：实现阶段统一改造 `import/reset/cleanup/compact` 入口，并增加守卫与审计。

## 12. 里程碑与拆分（Milestones）
- M1：RFC 0007 Approved
- M2：完成 `orders / events / trade_facts / buy_lots` 主账本 MVP
- M3：完成 `lot_slices / sell_allocations`，并建立 Guardian 兼容读模型
- M4：切换 Guardian 到新读模型，保持语义不变
- M5：切换单笔止损到 `buy_lot_id`
- M6：完成外部订单推断与 120 秒自动确认
- M7：收口所有直写 `stock_fills` 路径，保留兼容投影
