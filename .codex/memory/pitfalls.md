# Pitfalls

- Do not treat merge as `Done`; deploy, health check, and cleanup still gate completion.
- Do not let `Global Stewardship` create repair PRs; code defects become follow-up issues.
- Do not re-explore the whole repository after issue state, branch, and memory context are already known.
- If memory context conflicts with fresh GitHub or runtime evidence, trust the formal source and refresh memory again.
