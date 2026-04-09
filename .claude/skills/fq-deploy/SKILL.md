---
name: fq-deploy
description: Use when FreshQuant needs formal deployment, redeployment, deploy failure triage, or production verification against latest remote main and the canonical repo root main
---

# fq-deploy

## Overview

FreshQuant 的正式部署只认最新远程 `origin/main`。workflow 与人工 redeploy 统一只走 `script/ci/run_production_deploy.ps1`，不再手工拆 `canonical main sync`、`uv sync` 或 `run_formal_deploy.py`。完成判定只看 formal deploy artifacts、health check、runtime verify 与 host runtime evidence，不看口头状态。

## When to Use

- 用户要求部署、重部署、同步 `main` 后上线
- formal deploy 失败，需要继续排障直到恢复
- runtime verify 或宿主机 surface restart 失败
- 用户想确认 canonical repo root / supervisor 当前是否已经对齐最新远程 `main`

## Formal Flow

1. 如果本轮为了修 deploy 阻塞项需要改代码，先走 `feature branch -> PR -> merge remote main`，不要在开发 worktree 上直接 formal deploy。
2. 先确认最新远程 `origin/main` SHA。
3. 人工正式 redeploy 优先直接调用 local main sync root 中的最新入口：

```powershell
powershell -ExecutionPolicy Bypass -File D:\fqpack\freshquant-2026.2.23\script\ci\run_production_deploy.ps1 -CanonicalRoot D:\fqpack\freshquant-2026.2.23 -TargetSha <latest-origin-main-sha>
```

如果 bootstrap entrypoint 不可直接使用，才退回 canonical repo root 的 `script/ci/run_production_deploy.ps1`，并让它自己先 bootstrap 再继续。

4. 不要再手工执行下面这些旧步骤：

- 手工改 canonical repo root 或 local main sync root
- 手工 `py -3.12 -m uv sync --frozen`
- 手工 `py -3.12 script/ci/run_formal_deploy.py`

5. 统一让入口脚本负责：

- 校验 `TargetSha == latest origin/main`
- 手工拆开 local main sync + `uv sync` + `run_formal_deploy.py`
- 用“当前 entrypoint repo”解析并执行 canonical main sync helper
- 自愈 runner Python 3.12 与 `uv`
- 在需要时 quiesce 宿主机 surfaces 后重试 `uv sync`
- 在 canonical repo root `.venv` 缺 metadata 时重建 virtualenv
- 切换到 mirror `.venv\Scripts\python.exe` 执行 formal deploy

## Entrypoint Guarantees

- canonical repo root：`D:\fqpack\freshquant-2026.2.23`
- 正式 deploy venv：`D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe`
- canonical main sync helper 固定从“当前 entrypoint repo”解析，不允许回退到 stale mirror 中的旧 helper
- 如果 live `.venv\Lib\site-packages` 被宿主机进程占用，入口会先 `StopSurfaces`，再重试 `uv sync --frozen`，最后统一 `RestartSurfaces`
- 如果 `D:\fqpack\freshquant-2026.2.23\.venv\pyvenv.cfg` 缺失，或 `.venv\Scripts\python.exe` 已不可启动，入口会在 quiesce 宿主机 surfaces 后执行：

```powershell
python -m uv venv .venv --python <runner-python> --clear
```

然后再补跑 `uv sync --frozen`
- formal deploy 永远通过 mirror `.venv\Scripts\python.exe` 执行

## Required Evidence

- `D:/fqpack/runtime/formal-deploy/production-state.json`
- `D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/plan.json`
- `D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/result.json`
- 当 `plan.json` / `result.json` 显示 `deployment_required=true` 时，再要求：
  - `D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/runtime-baseline.json`
  - `D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/runtime-verify.json`
