---
tracker:
  kind: github
  repo: dao1oad/fqpack-next
  auth_token: $GITHUB_TOKEN
  managed_label: symphony
  blocked_label: blocked
  state_labels:
    in_progress: in-progress
    rework: rework
    merging: merging
    global_stewardship: global-stewardship
  active_states:
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

Memory context:

- If `FQ_MEMORY_CONTEXT_PATH` is set and the file exists, read the memory context pack first.
- The memory context pack is derived input for faster startup. It does not replace GitHub, `docs/current/**`, or deploy/health results.
- If memory context conflicts with formal truth, trust the formal source and refresh your understanding from there.

Core governance rules:

- GitHub Issue is the formal task entry and execution contract.
- GitHub PR + CI + merge gate is the code-delivery truth.
- `docs/current/**` is the only formal documentation set.
- If current system facts change, update `docs/current/**` in the same PR.
- Code changes must redeploy affected modules before Done.
- Done means: merge + ci + docs sync + deploy + health check + cleanup.
- Cleanup deletes only task-level temporary resources, never shared runtime resources.
- `Global Stewardship` is owned by the single global Codex automation, not the per-issue Symphony agent.
- Never do task work on local `main`; use the issue branch and its PR.

State contract:

- `In Progress`: implement, test, sync `docs/current/**`, and prepare the PR for merge.
- `Rework`: fix deterministic repository-side failures before merge.
- `Merging`: perform one-shot GitHub truth check, merge the PR, write the merge handoff comment, and move the issue to `Global Stewardship`.
- `Global Stewardship`: global Codex automation handles deploy, health check, runtime ops check, cleanup, and follow-up issue creation.
- `Blocked`: use only for a real external blocker.

Required behavior:

1. Start from the issue's current tracker state and follow the matching path.
2. The GitHub Issue body is the execution contract. Do not wait for a separate human approval step.
3. If `FQ_MEMORY_CONTEXT_PATH` is available, read the memory context pack first before generic repository discovery.
4. Treat newly created GitHub issues as `symphony` + `in-progress` by default.
5. Do not treat comment-based approval as a merge condition.
6. Before any non-`Blocked` implementation turn starts, switch the workspace to the deterministic issue branch instead of local `main`. Reuse the remote issue branch when it already exists.
7. Use GitHub PR truth as the only merge truth: required checks, unresolved review threads, mergeability, and ruleset policy.
8. Keep the issue in `Merging` while required checks are pending.
9. Move to `Rework` only when the failure is deterministic and repository-side, such as `checks_failed`, `review_threads_unresolved`, `merge_conflict`, `ruleset_policy_block`, or `docs_guard_failed`.
10. If the issue enters `Rework`, record `blocker_class`, `evidence`, `next_action`, and `exit_condition` in GitHub.
11. Do not retry merge when GitHub truth has not changed.
12. If the task is blocked by missing access, missing tooling, or another real external dependency, move it to `Blocked`.
13. If the issue enters `Blocked`, record the blocker, clear condition, evidence, and target recovery state in GitHub. Do not leave a blocked task without saying whether it should resume to `In Progress`, `Rework`, `Merging`, or `Global Stewardship`.
14. When GitHub truth proves a blocked task is misclassified, restore it automatically: merged PR, pending ops -> `Global Stewardship`; open PR with pending checks -> `Merging`; open PR with deterministic repository-side failure -> `Rework`; no open PR -> `In Progress`.
15. If `before_run` fails because the workspace is not a git repository, rebuild the workspace once and retry before surfacing the failure.
16. All GitHub-facing text that you write must use Simplified Chinese by default, including PR titles, PR bodies, issue comments, PR comments, deployment notes, and done summaries.
17. If code repair is needed after merge, only create a follow-up issue for the next Symphony round; do not create a repair PR directly from the global automation.
