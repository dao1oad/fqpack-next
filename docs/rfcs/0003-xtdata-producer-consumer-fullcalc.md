# RFC 0003: XTData Producer/Consumer + fullcalc（替代轮询，统一缠论结构推送）

- **状态**：Approved
- **负责人**：TBD
- **评审人**：TBD
- **创建日期**：2026-03-05
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

当前仓库（`D:\fqpack\freshquant-2026.2.23`）对 A 股分钟级信号的主链路为：

- 通过 TDX/新浪/东财等“轮询 realtime → 写入 Mongo（`DBfreshquant.stock_realtime`）”；
- `freshquant/signal/astock/job/monitor_stock_zh_a_min.py` 每 30s 轮询 `get_data_v2()`，重复计算缠论结构并产生 Guardian 信号；

问题：

- 端到端延迟偏大且不可控（轮询频率、网络、写库、再次读库、再计算）。
- 计算冗余：同一标的/周期在多个模块重复“从头计算缠论结构”。
- 前端 UI 与策略无法复用同一份结构数据（容易不一致）。

旧仓库（`D:\fqpack\freshquant`）存在基于 XTQuant(MiniQMT) 的 Producer/Consumer 事件驱动实现：

- Producer 实时订阅 tick，生成分钟 bar close 事件；
- Consumer 消费 bar close，统一计算缠论结构/CLX 模型，并通过 Redis cache + Pub/Sub 推送前端；

本 RFC 要求在“去冗余 + 按需迁移”的前提下，将该架构迁移到本仓库，并替代轮询模式。

## 2. 目标（Goals）

- 以 XTData(xtquant) 实时订阅为源，产出 `BAR_CLOSE` 事件，驱动 downstream 计算。
- 引入 Consumer：对 `1m/5m/15m/30m` 统一计算缠论结构（fullcalc），并推送给前端 UI。
- 支持 STOCK/ETF（含前复权 qfq）：结构计算与前端展示均基于 qfq 后的 OHLC，避免除权/拆分导致结构断层。
- Mode A（Guardian-1m）与 Mode B（CLX-15/30）严格二选一，由 MongoDB params 配置，允许“重启进程后生效”。
- 必须具备：
  - `prewarm`：启动预热；每个周期都加载最多 20000 根，生成结构基线并推送。
  - `backfill`：缺口回补；回补数据不触发 fullcalc，只在下一根实时 bar close 到来时计算“最新一根”的结构刷新。
  - CLX 12 模型筛选（Mode B 仅 15m/30m）与钉钉消息发送。
- must_pool/持仓股新增时，Producer 需要及时增量订阅并开始推送 bar（无需重启）。
- fullcalc 计算需支持多进程（原分支已有实现思路），避免阻塞消费主循环并提升吞吐。
- 重建 `fullcalc`：从源码构建适配 Python 3.12 的 `fullcalc.pyd`，并保证“结构-only”可控（禁用 CLX 时 `signals=[]` 但结构正常输出）。
- 停用当前 TDX realtime 采集链路（无需启动相关进程）；由新模式写入 `DBfreshquant.stock_realtime` 供现有读取逻辑复用。

## 3. 非目标（Non-Goals）

- 本 RFC 不实现 tick 推送（后续止盈止损模块再完善 tick 事件）。
- 不整体搬迁旧仓库 Consumer 的大量“监控池来源/分流/海量 env 开关/复杂诊断”代码；只迁移本 RFC 需求所需的最小子集。
- 不在本 RFC 内改造所有 UI/接口以完全脱离 Mongo（仍以 Redis Pub/Sub + Mongo 作为主集成点）。

## 4. 范围（Scope）

**In Scope**
- Producer：XTData 订阅与 `BAR_CLOSE` 投递（1m + 当日实时 resample 5/15/30）。
- Consumer：消费 `BAR_CLOSE`，写入 `DBfreshquant.stock_realtime`，维护每周期最多 20000 根窗口，触发 fullcalc，推送结构；Mode B 产出 CLX12 + 钉钉。
- prewarm/backfill/积压处理策略落地（行为语义见第 7 节）。
- fullcalc 源码迁移与构建（xmake target + Python wrapper）。
- 配置（MongoDB params）与启停策略（停用 TDX realtime 采集进程）。

