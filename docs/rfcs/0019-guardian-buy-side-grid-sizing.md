# RFC 0019: Guardian 买单数量与三层价格状态机

- **状态**：Done
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-08
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）
当前目标仓库中的 Guardian 买单数量仍然沿用旧的简化规则：按 `get_trade_amount()` 取基础金额，再叠加本地 `position_pct` 与 `near_pattern:*` 的缩量规则，最后按信号价格换算整百股。该实现存在以下问题：

- Guardian 已经切到新的订单管理与仓位管理模块，但买单数量语义仍停留在旧策略层，未与新的数据边界、日志追踪和状态管理收口。
- `must_pool.initial_lot_amount` 字段已经存在，但运行时实际上未生效；首开仓仍缺少明确、稳定的金额来源。
- 旧分支 `D:\fqpack\freshquant` 中已存在 Guardian 与三层价格（`BUY-1/2/3`）结合的设计雏形，包括层级倍率和一次性生效状态，但未在主策略链路中形成完整闭环。
- 如果只迁移倍率、不迁移状态机，同一标的在短时间内重复触发深层买点会快速放大仓位，不符合 Guardian 的风险控制目标。
- 当前目标仓库对 Guardian 核心自动交易仍允许部分 legacy 回退；本次重构已明确要求 Guardian live 决策不再回退 legacy。

旧分支中与本 RFC 直接相关的来源包括：

- `D:\fqpack\freshquant\freshquant\strategy\guardian.py`
- `D:\fqpack\freshquant\freshquant\strategy\guardian_auto_open.py`
- `D:\fqpack\freshquant\freshquant\strategy\toolkit\guardian_grid_helper.py`
- `D:\fqpack\freshquant\freshquant\strategy\toolkit\grid_helper.py`
- `D:\fqpack\freshquant\freshquant\strategy\toolkit\grid_config_manager.py`
- `D:\fqpack\freshquant\freshquant\strategy\freshquant.grid_configs.json`

## 2. 目标（Goals）
- 保持 Guardian 继续作为买单数量的最终计算方，不将普通买单数量下沉到仓位管理模块。
- 将 Guardian 买单语义明确拆分为“首次新开仓”和“持仓加仓”两条规则。
- 迁移 Guardian buy-side 的三层价格配置与最小状态机，使加量买入只生效一次，避免连续快速加重仓位。
- 让 `must_pool.initial_lot_amount` 在首次新开仓时正式生效，并定义明确的默认回退规则。
- 让 Guardian buy-side 的层级价格与状态可通过现有 API/CLI 入口查看和设置。
- 让订单域完整记录 Guardian 的数量决策上下文，供后续日志管理模块复现信号、数量与状态变化过程。

## 3. 非目标（Non-Goals）
- 不迁移旧 Grid 策略的完整交易引擎，不实现 Guardian 的卖出层级价格策略。
- 不迁移旧 Grid 的 `SELL-1/2/3` 价格触发、卖出状态机和完整双向轮转。
- 不将 Guardian 的仓位管理职责重新拉回策略层；仓位准入仍由 `position_management` 负责。
- 不保留旧的 `position_pct` 缩量规则与 `near_pattern:*` 数量修正。
- 不要求首次新开仓依赖 `BUY-1` 或其他层级价格二次确认。
- 不再为 Guardian live 交易保留 legacy `stock_fills` 回退作为事实源。

## 4. 范围（Scope）
**In Scope**
- Guardian 买单数量规则重构。
- Guardian buy-side 三层价格配置模型与最小状态机。
- 旧 `grid_configs` 中 Guardian 需要的 buy-side 价格/状态迁移。
- Guardian buy-side 配置与状态的现有 API/CLI 暴露。
- 订单域与成交域对 buy-side 状态机的受理后更新、卖出成交后重置。
- 订单决策上下文透传与审计字段补齐。

**Out of Scope**
- Guardian 卖出数量计算改造。
- 仓位管理第三层级的卖出数量算法实现细节。
- 新的独立服务、独立 worker 或新的顶级模块。
- 轮询模式下的 Guardian 进场逻辑；后续仅保留事件模式。

