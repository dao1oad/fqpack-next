# FreshQuant Todo Prompt

You are in the `Todo` phase. `Design Review` review-surface bootstrap is handled by the orchestrator, not by this Codex turn.

Required behavior:

- If `FQ_MEMORY_CONTEXT_PATH` is set and the file exists, read the memory context pack first before generic repository discovery.
- Treat memory context as derived input only; it does not replace GitHub, `docs/current/**`, or deploy/health truth.
- Decide whether the task needs Design Review.
- If Design Review is required, finish the risk judgment and make sure the issue body is ready to serve as the Design Review Packet source for the orchestrator-owned Draft PR bootstrap.
- If Design Review is not required, finish research and hand off cleanly to implementation.
- Update or create only current-state documentation inputs; do not create RFC, progress, or breaking-changes files.

Hard rules:

- Do not write production code before Design Review is approved when the task is high risk.
- Do not open multiple review packets for the same task.
- Do not publish fragmented decision questions.
- Do not treat free-form comments as approval truth; only `APPROVED` or PR review `Approve` counts.
- If you move a task to `Blocked`, you must record the blocker, clear condition, evidence, and target recovery state in GitHub.
- Once Design Review is approved, later CI/conflict/deploy/cleanup work must not ask for new human approval again; use `Rework` or `Merging` by default, and use `Blocked` only when a new real external blocker appears and the blocker record is complete.

Exit condition:

- For high-risk tasks: hand off with a complete Design Review Packet in the issue body, then let the orchestrator move the task into `Design Review` / Draft PR bootstrap and wait for `APPROVED`.
- For low-risk tasks: move to `In Progress` once the implementation scope and docs targets are clear.
