# FreshQuant In Progress Prompt

You are in the In Progress or Rework phase.

Required behavior:

- Default to subagent-driven-development.
- Use test-driven-development for each implementation task.
- Record RED -> GREEN evidence for every task.
- Keep work on the issue branch and Draft PR.
- Run verification before asking to merge.
- Before moving to Merging, post a structured PR completion comment to Linear with solved problems, chosen solution, reasons, changed files, verification results, lessons learned, and PR link.

Hard rules:

- Do not skip TDD.
- Do not go to Merging without RED and GREEN evidence.
- Do not go to Merging without the PR completion comment in Linear.
- Do not modify secrets.
- Do not auto-execute deployment in this phase; deployment belongs only to Merging.
- Do not auto-execute shutdown, database destructive operations, or high-risk live trading actions.

Required evidence:

- failing test
- RED command/result
- minimal implementation
- GREEN command/result
- regression verification
