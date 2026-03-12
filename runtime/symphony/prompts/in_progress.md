# FreshQuant In Progress Prompt

You are in the in_progress or rework phase.

Required behavior:

- Default to subagent-driven-development.
- Use test-driven-development for each behavior change.
- Record RED -> GREEN evidence for each implemented task.
- Keep work on the issue branch and Draft PR.
- Sync `docs/current/**` whenever current system facts change.
- Run verification before asking to merge.

Hard rules:

- Do not skip TDD for code changes.
- Do not modify secrets.
- Do not auto-execute deployment in this phase; deployment belongs only to `deploying`.
- Do not run destructive database or high-risk live trading actions.
- Do not leave `docs/current/**` stale when interfaces, config, runtime, or behavior changed.

Required evidence:

- failing test
- RED command/result
- minimal implementation
- GREEN command/result
- regression verification
- docs update path(s), if applicable
