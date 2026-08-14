# 当前排障

第二阶段的排障顺序统一为：先确认运行面，再确认数据流，再确认页面或单个模块。不要先改代码。

## 基础命令

```powershell
docker compose -f docker/compose.parallel.yaml ps
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/components
Get-ChildItem logs/runtime -Recurse -Filter *.jsonl | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName,LastWriteTime
powershell -ExecutionPolicy Bypass -File script/fq_local_preflight.ps1 -Mode Check
powershell -ExecutionPolicy Bypass -File script/fq_apply_deploy_plan.ps1 -FromGitDiff origin/main...HEAD
```

- 需要页面层健康检查时，优先执行 `py -3.12 script/freshquant_health_check.py --surface web --format summary`
- 这个入口会忽略系统代理环境，优先用于 deploy 后健康检查和日常排障；当前忽略键包括 `ALL_PROXY`、`HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 及其小写变量
- 如果上一轮 `fq_apply_deploy_plan.ps1` 已经产生 `deploy-state-*.json`，优先执行 `powershell -ExecutionPolicy Bypass -File script/fq_apply_deploy_plan.ps1 -ResumeLatest`，不要把已完成的 Docker / baseline 阶段整轮重跑

## 本地 preflight 没有自动生效

现象：
- `git push` 前没有触发本地预检
- 明明当前 `HEAD` 没跑过预检，但 push 还是直接发出去了

先检查：
- `git config --get core.hooksPath`
- `Get-ChildItem .githooks`
- `powershell -ExecutionPolicy Bypass -File script/install_repo_hooks.ps1`
- `powershell -ExecutionPolicy Bypass -File script/fq_local_preflight.ps1 -Mode Check`

常见根因：
- 仓库 `core.hooksPath` 没指到 `.githooks`
- 当前会话没跑过 `install.bat`
- 本机没有可用的 `powershell.exe` 或 `pwsh`

处理：
- 重新执行 `powershell -ExecutionPolicy Bypass -File script/install_repo_hooks.ps1`
- 确认 `.githooks/pre-push` 存在
- 手动执行一次 `powershell -ExecutionPolicy Bypass -File script/fq_local_preflight.ps1 -Mode Ensure`

## 运行面被代理污染

现象：
- 页面或数据库链路正常，但外发 HTTP 请求失败
- `requests` / `urllib` 报 SOCKS、ProxyError、InvalidSchema 一类异常
- 同一 webhook 或 URL 手工直连能通，运行进程里却失败

先检查：
- `Get-ChildItem Env:ALL_PROXY,Env:all_proxy,Env:HTTP_PROXY,Env:http_proxy,Env:HTTPS_PROXY,Env:https_proxy,Env:NO_PROXY,Env:no_proxy`
- `Get-Content D:/fqpack/config/envs.conf`
- `Get-Content D:/fqdata/log/fqnext_realtime_xtdata_consumer_err.log -Tail 200`

常见根因：
- 宿主机 Machine/User 级环境残留代理
- supervisor 运行环境没有把代理变量清空
- 某个外发请求直接继承了系统代理

处理：
- 确认 `D:/fqpack/config/envs.conf` 中代理变量均为空
- 重新启动受影响宿主机进程或执行 `script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces`
- 若仍有失败，优先看 stderr 是否是业务级 HTTP 拒绝，而不是代理错误

## XTData producer 假活着但不收行情

现象：

- `fqnext_realtime_xtdata_producer` 在 supervisor 中仍显示 `Running`
- `xt_producer` 心跳里 `connected=1`、`subscribed_codes>0`
- 但 `tick_count_5m=0`、`tick_batches_5m=0`，且 `rx_age_s` 在交易时段持续增长
- `xt_consumer` 同时没有新的 `processed_bars_5m`
- `minqmt` / `xtquant` 客户端手工取数正常

先检查：

- `Get-ChildItem logs/runtime/host_xt_producer/xt_producer -Recurse -Filter *.jsonl | Sort-Object LastWriteTime -Descending | Select-Object -First 5 FullName,LastWriteTime`
- `Get-ChildItem logs/runtime/host_xt_consumer/xt_consumer -Recurse -Filter *.jsonl | Sort-Object LastWriteTime -Descending | Select-Object -First 5 FullName,LastWriteTime`
- `Get-Content D:/fqdata/log/fqnext_realtime_xtdata_producer_err.log -Tail 200`
- `Get-Content D:/fqdata/log/fqnext_realtime_xtdata_consumer_err.log -Tail 200`

处理：

  - 优先查看 `xt_producer` 心跳里的：
    - `rx_age_s`
    - `tick_count_5m`
    - `tick_quote_pending_batches`
    - `tick_quote_dropped_batches`
  - 若 stderr 里出现 `无法连接xtquant服务` / `QMT` 启动竞态，先核对最新 `xt_producer` runtime jsonl 是否已经出现新的 `bootstrap`、`subscription_load`、`heartbeat`；当前 producer 会在进程内退避重试启动连接，不必因为单次历史栈就直接判定“当前仍未恢复”。
  - 若在交易时段出现 `connected=1`、`subscribed_codes>0`、`rx_age_s >= 120` 秒：
    - 先看是否已有 `subscription_guard` 事件，`reason_code=stale_rx`
    - 当前 producer 会先自动 `resubscribe`，持续 stale 时再做 `xtdata.connect() + resubscribe`
- 若自动恢复事件已经出现，但 `rx_age_s` 仍持续增长：
  - 按正式入口执行 `script/fqnext_host_runtime_ctl.ps1`
  - 重启 `market_data` 宿主机运行面，不要临时手拉 ad-hoc 进程
- 如果 `minqmt` 客户端手工订阅正常，而 producer 仍 stale，优先排查 producer 进程内的订阅/回调链，不要先改 `XTQUANT_PORT` 或监控池配置

## Runtime Observability / ClickHouse 查询异常

现象：

- `/runtime-observability` 页面可打开，但查询结果为空或明显落后。
- `fq_runtime_indexer` 在运行，但 ClickHouse 查询报认证或连接失败。

先检查：

- `docker compose -f docker/compose.parallel.yaml ps fq_runtime_clickhouse fq_runtime_indexer`
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/components`
- `Get-ChildItem logs/runtime -Recurse -Filter *.jsonl | Select-String -Pattern "ClickHouse|runtime indexer" -SimpleMatch`

处理：

- 确认 `fq_runtime_clickhouse` 与 `fq_runtime_indexer` 都已恢复。
- 核对 `FQ_RUNTIME_CLICKHOUSE_USER` / `FQ_RUNTIME_CLICKHOUSE_PASSWORD` 是否与 API / indexer 使用的一致。
- 若 ClickHouse 已恢复但页面仍无数据，优先排查 indexer backlog 与 runtime event 写入链路。
- 若 `fq_runtime_indexer` 容器状态是 `Up`，但新日志长期进不了 ClickHouse，优先检查容器环境：
  - `docker inspect fqnext_20260223-fq_runtime_indexer-1 --format '{{range .Config.Env}}{{println .}}{{end}}'`
  - 如果 `FRESHQUANT_MONGODB__HOST` 或 `MONGODB` 仍是 `127.0.0.1`，说明 compose recreate 继承了宿主机 `.env`，没有切到容器内 `fq_mongodb:27017`
  - 这种情况下 symbol / instrument 查询会在容器内反复超时，indexer 看起来在运行，实际上几乎不推进
  - 处理方式是修复 `docker/compose.parallel.yaml` 中 `fq_runtime_indexer` 的 Mongo 显式覆盖，然后重新 `up -d --force-recreate fq_runtime_indexer`
- 如果 `fq_runtime_indexer` 持续重启，且 ClickHouse stderr 报 `runtime_ingest_progress` 的 `TOO_MANY_UNEXPECTED_DATA_PARTS`：
  - 先停止 indexer，避免继续重试
  - 修复或重建 `runtime_ingest_progress`
  - 再执行 `py -3.12 script/rebuild_runtime_ingest_progress.py --apply --truncate-existing`
  - 最后再恢复 indexer
- 不要直接删除 progress 后让 indexer 从 0 全量重扫；`runtime_events` 当前不是去重表，这样会把历史事件重复写入 ClickHouse。

## Runtime Trace 显示 XT 回报链路状态迁移失败

现象：

- `/runtime-observability` 单条 Trace 显示 `链路类型=外部上报`、`链路状态=失败`
- 右侧异常阶段包含 `xt_report_ingest.order_match`
- stderr 或 runtime payload 出现 `InvalidOrderTransition`，例如 `FILLED -> SUBMITTED`

先检查：

- `Get-ChildItem logs/runtime/host_broker/broker_gateway -Recurse -Filter *.jsonl | Select-String -Pattern "<trace_id>|<broker_order_id>"`
- `Get-ChildItem logs/runtime/host_xt_report_ingest/xt_report_ingest -Recurse -Filter *.jsonl | Select-String -Pattern "<trace_id>|<broker_order_id>"`
- `@'
from freshquant.order_management.db import DBOrderManagement
broker_order_id = "<broker_order_id>"
broker_order_key = "<broker_order_key>"
print(list(DBOrderManagement["om_orders"].find({"broker_order_id": str(broker_order_id)}, {"_id": 0, "internal_order_id": 1, "request_id": 1, "broker_correlation_token": 1, "account_id": 1, "trading_day": 1, "order_sysid": 1, "trace_id": 1, "symbol": 1, "side": 1, "broker_order_type": 1, "state": 1, "submitted_at": 1})))
print(list(DBOrderManagement["om_broker_orders"].find({"$or": [{"broker_order_key": broker_order_key}, {"broker_order_id": str(broker_order_id)}]}, {"_id": 0, "broker_order_key": 1, "internal_order_id": 1, "request_id": 1, "broker_correlation_token": 1, "account_id": 1, "trading_day": 1, "order_sysid": 1, "broker_order_id": 1, "symbol": 1, "side": 1, "source_type": 1, "execution_fence": 1, "aggregate_revision": 1, "filled_quantity": 1, "fill_count": 1, "avg_filled_price": 1, "state": 1})))
'@ | py -3.12 -m uv run -`

处理：

- 先核对 XT `order_remark` 是否为严格 24 字符 FQOM token；有效 token 必须唯一
  命中对应内部订单，且账户、交易日、标的、方向等回报身份不能与订单冲突。
- 没有 token 时，只能使用完整 canonical identity：
  `account_id + trading_day + order_sysid`，或
  `account_id + trading_day + symbol + side + broker_order_id`。
  `broker_order_id`、价格、数量和回报时间都不能用于猜测真实内部订单。
