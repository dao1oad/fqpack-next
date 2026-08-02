# Devin Ultra 单轮评审记录：CLX 日线选股与 Kline Slim 工作台

- 评审日期：2026-07-31（北京时间）
- 评审方式：按 `send-task-to-devin` 技能发起一次 `devin-ultra` Responses 请求
- 工作区：`D:\fqpack\freshquant-2026.2.23`
- 输入任务：`D:\fqpack\runtime\tmp\issue480-devin-clx-design-task.txt`
- 被评审文档：`docs/plans/2026-07-31-clx-daily-selection-workbench-design.md`
- Devin 输出附件：`https://app.devin.ai/attachments/d26c8d36-384d-4d7c-9fe3-3581a77ac3cb/clx-design-review.md`
- 单轮结果：Devin 返回“有条件采纳”的红队结论，摘要明确指出 3 项 P0、7 项 P1、6 项 P2，并给出 A–G 逐项审查、M1–M11 验收补充和 6 个待裁决问题。Devin 以只读方式读取方案与相关 Dagster 文件，没有改动仓库、没有实现代码、没有部署、没有推送。

## 1. 总体结论

Devin Ultra 认可独立 CLX 命名空间、服务端事实与统计分离、服务端历史 batch 封装、结果页与 Kline Slim 深链互通这条主线；其原始调度门控意见已被 2026-08-01 用户确认的 partition fork-join 决策覆盖。当前正式口径是 stock/ETF marker 各自 success 即启动本侧 partition，双侧 success 只门控 finalizer、正式发布和跨资产统计。采纳的其余前提是先冻结“计算 profile”和本侧上游 marker 快照，再把 partition 幂等、批量参数、原始编码解释、部分失败和机器验收写成硬合同。最终本地复核进一步把正式历史入口收敛为 `production_v1`（`switch_opt=1`），现有 switch0 只作为 `legacy_sall_v0` 只读保留。UI 方向建议保留“状态头 + 筛选 + 结果列表 + 分层统计 + 详情抽屉”，把复杂图表和工作台操作按页签/抽屉分层，减少 18 模型带来的认知负荷。


## 1.1 2026-08-01 用户确认的架构修订（覆盖旧双门控结论）

本修订发生在 Devin 单轮评审之后，属于用户确认的正式实现决策，不回写为 Devin 原始意见。股票与 ETF 不再互相阻塞计算启动：各自 marker success 立即触发独立 CLX18 partition，使用独立 `partition_selection_key/attempt/marker_snapshot_hash/drift`，单侧失败只重试失败侧。任一成功 partition 可提供明确 partial；只有 finalizer 在两侧不可变输出均成功并通过同交易日、`production_v1/switch_opt=1`、算法/数据/解释版本一致性校验后，才发布 final、跨资产统计和页面默认完整结果。

后续并发审计把 sensor 恢复窗口和 marker publication 进一步收敛为候选硬合同：三个 sensor newest-first 扫描最近 5 个已完成交易日，项目时区当天以 `15:05` 为 cutoff，每 tick 最多一条 RunRequest；`reuse/wait` 继续旧日，`active` 停止，`run` 返回，从而找回 D+1 延迟 marker、失败 partition attempt 2 和旧日 publication retry。ready marker 采用规范 UTC `generation_order` 与不可变 `publication_id` CAS；相同 publication id 幂等，迟到旧 generation 显式失败为 `stale_publication`，旧 batch 保持 failed，不能覆盖新 marker 或被标为 published。该增量需要最终组合回归与部署后 smoke 形成交付证据。

## 2. P0 问题与处理决定

### P0-1：批量参数组与 S0015 特殊语义

**问题**：`fq_clxs_all` 一次接收一组 `wave_opt/stretch_opt/trend_opt`，而 S0015 将第三参数解释为 `ext_opt`；其他模型和生产单模型使用的 `switch_opt`/model id 语义不能直接混合。初版只写了“trend_opt=0 或 250 表示 MA250”，还缺少批量与生产单模型的对账门槛。

**影响**：批量历史序列与 `fq_clxs(model_opt=10000..10017)` 可能出现模型级差异，页面会把未对齐的结果当成同一算法版本。

