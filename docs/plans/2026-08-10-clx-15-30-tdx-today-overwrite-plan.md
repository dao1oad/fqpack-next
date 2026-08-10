# CLX 15/30 监控结果写入通达信 + 持仓同步未持仓即关闭（最终方案）

日期：2026-08-10
状态：**定稿**（用户逐项确认 + Devin 两轮单轮评审达成一致；两处均按用户最终口径收敛）
关联需求：
1. CLX 监控结果写入通达信：覆盖写入当天命中标的，按最后信号时间排序；
2. 持仓同步：所有未持仓标的的止盈/买入三档价位配置一律关闭，防止下次开仓误用旧配置。

---

## 一、需求（用户已确认）

### 1.1 CLX 监控结果 → 通达信分组

1. 排序规则：按监控结果排序，先发生的信号在前，后发生的信号在后；
2. 写入范围：覆盖写入，只写当天有信号的标的；
3. 重复信号：同一标的天内重复产生信号，按**最后一次**产生信号的时间排序；
4. **只在有信号时写，不主动清空**（无信号时段通达信残留昨日标的，用户明确接受）。

最终目标行为：`T0002/blocknew/CLX_15_30.blk` = 当天所有命中标的，每标的一行，按各自「最后信号时间」升序。

### 1.2 持仓同步 → 关闭价位配置

- 判据唯一：**当前是否持仓**（`xt_positions` 中 `volume>0`）；
- 所有**未持仓**标的的启用配置（止盈三档 / 买入三档）一律关闭，**包括**从未持仓的候选标的（must_pool/stock_pools/pre_pool 中的预备开仓标的）；
- 持仓标的配置保持不动；
- 关闭后重新开仓必须重配价位（旧配置不再被自动复用）。

---

## 二、当前实现事实（本机核实）

### 2.1 CLX TDX 写入现状

- 挂载点：`freshquant/market_data/xtdata/strategy_consumer.py::_process_clx_signals`
  - 正信号 docs（`code` 带前缀小写、`datetime`=bar 结束时间 Asia/Shanghai、`created_at`=入库时间）`insert_many` 到 `realtime_screen_multi_period`；
  - 随后 best-effort 调 `append_tdx_group_members(sorted codes)` **去重追加**到 `CLX_15_30.blk`（GBK+CRLF，temp+fsync+os.replace 原子写）。
- 现状问题：累积追加（历史标的永不消失）、无时间排序、无当天概念。
- 同标的同一 bar 会因多模型（S0000-S0017）产生多条记录（实测 `sz000032` 在 11:00 bar 有 3 条）。
- `encode_tdx_blk_code`：带前缀代码 → 7 字符行（1=沪/0=深/2=北+6 位），未知市场 fail-closed。
- 并发：consumer fullcalc 回调来自线程池；`tdx_export.py` 已有模块级 `_TDX_BLK_WRITE_LOCK`。
- 目标文件 `D:\new_tdx\T0002\blocknew\CLX_15_30.blk` 已存在；`blocknew.cfg` 已注册 `clx_15_30`。
- 索引：`realtime_screen_multi_period` 当前仅 `_id_` 索引（已核实）。

### 2.2 持仓同步 worker（已实现、正在运行）

- 进程：`supervisord.fqnext.conf` 托管 `[program:fqnext_xt_account_sync_worker]`，命令 `python -m freshquant.xt_account_sync.worker --interval 15`，autostart + autorestart；当前正常运行。
- 链路：`worker.py::run_forever`（每 15 秒）→ `service.py::sync_once` → `sync_positions_once`：
  1. `query_stock_positions()` 拉券商持仓快照；
  2. `persistence.py::persist_positions()` 全量 upsert 到 `xt_positions`（返回 `cleared_zero_volume`、`deleted_missing`、`empty_snapshot_guard`）；
  3. `_resolve_effective_positions()` → `reconcile_account()` 外部对账。
