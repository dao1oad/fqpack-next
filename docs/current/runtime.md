# 当前运行面

## Guardian / TPSL 交易运行规则

- Guardian 买入以 Position Management 的 `pm_symbol_position_snapshots.market_value`
  计算阶段剩余容量，容量真值不可读取时本次 Grid 买入退出。
- Guardian 与最终提交门禁都优先读取持久化的单标的仓位快照；快照缺失时才
  解析 `xt_positions`。券商持仓中明确没有该标的按市值 `0` 处理；存在持仓
  但市值不可得时保持 fail-closed。
- Position Management 在最终买入门禁检查
  `market_value + payload.price * payload.quantity <= effective_limit`。
- TPSL 止盈订单统一提交 `price_mode=auto`；STOCK 与 CREDIT 在连续竞价时复用
  五档市价解析，其他时段使用限价。
- 止盈订单成功提交后才关闭本档及更低档；没有可提交数量时保留档位。

## 宿主机与 Docker 分层

### Windows 宿主机承担

- XTQuant / XTData 连接。
- Mongo 通过 `127.0.0.1:27027` 接入 Docker `fq_mongodb`；宿主机链路不要再使用 `127.0.0.1:27017`。
- `fqnext-supervisord` 宿主机底座与其托管的交易/运行链 Python 进程。
- Guardian monitor。
- XTData producer / consumer / adj refresh worker / QFQ canonical worker（XTData producer 启动阶段遇到可重试的 XTData 连接失败时会在进程内退避重试；交易时段若订阅链 stale，则先 `resubscribe`，持续 stale 再升级为 `xtdata.connect() + resubscribe`。`xtdata_adj_refresh_worker` 在启动或计划刷新遇到可重试的 XTData 连接失败时，会退避后重建新的 refresh service / XTData client 再继续同步。`fqnext_xtdata_qfq_worker` 读取 Dagster 盘后 ready marker，再以 XTData `preClose` 更新 Stock / ETF A/B canonical 快照。）
- XT account sync worker（作为 XT 账户数据的增量补偿同步入口，默认每 15 秒轮询 `assets / credit_detail / positions / orders / trades`；其中 `credit_detail` 保持高频刷新以驱动仓位管理状态，只把新增 `orders / trades` 送入 ingest；`credit_subjects` 只在启动和每日计划时间做低频同步，并在启动时做一次单标的实时仓位 fallback 种子刷新；若 `positions` 快照为空或严重缩水、但同轮 `credit_detail.market_value` 仍显著为正，则该轮快照会进入 quarantine，不覆盖 `xt_positions`，也不触发自动平账；这个 quarantine 现在也覆盖小账户单票/双票严重缩水的场景，同时 worker 会记录 warning 说明 quarantine 原因；对 `xtquant connect/subscribe` 可重试失败，worker 会在退避后重建新的 XT sync service/client 再继续同步）。
- XT auto repay worker（默认每 30 分钟低频巡检一次已同步的 `credit_detail` 快照，只处理普通融资负债；盘中命中候选后才即时执行一次 `query_credit_detail()` 二次确认，再走 `CREDIT_DIRECT_CASH_REPAY`；固定在 `14:55` 做日终硬结算、`15:05` 做一次补偿重试；`broker_submit_mode=observe_only` 时只记录事件，不真实提交还款）。
- TPSL tick listener。
- 需要直接访问券商、终端、`TDX_HOME` 或 Windows 本地目录的组件。

当前运行面还有三条与订单对账相关的固定语义：

