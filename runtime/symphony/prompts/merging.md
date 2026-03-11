# FreshQuant Merging Prompt

You are in the Merging phase.

Required behavior:

- Confirm the Draft PR is ready to merge.
- Merge the PR to the remote `main` branch.
- Deploy every required runtime surface based on changed paths.
- Run post-deploy health checks.
- Post a structured deployment comment to Linear.
- Only move the issue to `Done` after merge, deploy, health checks, and deployment trace succeed.

Deployment matrix:

- If Docker runtime modules changed, run:
  - `docker compose -f docker/compose.parallel.yaml up -d --build`
- If `runtime/symphony/**` changed, run:
  - `powershell -ExecutionPolicy Bypass -File runtime\\symphony\\scripts\\sync_freshquant_symphony_service.ps1`
  - `Restart-Service fq-symphony-orchestrator`
  - `Invoke-WebRequest http://127.0.0.1:40123/api/v1/state`

Failure handling:

- Retry deploy failures a small bounded number of times.
- Stay in `Merging` for transient deploy failures.
- Move back to `Rework` when the failure is deterministic and requires repository changes.

Hard rules:

- Do not mark `Done` after merge alone.
- Do not skip post-deploy health checks.
- Do not mark `Done` without a deployment comment in Linear.
- Do not auto-rollback.
- Do not modify secrets.
- Do not run high-risk production or live trading operations.
