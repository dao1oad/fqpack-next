# 双账本最终实施方案 v4（固定价触发底仓 + Guardian 做T，金字塔保留）

> 日期：2026-08-10 ｜ v2 变更：3 条买入线改为"固定价格触发补仓进底仓"（与 3 条止盈线同构：到价触发一次、触发即关、止盈后重激活）｜ v3 变更：R 统一按**占用取大**（`cap − max(D + C, MV) − 在途`，更保守）；手动/外部卖单分摊顺序细化为"① T 盈利低成本 → ② 底仓 → ③ T 非盈利兜底"；min_buy_amount 恢复为全局参数；修复 stoploss 双集合、读取侧缺失按 base 两个真实逻辑坑 ｜ **v4 变更**：状态机简化为**对称阶梯**（买入线触发 → 关该档及以上买入线 + 全开止盈档；止盈成交 → 关该档及以下止盈档 + 全开买入线；触发即关防重复、成交阶梯重算、零成交终态重开）；upsert 改为**整份读改写**，废除"未显式传字段保留现值"契约；做T盈利判定统一谓词 **`现价 ≥ guardian_price × (1 + percent/100)`**（逐 slice，percent = `guardian.stock.threshold.percent`）；破线区冷却改挂 **T 侧 `buy:<code>`**（两套系统互不卡冷却）；买入线 universe 统一为 **持仓 ∩ 有 buy grid 配置**；**底仓不依赖 slice 粒度**（按止盈线整仓卖出）；回填 = **flatten 幂等重建 + 存量止盈档批量激活**（不导出备份）；新增 **TP1 > BUY-1 配置校验** ｜ 关联：GitHub Issue #549 ｜ 分支：`codex/dual-ledger-base-t`
> 状态：**v4.1（2026-08-10 评审修正版，决策项已全部定稿）**——在 v4（用户确认全部决策项）基础上按"本地评审 + Devin 单轮评审"落实 3 项阻塞修正与补充：**R1 部署顺序**（存量止盈激活移到新代码部署并重启之后、非交易时段执行，禁止先激活后部署，防旧代码按全仓基数立即卖出）；**R2 D/C 口径**（**最简实现：D/C = 剩余股数 × 当前市场价，用户 2026-08-10 确认**，不用成本价聚合、不加 cost_price 字段）；**R3 状态写回**（单文档原子 `$set` + 字段级归属 + 事件幂等 + `find_one_and_update` 条件更新，废除 read→整份写回）；**§14 文件清单补充**（`tpsl/takeprofit_quantity.py`、`tpsl/takeprofit_service.py`、`tpsl/pools.py`、零成交终态钩子落点、consumer 插入点）；**§5 措辞修正**（`_build_guardian_slice_next_level_threshold`/`_get_guardian_buy_slice_grid_interval` 仅 guardian.py 内部引用，保留 `freshquant/data/astock/holding.py` 的 `_query_grid_interval` 本体）；**manual 加仓默认 base（用户 2026-08-10 确认：手动加仓算底仓）**。v4 的 D1–D7/M1–M4/四段走廊决策不变（Issue #549 已同步；trading-guide 已按 v4 重做用于可视化确认）。**注：评审阻塞项统一编号 R1/R2/R3，与 §18.2 代码质量编号（B1/A3、B3、B4）区分，避免混淆。**

## 1. 背景与目标

两套并行系统：

1. **固定价格触发机制（底仓 base）**：3 条止盈线 TP1/2/3 + 3 条买入线 BUY-1/2/3，采用**对称阶梯状态机**（§4.1）：
   - 卖出：实时价格触及 TP-N → **触发即关闭该档**（防重复卖单）→ **卖出成交后**关闭该档及以下全部止盈档、并重新激活全部买入线；
   - 买入：实时价格触及 BUY-N → 买入该线剩余可买额度 R_N = cap_N − max(D + C, MV) − 在途买单（占用取大），**计入底仓**；**触发即关闭该档及以上全部买入线、并激活全部止盈档**；任一买入/止盈事件按阶梯规则重算状态；
   - 破线区（p ≤ BUY-3）：**做T深档**，总仓位限制 = `global_cap`，可买量 R = global_cap − max(D + C, MV) − 在途，每次触发买入 B = R × 1/2（1/2 极限划分），直到 `B < min_buy_amount` 或不足一手停止；与 BUY-3 触线（base，一次性买满 cap3 − max(D + C, MV) − 在途）区分开。
2. **Guardian 做T机制（t，命名 Garden）**：信号触发；买入过 threshold 价格闸门、数量按金字塔走廊（v1 保留）；卖出沿用逐 slice 网格阈值并受 mount 约束；买卖均计入 T 账本。

目标：把"首次开仓/加仓混账 + 网格档位锚劫持买卖两侧 + TPSL 与 Guardian 对同一批持仓重复覆盖"拆开，两套账本并行叠加。

## 2. 术语（统一口径）

| 术语 | 定义 |
| --- | --- |
| `p` | 价格（元/股） |
| 成本价 | 元/股（价格，不是仓位） |
| `Q` | 仓位/股数（股） |
| `cap_i` | 总资金额度上限（元，**含底仓**）= 现有 `max_position_amounts`（cap1 ≤ cap2 ≤ cap3） |
| `global_cap` | 全局单标的上限 = `resolve_single_symbol_position_limit` |
| `D` | 底仓占用金额（元）= Σ(base 剩余股数 × 当前市场价 p)，**最简实现（v4.1 追加，用户确认"数量×当前市场价"；不用成本价聚合、不加 cost_price 字段），部分卖出自动释放** |
| `C` | T 占用金额（元）= Σ(t 剩余股数 × 当前市场价 p)，**最简实现（v4.1 追加，同上）** |
| `MV` | 当前市值（元）= 该 symbol 持仓实时市值（position snapshot `market_value`） |
| `R` | 剩余可买金额（元）= `cap − max(D + C, MV) − 在途买单金额`（**占用取大，更保守**） |
| `B` | 本次买入金额（元） |
| 在途买单 | 该 symbol 未完结 buy broker orders（state ∈ ACCEPTED/QUEUED/SUBMITTING/SUBMITTED/PARTIAL_FILLED/BROKER_BYPASSED/CANCEL_REQUESTED/INFERRED_PENDING）的 Σ(requested_quantity − filled_quantity) × price |
| `mount` | 最小卖出金额（元）= 复用 `get_trade_amount(symbol)`（默认 `guardian.stock.lot_amount`=50000，允许 per-instrument 覆盖） |
| `min_buy_amount` | 最小买入金额（元）= 新增全局参数 `guardian.stock.min_buy_amount`，默认 10000、下限 10000（低于下限钳制）；**所有买入路径（买入线 / 破线区 / 做T）通用**，`B < min_buy_amount → 不买`（不消耗冷却） |
| `guardian_price` | T slice 网格阶梯价（元/股）：arranger 首片=现价、后续 ×grid_interval 递增，近似各片买入成本 |
| `percent` | 做T盈利/卖出阈值百分比 = `guardian.stock.threshold.percent`（默认 1%，`instrument_strategy.threshold` 可覆盖） |
| 做T盈利卖出条件 | 逐 slice 独立判定：`现价 ≥ guardian_price × (1 + percent/100)`（percent 模式 = `build_slice_threshold` 口径）；**统一复用 `evaluate_guardian_sell_slices`，不新增 `is_slice_profitable` 重复实现（B4）**，§6.1 分摊与 §6.2 网格卖出共用同一判定 |