**最终处理**：新增不可变 `evaluation_profile`，并依据当前代码复核把正式口径收敛为 `production_v1`：production batch 必须把现有硬编码的 `switch_opt=0` 参数化为 `switch_opt=1`，其第 `m` 行逐 bar 等价于 `fq_clxs(..., model_opt=10000+m)`。现有 switch0 结果单独标记为只读 `legacy_sall_v0`，不进入新日选、默认历史或跨 profile 统计。当前静态分支与 donor 扩展动态对比均显示 S0001、S0002、S0005、S0009、S0010、S0011、S0012 七个模型在 switch0/1 下存在差异，因此这不是可忽略容差。profile 同时固定输入复权口径、bar 数、`wave_opt`、`stretch_opt`、`trend_opt/ext_opt`、源码 commit 和参数 hash；S0015 显式记录实际 MA 周期。上线前执行 18 个模型、多标的、多样本日的逐 bar 精确对账；对账不通过时，profile 进入 `contract_mismatch`。若需要 S0015 专用参数，方案允许将 S0015 作为第二批次单独计算后按同一 `production_v1` 合并，数据模型保留 `calculation_pass`，避免隐式覆盖。

### P0-2：run_key 与失败重跑

**问题**：初版同时写“run_key 相同则跳过”和“failed 可用相同 key 重跑”，与 Dagster 的 run 去重语义存在冲突。

**最终处理（经 2026-08-01 修订）**：每个资产 partition 使用 `partition_selection_key = trade_date|asset_type|marker_snapshot_hash|universe_version|evaluation_profile_id`、独立 `attempt_no` 和 `run_key`。规划写带 9 分钟 lease 的 `scheduled`，执行以 `claim_owner / claim_token` CAS 进入带 6 小时 lease 的 `running`，提交前再由同一 owner/token 且未过期的 claim 进入带 1 小时 lease 的 `committing`；重复 executor 不计算，过期旧 worker 不能提交。租约过期标为 `claim_expired` 并以新 attempt/run key 重派。sensor 只查询本资产侧 active/success 状态；失败侧新建 attempt，成功侧直接复用。

finalizer sensor 使用两个不可变 `partition_id` 形成 batch generation，并在 `finalization_attempts` 持久化 trade date、batch、partition ids 和 dispatch attempt。scheduled/running lease 分别为 9 分钟/10 分钟，失败或过期 dispatch 使用新的 attempt/run key，避免 Dagster 去重阻断；job 按 `finalization_attempt_id` 读取计划并强校验 tags。ready marker publication 通过带 owner/token CAS 的 2 分钟 claim 独立经历 `pending/publishing/failed/published`（无 publisher 时为 `not_required`）；marker 缺失只等待，generation 漂移不发布旧 failed/pending final，默认 latest final 只消费 publication 已完成的 batch。publication identity 使用规范 UTC generation order；相同 publication id 重试幂等，迟到旧 generation 以 `stale_publication` 失败并保留旧 batch failed。

### P0-3：marker 覆盖与输入冻结

**问题**：只用 marker 名称和日期可能遇到同日重跑、跨时区写入或上游 marker 被覆盖，导致 CLX 读到混合输入。

**最终处理（经 2026-08-01 修订）**：stock/ETF partition 分别冻结自己的 marker 字段并生成独立 `marker_snapshot_hash`。计算前后只核对本侧 hash；漂移只使本 partition 结束为 `upstream_drift`，另一侧成功输出保持可复用。finalizer 再校验两个输出的 trade_date/profile/version 合同。

## 3. P1 议题与整合

1. **事实口径**：`distinct_model_count`、`distinct_condition_count`、`signal_event_count` 分列存储；列表默认按去重模型数降序，再按条件数、最新触发时间、代码稳定排序。任何图表都显示分子、分母、未知数和成功评估 universe。
2. **原始 signal 与条件解释**：raw 编码可能存在 occurrence/entrypoint 组合碰撞，且只保留优先级最高的 entrypoint，解码不依赖 raw 数字反推 model。membership 分层保存 `signal_value_raw`、显式 `model_key/model_id/occurrence`、可 re-encode 的 `primary_entrypoint`、模型结构分支 `model_condition` 和事实依据 `evidence[]`。S0002 的 entrypoint 3 既可能是吞没反包，也可能是普通底/顶分型兜底，必须由 evidence 区分；缺证据时标记 `ambiguous`，未知编码保留原值并标为 `decoder_unknown`。
3. **三态线关系**：`above_ma250`、`above_chanlun_line`、`above_reference_line` 分开，取值为 yes/no/unknown，并带 `as_of、line_value、source、definition_version`。有效日线不足 250 根时为 unknown；unknown 不计入“下方”。
4. **股票/ETF 分母**：summary 同时返回 stock、ETF、合计三组分母，模型目录带 `eligible_asset_types`。首版页面默认合计视图但分组显示，行业统计只对股票分母计算。
5. **部分失败**：partition attempt 审计状态为 `scheduled/running/committing/completed/failed/claim_expired/upstream_drift`；对外 partition 状态继续明确 `waiting/running/completed/failed/upstream_drift/stale`，合同不一致记录在 batch 的 `contract_mismatch`。finalization attempt 状态为 `scheduled/running/failed/completed/claim_expired`，publication 状态为 `pending/publishing/failed/published/not_required`。页面显示 stock/ETF 各自状态、attempt 和分母；partial 与 publication 未完成的 final 内容都不进入默认完整结果，单侧失败或 claim 过期只重试该侧。
6. **历史接口**：`/history/signals` 只接受 `period=1d` 的日线计算输入，返回 bar 等长校验、计算范围、有效 bar 数、future-function guard。分钟图以交易日背景/收盘锚点呈现日线信号，周月图按周期聚合，不把收盘后结果画成开盘已知。
7. **性能与安全**：summary/query 采用 cursor、facet 预聚合、`run_id+filter_hash` 缓存；历史接口限制 bar_count、模型集合和并发，响应带 ETag、trace_id、schema_version。前端先拿 run meta/KPI/首屏 50 行，图表按 tab/视口延迟加载。