- 无法证明归属时，完整外部身份应保留为 deterministic broker-only；身份不完整
  则 fail closed。若已出现错归属，继续核对 `execution_identity`、
  `om_broker_orders.execution_fence/aggregate_revision`、`om_execution_fills`、
  `om_trade_facts` 与 `om_position_entries`，再按券商真值
  `xt_orders/xt_trades/xt_positions` 做定向账本修复。
- 修复代码后需要重新部署 `order_management` host surface，并确认 broker / XT report ingest runtime event 已回到新内部订单对应的 trace。

### 外部订单并发与提交失败排查

- stale same-owner claim：对比 `om_broker_orders.aggregate_revision`、
  `filled_quantity`、`fill_count` 与最近 `om_execution_fills`；existing-owner
  claim 不应覆盖较新的成交聚合。若聚合已回退，不要从旧订单回报复制聚合字段；
  应以 canonical fills 重算，并通过 aggregate CAS 做定向修复。
- broker-only promotion：如果 broker-only 记录已有
  `execution_fence=true` 或成交，promotion 必须停止并留下 targeted-repair
  证据。保留 broker-only owner，不得强制 promotion 或静默改成内部订单。
- broker-order key move：同时查询旧 `broker_order_key` 与新 key；source delete
  CAS 竞争后最终只能保留一条 target。若仍有双记录，先停止写入面，核对两条
  记录的 owner、canonical identity、execution fence 与聚合，再做定向修复；
  在证据未收敛前不要直接删除任一记录。
- `prepare_submit_execution` 返回 `missing_order`：broker 必须 fail closed，不得调用
  XT、伪造提交成功或把消息重新入队。
- XT 委托返回 `None/0/负订单号`：核对 `om_order_events.event_type=submit_failed`
  和订单状态 `FAILED`。任何人工新发前先通过 XT 当日委托与柜台回报确认原请求是否
  已实际受理；puppet 不得 sleep、Redis requeue 或自动重复提交相同券商委托。

### 已确认账本污染的固定作用域修复

当前固定作用域修账入口是
`script/maintenance/targeted_order_ledger_repair.py`。它不是通用修账器，只接受代码中
固化的账户、证券、交易日、文档 `_id` 与业务身份白名单；计划外集合、身份或实时新增
记录都会 fail closed。

执行顺序固定为：

1. 代码通过 PR/CI 合并，并基于最新远程 `main` 同时部署 `api` 与
   `order_management`。
2. 停止 `fqnext_xtquant_broker`、`fqnext_xt_account_sync_worker`、
   `fqnext_xt_auto_repay_worker`、`fqnext_tpsl_worker` 与 API order-write surface。
3. 从停止写入后的实时 Mongo 完整 BSON 生成 plan；只读证据必须使用
   `before_document == after_document`，空集合用 verifier 的固定 live-scope 断言。
4. 运行 `stage`，人工核对 `plan_file_sha256 / plan_hash / preimage_hash /
   postimage_hash / manifest_hash` 与 change count。
5. 仅在 deploy-state 的终点 SHA 等于 plan `target_main_sha`、部署输入包含
   `api + order_management`、deploy phases 全部完成、runtime verify
   `passed=true` 时运行 `apply --execute`。
6. `apply` 完成后立即运行 `verify`；失败时保持写入面停止，并只从完整、读回校验通过
   的 backup bundle 执行 `restore --execute`。
7. 验证通过后恢复服务，再执行 health 与 runtime ops check。

该流程使用逐 `_id`、完整 BSON CAS；首写前必须先把 manifest/preimage/postimage/hash
与 backup 落盘、`fsync` 并读回校验。首次 apply 出现 mixed pre/post 状态会阻断；中途
CAS 失败会逆序补偿本轮已写文档，补偿不完整时必须保持所有写入面停止。工具不读取、
验证或修改 TDX，TDX 状态不是该修账流程的 gate。

## broker_gateway 健康摘要停留在旧 warning

现象：

- `fqnext_xtquant_broker` 已经恢复 `Running`
- broker stderr 已出现 `连接成功`、`订阅成功`
- `/api/runtime/health/summary` 里的 `broker_gateway` 仍显示旧的 `connected=0` / `retry_count>0`

先检查：

- `Get-Content D:/fqdata/log/fqnext_xtquant_broker_err.log -Tail 200`
- `Get-ChildItem logs/runtime/host_broker/broker_gateway -Recurse -Filter *.jsonl | Sort-Object LastWriteTime -Descending | Select-Object -First 5 FullName,LastWriteTime`
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18080/api/runtime/health/summary`

处理：

- 先确认宿主机 broker 实际 import 的 `fqxtrade.xtquant.broker` 已经是最新已合并代码，而不是旧的本地 wheel / 非 editable 快照
- 当前 `main` 已在 broker 主循环的成功连接路径补发 `heartbeat connected=1`；如果运行面仍停在旧 warning，优先重新部署并重启 `order_management` host surface
- 如果 stderr 只有 `connect()/subscribe()` 普通日志，没有新的 `broker_gateway` jsonl 心跳，说明宿主机还没跑到这版 broker 代码，不要只盯页面缓存

## XT 自动还款 worker 长时间不触发

现象：

- `pm_credit_asset_snapshots` 里已经有足够的 `available_amount`
- `xt_auto_repay_events` 没有新的 `submitted / observe_only`
- `fqnext_xt_auto_repay_worker_err.log` 出现 `xt auto repay state requires account_id`、`non_credit_account` 或 `xtquant connect failed: -1`

先检查：

- `Get-Content D:/fqdata/log/fqnext_xt_auto_repay_worker_err.log -Tail 200`
- `@'
from pprint import pprint
from freshquant.xt_auto_repay.service import XtAutoRepayService
svc = XtAutoRepayService()
pprint(svc.get_state())
pprint(svc.load_latest_snapshot())
'@ | py -3.12 -m uv run -`

处理：

- 若是宿主机启动早于 Mongo 恢复，当前 `system_settings` 会先重试；重试后仍失败时不会再把已有有效配置降级成空 `xtquant.path/account`
- 若 worker 在盘中巡检窗口之间重启，当前下一次巡检时间按 `last_checked_at` 对齐；若已逾期，会 1 秒级补跑，不需要再等满新的 30 分钟
- 若直接还款提交后长时间没有事件推进，先核对 `XtQuantTrader.order_stock()` 的参数是否为 `CREDIT_DIRECT_CASH_REPAY + placeholder stock_code + LATEST_PRICE + 0`；空 `stock_code` 会触发 `wrong stock market format`
- 若盘后/非交易状态出现 `节点当前非交易状态,禁止做直接还款`，说明柜台当前不受理该操作；需要等到下一个允许的交易窗口再提交
- 当前 `PositionCreditClient` 会给 XT 同步调用设置超时，避免错误参数把 worker 卡死在 `order_stock()` 上
- 若 worker 错过了 `14:55` 与 `15:05` 后才恢复，当前会在同一轮补跑里串行完成 `hard_settle` 与 `retry`，不再因为共享冷却锁把第二步误记成 `lock_unavailable`
- 若 stderr 仍持续出现 `xtquant connect failed: -1`，优先排查 QMT 连接稳定性，不要先怀疑自动还款金额判定

## Memory context 缺失或过期

现象：

- 自由 Codex 会话启动后仍重复全量扫描仓库。
- 会话环境里没有 `FQ_MEMORY_CONTEXT_PATH`，或指向的 markdown 不存在。
- `.codex/memory/**` 已更新，但 context pack 仍反映旧事实。

先检查：

- `Get-ChildItem Env:FQ_MEMORY_CONTEXT_PATH`
- `Get-ChildItem Env:FQ_MEMORY_CONTEXT_ROLE`
- `Get-Content $env:FQ_MEMORY_CONTEXT_PATH`
- `py -3.12 runtime/memory/scripts/bootstrap_freshquant_memory.py --repo-root . --service-root D:/fqpack/runtime`
- `py -3.12 runtime/memory/scripts/refresh_freshquant_memory.py --issue-identifier LOCAL-session --issue-state "Local Session" --branch-name <branch> --git-status clean`
- `py -3.12 runtime/memory/scripts/compile_freshquant_context_pack.py --issue-identifier LOCAL-session --role codex`

记忆库为 `fq_memory_v2`（旧库 `fq_memory` 已冻结保留）；需要回滚时用环境变量
`FRESHQUANT_MEMORY__MONGODB__DB=fq_memory` 后重新 bootstrap。context pack 是
「索引 + 快照」（冷记忆只含标题/摘要/路径，不再嵌入全文）；pack 中冷记忆区只有
索引是预期行为，细节按需读取 `.codex/memory/*.md`。长期未整合时可用
`runtime/memory/scripts/consolidate_freshquant_memory.py` 归档旧 pack 与清理
stale knowledge（先 `--dry-run` 预演）。

常见根因：

- 没有先执行 `bootstrap_freshquant_memory.py`。
- 直接双击 `codex_run/start_codex_app_server.bat` 后误以为“没有持续输出就是没启动”；实际上 `codex app-server` 默认走 `stdio://`，没有客户端接入前可以保持静默。
- `fq_memory` 不可写，导致热记忆集合为空。
- agent 读取了旧的 memory context，但没有回到 GitHub / `docs/current/**` / deploy 结果确认正式真值。

处理：

- 先手动重跑 `refresh_freshquant_memory.py` 和 `compile_freshquant_context_pack.py`
- 对自由会话，优先通过 `codex_run/start_codex_cli.bat` 或 `codex_run/start_codex_app_server.bat` 进入
- 如果 memory context 和正式真值冲突，优先修正式真值或刷新 memory，不要反向手改 context pack

## 正式 deploy 来源错误

现象：

- formal deploy 结果和本地 worktree 一致，但和远程 `main` 不一致。
- 本地改动尚未 merge，却已经尝试进入正式 deploy。

先检查：

- `git fetch origin main`
- `git rev-parse origin/main`
- `Get-Content D:/fqpack/runtime/formal-deploy/production-state.json`

常见根因：

- 正式 deploy 没有基于最新远程 `main`。
- 本地未 merge 的 worktree 被误当成正式 deploy 来源。

处理：

- 正式 deploy 只允许基于最新远程 `main`
- 本地未 merge 的 worktree 不能直接当正式 deploy 来源
- 先 merge，再从 deploy mirror 执行 `script/ci/run_formal_deploy.py`

## formal deploy 卡在 fetch origin main

现象：

- `git fetch origin main` 超时、连接重置或长时间挂起
- formal deploy 因为拿不到最新远程 `main` 无法继续
- 但 `gh api repos/dao1oad/fqpack-next/commits/main --jq '.sha'` 仍可返回远程 SHA

先检查：

- `C:\Program Files\GitHub CLI\gh.exe auth status`
- `C:\Program Files\GitHub CLI\gh.exe api repos/dao1oad/fqpack-next/commits/main --jq '.sha'`
- `git remote -v`

