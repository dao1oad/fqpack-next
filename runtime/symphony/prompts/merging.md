# FreshQuant Merging Prompt

You are in the `Merging` phase.

Required behavior:

- Confirm the PR is ready to merge.
- Use GitHub PR truth as the merge truth: required checks, unresolved review threads, mergeability, and ruleset policy.
- Merge the PR to the remote `main` branch.
- Write the merge handoff comment as a structured handoff packet.
- The handoff packet must include `Source Issue`, `Source PR`, `Merge Commit`, `Merged At`, `PR Head SHA`, `Base SHA`, `Changed Paths`, `Suggested Deployment Surfaces`, `Suggested Docker Services`, `Suggested Host Surfaces`, `Docs Synced`, `Cleanup Targets`, `Verification Hints`, and `Contract Version`.
- Move the issue to `Global Stewardship`.
- Do a one-shot check and then end the turn; let the orchestrator schedule the next turn instead of blocking inside the current session.
- Do not use `gh pr checks --watch`, `gh run watch`, or custom polling loops with `Start-Sleep` inside the `Merging` session.
- Do not deploy, run health checks, or cleanup in the `Merging` session.

Failure handling:

- Stay in `Merging` while required checks are pending or when the failure is transient.
- Move back to `Rework` when the failure is deterministic, repository-side, and requires a new commit or review-thread resolution.
- Move to `Blocked` only when there is a real external blocker.

Hard rules:

- Do not mark `Done` after merge alone.
- Treat the handoff packet as candidate input for `Global Stewardship`, not as runtime-delivery truth.
- Do not register cleanup requests or call the host cleanup finalizer from the `Merging` session.
- Do not delete the task workspace or remote branch from the `Merging` session.
- Do not auto-rollback.
- Do not treat comments or ad hoc approval text as merge truth.
- Do not retry merge when GitHub truth has not changed.
- Do not modify secrets.
- Do not run high-risk production or live trading operations.
