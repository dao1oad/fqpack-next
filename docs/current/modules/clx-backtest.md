# CLX 大规模回测

## 职责

CLX 回测模块把同一份不可变行情快照依次转换为：

`Mongo snapshot -> 因果信号事实 -> 事件研究 -> VALIDATION 排行冻结 -> 一次性 HOLDOUT 揭示 -> 组合撮合 -> Mongo 投影 -> API / Web UI`

它用于研究 `S0000`～`S0017` 的单模型、触发类型、触发次数和多模型组合表现，不参与 Guardian 实时下单，也不替代盘后 CLXS 选股链。

## 入口

- 前端路由：`/clx-backtest`
- 研究引擎：`freshquant/backtest/clx/**`
- API 与投影：`freshquant/rear/clx_backtest/**`
- 外部 worker：`python -m freshquant.rear.clx_backtest.worker run`
- 全量 artifact 链：`script/clx_backtest/run_full_artifact_chain.sh`
- Docker 服务：`fq_apiserver`、`fq_clx_backtest_worker`、`fq_mongodb`、`fq_webui`
- Artifact 根目录：容器内 `/opt/clx-backtest`，由 `CLX_BACKTEST_ARTIFACT_ROOT` 指定

API 只提供控制面和派生结果查询；重计算、HOLDOUT 揭示、组合回测和导出都由外部 worker 执行。

## 固定研究合同

当前基线固定为：

- 模型：`S0000`～`S0017`，共 18 个模型
- 原生参数：`wave_opt=1560`、`stretch_opt=0`、`trend_opt=0`
- CLX 输入：前复权 `open/high/low/close` + 原始 `volume`
- 收益与撮合：原始价格域 `RAW`
- 决策时钟：T 日收盘后确认；第一笔委托在下一个市场交易日原始开盘价尝试
- 事件持有期：`1 / 3 / 5 / 10 / 20` 个交易日；当前排行默认使用 5 日
- 分段按 `reveal_date`：
  - `TRAIN`：`2005-01-04`～`2019-12-31`
  - `VALIDATION`：`2020-01-02`～`2023-12-29`
  - `HOLDOUT`：`2024-01-02`～`2026-07-21`
- 相邻分段：固定 `20` 个交易日 purge + `20` 个交易日 embargo
- 组合资金：`10,000,000` 元
- 单票目标权重：`10%`
- 最大持仓：`10`
- 正式组合：按冻结顺序选取 `VALIDATION` 正向组合前 `20`；不足 20 个时取全部
- 退出：对同一 canonical DSL 做严格方向反转；同日负向信号优先退出并否决当日买入

上述值进入 config、manifest 或内容哈希；正式 run 不在执行中静默修改。

## 快照与价格域

### 不可变快照

快照只读 Mongo `quantaxis.stock_day / stock_adj / stock_list`，并在抽取前后校验过滤范围内的源状态。发布动作使用同文件系统原子目录重命名；`snapshot_id`、manifest 和每个 Parquet 文件哈希共同定义输入身份。

快照同时保存：

- 原始 OHLCV
- 前复权 OHLC
- `adj_factor`
- 交易日历和连续 `session_no`
- 复权缺口、源状态、行数、代码数和质量位

CLX 计算排除 `EXCLUDED_CLX` 行；撮合排除 `EXCLUDED_MATCHING` 行。当前 `2026-07-21` 基线的已知复权缺口是 7 个精确的 `code + trade_date` 键：4 个经相邻因子连续性验证后重建，3 个保持隔离；它们不是“整段标的都缺复权因子”。每次 run 的实际数量仍以对应 manifest 和 `quality/adjustment_gaps.parquet` 为准。

当前全量链默认快照为：

- `snapshot_id=cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4`
- `manifest_sha256=e12b898e325e4573ebd156a49ddfed17036004d47aff29bc11fcc47a97db6e22`
- `16,426,284` 行、`5,201` 个代码、`8,740` 个交易日历 session
- IEEE NaN 为 `0`；4 条复权因子经验证重建，3 条缺口隔离

### 两个价格域

- 前复权 OHLC 只用于 CLX 结构识别，避免拆分、送转等造成图形断点。
- 原始 OHLC 用于 T+1 开盘撮合、收益、涨跌停、现金和持仓账本，避免在真实成交价格与复权价格之间混用。
- 事件 artifact 逐持有期统计 `adj_factor` 跳变并标记 `CORPORATE_ACTION_NOT_FULLY_LEDGERED`；组合账本保持固定 RAW 口径，不模拟分红、送转或拆并股导致的现金与持股数量变化，因此相关区间属于显式研究近似，不能解释为完整公司行动总收益。