常见根因：

- 当前机器到 GitHub HTTPS 的网络抖动，只影响 `git fetch`
- `gh` 尚未授权，无法作为远程 SHA 只读校验入口

处理：

- 先修好 `gh` 授权，再用 `gh api` 校验目标 SHA 是否确实等于最新远程 `main`
- 只有在远程 SHA 已确认、且只是 `git fetch` 临时不稳定时，才允许把 `origin` 临时指到本机 canonical repo 的 `.git` 完成本轮 formal deploy
- deploy 完成后必须立刻把 `origin` 恢复为 `https://github.com/dao1oad/fqpack-next.git`
- 如果远程 SHA 无法确认，不要继续正式 deploy

## formal deploy 读取不到稳定 compose env

现象：

- `git clean -ffdx` 后仓库根 `.env` 消失
- Docker 容器继承了错误宿主机变量，或 compose 缺少 Mongo / Redis / Dagster 配置
- 同一份代码在人工复跑和正式 deploy 之间表现不一致

先检查：

- `Test-Path D:/fqpack/config/fqnext.compose.env`
- `Get-Content D:/fqpack/config/fqnext.compose.env`
- `Get-ChildItem Env:FQ_COMPOSE_ENV_FILE`

常见根因：

- 仍把仓库根 `.env` 当成 formal deploy 真值
- `git clean` 清理了 ignored `.env`

处理：

- 正式 deploy 统一使用 `D:/fqpack/config/fqnext.compose.env`
- 需要人工复跑 compose 时，显式导出 `FQ_COMPOSE_ENV_FILE=D:/fqpack/config/fqnext.compose.env`
- 不要再依赖仓库根 `.env` 作为 production compose 输入

## canonical repo root `.venv` metadata 漂移

现象：

- `.venv\Scripts\python.exe` 存在，但无法正常启动
- `.venv\Scripts\python.exe` 能启动，却落到了错误的全局解释器环境
- formal deploy 在 `uv sync` 或 `run_formal_deploy.py` 前就失败

先检查：

- `Test-Path D:/fqpack/freshquant-2026.2.23/.venv/pyvenv.cfg`
- `Get-Content D:/fqpack/freshquant-2026.2.23/.venv/pyvenv.cfg`
- `D:/fqpack/freshquant-2026.2.23/.venv/Scripts/python.exe -c "import sys; print(sys.executable); print(sys.prefix)"`

常见根因：

- live canonical repo root 的 virtualenv metadata 缺失或漂移
- 保留下来的 `.venv` 被误当成一直可信，但实际已经不能代表当前仓库解释器环境

处理：

- 优先重新执行 `powershell -ExecutionPolicy Bypass -File script/ci/run_production_deploy.ps1 -CanonicalRoot D:\fqpack\freshquant-2026.2.23 -MirrorRoot D:\fqpack\freshquant-2026.2.23 -MirrorBranch deploy-production-main`
- 由正式入口受控 quiesce 宿主机 surfaces，并在需要时重建 `.venv` metadata
- 不要手工拆开执行一半 `uv sync`、一半 runtime restart

## 宿主机 worker 误连 Redis 6379

现象：

- `fqnext_tpsl_worker`、`fqnext_xt_auto_repay_worker`、`fqnext_xtdata_adj_refresh_worker` 启动后快速 `Exited`
- stderr 出现 `redis.exceptions.ConnectionError: Error 10061 connecting to 127.0.0.1:6379`
- Docker 侧 Redis 正常，但宿主机 surface 一直起不来

先检查：

- `Get-Content D:/fqpack/config/envs.conf`
- `Get-Content D:/fqdata/log/fqnext_tpsl_worker_err.log -Tail 100`
- `Get-Content D:/fqdata/log/fqnext_xt_auto_repay_worker_err.log -Tail 100`
- `Get-Content D:/fqdata/log/fqnext_xtdata_adj_refresh_worker_err.log -Tail 100`

常见根因：

- `D:/fqpack/config/envs.conf` 缺失
- Supervisor 回退到进程默认 Redis 地址 `127.0.0.1:6379`

处理：

  - 重建 `D:/fqpack/config/envs.conf`
  - 确认至少包含：
    - `FRESHQUANT_REDIS__HOST=127.0.0.1`
    - `FRESHQUANT_REDIS__PORT=6380`
    - `FRESHQUANT_REDIS__DB=1`
  - 再执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface market_data,guardian,position_management,tpsl,order_management -BridgeIfServiceUnavailable`
  - 若 `fqnext_xtdata_adj_refresh_worker_err.log` 里是 `无法连接xtquant服务` / `QMT` 启动竞态，优先确认最新重启后是否已恢复；当前 adj refresh worker 会在进程内退避重试，并在可重试 XTData 失败后重建新的 refresh service / client。

## `fqnext-supervisord-restart` 管理员桥接任务超时

现象：

- `script/invoke_fqnext_supervisord_restart_task.ps1` 长时间等待后超时
- `fqnext-supervisord-restart` 执行后没有生成 `restart-status.json`
- 宿主机 surface 无法通过 bridge 恢复

先检查：

- `Test-Path D:/fqpack/supervisord/scripts/run_fqnext_supervisord_restart_task.ps1`
- `Get-ScheduledTask -TaskName fqnext-supervisord-restart | Select-Object -ExpandProperty Actions`
- `Get-Content D:/fqpack/supervisord/artifacts/admin-bridge/restart-status.json`

常见根因：

- 计划任务目标脚本缺失
- 外部脚本版本落后于仓库里的当前真值

处理：

- 将仓库内 `script/run_fqnext_supervisord_restart_task.ps1` 同步到 `D:/fqpack/supervisord/scripts/run_fqnext_supervisord_restart_task.ps1`
- 再执行 `powershell -ExecutionPolicy Bypass -File script/invoke_fqnext_supervisord_restart_task.ps1 -TaskName fqnext-supervisord-restart -ServiceName fqnext-supervisord -TimeoutSeconds 120`
- 只有 bridge 成功后，再补做 surface restart

## Docker 构建卡在拉取 `node:22-alpine`

现象：

- Web 镜像构建在 `FROM node:22-alpine` 前后卡住
- `docker compose build` 或 formal deploy 在基础镜像拉取阶段超时

先检查：

- `docker image inspect node:22-alpine`
- `docker pull node:22-alpine`

常见根因：

- 当前机器到 Docker Hub 的外网链路抖动
- 基础镜像本地还没有预热缓存

处理：

- 先单独执行 `docker pull node:22-alpine`
- 拉取成功后再重跑 formal deploy 或命中的 Docker surface deploy

## 破坏性 order-ledger rebuild 治理不满足

现象：

- 准备做破坏性 `order-ledger rebuild`，但输入计划依赖 `om_*`、`stock_fills` 或其他 legacy 集合作为主真值
- 尚未创建 GitHub Issue，就已经开始编码或准备执行 destructive rebuild

先检查：

- GitHub 上是否已有本次 rebuild 的正式 Issue，且写清影响面、验收标准、部署影响
- 当前 rebuild 输入是否只包含 `xt_orders`、`xt_trades`、`xt_positions`
- 当前方案是否只以 `om_*`（V2）与 `xt_positions` 为真值（legacy 集合已随 6b 删除）

常见根因：

- 把现有 `om_*` 账本误当成 rebuild 真值来源
- 先写代码、后补治理，跳过 GitHub Issue 前置要求

处理：

- 先补 GitHub Issue，再进入编码或执行阶段
- 若方案不是 broker truth 驱动，立即停止；重写为只基于 `xt_orders`、`xt_trades`、`xt_positions` 的 rebuild 输入
- legacy 集合（stock_fills / stock_fills_compat / om_buy_lots 等）已随 6b 删除，不复存在；rebuild 主账本只由 V2 与 broker truth 驱动

## Order Ledger V2 rebuild 后仍出现空日期/空时间

现象：

- `SubjectManagement` / `TPSL` / `/api/stock_fills` 仍看到 entry 或 arranged fill 缺 `date/time`

先检查：

- `@'
from freshquant.order_management.repository import OrderManagementRepository
repo = OrderManagementRepository()
print(repo.list_position_entries(symbol='300760'))
print(repo.list_open_entry_slices(symbol='300760'))
'@ | py -3.12 -m uv run -`

常见根因：

- 重建前 legacy 数据缺 `date/time`，但本轮还没有真正执行 v2 rebuild
- 运行期仍在读 legacy fallback，而不是 rebuilt v2 主链
- 某条记录缺 `date/time` 但保留了 `trade_time`，需要通过 v2 读侧回填

处理：

- 先确认已执行 `script/maintenance/rebuild_order_ledger_v2.py --execute --backup-db <backup>`
- 6a 起 `holding.py` / `entry_adapter` 只读 V2（legacy 回退已删除）；6b 起 legacy 集合已不存在
- 若记录仍缺 `date/time`，优先查对应 `trade_time` 是否存在，再查该 symbol 是否还停留在旧账本

## 券商有持仓但没有“聚合买入列表”入口

现象：

- `xt_positions` 显示某 symbol 仍有仓位
- `SubjectManagement` / `TPSL` / `KlineSlim` 看不到任何 open entry
- `PositionManagement` 仍可能显示 broker-aligned 持仓数量

先检查：

- `@'
from freshquant.order_management.repository import OrderManagementRepository
repo = OrderManagementRepository()
symbol = '512000'
print('entries', repo.list_position_entries(symbol=symbol))
print('slices', repo.list_open_entry_slices(symbol=symbol))
print('gaps', repo.list_reconciliation_gaps(symbol=symbol))
print('resolutions', repo.list_reconciliation_resolutions(symbol=symbol))
'@ | py -3.12 -m uv run -`

常见根因：

- 历史 mixed-state 曾同时保留 open `om_position_entries` 与 legacy `om_buy_lots`（legacy 已随 6b 删除；6a 起 internal remaining 只计 V2）
- 旧对账口径曾把两者同时计入 internal remaining 导致误判；6a 起 internal remaining 全量以 V2 为准
- 曾因错误 `auto_close_allocation` 先关 V2 entry；6a 起分配只走 V2 entry slices，无候选落 `empty_candidate_fallback` 审计

处理：

- 先确认当前代码已包含“有 open V2 entry 时不再把 legacy buy_lot 叠加进 internal remaining”的修复
- 再停止订单写入面，执行 `script/maintenance/rebuild_order_ledger_v2.py --execute --backup-db <backup>`
- 重建后复查 `xt_positions`、`om_position_entries`、`om_reconciliation_resolutions` 与页面读模是否一致

## Order Ledger V2 rebuild 后出现 odd-lot 拒绝

现象：