## 3. 双账本模型

- `om_position_entries` / `om_entry_slices` 增加 `position_type: "base" | "t"`（逻辑拆分，不物理拆集合）。
- **底仓定义**：① 首次建仓（must_pool 首开或手动首开，持仓从无到有）② buy 线触发买入；其余（Guardian 信号加仓）→ t。
- 打标规则（按来源，运行时 ingest 从 order request `strategy_context.buy_ledger` 读取；已确认 `strategy_context` 随请求持久化）：
  - 无 open entry（持仓 0→有，含 must_pool 与手动首开）→ base；
  - `buy_ledger == "base_line"`（buy 线触发）→ base；
  - 其余 → t；
  - **手动加仓（manual source，非首开，无 buy_ledger）→ base（v4.1：Devin 建议 + 用户 2026-08-10 确认"手动加仓算底仓"，已定稿）**；
  - V1 buy_lot 路径不标记，默认按 base（边界，Issue 注明）。
- **slice 粒度（v4）**：`position_type` 在 slice 上**仅 T 账本需要**（T 卖出按 slice 网格阈值逐片判定）；**底仓按止盈线整仓比例卖出，不依赖 slice 粒度**——base slice 缺失/未标记一律按 base（读取侧 `position_type != "t"` 即 base），**不做 entry/slice 一致性校验**（base 不分片语义，见 §4.3）。
- **读取侧统一口径**：`position_type` 缺失/未知一律按 base 处理（`position_type != "t"` 即 base），消除"回填后、部署前旧代码写入无标记 slice"的窗口期两账本都不可见问题。
- 重建/对账：`build_flatten_from_positions`（flatten 拍平）→ base；`_reconcile_positions_against_xt_positions`（auto-open）→ base；`build_from_truth` 逐笔重建**保留已有 `position_type`**，**缺失/无法判断 → base**（做T由运行时 ingest 自动打标，重建兜底一律按底仓计算）。
- 手动网格重建（`manual/service.py::reset_symbol_lots` 重建 manual_locked entry/slice）：显式打标 `position_type=base`（整仓重建，默认 base）。
- **切换完成前的账单重建一律按 flatten 口径**：整仓按成本价生成一条 base 买入 entry（即 `build_flatten_from_positions` 语义），不做逐笔区分；切换完成后才由运行时 ingest 逐笔打标。
- 历史回填：`script/maintenance/backfill_position_type.py`（dry-run + execute），已有标记保留、缺失/无法判断 → base；**execute 只重建 `position_type`，止盈档批量激活为部署后的独立步骤 `--activate-takeprofit`（v4.1 R1，见 §11/§13）**，消除"存量持仓止盈永不激活"死区且不触发旧代码超卖；回填前未标记存量默认按 base。

## 4. 固定价格触发机制（底仓账本）

### 4.1 买入线（新增执行器，挂 TPSL tick worker）

- 触发：实时价格（`bid1`，无则 `last`）≤ `BUY-N`，且 `buy_enabled[N]=true`，且该线 armed，且当前 symbol 存在 open 持仓（**空仓首开仍走 must_pool/手动**，买入线只补仓不建仓）。
- 执行器 universe（**handle_tick 维护双集合**）：TP/SL 评估仍用旧 `load_active_tpsl_codes`；buy 线评估用**扩展集 = 当前持仓 ∩ 有 `guardian_buy_grid_configs`**（"没配就不用"）；**不得把扩展集并入 TP/SL 集合**——`evaluate_stoploss` 依赖 `must_pool.stop_loss_price`（不依赖 TPSL profile），扩集合会让"仅配 buy 线且 must_pool 带止损价"的标的被全仓止损误触发。**注：止损功能作为本方案需求保持关闭**（订单止损与全仓止损均不启用，见 §16）；双集合隔离仍作为防御性实现约束保留，若未来启用止损须先完成隔离评审。
- 数量：`R_N = cap_N − max(D + C, MV) − 在途买单金额`（占用取大）；`B = R_N`；`B < min_buy_amount → 不买`（不消耗冷却）；`Q = floor(B/p/100)×100`；`Q < 100 → 不买`。
- **对称阶梯状态机（v4 简化，事件触发式，无轮询）**：
  - **事件 B（买入线触发，提交买单时）**：关闭 `BUY-N` **及所有价格高于 BUY-N 的买入线**（即 BUY-1..BUY-N，价格 ≥ 触发价的买入线全部关闭——价格只回落不回涨，更高档已无触发意义）；同时**全开止盈档**（TP1/2/3 全 armed，底仓增加 → 准备卖出）；
  - **事件 A（止盈卖出成交）**：关闭 `TP-1..TP-N`（该档及以下止盈档）；同时**全开买入线**（底仓减少 → 释放补仓额度）；
  - 时点：买入线在**触发提交时**关闭（防同档重复触发重复下单）；止盈档在**触发提交时关闭该档**（防重复卖单，见 §4.3），**成交时做阶梯重算**（关 ≤N + 全开买入线，用户确认"按成交重激活"）；重激活后**不当场评估买入线，等下一 tick**；
  - **零成交终态**：买单/卖单被撤或失效（终态非 FILLED）→ 重开对应档位（买单重开该买入线；卖单重开该止盈档），避免单子没成但状态永久丢失；
  - 状态写回（v4.1，R3 修正）：**单文档原子 `$set` + 字段级归属 + 事件幂等**。废除 v3"未显式传字段保留现值"契约，也**不做 read→整份写回**——双进程（tpsl tick worker 与 XT ingest）各自 read 旧值后整份覆盖会互相丢失事件（lost update）。每个事件**只写自己负责的字段**：买入线事件只 `$set` `buy_line_armed`（联动全开止盈时同一次 `$set` 同时写 `armed_levels`——Mongo 单文档更新原子）；止盈事件只 `$set` `armed_levels`（联动全开买入线同理）；关键联动事件用 `find_one_and_update` 带条件（匹配期望现值，冲突则本轮放弃、下一 tick 重试）；事件按 `broker_order_id`/`intent_id` 幂等（同一订单只触发一次阶梯重算/重开）。`_normalize_state` 缺省含 `buy_line_armed=[true,true,true]`；
  - 初始 arming：买入线默认全 armed；TP 档默认全 False，由**任意 base 买入事件**（首开、买入线触发或**手动加仓**）全开（v4.1 统一：manual 加仓→base 后同样全开止盈档）；**存量持仓由部署后 `--activate-takeprofit` 一次性批量激活**（§11/§13），避免"止盈永不激活"死区；
  - **配置校验（fail-closed + 告警）**：`TP1 > BUY-1`（且 BUY-1 > BUY-2 > BUY-3、TP 档递增、caps 递增）——配置倒挂会在同价位止盈/补仓洗单；
  - `upsert_state` 改为**固定键字段级 `$set`**（v4.1 R3）：缺省态（`_normalize_state`）包含 `buy_line_armed`（缺省全 true）与 `armed_levels`；rear `guardian_buy_grid_state` GET/POST/reset 需**暴露并保留**该两字段，reset 语义 = 回缺省态（安全方向：最坏多买一次，受 R/冷却/min_buy_amount 约束）。
