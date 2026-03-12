---
tracker:
  kind: github
  repo: dao1oad/fqpack-next
  auth_token: $GITHUB_TOKEN
  managed_label: symphony
  review_required_label: design-review
  blocked_label: blocked
  rework_label: rework
  active_states:
    - queued
    - design_review
    - in_progress
    - rework
    - deploying
  terminal_states:
    - done
    - closed
polling:
  interval_ms: 30000
workspace:
  root: D:/fqpack/runtime/symphony-service/workspaces
hooks:
  after_create: |
    git clone --depth 1 ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git .
agent:
  max_concurrent_agents: 2
  max_concurrent_agents_by_state:
    queued: 1
    in_progress: 2
    rework: 1
    deploying: 1
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

- queued: prepare context and decide whether Design Review is required
- design_review: create or update the Draft PR Design Review Packet and wait for approval
- in_progress: implement, test, and sync `docs/current/**`
- rework: fix review, CI, deploy, or cleanup failures
- deploying: merge, deploy, run health checks, and complete cleanup
