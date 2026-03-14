# Workflow Rules

- GitHub Issue, Draft PR, merged PR, and deploy results remain the only formal truth surfaces.
- `Design Review` is the only human approval gate for high-risk work.
- `Global Stewardship` owns deploy, health check, runtime ops check, cleanup, and follow-up creation.
- Memory context is a bootstrap aid. It must not override GitHub state, `docs/current/**`, or real deploy evidence.