## 5. 模块边界（Responsibilities / Boundaries）
**负责（Must）**
- `freshquant/strategy/guardian.py` 负责判断“新开仓 / 持仓加仓”路径，并调用 Guardian buy-side 状态与数量服务计算买单数量。
- Guardian buy-side 配置/状态服务负责：
  - 读取 `BUY-1/2/3`
  - 读取和维护 `buy_active`
  - 计算命中层级
  - 按“最深命中层级”返回倍率与失活层级列表
- 订单管理模块负责在**订单域受理成功后**更新 Guardian buy-side 状态。
- 成交 ingest / 对账链路负责在**卖出成交事实落地后**重置对应标的的 Guardian buy-side 状态。
- `rear.stock.routes` 与 `command.stock` 负责暴露层级价格与状态的查看、设置、重置入口。
- 订单跟踪与日志上下文负责保存 buy-side 决策细节。

**不负责（Must Not）**
- Guardian 不负责仓位状态解释，不负责最终买单准入。
- Guardian buy-side 状态机不负责卖出层级策略。
- Guardian buy-side 状态机不依赖旧 Grid 策略的完整状态机、卖出逻辑和轮询链路。
- 订单域不根据“信号出现”直接改 buy-side 状态；只能根据“受理成功”和“卖出成交”改状态。

**依赖（Depends On）**
- `freshquant/position_management/` 作为买单准入门禁。
- `freshquant/order_management/submit/` 作为订单受理边界。
- `freshquant/order_management/ingest/xt_reports.py` 作为卖出成交事实入口之一。
- `freshquant/data/astock/must_pool.py` 提供 `initial_lot_amount` 与 `lot_amount`。
- Guardian 事件模式信号输入，特别是 `signal.price`。

**禁止依赖（Must Not Depend On）**
- 不允许 Guardian live 决策继续静默回退 legacy `stock_fills`。
- 不允许 Guardian 首次新开仓依赖 tick 价格或 `BUY-1` 二次确认。
- 不允许 Guardian 买单数量继续依赖旧 `position_pct` 或 `near_pattern:*` 缩量逻辑。

## 6. 对外接口（Public API）
本 RFC 的接口范围包括稳定内部 Python API、现有 stock blueprint 下的 HTTP API，以及现有 CLI 组上的子命令扩展。

### 6.1 稳定内部 Python API
- `get_guardian_buy_grid_config(code) -> dict | None`
- `upsert_guardian_buy_grid_config(payload) -> dict`
- `get_guardian_buy_grid_state(code) -> dict`
- `set_guardian_buy_grid_state(code, buy_active, reason, actor) -> dict`
- `reset_guardian_buy_grid_state(code, reason, actor, context=None) -> dict`
- `resolve_guardian_buy_quantity(signal, holding_context) -> GuardianBuyDecision`
- `mark_guardian_buy_levels_hit(code, hit_levels, context) -> dict`

其中 `GuardianBuyDecision` 至少包含：
- `path`: `new_open | holding_add`
- `base_amount`
- `initial_amount`
- `grid_level`
- `hit_levels`
- `multiplier`
- `quantity`
- `source_price`
- `buy_prices_snapshot`
- `buy_active_before`
- `buy_active_after`

### 6.2 HTTP API
建议沿用现有 `freshquant.rear.stock.routes` blueprint，不新增独立服务。

- `GET /api/guardian_buy_grid_config?code=<code>`
- `POST /api/guardian_buy_grid_config`
- `GET /api/guardian_buy_grid_state?code=<code>`
- `POST /api/guardian_buy_grid_state`
- `POST /api/guardian_buy_grid_state/reset`

错误语义：
- 缺少 `code` 或价格字段非法：400
- `BUY-1/2/3` 顺序非法（不满足 `BUY-1 > BUY-2 > BUY-3`）：400
- 标的不存在：404
- 状态更新失败：500

### 6.3 CLI
建议在现有 `fqctl stock.*` 下扩展，不新增顶级命令组。

- `fqctl stock.guardian-grid get --code 600xxx`
- `fqctl stock.guardian-grid set --code 600xxx --buy1 ... --buy2 ... --buy3 ...`
- `fqctl stock.guardian-grid state --code 600xxx`
- `fqctl stock.guardian-grid reset --code 600xxx`
- `fqctl stock.guardian-grid activate --code 600xxx --levels 1,2`

