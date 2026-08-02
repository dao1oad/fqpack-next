# CLX 日线选股

## 职责

`clx_daily_selection` 是独立于旧 `/daily-screening` 的 18 模型日线选股链，负责：

- 以冻结的 `production_v1 / switch_opt=1` profile 计算 `S0000-S0017`
- 以 `clx-daily-selection.v2` 保存 Stock+ETF canonical QFQ snapshot pair 与 pair hash
- 分别消费股票、ETF 盘后 ready marker，独立生成不可变 partition 输出
- 在页面明确展示 partial，但只把双 partition 校验通过的 batch 标为 final
- 提供批次、结果、解释证据、统计和单标的历史 marker API
- 为桌面 `/clx-daily-screening` 与 `/kline-slim` 提供同一套服务端事实

旧 `/daily-screening` 的 12 模型 scope、集合和 `daily_screening_ready` marker 保持原语义，不参与本模块的 partition、batch 或默认页面结果。

## 代码入口

- 计算合同：`freshquant/clx_daily_selection/contracts.py`
- 计算服务：`freshquant/clx_daily_selection/service.py`
- 原生引擎 adapter：`freshquant/clx_daily_selection/engine.py`
- 日线数据 provider：`freshquant/clx_daily_selection/market_data.py`
- Mongo repository：`freshquant/clx_daily_selection/repository.py`
- HTTP blueprint：`freshquant/rear/clx_daily_selection/routes.py`
- Dagster job：`fqdagster.defs.jobs.clx_daily_selection`
- Dagster sensor：`fqdagster.defs.sensors.clx_daily_selection`
- 页面：`morningglory/fqwebui/src/views/ClxDailyScreening.vue`
- 页面合同：`morningglory/fqwebui/src/views/clxDailySelection.mjs`
- Kline CLX 投影：`morningglory/fqwebui/src/views/js/kline-slim-clx.mjs`

## 计算 profile

正式 profile 固定为：

- `evaluation_profile_id=production_v1`
- `switch_opt=1`
- `algorithm_version=clx18-production-v1`
- `data_version=qfq-daily-v1`
- `wave_opt=1560`
- `stretch_opt=0`
- `trend_opt=0`
- `bar_count=1200`
- 模型目录：`S0000-S0017`

`fqcopilot.fq_clxs_all(..., switch_opt=1)` 的第 `m` 行对应生产单模型 `fq_clxs(..., model_opt=10000+m)`。旧批量默认 `switch_opt=0` 只属于 `legacy_sall_v0` 兼容口径，不进入新日选、默认历史或 final 统计。

Schema v2 要求每个新 generation 冻结同一个完整 QFQ snapshot pair。pair 的 `stock / etf` 两侧都包含 `scope / active_slot / collection / snapshot_id / factor_asof / published_at / effective_version / source_exclusions[]`；`effective_version` 等于本次严格读取使用的 `snapshot_id`。`source_exclusions[]` 只保留稳定的 `code / reason` 并按二者排序，规范化后的完整 pair 参与 canonical hash。

服务优先调用 production batch。当前本机运行时没有可用 production batch 入口时，adapter 会逐个调用 `10000..10017`，写入 `calculation_mode=single_model_fallback`；完全缺少 `fq_clxs_all` 时 `fallback_reason=fq_clxs_all_unavailable`，旧批量签名缺少 `switch_opt` 时为 `fq_clxs_all_missing_switch_opt`，两种情况都不回退到 switch0。`qfq-daily-v1` 同时要求进入计算的每个 bar 日期都由 active QFQ snapshot 提供有限且大于 0 的复权因子，不以 `adj=1` 或未复权数据继续计算。规划阶段只对目标日 BFQ 行做 strict-reader availability probe；该 probe 的 `QFQ_DATA_NOT_READY` 标的进入有证据的隔离集合，完整 1200-bar 读取或模型计算阶段的逐标的异常仍按零容忍使本侧 partition 失败。

## fork-join 调度

### 独立启动

- `stock_postclose_ready(trade_date)` success 后，`clx_daily_selection_stock_sensor` 只读取股票 marker，并立即规划股票 partition。
- `etf_postclose_ready(trade_date)` success 后，`clx_daily_selection_etf_sensor` 只读取 ETF marker，并立即规划 ETF partition。
- 任一侧的 marker 缺失、运行中或失败都不阻塞另一侧计算启动。