## 信号编码与因果时钟

### 原始数字

单个模型行内的非零值按下式编码：

`raw_signal = direction * (model_id * 1000 + occurrence * 100 + primary_entrypoint)`

- `direction`：`+1` 为正向，`-1` 为负向
- `model_id`：`0..17`
- `occurrence`：`1..99`
- `primary_entrypoint`：`1..7`

原生编码器对 `model_id < 0`、`occurrence <= 0` 或 `primary_entrypoint` 不在 `1..7` 的输入按无信号处理，对 `occurrence > 99` 统一饱和为 `99`，因此 `occurrence=99` 表示“第 99 次或更多”，不保证恰好是第 99 次。`S0013` 和 `S0014` 从 `S0008` 派生时，使用可信的源模型行 `model_id=8` 恢复完整 occurrence，不按原始标量的固定数字位截取。

必须结合可信的 `expected_model_id` 行上下文解码。`occurrence >= 10` 后，单独看数字位数会与模型段重叠，因此原始标量不是自描述协议；单凭固定总位数不足以判断模型。

主触发语义固定为：

1. `MODEL_STRUCTURAL`
2. `PIN_BAR`
3. `ENGULFING`
4. `STRONG_FRACTAL`
5. `MA5_TURN`
6. `PRICE_VOLUME_CONFIRMATION`
7. `MACD_CROSS`

`occurrence` 是模型本地计数，从该标的快照中第一根可参与 CLX 的 bar 起，在“从头计算到当前 as-of”的前缀内统计；它不在不同模型之间直接比较。`S0002` 的 entrypoint 3 还会按原生基础谓词区分 `ENGULFING` 与 `S0002_NORMAL_FRACTAL_LEGACY_3`。

### 同 K 线并发触发

原始数字只携带一个主触发。研究事实另存 7 bit mask：

- `direction_base_trigger_mask`：原生共享谓词
- `synthetic_primary_mask`：补齐模型主触发的来源位
- `concurrent_trigger_mask`：两者按位或

因此“主触发类型”和“同 K 线并发触发集合”是两个维度，排行与下钻都保留两者。

### 因果前缀

每个标的按交易日从第一根合格 bar 重算到当日，比较相邻两个前缀：

- `ADD`：从无信号变为有信号，可执行
- `REPLACE`：已存在的信号值或触发来源变化，可执行
- `REMOVE`：历史信号消失，只保留修订事实，不生成新入场

`signal_date` 是模型标记的历史 K 线日期，`reveal_date/as_of_date` 是当时实际可观察到该版本的日期。研究、分段和 T+1 撮合统一以 `reveal_date` 为时钟，不把完整历史回看后的最终图形冒充当时已知信号。

## 单模型与组合搜索

单模型阶段分别评估：

- 模型 + 方向
- 模型 + 方向 + 发生次数
- 模型 + 方向 + 主触发或并发 trigger mask

通过 TRAIN 样本量、密度、年度覆盖和 FDR 门槛后，才进入有限的多模型搜索：

- 同日共振
- 最近 `1 / 3 / 5` 个交易日内共振
- 最大间隔 `1 / 3 / 5` 个交易日的有序序列

组合条件使用 canonical JSON DSL，而不是动态 Python/SQL。DSL 支持 signal、trigger mask、布尔组合、同日、窗口、序列、计数和固定因子条件；规范化 JSON 的内容哈希定义 `combo_id`。

模型投票按 `independence_root` 去重：

- `S0008 / S0013 / S0014` 只算一个独立根
- `S0016 / S0017` 只算一个独立根
- 其他模型各自是独立根

同一根的子集或变体即使同时命中也只计一票。相同方向且事件 membership 完全一致的组合只保留复杂度更低、`combo_id` 更稳定的一个。

## 统计、排行与组合结果

TRAIN 用于生成和筛选候选；VALIDATION 用固定评分权重、样本门槛和 Benjamini-Hochberg FDR 形成最终顺序。并列时依次按更低复杂度和 `combo_id` 确定稳定顺序。

系统同时产出两类结果：

