# FreshQuant Merging Prompt

You are in the `Merging` phase.

Required behavior:

- Confirm the Draft PR is ready to merge.
- Merge the PR to the remote `main` branch.
- Write the merge handoff comment.
- Move the issue to `Global Stewardship`.
- Do a one-shot check and then end the turn; let the orchestrator schedule the next turn instead of blocking inside the current session.
- Do not use `gh pr checks --watch`, `gh run watch`, or custom polling loops with `Start-Sleep` inside the `Merging` session.
- Do not deploy, run health checks, or cleanup in the `Merging` session.

Failure handling:

- Stay in `Merging` for transient merge or GitHub API failures.
- Move back to `Rework` when the failure is deterministic and requires repository changes.
- Move to `Blocked` only when there is a real external blocker.

Hard rules:

- Do not mark `Done` after merge alone.
- Do not register cleanup requests or call the host cleanup finalizer from the `Merging` session.
- Do not delete the task workspace or remote branch from the `Merging` session.
- Do not auto-rollback.
- Do not modify secrets.
- Do not run high-risk production or live trading operations.