三个 CLX sensor（stock、ETF、finalizer）不只检查最新一天，而是 newest-first 扫描最近 5 个已完成交易日。交易日解析以项目时区和交易日历为准，当天必须到 `15:05` 才进入候选；周末、节假日和未收盘当天不会被误判为已完成交易日。每个 sensor 每 tick 最多返回一个 `RunRequest`：marker 缺失或计划为 `reuse/wait` 时继续扫描旧日，`active` 立即停止本轮，`run` 立即派发并返回。这个有界追赶窗口用于自动找回 D+1 延迟 marker、失败 partition 的 `attempt_no=2+` 和旧日 publication retry。

每侧独立保存：

- `selection_key`
- `attempt_id / attempt_no`
- `marker_snapshot / marker_snapshot_hash`
- 完整 `qfq_snapshot_pair / qfq_snapshot_pair_hash` 及两侧 snapshot id
- 冻结的 `effective_instruments / effective_universe_hash`
- `universe_evidence`：candidate/effective 数量与 hash、marker source exclusions、strict-reader isolations 及 isolation hash
- `input_snapshot_hash`
- `partition_id / content_hash`
- `status / claim_owner / claim_token / lease_expires_at / error`

`selection_key` 同时包含本侧 post-close marker hash、完整 Stock+ETF QFQ pair hash 和本侧 `effective_universe_hash`。因此，同一交易日任一本侧 marker、任一个 QFQ snapshot 或本侧有效标的集合改变，都会形成新的 selection key；QFQ pair 改变会同时切换 Stock、ETF 两侧 batch generation。旧 partition 保留为不可变历史，不会被原地覆盖。Schema v1、缺 canonical pair/hash 或缺 effective-universe hash 的旧结果按 stale 处理，不进入 v2 复用。finalizer 只 join 当前完整 selection key 对应、pair/hash 相同且各自有效标的合同完整的两个输出。

规划 partition 时先写 `attempt_status=scheduled` 和 9 分钟 claim lease；job 开始执行时以 compare-and-set 原子领取为 `running`，写入以 Dagster `run_id` 为主的 `claim_owner`、唯一 `claim_token`，并把 lease 延长为 6 小时。提交前必须用同一 owner/token 且未过期的 running claim 原子切为 `committing`，commit lease 为 1 小时；不可变明细、partition 头和 attempt completion 都由该 owner/token fencing。重复 executor 只复读 active 状态，不进入计算；旧 worker 在 claim 过期或被新 attempt 取代后不能提交。scheduled、running 或 committing lease 到期后，原 attempt 原子标为 `claim_expired`，新建递增 `attempt_no` 与新 run key。同一 `selection_key` 已有 completed partition 时直接复用，已成功侧不重复计算。

### 输入冻结与漂移

规划 attempt 前，服务通过严格 QFQ reader 解析 Stock+ETF 两侧 active snapshot，按目标交易日规范化 canonical pair。Stock 与 ETF 各自只规划本侧 raw candidate universe：先按 marker 中通用的 `source_exclusions` 规范化代码并剔除，再对其余标的的目标日 BFQ 行调用 shared strict reader，且要求返回 metadata 与冻结 pair 完全一致。只有错误码为 `QFQ_DATA_NOT_READY` 的逐标的 probe 会被隔离；隔离事实保存 `code / classification / error_code / reason / source` 及 count/hash，`missing_dates` 非空时统一分类为 `target_date_not_covered_by_active_qfq_snapshot`，其他异常在创建 attempt 前直接向上抛出。最终冻结 strict-QFQ-effective universe，断言它与 marker exclusions 无交集且非空，并保存完整 instruments/hash；不向 QFQ marker 伪造新的 `source_exclusions`。

一侧 source exclusion 或目标日缺 QFQ proof 不阻塞另一侧规划，也不让少量已分类异常停掉整个 scope。attempt 执行阶段只读取已冻结的 effective instruments，不重新枚举 raw universe；重试复用同一 marker/pair 下的冻结有效集合。candidate、effective、source-excluded、reader-isolated 的数量必须守恒，任一残余交集、hash/count 不一致或未分类异常都在零 attempt 或零提交边界 fail-closed。

partition 在计算前后各解析一次本侧 ready marker 和完整 Stock+ETF QFQ pair，以 attempt 冻结的 `effective_universe_hash` 重新构造 current selection key，并与规划时冻结的完整 `selection_key` 对比。每只标的的完整历史严格读取还必须返回与 attempt 一致的 `snapshot_id / factor_asof / effective_version / collection` provenance。任一阶段发生 marker 或 pair 漂移、或逐标的 provenance 不一致时，本侧 attempt 结束为 `upstream_drift` 或计算失败，本次输出不提交；另一侧旧 pair 的成功输出保持不可变历史，但新 pair generation 会让两侧 selection key 都失效并重算。