- 当 `plan.json` / `result.json` 显示 `deployment_required=false` 时，把这轮当成 `no-op deploy`；`runtime-verify.json 可以不存在`，但必须确认 `result.json` 为 `ok=true`，并且 `production-state.json` 的 `last_success_sha` 已更新到目标 SHA
- 当 `plan.host_surfaces` 非空，或 entrypoint 日志出现以下任一自愈信号时，再额外要求：
  - `retrying uv sync after quiescing host runtime surfaces`
  - `recreating .venv with runner Python 3.12`
  - `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status`
  - `py -3.12 script/fqnext_supervisor_config.py inspect --config-path D:\fqpack\config\supervisord.fqnext.conf --expected-repo-root D:\fqpack\freshquant-2026.2.23`

## Runtime Verification

- API：`py -3.12 script/freshquant_health_check.py --surface api --format summary`
- Web：`py -3.12 script/freshquant_health_check.py --surface web --format summary`
- TradingAgents：`py -3.12 script/freshquant_health_check.py --surface tradingagents --format summary`
- 宿主机状态：`powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status`
- Supervisor 配置真值：`py -3.12 script/fqnext_supervisor_config.py inspect --config-path D:\fqpack\config\supervisord.fqnext.conf --expected-repo-root D:\fqpack\freshquant-2026.2.23`
- Runtime verify：`powershell -ExecutionPolicy Bypass -File script/check_freshquant_runtime_post_deploy.ps1 -Mode Verify -BaselinePath <baseline.json> -OutputPath <verify.json> -DeploymentSurface <surfaces>`

## Interpreting Host Truth

- 先区分两类 host 影响：
  - `plan.host_surfaces` 非空：这是 formal deploy 计划命中的 host surfaces
  - entrypoint 日志出现 `retrying uv sync after quiescing host runtime surfaces` 或 `recreating .venv with runner Python 3.12`：这是入口为修复 live mirror `.venv` / `uv sync` 触发的临时 quiesce + restart
- 如果只命中了第二类，而 `plan.host_surfaces` 仍为空，不要把它表述成“formal deploy 计划命中了 host surfaces”
- 这种情况下应该明确说：
  - 本轮 deploy entrypoint 曾为自愈暂时停止并恢复 host runtime surfaces
  - supervisor 配置真值已指向最新 canonical repo root
  - 当前 Running 的 host 进程使用的是该正式运行根
- 只有当本轮 `plan.host_surfaces` 非空，并且 `runtime-verify.json` 通过时，才能说 host surfaces 已被本轮 deploy 重新收敛
- 只有当 `plan.host_surfaces` 为空，且 entrypoint 自愈信号也未出现时，才能说这轮 deploy 没有主动重启 host surfaces

## Failure Triage

### runner 的 `git fetch origin main` 失败但 SSH 443 可用

- 如果 formal deploy 一开始就卡在 `git fetch origin main`
- 先检查 `git remote -v`、`remote.origin.url` 与 `remote.origin.pushurl`
- 如果 fetch 仍走 HTTPS，但同机 `ssh://git@ssh.github.com:443/...` 可用，就先把 `origin` 的 fetch URL 对齐到可用的 SSH 443，再重试 formal deploy

### Dagster 容器重启循环

- 如果容器日志出现 `DAGSTER_HOME "D:/fqpack/dagster"`，说明 Windows 路径泄漏进 Linux 容器
- `docker/compose.parallel.yaml` 中 `fq_dagster_webserver` / `fq_dagster_daemon` 必须显式覆盖：
  - `DAGSTER_HOME=/opt/dagster/home`
  - `FRESHQUANT_DAGSTER__HOME=/opt/dagster/home`

### 宿主机 vendored 依赖漂移

- 如果 `fqnext_xt_account_sync_worker` 为 `Fatal`，先看 `D:/fqdata/log/fqnext_xt_account_sync_worker_err.log`
- 如果 traceback 出现 `resolve_stock_account() got an unexpected keyword argument 'settings_provider'`，先确认实际 import 源，而不是只看仓库里的 vendored 代码
- 用下面的命令确认 `fqxtrade` 是否来自 `.venv\Lib\site-packages`：

