# 当前排障

第二阶段的排障顺序统一为：先确认运行面，再确认数据流，再确认页面或单个模块。不要先改代码。

## 基础命令

```powershell
docker compose -f docker/compose.parallel.yaml ps
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/components
Get-ChildItem logs/runtime -Recurse -Filter *.jsonl | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName,LastWriteTime
```

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

## API 无响应

现象：

- `15000` 端口不可访问，或前端页面全部报接口错误。

先检查：

- `docker compose -f docker/compose.parallel.yaml ps`
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/components`

处理：

- 重建 API：`docker compose -f docker/compose.parallel.yaml up -d --build fq_apiserver`

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
