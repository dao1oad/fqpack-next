# Workflow Rules

- GitHub PR + CI + merge gate is the code-delivery truth; direct `feature branch -> PR` is allowed.
- High-impact, breaking, or stewardship-tracked work should open a GitHub Issue first.
- For Symphony-managed tasks, GitHub Issue is the formal task entry and execution contract.
- Deploy + health check + cleanup is the runtime-delivery truth; if a round includes real deploy, runtime ops check is also required before closing.
- These three surfaces together define the formal truth; memory only bootstraps from them.
- Issue body should already define background, goal, scope, non-goals, acceptance criteria, and deployment impact.
- There is no separate design or manual approval gate in the formal workflow.
- The formal issue-managed flow is `Issue -> In Progress -> Rework -> Merging -> Global Stewardship -> Done`; `Blocked` is only for real external blockers.
- `Rework` is only for deterministic pre-merge repository-side failures. Post-merge deploy or runtime problems do not go back to `Rework`.
- Never do task work on local `main`; use a feature branch and PR. If Symphony manages the task, use the issue branch and its PR.
- `Global Stewardship` owns deploy, health check, runtime ops check, cleanup, and follow-up issue creation for issue-managed tasks.
- If post-merge code repair is needed, create or reuse a follow-up issue. Do not create a repair PR directly from `Global Stewardship`.
- Memory context is a bootstrap aid. It must not override GitHub state, `docs/current/**`, or real deploy evidence.
