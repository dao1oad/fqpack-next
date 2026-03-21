---
description: FreshQuant 正式部署与重部署 - 当用户要求部署、重部署、同步 main 后 formal deploy、排查 deploy 失败、核对 runtime verify 时使用
trigger:
  - "部署"
  - "重部署"
  - "formal deploy"
  - "deploy main"
  - "runtime verify"
---

用户请求 FreshQuant 部署相关操作。

## 正式部署前置

- 代码真值必须是最新远程 `origin/main`
- 如果需要修复 deploy 阻塞项，先走 `feature branch -> PR -> merge remote main`
- 合并后把本地 `main` 同步到 `origin/main`
- 正式 deploy 只从 `D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production` 执行

## 正式部署命令

```powershell
git fetch origin --prune
git checkout main
git pull --ff-only origin main
git -C D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production fetch origin main
git -C D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production checkout deploy-production-main
git -C D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production merge --ff-only origin/main
py -3.12 -m uv sync --frozen
py -3.12 script/ci/run_formal_deploy.py --repo-root . --format summary
```

在 deploy mirror 目录 `D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production` 中执行：

```powershell
py -3.12 -m uv sync --frozen
py -3.12 script/ci/run_formal_deploy.py --repo-root . --format summary
```

## 必查证据

- `D:/fqpack/runtime/formal-deploy/production-state.json`
- `D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/plan.json`
- `D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/runtime-baseline.json`
- `D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/runtime-verify.json`
- `D:/fqpack/runtime/formal-deploy/runs/<timestamp>-<sha>/result.json`

## 健康检查与运维核对

- API：`py -3.12 script/freshquant_health_check.py --surface api --format summary`
- Web：`py -3.12 script/freshquant_health_check.py --surface web --format summary`
- TradingAgents：`py -3.12 script/freshquant_health_check.py --surface tradingagents --format summary`
- Runtime verify：`powershell -ExecutionPolicy Bypass -File script/check_freshquant_runtime_post_deploy.ps1 -Mode Verify -BaselinePath <baseline.json> -OutputPath <verify.json> -DeploymentSurface <surfaces>`

## 关键纪律

- 不要把开发 worktree 直接当正式 deploy 来源
- 不要跳过 `CaptureBaseline -> deploy -> health check -> Verify`
- 不要只看命令退出码，必须读 formal deploy artifacts
- 如果本轮没有代码变化但用户要求重部署，仍以 formal deploy 产物判断是 no-op 还是实际部署

## Dagster 特殊项

- Dagster Linux 容器内必须使用 `DAGSTER_HOME=/opt/dagster/home`
- Dagster Linux 容器内必须使用 `FRESHQUANT_DAGSTER__HOME=/opt/dagster/home`
- 如果容器日志出现 `DAGSTER_HOME "D:/fqpack/dagster"`，说明主工作树 `.env` 的 Windows 路径泄漏进了容器；优先修 `docker/compose.parallel.yaml` 的 Dagster `environment` 覆盖，再重跑 formal deploy

请按上述顺序执行，并以 formal deploy artifacts + health check + runtime verify 作为是否完成的唯一依据。
