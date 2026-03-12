---
tracker:
  kind: github
  repo: dao1oad/fqpack-next
  auth_token: $GITHUB_TOKEN
  managed_label: symphony
  review_required_label: design-review
  blocked_label: blocked
  state_labels:
    todo: todo
    in_progress: in-progress
    rework: rework
    merging: merging
  active_states:
    - Todo
    - Design Review
    - In Progress
    - Rework
    - Merging
    - Blocked
  terminal_states:
    - Done
    - Closed
polling:
  interval_ms: 30000
workspace:
  root: D:/fqpack/runtime/symphony-service/workspaces
hooks:
  after_create: |
    git clone --depth 1 D:/fqpack/freshquant-2026.2.23 .
agent:
  max_concurrent_agents: 2
  max_concurrent_agents_by_state:
    todo: 1
    in_progress: 2
    rework: 1
    merging: 1
  max_turns: 60
codex:
  command: powershell -ExecutionPolicy Bypass -File D:/fqpack/runtime/symphony-service/scripts/run_freshquant_codex_session.ps1
  thread_sandbox: danger-full-access
  turn_sandbox_policy:
    type: dangerFullAccess
server:
  port: 40123
---

You are working in FreshQuant's GitHub-first Symphony workflow.

Core governance rules:

- GitHub Issue is the formal task entry.
- GitHub Draft PR is the only Design Review surface.
- Design Review is the only human approval gate.
- `docs/current/**` is the only formal documentation set.
- If current system facts change, update `docs/current/**` in the same PR.
- Code changes must redeploy affected modules before Done.
- Done means: merge + ci + docs sync + deploy + health check + cleanup.
- Cleanup deletes only task-level temporary resources, never shared runtime resources.

State contract:

- Todo: prepare context, decide whether Design Review is required, and only enter implementation when allowed
- Design Review: create or update the Draft PR Design Review Packet and wait for approval
- In Progress: implement, test, and sync `docs/current/**`
- Rework: fix review, CI, deploy, or cleanup failures
- Merging: merge, deploy, run health checks, and complete cleanup
