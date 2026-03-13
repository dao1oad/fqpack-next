# FreshQuant Merging Prompt

You are in the `Merging` phase.

Required behavior:

- Confirm the Draft PR is ready to merge.
- Merge the PR to the remote `main` branch.
- Deploy every required runtime surface based on changed paths.
- Run post-deploy health checks.
- Do a one-shot check and then end the turn; let the orchestrator schedule the next turn instead of blocking inside the current session.
- Do not use `gh pr checks --watch`, `gh run watch`, or custom polling loops with `Start-Sleep` inside the `Merging` session.
- Render a structured done summary and register a cleanup request with branch name, workspace path, and deployment results.
- When registering the cleanup request, write the deployment summary to a UTF-8 markdown file and pass `-DeploymentCommentBodyPath` instead of inlining long markdown into the PowerShell command line.
- Register cleanup only through `runtime/symphony/scripts/request_freshquant_symphony_cleanup.ps1`.
- Do not run `Remove-Item`, `git worktree remove`, or other direct workspace-deletion commands against the task workspace from the Codex session.
- Let the host cleanup finalizer delete the remote branch, delete the workspace, prune old artifacts, update GitHub, and then move the task to `Done`.

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
- Stay in `Merging` for transient cleanup or GitHub API failures.
- Move back to `Rework` when the failure is deterministic and requires repository changes.
- Do not move a merged issue to `Blocked` only because cleanup or host-side retries still need to finish; keep it in `Merging` unless there is a real external blocker.

Hard rules:

- Do not mark `Done` after merge alone.
- Do not skip post-deploy health checks.
- Do not mark `done` without successful remote-branch cleanup, workspace cleanup, and old-artifact cleanup.
- Do not auto-rollback.
- Do not modify secrets.
- Do not run high-risk production or live trading operations.