finalizer 读取当前 marker 时，也会重新解析 canonical QFQ pair。任一侧 marker 缺失会把该侧投影为 `status=waiting / upstream_status=marker_missing`；QFQ pair 未 ready 时投影为 `status=waiting / upstream_status=qfq_not_ready`。若同交易日 marker 或 pair 已更新，完整 current selection key 会形成新的 batch generation；旧 generation 的 failed/pending final 内容保留审计，但不会继续 publication。

### partial 与 final

每个 partition 完成后都会刷新 batch 状态。partition attempt 审计保留 `scheduled / running / committing / completed / failed / claim_expired / upstream_drift`；公共 batch partition 状态把 scheduled/committing 映射为 running、claim_expired 映射为 failed，同时在 `attempt_status` 保留原值。batch 的两个分区可分别处于 `waiting / running / completed / failed / upstream_drift / stale` 等状态：

- 只有一侧完成时，`release_status=partial`、`is_final=false`。
- partial 只包含已完成 partition 的事实，可显式查看，不代表股票与 ETF 的完整发布。
- `clx_daily_selection_finalizer_sensor` 只有在两个不可变 partition 都 completed 后才派发 finalizer；它先在 `finalization_attempts` 创建带 9 分钟 dispatch lease 的 `scheduled` attempt。job 以 owner/token CAS 领取为 `running`，运行 lease 为 10 分钟；前置失败、租约过期或完成分别保留 `failed / claim_expired / completed` 审计。每次 dispatch 使用新的 `finalization_attempt_no` 与 run key，避免 Dagster 对失败 run key 的永久去重阻断重试。
- finalizer job 必须携带 `trade_date / batch_id / partition_ids / finalization_attempt_id / finalization_attempt_no / qfq_snapshot_pair_hash / Stock+ETF snapshot_id / generation_order` tags。job 先按 attempt id 读取持久化计划，再逐项强校验 tag 与持久化事实；不一致直接失败，不根据运行时 tag 临时改写计划。
- finalizer 合同校验通过后先写不可变 final 内容；publication 初始为 `pending`，以 `claim_owner / claim_token / attempt_count / lease_expires_at` 做 CAS 后进入 `publishing`，成功为 `published`，marker 写入异常为 `failed`，未配置 publisher 的受控运行面为 `not_required`。publishing claim 的 lease 为 2 分钟；只有持有同一 owner/token 的发布者能把 publishing 推进为 failed/published。过期或 failed publication 以递增 `attempt_count` 独立重试，不重算 partition。
- publication 身份固定为 `generation_id / generation_order / publication_id`。Schema v2 的字典序键按 `v2 | 两侧 post-close marker UTC 时间 | 两侧 QFQ published_at | 两侧 factor_asof | canonical pair hash | 两侧 partition completed_at | batch_id` 组成。权威 upstream generation 始终排在下游完成时间之前，因此“新 pair 较早完成、旧 pair 较晚完成”时仍由新 pair 排序更大；`v2` 前缀也使新合同不会被旧时间开头格式误判为更旧。相同 `publication_id` 的重试幂等成功。若新 generation 已先写入 ready marker，迟到旧 publisher 会收到 `stale_publication`，旧 batch 的 publication 保持 `failed` 并记录结构化 `last_error`，不会被推进为 `published`。

finalizer 在发布前校验两侧：

- 同一 `trade_date`，且各自 marker 的交易日与 partition 一致
- `production_v1 / switch_opt=1`
- `algorithm_version / data_version / parameter_hash`
- `schema_version / condition_catalog_version / line_definition_version`
- 两侧完整 `qfq_snapshot_pair / qfq_snapshot_pair_hash` 相同，且各自 effective-universe hash/evidence 完整，selection key 可由当前 marker、pair、effective hash 与 profile 重建

任一字段不一致时，batch 保持非 final，并标记 `contract_mismatch`。默认批次查询只返回 `is_final=true` 且 `publication.status` 为 `published/not_required` 的记录；`pending/publishing/failed` 虽保留不可变 final 内容，但公共投影为 `release_status=partial / is_final=false`，只能通过显式 partial 视图观察。partial 页面只展示已完成侧及其明确的分区/发布状态，不冒充正式发布。