**Out of Scope**
- 止盈止损模块及 tick 事件推送/消费。
- 其它周期（60m/120m/日线等）的结构推送（后续如需再扩展）。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**
- Producer 只负责：实时订阅 → 产出 bar close 事件（含当日 resample）→ 写入 Redis 队列。
- Consumer 负责：
  - bar 持久化：将所有收到的 bar 写入 `DBfreshquant.stock_realtime`（`frequence` = `1min/5min/15min/30min`）。
  - 结构计算：fullcalc 统一产出缠论结构，并通过 Redis Pub/Sub 推送前端。
  - Mode B：仅在 15m/30m 周期产出 CLX12 结果、落库、钉钉。
  - prewarm/backfill 与积压策略（只算最新一根）。

**不负责（Must Not）**
- Producer 不做 fullcalc、不做信号筛选、不做 DB 落库。
- Consumer 不对回补出来的每一根 bar 做 fullcalc（避免回补风暴）。
- Mode 切换不要求热切换；只支持重启进程后生效。

**依赖（Depends On）**
- XTQuant/MiniQMT（Windows 本机环境）。
- Redis（队列 + Pub/Sub + 可选 cache）。
- MongoDB（params、stock_realtime、CLX 信号落库等）。
- QUANTAXIS（历史分钟库读取 + 前复权）。

**禁止依赖（Must Not Depend On）**
- TDX realtime 采集链路（不再作为分钟信号主链路）。

## 6. 对外接口（Public API）

### 6.1 MongoDB params（重启生效）

参数存储沿用 `queryParam()` 约定（`DBfreshquant.params`，按 `code` 分段）。

建议存放在 `code="monitor"` 文档的 `value.xtdata` 下：

- `monitor.xtdata.mode`: `"guardian_1m" | "clx_15_30"`（严格二选一）
- `monitor.xtdata.max_codes`: `50`（上限约束）
- `monitor.xtdata.periods`: 固定 `["1m","5m","15m","30m"]`（前端展示所需）
- `monitor.xtdata.prewarm.max_bars_per_period`: `20000`
- `monitor.xtdata.qfq`: `true`（股票历史/实时统一前复权，见第 7.4 节）

### 6.2 Redis 事件协议

**队列（List）**
- Key：`FQ:QUEUE:BAR_EVENT:{shard}`（分片规则实现时保持可配置；默认 10 分片）
- Value：JSON（UTF-8），最小字段：
  - `type`: `"BAR_CLOSE"`
  - `code`: 证券代码（建议统一为 `"000001.SZ"` 或 `"000001.SH"`；实现时统一规范）
  - `period`: `"1min" | "5min" | "15min" | "30min"`
  - `data`: `{time, time_str, open, high, low, close, volume, amount}`
  - `created_at`: producer 生成时间（epoch seconds）

**Pub/Sub（前端结构推送）**
- Channel：`CHANNEL:BAR_UPDATE`
- Payload：`{code, period, data: chanlun_data}`
  - `period` 对前端使用 `1m/5m/15m/30m`（frontend 格式）

## 7. 数据与配置（Data / Config）

### 7.1 历史数据读取（QUANTAXIS 分钟库）

- STOCK：
  - 历史分钟数据使用 QUANTAXIS 的 `QA_fetch_stock_min_adv(...).to_qfq()`（qfq）作为主来源。
  - 实时增量来自 `DBfreshquant.stock_realtime`（本 RFC 新链路写入）。
- ETF：
  - 历史分钟数据使用 QUANTAXIS 的 `QA_fetch_index_min_adv(...)`（bfq）作为主来源；
  - 通过 `DBQuantAxis.etf_adj`（见 RFC 0002）对“历史 + realtime 增量”统一应用 qfq；
  - 实时增量来自 `DBfreshquant.index_realtime`（本 RFC 新链路写入，复用现有 ETF 读取逻辑）。