- 开销实测：常驻内存 ~130MB 私有 / ~234MB 工作集（进程基线，非轮询造成）；CPU 启动 10 分钟累计 ~5.4s（≈单核 1%）；每轮 6 个查询 + 少量 Mongo 写入（订单/成交走增量游标）。
- 容错（已核实）：
  - 可重试错误（xtquant connect/subscribe 失败、credit_detail 无记录、连接类）→ 指数退避重试 5s→60s 封顶，不退出、发 retry 事件；
  - 空快照守卫：查询成功但返回空且库有存量 → `empty_snapshot_guard=True`，保留存量不删除；
  - 缺失淘汰：快照**成功**但单标的持续缺失累计 20 轮或 300 秒才 evict（断网属查询失败，不进入该计数）。
- 15 秒间隔：既有生产配置，时效与开销均合理，**本次不改**。

---

## 三、设计原则（用户确认的简化）

1. **数据库即真值**：CLX 分组每次从 `realtime_screen_multi_period` 查当天记录重写；持仓收敛每次从 `xt_positions` 对账。不引入内存聚合、跨天检测、重启恢复、边沿触发等状态机。
2. **对账 + 覆盖写**：两个改动本质都是「拉取真值 → 计算差集/排序 → 覆盖写」，天然幂等、天然覆盖跨天与重启。
3. **best-effort**：TDX 写入、配置关闭失败仅 warning，不阻塞信号主链与持仓同步主链。
4. **复用现有能力**：原子写、blocknew.cfg 注册、`set_tier_manual_enabled`、`upsert_state` 等均复用，不新造。

---

## 四、改动一：CLX TDX 当天覆盖写

### 4.1 `freshquant/clx_daily_selection/tdx_export.py`

新增 `write_tdx_group_members(codes, *, block_key="CLX_15_30", display_name="clx_15_30", tdx_home=None)`（全量覆盖，非追加）：

- 按传入顺序 `encode_tdx_blk_code` → 7 字符行去重；
- **per-code try/except**：单个编码失败跳过 + `logger.warning`，不阻断全组；
- 空列表（含全部编码失败）→ no-op：不抛错、不触碰旧文件，返回 `written_count=0`；
- 复用 `_atomic_write_blk`（temp+fsync+os.replace）与 `ensure_tdx_group_registered`（幂等注册 blocknew.cfg）；
- 保留 `append_tdx_group_members`、`write_clx_tdx_group`（CLX_18）不动，向后兼容。

### 4.2 `freshquant/market_data/xtdata/strategy_consumer.py`

`_process_clx_signals` 写库成功后：

1. **入库失败 → 跳过 TDX 写入**（以 DB 为真值，入库失败则无需重写）；
2. **整体串行**：在 `_TDX_BLK_WRITE_LOCK` 内完成「查询 → 聚合 → 覆盖写」，避免两个回调的旧快照覆盖新快照；
3. 查询：`realtime_screen_multi_period` 中 `datetime >= 当日 00:00`（Asia/Shanghai tz-aware，Mongo 存 UTC）的记录，投影 `{code, datetime}`；
4. 聚合：每个 code 取 `max(datetime)`（同 bar 多模型自动合并；15min/30min 先后命中取最后，即「最后一次信号」）；
5. 排序：按 `(datetime, code)` 升序（先发生在前；同时间按 code tie-break）；
6. 调 `write_tdx_group_members(codes)` 全量覆盖写；
7. 异常仅 `logger.warning`，不阻塞信号主链（best-effort）。

无需：内存聚合状态、跨天检测、启动恢复（数据库即真值，天然覆盖）。

**索引（推荐）**：给 `realtime_screen_multi_period.datetime` 补索引（当天查询稳定；集合量小，非阻塞）。

### 4.3 测试

tdx_export（`test_clx_daily_selection_tdx_export.py` 新增）：
- 覆盖写顺序保持；空列表 no-op；全部编码失败 no-op；部分失败跳过坏码 + warning；原子失败保留旧文件；blocknew.cfg 注册幂等。

consumer（`test_xtdata_consumer_clx_tdx_group.py` 改写 + 新增）：
- 断言「查询当天记录 → `write_tdx_group_members` 调用与入参顺序」；
- 聚合：同 bar 多模型合并；15min/30min 先后命中按最后时间排序；
- 查询边界：仅当天记录参与，昨日记录不参与（跨天天然覆盖）；
- 并发：两回调交错，最终文件 = 最新查询快照；
- 入库失败跳过写入；编码失败标的跳过、其余正常。