## 结果与解释合同

### partition 输出

每个不可变 partition 包含：

- candidate/effective universe、source exclusion、strict-reader isolation、成功评估、命中标的、信号事件和错误计数
- marker、输入和内容 hash
- canonical `qfq_snapshot_pair / qfq_snapshot_pair_hash`、`effective_universe_hash / universe_isolation_hash / universe_evidence` 与逐标的 QFQ input provenance hash
- `memberships`：标的 × 模型 × 触发事实
- `snapshots`：标的级模型/条件去重摘要与线关系
- `model_stats`：本资产分区内的模型命中统计

### symbol 级错误隔离

- partition 会隔离单个 symbol 的计算异常，继续遍历同侧其余 symbol，以便一次收集完整的 `errors[]` 诊断；每条错误包含 `symbol / type / message`。
- 当前发布门禁是零容忍：只要 `counts.error_count > 0`，本侧 attempt 就以 `PartitionInstrumentError` 失败，不提交已成功 symbol 的不可变 completed partition。
- 这里的“隔离”只表示错误不会中断其余 symbol 的诊断计算，不表示带错误的 partition 可以发布或进入 finalizer。
- 单侧失败后只创建该侧下一 `attempt_no`；另一侧已有 completed partition 时直接复用，不重复计算。
- partition 外层异常或 `upstream_drift` 同样阻断本侧 completed；finalizer 仍只接受两个 completed partition。任何单侧可见中间态都保持 `is_final=false`。

批次结果默认按：

`distinct_model_count DESC -> distinct_condition_count DESC -> symbol ASC`

排序，支持资产、模型、条件、方向、代码/名称和最少模型数筛选。

### membership

`model_id` 不从 raw signal 反推，membership 分开保存：

- `model_key / production_model_id`
- `signal_value_raw / signal_direction / occurrence`
- `primary_entrypoint`
- `model_condition`
- `condition_evidence[]`

S0002 entrypoint 3 额外使用 `fq_s0002_entrypoint3_evidence` 区分吞没与普通分型兜底。没有结构证据时保留 raw signal，并把条件状态记为 `unknown`；unknown 不折叠成 false。

`above_ma250`、`above_chanlun_line`、`above_reference_line` 是相互独立的三态字段。当前 MA250 根据有效日线计算；缠论连线和模型参考线在没有正式来源时保持 `unknown`。

## HTTP API

- `GET /api/clx-daily-selection/health`
- `GET /api/clx-daily-selection/model-catalog`
- `GET /api/clx-daily-selection/batches`
- `GET /api/clx-daily-selection/batches/latest`
- `GET /api/clx-daily-selection/batches/<batch_id>/summary`
- `GET|POST /api/clx-daily-selection/batches/<batch_id>/results`
- `POST /api/clx-daily-selection/batches/<batch_id>/results/query`
- `GET /api/clx-daily-selection/batches/<batch_id>/results/<asset_type>/<symbol>`
- `GET /api/clx-daily-selection/batches/<batch_id>/statistics`
- `GET /api/clx-daily-selection/history/signals`

`/batches` 与 `/batches/latest` 默认只返回 publication 已完成（`published/not_required`）的 final；显式传 `include_partial=1` 才把普通 partial 以及 `pending/publishing/failed` publication 纳入候选，后者对外仍投影为 partial。

`/history/signals` 当前只接受 `period=1d`，`barCount` 范围为 `1..2000`。`endDate` 可显式传入；省略时由 provider 解析该标的最新交易日。响应包含 bar 等长的模型序列、压缩 marker、bar 等长的 `line_series`（当前正式计算 MA250，其他未接入连线保持 unknown）、`calculation_profile`、`future_function_guard`、`input_bar_asof`、实际 `end_date`、`query_hash`，以及真实的 `qfq_snapshot_id / qfq_factor_asof / qfq_effective_version / qfq_provenance`。HTTP ETag 同时绑定 `query_hash` 与 `qfq_effective_version`，并返回 `X-QFQ-Effective-Version`，QFQ snapshot 切换后旧缓存不会继续命中。

## 存储

数据库：`freshquant_clx_daily_selection`

- `partition_attempts`
- `partitions`
- `memberships`
- `snapshots`
- `model_stats`
- `finalization_attempts`
- `batch_statuses`