## 7. 数据与配置（Data / Config）
### 7.1 存储位置
- 新增集合继续存放在现有业务库 `freshquant` 中。
- 不新增独立数据库；原因是本 RFC 涉及的是策略配置与运行状态，而不是新的账本域。

### 7.2 集合
- `guardian_buy_grid_configs`
- `guardian_buy_grid_states`

### 7.3 `guardian_buy_grid_configs`
关键字段建议如下：

- `code`
- `BUY-1`
- `BUY-2`
- `BUY-3`
- `enabled`
- `created_at`
- `updated_at`

说明：
- 本 RFC 不引入每标的自定义倍率；倍率固定为 Guardian 语义 `2/3/4`。
- 本 RFC 不在配置中保存 `SELL-*` 价格。

### 7.4 `guardian_buy_grid_states`
关键字段建议如下：

- `code`
- `buy_active`: `[bool, bool, bool]`
- `last_hit_level`
- `last_hit_levels`
- `last_hit_price`
- `last_hit_signal_time`
- `last_request_id`
- `last_internal_order_id`
- `last_reset_reason`
- `updated_at`
- `updated_by`

默认状态：
- `buy_active = [true, true, true]`

### 7.5 数量规则
#### 首次新开仓
- 不看层级价格。
- `quantity = floor(initial_amount / signal.price / 100) * 100`

其中：
- `initial_amount = must_pool.initial_lot_amount ?? must_pool.lot_amount ?? 150000`

#### 持仓加仓
- 使用 `signal.price` 判断命中层级。
- 命中多个层级时，取**最深命中层级**：
  - `BUY-3 > BUY-2 > BUY-1`
- 命中层级的固定倍率为：
  - `BUY-1 -> 2`
  - `BUY-2 -> 3`
  - `BUY-3 -> 4`
- `quantity = floor((base_amount * multiplier) / signal.price / 100) * 100`

其中：
- `base_amount = get_trade_amount(symbol)`

#### 无配置或未命中层级
- 按基础金额执行：
  - `quantity = floor(base_amount / signal.price / 100) * 100`

### 7.6 最小状态机
- 初始：`buy_active = [true, true, true]`
- 持仓加仓买信号：
  - 读取配置与状态
  - 计算所有命中层级
  - 取最深命中层级决定倍率
  - 记录所有命中层级
- 订单域受理成功后：
  - 将所有命中的层级失活
  - 例如命中 `BUY-3` 时，失活 `BUY-1/2/3`
- 卖出成交事实落地后：
  - 重置 `buy_active = [true, true, true]`
- 手工修改 `BUY-1/2/3` 配置后：
  - 默认重置 `buy_active = [true, true, true]`

## 8. 破坏性变更（Breaking Changes）
本 RFC 落地后将引入以下行为语义变化；实现合并时必须同步更新 `docs/migration/breaking-changes.md`。

- Guardian 买单数量不再使用旧的 `position_pct` 缩量规则。
- Guardian 买单数量不再使用 `near_pattern:*` 数量修正。
- 首次新开仓不再依赖 `BUY-1` 二次确认。
- `must_pool.initial_lot_amount` 从“仅存储字段”变为“正式生效字段”。
- Guardian 持仓加仓将引入一次性生效的 buy-side 层级状态机。
- Guardian 配置与状态将新增可写 API/CLI 暴露面。

### 迁移步骤
1. 新增 Guardian buy-side 配置与状态集合。
2. 提供旧 buy-side 配置迁移脚本，将旧 `grid_configs` 中相关标的的 `BUY-1/2/3` 与 `buy_active` 迁入新集合。
3. 新集合中缺少配置的标的，按“无配置时基础金额执行”处理。
4. Guardian 主流程切换到新 buy-side 配置与状态服务。
5. 订单域受理成功后接入 buy-side 状态失活更新。
6. 卖出成交 ingest / 对账链路接入 buy-side 状态重置。