- 冷却：独立 key `base_buy:<code>`（15 分钟），**不与 Guardian `buy:<code>` 共用**（两套系统互不卡冷却）；未达数量不消耗冷却；**破线区做T用 T 侧 `buy:<code>`**（§4.2/§5），与买入线冷却天然隔离。
- 提交：复用 `submit_guardian_order` 包装器（内部走 `OrderSubmitService`，`source="strategy"` 自动过仓位管理闸门），`strategy_context` 带 `buy_ledger="base_line"` + `guardian_buy_grid` 审计字段，**不带 `hit_levels`**（`_mark_guardian_buy_grid_after_accept` 天然跳过，不污染旧 `buy_active` 审计态）；
- **占用取大（更保守）**：R 统一按 `cap − max(D + C, MV) − 在途` 计算（等效于"剩余取小、谁紧听谁"）；市值口径不再需要额外 min 折算，PM 市值口径闸门仍保留为第二道关卡（双保险）；深跌反弹段市值已顶上限 → 单被拒，属保守行为，显式声明为运行语义，不作为 bug；
- **MV 缺失 → fail-closed 不买**：`MV` 读取失败时沿用 `_load_position_capacity` 缺失即 skip 的行为，**禁止退化为 D+C 单边口径**（否则占用取大失去意义）；
- **`_prepare_guardian_buy_orders` 必须按 `buy_ledger` 跳过 base_line 在途买单**（它现状会取消一切在途买单，若不跳过会误杀 buy 线补仓单）；buy 线评估器自身不复用 `_prepare_guardian_buy_orders`。
- 配置缺失 / BUY 价非法 / caps 非法 → 跳过（fail-closed）。
- 状态存储：`guardian_buy_grid_states` 新增 `buy_line_armed: [bool×3]`（默认全 true）；**不改变现有 `buy_active` 审计语义**（`reset_after_sell_trade` 仍只作用于 `buy_active`）。

### 4.2 破线区（p ≤ BUY-3，做T深档）

- **归属：T 账本**（跌破 BUY-3 后做T继续，不停止）；
- 可买量：`R = global_cap − max(D + C, MV) − 在途`（占用取大）；**破线区总仓位限制 = `global_cap`**（跌破 BUY-3 之后做T的总仓位限制）；
- 每次触发买入：`B = R × 1/2`（1/2 极限划分）；成交后 R 更新，下次再买剩余的一半，收敛到 `global_cap`；
- 终止：`B < min_buy_amount`（不够最低买入金额放弃，不消耗冷却）或 `Q < 100`（不足一手）；
- 触发频率：受 **T 侧 `buy:<code>` 冷却**约束（v4 变更：破线区与普通做T同属 T 账本、同在 Guardian worker，共用 T 侧冷却，保持"两套系统互不卡冷却"承诺）；几何收敛 4–5 次后单次金额 < 5% 残差；
- 与 BUY-3 触线（base，一次性买满 `cap3 − max(D + C, MV) − 在途`）并存并**区分开**：BUY-3 触线（base）用 cap3；破线区做T 用 global_cap；两者共用 R 互斥 + 在途扣减 + 各自冷却键，**先触发者消耗额度，后触发者买剩余部分**；同 tick 两路并存时 BUY-3 触线（base 补仓）优先，破线区随后按剩余额度收敛（由 R 互斥 + 在途扣减天然实现，无需额外锁）。

### 4.3 卖出线（TPSL，复用现状 + 双账本改造）

- `evaluate_takeprofit` 只扫 `position_type=="base"` 的 slices；**比例基数 = 底仓总股数（Σ base slices remaining）**；
- base 过滤在取 `list_open_entry_slices_compat` 之后、传入 `resolve_takeprofit_sell_quantity` 之前执行一次，quantity 与 breakdown（slice_details）必须共用同一份过滤结果（只改 total 参数不过滤 slices 不自洽）。
- 比例沿用 L1=1/3、L2=1/2、L3=1（按当前底仓总量）；`armed_levels` 阶梯状态机（v4）：**触发提交时关闭该档**（防重复卖单）→ **成交时关闭该档及以下全部止盈档 + 全开买入线** → **零成交终态重开该档**；
- **`total_position_quantity` 必须从券商全仓 `position_volumes["volume"]` 改为 Σ base remaining**（否则 L1 会按全仓 1/3 超卖底仓；例 base 900+T 300 → L1 卖 400 而非 300）；`can_use_volume` 仍用券商值。
- **rearm 门控（v4.1 统一口径）**：仅 base 买入事件（首开 + buy 线触发 + **手动加仓**）执行"全开止盈档"——与 §4.1"任意 base 买入事件全开止盈"保持一致；**T 买入不触发状态机**（Guardian 做T与固定触发机制解耦，不会反复重置止盈阶梯，破坏"3 次清空底仓"）。

## 5. Guardian 做T账本：买入

- **门槛**：`price ≤ bot_river_price`（threshold 配置 percent/ATR）；基准 = 最近一笔 execution fill 成交价；无成交记录 → 全部持仓（base+T 所有 open entries 按剩余股数加权）平均成本价；无 execution fill 且无 OM entries → 兜底 `xt_positions.avg_price`；三者皆无 → 不买。
- 无 execution fill 基准时无 fill_time → **跳过时序校验**（timing_check 仅在 fill_time 存在时执行）。
- **删除"情况2"**（`guardian_arranged_fill_fallback → guardian_slice_next_level`）回退；删除 `_build_guardian_slice_next_level_threshold` / `_get_guardian_buy_slice_grid_interval`（v4.1 核实：这两个函数**仅 `guardian.py` 内部（1635/1689/1706）与测试引用**，可安全删除）及 `guardian.py` 中 `_query_grid_interval` 导入；**保留 `freshquant/data/astock/holding.py` 的 `_query_grid_interval` 函数本体**——`xt_reports.py:733-737`、`order_management/manual/service.py:485-488` 的调用方依赖的是 holding 版函数，勿误删。
- **数量：金字塔走廊保留（v1 §5.2，四段走廊，v4 明确）**：
  - 做T区域 = **四段走廊**（价格自上而下单调穿越）：
    1. **回补走廊** `(最近止盈线, BUY-1]`：上界 U = 最近一条高于当前价的止盈线（TP3/TP2/TP1 动态取最近），下界固定 = BUY-1，cap = cap1——价格从止盈区回落、跌破止盈线后开始做T；
    2. **[BUY-1, BUY-2]**：上界 = BUY-1，下界 = BUY-2，cap = cap2；
    3. **[BUY-2, BUY-3]**：上界 = BUY-2，下界 = BUY-3，cap = cap3；
    4. **破线区** `p ≤ BUY-3`：无上下界，总仓位限制 = `global_cap`，1/2 收敛（§4.2）；
  - `t = (上界 − p)/(上界 − 下界)`；`R = cap − max(D + C, MV) − 在途`（占用取大）；`B = R × t²`；`Q = floor(B/p/100)×100`；
  - `B < min_buy_amount → 不买`（不消耗冷却）；**min 只约束取整前 B**（B≥min 后整手取整，Q×p 可能 <min，允许）；
  - **`p > 上界`（含 p > TP3 不买入区，t<0）→ 不做T买入**，等待价格回落进走廊（v4 显式边界）；
  - `p ≤ BUY-3`：T 侧**继续买入**（`BUY-3_BELOW` 分支保留，按 §4.2 破线区规则：R=global_cap 基数、1/2 收敛、min 终止、**冷却用 `buy:<code>`**）。