- `ExternalOrderReconcileService` 对 buy gap 会同时记录 `initial/latest/chosen` 三组价格快照；运行面和排障口径里若看到 `chosen_price_policy=freeze_initial`，表示最终确认价按首次发现快照冻结，而不是跟随长时间观测漂移。
- Guardian 遇到“持仓 entry 已确认但 arranged fills 不可用”的场景时，当前会显式区分 `arrangement_degraded` 与 `entry_without_slices`；这两种情况默认保守跳过，不再误记成“无持仓”。
- XT 委托/成交回报匹配内部订单时，优先使用严格 24 字符 FQOM correlation
  token，其次只接受完整 canonical broker identity。`broker_order_id`、
  `symbol/side`、价格、数量或回报时间都不作为猜测归属依据；无法证明归属时，
  完整外部身份进入 deterministic broker-only，身份不完整则 fail closed。

### Docker 并行环境承担

- MongoDB：宿主机 `27027 ->` 容器内 `27017`
- Redis：`6380 -> 6379`
- ClickHouse HTTP：`18123 -> 8123`
- ClickHouse native：`19000 -> 9000`
- API Server：`15000 -> 5000`
- TDXHQ：`15001 -> 5001`
- Dagster Webserver：`11003 -> 10003`
- QAWebServer：`18010 -> 8010`
- Web UI：`18080 -> 80`
- Runtime indexer：`fq_runtime_indexer`
对应编排文件是 `docker/compose.parallel.yaml`。

## 当前正式入口

- 自由会话硬入口：`codex_run/start_codex_cli.bat`、`codex_run/start_codex_app_server.bat`
- 自由会话 bootstrap：`runtime/memory/scripts/bootstrap_freshquant_memory.py`
- 共享部署计划脚本：`script/freshquant_deploy_plan.py`
- deploy 后运维面检查脚本：`script/check_freshquant_runtime_post_deploy.ps1`
- 宿主机运行时控制脚本：`script/fqnext_host_runtime_ctl.ps1`
- 仓库级本地预检正式入口：`script/fq_local_preflight.ps1`
- 本地开 PR 的正式入口：`script/fq_open_pr.ps1`
- 仓库 `git push` 会通过 `.githooks/pre-push` 调用本地预检；首次接入或 hook 丢失时，用 `script/install_repo_hooks.ps1` 恢复 `core.hooksPath`
- 当前本地预检会缓存 docs guard / pre-commit / pytest / review-thread 检查结果；当前分支已有关联 PR 且 `gh` 已登录时，会直接阻断 unresolved review threads
- 当前本地预检命中 `morningglory/fqwebui/**`、`.github/workflows/ci.yml` 或 `script/fq_local_preflight.ps1` 变更时，会额外执行 `npm run lint`、`npm run test:browser-smoke`、`npm run test:unit`、`npm run build`
- FQNext 宿主机 Supervisor service：`fqnext-supervisord`
- Supervisor XML-RPC 入口：`http://127.0.0.1:10011/RPC2`
- formal deploy 状态根目录：`D:/fqpack/runtime/formal-deploy`
- memory context pack 产物根目录：`D:/fqpack/runtime/artifacts/memory/context-packs`
- 冷记忆目录：`.codex/memory`
- 热记忆 Mongo database：`fq_memory`

## XTData QFQ A/B 运行口径

