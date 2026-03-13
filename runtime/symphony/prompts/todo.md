# FreshQuant Todo / Design Review Prompt

You are in the `Todo` or `Design Review` phase.

Required behavior:

- Decide whether the task needs Design Review.
- If Design Review is required, ensure the GitHub Draft PR exists and publish a complete Design Review Packet.
- If Design Review is not required, finish research and hand off cleanly to implementation.
- Update or create only current-state documentation inputs; do not create RFC, progress, or breaking-changes files.

Hard rules:

- Do not write production code before Design Review is approved when the task is high risk.
- Do not open multiple review packets for the same task.
- Do not publish fragmented decision questions.
- Do not treat free-form comments as approval truth; only `APPROVED` or PR review `Approve` counts.
- If you move a task to `Blocked`, you must record the blocker, clear condition, evidence, and target recovery state in GitHub.
- Once Design Review is approved, later CI/conflict/deploy/cleanup work must not ask for new human approval again; use `Rework` or `Merging` instead of `Blocked`.

Exit condition:

- For high-risk tasks: stay in `Design Review` until the Draft PR contains a complete Design Review Packet and the reviewer has replied `APPROVED`.
- For low-risk tasks: move to `In Progress` once the implementation scope and docs targets are clear.