- 事件研究：样本数、可执行数、均值/中位收益、胜率、95% 区间、方向归一化 MFE/MAE、信号密度、年度正收益比例、最差年度、FDR q 值；负向信号把下跌低点记为有利波动、上涨高点记为不利波动
- 组合撮合：资金曲线、总收益/年化收益、Sharpe、最大回撤、成交、费用、受阻原因、未完成退出和质量披露

因此最终排行回答的是“某个 canonical 组合在固定统计口径下的表现”，并能继续下钻到单模型、主触发、并发触发、次数、原始信号、成交和资金曲线。事件均值与真实组合收益属于不同层级，不互相替代。

事件 artifact 使用 `clx-event-study-v2`；verifier 同时锁定方向收益和正负向 MFE/MAE 语义，旧的多头 excursion 口径不会被恢复链静默复用。排行还把规范化交易日历的逻辑 SHA-256 写入 config、freeze 和 manifest；build resume 与 HOLDOUT reveal 在 claim 或物理读取前拒绝不同日历，避免用变化后的 session 序列恢复既有排行。

## HOLDOUT 冻结边界

Ledger 输出绑定合同：初始 claim 持久化 canonical `output_dir`（不进入 `claim_id`）；`resume / complete / reconcile` 必须精确匹配该目录，否则在 `resume_count` 递增或物理读取前 fail-closed。artifact A 发布后切换到不同 output B 不会产生第二次 HOLDOUT 读取或第二份 artifact。

HOLDOUT 使用物理访问边界，不只是在查询层隐藏：

1. event artifact 按日期边界分区并记录每次 Parquet 打开审计。
2. 搜索与 VALIDATION 排行期间，HOLDOUT Parquet 打开数必须为 `0`。
3. projector 在 run manifest 的 `freeze_input` 发布完整冻结顺序、固定入选组合、ranking config、split hash 和 rank digest。
4. API 递归规范化 JSON 中的整数/整数浮点表示后，只接受与服务端整份 `freeze_input` 完全一致的冻结材料；页面上的 2～4 项同屏比较与正式入选的 VALIDATION 正向前 20（或不足 20 时的全部正向组合）相互解耦。
5. API 确认揭示时只原子预留一个 worker job，并把 freeze 置为 `REVEALING / reveal_count=0`；此时查询和导出继续封存。`HOLDOUT_REVEAL_QUEUED` 由该预留的幂等投影产生，投影失败时保留 reconciliation marker，不留下“已入队但无审计”的永久窗口。
6. worker 取得 persistent holdout ledger 的唯一 claim，完成 HOLDOUT 指标与组合结果生成后先原子发布并校验 immutable HOLDOUT artifact，再把 ledger 置为 `COMPLETE`。同一 `freeze_id` 还持有独立的跨进程 execution lock，从 output 检查、claim/resume 一直覆盖物理读取、artifact 校验/发布和 ledger `COMPLETE`；锁由进程退出自动释放。相同 output 的后继只校验并对账已有 artifact，不再次读取；不同 output 的后继在首个执行成功后于物理读取前 fail-closed，不发布第二份 HOLDOUT artifact。若进程停在 HOLDOUT 读取后、artifact 发布前，普通 API 和未带恢复参数的 CLI 重试继续 fail-closed；正式不可变同-run链显式传入 `--resume-claimed`，干净首跑仍创建唯一初始 claim，已有状态时则只恢复同一 `CLAIMED` 的 `freeze_id / ranking_set_id / claim_id`，不会创建第二个 claim 或改变 frozen ranking。ledger 在重新打开 HOLDOUT 前以 `write + file fsync + atomic replace + directory fsync` 持久化确定性的 `resume_count / resume_audit`，claim 目录也在首次读取前持久化；`COMPLETE` 或任一身份不一致都拒绝恢复。每次逻辑揭示授权和 Parquet 打开同时追加到 run-scoped 外部日志，并绑定 `run_id / freeze_id / claim_id / attempt_no`；追加在独占文件锁内完成。若上次写入只留下未终止尾段，下一次已授权恢复会在锁内严格校验全部完整记录，以原子替换仅移除该尾段并同时写入绑定尾段 SHA-256、字节数、偏移和恢复 attempt 的 `REPAIR_UNTERMINATED_JSONL_TAIL` 审计事实；任何已终止的非法 JSON 或非法合同记录继续 fail-closed。成功 artifact 发布后日志固定为 `0444`，V2 Gate 将 repair、历次物理打开与 canonical resume audit 对账并披露实际恢复次数。若进程停在 artifact rename 与 ledger 完成之间，重启仍只从已验证 artifact 对账 ledger，不再次打开 HOLDOUT。Mongo 投影及 manifest attachment 成功后，worker 先幂等写入终态审计，再发布 `REVEALED / reveal_count=1`；哈希、job/run/freeze 身份或审计写入任一失败都保持查询锁定，失败记录为 `REVEAL_FAILED / reveal_count=0`。
7. HOLDOUT 组合撮合在冻结顺序和 ranking reveal artifact 均已校验后，才读取 event outcomes 生成派生决策与资金曲线。portfolio manifest 把 `run_id / event_set_id / event manifest SHA-256 / ranking_set_id / ranking manifest SHA-256 / freeze_id / reveal_id / reveal manifest SHA-256 / claim_id / attempt_no` 固定为显式授权身份，并登记本次实际使用的 event source `path + file_sha256` 有序集合、数量和内容摘要；verifier 与 V2 portfolio Gate 分别核对内部身份和上游 manifest/reveal audit。已完成 portfolio 的 resume 只校验 sealed artifact，不再次扫描 event outcomes。
8. portfolio 中保留的 `successful_holdout_reads` 是兼容字段，含义与新字段 `upstream_reveal_successful_reads` 相同，只证明上游 ranking reveal 的成功逻辑读取数为 `1`，不代表 portfolio 自身读取次数，也不表示整个生命周期只物理打开一次。portfolio scan 属于冻结后的授权派生读取，不参与候选生成、排序或 frozen top set 选择；揭示只给冻结组合附加 HOLDOUT 指标和组合结果，保持 `frozen_rank` 原值，也不重新搜索。