- Supervisor program 为 `fqnext_xtdata_qfq_worker`，并与 `fqnext_xtdata_adj_refresh_worker` 同属 `fqnext_reference_data` group；它运行在 Windows 宿主机，默认每 60 秒检查一次盘后就绪状态。
- worker 从 `freshquant.dagster_pipeline_markers` 读取 `pipeline_key=stock_postclose_ready` / `etf_postclose_ready` 的最新成功文档，再把目标交易日传给 XTData QFQ writer。
- `stock_postclose_ready` 在股票日线、分钟线和质量股票池快照完成后发布；`etf_postclose_ready` 在 ETF 日线与分钟线完成后发布。正常 schedule 不再选择旧 `stock_xdxr`、`etf_xdxr`、`etf_adj` asset。
- A/B 快照与发布 marker 写在 QuantAxis Mongo：数据集合为 `stock_adj_qfq_a/b`、`etf_adj_qfq_a/b`，marker 集合为 `qfq_ready`；`qfq_writer_locks` 以 scope 唯一后台 heartbeat lease 强制 worker、人工 build 与 rollback 串行，单次 XTData 下载或 Mongo `$out` 阻塞期间也会持续续租，发布前再次核对 owner。
- QFQ coverage 排除 `vol/amount` 同时命中 QASU 浮点哨兵的 BFQ 占位行；XTData 多出的真实交易日仍参与完整递推，之后才投影到有效 BFQ 日期。bootstrap、update 与 audit JSON 的 `coverage` 字段记录 sentinel 和无有效历史标的计数。
- Stock / ETF 在线 reader 每次请求从 `qfq_ready` 解析 active slot；marker、coverage、factor 或 snapshot-bound override 不满足合同时 fail closed 为 `QFQ_DATA_NOT_READY`。Redis Kline 与 StrategyConsumer 常驻窗口按 effective adjustment version 隔离，marker/override 版本变化会 miss/reload。
- `/api/stock_data?realtimeCache=1` 且未显式传 `endDate` 时，若只有当前交易日缺 snapshot-bound intraday override，Kline 读取会按交易日历最多回退最近 5 个已完成交易日取分钟历史；显式 `endDate` 或非当前交易日缺口仍保持 `QFQ_DATA_NOT_READY`。
- 旧 `stock_xdxr`、`etf_xdxr`、`etf_adj` asset 仅保留为人工 legacy 运维入口；`stock_adj` / `etf_adj` 集合至少保留 7 个交易日且不再作为在线真值。
- 真实 Index 当前固定读取 BFQ 日线/分钟线与 `index_realtime`，不读取 `stock_adj`、`etf_adj` 或 QFQ A/B 集合。
- 首次 bootstrap 与历史 backfill 只通过人工 `qfq_worker build --scope <stock|etf> --target-date YYYY-MM-DD [--full]` 执行；正常 worker 遇到缺失 `qfq_ready` marker 返回 `bootstrap_required`，不自动构建全历史。
- 运维 CLI 入口为 `python -m freshquant.market_data.xtdata.qfq_worker`，子命令为 `worker`、`build`、`audit`、`status`、`rollback`；`status --strict` 检查 active 截止日是否追平盘后 ready marker，`audit --mode structure|tail|full` 分别执行结构、近期 XTData 递推和全历史 XTData 递推审计。

## 会话与记忆口径

- memory refresh 会先同步远程 `origin/main`，再从该 ref 的 `.codex/memory/**` 与 `docs/current/modules/*.md` 汇总开发参考记忆。
- 会话通过环境变量 `FQ_MEMORY_CONTEXT_PATH` 注入本轮 context pack，并通过 `FQ_MEMORY_CONTEXT_ROLE` 暴露当前角色。
- 若当前会话没有现成 `FQ_MEMORY_CONTEXT_PATH`，应先执行 `bootstrap_freshquant_memory.py` 再继续仓库探索。
- 自由会话启动 `codex app-server` 时默认走 `stdio://`；没有客户端接入前可以保持静默。
- 关闭 `start_codex_app_server.bat` 的窗口，或在窗口里按 `Ctrl+C`，都会停止当前 `codex app-server`。
- memory context 只作为启动辅助信息，不能覆盖 GitHub、`docs/current/**` 或实际 deploy 证据。

## 开发与发布工作流

- 默认工作流是 `local session -> feature branch -> PR -> merge remote main -> deploy`。
- 轻量更新允许直接走 `feature branch -> PR`。
- 高影响、破坏性变更应先建 GitHub Issue。
- 本地会话只负责开发、测试和预检查，不是正式 deploy 真值。
- 正式 deploy 只允许基于最新远程 `main` 已合并 SHA。
- 命中宿主机 deployment surface 时，正式入口固定为 `script/fqnext_host_runtime_ctl.ps1`。