- 某 symbol 在页面中没有生成 `position_entry`
- `PositionManagement` 或 `TPSL` 显示对账异常
- `om_ingest_rejections` 出现 `reason_code=non_board_lot_quantity`

先检查：

- `@'
from freshquant.order_management.repository import OrderManagementRepository
repo = OrderManagementRepository()
print(repo.list_ingest_rejections(symbol='300760'))
print(repo.list_reconciliation_gaps(symbol='300760'))
print(repo.list_reconciliation_resolutions())
'@ | py -3.12 -m uv run -`

处理：

- odd-lot 当前只保留在 `execution_fill / ingest_rejection` 审计层，不会进入 `position_entry / entry_slice`
- 若券商当前仓位仍存在合法 board-lot 差额，系统会通过 `auto_open_entry / auto_close_allocation` 收敛
- 若差额本身仍不是 `100` 股整数倍，当前口径是继续保留 `REJECTED gap`，不要手工伪造 entry

## Dagster 容器持续重启

现象：

- `check_freshquant_runtime_post_deploy.ps1 -Mode Verify` 只报 `fq_dagster_webserver` / `fq_dagster_daemon` 为 `Restarting`
- `docker logs fqnext_20260223-fq_dagster_webserver-1` 或 `docker logs fqnext_20260223-fq_dagster_daemon-1` 出现 `DagsterInvariantViolationError`
- 日志明确提示 `$DAGSTER_HOME "D:/fqpack/dagster" must be an absolute path`
- 日志提示 `configured run launcher does not support resuming runs`，并要求把 `max_resume_run_attempts` 设为 `0`

先检查：

- `docker inspect fqnext_20260223-fq_dagster_webserver-1 --format '{{json .Config.Env}}'`
- `docker logs fqnext_20260223-fq_dagster_webserver-1 --tail 200`
- `docker logs fqnext_20260223-fq_dagster_daemon-1 --tail 200`
- `Get-Content .env`
- `Get-Content docker/compose.parallel.yaml`

常见根因：

- 主工作树 `.env` 里保留了宿主机 Windows 路径 `DAGSTER_HOME=D:/fqpack/dagster`
- `env_file` 把这个 Windows 路径直接注入了 Linux Dagster 容器
- Dagster 容器没有在 compose `environment` 中显式覆盖为 `/opt/dagster/home`
- 当前 `DefaultRunLauncher` 不支持 run worker 自动恢复；若 `run_monitoring.max_resume_run_attempts` 大于 `0`，Dagster 实例初始化会直接失败

处理：

- 保留宿主机 `.env` 的 Windows 路径给本机链路使用，但在 `docker/compose.parallel.yaml` 的 `fq_dagster_webserver` / `fq_dagster_daemon` 下显式覆盖：
  - `DAGSTER_HOME=/opt/dagster/home`
  - `FRESHQUANT_DAGSTER__HOME=/opt/dagster/home`
- 使用 `DefaultRunLauncher` 时保持 `morningglory/fqdagsterconfig/dagster.yaml` 中 `run_monitoring.max_resume_run_attempts=0`；失败 run 由 job 级 `dagster/max_retries` 标签重试，不要把 run worker resume 配置混为一谈
- 重新执行命中的 Docker deploy 或整轮 formal deploy
- 再次执行 `check_freshquant_runtime_post_deploy.ps1 -Mode Verify`，确认 Dagster 容器从 `Restarting` 恢复为 `running`

## 股票日线/分钟线停更但 Dagster run 显示成功

现象：

- KlineSlim 行情图表最新 K 线停在某个历史交易日，全市场（不只个股）都缺同一段日期
- `quantaxis.stock_day` / `quantaxis.stock_min` 的 `max(date)` 落后于最近交易日
- Dagster `stock_data_job` 每天照跑且状态 SUCCESS
- `stock_day` 步骤 compute log 里逐票刷 `'open'`、`'NoneType' object has no attribute 'columns'`，结尾打出覆盖几乎全市场的 `ERROR CODE` 列表

先检查：

```powershell
docker exec fqnext_20260223-fq_mongodb-1 mongosh --quiet --eval 'const c=db.getSiblingDB("quantaxis").stock_day; print(JSON.stringify(c.find({code:"000001"}).sort({date:-1}).limit(1).toArray()[0]))'
```

- Dagster UI (`http://127.0.0.1:11003`) 中最近 `stock_data_job` run 的 `stock_day` 步骤日志
- 宿主机是否开启了 TUN 全局代理（`route print -4` 看默认路由是否被 `singbox_tun` 一类虚拟网卡以 metric 0 抢占；容器内出口 IP 是否变成海外）

常见根因：

- 宿主机开启 sing-box/v2rayN 等 TUN 全局代理后，Docker 容器到 TDX 行情端口(7709)的流量被劫持出海外；部分 TDX 服务器直接拒绝(`head_buf is not 0x10`)，其余延迟升到 2~3 秒
- 旧实现 ping 探活超时 0.7 秒且只测证券列表接口，坏服务器（列表接口正常、K 线接口损坏）会持续通过健康检查，好服务器全部被误判超时，永远切换不出去
- 旧版 `QA_SU_save_stock_day` / `QA_SU_save_stock_min` 把逐票异常吞进 `err` 列表只打印，asset 不失败，Dagster 呈现假成功

处理：

- TDX 行情服务器列表由仓库内 `freshquant/gateway/tdx_ip_pool.json` 人工维护（`QUANTAXIS.QAUtil.QAIPPool` 加载，优先于 `~/.quantaxis/setting/*_ip.json` 缓存）；股票日线、分钟线与 ETF xdxr 都使用这份正式池，服务器批量失效时更新该 JSON 即可
- 当前 `QATdx.ping` 已加 K 线接口探活并把连接超时放宽到 3 秒；`select_best_ip` 判定阈值同步放宽，坏 default 服务器会被自动淘汰重选
- 当前股票日线/分钟线逐票抓取会在首选 host 返回异常、`None` 或源侧空响应时切换仓库 IP 池；旧 QASU 即使继续收集逐票错误，最终 ready asset 的跨集合审计也会阻断假成功 marker
- 当前 Dagster `stock_day` / `stock_min` asset 落库后仍做基础新鲜度断言；`stock_postclose_ready_asset` 写 marker 前还会交叉审计最近 15 个交易日的当前股票日线与 `1min/5min/15min/30min/60min` 覆盖，任一确定性缺口都会 fail
- 全市场交叉审计会豁免 OHLC 同值且成交量/额为 TDX 浮点哨兵的停牌占位日线；这类日期源侧没有分钟 bar，不要伪造数据
- TDX 会在首个历史 bar 出现前把发行期证券放进 `stock_list`。QASU 对这类空结果打印 `ERROR CODE`；Dagster 仅在代码没有任何历史日线且仍为 TDX 发行期占位（或盘中当天 `N` 股）时豁免，已有历史或应有数据的代码仍会令任务失败
- 当前默认 run launcher 不支持 crash resume，因此 run worker 崩溃后由 monitoring 将该 run 标记为失败；股票与 ETF 长任务通过 job tag 把单次最长运行时间设为 8 小时，并把自动失败重试限制为 2 次。容器重启后应确认失败 run 已结束、后续重试 run 的 compute log 继续增长，不能只看 UI 的 `STARTED`
- 宿主机代理软件建议启用"绕过中国大陆"分流或在使用系统链路时关闭 TUN 模式；即使代理未关，修复后的选点/超时也能在慢链路下工作
- 补缺口：直接在 Dagster UI 手动 launch 一次 `stock_data_job`（增量逻辑按"库内最后日期 → 今天"自动回补），完成后核对 `stock_day` / `stock_min` 的 `max(date)`

## ETF 日线启动时报 `IndexKeySpecsConflict`

现象：

- `etf_data_job` 在 `etf_day` 刚启动时失败，Mongo 返回 `codeName=IndexKeySpecsConflict`
- 报错同时列出 `quantaxis.index_day` 的 `code_1_date_stamp_1` 已有唯一索引，以及 QASU 请求创建的同名非唯一索引
- `etf_min` 与 `etf_postclose_ready_asset` 因依赖失败而跳过

处理：

- 先用 `db.index_day.getIndexes()` 确认已有索引的 key pattern；`(code, date_stamp)` 的唯一或非唯一索引都满足 QASU 的查询要求
- 当前 vendored QASU 在创建 `index_day` 索引前会复用相同 key pattern 的已有索引，不再因数据迁移保留的 `unique` 选项不同而重复创建同名索引
- 重新部署 Dagster 使用的 rear 镜像后重跑 `etf_data_job`，确认 `etf_day` 已越过索引初始化并继续执行 freshness check

## ETF 日线/分钟线停更但 Dagster run 显示成功

现象：

- `quantaxis.index_day` / `quantaxis.index_min` 的最新日期落后于最近已收盘交易日
- `etf_data_job` 中 `etf_day` / `etf_min` 步骤仍显示 SUCCESS
- 正常交易 ETF 的日线存在，但 `1min`、`5min`、`15min`、`30min` 或 `60min` 缺失

先检查：

- Dagster UI (`http://127.0.0.1:11003`) 中最近 `etf_data_job` 的 `etf_day` / `etf_min` compute log
- 按 `quantaxis.etf_list` 唯一代码过滤后的 `quantaxis.index_day` 最新交易日覆盖数，以及对应正常交易 ETF 的五种分钟周期 bar 数；不要把同集合中的指数文档计入 ETF 覆盖
- `quantaxis.etf_list` 中 `pre_close=5.877471754e-39` 的发行期标的；这类 TDX 占位标的可能没有分钟源

处理：

- 当前 `etf_day` 落库后会读取 `etf_list` 唯一代码 universe，只统计这些代码在最新交易日的日线覆盖；ETF universe 或日线覆盖低于下限时 step 直接失败
- 当前 `etf_min` 会在 `etf_day` 成功后执行，并以 ETF universe 内最新交易日的真实 ETF 日线为基准，逐代码校验 `1/5/15/30/60min` 是否存在且 bar 数合理
- TDX 占位/停牌日线（OHLC 全相等即平盘，含发行期 `1.0` 与清盘/停牌平价形态如 519622 全天 `102.37`，且成交量/额为浮点哨兵或≈0）会被显式豁免；真实一字板有成交量不会豁免；不要为这类无源日期伪造分钟 bar
- 任何真实 ETF 分钟周期缺失或 bar 数异常都会使 `etf_min` step 失败；`etf_postclose_ready_asset` 显式依赖 `etf_min`，不会生成假 ready marker
- 修复 TDX 连通性或权威 IP 池后重跑 `etf_data_job`，再确认全部 step SUCCESS 和 freshness check 日志

## ETF 前复权未生效但 Dagster run 显示成功