- **边界归属**：`t < 1` → T（信号触发）；`t = 1`（p 触及 BUY-N）→ 归 buy 线触发的 base 补仓，T 侧不重复买入（R 互斥 + 在途扣减保证，不再需要"金字塔终点归属"裁决）。

## 6. Guardian 做T账本：卖出（同 v1，盈利判定统一）

1. 只扫描 T slices（`position_type=="t"`，不动底仓）；
2. 逐 slice 卖出条件 = **统一盈利判定（v4.1 命名：复用 `evaluate_guardian_sell_slices`，不新增 `is_slice_profitable`）：`price ≥ guardian_price × (1 + percent/100)`**（percent 来自现有 `guardian.stock.threshold.percent`，默认 1%，逐标的 `instrument_strategy.threshold` 可覆盖）；§6.1 分摊与 §6.2 网格卖出共用同一判定，避免两处口径漂移；
3. mount 过滤：可卖金额 = Σ(可卖 slice 股数 × 当前价)；可卖金额 < mount → 本次不卖，可卖 slices 保留，不消耗 `sell:<code>` 冷却；
4. 卖出总量 = 底仓 TPSL 卖出 + 做T卖出叠加；`can_use_volume` 全仓约束不变。

- **手动/外部卖单（无 source plan）分摊顺序**（按用户确认）：
  1. 先分摊到 **T 账本中盈利且成本低**的 slices（**盈利判定 = 该外部卖单 `avg_filled_price` ≥ `guardian_price × (1 + percent/100)`**——用卖单成交价而非 ingest 时点现价，避免时点漂移；按 `guardian_price` 升序 = 成本低优先）；
  2. T 中无盈利切片可抵扣（或扣完不够）→ **抵扣底仓** slices（`guardian_price` 升序，成本低优先）；
  3. 仍不够 → 剩余 T 非盈利 slices（`guardian_price` 升序）兜底，保证卖单可成交；
  4. 三段分桶排序实现（不能复用单一 stable order）；
  5. `om_exit_allocations` 记录每笔被扣 slice 的 `position_type`，便于事后审计账本漂移；
  6. 与有 source plan 的卖单叠加时可能触发 `SellAllocationPlanExhaustedError`：现有预校验 fail-closed 已保证不半写账本，记 rejection + 告警 + 人工对账。

## 7. 容量与风控

- `R = cap − max(D + C, MV) − 在途买单`（占用取大、更保守；base 触线与 T 共用同一互斥口径，防同刻双买）；
- **双进程残余窗口**：T 信号 worker 与 tpsl tick worker 是不同进程，同刻可能读到相同在途集合各自下单；双单之和 ≤ 2R，且被 PM 市值口径闸门兜底，风险有限；**定稿：提交侧做一次在途复核**（buy 线提交前用 `list_broker_orders` 复核，超 cap 放弃；落点见 §14 #7），不采用共用冷却键（与 §4.1 独立冷却承诺矛盾）；check-then-submit 非原子，残余 ≤2R 由 PM 闸门兜底，与本节声明一致；
- 手动/外部卖单（无 source plan）fallback 分摊顺序 = **① T 盈利低成本切片（卖单 `avg_filled_price` ≥ `guardian_price × (1+percent/100)`）→ ② 底仓（成本低优先）→ ③ T 非盈利切片兜底**；`om_exit_allocations` 记录被扣 slice 的 `position_type`；
- `D/C = Σ(该账本剩余股数 × 当前市场价 p)`（**v4.1 追加，用户 2026-08-10 确认：最简实现，不用成本价聚合、不加 cost_price 字段**）。与 `MV`（券商快照市值）的关系：D/C 用实时价、MV 用快照，`max(D+C, MV)` 基本以市值为准（快照滞后时取实时值更紧），"占用取大"的保守性主要由**在途扣减 + PM 市值闸门**承载；**账本股数与券商股数漂移时（OM 少记/漏记），MV 更大即兜住（保留 max 的价值）**；剩余股数随部分卖出/分摊自动减少，额度自动释放；实施时对"部分成交、手动 reset_symbol_lots 整仓重建"两条扣减路径补测试，确保剩余股数始终同步；
- 底仓首开只受 `global_cap` 约束（`build_new_open_decision` 去掉三线 cap 的行为变更需落实），不受三条线 cap 约束；
- 整手取整；`Q < 100` 不买；配置缺失 fail-closed；
- 破线区（做T深档）：**总仓位限制 = `global_cap`**、R=global_cap 基数、1/2 极限收敛 + `min_buy_amount` 终止；BUY-3 触线（base）用 cap3，两条线区分开；
- **配置校验**：`TP1 > BUY-1`（且买入线/止盈线各自严格单调）fail-closed + 告警，防同价洗单；
- Stoploss 保持现状（覆盖全部），V1 buy_lot 不标记（默认 base）；
- 统一口径：所有买入路径 R 均为 `cap − max(D + C, MV) − 在途`（占用取大）；PM 市值口径闸门保留为第二道关卡（双保险），文档注明。

## 8. 配置清单

| 配置 | 来源 | 默认 | 用途 |
| --- | --- | --- | --- |
| `position_type` | 数据字段（非配置） | base/t | 双账本 |
| `BUY-1/2/3` + `buy_enabled` + `max_position_amounts` | 现有 `guardian_buy_grid_configs` | — | 买入线触发价 + 各线 cap |
| `global_cap` | 现有 position management 配置（`single_symbol_position_limit`） | — | 首开上限、破线区 1/2 基数 |
| `percent` | 现有 `guardian.stock.threshold` / `instrument_strategy.threshold` | 1% | 做T买入门槛、做T卖出/盈利阈值（复用 `evaluate_guardian_sell_slices`） |
| `lot_amount` | 现有 `guardian.stock.lot_amount`（可 per-instrument 覆盖） | 50000 | 卖出 mount |
| `min_buy_amount`（新增全局） | `params.guardian.stock.min_buy_amount` | 10000（下限 10000） | 所有买入路径的最小买入金额门槛 |
| `TP1/2/3` | 现有 TPSL profile（tiers + `armed_levels` state） | — | 底仓卖出线（触发即关/成交阶梯重算/零成交重开） |
| `buy_line_armed`（新增状态） | `guardian_buy_grid_states` | [true,true,true] | 买入线触发/重激活（对称阶梯状态机） |
| `TP1 > BUY-1` 校验 | 配置校验（启动/变更时） | fail-closed + 告警 | 防同价洗单 |