`HOLDOUT_LOCKED`、`HOLDOUT_REVEAL_IN_PROGRESS`、`HOLDOUT_REVEAL_FAILED`、`HOLDOUT_ALREADY_REVEALED` 和冻结材料哈希不一致都是合同保护结果；删除页面状态或重发请求仍会命中相同保护。

## Artifact 与 Mongo 投影

主要 artifact 目录：

- `snapshots/<snapshot_id>`
- `events/<run_tag>` 或 `runs/<run_id>/event`
- `rankings/<run_tag>` 或 `runs/<run_id>/ranking`
- `holdout/<run_tag>` + `holdout-ledger`（全量链），或 `runs/<run_id>/holdout` + `holdout-ledgers/<run_id>`（worker 链）
- `portfolios/<run_tag>/<split>` 或 `runs/<run_id>/portfolios/<split>`
- `exports/<run_id>`

全量因果信号由 `finalize_full_signal_facts.sh` 先把 facts 树固定为只读，再深度校验并交叉绑定 verify 输出、manifest 与 run contract 的 run、snapshot、engine、source commit、config、signal identity 和计数。在 `CLX_EVIDENCE_ROOT` 排他发布 `v2-causal-signal-<run_id>-<signal_sha256>.json` 及同名 `.json.sha256`，并发布确定性的 `.runner/finalized` 身份 marker。文件名同时绑定 run 身份和内容寻址的 `signal_set_id`；三类文件都执行内容 `fsync`、原子 hard-link、权限 `0444` 和 parent-directory `fsync`。同一名称重跑只接受逐字节完全一致的内容，任一已有文件内容不同都会停止链路，不覆盖或改写既有证据。

event artifact 完成后只执行一次逐文件深度校验：除文件哈希、行数、schema 和逻辑哈希外，还会从实际 `reveal_date` 列重新计算 `min_reveal_date / max_reveal_date`，并校验每行 `split_id / split_boundary_status` 与 split plan 兼容，避免下游路径裁剪信任错误边界。校验通过后整棵 event 树封为只读，并在树外排他发布绑定 run、signal、event manifest、engine image、source commit、run contract、verifier bytes 和完整 lstat 清单的 proof、marker 及 sidecar。恢复、ranking Gate 和 Mongo projector 只验证这组封存证明、manifest 与当前 lstat，不再次打开或哈希 `event_outcomes` Parquet；普通独立 verifier 未传 proof 时仍执行完整深验。