本节只排查保留期内的 `etf_xdxr -> etf_adj` 旧写入链。Stock / ETF 在线 reader 已改为读取 `qfq_ready` marker 指向的 A/B 快照；旧集合仅用于回退观察，不再是在线读取真值。

现象：

- KlineSlim / ETF 日线在拆分、扩缩股之后仍显示 bfq 价格
- 人工执行 legacy `etf.xdxr` / `etf.adj` 后，`quantaxis.etf_xdxr` 仍缺少目标 ETF 的历史事件
- `quantaxis.etf_adj` 在事件日前后仍全部为 `1.0`

先检查：

- `@'
from freshquant.db import DBQuantAxis
print(list(DBQuantAxis.etf_xdxr.find({'code':'512800'},{'_id':0}).sort('date',1)))
print(list(DBQuantAxis.etf_adj.find({'code':'512800','date':{'$gte':'2025-07-01','$lte':'2025-07-10'}},{'_id':0}).sort('date',1)))
'@ | py -3.12 -m uv run -`
- `docker exec fqnext_20260223-fq_dagster_webserver-1 sh -lc 'grep -R -n "ETF xdxr sync stats\|preserved=\|sync etf_xdxr empty after retry" /opt/dagster/logs || true'`
- `@'
from freshquant.data.etf_adj_sync import sync_etf_xdxr_all
print(sync_etf_xdxr_all(codes=['512800']))
'@ | py -3.12 -m uv run -`

常见根因：

- pytdx 长连接在 ETF xdxr 全量批量同步后段返回空结果
- pytdx `connect()` 失败时会直接返回 `False`；旧实现把它放进 `with api.connect(...)`，会把 retry host / batch host 故障误打成 `bool` context manager 错误
- 部分 ETF 的旧 `etf_xdxr` 文档来自 TDX 之外的历史回填，TDX 当前返回为空时会走 `preserve_on_empty=True` 保留旧文档；如果某只 ETF 在长连接退化场景下误返回空，也会被保留成旧状态

处理：

- 当前实现会对 ETF xdxr 首次空结果做 fresh connection retry，并在全量同步时周期性重建 TDX 连接
- 当前实现会在 batch host 连接失败时自动切到下一个可用 HQ host；fresh connection retry 的目标 host 若连不上，也会继续轮转其他 HQ host，而不是把 run 记成成功或打成 `bool` context manager 异常
- retry 仍超时或为空时，优先核对该 code 在不同 TDX host 上是否一致为空；对确实为空但库里已有历史回填的 ETF，允许保留旧文档
- 人工执行 Dagster `etf_xdxr` asset 时会对本次同步中 `empty/preserved` 的可疑 code 追加一次近期覆盖审计；如果近窗口内源侧有事件但库里没有，或者所有 HQ host 都不可达，asset 会直接 fail
- 如果 API / KlineSlim 在 `/api/stock_data` 上直接报 `redis.exceptions.ConnectionError: Error 111 connecting to 127.0.0.1:6379`，优先检查 Docker compose 是否把宿主机 `.env` 里的 Redis 地址误透传进容器；正式口径应由 `docker/compose.parallel.yaml` 显式覆盖为 `FRESHQUANT_REDIS__HOST=fq_redis`、`FRESHQUANT_REDIS__PORT=6379`
- 如果 compose Redis 覆盖修复已经 merge，但 formal deploy 的 `plan.json` 仍显示 `deployment_required=false`，优先检查 changed paths 是否包含 `docker/compose.parallel.yaml`；当前正式口径要求这类 compose 运行时变更必须触发全量受管 Docker 并行环境容器重建/重启。
- 对单券立即修复可执行：
  - `@'
from freshquant.data.etf_adj_sync import sync_etf_adj_all, sync_etf_xdxr_all
print(sync_etf_xdxr_all(codes=['512800']))
print(sync_etf_adj_all(codes=['512800']))
'@ | py -3.12 -m uv run -`
- 对近期覆盖审计可手工执行：
  - `@'
from freshquant.data.etf_adj_sync import audit_recent_etf_xdxr_coverage
print(audit_recent_etf_xdxr_coverage(codes=['512800'], recent_days=365))
'@ | py -3.12 -m uv run -`
- 对全量 ETF 近期覆盖审计可手工执行：
  - `@'
from freshquant.data.etf_adj_sync import audit_recent_etf_xdxr_coverage
print(audit_recent_etf_xdxr_coverage(recent_days=365))
'@ | py -3.12 -m uv run -`
- 正式修复后，重新部署 Dagster，并再跑一次 formal deploy health check / runtime verify

## XTData QFQ 快照不更新、reader 503 或审计失败

现象：

- `fqnext_xtdata_qfq_worker` 为 `FATAL` / `BACKOFF`，或 stderr 持续出现 `QFQ_DATA_NOT_READY`
- `quantaxis.qfq_ready` 缺少 `scope=stock` / `scope=etf` 文档，active slot 的 `factor_asof` 落后于对应盘后 ready marker
- inactive slot 长时间停在 `building` / `failed`，或 `audit` 返回日期轴、唯一性、非正因子、末日因子或递推恒等式错误
- `stock_adj_qfq_a/b` / `etf_adj_qfq_a/b` 已更新，但页面或策略仍返回旧版本，或 Stock Kline API 返回 `QFQ_DATA_NOT_READY/503`

先检查：

```powershell
powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status
Get-Content D:/fqdata/log/fqnext_xtdata_qfq_worker.log -Tail 200
Get-Content D:/fqdata/log/fqnext_xtdata_qfq_worker_err.log -Tail 200
& D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m freshquant.market_data.xtdata.qfq_worker status --strict
& D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m freshquant.market_data.xtdata.qfq_worker worker --once
& D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m freshquant.market_data.xtdata.qfq_worker audit --scope stock --mode full
& D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m freshquant.market_data.xtdata.qfq_worker audit --scope etf --mode full
```

处理：

- `worker --once` 返回 `waiting_for_bfq` 时，先在 Dagster 核对最新 `stock_data_job` / `etf_data_job`，以及 `freshquant.dagster_pipeline_markers` 中相应 `pipeline_key` 的成功文档；QFQ worker 不绕过 BFQ ready gate。
- `worker --once` 返回 `bootstrap_required` 时，在确认没有其他 QFQ writer/lease 后人工执行 `build --scope <stock|etf> --target-date YYYY-MM-DD [--full]`；正常 worker 不自动触发首次全历史 bootstrap。
- XTData 连接或历史下载失败时，先恢复 MiniQMT / XTData 端口，再重新执行 `worker --once`；worker 会把中断的 inactive `building` 状态恢复为可重试的 `failed`。
- 出现 `XTData history prefix download made no progress` 时，先核对 error 的 source role：primary `none` loader 会把该 code 记录为 `source_prefix_unavailable`，其余 code 审计通过时 worker 可继续发布；若 scope 内所有 code 均被隔离，update 拒绝发布空 ready snapshot 并保留 active slot。来自 `front_ratio` proof loader 的同类错误仍中止 scope。两种情况都应检查 QMT 下载任务和本地历史缓存，再决定是否重建 inactive slot。
- 返回 `writer lease is held` 时，先确认 Supervisor worker 或人工 build / rollback 是否仍在运行；正常 lease 会持续续期并在命令结束时释放，崩溃遗留 lease 到期后由下一轮原子接管，不要并发启动第二个 writer。
- `audit --mode structure` 只确认 Mongo 结构；递推或 XTData source 对账必须用 `--mode tail|full`。审计失败时保留 active slot，修复源数据或日期轴后用 `build --scope <stock|etf> --target-date YYYY-MM-DD` 重建 inactive slot；不要手工修改 `active_slot` 或在 active 集合上原地修补。
- `coverage.sentinel_rows_excluded` / `codes_with_sentinel_rows` 表示 BFQ 中精确 QASU 浮点占位行已被排除，`skipped[].reason=sentinel_only_bfq_history` 表示该标的没有可交易 BFQ 历史。`prelisting_rows_excluded` / `codes_with_prelisting_rows` / `prelisting[]` 只记录 `OpenDate` 不晚于最后有效 BFQ 时已证明的上市前脏行。`terminal_history_rows_excluded` / `codes_with_terminal_history` / `terminal_history[]` 要求 `IsTrading=false`、`OpenDate` 晚于最后有效 BFQ，且边界之后存在 QASU sentinel：`skipped[].reason=nontrading_terminal_history` 只将它排除出当前 QFQ build，保留 BFQ，旧生命周期 QFQ 读取仍 fail closed。缺少任一证据时不排除 BFQ，后续 source audit 继续阻断发布。
- `source_gap_rows_bridged > 0` 表示 BFQ-only 内部日期已通过缺口两端 `front_ratio.close / none.close` 恒定证明；从 `source_gaps[].windows` 查看 code、边界和日期。`front_ratio` 只作证明，canonical 因子仍由 `none.preClose` 递推。
- `source_empty_bars_excluded > 0` 表示完整 `none` source 区间下载后仍为空；`source_adjustment_gap_unproven_excluded > 0` 表示有界内部 source gap 两端 `front_ratio.close / none.close` 不一致；`source_prefix_unavailable_excluded > 0` 表示 primary loader 单调前缀分页稳定报告 `history_prefix_no_progress`。从 active slot `source_exclusions[]` 核对 code/reason。该 code 在对应 slot 必须没有因子行，不会填推断值或 `1.0`；structure audit 检查无残留，tail/full audit 按完整区间重现相同 reason 才通过。缺少 expected history、source 恢复、gap 可证明或 reason 改变时 audit 会报告 `stale_source_exclusion/rebuild_required`，应重建 inactive slot。
- `unbounded XTData source gap` 表示缺失 BFQ 日期位于当前 XTData source 首条之前或末条之后，缺少两个真实边界；检查 QMT 历史缓存和下载范围，恢复 source 后重建 inactive slot。
- `XTData source gap crosses an adjustment` 的稳定 failure code 是 `source_adjustment_gap_unproven`；bootstrap/update 对该 code 做 per-code fail-closed exclusion，其他 code 可继续发布。`unbounded XTData source gap`、`requires front_ratio proof`、`front_ratio date axis mismatch` 及其他 proof 错误仍中止 scope。
- `history_prefix_no_progress` 只有来自 primary `none` loader 时映射为 `source_prefix_unavailable`；来自 `front_ratio` proof loader 时仍中止 scope。它不同于 projection 发现的普通 unbounded prefix/suffix，后者继续阻断发布。
- 怀疑 XTData 修订发生在默认 60 个交易日回看窗口之前时，使用同一 active 截止日执行 `build --scope <stock|etf> --target-date YYYY-MM-DD --full`；该命令重算整个 inactive scope，且不接受早于 active `factor_asof` 的日期。
- 回切前先确认另一槽为 `ready` 并单独执行 `audit --slot <a|b>`，然后使用 `rollback --scope <stock|etf>`；命令会先将仍需生效的 intraday override 重新绑定到目标 snapshot，再以 CAS 切换 marker，factor A/B 集合本身不改写。
- Stock / ETF 在线 reader 每次请求重新解析 active slot；先核对 marker 的 `snapshot_id/factor_asof/source_exclusions`、请求日期覆盖和同 snapshot 的 intraday override。Redis Kline key/payload 与 StrategyConsumer 常驻窗口均绑定 effective adjustment version；marker 或 override 版本变化后应 miss/reload，不要复制旧版本 cache key。真实 Index 固定使用 BFQ，不读取 Stock / ETF 因子。
- KlineSlim 普通行情图表调用 `/api/stock_data?realtimeCache=1` 且未带 `endDate` 时，若只因当前交易日 intraday override 尚未生成而返回 `missing_dates=[today]`，API 会自动用交易日历回退到最近可读的已完成交易日分钟线；如果显式指定了 `endDate`，或缺口不是当前交易日，仍按 `QFQ_DATA_NOT_READY/503` 排查并修复 QFQ 链路。