## 9. API 契约（同 v1）

| 接口 | 新增字段 |
| --- | --- |
| `GET /api/stock/get_stock_position_list` | 每行 `base_quantity / base_amount / t_quantity / t_amount`（route 侧 join OM ledger；当前数据源为 XT positions） |
| `GET /api/position-review/symbols/<symbol>` | entries/slices 带 `position_type`；`ledger` 汇总（base/t 数量与金额）；T 每笔 `sell_eligible / eligible_amount`；`min_sell_amount`（mount）；底仓 tiers 状态 |

## 10. 前端设计（P0 同 v1）

设计原则：总仓 = 底仓 + 做T 的"叠加"可视化；色彩语义：底仓=靛蓝（#6366F1）、做T=琥珀（#F59E0B）。

1. **StockPositionList 重构**：表格列 = 品种/名称/总股数/总金额/底仓(股·额)/做T(股·额)/总盈亏；展开行为双账本明细卡。
2. **PositionReview 重构**：顶部汇总条；Tab：全部/底仓/做T；做T Tab 每笔订单一行（可卖高亮）+ mount 进度；底仓 Tab 显示止盈档状态。
3. API 层 mjs 透传新字段；沿用 `pollingNormal` 轮询。

## 11. 历史回填

`script/maintenance/backfill_position_type.py`：
- dry-run 输出统计，execute 才写库；
- 规则：**已有 `position_type` 保留不覆盖**；缺失/无法判断 → base；同步更新对应 slices；
- **实现 = 所有持仓按 flatten 语义重建一次账本（每持仓按整仓成本价生成一条 base 买入 entry/slice），幂等可重跑**（用户确认：不过度设计，不导出备份；真实回滚 = 回退代码，旧代码忽略新字段）；
- **止盈档批量激活为独立步骤（v4.1，R1 修正）**：回填 execute **只重建 `position_type`**，不再附带激活；存量止盈档批量激活（`armed_levels` 全 True）改由**独立命令（`backfill_position_type.py --activate-takeprofit`）在新代码部署并重启之后、非交易时段执行**——消除"存量持仓止盈永不激活"死区（v4，Devin H2），同时避免"先激活后部署"窗口期旧代码按全仓基数立即卖出（见 §13/§17）；**该命令天然幂等（置 armed 全 True），可中断重跑**；
- 回填完成后校验：每个 symbol 至少一个 base（如有持仓）、Σslices 守恒不变；
- **已知降级**：重建/回填兜底一律按 base——做T仓位在重建后可能被标为 base（由 TPSL 三条线卖出而非网格），属用户接受的保守语义；正常运行期间做T由运行时 ingest 自动打标，不受影响。

## 12. 测试面

- `test_guardian_buy_grid.py`：**对称阶梯状态机**——买入线触发关 BUY-N 及以上 + 全开止盈档；止盈成交关 TP-N 及以下 + 全开买入线；触发即关（重复触发不重复下单）；零成交终态重开对应档位；重激活后不当场评估（下一 tick 才触发）；`upsert_state` **字段级原子 `$set` + `find_one_and_update` 条件更新 + 事件幂等（同订单不重复重算）+ 双进程交错写 lost update 防护**；`_normalize_state` 缺省态（`buy_line_armed=[true,true,true]`）；`build_base_line_decision`（BUY-1/2/3、R=cap−max(D+C,MV)−在途、整手、buy_enabled、配置缺失 fail-closed、空仓不触发）；破线区 1/2（**global_cap 基数**、min 终止、**冷却用 `buy:<code>`**）；**TP1 > BUY-1 校验 fail-closed + 告警**；
- `test_guardian_strategy.py`：门槛基准（execution fill / 平均成本 / xt avg 兜底）；删 slice_next_level；T 买入金字塔保留（含 **p > 上界 → 不买**）；卖出只扫 T、**统一判定复用 `evaluate_guardian_sell_slices`（≥、percent/100，无重复实现 B4）**、mount 过滤与冷却不消耗；
- `test_order_management_xt_ingest.py`：`buy_ledger` 打标（base_line→base、首开→base、**手动加仓→base（v4.1 用户确认）**、Guardian→t、缺失回退）；**手动/外部卖单分摊 ① 盈利判定用卖单 avg_filled_price**；
- `test_tpsl_*`：只扫 base、`total_position_quantity`=Σbase remaining、**TP 触发即关/成交阶梯重算/零成交重开（按订单幂等）**、rearm 仅 base 买入（首开 + buy 线触发 + **手动加仓**，T 买入不触发状态机——断言 manual 加仓后止盈档全开）；**consumer 双集合：buy 线评估插入点在 TP 评估之前**（现 `handle_tick` TP 命中即 return；TP1 > BUY-1 价格区间不相交，同 tick 双命中不可能，先评估先提交无冲突）；
- 新增 `test_base_buy_line`：tick 触发、冷却 key（`base_buy:<code>` vs `buy:<code>` 隔离）、universe（持仓 ∩ buy grid 配置，**TP/SL 双集合不混入**）、提交 payload `buy_ledger`、**提交侧在途复核**；
- `test_rebuild_flatten.py` / `test_order_ledger_v2_rebuild.py`：保留已有标记；**回填 execute 不激活止盈档；`--activate-takeprofit` 独立步骤批量激活存量止盈档**；
- 前端：`stockControlLedger.test.mjs`、`positionReview*.test.mjs`、`positionManagement*.test.mjs` 更新 + 新增展开卡/Tab 测试。

## 13. 部署顺序

1. 执行回填脚本（**仅 `position_type` flatten 幂等重建，不激活止盈档**），dry-run → execute（非交易时段）；
2. 部署后端（`freshquant/strategy/**`、`freshquant/order_management/**`、`freshquant/tpsl/**`、`freshquant/rear/**`）→ 重启：guardian event（`monitor_stock_zh_a_min --mode event`）、XT ingest、tpsl worker、API；
3. **新代码就绪后执行存量止盈档批量激活**（`backfill_position_type.py --activate-takeprofit`，非交易时段；此时新代码按 Σbase remaining 基数卖出，无超卖风险——v4.1 R1：原"先激活后部署"会让旧代码在全仓基数下立即卖出）；
4. 部署前端（`morningglory/fqwebui/**` 重建 fq_webui）；
5. `docs/current/modules/strategy-guardian.md` 同步；
6. 100/116 两台机器同步部署 + 健康检查（API `/api/runtime/health/summary`、WebUI 18080）。

## 14. 文件级改动清单