### 7.2 实时写入（替代 TDX realtime）

- Consumer 将 Producer 推送的 `1/5/15/30` 分钟 bar 写入 realtime 增量集合，字段遵循现有 schema：
  - `datetime/open/high/low/close/volume/amount/code/frequence/source/time_stamp/date_stamp`
- 集合选择：
  - STOCK → `DBfreshquant.stock_realtime`
  - ETF → `DBfreshquant.index_realtime`（复用 `freshquant/quote/etf.py` 的读取与 qfq 应用逻辑）
- `source` 统一标识为 `XTQuant_Realtime`（或其它明确常量）。

### 7.3 prewarm：每周期 20000 根窗口

- 对每个 code、每个周期（1m/5m/15m/30m）：
  - 读取历史（QUANTAXIS，qfq）+ 实时增量（stock_realtime）
  - 截断尾部最多 20000 根
  - 调用 fullcalc 生成结构基线并推送前端（可选写入 Redis cache）

### 7.4 前复权（QFQ）一致性要求（股票）

结论：需要正确使用前复权（QFQ），并保证“历史 + 实时增量”处于同一复权基准，否则会在除权日附近产生价格断层，导致缠论结构与 CLX 信号失真。

约束：
- 历史：使用 QUANTAXIS `to_qfq()`。
- 实时：写入 `stock_realtime` 的 bar 必须与历史保持同一复权基准：
  - 推荐：在 Consumer 写入前，将 XTData bar 统一转换为 qfq 后再写入；
  - 备选：写入 raw + `adj_factor`，读取合并时再按 factor 转换（实现复杂度更高，非默认）。

### 7.4.1 前复权（QFQ）一致性要求（ETF）

结论：ETF 也需要 qfq，且应复用现有 `etf_adj` 因子链路（RFC 0002），避免拆分/分红导致价格断层。

约束：
- 历史：使用 QUANTAXIS index 分钟线（bfq）。
- realtime 增量：写入 `DBfreshquant.index_realtime`（bfq）。
- 合并后：在 Consumer 中对“历史 + realtime 增量”统一 `apply_qfq_to_bars(...)`，再送入 fullcalc 与前端推送。
- 若 `etf_adj` 缺失：允许降级为 bfq（但必须记录告警/日志，且结构/信号可能失真）。

### 7.5 backfill：只补 bar，不跑 fullcalc

- 缺口检测后只补齐 bar（写库/更新窗口），不触发 fullcalc；
- 等下一根实时 `BAR_CLOSE` 到来时，再对该 code+period 只计算“最新一根结构”并推送，保证 UI 刷新且避免回补风暴。

### 7.6 积压：只算最新一根结构（允许错过中间信号）

- 当 Redis 队列出现积压或消费落后时：
  - 对积压事件逐条落库/更新窗口；
  - fullcalc 只在“追到最新”后执行一次（每 code+period）。
- Mode B：允许因此错过积压期间本应触发的 CLX 信号/钉钉消息（只保最新一根）。

### 7.7 动态订阅：must_pool/持仓变更增量生效

- Producer 需周期性刷新“本模式标的集合”（Mode A：持仓+must_pool；Mode B：stock_pools）。
- 当检测到新增标的时，应在不重启的情况下增量订阅并开始推送 bar close。
- 当检测到移除标的时，可选择取消订阅或继续保留订阅（默认建议取消订阅以减少推送负载；实现时保持幂等且可恢复）。

### 7.8 fullcalc 多进程执行（CPU 隔离）

- Consumer 的 fullcalc 必须使用多进程（例如 `ProcessPoolExecutor`）执行：
  - 避免阻塞 BLPOP 主循环与 IO 写入；
  - 允许设置超时与自愈（超时/进程池 broken 时重建）。
- 由于本 RFC 定义“积压只算最新一根”，并发压力主要来自“多 code × 多周期”在同一时间边界触发；
  - 需全局限流（例如每轮最多提交 N 个 fullcalc task）；
  - 积压时跳过提交，追到最新后再提交一次。

