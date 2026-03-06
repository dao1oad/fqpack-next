# 迁移进度（progress）

> 记录粒度：以 RFC 为单位。每个 RFC 通过评审后才能进入编码状态。

## 更新规则（强制）

- RFC 状态任意变更时（Draft / Review / Approved / Implementing / Done / Blocked），必须在同一提交更新本表。
- 任何涉及迁移、重构、删改功能的合并到 `main`，必须在同一提交更新本表。
- 处于 Implementing 状态的 RFC，按 Asia/Shanghai 自然日每天至少更新一次。

## 状态说明

- Draft：起草中
- Review：评审中
- Approved：已通过，可开始编码
- Implementing：编码中
- Done：完成并合并
- Blocked：阻塞中

## 进度总表

| RFC | 主题 | 状态 | 负责人 | 更新时间 | 旧分支来源（路径/能力） | 备注 |
|---:|------|------|--------|----------|--------------------------|------|
| 0001 | Docker 并行部署（端口隔离） | Done | TBD | 2026-03-06 | N/A（部署形态） | `docker/compose.parallel.yaml` + 部署文档；覆盖 Web UI/API/TDXHQ/Dagster UI+daemon/Redis/Mongo/QAWebServer；修复 tdxhq `len(int)` 导致的 500；Web UI Nginx 增加 Docker DNS 动态解析避免 502；stock_data_job 排除 cjsd_data + 关闭 cjsd_data eager auto-materialize（避免数据同步触发 CJSD） |
| 0002 | ETF 前复权(qfq)因子同步（TDX xdxr → etf_adj）与查询默认 qfq | Done | TBD | 2026-03-05 | 现状缺口补齐（ETF 无 xdxr/adj） | 新增 `etf_xdxr/etf_adj`，Dagster 补历史+每日更新；ETF 查询链路默认应用 qfq，与股票一致（无开关）；容器内已验证 `512000` 拆分与 `510050` 分红连续性，`get_data_v2()` 股票/ETF 日线&分钟均可 qfq 读取 |
| 0003 | XTData Producer/Consumer + fullcalc（替代轮询） | Done | TBD | 2026-03-06 | `D:\fqpack\freshquant\freshquant\market_data\xtdata\market_producer.py` / `strategy_consumer.py` / `morningglory\fqcopilot\fullcalc\*` | 已合并 main（PR #5）；Producer/Consumer/fullcalc/Guardian(event) 已落地骨架与关键语义（prewarm/backfill/qfq/积压只算最新）；端到端运行验收与部署说明待补充 |
| 0004 | Windows PowerShell UTF-8 中文显示（cat/type 不乱码） | Done | TBD | 2026-03-05 | N/A（开发体验） | 新增 `script/pwsh_utf8.ps1`；`docs/agent` 与 `README.md` 增加提示；dot-source 后 `cat/type` 默认按 UTF-8 读取 |
| 0005 | KlineSlim MVP（5m 主图 + 30m 缠论叠加） | Done | Codex | 2026-03-06 | `D:\fqpack\freshquant\morningglory\fqwebui\src\views\KlineSlim.vue` / `src\views\js\kline-slim.js` / `src\views\js\draw-slim.js` / `freshquant\rear\stock\routes.py` | 方案 A 已落地并完成联调：不使用 WebSocket，前端采用 HTTP 轮询并避免闪屏；后端 `/api/stock_data` 增加了 **opt-in** 的 Redis-first 实时读取（仅 `realtimeCache=1` 时启用，避免影响旧页面字段契约）；`KlineSlim` 在无 `endDate` 的实时模式下默认携带该参数，历史模式不携带。默认展示 `5m` K 线并叠加 `30m` 缠论结构。RFC、设计稿、实施计划、breaking-changes 与测试说明已同步补充该语义。 |
| 0006 | XGB / JYGS / Gantt / Shouban30 盘后读模型与独立分库 | Done | TBD | 2026-03-06 | D:\fqpack\freshquant\freshquant\data\xgb_cache_service.py / D:\fqpack\freshquant\freshquant\signal\astock\job\monitor_jygs_action_yidong.py / D:\fqpack\freshquant\freshquant\data\gantt_shouban30_service.py | 已在 `freshquant_gantt` 分库落地 XGB/JYGS 原始同步、`plate_reason_daily/gantt_*/shouban30_*` 读模型、`/api/gantt/*` 最小查询接口与盘后 Dagster job；统一改为 `FRESHQUANT_MONGODB__GANTT_DB` 覆盖分库配置，CI 已按 Linux 大小写语义验证。2026-03-06 追加修复 Docker 中 `job_gantt_postclose`：Dagster 改为只读挂载宿主机配置目录获取 `JYGS_SESSION/JYGS_COOKIE`，避免 `DAGSTER_HOME` 污染容器；JYGS 过滤无理由的非主题桶；XGB 在历史榜单理由缺失时补读 `/plate/plate_set.desc`。 |
| 0007 | 股票/ETF 系统化订单管理与逐买入跟踪 | Done | Codex | 2026-03-06 | `D:\fqpack\freshquant\freshquant\strategy\toolkit\order_manager.py` / `order_tracking_service.py` / `strategy_tracker.py` / `fill_stoploss_helper.py` / `morningglory\fqxtrade\fqxtrade\util\position_sync.py` / `freshquant\data\astock\holding.py` | 本分支实现任务已全部完成：Task 1-5 已完成独立分库、主账本、Guardian 语义层、XT trade/order ingest、`stock_fills` 兼容投影与持仓读切换；Task 6 已完成统一下单入口（`/api/order/*`、`/api/stock_order` 兼容、`fqctl om-order`、`xtquant buy/sell/cancel`、Guardian 策略入口）并接入 broker 提交/撤单桥接；Task 7 已完成外部订单候选、仓位差异检测、外部成交回报匹配与 120 秒自动确认，并在 `sync_positions/saveTrades` 路径接入对账；Task 8 已完成 `buy_lot_id` 级别止损绑定、剩余量止损卖单生成与 `buy-lot` 详情/API；Task 9 已将 `import_fill`、Excel `import_deals` 与 `/api/stock_fills/reset` 收口到订单域手工写服务，`clean/compact` 仅保留 legacy `stock_fills` 兼容投影维护；Task 10 已通过 `pytest freshquant/tests -q`（`86 passed, 1 skipped`）与相关 `py_compile` 验证。PR #12 的 CI 修复已完成：去除 `xtquant cli_commands` 与 `cn_future` 对 `pendulum` 的硬依赖、为 `stock routes` 增加 `func_timeout` fallback，并将 XT 回报时间统一按 `Asia/Shanghai` 解释；补齐 `pre-commit` 侧 `mypy` 显式包基配置并隔离 legacy 模块类型债务，解决 Linux runner 下的导入失败、日期漂移与类型检查阻塞。随后按 review 修复了在途内部成交被误判为外部订单的问题，并将 `/api/stock_order` 的非数字 `quantity` 输入统一收敛为 400 参数错误。 |
| 0008 | TradingAgents-CN 集成（阶段 1：保持原生本地数据逻辑可用） | Implementing | Codex | 2026-03-06 | N/A（新增第三方能力） | 已纳入 `third_party/tradingagents-cn/`，并在 `docker/compose.parallel.yaml` 中增加 `ta_backend` / `ta_frontend`；运行期复用 `fq_mongodb` / `fq_redis`，隔离到 Mongo `tradingagents_cn` 与 Redis `db 8`；前端通过专用 Nginx 反代后端；已修复 Mongo 库名硬编码、AKShare/BaoStock 单股补数回退、`symbol/stock_code` 与缺省 `parameters` 兼容问题，`000001` 任务已能通过本地数据检查并进入多智能体分析；当前阻塞为 DashScope `401 invalid_api_key`，待替换有效 LLM 凭证后继续验收完整分析闭环。 |