后端：
0. `freshquant/strategy/common.py`：新增 `get_min_buy_amount()`（900s 内存缓存；读 `params.guardian.stock.min_buy_amount`，默认 10000、下限钳制 10000）+ **先抽取共享参数解析 helper（B3：instrument_strategy → must_pool/params → 默认 解析链，供 `get_trade_amount`/`get_threshold_config`/`get_grid_interval_config`/`get_min_buy_amount` 复用）+ 修正现有 `int(pydash.get(...))` 字段缺失即 TypeError 的模式（Devin 新发现，勿复制）**
1. `freshquant/order_management/guardian/arranger.py`：entry/lot/slice 支持 `position_type`；顺带清理 `remaining_amount` 死参数；**两个递归切片生成器（`_arrange_entry_remaining`/`_arrange_remaining`）与 `_insert_slice_desc`/`_insert_entry_slice_desc` 的合并 → 独立小 PR（B1/A3：status "OPEN"/"open" 口径差异 + rebuild 完整性硬断言 "OPEN"，需单独验证），不在本 PR**
2. `freshquant/order_management/entry_aggregation.py`：聚类保留 `position_type`
3. `freshquant/order_management/ingest/xt_reports.py`：`_upsert_broker_position_entry` 按 `buy_ledger` 打标；`_notify_new_buy_trade` 传 `position_type`；**止盈卖出成交事件 → 阶梯重算（关 ≤N + 全开买入线）**；**零成交终态事件（`ingest_order_report` 中终态非 FILLED，如 CANCELED/部分撤单，状态映射见 `_map_xt_order_status_to_state`）→ 重开对应档位（买单重开该买入线、卖单重开该止盈档），按 `broker_order_id` 幂等；部分成交后撤单：已成交部分先按成交事件处理（幂等），未成交部分按零成交终态重开**；卖出分摊按 `position_type` 约束（无 source plan fallback ① T 盈利低成本 → ② 底仓 → ③ T 非盈利兜底，**盈利判定用卖单 avg_filled_price**；`om_exit_allocations` 记录被扣 slice 的 `position_type`）
4. `freshquant/order_management/rebuild/service.py`：flatten/auto-open → base；逐笔重建保留已有标记、缺失/无法判断 → base
5. `freshquant/order_management/guardian/read_model.py`：arranged fill 带 `position_type`
6. `freshquant/strategy/guardian.py`：买入门槛统一（execution fill / 平均成本 / xt avg 兜底）；删情况2 及关联函数/导入；**删除 `test_order_alert_signal` + `__main__`（A1，会真实发送 order_alert）**；卖出只扫 T + mount + **统一盈利谓词（直接复用 `evaluate_guardian_sell_slices`，不新增重复实现 B4）**；`_prepare_guardian_buy_orders` 按 `buy_ledger` 跳过 base_line 在途买单
7. `freshquant/strategy/guardian_buy_grid.py`：新增 `build_base_line_decision` + **调用 `guardian_ladder` 阶梯状态机（#15）** + `min_buy_amount` 门槛（经 `common.get_min_buy_amount()`，只约束取整前 B）+ **R 统一按占用取大（max(D+C, MV)），MV 缺失 fail-closed** + **TP1 > BUY-1 配置校验** + **提交侧在途复核（提交前 `list_broker_orders`，超 cap 放弃）**；`build_new_open_decision` 去掉三线 cap（只留 `global_cap`）；`build_holding_add_decision` 保留（做T数量，同样套 `min_buy_amount`，**`BUY-3_BELOW` 分支按破线区规则出量：R=global_cap 基数、1/2 收敛、min 终止、冷却 `buy:<code>`**）
8. `freshquant/order_management/guardian/slice_evaluation.py`：支持 T 过滤/基准
9. `freshquant/tpsl/service.py`：`evaluate_takeprofit` 只扫 base（过滤一次、quantity 与 breakdown 共用）+ `total_position_quantity` 改传 Σ base remaining；**TP 触发即关该档（防重复卖单）**；**止盈成交 → 阶梯重算 + 全开买入线**；**零成交终态重开该档**；**`on_new_buy_trade` 改为阶梯事件钩子（仅 base 买入全开止盈，T 买入不触发；旧 rearm 条件整体替换）**；新增 `evaluate_base_buyline` + `submit_base_buy_batch`
10. `freshquant/tpsl/consumer.py`：`handle_tick` 挂 base 买入线评估，**维护双集合**——TP/SL 仍用旧 `load_active_tpsl_codes`，buy 线用扩展集（持仓 ∩ 有 buy grid 配置），不得混入 TP/SL 集合（防 `must_pool.stop_loss_price` 全仓止损误触发）；**buy 线评估插入点在 TP 评估之前**（现 `handle_tick` TP 命中即 return，插在其后则 TP 命中的 tick 上买入线永不评估；TP1 > BUY-1 价格区间不相交，同 tick 双命中不可能，先评估先提交无冲突）
11. `freshquant/rear/stock/routes.py`：持仓列表 base/t 字段（join ledger）；**`guardian_buy_grid_state` GET/POST/reset 暴露并保留 `buy_line_armed` 与 `armed_levels`，reset 语义 = 回缺省态**
12. `freshquant/position_review/service.py`：detail 加 ledger 汇总 + `position_type`
13. `freshquant/order_management/manual/service.py`：`reset_symbol_lots` 重建打标 base；`_notify_new_buy_trade`（manual/service.py:324）传 `position_type`
14. `freshquant/order_management/guardian/allocation_policy.py`：无 source plan fallback 分摊顺序改为**① T 盈利低成本（`avg_filled_price` ≥ `guardian_price × (1+percent/100)`，`guardian_price` 升序）→ ② 底仓 → ③ T 非盈利兜底，三段分桶实现**；`PlanExhausted → 告警 + 人工对账`
15. `freshquant/strategy/guardian_ladder.py`（**新文件，M1**）：对称阶梯状态机独立模块——`buy_line_armed` + `armed_levels` 统一读写（**字段级原子 `$set` + 事件幂等 + 条件更新，v4.1 R3，不做整份读改写**）、事件处理（抄底线触发：关 ≥N 线 + 全开止盈；止盈成交：关 ≤N 档 + 全开买入线；零成交终态重开）、缺省态（`buy_line_armed=[true,true,true]`、TP 档全 False）；`guardian_buy_grid`（#7）与 `tpsl`（#9）经事件钩子调用，不直接操作对方状态
16. `freshquant/tpsl/takeprofit_quantity.py`（v4.1 补充）：`resolve_takeprofit_sell_quantity` 的 `total_position_quantity` 基数改造（Σ base remaining 的传入/计算落点）、`choose_takeprofit_level` 与 ladder `armed_levels` 联动（触发即关该档）
17. `freshquant/tpsl/takeprofit_service.py`（v4.1 补充）：`armed_levels` 读写经 LadderState 事件钩子（`rearm_all_levels` 收敛/替换为阶梯事件）、零成交终态重开落点、`--activate-takeprofit` 批量激活存量止盈档支持
18. `freshquant/tpsl/pools.py`（v4.1 补充）：新增 buy 线 universe loader（持仓 ∩ 有 buy grid 配置），与 `load_active_tpsl_codes` 双集合隔离