## 8. 破坏性变更（Breaking Changes）

- 分钟信号主链路从“轮询 get_data_v2”切换为“订阅 BAR_CLOSE 事件驱动”。
- 生产部署需停止启动 TDX realtime 采集进程（例如 `freshquant.market_data.stock_cn_a_collector`），避免双写与资源浪费。

> 破坏性变更在实现落地时再登记到 `docs/migration/breaking-changes.md`。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

按需迁移（只迁入本 RFC 必需能力）：

- Producer（核心片段）
  - `freshquant/market_data/xtdata/market_producer.py`：
    - tick pump（避免 callback 阻塞）
    - `OneMinuteBarGenerator`（含 synthetic bar 可选）
    - `MultiPeriodResamplerFrom1m`（仅当日实时 resample 5/15/30）
    - Redis 队列写入协议（`BAR_CLOSE`）
- Consumer（核心片段）
  - `freshquant/market_data/xtdata/strategy_consumer.py`：
    - `BLPOP` 消费队列
    - prewarm/backfill/积压只算最新一根的策略（本仓库实现将进一步简化）
    - `CHANNEL:BAR_UPDATE` 推送结构数据
- fullcalc
  - `morningglory/fqcopilot/fullcalc/*`（binding/fullcalc/types）
  - `morningglory/fqcopilot/xmake.lua` 的 `target("fullcalc_py")`（适配 Python 3.12）

## 10. 测试与验收（Acceptance Criteria）

- [ ] Mode A：启动后对“持仓+must_pool”在 `1/5/15/30` 周期产生结构推送；Guardian 信号由事件驱动触发（不再轮询 `get_data_v2`）。
- [ ] Mode B：启动后对 `stock_pools` 在 `1/5/15/30` 周期产生结构推送；在 `15/30` 周期能产出 CLX12 信号并发送钉钉（去重后）。
- [ ] ETF：当监控集合包含 ETF 时，能正确读取历史 + realtime 增量并应用 qfq，结构推送连续无明显断层。
- [ ] prewarm：每周期最多加载 20000 根，启动后无需等待首根实时 bar 即能看到结构数据推送。
- [ ] backfill：制造缺口后能补齐 bar；回补过程不触发 fullcalc 风暴；下一根实时 bar 到来后结构刷新。
- [ ] 积压：人为压测产生队列积压时，只计算最新一根结构，且 Mode B 允许错过积压期间的 CLX 信号。
- [ ] QFQ：验证除权日前后（或历史区间）结构计算无明显断层；历史与实时增量的价格基准一致。
- [ ] 动态订阅：must_pool/持仓新增标的后，无需重启即可开始订阅并推送结构。
- [ ] 多进程 fullcalc：fullcalc 在子进程运行，主循环不卡死；超时任务可恢复。

## 11. 风险与回滚（Risks / Rollback）

- 风险：XTData/MiniQMT 环境依赖强（Windows、本机服务、权限）。
  - 缓解：部署文档明确运行边界；保留旧轮询链路作为 fallback（不立即删除）。
- 风险：QFQ 因子处理不一致导致结构/信号异常。
  - 缓解：默认强制 qfq 一致性；提供快速诊断日志与回滚开关（实现阶段定义）。
- 回滚：停止 Producer/Consumer 进程，恢复运行旧的 `monitor_stock_zh_a_min.py` 轮询链路与原有 realtime 采集（TDX）。

## 12. 里程碑与拆分（Milestones）

- M1：RFC 通过（本文件）
- M2：fullcalc 源码迁移 + Python 3.12 构建可用
- M3：Producer（1m + 当日 resample 5/15/30）与 Consumer（落库/推送/积压策略）跑通
- M4：Mode A（Guardian 事件驱动）跑通并替代轮询
- M5：Mode B（CLX12 + 钉钉）跑通
- M6：停用 TDX realtime 采集进程的部署变更与回滚说明完善