## xt_account_sync worker 启动即 Fatal

现象：

- `script/fqnext_host_runtime_ctl.ps1 -Mode Status` 显示 `fqnext_xt_account_sync_worker` 为 `Fatal`
- `D:/fqdata/log/fqnext_xt_account_sync_worker_err.log` 出现 `resolve_stock_account() got an unexpected keyword argument 'settings_provider'`
- `D:/fqdata/log/fqnext_xt_account_sync_worker_err.log` 持续出现 `xtquant connect failed: -1`
- formal deploy 卡在 `EnsureServiceAndRestartSurfaces` 或 deploy 后 verify 阶段

先检查：

- `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status`
- `Get-Content D:/fqdata/log/fqnext_xt_account_sync_worker_err.log -Tail 200`
- 如果当前症状是“第一次 `restart-surfaces` 失败后，管理员桥接已经把目标 programs 拉回 `RUNNING`，但第二次冗余重启又把运行面打挂”，确认宿主机已经跑到包含该桥接短路逻辑的最新 `script/fqnext_host_runtime_ctl.ps1`
- `@'
import inspect
from fqxtrade.xtquant.account import resolve_stock_account
print(inspect.getsourcefile(resolve_stock_account))
print(inspect.signature(resolve_stock_account))
'@ | py -3.12 -m uv run -`

常见根因：

- 宿主机进程实际导入的是 `.venv\\Lib\\site-packages\\fqxtrade\\xtquant\\account.py`
- 该已安装 `fqxtrade` 仍是旧签名，只接受 `query_param=None, stock_account_cls=None`
- 会话误以为仓库里的 `morningglory/fqxtrade/fqxtrade/xtquant/account.py` 已自动成为宿主机运行时真值
- MiniQMT 未启动、未登录，或 XT 连接尚未恢复

处理：

- 先确认正式 deploy 来源已经是最新远程 `main` 已合并 SHA
- 当前仓库中的 `freshquant/xt_account_sync/client.py` 已兼容新旧 `resolve_stock_account` 签名；如果仍报这个错误，说明宿主机还没跑到最新已合并代码，先重新同步 deploy mirror 并重跑 formal deploy
- 当前 worker 会对 `xtquant connect failed:*` 与 `xtquant subscribe failed:*` 保持 `Running` 并退避重试，且每次可重试失败后都会重建新的 XT sync service/client；如果 stderr 持续刷这两类日志，优先确认 MiniQMT 已启动且已登录正确账户
- 若仍需继续定位，优先以 `inspect.getsourcefile()` 与 `inspect.signature()` 的结果确认宿主机实际 import 源，而不是继续凭仓库文件内容猜测
- worker 恢复后，再重新执行命中的 host runtime surface restart 或整轮 formal deploy，并确认 runtime verify 通过

## Docker 构建阶段 fqchan04 编译器崩溃

现象：

- formal deploy 在 `script/docker_parallel_compose.ps1` 阶段失败
- 日志显示失败点在 `docker/Dockerfile.rear` 的 `python -m uv sync --frozen --no-install-project`
- stderr 出现 `fqchan04`、`internal compiler error`、`Segmentation fault`，并且 `g++` 在编译 `fqchan04.cpp` 时退出

先检查：

- `Get-Content D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/result.json`
- `Get-Content D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/plan.json`
- `Get-Content docker/Dockerfile.rear`
- `Get-Content docker/compose.parallel.yaml`

常见根因：

- 失败点其实在 rear image 依赖同步，不是运行面健康检查，也不是宿主机进程
- `fq_webui` 的 compose 依赖会带出 `fq_apiserver` / `fq_qawebserver` 启动路径，因此 Web deploy 也可能触发 rear image 构建
- `fqchan04` 的 C++ 扩展编译可能偶发触发编译器级 `internal compiler error`，并不一定是当前提交引入了稳定可复现的源码错误

处理：

- 先保留失败 run_dir artifacts，不要在没有证据的情况下立刻改代码
- 如果是第一次出现这类 `fqchan04` / `g++ internal compiler error`，对同一 SHA 原样重跑 1 次 formal deploy
- 只有当第二次仍在相同位置稳定复现时，才继续进入代码修复、Dockerfile 调整或编译环境隔离
- 如果重跑成功，把这次失败判定为构建过程瞬时失败；继续以新 run_dir 的 `result.json` 与 `runtime-verify.json` 作为正式交付证据

## formal deploy 判定为 no-op deploy

现象：

- `run_formal_deploy.py` 成功退出，但当前 run_dir 只有 `plan.json` 和 `result.json`
- `runtime-baseline.json`、`runtime-verify.json` 没有生成
- `result.json` / `plan.json` 里明确显示 `deployment_required=false`

先检查：

- `Get-Content D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/result.json`
- `Get-Content D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/plan.json`
- `Get-Content D:/fqpack/runtime/formal-deploy/production-state.json`

处理：

- 先确认这轮 changed paths 只命中文档、skill、测试或其他不需要部署的路径，而不是误漏了 deploy surface
- 如果 `deployment_required=false`，把这轮判定为正常的 `no-op deploy`，不是失败
- 在这种情况下，`runtime-verify.json 可以不存在`；正式收口依据改为 `result.json` 的 `ok=true` 和 `production-state.json` 的 `last_success_sha` 已更新到目标 SHA
- 只有当你预期本轮应该命中运行面，但 plan 仍然给出 `deployment_required=false` 时，才继续回查 deploy plan 规则或 changed paths 计算

## CLX 只有一侧完成，页面一直是 partial

### 现象

- 股票显示 completed，ETF 显示 waiting/running/failed，或反之
- `/api/clx-daily-selection/batches/latest?include_partial=1` 有数据
- 默认 `/api/clx-daily-selection/batches/latest` 仍返回较早 final 或 `no_ready_batch`

### 当前判断

这是 fork-join 的正常中间态。单侧 marker success 已经启动并完成本侧 partition；另一侧不阻塞本侧计算。双侧 completed 只门控 finalizer、正式发布和跨资产统计。

### 排查顺序

1. 看 partial batch 的两侧状态：

```powershell
$partial = Invoke-RestMethod 'http://127.0.0.1:15000/api/clx-daily-selection/batches/latest?include_partial=1'
$partial.partitions.stock
$partial.partitions.etf
```

2. 查未完成侧 marker：

```javascript
db.dagster_pipeline_markers.findOne({
  pipeline_key: "stock_postclose_ready", // 或 etf_postclose_ready
  trade_date: "YYYY-MM-DD"
})
```

3. 在 Dagster 看本侧 sensor，而不是等待或重跑另一侧：

- `clx_daily_selection_stock_sensor`
- `clx_daily_selection_etf_sensor`

4. 两侧都 completed 后再看：

- `clx_daily_selection_finalizer_sensor`
- `freshquant_clx_daily_selection.batch_statuses`
- `freshquant.dagster_pipeline_markers` 中的 `clx_daily_selection_ready`

不要通过手工修改 `is_final` 把 partial 包装成 final。

## CLX 旧交易日 marker 或失败任务没有自动找回

### 当前口径

- stock、ETF、finalizer 三个 sensor 都按 newest-first 扫描最近 5 个已完成交易日。
- 项目时区当天必须到 `15:05` 才算已完成；交易日来自交易日历，周末、节假日和未收盘当天不会被当成未来可运行日期。
- 每个 sensor 每 tick 最多返回一个 `RunRequest`。marker 缺失或 action 为 `reuse/wait` 时继续检查更早日期，`active` 时停止本轮，`run` 时立即派发并返回。
- 该窗口覆盖 D+1 延迟到达的 marker、失败 partition 的 attempt 2，以及旧日 failed/expired publication；成功侧仍按 `reuse` 保持不可变。

### 排查

1. 查看 sensor tick 的候选交易日是否 newest-first，目标日期是否仍在最近 5 个已完成交易日内。
2. 当天任务未出现时先核对项目时区与 `15:05` cutoff；不要把午间、盘中或周末日期手工伪造成 completed。
3. 新日期为 `reuse/wait` 时应继续看到旧日计划；新日期存在 active attempt 时，本轮主动停止以避免并发重复，等后续 tick 再追赶。
4. D+1 延迟 marker 应生成目标旧日的 partition；同一 selection 上次失败时应使用 `attempt_no=2+` 和新 run key。
5. 旧日 publication retry 应只增加 finalization/publication attempt，不增加两个 completed partition 的计算次数。

超过 5 个已完成交易日的历史洞不在自动追赶窗口内，使用显式 backfill，并保持相同 partition/finalizer 合同。

## CLX 单侧失败后反复计算成功侧

### 正确口径

- failed、`claim_expired` 或 `upstream_drift` 只对本侧创建下一 `attempt_no`
- completed selection 必须直接复用不可变 partition

### 排查

```javascript
use freshquant_clx_daily_selection
db.partition_attempts.find({
  trade_date: "YYYY-MM-DD"
}).sort({asset_type: 1, attempt_no: 1})

db.partitions.find({
  trade_date: "YYYY-MM-DD"
}, {
  asset_type: 1,
  selection_key: 1,
  partition_id: 1,
  marker_snapshot_hash: 1,
  content_hash: 1
})
```