`partitions` 按含 canonical pair hash 与 effective-universe hash 的 `selection_key` 唯一；相同 key 只接受相同 `content_hash`。`partition_attempts / partitions / batch_statuses / finalization_attempts` 保存完整 pair/hash 及有效标的/隔离 hash；ready marker 同时发布 pair/hash、两侧 snapshot id、两侧 effective/isolation hash 和精简 `universe_evidence`。`memberships / snapshots / model_stats` 通过 `partition_id` 绑定不可变输出。`partition_attempts` 保存 scheduled/running/committing owner-token lease 与 `claim_expired` 审计。`finalization_attempts` 按 `(batch_id, attempt_no)` 唯一，保存 dispatch/run claim、两个持久化 partition id 和 `scheduled/running/failed/completed/claim_expired` 状态。`batch_statuses` 保存当前 partial 状态和独立 publication 状态；一旦 final 内容写入，只接受相同 final `content_hash`，publication 使用 owner/token CAS 独立推进或重试。

ready marker 仍写在主库 `freshquant.dagster_pipeline_markers`：

- 输入：`stock_postclose_ready`、`etf_postclose_ready`
- 输出：`clx_daily_selection_ready`

## 桌面页面

### `/clx-daily-screening`

- 顶部展示交易日、profile、算法/数据版本、股票/ETF partition 和 partial/final 状态。
- 默认选择最新 `published/not_required` final；用户可显式切换并查看 partial 或 publication 中间态。
- 页面把 `/batches/latest` 的权威 final 合入最近 30 条混合批次列表；URL 显式 `scope_id` 不在该窗口时，先以 `/batches/<batch_id>/summary` 取回并稳定去重加入列表。权威 summary 决定该 scope 的 partial/final 状态，只有 final 才请求和展示跨资产统计。
- 左侧按资产、模型、条件、方向、三态线关系和最少模型数筛选。
- 中栏显示服务端排序结果与分页；统计和批次页签展示 final 统计或独立 partition 元数据。
- 右栏显示 raw signal、entrypoint、model condition 和 evidence。
- 选中标的可带 `scope / model / condition` query 深链到 `/kline-slim`。

### `/kline-slim`

- 左栏新增 `CLX日线选股` section，显示 scope、股票/ETF partition 状态，并按模型数、条件数、symbol 排序。
- 标的 hover 展示模型、条件、最近触发、scope 和 profile 摘要。
- 右侧 `CLX 信号工作台` 分为“显示控制 / 信号时间轴 / 信号详情”。
- 历史 marker 通过 `/history/signals` 加载，模型/条件筛选只控制可见性。
- marker 会按当前日/周/月 K 线日期锚定，并由 chart renderer 生成真实 ECharts scatter series；同日 marker 可聚合或逐条显示，点击 marker 会联动时间轴和证据详情。
- 只有历史响应满足 `production_v1 / switch_opt=1` 且 `future_function_guard.passed=true` 时，CLX series 才进入可见状态。

## 部署与健康检查

- `freshquant/clx_daily_selection/**` 或 `freshquant/rear/clx_daily_selection/**` 变更：重建 API Server；同时重启 Dagster Webserver / Daemon 以加载服务代码。
- `morningglory/fqdagster/**` 变更：重启 Dagster Webserver / Daemon。
- `morningglory/fqcopilot/**` 变更：重新构建并安装原生扩展，再重建/重启消费该扩展的 API 与 Dagster 运行面。
- `morningglory/fqwebui/**` 变更：重新构建 Web UI。

正式部署后至少检查：

```powershell
Invoke-RestMethod http://127.0.0.1:15000/api/clx-daily-selection/health
Invoke-RestMethod http://127.0.0.1:15000/api/clx-daily-selection/model-catalog
Invoke-RestMethod http://127.0.0.1:15000/api/clx-daily-selection/batches/latest
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18080/clx-daily-screening
```

健康接口应报告原生 batch、单模型和 S0002 evidence 能力；`model-catalog` 应返回 18 个模型和 `production_v1 / switch_opt=1`。没有 `published/not_required` final 时，默认 `batches/latest` 可以返回较早已发布 final 或 `no_ready_batch`；`pending/publishing/failed` 与普通 partial 都不能充当 final 健康证据。

## 排障

### 一侧已经完成但页面仍显示 partial

- 这是 fork-join 的正常中间态；先看 batch 的 `partitions.stock / partitions.etf`。
- 查未完成侧对应的 ready marker 和 partition sensor，不要重跑成功侧。
- 两侧都 completed 后，再看 finalizer sensor 与 `clx_daily_selection_ready`。

