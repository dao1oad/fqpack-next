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

- Web / TradingAgents 相关镜像构建在 `FROM node:22-alpine` 前后卡住
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
- 当前方案是否把 `om_*` / `stock_fills` 仅作为兼容投影或排障参考，而不是 primary truth

常见根因：

- 把现有 `om_*` 账本误当成 rebuild 真值来源
- 先写代码、后补治理，跳过 GitHub Issue 前置要求

处理：

- 先补 GitHub Issue，再进入编码或执行阶段
- 若方案不是 broker truth 驱动，立即停止；重写为只基于 `xt_orders`、`xt_trades`、`xt_positions` 的 rebuild 输入
- 不要用 legacy `om_*`、`stock_fills`、`stock_fills_compat` 反推正式 rebuild 主账本

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
- 再确认 `holding.py` / `entry_adapter` 当前已经优先返回 v2 entry / slice，而不是回退 legacy `stock_fills` 或 `buy_lots`
- 若记录仍缺 `date/time`，优先查对应 `trade_time` 是否存在，再查该 symbol 是否还停留在旧账本

## 券商有持仓但没有“按持仓入口止损”

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
print('buy_lots', repo.list_buy_lots(symbol=symbol))
print('gaps', repo.list_reconciliation_gaps(symbol=symbol))
print('resolutions', repo.list_reconciliation_resolutions(symbol=symbol))
'@ | py -3.12 -m uv run -`

常见根因：

- 历史 mixed-state 同时保留了 open `om_position_entries` 和 open legacy `om_buy_lots`
- 旧对账口径把两者同时计入 internal remaining，随后误判为 `ledger > broker`
- 错误 `auto_close_allocation` 先把 V2 entry 关掉，只剩 legacy lot 留在兼容层

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

处理：

- 保留宿主机 `.env` 的 Windows 路径给本机链路使用，但在 `docker/compose.parallel.yaml` 的 `fq_dagster_webserver` / `fq_dagster_daemon` 下显式覆盖：
  - `DAGSTER_HOME=/opt/dagster/home`
  - `FRESHQUANT_DAGSTER__HOME=/opt/dagster/home`
- 重新执行命中的 Docker deploy 或整轮 formal deploy
- 再次执行 `check_freshquant_runtime_post_deploy.ps1 -Mode Verify`，确认 Dagster 容器从 `Restarting` 恢复为 `running`

## ETF 前复权未生效但 Dagster run 显示成功

现象：

- KlineSlim / ETF 日线在拆分、扩缩股之后仍显示 bfq 价格
- `quantaxis.etf_xdxr` 缺少目标 ETF 的历史事件，但 Dagster `etf_data_schedule` 显示成功
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
- Dagster `etf_xdxr` 资产会对本次同步中 `empty/preserved` 的可疑 code 追加一次近期覆盖审计；如果近窗口内源侧有事件但库里没有，或者所有 HQ host 都不可达，asset 会直接 fail，不再把 run 记成成功
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

现象：
- ETF 在页面上跨扩缩股日出现价格断层
- 例如事件日后 close 约为事件日前的一半，但事件日前没有按前复权回落

先检查：
- `python -m freshquant.cli etf.xdxr save --code 512000`
- `python -m freshquant.cli etf.adj save --code 512000`
- `python -m freshquant.cli etf.xdxr save --code 512800`
- `python -m freshquant.cli etf.adj save --code 512800`
- 查询 `quantaxis.etf_xdxr` 是否存在 `category=11` / `suogu`
- 查询 `quantaxis.etf_adj` 是否在事件日前生成了 `adj=0.5` 这类因子
- 请求 `/api/stock_data?period=1d&symbol=512000&endDate=2025-08-08`

常见根因：
- `quantaxis.etf_xdxr` 缺失扩缩股事件，导致 `etf_adj` 整段生成成 `1.0`
- ETF 历史库已更新，但没有重跑 `etf_xdxr -> etf_adj`
- 旧实现把上游空响应当真，单次同步把已有 `etf_xdxr` 清空

处理：
- 优先重跑 `etf.xdxr` 和 `etf.adj`
- 如果是全市场历史缺口，执行一次 ETF 全量回填：
  - `python -m freshquant.cli etf.xdxr save`
  - `python -m freshquant.cli etf.adj save`
- 如果库里 `etf_adj` 已正确，而页面仍错误，再查 `/api/stock_data` 所在运行面是否仍在读旧库或旧容器

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
- `monitor.xtdata.mode`
- `XTQUANT_PORT`

处理：

- 修正 `monitor.xtdata.mode` 与 `monitor.xtdata.max_symbols`
- 重启 producer / consumer
- 通过 `/runtime-observability` 看 `xt_producer` / `xt_consumer` 心跳与 backlog

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