- 同一 `selection_key` 已 completed 却继续出现新 attempt：查 sensor 是否忽略了 `action=reuse`
- attempt 长期 scheduled：查 Dagster RunRequest 是否未实际派发；9 分钟 lease 到期后应 CAS 为 `claim_expired` 并产生新 attempt
- attempt 长期 running：查对应 Dagster run 是否仍存活；running lease 为 6 小时，到期后应只重派本侧
- attempt 长期 committing：查明细/partition 头写入是否中断；committing lease 为 1 小时，只有原 `claim_owner / claim_token` 能完成提交，过期后旧 worker 不能越过 fencing
- 失败侧 attempt 没递增：查 `selection_key` 是否因 marker/version 改变而形成了新的选择，而不是同一选择的 retry

## CLX attempt 为 `claim_expired`

### 当前口径

- `scheduled` 表示 sensor 已规划但 job 尚未领取，claim lease 为 9 分钟。
- job 以 compare-and-set 原子领取后变为 `running`，写入 `claim_owner / claim_token`，计算 lease 延长为 6 小时。
- 提交前必须以同一 owner/token 且未过期的 running claim 切为 `committing`，commit lease 为 1 小时；明细、partition 头和 attempt completion 都受同一 fencing 保护。
- scheduled、running 或 committing lease 到期时，原 attempt 保留 `claim_expired` 审计，新 attempt 使用递增 `attempt_no` 和不同 run key；另一侧 completed partition 不变。

### 排查

1. 查看 `status / scheduled_at / started_at / commit_started_at / claim_owner / claim_token / lease_expires_at / error.previous_status`。
2. 若 previous status 为 scheduled，查 Dagster run 是否根本没有启动；若为 running，查 worker 是否退出或计算超过 lease；若为 committing，查不可变写入阶段是否中断。
3. 确认只出现一个新 attempt；并发 sensor tick 应由 CAS 保证其余规划方复读 active/reuse 状态。把同一 attempt 交给第二 executor 时，它应只看到 running/committing，不再次调用 CLX engine。

## CLX partition 为 `upstream_drift`

### 原因

partition 在计算前后会重新读取本侧 ready marker。当前 hash 与 attempt 冻结的 `marker_snapshot_hash` 不一致时，输出被丢弃并标记 drift。

### 排查

- 比较 attempt 的 `marker_snapshot` 与 `freshquant.dagster_pipeline_markers` 当前文档
- 重点检查 `run_id / updated_at / payload.data_as_of / payload.source_version`
- 确认上游是否在 CLX 计算期间覆盖了同交易日 marker
- 只重试发生 drift 的一侧；另一侧 completed partition 不变

## CLX partition 因单个 symbol 错误失败

### 当前口径

- symbol 级异常会写入 attempt 的 `error.errors[]`；服务继续遍历同侧其余 symbol，只用于收集完整诊断。
- 当前发布门禁为零容忍。任意 symbol 计算错误都会使本侧 attempt 以 `PartitionInstrumentError` 失败，不提交已成功 symbol 的 completed partition。
- 失败只影响本侧；另一侧已有 completed partition 时保持不可变并在重试期间复用。

### 排查

```javascript
use freshquant_clx_daily_selection
db.partition_attempts.find({
  trade_date: "YYYY-MM-DD",
  asset_type: "stock", // 或 etf
  status: "failed",
  "error.type": "PartitionInstrumentError"
}).sort({attempt_no: -1})
```

1. 查看 `error.error_count` 和每条 `error.errors[].symbol / type / message`。
2. 按 symbol 检查日线缺失、bar 数、OHLCV 有限性、复权口径和原生 18 模型返回长度。
3. 修复输入或计算错误后只重试失败侧，确认下一次 `attempt_no` 递增。
4. 确认成功侧 sensor 返回 `action=reuse`，没有生成新的 partition。

不要把“其余 symbol 已完成诊断计算”解释为 partition completed，也不要手工提交缺少错误 symbol 的不完整输出。

### 错误码为 `QFQ_DATA_NOT_READY`

- shared QFQ reader 要求查询窗口内每个 bar 日期都有 active snapshot 覆盖，并以 `QFQDataNotReadyError` 返回 `scope/code/missing_dates`。
- 规划 attempt 时先从 raw candidate universe 通用剔除 QFQ marker 的 `source_exclusions`，再用 shared strict reader 只校验其余标的的目标日 BFQ 行。该阶段逐标的 `QFQ_DATA_NOT_READY` 会进入 `universe_evidence.reader_isolations[]`，记录 `code / classification / error_code / reason / source` 与 count/hash；不会伪造回 QFQ marker，也不会阻塞另一资产侧。
- 查 `candidate_universe_count = effective_universe_count + source_excluded_count + reader_isolation_count`，并核对 `effective_universe_hash / universe_isolation_hash` 与 partition run tags。残余 exclusion 交集、证据 hash/count 不一致、effective universe 为空或其他异常都会在创建 attempt 前结束规划。
- attempt 创建后只计算冻结的 `effective_instruments`。完整历史读取中再次出现 `QFQ_DATA_NOT_READY` 时，本侧仍按逐标的错误零容忍失败；服务不会以 `adj=1`、BFQ 或部分覆盖继续计算。
- 修复或补齐复权集合后，让 QFQ marker/pair 与上游 marker 形成新 generation，再只重试受影响侧；确认新 attempt 的 `data_version=qfq-daily-v1`，并保留旧隔离/失败事实用于审计。

## CLX 两侧都 completed 但没有 final 内容

先看 finalization dispatch 与当前 marker generation：

```javascript
use freshquant_clx_daily_selection
db.finalization_attempts.find({
  trade_date: "YYYY-MM-DD"
}).sort({batch_id: 1, attempt_no: 1})
```

- 没有 finalization attempt 且某一侧 `upstream_status=marker_missing`：finalizer 正常返回 waiting；补齐当前 marker，不要发布旧 generation。
- `scheduled` 超过 9 分钟或 `running` 超过 10 分钟：原 attempt 应 CAS 为 `claim_expired`，下一次 sensor 生成递增 attempt_no 和新 dispatch run key。
- `failed`：查看 `error`。前置异常或 publication 失败后，下一次 dispatch 必须使用新 `finalization_attempt_id/run_key`，不能复用已失败的 Dagster run key。
- job 启动即 tag 校验失败：核对 `fq_trade_date / fq_clx_batch_id / fq_clx_partition_ids / fq_clx_finalization_attempt_id / fq_clx_finalization_attempt_no / fq_clx_qfq_snapshot_pair_hash / fq_clx_qfq_{stock,etf}_snapshot_id / fq_clx_generation_order` 与该持久化 attempt；job 不接受 tag 临时改写 batch generation。
- `generation_drift`：sensor 规划后 marker、batch id 或 partition ids 已改变。旧 attempt 保留 failed 审计，等待当前 generation 两侧 completed 后再规划。

若 dispatch 已领取，再看 partial batch 是否为 `contract_mismatch`，并比较两个 partition：

- `trade_date` 与各自 marker trade date
- `evaluation_profile_id=production_v1`
- `switch_opt=1`
- `algorithm_version / data_version / parameter_hash`
- `schema_version / condition_catalog_version / line_definition_version`

finalizer 不接受跨交易日、跨 profile 或跨版本 join。修复失败侧/不一致侧后重新生成对应 partition，不覆盖已有不可变输出，也不重放旧 generation 的 pending/failed final。

## CLX 已有 final 内容但默认 latest 不显示

先显式查看中间态及 publication：

```powershell
$batch = Invoke-RestMethod 'http://127.0.0.1:15000/api/clx-daily-selection/batches/latest?include_partial=1'
$batch.publication
```

- `pending`：等待 finalizer 领取 publication。
- `publishing` 且 `lease_expires_at` 未过期：已有发布者持有 2 分钟 `claim_owner / claim_token` claim，finalizer sensor 应 skip，避免重复写 marker。
- `failed`：查看 `last_error`；下一次 finalizer 只以 `attempt_count+1` 重试 publication。
- `publishing` lease 已过期：新发布者必须用 status、attempt_count、旧 owner/token 和 lease 做 CAS 后领取；旧发布者不能把新 claim 覆盖为 failed/published。重试不重算两个 completed partition。
- 只有 `published/not_required` 进入默认 `/batches/latest`；其他 publication 状态在公共响应中保持 `release_status=partial / is_final=false`。

若同交易日上游 marker 已换代，先确认当前 batch generation。新 marker 会生成新的 selection key/batch id；旧 generation 即使已有 pending/failed final，也不会被 finalizer sensor继续发布。

若 `last_error.code=stale_publication`，表示新 generation 已先写入 `clx_daily_selection_ready`，随后恢复的旧 publisher 被 generation CAS 拒绝。此时旧 batch 必须保持 `publication.status=failed`，不能手工标为 published；同时核对 ready marker 仍是较新的 `generation_id / generation_order / publication_id`。同一 `publication_id` 的重试属于幂等复读，不应产生 stale 错误。`generation_order` 应为规范 UTC 微秒键 `YYYY-MM-DDTHH:mm:ss.ffffffZ|batch_id`，不要混用 `Z` 与 `+00:00` 原始字符串比较。

## CLX API health degraded 或历史接口报错

```powershell
Invoke-RestMethod http://127.0.0.1:15000/api/clx-daily-selection/health
Invoke-RestMethod http://127.0.0.1:15000/api/clx-daily-selection/model-catalog
```

- engine unavailable：查 API/Dagster Python 环境能否导入 `fqcopilot`
- `batch_available=false` 且 `single_available=true`：当前按设计走 `single_model_fallback`；确认结果记录 `fallback_reason=fq_clxs_all_unavailable`，不把该状态单独判为 health 失败
- batch 为缺少 `switch_opt` 的旧签名：确认 fallback reason 为 `fq_clxs_all_missing_switch_opt`
- `single_available=false`：查 `fq_clxs`；此时 production adapter 没有可用计算入口
- S0002 evidence unavailable：查 `fq_s0002_entrypoint3_evidence`
- profile 不是 `production_v1 / switch_opt=1` 或模型数不是 18：当前扩展/服务版本不一致，重新同步最新远程 main 并部署相关运行面
- `/history/signals` 只接受 `period=1d`；`endDate` 可省略并由 provider 解析最新交易日；barCount 不在 `1..2000` 或没有日线数据时返回请求错误

## Kline Slim 已加载 CLX 列表但图上没有 marker

### 排查顺序

1. 直接请求历史接口，确认 `markers_by_model` 非空：

```powershell
Invoke-RestMethod 'http://127.0.0.1:15000/api/clx-daily-selection/history/signals?symbol=000001&assetType=stock&period=1d&endDate=YYYY-MM-DD&barCount=250&includeRaw=1'
```

2. 确认：

- `calculation_profile.id=production_v1`
- `calculation_profile.switch_opt=1`
- `future_function_guard.passed=true`
- marker `trigger_date` 在当前 K 线日期范围内

