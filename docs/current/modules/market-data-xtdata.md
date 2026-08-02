# XTData 行情链路

## 职责

XTData 链路负责把宿主机 XTData 行情转换成 FreshQuant 可消费的实时事件流，并维护独立的盘后 QFQ shadow 快照。它承担五件事：

- 从 XTQuant 订阅当前监控池的全量行情。
- 把 tick 推入 Redis 分片队列。
- 合成 1 分钟 bar，并继续向下游发布 bar close 事件。
- 在 consumer 侧做 prewarm、结构计算、实时缓存与运行观测。
- 在盘后 BFQ ready 后，以 XTData 日线 `preClose` 构建和审计 Stock / ETF A/B QFQ shadow 快照。

## 入口

- producer
  - `python -m freshquant.market_data.xtdata.market_producer`
- consumer
  - `python -m freshquant.market_data.xtdata.strategy_consumer --prewarm`
- QFQ shadow worker
  - `python -m freshquant.market_data.xtdata.qfq_worker worker`
- QFQ 运维 CLI
  - `python -m freshquant.market_data.xtdata.qfq_worker status --strict`
  - `python -m freshquant.market_data.xtdata.qfq_worker audit --scope <stock|etf> --mode <structure|tail|full> [--code CODE]`
  - `python -m freshquant.market_data.xtdata.qfq_worker build --scope <stock|etf> --target-date YYYY-MM-DD`
  - `python -m freshquant.market_data.xtdata.qfq_worker build --scope <stock|etf> --target-date YYYY-MM-DD --full`
  - `python -m freshquant.market_data.xtdata.qfq_worker rollback --scope <stock|etf>`

producer 是唯一 XTData 实时订阅入口；consumer 是唯一 bar 队列消费入口。QFQ worker 是独立的盘后 XTData 日线读取入口，不参与实时队列。

## 依赖

- 宿主机 XTQuant / XTData 环境
- `XTQUANT_PORT`，默认 `58610`
- Redis
- QuantAxis 历史库
- `freshquant.dagster_pipeline_markers` 的 `stock_postclose_ready` / `etf_postclose_ready` 成功文档
- 监控池来源
  - `guardian_1m = xt_positions + must_pool`
  - `guardian_and_clx_15_30 = (xt_positions + must_pool) + stock_pools`
    - 先保留 Guardian 池
    - 再补未过期 `stock_pools`
    - 总数不超过 `monitor.xtdata.max_symbols`

## 数据流

### Tick 链

`XTData -> market_producer -> REDIS_TICK_QUEUE_PREFIX:<shard> -> TpslTickConsumer`

- `market_producer` 的 XTData 回调当前只负责规范化 tick、更新接收心跳、把 tick quote 批次交给后台写队列，并把原始 tick 交给 1 分钟 bar pump。
- tick quote 的 Redis `rpush` 已从 XTData 回调线程移到后台 worker，避免 Redis 抖动直接卡住 XTData 回调链。

### Bar 链

`XTData -> market_producer/OneMinuteBarGenerator -> REDIS_QUEUE_PREFIX:<shard> -> strategy_consumer -> realtime cache / chanlun payload / Guardian`

consumer 会在启动时做历史 prewarm，并在 backlog 很高时进入 catchup 模式，暂时跳过 fullcalc，只保留最新数据。
- `OneMinuteBarGenerator` 当前只在 `whole_quote` 快照带来正向 `volume/amount` 增量时更新 1 分钟 bar 的 OHLC；无成交的 quote-only 快照不会再改写分钟高低收。
- `11:30:00` 与 `15:00:00` 这类交易时段结束边界快照会归入最后一个有效分钟 bar，而不是落到午休或收盘后的无效分钟桶。
- `StrategyConsumer` 当前只允许“当天”的 realtime bar 参与 history/realtime merge；所有已完成交易日的分钟线都只信任盘后同步到 QuantAxis 的历史库，不再允许旧 `index_realtime/stock_realtime` 覆盖历史分钟线。
- `OneMinuteBarGenerator` 和 `StrategyConsumer` 都会通过 FreshQuant A 股交易日历拦截非交易日 bar；周末/节假日 tick 不生成 bar，非交易日 `BAR_CLOSE` 不写入 `stock_realtime/index_realtime`。
- consumer prewarm、股票分钟线 API 拼接与 ETF/index K 线查询都会过滤非交易日 realtime 行，避免历史脏数据继续进入 Redis Kline cache 或 `/api/stock_data` 返回值。

### QFQ shadow 链

`Dagster Stock/ETF BFQ + 旧复权 writer -> postclose ready marker -> fqnext_xtdata_qfq_worker -> XTData preClose -> inactive A/B slot -> audit -> qfq_ready active_slot`