## 最小可用运行面

当目标是调试主交易链时，至少需要：

- MongoDB
- Redis
- API Server
- XTData producer
- XTData consumer
- Guardian monitor
- XT account sync worker
- Order submit / broker / XT 回报 ingest
- TPSL worker（如果验证退出逻辑）

如目标包含信用自动还款验证，还需要：

- XT auto repay worker

当目标是调试前端展示时，至少还需要：

- Web UI
- Gantt/Shouban30 对应读模型数据
- Runtime Observability 原始日志目录

当目标是调试 CLX 日线选股与 Kline marker 时，至少还需要：

- MongoDB 与 `freshquant_clx_daily_selection`
- 已安装且可导入的 `fqcopilot` 原生扩展
- API Server
- Dagster Webserver 与 Daemon
- 股票侧 `stock_postclose_ready` 或 ETF 侧 `etf_postclose_ready`；调试本侧 partition 时不要求另一侧 marker 已成功
- Web UI；Kline marker 还需要目标标的日线历史数据

## CLX 日线选股运行口径

- `clx_daily_selection_stock_sensor` 与 `clx_daily_selection_etf_sensor` 分别以 30 秒最小间隔观察本侧 marker；任一侧 success 即可派发对应 partition job。
- stock、ETF 与 finalizer 三个 sensor 都调用 `resolve_recent_completed_trade_dates(limit=5)`，按 newest-first 追赶最近 5 个已完成交易日。项目时区当天到 `15:05` 后才算完成，周末、节假日或未收盘当天不进入候选。每个 sensor 每 tick 最多派发一个 `RunRequest`：marker 缺失或 `reuse/wait` 继续旧日，`active` 停止本轮，`run` 立即返回；因此 D+1 延迟 marker、失败侧 attempt 2 和旧日 publication retry 可被自动找回。
- stock/ETF partition 拥有独立 `selection_key / attempt / marker_snapshot_hash / drift`。规划先写 9 分钟 lease 的 `scheduled` attempt，执行时以 `claim_owner + claim_token` CAS 切为 `running` 并延长为 6 小时；提交前由同一 owner/token 且未过期的 claim 切为带 1 小时 lease 的 `committing`。active 或 completed 选择会跳过重复派发；第二 executor 不重复计算，过期旧 worker 不能提交；任一阶段 lease 到期标为 `claim_expired` 并只重派本侧。
- partition 计算前后都核对本侧 marker snapshot。hash 变化时该 run 以 `upstream_drift` 失败，不提交输出，也不影响另一侧 completed partition。
- 单个 symbol 异常会写入 `errors[]` 并继续扫描同侧其余 symbol 以收集诊断；当前门禁为零容忍，`error_count > 0` 时本侧 attempt 失败且不提交 completed partition，只独立重试本侧。
- `clx_daily_selection_finalizer_sensor` 只在两侧不可变 partition 都 completed 后派发 finalizer；双侧 success 不作为任一侧开始计算的门禁。任一当前 marker 缺失时计划返回 waiting，并把该侧标为 `upstream_status=marker_missing`。
- sensor 在 `finalization_attempts` 持久化 `trade_date / batch_id / partition_ids / finalization_attempt_id`：scheduled dispatch lease 为 9 分钟，job owner/token running lease 为 10 分钟，终态为 `failed / completed / claim_expired`。每次 dispatch/retry 使用新的 attempt_no 和 run key，避免失败 run key 被 Dagster 永久去重；job 必须把四项 tags 与持久化计划精确对齐。
- finalizer 通过同交易日、`production_v1 / switch_opt=1` 与版本合同检查后，先写不可变 final 内容，再以 2 分钟 publication claim 发布 `clx_daily_selection_ready`。publication 按 `claim_owner / claim_token / attempt_count / lease_expires_at` CAS，状态由 `pending -> publishing -> published` 推进；`failed` 或过期 publishing 独立重试，不重算 partition；无 publisher 的受控运行面记为 `not_required`。marker/partition generation 在规划后漂移时，本 attempt 失败为 `generation_drift`，旧 generation 的 pending/failed final 不继续发布。ready marker 另以规范 UTC `generation_order` 和 `publication_id` CAS：相同 publication id 重试幂等；更新 generation 已存在时，迟到旧 publication 显式失败为 `stale_publication`，旧 batch 不进入 published。
- API 默认 latest/batch 列表只读 `publication.status in [published, not_required]` 的 final；`pending/publishing/failed` 与普通 partial 只有 `include_partial=1` 才可见，并统一按部分结果展示，不能显示为“完整结果”。
- `qfq-daily-v1` 对每根纳入计算的 bar 要求有效复权因子；覆盖缺失或因子非法时本侧 fail-closed，不以未复权价格继续计算。
- `/api/clx-daily-selection/history/signals` 只用闭合日线输入，返回 `future_function_guard`；Kline 只有在 profile 与 guard 通过时才显示 CLX marker series。