### 4.4 验收

1. 当日命中后 blk 只含当日标的、按最后信号时间升序、每标的一行；
2. 昨日标的在今日首个信号后消失；无信号时段不主动清空（盘前可能显示昨日标的，已声明）；
3. 重复信号标的按最后信号时间重排（10:45 命中、11:00 再命中 → 按 11:00 排）；
4. 重启 consumer 后，下一次信号触发即重写为当天全量；
5. 北交所/异常码出现时文件仍正常更新且有 warning 日志；
6. CI 三项全绿；`CLX_18` 相关既有测试零改动零回归。

---

## 五、改动二：持仓同步未持仓即关闭

### 5.1 挂载点与动作

**挂载点**：`freshquant/xt_account_sync/service.py::sync_positions_once`，`persist_positions` 返回后、`reconcile_account` 前，执行收敛。

**收敛动作**（每轮同步成功后，best-effort、幂等）：

1. **持仓集合**：`xt_positions` 中 `volume>0` 的标的（归一化 6 位；与仓位门禁口径一致；迟滞窗口内缺失但未 evict 的标的仍保留 volume>0，不会误关）；
2. **启用配置集合**：
   - 买入：`guardian_buy_grid_configs` 中 `enabled=True`（或 `buy_enabled` 任一为 True）的 code；
   - 止盈：`om_takeprofit_profiles` 中任一 tier `manual_enabled=True` 的 symbol；
3. **待关闭 = 启用配置集合 − 持仓集合**（两套配置分别计算）；
4. 止盈三档：先读 profile，仅对 `manual_enabled=True` 的档位调 `TakeprofitService.set_tier_manual_enabled(level, False)`（profile `manual_enabled=False` + state `armed_levels=False`）；异常逐 symbol try/except（M4）；
5. 买入三档：`GuardianBuyGridService.disable_grid(code, updated_by="xt_account_sync")`（判空 + 直写 `$set {"buy_enabled":[False,False,False], "enabled":False}`，绕过 caps 校验、不 upsert，M2）+ `upsert_state(buy_active=[False,False,False])`；
6. runtime 事件留痕（`component=xt_account_sync` / `node=position_cleanup_disabled` / `reason_code=non_holding_config_disabled`）；
7. 任一步失败仅 `logger.warning`，不抛出、不阻塞同步主链；下轮可重试。

**守卫**：`empty_snapshot_guard=True` 时不执行收敛（防空快照全量误关）。

### 5.2 触发边界（用户最终口径）

- 判据唯一：`xt_positions` 中 `volume>0` = 持仓；其余（从未持仓、曾持仓已清仓、volume=0、evict 删除）全部视为未持仓；
- 未持仓标的的启用配置（含 must_pool/stock_pools/pre_pool 候选标的）一律关闭——预备开仓标的在开仓前配置应为关闭，开仓时按新配置重设；
- 收敛基于「启用配置 − 持仓集合」差集，天然幂等：已关闭的不重复写、不重复发事件；用户重新配置后若仍未持仓，下一轮收敛再次关闭（符合未持仓即关闭语义）；
- 迟滞兼容：快照缺失但未 evict（xt_positions 保留 volume>0）不关闭；evict 后下一轮收敛关闭。

**关闭后语义**：开仓前必须重配价位（`update_guardian_buy_grid` / 止盈 profile 保存），持仓后配置保持启用；未持仓状态下配置恒为关闭（M3 前置条件）。

### 5.3 测试

