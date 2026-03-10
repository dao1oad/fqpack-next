# FreshQuant In Progress Prompt

You are in the In Progress or Rework phase.

Required behavior:

- Default to subagent-driven-development.
- Use test-driven-development for each implementation task.
- Record RED -> GREEN evidence for every task.
- Keep work on the issue branch and Draft PR.
- Run verification before asking to merge.

Hard rules:

- Do not skip TDD.
- Do not go to Merging without RED and GREEN evidence.
- Do not modify secrets.
- Do not auto-execute deployment, shutdown, database destructive operations, or high-risk live trading actions.

Required evidence:

- failing test
- RED command/result
- minimal implementation
- GREEN command/result
- regression verification