## Runtime Observability 页面口径

- `/runtime-observability` 主视图固定拆成 `全局 Trace` 与 `组件 Event` 两个视角。
- 顶部 `异常链路` 只过滤中间 Trace 列表，不过滤右侧已选 Trace 的完整步骤明细。
- 顶部 `异常节点` 与工具栏 `仅异常` 用于过滤当前右侧步骤/事件明细；查看异常 Trace 时，默认仍可回看完整链路步骤。
- 左侧组件卡片点击后默认进入该组件的完整 `Event` 视图；卡片上的 `异常节点` 按钮才进入该组件的仅异常 Event 视图。
- `broker_gateway` 的健康卡片不只依赖 XtQuant callback；broker 主循环在 `connect()/subscribe()` 成功后也会立刻补一条 `heartbeat connected=1`，避免页面长期停留在旧的重试告警。
- 右侧 Trace 摘要里的 `异常阶段` 列出当前单条 Trace 的异常节点列表。
- 左侧组件卡片里的 `异常节点 N` 是当前选定时间范围内该组件异常 Event 的聚合计数，不等于单条 Trace 的异常节点数。
- 顶部时间范围默认按北京时间 `09:00` 分界：`09:00` 前展示“昨天 + 今天”，`09:00` 起只展示当天运行观测。
- 右侧步骤详情区在桌面宽度和浏览器默认 `100%` 缩放下由详情面板自身承接纵向滚动；内容超出可视高度时应出现内部滚动条，不能依赖浏览器缩放才能看全。
- `当前过滤条件下没有节点` 只在当前步骤过滤结果实际为空时显示；若当前 Trace 仍有可见步骤，该提示不应额外占用大块空白区域。

## 持仓复盘页面口径

- 顶部导航中的“持仓复盘”进入独立 `/position-review` 路由；页面只读，不提交订单，也不修改持仓、策略配置或历史证据。
- 页面通过以下只读接口加载全局统计、历史成交标的和单标的完整详情：
  - `GET /api/position-review/summary`
  - `GET /api/position-review/symbols`
  - `GET /api/position-review/symbols/<symbol>`
- 历史成交标的集合包含当前仍持仓和已经清仓的标的。全局统计、标的列表、图表和订单明细使用同一套账户、标的与时间范围口径。
- 当前交易快照来自 `xt_trades`，持久历史成交由
  `om_execution_history_archive` 补齐；订单请求、实际成交数量和持仓变化合并
  当前 OM 账本与 `position_review_evidence_archive` 交叉核对。
  `broker_order_id` 和 `broker_trade_id` 都不能作为跨历史记录的单键关联依据。
- 页面与 API 只显示不可逆 `account_partition`，不返回原始券商账户号；多账户冲突或
  `unknown` 分区通过 `data_quality` 明示。