兼容层说明：`entry_adapter` 的 legacy 白名单转换（`_legacy_buy_lot_to_entry` / `_legacy_lot_slice_to_entry_slice`）不要求透传 `position_type`——legacy buy_lot/lot_slice 默认 base 即预期语义（V1 不标记）；v2 entry/slice 经 `_normalize_entry` / `_normalize_entry_slice` 的 `dict(item)` 直通保留字段；arranged fills 透传由 read_model（#5）覆盖。

脚本：`script/maintenance/backfill_position_type.py`（flatten 幂等重建 + **`--activate-takeprofit` 存量止盈档批量激活，独立步骤、部署后执行**）

前端（P0）：
13. `morningglory/fqwebui/src/views/StockPositionList.vue`：展开卡双账本
14. `morningglory/fqwebui/src/views/PositionReview.vue`（+ `positionReview*.mjs`）：Tab + 汇总条 + 账本列
15. `morningglory/fqwebui/src/api/stockApi.js` 等：透传新字段

文档：`docs/current/modules/strategy-guardian.md`

## 15. 验收标准

1. entry/slice `position_type` 正确：首开（含手动）→ base；buy 线触发 → base；Guardian 加仓 → t；重建/对账 → base；回填保留已有标记、缺失 → base；
2. 做T买入门槛：execution fill → 平均成本 → xt avg 兜底；不再出现 `guardian_slice_next_level` 阈值来源；
3. 买入线：价格触及 BUY-N → 买入 `R_N = cap_N − max(D + C, MV) − 在途`（占用取大）；`B < min_buy_amount` 或不足一手不买；**触发即关该档及以上、全开止盈档**；**止盈成交关该档及以下、全开买入线**；**零成交终态重开对应档位**；**重激活不当场评估**；独立冷却 `base_buy:<code>`；
4. 破线区（做T深档）：**总仓位限制 = `global_cap`**，可买量 `R = global_cap − max(D + C, MV) − 在途`，每次买 `B = R/2`，受 `min_buy_amount`/整手约束，收敛到 global_cap；**冷却用 `buy:<code>`（与 `base_buy:<code>` 隔离）**；
5. TPSL 只卖 base、基数=底仓总量、**TP 触发即关/成交阶梯重算/零成交重开**、rearm 仅 base 买入（T 买入不触发）；Guardian 只卖 t + mount + **统一盈利谓词**；手动/外部卖单 fallback 分摊 = ① T 盈利低成本（卖单 avg_filled_price 判定）→ ② 底仓 → ③ T 非盈利兜底；
6. **配置校验：TP1 > BUY-1（及线序单调）倒挂 → fail-closed + 告警**；
7. **回填后存量持仓止盈档已批量激活**（无"止盈永不激活"死区）；
8. 持仓列表与复盘账本接口返回 base/t 分组；前端 P0 双账本展示可用；
9. CI 全绿（docs-current-guard / pre-commit / pytest），`docs/current/modules/strategy-guardian.md` 同步。
10. **做T四段走廊与 cap 映射正确**：回补走廊（上界=最近止盈线、下界=BUY-1、cap1）、[BUY-1,BUY-2]（cap2）、[BUY-2,BUY-3]（cap3）、破线区（global_cap、1/2 收敛）均有单测/模拟器覆盖；p > TP3 不买入；触线 t=1 归属抄底线、T 侧不重复买；
11. **模块化与清理项落地**：`guardian_ladder.py` 独立模块且 `guardian_buy_grid`/`tpsl` 均经事件钩子调用；统一盈利谓词复用 `evaluate_guardian_sell_slices`（无新增重复实现）；`common.py` 共享解析 helper 复用（无第 4 份拷贝）；`test_order_alert_signal` 已删除；trading-guide 页面与 v4 方案一致（四段走廊 + 对称阶梯 + R 公式 + min_buy_amount）。

## 16. 非目标与边界

- 不物理拆分 Mongo 集合（逻辑账本，避免全链迁移）；
- **止损功能关闭（需求固定）**：订单止损与全仓止损均不启用——本方案以止损不启用为前提运行；若未来启用止损，须先完成与买入线 universe 的隔离评审（双集合）后再上线；
- 不做 V1 buy_lot 的 `position_type` 标记（默认 base）；
- 买入线不做空仓开仓（空仓首开走 must_pool/手动）；
- **不做 entry/slice 的 `position_type` 一致性校验**（底仓按止盈线整仓卖出，不依赖 slice 粒度；slice 标记仅 T 需要，缺失一律 base）；
- 不做 KlineSlim 走廊可视化与双账本工作台（P1/P2）；
- 不新增独立 strategy 模块（Garden = Guardian holding-add 路径命名）；
- 重建/回填兜底一律按 base（做T由运行时 ingest 打标）；重建后做T仓位可能被标为 base（已知降级，见 §11/§17）。

## 17. 风险与回滚

- **行为变化**：存量 base-only 持仓（如 300760）Guardian 卖点不再卖出（改由 TPSL 卖出），需确认已配 TPSL profile（**v4.1：回填 execute 只重建 position_type，存量止盈档由部署后独立步骤 `--activate-takeprofit` 批量激活（非交易时段），消除人工逐标的 rearm 且不触发旧代码超卖**；TPSL pool = 持仓 ∩ (stoploss bindings ∪ takeprofit profiles)，配 profile 自动入 pool，无需单独操作）；
- **买入线执行器在 TPSL tick worker 上，universe 与 TPSL profile 解耦**：买入线评估集合 = **持仓 ∩ 有 buy grid 配置**（v4 统一口径，删除"∪ TPSL pool"表述）；**未配止盈不影响买入线**，但**底仓卖出仍依赖 TPSL profile**——无 profile 的底仓只能补不能卖，上线前按标的核对；
- **rearm 循环（设计意图）**：底仓补仓 → 止盈卖出 → 价格回落 → 再补仓，构成底仓"网格"周期；每轮买入受 R=cap−max(D+C,MV)−在途 + 冷却 + min_buy_amount 有界；核对 cap1/2/3 递增与首开金额关系（cap1 需 ≥ 首开金额，否则买入线长期 R=0）；
- **占用取大 + 在途扣减**：R = `cap − max(D + C, MV) − 在途`，任何单边口径都比它宽松，更保守；同时防止触线与 T 信号同刻双买；**D/C 最简实现 = 剩余股数 × 当前市场价（v4.1 追加，用户确认）**——避免阶梯价 `remaining_amount` 虚高导致的"买入线长期 R=0"；与 MV 取大后基本以市值为准，保守性由在途扣减 + PM 市值闸门承载；剩余股数随分摊自动释放额度；
- **双进程残余窗口**：T 信号 worker 与 tpsl tick worker 不同进程，双单之和 ≤ 2R，由 PM 市值口径闸门兜底；**定稿：提交侧在途复核消除**（buy 线提交前 `list_broker_orders` 复核，不采用共用冷却键，与独立冷却承诺矛盾）；check-then-submit 非原子，残余窗口接受（≤2R + PM 闸门）；
- **状态写回（v4.1，R3 修正）**：单文档原子 `$set` + 字段级归属 + 事件幂等 + `find_one_and_update` 条件更新（详见 §4.1），不做 read→整份写回（防双进程 lost update）；`_normalize_state` 缺省含 `buy_line_armed=[true,true,true]`；写入方均为事件触发点；reset 路由语义 = 回缺省态（安全方向，最坏多买一次，受 R/冷却/min_buy_amount 约束）；**废除 v3"未显式传字段保留现值"契约**（旧契约文字与测试项同步删除）；
- **初始 arming**：TP 档默认全 False，由任意 base 买入事件（首开或 buy 线触发）全开；**存量持仓由回填 execute 批量激活**，人工 rearm 仅作为回填失败时的兜底手段；
- **配置倒挂**：TP1 ≤ BUY-1 或线序非单调 → fail-closed + 告警（防同价洗单）；
- **回填顺序（v4.1，R1 修正）**：回填 position_type（旧代码忽略新字段，无副作用）→ 部署新代码并重启 → **新代码就绪后**批量激活存量止盈档（非交易时段）。**禁止先激活后部署**：旧 `evaluate_takeprofit` 的 `total_position_quantity` 用券商全仓、`choose_takeprofit_level` 只看 `armed_levels`，激活后、部署前若现价 ≥ TP 线会立即按全仓 1/3 卖出（正是本方案要修的 bug）；**读取侧 `position_type != "t"` 一律按 base**，消除部署窗口期无标记 slice 的账本可见性问题；
- **切换前重建口径**：切换完成前的账单重建一律按 flatten（整仓成本价一条 base），切换完成后由运行时 ingest 逐笔打标；
- **回滚**：代码回滚 = 恢复上一 production SHA + 重启进程；数据回滚 = **重跑 flatten 幂等重建**（v4：回填为派生数据重建，可重跑，不导出备份；旧代码忽略新字段，无兼容性负担）。

