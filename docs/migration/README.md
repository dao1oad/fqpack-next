# 迁移进度与变更记录

本目录用于**文件化**记录从 `D:\fqpack\freshquant` → `D:\fqpack\freshquant-2026.2.23` 的迁移进度。

## 使用规则（强制）

1) 任何新增模块/破坏性变更：先写 RFC（见 `docs/rfcs/0000-template.md`），评审通过后再编码。
2) 每个迁移单元必须在 `progress.md` 登记，并关联一个 RFC。
3) 破坏性变更落地时，必须在 `breaking-changes.md` 追加记录，并引用对应 RFC。

## 文件说明

- `progress.md`：迁移进度总表（以 RFC 为单位）
- `breaking-changes.md`：破坏性变更清单（面向迁移与回滚）