- 复盘结果使用 `PASS / FAIL / INSUFFICIENT_EVIDENCE / NOT_APPLICABLE` 四态；合规率只使用可判定的 `PASS + FAIL` 作为分母，不能把证据不足或不适用记录计入合规率。
- 证据置信度使用 `HIGH / MEDIUM / LOW`；页面同时展示 `data_quality`，使缺失策略上下文、持仓解释或执行关联的结果不会被误读为确定结论。
- 单标的详情统一返回摘要、图表、订单级复盘、成交时间线和数据质量信息。图表数量与订单级复盘明细必须能够回勾到相同的实际成交事实。
- ClickHouse Trace 只用于补充可选的信号、策略门禁和运行链证据，以及跳转到 `/runtime-observability`。持仓复盘接口不依赖 ClickHouse 才能返回成交和账本结果；Trace 不可用时由证据置信度和 `data_quality` 显示降级。

## 并行环境的默认口径

- 宿主机 `.env` 示例：`deployment/examples/envs.fqnext.example`
- 宿主机 `.env` 示例默认不再携带 `ALL_PROXY`、`HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 及其小写变量
- Production Docker API 使用 `FQ_COMPOSE_ENV_FILE` 指向 `D:/fqpack/config/fqnext.compose.env`，不要依赖会被 `git clean -ffdx` 清理的仓库根 `.env`
- GHCR 预构建镜像仅用于加速 Docker 部署，不改变运行真值；实际运行真值仍来自当前 `main`、deploy 结果与 health/runtime ops evidence
- `deploy-production.yml` 在正式 Windows self-hosted runner 上把 deploy state / logs 固化到 `formal-deploy` artifacts 目录，但正式 deploy 真值已经改为本机 mirror，不再依赖下载部署归档或把 Docker Images 作为前置。
- `deploy-production.yml` 不走 `actions/checkout`，而是先把 `D:\fqpack\freshquant-2026.2.23` 这个 local main sync root reset 到目标 SHA，再直接调用那里的 `script/ci/run_production_deploy.ps1`；随后该脚本继续确保 `D:\fqpack\freshquant-2026.2.23` 这个本机 canonical repo root worktree 存在并 fast-forward 到目标 SHA。
- canonical repo root clean 会保留 `.venv`、`.pytest_cache` 和 `logs/runtime`；这些路径分别承载 live virtualenv、pytest 本地缓存和运行日志，不作为 formal deploy 的 stale source artifact 清理对象。
- bootstrap entrypoint 在 canonical main sync 阶段会从当前 entrypoint repo 解析 `sync_local_deploy_mirror.py`，避免 stale `canonical repo root` 工作树里的旧 helper 把 `.venv\` 清理逻辑回退到 `git clean -ffdX`。
- 如果 live host runtime 仍在占用 `.venv\Lib\site-packages` 里的二进制扩展，正式入口会先 quiesce 宿主机 surfaces、重试 `uv sync`，再统一拉起这些 surfaces；这样 deploy 不会在 `.pyd` / `.dll` rename 阶段直接中断。
- 如果 `D:\fqpack\freshquant-2026.2.23\.venv\pyvenv.cfg` 缺失，或保留下来的 `.venv\Scripts\python.exe` 已经不能正常启动，正式入口会把该 mirror `.venv\` 视为损坏状态：先 quiesce 宿主机 surfaces，再用 runner Python 3.12 重建 `.venv` metadata 并重新执行 `uv sync --frozen`，然后才允许进入 formal deploy。
- 正式 production runner 宿主机必须至少存在一个可用的 Python 3.12；如果 `py -3.12` 因旧注册漂移失效，正式入口会回退到已注册的 per-user / system Python 3.12，并回补当前用户 `PythonCore\3.12` 注册。
- 若 runner Python 3.12 里缺少 `uv` 模块，正式入口会先自愈 `python -m uv`，再继续 deploy。
- 正式 deploy 固定导出 `FQ_DOCKER_FORCE_LOCAL_BUILD=1`，确保 mirror 上的 Docker 镜像来自本机构建而不是 GHCR pull。
- 对已经有 `last_success_sha` 的增量正式 deploy，`run_formal_deploy.py` 现在直接在 mirror 的 `.git` 工作树里计算 `last_success_sha..HEAD` changed paths，不再依赖 compare API 作为正式路径。
- mirror 同步完成后，正式入口会先用 runner Python 3.12 在 `D:\fqpack\freshquant-2026.2.23` 执行 `python -m uv sync --frozen`，再切到 mirror `.venv\Scripts\python.exe` 调用 `run_formal_deploy.py`。
- formal deploy 命中宿主机 deployment surface 时，会通过 `script/fqnext_supervisor_config.py` 把 `D:\fqpack\config\supervisord.fqnext.conf` 收敛到 `canonical repo root`，并在配置发生变化或 service 仍吃旧配置时先重载一次 `fqnext-supervisord`。
- 当前宿主机正式 Supervisor program 解释器与 `PYTHONPATH` 真值都固定落在 `D:\fqpack\freshquant-2026.2.23`；若运行面 traceback 指到 `.venv\Lib\site-packages\fqxtrade\...`，应视为 deploy/runtime truth 失配。
- `restart-surfaces` 当前以最终 settled state 为准；中途若出现一次 `Exited/Fatal/Backoff/Starting` 的瞬时启动错误，但最终 supervisor 已收敛回 `RUNNING`，运行面不再把这类 program 继续判成重启失败。
- 该 workflow 中的 PowerShell steps 固定带 `-ExecutionPolicy Bypass`，避免 self-hosted Windows runner 的本机执行策略在 step 启动前拦截临时脚本
- 该 workflow 也会显式设置 `$ErrorActionPreference = 'Stop'`，确保 PowerShell cmdlet 的 non-terminating error 仍然按 fail-fast 方式中断正式 deploy
- `script/docker_parallel_compose.ps1` 会优先读取 `FQ_DOCKER_BUILD_CACHE_ROOT`；未显式设置时，Docker BuildKit 本地缓存默认落到仓库 `.artifacts/docker-build-cache`
- 宿主机 FreshQuant / FQXTrade / vendored QUANTAXIS 默认统一解析到 `127.0.0.1:27027`
- Docker 容器内部 Mongo 继续使用服务名 `fq_mongodb:27017`
- Docker 容器内部 Redis 继续使用服务名 `fq_redis:6379`
- `docker/compose.parallel.yaml` 会为核心容器显式注入 `FRESHQUANT_MONGODB__HOST=fq_mongodb`、`FRESHQUANT_MONGODB__PORT=27017`、`FRESHQUANT_REDIS__HOST=fq_redis` 与 `FRESHQUANT_REDIS__PORT=6379`
- `docker/compose.parallel.yaml` 只要变更，正式 deploy plan 就按全量受管 Docker 并行环境容器重建/重启处理，避免 merge 后漏掉运行时配置更新。
- Web UI 默认访问并行 API `http://127.0.0.1:15000`