- Stock 数据集合为 `stock_adj_qfq_a` / `stock_adj_qfq_b`，ETF 数据集合为 `etf_adj_qfq_a` / `etf_adj_qfq_b`。
- `quantaxis.qfq_ready` 对每个 scope 使用一个原子双槽 marker；构建 inactive slot 期间 active slot 保持只读，inactive slot 审计成功后才切换。
- `quantaxis.qfq_writer_locks` 对每个 scope 只允许一个带过期时间并由后台线程持续续期的 writer lease；单次 XTData 请求或 Mongo `$out` 阻塞时仍续租，发布前重新核对 owner。中断的 `building` 仅由下一位 lease owner 恢复，人工 build / rollback 不与 Supervisor worker 并发写。
- 首次 bootstrap 先构建并审计 A，再复制和审计 B，之后发布双槽 marker；日更只对 inactive slot 写入。
- XTData field-table 以日期列为交易日，epoch 回退按 Asia/Shanghai 还原；`dividend_type=none` 日线的 `preClose` 仍是 canonical 因子来源，常规边先在真实 XTData 日期轴递推，再投影到有效 BFQ coverage。
- BFQ 中 `vol` 与 `amount` 同时等于 QASU 浮点哨兵的占位行不进入 coverage。Stock 优先以 `stock_xdxr` 中最早满足 `category=5`、`shares_before=0`、`shares_after>0` 的初始股本记录作为上市边界；缺少该记录时才回退 XTData instrument detail 的 `OpenDate`，ETF 也使用同一证据。只有 `OpenDate` 不晚于最后一条有效 BFQ 时才将其解释为上市边界；若 `IsTrading=false`、`OpenDate` 晚于全部有效 BFQ，且该边界之后还有 QASU sentinel 证据，则分类为 `nontrading_terminal_history`，仅从当前 QFQ build universe 排除并保留 BFQ 历史；该旧生命周期没有 XTData `preClose` 因子时 reader 仍 fail closed。缺失、无效或缺少任一终止证据的 `OpenDate` 不排除 BFQ，source 前后缀缺口仍 fail closed。
- BFQ-only 日期仅在两个真实 XTData bar 之间，且同日期轴的 `front_ratio.close / none.close` 在缺口两端容差内相等时桥接；该稀疏边按无调整处理，缺失日期写入相同因子，并记录 `source_gap_rows_bridged`、`codes_with_source_gaps`、`source_gaps[]`。
- `front_ratio` 只证明缺口未跨公司行为，不参与 canonical 因子计算；前后缀缺口、proof 缺失、none/front_ratio 日期轴不一致或两端比率变化均 fail closed，不发布 marker。
- 完整 source 区间下载后仍无 `none` bars 的 code 不生成空因子或 `1.0`：writer 从本轮 inactive slot 删除其残留行，并在该 slot 的 `source_exclusions[]` 记录 `{code, reason=source_empty_bars}`；其他 code 审计通过时 marker 仍可 ready。A/B 各自保留自己的 exclusion metadata，rollback 随 slot 一起恢复。tail 请求为空必须先用完整 BFQ 区间复核；`front_ratio` proof 为空不属于该分类，继续 fail closed。
- XTData 长区间下载只返回近期后缀时，QFQ client 会以当前最早缓存日的前一日为边界继续向前分页，直至覆盖请求起点；任一页未把最早日期向前推进时立即报错，不发布不完整快照。
- 当前 Stock / ETF 在线 reader 和旧 `stock_xdxr`、`etf_xdxr -> etf_adj` writer 均未切换；A/B 发布不会改变现有 Kline 或策略读取结果。
- 真实 Index 走 BFQ 日线/分钟线和 `index_realtime`，不读取 ETF/Stock 因子，也不进入 QFQ shadow scope。

## 存储

- Redis
  - tick 分片队列
  - bar 分片队列
  - 实时 Kline cache
- Mongo / QuantAxis
  - 历史分钟线读取
  - 实时结构或补权结果所需的基础数据
  - `realtime_screen_multi_period`
  - `stock_adj_qfq_a/b`、`etf_adj_qfq_a/b` 与 `qfq_ready`

当前模块会在启用 CLX 能力时把命中的多周期 CLX 信号写入 `realtime_screen_multi_period`。

## 配置

- `monitor.xtdata.mode`
  - 决定订阅池来源和 consumer 行为。
  - `guardian_1m` 只服务 Guardian 1 分钟事件链。
  - `guardian_and_clx_15_30` 同时服务：
    - Guardian 1 分钟事件链
    - `stock_pools` 的 15/30 分钟 CLX 模型
  - 兼容旧值：
    - `clx_15_30`
      - 读取时自动归一到 `guardian_and_clx_15_30`
- `monitor.xtdata.max_symbols`
  - 限制订阅池大小。
- `monitor.xtdata.queue_backlog_threshold`
  - 决定 consumer 何时进入 catchup 模式。
- `XTQUANT_PORT`
  - XTData 连接端口。
  - QFQ worker 通过 `bootstrap_config.xtdata.port` 读取同一端口，默认 `58610`。