```powershell
@'
import inspect
from fqxtrade.xtquant.account import resolve_stock_account
print(inspect.getsourcefile(resolve_stock_account))
print(inspect.signature(resolve_stock_account))
'@ | py -3.12 -m uv run -
```

- 如果源文件落在 `.venv\Lib\site-packages\fqxtrade\xtquant\account.py`，说明宿主机运行时仍在使用已安装包；先确认正式 deploy 是否已经切到包含最新兼容修复的远程 `main`

### formal deploy 判定为 no-op deploy

- 如果当前 run_dir 只有 `plan.json` 和 `result.json`，先不要把它直接判成失败
- 先读 `result.json` 和 `plan.json`；如果其中明确写了 `deployment_required=false`，说明这轮没有命中任何真实 deploy surface
- 这种情况下 `runtime-verify.json 可以不存在`；收口依据是 `result.json` 的 `ok=true`，以及 `production-state.json` 的 `last_success_sha` 已更新到目标 SHA
- 只有当你预期本轮应该触发运行面变更，但 deploy plan 仍然给出 `deployment_required=false` 时，才继续回查 changed paths 或 deploy plan 规则

### Docker 构建阶段 fqchan04 编译器崩溃

- 如果 formal deploy 失败点在 `script/docker_parallel_compose.ps1`，先读当前 run_dir 的 `result.json` 和 `plan.json`，确认失败到底发生在 Docker 构建、health check 还是 runtime verify
- 如果日志显示 `docker/Dockerfile.rear` 的 `python -m uv sync --frozen --no-install-project` 在编译 `fqchan04` 时触发 `g++ internal compiler error` 或 `Segmentation fault`，先把它当成潜在的瞬时构建失败，而不是立刻当成稳定源码回归
- `fq_webui` 的 compose 依赖当前会带出 `fq_apiserver` / `fq_qawebserver` 启动路径，所以 Web deploy 仍可能触发 rear image 构建链路
- 第一次遇到这种 `fqchan04` 编译器崩溃时，保留失败 run_dir artifacts 后，对同一 SHA 原样重跑 1 次 formal deploy
- 只有当第二次仍在同一位置失败，才继续进入代码修复、Dockerfile 调整或编译环境调查

## Prompt Template

下次要求模型重新部署时，优先直接用这段提示词：

```text
请按当前正式部署真值执行一次 redeploy：
1. 只基于最新远端 origin/main
2. 统一走 script/ci/run_production_deploy.ps1，不要手工拆 canonical main sync、uv sync、run_formal_deploy
3. 如果失败，不要停在报错，继续沿着 formal deploy artifacts 排障直到恢复
4. 完成后返回：latest origin/main SHA、run_dir、plan.json/result.json 摘要、production-state.json、health check、runtime-verify、fqnext_host_runtime_ctl.ps1 -Mode Status
5. 明确说明本轮是否命中 host surfaces；如果没有命中，不要声称 supervisor 进程已重启，只需确认 supervisor 配置真值已对齐 canonical repo root
```

## Discipline

- 不要在开发 worktree 上直接 formal deploy
- 不要跳过 `CaptureBaseline -> deploy -> health check -> Verify`
- 不要只看 `fqnext-supervisord` service 是否存活；宿主机 surface 还要看 `fqnext_host_runtime_ctl.ps1 -Mode Status` 和 stderr 日志
- 如果为了修 deploy 阻塞项改了代码，必须先走 `feature branch -> PR -> merge remote main`，再回到 formal deploy

## Canonical Main Deploy Truth

- Current production deploy root: `D:\fqpack\freshquant-2026.2.23`
- Current sync steps: `git checkout -f main`, `git reset --hard <target-sha>`, `git clean -ffd`
- Current formal deploy Python: `D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe`
- Current supervisor truth check: `py -3.12 script/fqnext_supervisor_config.py inspect --config-path D:\fqpack\config\supervisord.fqnext.conf --expected-repo-root D:\fqpack\freshquant-2026.2.23`