### 跑本地预检并开 PR

```powershell
powershell -ExecutionPolicy Bypass -File script/fq_local_preflight.ps1 -Mode Ensure
powershell -ExecutionPolicy Bypass -File script/fq_open_pr.ps1 -- --fill
```

### 按变更面执行 selective deploy

```powershell
powershell -ExecutionPolicy Bypass -File script/fq_apply_deploy_plan.ps1 -FromGitDiff origin/main...HEAD
```

## 当前阶段的运行风险

- Docker 里的 Mongo/Redis 与宿主机 broker/xtdata 之间必须通过宿主机端口对齐，否则交易链会出现“页面正常、worker 无数据”。
- 如果宿主机仍靠 `frequant-next.bat` 手工拉起，而不是 `fqnext-supervisord` service 开机自启，就会失去稳定的正式入口与权限边界。
- 如果 `D:\fqpack\config\supervisord.fqnext.conf` 仍指向 `main-runtime`、空目录或 `.venv\Lib\site-packages\fqxtrade`，formal deploy/runtime verify 现在应直接判为异常，而不是继续假设线上跑的是最新代码。
- 如果宿主机进程仍报 `127.0.0.1:27017`，优先检查进程环境是否缺少 `FRESHQUANT_MONGODB__HOST/PORT`。

