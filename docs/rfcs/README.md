# RFC 目录（需求 + 边界）

本目录用于承载“先定需求边界、后编码”的评审入口。

## 规则（强制）

- 任何新增模块/新增入口/破坏性变更/跨目录重构：必须先写 RFC，并在通过评审（Approved）后才能编码。
- 每个 RFC 必须登记到 `docs/migration/progress.md`，并在落地破坏性变更时同步更新 `docs/migration/breaking-changes.md`。

## 模板

- `docs/rfcs/0000-template.md`