## 18. 模块化分解与代码质量清理（v4 定稿附带）

### 18.1 领域模块（4 核心 + 4 支撑）

| 模块 | 职责 | 对应需求 |
| --- | --- | --- |
| **LadderState**（新 `strategy/guardian_ladder.py`） | 6 线开关统一管理：抄底线触发 → 关 ≥N 线 + 全开止盈；止盈成交 → 关 ≤N 档 + 全开买入线；零成交重开；**字段级原子 `$set` + 事件幂等 + 条件更新（v4.1 R3）** | "3 条止盈线 + 3 条抄底线" |
| **DipLine**（`guardian_buy_grid.py` 收敛） | 抄底线买入量：`R = cap_N − max(D+C, MV) − 在途`（扣做T后的剩余，市值取大更保守）；universe、冷却、提交 | "抄底只买入扣减掉做T仓位的那部分" |
| **TakeProfit**（`tpsl/service.py`） | 只卖底仓、比例 L1/3·L2/2·L3/1、触发即关/成交重算/零成交重开 | "3 条止盈线" |
| **TTrading**（`guardian.py` + `slice_evaluation.py` + `allocation_policy.py`） | 四段走廊金字塔买入（回补走廊/[BUY-1,BUY-2]/[BUY-2,BUY-3]/破线区）、统一盈利谓词卖出、mount、三段分桶分摊 | "中间是做T的" |
| **Config**（`common.py`） | 共享参数解析 helper（B3）、min_buy_amount、TP1>BUY-1 校验 | 支撑 |
| **Ledger**（`xt_reports`/`manual`/`rebuild`/backfill） | position_type 打标/读取/重建/回填 + 存量止盈批量激活 | 支撑 |
| **Capacity**（`guardian_buy_grid` + `submit/guardian`） | R 计算、global_cap、在途扣减、提交侧在途复核 | 支撑 |
| **API/前端**（`rear/stock/routes` + fqwebui） | base/t 字段、状态路由透传、双账本展示 | 支撑 |

### 18.2 代码质量清理矩阵（范围 = §14 文件）

| 项 | 内容 | 时机 | 依据 |
| --- | --- | --- | --- |
| B4 | 统一盈利谓词直接复用 `evaluate_guardian_sell_slices`（不新增 is_slice_profitable） | **本 PR（P0）** | Devin 确认 |
| B3 | `common.py` 共享解析 helper（先抽 helper 再新增 get_min_buy_amount） | **本 PR（P0）** | Devin 确认 |
| LadderState | 状态机独立模块 + tpsl 旧 rearm 条件整体替换 | **本 PR（P0）** | Devin 确认 |
| A1 | 删除 `test_order_alert_signal` + `__main__`（会真实发送 order_alert） | **本 PR（P1）** | Devin 确认（危险钩子） |
| 死参数 | arranger 两生成器 `remaining_amount` 参数 | **本 PR** | Devin 新发现 |
| B1/A3 | arranger 两生成器 + `_insert_slice_desc` 合并 | **独立小 PR** | status "OPEN"/"open" 差异 + rebuild 硬断言，需单独验证 |
| C3 | `xt_reports` buy_lot 双写路径 | **不动** | reconcile/stoploss/projection（§14 外）仍消费，活跃路径 |
| C1 | `list_profitable_open_slices` | **不动** | takeprofit 仍需 slice 明细分摊 |
| C2 | entry_adapter legacy 分支 | **待数据核验** | 回填时计数 V1 buy_lot，确认为零再删 |
| C4 | `buy_active` 审计态 | **仅标注 deprecated** | 不阻塞 |
| C5 | consumer 每 tick 调用 evaluate_stoploss | **不动** | 需求关闭，非代码问题 |

### 18.3 决策记录

- D1–D7（状态机时点/存量激活/T 买入不触发/BUY-3 优先/分摊价格源/部分成交/min_buy_amount）：用户 2026-08-10 全部按推荐确认。
- M1–M4（LadderState 位置 `strategy/guardian_ladder.py` / 模块化幅度 / 清理范围 / 抄底线口径）：用户 2026-08-10 确认。
- 做T区域四段走廊（回补走廊 [最近止盈线, BUY-1]/cap1、[BUY-1,BUY-2]/cap2、[BUY-2,BUY-3]/cap3、破线区/global_cap）：用户 2026-08-10 明确"做T区域并非 TP1–BUY-1 一条带"，按 Issue #549 已确认的 v1 表（trading-guide 模拟器 corridor()）落盘。
- **v4.1（2026-08-10 评审修正，本地评审 + Devin 单轮一致）**：R1 存量止盈激活移到部署后（非交易时段）；R2 D/C 口径最简实现（剩余股数 × 当前市场价，用户确认）；R3 状态写回改单文档原子 `$set` + 字段级归属 + 事件幂等 + 条件更新；§14 补充 takeprofit_quantity / takeprofit_service / pools / 零成交终态钩子 / consumer 插入点；§5 措辞修正（保留 `holding._query_grid_interval` 本体）；**manual 加仓默认 base（用户 2026-08-10 确认：手动加仓算底仓）**。
- **v4.1 追加（2026-08-10 用户确认）**：D/C 占用金额**最简实现 = 剩余股数 × 当前市场价**（不用成本价聚合、不加 cost_price 字段）；与 MV 取大后基本为市值口径，保守性由在途扣减 + PM 市值闸门承载。
