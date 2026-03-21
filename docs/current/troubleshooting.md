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
