---
name: fq-deploy
description: Use when FreshQuant needs formal deployment, redeployment, deploy failure triage, or production verification against the main deploy mirror
---

# fq-deploy

## Overview

FreshQuant 的正式部署只认最新远程 `origin/main`，并且只从 `D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production` 执行。完成判定只看 formal deploy artifacts、health check 和 runtime verify，不看口头状态。

## When to Use

- 用户要求部署、重部署、同步 `main` 后上线
- formal deploy 失败，需要继续排障直到恢复
- runtime verify 或宿主机 surface restart 失败

## Formal Flow

先在 canonical repo root 同步真值：

```powershell
git fetch origin --prune
git checkout main
git pull --ff-only origin main
```

再同步 deploy mirror：

```powershell
git -C D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production fetch origin main
git -C D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production checkout deploy-production-main
git -C D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production merge --ff-only origin/main
```

在 deploy mirror 中执行：

```powershell
py -3.12 -m uv sync --frozen
py -3.12 script/ci/run_formal_deploy.py --repo-root . --format summary
```

## Required Evidence

- `D:/fqpack/runtime/formal-deploy/production-state.json`
- `D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/plan.json`
- `D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/result.json`
- 当 `plan.json` / `result.json` 显示 `deployment_required=true` 时，再要求：
  - `D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/runtime-baseline.json`
  - `D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/runtime-verify.json`
- 当 `plan.json` / `result.json` 显示 `deployment_required=false` 时，把这轮当成 `no-op deploy`；`runtime-verify.json 可以不存在`，但必须确认 `result.json` 为 `ok=true`，并且 `production-state.json` 的 `last_success_sha` 已更新到目标 SHA

## Runtime Verification

- API：`py -3.12 script/freshquant_health_check.py --surface api --format summary`
- Web：`py -3.12 script/freshquant_health_check.py --surface web --format summary`
- TradingAgents：`py -3.12 script/freshquant_health_check.py --surface tradingagents --format summary`
- 宿主机状态：`powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status`
- Runtime verify：`powershell -ExecutionPolicy Bypass -File script/check_freshquant_runtime_post_deploy.ps1 -Mode Verify -BaselinePath <baseline.json> -OutputPath <verify.json> -DeploymentSurface <surfaces>`

## Failure Triage

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

## Discipline

- 不要在开发 worktree 上直接 formal deploy
- 不要跳过 `CaptureBaseline -> deploy -> health check -> Verify`
- 不要只看 `fqnext-supervisord` service 是否存活；宿主机 surface 还要看 `fqnext_host_runtime_ctl.ps1 -Mode Status` 和 stderr 日志
- 如果为了修 deploy 阻塞项改了代码，必须先走 `feature branch -> PR -> merge remote main`，再回到 formal deploy
