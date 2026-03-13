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
    if git remote get-url github >/dev/null 2>&1; then
      git remote set-url github https://github.com/dao1oad/fqpack-next.git
    else
      git remote add github https://github.com/dao1oad/fqpack-next.git
    fi
    git config remote.pushDefault github
  before_run: |
    if git remote get-url github >/dev/null 2>&1; then
      git remote set-url github https://github.com/dao1oad/fqpack-next.git
    else
      git remote add github https://github.com/dao1oad/fqpack-next.git
    fi
    git config remote.pushDefault github
agent:
  max_concurrent_agents: 4
  max_concurrent_agents_by_state:
    todo: 2
    in_progress: 4
    rework: 2
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

You are working on FreshQuant GitHub issue `{{ issue.identifier }}`

{% if attempt %}
Continuation context:

- This is retry attempt #{{ attempt }} because the issue is still active in the tracker.
- Resume from the current workspace state instead of restarting from scratch.
- Do not repeat already-completed investigation or validation unless new evidence requires it.
- Continue the same task without asking for new human confirmation unless a real blocker appears.
{% endif %}

Issue context:
Identifier: {{ issue.identifier }}
Title: {{ issue.title }}
Current state: {{ issue.state }}
Labels: {{ issue.labels }}
URL: {{ issue.url }}

Description:
{% if issue.description %}
{{ issue.description }}
{% else %}
No description provided.
{% endif %}

Core governance rules:

- GitHub Issue is the formal task entry.
- GitHub Draft PR is the only Design Review surface.
- Design Review is the only human approval gate.
- `docs/current/**` is the only formal documentation set.
- If current system facts change, update `docs/current/**` in the same PR.
- Code changes must redeploy affected modules before Done.
- Done means: merge + ci + docs sync + deploy + health check + cleanup.
- Cleanup deletes only task-level temporary resources, never shared runtime resources.
- Never do task work on local `main`; use the issue branch and its Draft PR.

State contract:

- `Todo`: prepare context, decide whether Design Review is required, and only enter implementation when allowed.
- `Design Review`: create or update the Draft PR Design Review Packet and wait for approval.
- `In Progress`: implement, test, and sync `docs/current/**`.
- `Rework`: fix review, CI, deploy, or cleanup failures.
- `Merging`: merge, deploy, run health checks, and complete cleanup.
- `Blocked`: stop active work and record the external blocker clearly.

Required behavior:

1. Start from the issue's current tracker state and follow the matching path.
2. Do not write production code while the issue is in `Todo`, `Design Review`, or `Blocked`.
3. If a task is low risk and does not require Design Review, do not invoke `brainstorming` and do not ask for human approval.
4. Low-risk `Todo` work should finish one solid research turn, then let the orchestrator move the issue to `In Progress` automatically.
5. When the issue is already in `Design Review`, treat the issue body as the current design context and the source material for the Draft PR packet.
6. In `Design Review`, do not invoke `brainstorming` and do not ask for new human clarification inside the Codex session. This phase is operational: create or refresh the Draft PR review surface from the issue body and then wait for approval on GitHub.
7. If a task is high risk, the first priority is to make sure the GitHub review surface exists. If there is no linked Draft PR yet, first create or switch to the issue branch, create the Draft PR, and publish the complete Design Review Packet in the PR body before more repo exploration.
8. Once the Draft PR exists for a high-risk task, keep the issue in `Design Review` and wait for explicit approval. Only `APPROVED` or PR review `Approve` counts.
9. Do not keep looping on generic repository discovery once the issue context and review surface are already known.
10. If the task is blocked by missing access, missing tooling, or another real external dependency, move it to `Blocked` instead of leaving it in `Todo`.
11. Treat newly created GitHub issues as `symphony` + `todo` by default. Do not pre-apply `design-review` at issue creation time; add it only after the task is confirmed to be high risk.
12. All GitHub-facing text that you write must use Simplified Chinese by default, including Draft PR titles, PR bodies, issue comments, PR comments, deployment notes, and done summaries. Preserve the control tokens `APPROVED`, `REVISE:`, and `REJECTED:` exactly when they are required.