### 回滚方案
- 回滚到“基础金额买入 + 无 buy-side 状态机”逻辑。
- 保留 Guardian buy-side 配置与状态数据，不删除历史记录，便于排障与重放。
- 保留订单上下文中的 buy-side 决策日志，以便比较回滚前后的策略差异。

## 9. 迁移映射（From `D:\fqpack\freshquant`）
- `freshquant\strategy\guardian.py`
  - 旧 Guardian 买单数量逻辑
  - 迁移到目标仓 `freshquant/strategy/guardian.py` 的新数量决策链路
- `freshquant\strategy\guardian_auto_open.py`
  - 旧自动首开仓金额与 BUY-1 二次确认逻辑
  - 迁移时保留“首开仓单独规则”的边界，但移除 BUY-1 依赖
- `freshquant\strategy\toolkit\guardian_grid_helper.py`
  - 旧 `BUY-1/2/3 -> 2/3/4` 倍率与层级判定语义
  - 迁移到 Guardian buy-side 配置与状态服务
- `freshquant\strategy\toolkit\grid_helper.py`
  - 旧层级顺序与价格判断辅助
  - 仅保留 buy-side 相关能力，不迁移 sell-side 逻辑
- `freshquant\strategy\toolkit\grid_config_manager.py`
  - 旧 `BUY-1/2/3` 与 `buy_active` 配置/状态读取
  - 迁移到 Guardian 专用集合与服务，不直接复用旧 Grid 全语义
- `freshquant\strategy\freshquant.grid_configs.json`
  - 旧层级价格初始化来源
  - 作为一次性迁移输入，不作为新运行时真相源

## 10. 测试与验收（Acceptance Criteria）
- [ ] 首次新开仓在 `must_pool` 中存在 `initial_lot_amount` 时，按该值计算数量。
- [ ] 首次新开仓在缺少 `initial_lot_amount` 时，回退 `lot_amount`；两者都缺失时回退 `150000`。
- [ ] 持仓加仓命中 `BUY-1/2/3` 时，分别按 `2/3/4` 倍计算数量。
- [ ] 当 `signal.price` 同时命中多个层级时，取最深命中层级作为倍率来源。
- [ ] 当命中 `BUY-2` 时，受理成功后会失活 `BUY-1/2`；命中 `BUY-3` 时会失活 `BUY-1/2/3`。
- [ ] 同一层级在失活后，后续买信号不会再次触发该层级加量。
- [ ] 任意卖出成交事实落地后，对应标的的 `buy_active` 会重置为 `[true, true, true]`。
- [ ] 没有 buy-side 三层价格配置时，Guardian 仍可按基础金额执行买单。
- [ ] Guardian 订单上下文会记录 `grid_level`、`hit_levels`、`multiplier`、`source_price`、`buy_prices_snapshot`、`buy_active_before/after`、`path`。
- [ ] 配置 API/CLI 支持查看、设置、重置 buy-side 价格与状态。
- [ ] Guardian live 决策不再回退 legacy `stock_fills` 作为数量事实源。

## 11. 风险与回滚（Risks / Rollback）
- 风险点：受理成功后状态未更新，导致同层级重复加量。
  - 缓解：将状态更新严格绑定到订单域受理成功事件，并补回归测试。
- 风险点：卖出成交未触发状态重置，导致后续正常加仓被错误抑制。
  - 缓解：在 XT 成交 ingest 与手工/对账卖出路径统一接入状态重置。
- 风险点：手工修改层级价格后沿用旧状态，导致配置和状态脱节。
  - 缓解：手工更新价格默认重置 `buy_active`，并记录审计日志。
- 风险点：迁移旧 `grid_configs` 时混入 sell-side 或旧 Grid 语义。
  - 缓解：迁移脚本只抽取 `BUY-1/2/3` 与 `buy_active`，其余字段忽略。

## 12. 里程碑与拆分（Milestones）
- M1：RFC 0019 评审通过
- M2：Guardian buy-side 配置/状态集合与服务落地
- M3：旧 `grid_configs` buy-side 配置迁移脚本落地
- M4：Guardian 主买单数量链路切换到新 buy-side 规则
- M5：订单受理成功后的状态失活更新与卖出成交后的状态重置接入
- M6：API/CLI 暴露、日志上下文补齐与测试完成
