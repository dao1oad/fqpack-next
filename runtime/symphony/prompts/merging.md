# FreshQuant Merging Prompt

You are in the Merging phase.

Required behavior:

- Confirm the Draft PR is ready to merge.
- Merge the PR to the remote `main` branch.
- Deploy every required runtime surface based on changed paths.
- Run post-deploy health checks.
- Render a structured deployment comment body and register a cleanup request with branch name, workspace path, and comment body.
- Let the host cleanup finalizer delete the remote branch, delete the issue workspace, prune old artifacts, post the final deployment comment to Linear, and then move the issue to `Done`.

Deployment matrix:

- If Docker runtime modules changed, run:
  - `docker compose -f docker/compose.parallel.yaml up -d --build`
- If `runtime/symphony/**` changed, run:
  - `powershell -ExecutionPolicy Bypass -File runtime\\symphony\\scripts\\sync_freshquant_symphony_service.ps1`
  - `Restart-Service fq-symphony-orchestrator`
  - `Invoke-WebRequest http://127.0.0.1:40123/api/v1/state`

Failure handling:

- Retry deploy failures a small bounded number of times.
- Retry cleanup/finalizer failures a small bounded number of times.
- Stay in `Merging` for transient deploy failures.
- Stay in `Merging` for transient cleanup or Linear API failures.
- Move back to `Rework` when the failure is deterministic and requires repository changes.

Hard rules:

- Do not mark `Done` after merge alone.
- Do not skip post-deploy health checks.
- Do not post the final deployment comment to Linear before cleanup succeeds.
- Do not mark `Done` without successful remote-branch cleanup, workspace cleanup, old-artifact cleanup, and the final deployment comment in Linear.
- Do not auto-rollback.
- Do not modify secrets.
- Do not run high-risk production or live trading operations.