### 旧交易日 marker 或失败重试没有被找回

- 确认当前时间与项目时区；交易日当天 `15:05` 前不会进入 completed-date 候选。
- 查看三个 sensor 是否按 newest-first 得到最近 5 个已完成交易日；D+1 延迟 marker、失败 partition attempt 和旧 publication 都必须在这个窗口内。
- `reuse/wait` 应继续扫描旧日，`active` 应停止本轮，`run` 应立即返回；每个 sensor tick 最多只有一个 `RunRequest`。
- 窗口外日期不属于自动追赶范围，需要显式 backfill。

### 同一侧重复计算或重试没有增加 attempt

- 查 `partition_attempts.selection_key / attempt_no / status`。
- 同时查 `claim_owner / claim_token / lease_expires_at`；未过期的 running/committing claim 只能由原 owner/token 提交。
- 查 partition run tags 中的 `fq_trade_date / fq_clx_asset_type / fq_clx_attempt_id / fq_clx_attempt_no / fq_clx_selection_key / fq_clx_marker_snapshot_hash / fq_clx_qfq_snapshot_pair_hash / fq_clx_qfq_{stock,etf}_snapshot_id / fq_clx_effective_universe_hash / fq_clx_universe_isolation_hash`，并与持久化 attempt 完全一致。
- completed selection 应复用；failed、`claim_expired` 或 `upstream_drift` 才创建下一 attempt。

### 两侧 completed 但默认 latest 没有新 batch

- 先查 `finalization_attempts.batch_id / attempt_no / status / lease_expires_at`。scheduled 9 分钟或 running 10 分钟 lease 过期后应标为 `claim_expired`，下一次 sensor 使用新的 dispatch attempt/run key。
- 核对 Dagster tags 的 `fq_trade_date / fq_clx_batch_id / fq_clx_partition_ids / fq_clx_finalization_attempt_id / fq_clx_qfq_snapshot_pair_hash / fq_clx_qfq_{stock,etf}_snapshot_id / fq_clx_generation_order` 与持久化 attempt 完全一致。
- 查 `batch_statuses.publication.status / attempt_count / lease_expires_at / last_error`。
- `pending` 等待 finalizer publication；未过期 `publishing` 表示已有发布者持有 owner/token claim，不应并发重复发布。
- `failed` 或过期 `publishing` 只重试 ready marker publication；两个 completed partition 保持不可变。
- `last_error.code=stale_publication` 表示更新的 generation 已先发布；旧 batch 必须继续保持 failed，不应手工改为 published。同一 `publication_id` 的幂等重试则应复读现有 marker 并成功收敛。
- 只有 `published/not_required` 会进入默认 latest；显式 `include_partial=1` 可查看发布中间态。

### finalizer 等待 marker 或报告 generation drift

- 任一当前 marker 缺失时，finalizer 返回 waiting，并在该侧写 `upstream_status=marker_missing`；另一侧 partition 事实仍可作为 partial 查看。
- 若 sensor 规划后 marker、canonical QFQ pair、generation order 或当前 partition id 改变，执行结果为 `generation_drift`，本次 `finalization_attempt` 记为 failed。
- 不重放旧 generation 的 pending/failed publication；等待新 generation 两侧 completed 后创建新的 finalization attempt。

### partition 结束为 `upstream_drift`

- 比较 attempt 中冻结的完整 `selection_key` 与由当前本侧 marker snapshot、完整 canonical QFQ pair、冻结 `effective_universe_hash` 和 profile 重建的 current selection key。
- 同时核对逐标的 `snapshot_id / factor_asof / effective_version / collection` provenance；确认漂移来自 marker 还是 QFQ pair。
- 仅 marker 漂移时重试对应侧；QFQ pair 漂移会让 Stock、ETF 两侧 selection key 同时失效，必须形成新的双 partition generation。

### Kline 没有 CLX marker

- 先直接请求 `/api/clx-daily-selection/history/signals`，确认 `period=1d`、`endDate`、symbol 和 asset type 正确。
- 确认响应为 `production_v1 / switch_opt=1`，且 `future_function_guard.passed=true`。
- 确认 marker 的 `trigger_date` 能落到当前 K 线日期范围，页面 `CLX信号` 已开启，模型/条件筛选没有把 marker 排除。
- renderer 中应存在 `clx-signal-<sceneScopeId>` scatter series；只有列表数据而没有该 series 不算已绘制。
