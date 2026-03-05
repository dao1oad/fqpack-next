# RFC 0000: <标题>

- **状态**：Draft | Review | Approved | Rejected | Superseded
- **负责人**：<Owner>
- **评审人**：<Reviewers>
- **创建日期**：2026-03-05
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

说明为什么要做、当前痛点是什么、来自旧分支 `D:\fqpack\freshquant` 的哪些能力/问题。

## 2. 目标（Goals）

- ...

## 3. 非目标（Non-Goals）

- ...

## 4. 范围（Scope）

**In Scope**
- ...

**Out of Scope**
- ...

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**
- ...

**不负责（Must Not）**
- ...

**依赖（Depends On）**
- ...

**禁止依赖（Must Not Depend On）**
- ...

## 6. 对外接口（Public API）

> 这里的“接口”包括 CLI 命令、HTTP API、内部稳定 Python API、消息/事件协议等。

- 输入/输出
- 错误语义（异常、返回码、错误码）
- 兼容性策略（如适用）

## 7. 数据与配置（Data / Config）

- 配置来源与命名约定（示例：dynaconf / 环境变量）
- 数据存储（Mongo/Redis/文件等）
- schema/字段（如涉及）

## 8. 破坏性变更（Breaking Changes）

> 本项目允许破坏性变更，但必须写清楚影响与迁移步骤，并在落地时同步更新 `docs/migration/breaking-changes.md`。

- 影响面（谁会被影响：模块、脚本、服务、用户）
- 迁移步骤（怎么升级）
- 回滚方案（怎么撤回）

## 9. 迁移映射（From `D:\fqpack\freshquant`）

列出旧分支中将被迁移/替代的路径、入口、关键类/函数，并映射到新模块的归属。

- 旧路径/能力 → 新模块/位置
- 删除/合并/替代说明

## 10. 测试与验收（Acceptance Criteria）

必须可执行、可验证：
- [ ] 单元测试：...
- [ ] 集成测试/脚本：...
- [ ] 手工验证步骤（如必须）：...

## 11. 风险与回滚（Risks / Rollback）

- 风险点：...
- 缓解：...
- 回滚：...

## 12. 里程碑与拆分（Milestones）

- M1：RFC 通过
- M2：最小可用实现（MVP）
- M3：迁移完成与清理冗余
