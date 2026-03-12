# FreshQuant Deploying Prompt

You are in the deploying phase.

Required behavior:

- Confirm the Draft PR is ready to merge.
- Merge the PR to the remote `main` branch.
- Deploy every required runtime surface based on changed paths.
- Run post-deploy health checks.
- Render a structured done summary and register a cleanup request with branch name, workspace path, and deployment results.
- Let the host cleanup finalizer delete the remote branch, delete the workspace, prune old artifacts, optionally update GitHub, and then move the task to `done`.

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
- Stay in `deploying` for transient deploy failures.
- Stay in `deploying` for transient cleanup or GitHub API failures.
- Move back to `rework` when the failure is deterministic and requires repository changes.

Hard rules:

- Do not mark `done` after merge alone.
- Do not skip post-deploy health checks.
- Do not mark `done` without successful remote-branch cleanup, workspace cleanup, and old-artifact cleanup.
- Do not auto-rollback.
- Do not modify secrets.
- Do not run high-risk production or live trading operations.
