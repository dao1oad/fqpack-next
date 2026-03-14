# FreshQuant Intake Prompt

You are in the compatibility `Todo` phase. Formal governance no longer uses `Todo`; treat this prompt as issue intake and route the task immediately.

Required behavior:

- Verify that the GitHub Issue body is sufficient as the execution contract.
- If the execution contract is sufficient, move directly to `In Progress`.
- If the task cannot proceed because of a real external blocker, move it to `Blocked`.
- Update or create only current-state documentation inputs; do not create RFC, progress, or breaking-changes files.

Hard rules:

- Do not reintroduce `Design Review` or any human approval gate.
- Do not leave a task in `Todo` after one pass.
- Do not treat comments as merge or approval truth.
- If you move a task to `Blocked`, you must record the blocker, clear condition, evidence, and target recovery state in GitHub.

Exit condition:

- Move to `In Progress` once the issue body clearly covers background, goal, scope, non-goals, acceptance criteria, and deployment impact.
- Move to `Blocked` only when a real external blocker prevents entering `In Progress`.