## Canonical Main Runtime Truth

- The live host runtime now imports from `D:\fqpack\freshquant-2026.2.23`, not from any deploy mirror worktree.
- Formal deploy syncs the canonical repo root onto local `main` before it runs `uv sync` or `run_formal_deploy.py`.
- The expected host runtime Python is `D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe`.
- When host surfaces are hit, supervisor reconciliation and runtime verify both treat `D:\fqpack\freshquant-2026.2.23` as the only accepted repo root truth.

## XT Host Reconnect Guardrails

- `freshquant.xt_account_sync.client.XtAccountQueryClient` 现在会在只读 XT 查询遇到可重试连接错误时主动 `reset_connection()` 并重建连接后再重试一次；`query_credit_detail()` 在信用账户下如果返回空记录，也会先断开旧连接再补一次读取。
- `freshquant.position_management.credit_client.PositionCreditClient` 现在对 `query_credit_detail()` 采用相同的读请求自愈逻辑；这层被 `xt_auto_repay`、`position_management.snapshot_service` 等宿主机链路复用。
- `freshquant.xt_auto_repay.worker.XtAutoRepayWorker` 现在只对“确认还款前的 `query_credit_detail()`”做带退避的可重试 XT 自愈：命中 `xtquant connect/subscribe failed` 或空明细时，会先 reset 当前 credit client，再重建新的 executor 后继续查询。
- `xt_auto_repay` 的真实 `submit_direct_cash_repay()` 仍然不做盲目自动重提，避免在券商侧已受理但客户端回包异常时制造重复还款。

## Trade Calendar Refresh Runtime

- Dagster provides `trade_calendar_refresh_job` to refresh the persisted A-share trade calendar cache.
- `trade_calendar_morning_refresh_schedule` runs at `08:30` Asia/Shanghai on weekdays.
- `trade_calendar_postclose_refresh_schedule` runs at `15:10` Asia/Shanghai on weekdays.
- A successful live Sina/AkShare refresh updates Mongo and the shared disk snapshot under `FQ_TRADE_CALENDAR_STATE_DIR`.
- When a live refresh fails, FreshQuant falls back to Mongo last-known-good first, then the disk snapshot; the Dagster asset reports `refresh_status` and `degraded` so a cache-served refresh is visible without failing the run.
- Dagster run monitoring marks a run failed when its worker crashes because the current default run launcher does not support resume. `stock_data_job` and `etf_data_job` carry an eight-hour per-run limit because full daily/minute/xdxr recovery can exceed the global five-hour default, and each job limits automatic failed-run retries to two so a persistent upstream failure cannot create a long retry chain.
- `stock_postclose_ready` is emitted only after the latest 15 trade dates pass a cross-collection audit between `stock_day` and all five `stock_min` frequencies for the current stock universe.
- `stock_postclose_ready` success immediately releases only the stock CLX partition; it does not wait for `etf_postclose_ready`.
- `etf_postclose_ready` success immediately releases only the ETF CLX partition; it does not wait for `stock_postclose_ready`.
- Both partition outputs are required only for the CLX finalizer, final publication, and cross-asset statistics.
- Stock, ETF, Gantt, and daily-screening date resolution read the shared FreshQuant trade calendar entry, which falls back to Mongo last-known-good data and then the disk snapshot when the live Sina/AkShare request fails.