- 收敛：未持仓标的（从未持仓候选、曾持仓已清仓、volume=0、evict 删除）启用配置全部关闭；
- 幂等：已关闭配置下一轮不再写库/不再发事件；重新配置后仍未持仓 → 下一轮再次关闭；
- 持仓保持：volume>0 持仓标的配置不被关闭；
- 迟滞兼容：未 evict 不关闭；evict 后关闭；
- M2 回归：config 带 `max_position_amounts` 且 capacity 不可用时关闭仍成功（`disable_grid` 不走 caps 校验）；
- M3 回归：关闭后 `build_new_open_decision` 返回 quantity=0（被阻断）；重配后恢复可开仓；
- M4 回归：profile 不存在/档位缺失逐 symbol 捕获不中断；仅对 `manual_enabled=True` 档位调用；
- `empty_snapshot_guard=True` 不触发关闭；无 profile/config 的标的跳过（no-op）；
- 关闭失败不阻断同步主链（fake 抛错断言 warning 路径）；
- 顺序竞态：先关闭，后迟到 sell trade fact 触发 `reset_after_sell_trade`（buy_active 变回 [T,T,T]）——断言因 config `buy_enabled=[F,F,F]`，`_resolve_hit_levels` 仍返回空（config 是真正守门人，双闸不冲突）；
- 代码归一化：xt `stock_code`（如 `600000.SH`）→ 6 位键与 profile/config 一致。

### 5.4 验收

1. 每轮同步后：所有未持仓标的止盈全档 `manual_enabled=False`、`armed_levels` 全 False；买入 `buy_enabled=[False,False,False]`、`enabled=False`、`buy_active=[False,False,False]`；所有持仓标的配置保持不动；
2. 收敛只对「启用配置 ∩ 未持仓」差集写库，audit/runtime 事件不刷屏；
3. 空快照守卫不触发关闭；
4. 关闭失败不影响持仓同步主链，且下轮可重试成功；
5. 未持仓标的重新开仓：重配后能正常下单；持仓期间配置保持启用；
6. CI 三项全绿；`test_xt_account_sync_*`、`test_tpsl_*`、`test_guardian_buy_grid*` 既有用例零回归。

---

## 六、部署面

- `freshquant/market_data/**` + `freshquant/clx_daily_selection/**` → 重启 `fqnext_realtime_xtdata_consumer`、重部署 `fq_apiserver`；
- `freshquant/xt_account_sync/**` + `freshquant/tpsl/**` + `freshquant/strategy/guardian_buy_grid.py` → 重启 `fqnext_xt_account_sync_worker`；
- 文档同步（否则 docs-current-guard 挡 CI）：
  - `docs/current/modules/market-data-xtdata.md`（现仍写「去重追加」，需改为当天覆盖写）；
  - `docs/current/reference/stock-pools-and-positions.md`（CLX 分组段落 + 持仓同步关闭价位段落）。

## 七、非目标

- 不改变 `CLX_18.blk` 每日选股导出行为；
- 不改变 `stock_pools` / `must_pool` 语义；不触发下单；
- 不做「开盘前主动清空」；
- `CLX_15_30` 分组系统托管：用户手动添加的标的会被覆盖；
- 不做「清仓后自动删除 profile/config 文档」（只关闭，保留历史配置供重配参考）；
- 不改变开仓/加仓决策逻辑本身；
- 持仓降量但仍有持仓 → 不关闭（仅未持仓触发）。

## 八、实施清单与 Done 定义

| # | 改动 | 文件 | 量级 |
|---|---|---|---|
| 1 | 新增 `write_tdx_group_members`（覆盖写 + 容错 + 复用原子写/注册） | `freshquant/clx_daily_selection/tdx_export.py` | ~30 行 |
| 2 | `_process_clx_signals` 查库当天记录 → 聚合排序 → 覆盖写（锁内串行） | `freshquant/market_data/xtdata/strategy_consumer.py` | ~30 行 |
| 3 | `disable_grid`（判空 + 直写 $set，绕过 caps 校验） | `freshquant/strategy/guardian_buy_grid.py` | ~15 行 |
| 4 | 收敛挂载：启用配置 − 持仓集合 → 关闭止盈/买入 | `freshquant/xt_account_sync/service.py`（或新增小模块） | ~30 行 |
| 5 | 测试 + docs/current 同步 | 测试文件 4 个 + 文档 2 个 | — |

Done = PR 合并 + CI 全绿 + docs 同步 + 部署 + 健康检查 + cleanup（按 AGENTS.md）。