## 4. P2 议题与整合

- 18 个模型使用“模型家族颜色 + S000x 文本 + 图形形状”三重编码，避免只靠颜色。
- 复杂统计采用结果/统计/模型共振/任务记录页签；详情用抽屉，桌面右侧工作台可调宽度，窄屏改底部 sheet。
- 左栏 popover 同时支持 hover、focus、click，摘要随列表返回，逐条件证据首次打开再加载并缓存。
- URL 保存 symbol、scope、trade_date、model set、condition set、line state、range、marker mode；localStorage 只存偏好。
- “筛选条件”固定提示为对既有计算事实的可见性筛选；模型内部公式由服务端 profile 冻结。
- 监控补充 run 延迟、marker 等待时长、模型耗时 P95、decoder_unknown_count、cache 命中率和 API p95。

## 5. A–G 审查结论

- **A Dagster（2026-08-01 修订）**：stock/ETF marker 分别驱动独立 partition sensor；每侧拥有独立 key/attempt/snapshot/drift 与 scheduled/running/committing owner-token claim lease。三个 sensor newest-first 扫描最近 5 个已完成交易日，受 `15:05` cutoff 和每 tick 一条 RunRequest 限制。finalizer 只 join 两个不可变 success output，先持久化独立 finalization attempt，再强校验 Dagster tags；跨时区用交易日和 marker `data_as_of` 校验。marker 缺失只等待，generation drift 不发布旧 final；单侧重试不重算成功侧，ready marker publication 失败只以 owner/token CAS 重试发布，generation CAS 拒绝迟到旧 publisher。
- **B 执行与存储**：第一期保持日级 production batch，按标的并发并记录 calculation_pass；batch 必须使用 `switch_opt=1`，legacy switch0 只读隔离。当规模需要时再按资产类型/分区拆分。membership、snapshot、model_stats 分离，索引围绕 scope、symbol、model、condition、trade_date 建立。
- **C universe/连线**：股票与 ETF 统一 schema、独立分母；年线默认 MA250；连线来源和定义版本写入事实；数据不足使用 unknown。
- **D API/历史**：服务端封装参数化后的 `production_v1` batch（`switch_opt=1`），不复用只返回最后 bar 的 fullcalc，也不把 legacy switch0 当成正式历史；历史响应做长度、日期单调、参数 hash、profile 和 future-function 检查；ETag 与限流保护高频工作台。
- **E UI/UX**：首屏回答“哪些标的、为什么、接下来去哪看”三问；模型共振直方图、覆盖条形图、18×18 矩阵、条件堆叠、线关系堆叠、趋势图为核心，均支持数据表和交叉筛选。Kline 工作台分“显示控制/信号时间轴/信号详情”三个 tab。
- **F 兼容**：新集合、新路由、新 marker 与旧 12 模型链隔离；`production_v1` 与 `legacy_sall_v0` 分 profile 隔离；非法 model id、扩展缺失、S0015 语义不一致均进入 contract_mismatch，不回退为其他模型。
- **G 验收**：除 UI smoke 外，补充 production batch 与 `10000+m` 单模型逐 bar 精确对账、七个 switch 差异模型的回归证据、S0002 entrypoint 3 双义 fixture、marker drift、attempt 幂等、18×模型完整性、membership/snapshot 聚合对账、三态线关系、历史等长和未来函数保护等机器证据；Dagster 还需覆盖 5 日 catch-up、cutoff/周末、D+1 marker、attempt 2、旧 publication retry、每 tick 一条 RunRequest，以及 publication 幂等/迟到 generation fencing。

## 6. 最终共识与未决项

