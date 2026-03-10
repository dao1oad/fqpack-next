---
tracker:
  kind: linear
  api_key: $LINEAR_API_KEY
  project_slug: fce206e3a355
  active_states:
    - Todo
    - In Progress
    - Rework
    - Merging
workspace:
  root: D:/fqpack/runtime/symphony-service/workspaces
hooks:
  after_create: |
    git clone --depth 1 ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git .
agent:
  max_concurrent_agents: 1
  max_turns: 60
codex:
  command: codex --config shell_environment_policy.inherit=all app-server
  thread_sandbox: danger-full-access
  turn_sandbox_policy:
    type: dangerFullAccess
server:
  port: 40123
---

You are working in FreshQuant's formal Symphony workflow.

Core governance rules:

- Linear issue is the only task entry.
- One development requirement maps to one Linear issue.
- Human Review is the only human approval gate.
- Human Review -> In Progress is the only approval truth.
- Human Review is not an active dispatch state.
- Design phase does not open a PR.
- In Progress opens and updates a Draft PR on the issue branch.
- Default implementation mode is subagent-driven-development + TDD.
- Do not modify secrets or run high-risk deployment / trading operations automatically.

State contract:

- Todo: follow `runtime/symphony/prompts/todo.md`
- In Progress: follow `runtime/symphony/prompts/in_progress.md`
- Rework: follow `runtime/symphony/prompts/in_progress.md`
- Merging: finalize verification, CI, merge preparation, and completion bookkeeping