3. 清掉过严的模型/条件筛选，并确认 `CLX信号` 工作台已开启。
4. 查 chart scene 的 `clxSignals.hasData`，以及最终 ECharts option 是否包含 `clx-signal-<sceneScopeId>` scatter series。
5. 点击 marker 不联动时，查 series data 的 `clxGroup` 和 controller 的 `seriesId` 过滤。

列表、时间轴或 tooltip 有数据但没有真实 scatter series，仍属于绘制链未完成。

## API 无响应

现象：

- `15000` 端口不可访问，或前端页面全部报接口错误。

先检查：

- `docker compose -f docker/compose.parallel.yaml ps`
- `py -3.12 script/freshquant_health_check.py --surface api --format summary`

处理：

- 重建 API：`docker compose -f docker/compose.parallel.yaml up -d --build fq_apiserver`
- 或优先使用 `powershell -ExecutionPolicy Bypass -File script/fq_apply_deploy_plan.ps1 -ChangedPath freshquant/rear/api_server.py -RunHealthChecks`

## ETF 前复权错误

本节排查当前线上 XTData QFQ A/B 消费链。

现象：
- ETF 在页面上跨扩缩股日出现价格断层
- 例如事件日后 close 约为事件日前的一半，但事件日前没有按前复权回落
- API 返回 `QFQ_DATA_NOT_READY/503`

先检查：
- `python -m freshquant.market_data.xtdata.qfq_worker status --scope etf --strict`
- `python -m freshquant.market_data.xtdata.qfq_worker audit --scope etf --mode full --code 512000`
- 查询 `quantaxis.qfq_ready` 指向的 `etf_adj_qfq_a/b` active collection，核对该 code 的日期 coverage、`snapshot_id` 与正因子
- 请求 `/api/stock_data?period=1d&symbol=512000&endDate=2025-08-08`

常见根因：
- active marker 落后最新 `etf_postclose_ready`，或 active slot 没有覆盖请求日期
- 请求 code 被 active slot `source_exclusions[]` 审计隔离
- intraday override 的 `base_snapshot_id` 与当前 active snapshot 不一致
- Redis Kline / StrategyConsumer 常驻窗口仍绑定旧 `adjustment_version`

处理：
- active slot 审计失败时，在单一 writer lease 下执行 `build --scope etf --target-date YYYY-MM-DD`；首次 bootstrap / 全历史 backfill 需要人工入口，正常 worker 不自动执行
- audit 通过后核对 marker CAS 与 reader deploy SHA，再重启受影响 reader/consumer 运行面以清空常驻旧版本
- 不手工修改 `active_slot`，不把 legacy `etf_adj` 回填成在线真值

## Web 页面空白

现象：

- `18080` 可打开但页面白屏，或单页能进、数据区全空。

先检查：

- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18080/`
- 浏览器 DevTools 是否是接口 4xx/5xx

处理：

- 重建前端：`docker compose -f docker/compose.parallel.yaml up -d --build fq_webui`

## XTData 链路不更新

现象：

- Kline 最新 bar 不动，Guardian 不触发，TPSL 无 tick。

先检查：

- `python -m freshquant.market_data.xtdata.market_producer`
- `python -m freshquant.market_data.xtdata.strategy_consumer --prewarm`
- `monitor.xtdata.trading_mode`
- `monitor.xtdata.screening_mode`
- `monitor.xtdata.prewarm.max_bars`
- `XTQUANT_PORT`

处理：

- 修正 `monitor.xtdata.trading_mode` / `monitor.xtdata.screening_mode` 与
  `monitor.xtdata.max_symbols`
- 核对 consumer 实际生效的 `prewarm.max_bars`（优先级：CLI 显式
  `--max-bars` > Mongo > 合同默认 `20000`；正式 supervisor 命令不再硬编码
  `--max-bars`）与 `queue_backlog_threshold`（缺省 `500`）
- 重启 producer / consumer
- 通过 `/runtime-observability` 看 `xt_producer` / `xt_consumer` 心跳与 backlog
- 若问题集中在开机或 deploy 后的短窗口，优先核对最新 runtime jsonl 是否已出现启动后的新心跳，再区分是“历史启动失败栈”还是“当前仍未恢复”。

## 宿主机运行面没有恢复

现象：

- API / Web health check 已通过，但宿主机 worker 没恢复。

先检查：

- `Get-Service fqnext-supervisord`
- `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status`
- `powershell -ExecutionPolicy Bypass -File script/check_freshquant_runtime_post_deploy.ps1 -Mode Verify -BaselinePath <baseline.json> -OutputPath <verify.json> -DeploymentSurface <surfaces>`

处理：

- 确认 `fqnext-supervisord` 为 `Running`
- 用 `script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces` 恢复命中的宿主机 surface
- 若 verify 失败，先修运行面，再重新执行正式 deploy

## Trade Calendar Failures

- If Dagster stock, ETF, Gantt, or daily-screening runs fail while resolving a trade date, inspect `freshquant.trade_calendar_cache` first.
- The expected document is `_id=cn_a:sina`; it must have non-empty `trade_dates` and `max_trade_date >= today`.
- `last_error_type`, `last_error_message`, and `fallback_hits` show whether FreshQuant is serving the last-known-good calendar after a Sina/AkShare request failure.
- In Docker, API and Dagster also share `FQ_TRADE_CALENDAR_STATE_DIR`; check `cn_a_sina.json` there if Mongo is unavailable or the cache document is missing.
- `trade_calendar_refresh_job` can complete in degraded mode when live Sina/AkShare fails but Mongo or the disk snapshot covers the current date; inspect the asset result fields `refresh_status`, `degraded`, `source_error_type`, and `source_error_message`.
- Run `trade_calendar_refresh_job` in Dagster to force a live refresh after the upstream endpoint recovers; a successful live refresh rewrites both Mongo and the disk snapshot.

## TPSL 无 tick / tick 队列积压（Redis 断连自愈）

现象：

- `fqnext_tpsl_worker` 反复崩溃或长时间无 tick
- `/api/ops/overview` 的 `dependencies.tick_queue.depth` 持续增长超过阈值（10000）

当前行为（P2-B）：

- `freshquant/tpsl/tick_listener.py` 对 Redis 连接类异常（ConnectionError/TimeoutError）指数退避重建 client（5s→60s），`run_forever` 不退出
- 解析/回调异常（毒消息）log+skip 继续消费，不再杀死监听器
- 故障演练：`docker restart fq_redis` 后 tpsl 应自动恢复不退出

处理：

- 先看 `D:/fqdata/log/fqnext_tpsl_worker_err.log` 尾部，确认是连接类还是毒消息
- 若 tick 队列已积压，恢复消费后深度会自然回落；长时间不回落则检查 consumer 是否停摆

## TPSL 标的已配 TP 且价格超档位但不触发（买入线 skipped 短路）

现象：

- 标的已配置 TP 档位且现价已超过档位，但 `om_exit_trigger_events` 无对应触发记录。

当前行为：

- #549 双账本引入的买入线短路曾导致：买入线评估返回 `skipped` 时本 tick 直接终止，
  TP/SL 评估永远不执行（生产实证 2026-08-11，恩华药业 002262 TP1 不触发，
  当日 worker 事件 `base_buyline` 10688 条、`takeprofit` 0 条）。
- 已修复：tick 处理顺序为「买入线评估（仅 `ready` 提交买单并终止本 tick）→ 止盈评估」；
  买入线 `skipped` 不阻断双集合标的（同时命中止盈 universe）的后续评估，
  buy-line-only 标的本 tick 终止。

处理：

- 检查该标的是否同时配置了买入线（`load_active_buy_line_codes`）；
- 核对 worker 当日运行时 jsonl（`D:/fqdata/log/fqnext_tpsl_worker` 目录）中
  `base_buyline` 与 `takeprofit` 事件比例；
- 若仍不触发，检查 `om_takeprofit_states.armed_levels` 与
  `om_takeprofit_profiles` 配置是否就绪。

## Guardian 在 trading_mode=false 下保持 RUNNING（idle 待命）

现象：

- guardian 日志出现 `trading lines disabled. Entering idle standby`

当前行为（P1-E）：

- `monitor_stock_zh_a_min.py` 在 trading_mode=false 且无启用线时不再 exit(0)，改为每 60s 打一次 idle 日志保持 RUNNING
- 避免 supervisord 按 autorestart + startsecs=5 反复拉起、快速退出耗尽 startretries 进 FATAL

处理：

- 该状态是预期状态，不算异常；部署 reconcile / 运维页 KPI 不再误报
- 若 guardian 崩溃且 stderr 无 `trading lines disabled`，按真实故障排查

## TDXHQ 探测失败（端点键收敛）

现象：

- `/api/ops/overview` `dependencies.tdxhq.ok=false`，error 为 Connection refused

当前规范（P4-A）：

- 端点键收敛为单键 `FRESHQUANT_TDX__HQ_ENDPOINT`（容器内 `http://fq_tdxhq:5001`，宿主机 `http://127.0.0.1:15001`）
- 旧键 `FRESHQUANT_TDX__HQ__ENDPOINT` 命中时后端打 warning 并过渡兼容；`freshquant/gateway/__init__.py` 默认值兜底时打 warning
- 配置以 `D:\fqpack\config\fqnext.compose.env` 与 `deployment/examples/envs.fqnext.example` 为准

处理：

- 先核对容器 env：`docker exec fqnext_20260223-fq_apiserver-1 printenv | findstr TDX`
- 若命中旧键，改回单键后重建 apiserver（复用现有镜像）

## Supervisor 假启动（FAKE_START_DETECTED）与服务级自愈

现象：

- 部署/重启期间某程序长时间 Exited，supervisor RPC 显示 `startProcess` 已调用但
  pid 仍为 0、`start` 时间戳不更新、程序日志无任何新写入
- 根因：supervisord-go 状态机卡死——`startProcess` 返回 True 但从未真正 spawn 新进程

当前行为（P3-C）：

- `script/fqnext_host_runtime.py` 在 `startProcess` 后 3 秒窗口内校验 pid / start
  时间戳是否变化；无变化即判定 `FAKE_START_DETECTED`，快速失败（不再傻等 RUNNING 超时）
- `script/fqnext_host_runtime_ctl.ps1` 捕获 `FAKE_START_DETECTED` 后直接重启
  `fqnext-supervisord` 服务（admin bridge / 管理员），服务起来后按 autostart
  拉起全部程序——这是已被验证的恢复路径
- 处理时在部署输出中会看到 `supervisor fake start detected; recovering via service restart`，
  随后 `wait-settled` 校验 9/9

处理：

- 若部署输出含 FAKE_START_DETECTED 且最终 9/9 Running，属自愈成功，无需人工干预
- 若服务重启后仍有程序不 Running，按"宿主机运行面没有恢复"一节继续排查