每一层都携带上游 manifest SHA-256、配置哈希和内容身份。projector 先校验 artifact，再幂等写入派生库 `freshquant_clx_backtest`；传入的 signal/event/ranking/portfolio/HOLDOUT manifest 必须属于 caller run，portfolio 目录映射键必须与 manifest `split_id` 相同。同一 `_id` 若内容不同会报冲突，不覆盖既有研究事实。组合 decision 的 `source_signal_fact_ids` 只记录 canonical DSL 实际命中的当日 anchor 与历史因果成员；不产生 source fact 的纯因子或纯否定布尔命中不生成 portfolio decision。projector 要求成员属于同一标的且不晚于 decision，并要求至少一个当日同方向 anchor。`combo_signals` 按这些 ID 回连 sealed signal revision artifact，并以 event preverification、event/signal manifest 血缘和统一 winner 规则证明来源；源事实缺失、输给同组 revision winner 或身份不一致时整次投影失败，不发布残缺下钻记录。

核心集合：

- 控制面：`runs / jobs / workers / progress_events / freeze_records`
- 血缘与审计：`manifests / audit_findings / model_registry`
- 排行：`combo_definitions / combo_metrics / model_heatmap`
- 组合：`portfolio_summaries / portfolio_equity / portfolio_trades / combo_signals`

源 Mongo 只用于创建快照；页面不直接扫描源行情或大体量 Parquet，而是查询上述派生集合。

## 页面口径

`/clx-backtest` 分为三个工作区：

- F1 结果分析
  - 服务端分页筛选 split、模型、方向、主触发、发生次数、周期和最低分
  - 多模型组合按 `model_ids / primary_triggers / occurrences` 数组 membership 过滤，不只检查一个兼容主值
  - 当前页关键词只过滤当前已加载的组合名/DSL
  - 展示排行、模型×触发热力图、组合定义、指标卡、资金曲线、成交和信号事实
  - 信号下钻保留 `signal_date / reveal_date / model / occurrence / primary trigger / concurrent triggers / raw signal`
- F2 实验运行
  - 创建、克隆、启动、取消不可变 run
  - 通过 cursor/SSE 查看外部 worker 进度和阶段事件
  - 展示固定配置、血缘与配置哈希
- F3 对比与审计
  - 同屏比较 2～4 个组合；该选择只影响比较
  - 使用服务端 `freeze_input` 冻结正式规则
  - 显示数据质量、偏差披露、manifest 和可审计导出
  - 明确确认后执行一次 HOLDOUT 揭示；`REVEALING` 期间有界自动轮询 run，进入 `REVEALED / REVEAL_FAILED` 后停止并刷新排名、manifest 和页面权限

导出支持 `rankings / metrics / equity / trades / signals` 与 `CSV / JSON / Parquet`。

## 部署与健康

- `fq_apiserver` 对 artifact 根目录只读挂载。
- `fq_clx_backtest_worker` 对同一目录可写挂载，使用 Mongo lease、心跳和阶段 checkpoint 执行任务。
- 默认 worker 限额为 `4 CPU / 12G`；可用 `FQ_CLX_WORKER_CPUS / FQ_CLX_WORKER_MEM` 覆盖。
- `/api/clx-backtest/health` 检查派生 Mongo 和 API 控制面。
- `engine_unit_fixture.sh` 只运行 `test_signal.py + test_engine.py`，验证信号编解码和 engine adapter 单元边界；trigger mask、隔离 native build、因果事实与性能分别由对应 Gate 验证，不把整个 `freshquant/tests/clx_backtest` 目录混入该 Gate。
- `trigger_mask_fixture.sh`、`prefix_performance_fixture.sh` 与 `signal_facts_real_sample.sh` 在隔离的 `python:3.12-bookworm` 中从源码构建 native 模块，并固定安装包含 `pybind11==3.0.2` 的构建依赖；其中 trigger-mask Gate 还固定 `numpy==2.2.6`，供同一隔离环境内的 engine 合同测试使用。`setup.py` 默认 `FQCOPILOT_BUILD_TARGET=all` 以保持正式打包同时构建 `fqcopilot + fullcalc`；这三个 CLX Gate 显式使用 `FQCOPILOT_BUILD_TARGET=fqcopilot`，只验证自身依赖的 extension，不把 `fullcalc` 源树混入 CLX Gate。
- 正式 artifact/V2 脚本要求显式传入不可变 `CLX_ENGINE_IMAGE_ID`；causal/full-chain 还要求 `CLX_EXPECTED_ENGINE_SHA256` 和启动前冻结的 `CLX_EXPECTED_ONLINE_ENGINE_SHA256`。下游 artifact 阶段及 causal/ranking/portfolio V2 Gate 的容器固定使用 `PYTHONPATH=/opt/clx-src:/opt/clx-engine:/workspace` 和工作目录 `/opt/clx-src`，包装器本身随 `freshquant/backtest/clx` 进入 runner 的 source manifest；包装器在执行原模块或 Gate heredoc 的同一 Python 进程中校验 `freshquant`、CLX 包、目标模块都来自 `/opt/clx-src`，并校验 `fqcopilot` 来自 `/opt/clx-engine` 且字节 SHA-256 等于 `CLX_EXPECTED_ENGINE_SHA256`。在线模块基线必须同时记录在不可变 `run-contract.json` 的 `engine.online_module_sha256`，Gate 核对环境 pin、run contract 与实际在线模块，任一缺失或不一致时立即失败。
- 真实交付门禁为 `v2_causal_signal_real.sh`、`v2_ranking_real.sh`、`v2_portfolio_real.sh`、`v2_frontend_real.sh` 和 `v2_e2e_real.sh`；后两者只读取已经揭示并完成投影的真实 run，不触发第二次 HOLDOUT 揭示。
- worker 容器 healthcheck 使用：