最终实现共识是：先冻结 `production_v1` evaluation profile 和 condition catalog；production 计算必须与 `fq_clxs(...,10000+m)` 逐 bar 等价，legacy switch0 只读隔离。当前本机运行时没有可用 production batch 入口，因此 adapter 严格执行 18 次 production 单模型调用并记录 `calculation_mode=single_model_fallback`；batch 完全缺失时 reason 为 `fq_clxs_all_unavailable`，旧签名缺少 `switch_opt` 时为 `fq_clxs_all_missing_switch_opt`，两种路径都不调用 switch0。stock/ETF marker 各自触发独立 partition，以 partition key/attempt/snapshot hash 和 owner-token fencing 解决重跑、重复 executor 与漂移；三个 sensor 用最近 5 个已完成交易日有界追赶延迟与失败；finalizer 只在双侧不可变输出同日同版本时创建持久化 dispatch attempt，严格校验 tags 后发布 final；publication 另以 owner/token 与 generation-aware CAS 防止旧发布者覆盖新 claim。以 `signal_value_raw + primary_entrypoint + model_condition + evidence[]` 分层解释信号，并以三态关系、partial 警告保护用户判断。

默认值共识：股票与 ETF 都扫描但分组计数；MA250 作为年线；最新成功且完整 scope 为默认 scope；列表按去重模型数降序；工作台历史默认近 250 根或当前可视区，全部历史由用户主动加载；同日多模型 marker 默认聚合；partial/unknown 不折算为完整命中或否定状态。

尚待 Phase 0 落实的事项：production_v1 对账样本集和证据保存格式（整数信号要求逐 bar 精确相等，不设置差异容差）；缠论连线的唯一数据来源；ETF 是否对某些模型设为 excluded；历史缓存保留天数；partial 结果是否允许写入预选池。它们均进入实现前的合同评审，不影响本次方案落盘。

## 7. 结论

本记录保留 Devin Ultra 原始单轮结果，并记录 2026-08-01 用户确认的 fork-join 修订。后续实施以修订后的 partition/finalizer 合同为准；正式交付边界已更新为 feature branch + PR + CI + merge remote main + deploy/health/cleanup。


## 8. 本地补充证据与证据等级

Devin 评审后，本地架构审计又补充了参数差异事实：在 donor 已编译扩展上用 40 组固定种子、每组 600 bars 对比 batch `switch_opt=0` 与 production `10000+m` `switch_opt=1`，差异模型为 S0001、S0002、S0005、S0009、S0010、S0011、S0012，累计差异点分别为 34、445、170、444、355、72、32；其余 11 个模型一致。这个结果直接支持 Devin 的 P0-1：批量 profile 与生产单模型 profile 需要显式对账，不能把不同 switch 语义下的结果视作天然一致。

该补充属于 donor 构建的 V1/V2 前置审计证据，不是当前 checkout 的完整生产验收。早期 checkout 曾有 3 项原生测试因扩展不可导入而 skipped；这是构建完成前的历史记录。2026-08-01 当前 #482 复验已从隔离候选源码构建扩展，并在 `D:\new_tdx\vipdoc` 的 20 个文件、28,847 bars 上完成 360 次 production 单模型调用与 18 模型逐 bar 零差异对账；完整机器事实以 `2026-07-31-clx18-validation-evidence.md` 为准。

## 9. 2026-08-01 实现合同收敛

最终实现将持久化合同收敛到独立数据库 `freshquant_clx_daily_selection` 的七个集合：`partition_attempts`、`partitions`、`memberships`、`snapshots`、`model_stats`、`finalization_attempts`、`batch_statuses`。partition attempt 使用 `scheduled/running/committing/completed/failed/claim_expired/upstream_drift` 状态与 owner/token lease fencing；finalization attempt 使用 `scheduled/running/failed/completed/claim_expired`，每次 dispatch 有独立 attempt/run key。Dagster 正式 job 为 `clx_daily_selection_partition_job` 与 `clx_daily_selection_finalize_job`，由 stock、ETF、finalizer 三个 sensor 驱动；三个 sensor 对最近 5 个已完成交易日 newest-first catch-up，按 `15:05` cutoff 且每 tick 至多一个 RunRequest。finalizer job 按持久化 attempt 强校验 `trade_date/batch_id/partition_ids/finalization_attempt_id` tags，marker 缺失返回 waiting，generation drift 不发布旧 final。publication 通过 owner/token 与 `generation_order/publication_id` CAS 发布 `clx_daily_selection_ready`；迟到旧 generation 记录 `stale_publication` 并保持 failed。历史接口省略 `endDate` 时由 provider 解析最新日线，并返回实际 `end_date` 与 bar 等长的 `line_series`；前端只有在 `production_v1/switch_opt=1` 且 `future_function_guard.passed=true` 时绘制历史 marker。