对 Guardian 主链最重要的是：

- `monitor.xtdata.mode` 启用了 Guardian 能力
  - 正式值可为 `guardian_1m` 或 `guardian_and_clx_15_30`

## 部署/运行

- producer、consumer 与 QFQ worker 通常运行在宿主机，不放进 Docker。
- 修改 `freshquant/market_data/**` 后，按 `market_data` surface 重启 producer、consumer、adj refresh worker 与 QFQ worker。
- consumer 改动涉及结构缓存或 prewarm 逻辑时，建议带 `--prewarm` 重新拉起。
- producer 启动阶段若遇到可重试的 XTData 连接失败，当前会在进程内按退避重试继续等待 XTQuant / QMT 就绪，不再只依赖 supervisor 外层重启。
- producer 当前会在交易时段内监控 `rx_age_s`：
  - 当 `connected=1`、`subscribed_codes>0` 且 `rx_age_s >= 120` 秒时，先自动重订阅当前代码池。
  - 若 30 秒后仍持续 stale，则升级为 `xtdata.connect() + 重订阅`。
  - 恢复动作会写入 `subscription_guard` 运行事件，`reason_code=stale_rx`。
- producer 心跳当前额外暴露：
  - `tick_quote_pending_batches`
  - `tick_quote_dropped_batches`
- `xtdata_adj_refresh_worker` 若在启动或日内计划刷新时遇到可重试的 XTData 连接失败，当前会退避后重建新的 refresh service / XTData client 再继续同步。
- `fqnext_xtdata_qfq_worker` 默认每 60 秒轮询盘后 ready marker；可用 `worker --once` 单轮执行，用 `status --strict`、`audit`、`build`、`rollback` 做运维检查。正式 post-deploy verify 会执行严格 status，不能只以进程存在代替数据 ready。
- 默认日更回看 60 个实际交易日；更早的 XTData 历史修订通过 `build --full` 在 inactive slot 做同截止日全 scope 重算并清除 universe 外残留 code，自动执行频率需在全市场容量 gate 后确定。
- `audit --mode structure` 是 Mongo 快速结构审计，并要求 `source_exclusions[]` 中的 code 在对应 slot 没有因子残留；所有 mode 都从同一 XTData client 读取 `OpenDate` / `IsTrading` 以保持 coverage 一致，`--mode tail` / `--mode full` 还会重新读取 XTData source bars 并验证递推恒等式。excluded code 在 source audit 中始终按完整 BFQ 区间复核：仍为空才通过，bars 恢复时要求重建；正式全市场 gate 使用 `--mode full`。

## 排障点

### producer 无数据

- 检查 XTQuant 是否在线。
- 检查 `XTQUANT_PORT`。
- 检查订阅池是否为空。
- 检查最新 `xt_producer` 心跳里的 `rx_age_s`、`tick_count_5m`、`tick_quote_pending_batches`、`tick_quote_dropped_batches`。
- 若 `connected=1`、`subscribed_codes>0`，但 `rx_age_s` 在交易时段持续增长且 `tick_count_5m=0`，优先判断为 producer 订阅/回调链 stale，而不是先怀疑 `minqmt` 客户端配置。
- 检查 `subscription_guard` 事件是否已触发自动 `resubscribe` / `reconnect`；若仍不恢复，再按宿主机运行面入口重启 `market_data`。

### consumer 不更新

- 检查 Redis bar 队列是否持续堆积。
- 检查 `monitor.xtdata.mode` 是否匹配。
- 检查 prewarm 是否异常退出。

### Kline 页面停在旧 bar

- 检查 Redis realtime cache 是否更新。
- 检查 `/api/stock_data` 是否启用了 realtime cache。
- 如果页面出现周末/节假日 Kline，先查 `freshquant.stock_realtime` 与 `freshquant.index_realtime` 对应日期是否存在 `source=xtdata` 行；这些行属于实时表脏数据，需要先备份后删除，并同步清理受影响的 `CACHE:KLINE:<code>:<period>` Redis 缓存。

### TPSL 不收到 tick

- 检查 tick 分片队列是否有目标 code。
- 检查 producer 是否在向 `REDIS_TICK_QUEUE_PREFIX:<shard>` 推送。

### QFQ shadow 不更新

- 检查 `fqnext_xtdata_qfq_worker` Supervisor 状态与 `D:/fqdata/log/fqnext_xtdata_qfq_worker_err.log`。
- 执行 `python -m freshquant.market_data.xtdata.qfq_worker worker --once`，区分 `waiting_for_bfq`、`current`、`published` 与错误结果。
- 执行 `status --strict` 核对 active 截止日与盘后 marker，执行 `audit --scope stock|etf --mode full` 对 active slot 做 XTData source-aware 审计；快速排查可先用 `--mode structure`。
- 页面仍读取旧 Stock / ETF 因子；shadow 集合已更新但页面未变化，不代表 QFQ worker 失败。