```powershell
docker exec fq_clx_backtest_worker /freshquant/.venv/bin/python -m freshquant.rear.clx_backtest.worker health --max-heartbeat-age 90
```

变更 `freshquant/backtest/clx/**`、`freshquant/rear/clx_backtest/**`、`freshquant/rear/api_server.py` 或 rear image 依赖时，同时重建 `fq_apiserver` 和 `fq_clx_backtest_worker`；变更前端时再重建 `fq_webui`。

## 排障

### 页面能打开但 CLX API 异常

- 请求 `/api/clx-backtest/health`
- 检查 `fq_apiserver` 是否连接 `freshquant_clx_backtest`
- 检查 API 是否把 `FQ_CLX_BACKTEST_HOST_ROOT` 只读挂载到 `/opt/clx-backtest`

### run 长时间停在 QUEUED 或 RUNNING

- 查看 `docker compose -f docker/compose.parallel.yaml ps fq_clx_backtest_worker`
- 查看 `docker logs fq_clx_backtest_worker`
- 检查 `freshquant_clx_backtest.workers` 的 `heartbeat_at` 和 `jobs` 的 lease/status
- 检查 artifact 目录写权限与阶段日志 `runs/<run_id>/control/logs`

### 排行为空

- 先看 run manifest、`quality` 和 `ranking_search_audit`
- 再看 TRAIN/VALIDATION 的样本量、密度、年度覆盖与 FDR rejection 计数
- 确认信号参数、前复权输入和 split config 与 run config 哈希一致

### 冻结返回 `FREEZE_SOURCE_MISMATCH`

- 重新读取 `/api/clx-backtest/runs/<run_id>/manifest`
- 以 `manifest.freeze_input` 为冻结材料，不从当前比较选择自行拼装
- 检查完整 VALIDATION 顺序、ranking config、split hash 和 rank digest

### HOLDOUT 查询返回锁定或重复揭示

- 冻结前返回 `HOLDOUT_LOCKED` 是预期边界
- 已有 `reveal_count=1` 后重复请求会返回 `HOLDOUT_ALREADY_REVEALED`
- `REVEALING / reveal_count=0` 表示 worker 尚在生成或投影，HOLDOUT 查询仍返回 `HOLDOUT_LOCKED`
- `REVEAL_FAILED / reveal_count=0` 表示本次唯一 claim 需要运维检查；保留 ledger、失败 job、日志和 artifact 证据
- 查看 `freeze_records`、holdout ledger、event access audit 和 holdout manifest；若 ledger 为 `CLAIMED` 且 artifact 尚未发布，只由原正式不可变同-run链通过 `--resume-claimed` 恢复，核对三项身份及 `resume_count / resume_audit`
- 不删除 ledger、不重建 freeze，也不更换 ranking 或输出目录来重跑测试集；已有 verified artifact 时沿用 reconcile 路径

### Artifact 校验失败

- 对照 `manifest.json / manifest.sha256` 检查挂载路径、文件 SHA-256、行数和上游 lineage
- 保留原 artifact 作为证据；从已验证的上游重新发布目标层，不直接编辑只读 Parquet 或 manifest
