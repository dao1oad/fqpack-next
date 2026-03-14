# Pitfalls

- Do not treat merge as `Done`; deploy, health check, and cleanup still gate completion.
- Do not let `Global Stewardship` create repair PRs; code defects become follow-up issues.
- Do not force every small change through the issue state machine; direct `feature branch -> PR` is allowed outside Symphony-managed work.
- Do not send post-merge deploy or runtime failures back to `Rework`; they belong to `Global Stewardship` follow-up handling.
- Do not treat pending GitHub checks as `Rework`; `Merging` waits for GitHub truth to change.
- Do not work directly on local `main`; use a feature branch and PR. If Symphony manages the task, use the deterministic issue branch.
- Do not re-explore the whole repository after issue state, branch, and memory context are already known.
- If memory context conflicts with fresh GitHub or runtime evidence, trust the formal source and refresh memory again.
