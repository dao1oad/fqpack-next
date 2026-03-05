# Codex 全局指令（AGENTS.md）

## 0. 项目目标（迁移与重构）

本仓库（`D:\fqpack\freshquant-2026.2.23` / GitHub: `dao1oad/fqpack-next`）是 **目标架构**。
需要在“重构与去冗余”的前提下，逐步迁移并整合旧分支仓库 `D:\fqpack\freshquant` 的功能。

迁移过程中 **允许破坏性变更（Breaking Changes）**，但必须先写清需求与边界，经评审后才能编码。

## 1. 语言与风格

- 默认使用简体中文回复（除非用户明确要求英文）。
- 代码、命令、文件路径、标识符保持原样（通常为英文）。
- 表达直接、简洁、可执行；避免空话。

## 2. 文档优先级

- “需求/边界/RFC” > “实现细节”。
- 所有新增模块/子系统：先写 RFC（需求+边界），评审通过后再写代码。
- 项目文档优先中文；需要时在括号中保留关键英文术语。

## 3. 强制流程（先定需求边界，再编码）

以下任一情况 **必须** 先写 RFC 并通过评审：
- 新增顶级模块（例如新增 `freshquant/<module>/` 目录，或新增稳定公共 API 面）。
- 新增对外入口（CLI/API/worker/service/scheduler）。
- 需要跨多个目录的大重构/重命名/拆分合并。
- 引入新的外部依赖（服务、存储、消息系统、第三方 API）。
- 任何破坏性变更（接口、配置、数据结构、行为语义）。

评审通过的最低标准：
- 目标/非目标明确（不做什么要写清楚）。
- 范围与边界明确（职责/不负责什么/依赖什么/禁止依赖什么）。
- 对外接口与数据/配置明确（输入输出、错误语义、兼容/迁移策略）。
- 验收标准明确（如何验证“做对了”）。

落地顺序（严格执行）：
1) 写 RFC（`docs/rfcs/`，按模板）
2) 评审/修订 → 通过（Approved）
3) 编码与测试
4) 更新进度与破坏性变更记录（`docs/migration/`）

## 4. RFC（需求/边界）规范

- 目录：`docs/rfcs/`
- 模板：`docs/rfcs/0000-template.md`
- 命名：`docs/rfcs/NNNN-<topic>.md`（NNNN 为 4 位递增编号；topic 用短横线）
- 状态：Draft / Review / Approved / Rejected / Superseded

RFC 必含内容（至少）：
- 背景与问题
- 目标 / 非目标
- 范围（In/Out）
- 模块边界（负责/不负责）
- 依赖与集成点（Dependencies）
- Public API（对外接口、错误语义）
- 数据与配置（Data/Config）
- 破坏性变更（影响面、迁移步骤、回滚）
- 测试与验收（Acceptance Criteria）
- 迁移映射（从 `D:\fqpack\freshquant` 的哪些路径/能力迁到哪里）

## 5. 迁移进度记录（文件化，不依赖插件）

本仓库以文件方式记录迁移进度（等价于 “planning-with-files” 的效果）：
- 进度总表：`docs/migration/progress.md`
- 破坏性变更清单：`docs/migration/breaking-changes.md`

规则：
- 每个迁移单元必须关联一个 RFC（在进度表里写 RFC 编号/链接）。
- 任何破坏性变更落地时，必须在 `breaking-changes.md` 追加记录，并引用对应 RFC。

强制更新频率（必须遵守）：
- **RFC 状态变更即更新**：RFC 从 Draft/Review/Approved/Implementing/Done/Blocked 任意变更时，必须在**同一提交**更新 `docs/migration/progress.md`。
- **迁移代码合并即更新**：任何涉及迁移/重构/删改功能的合并到 `main`，必须在**同一提交**更新 `docs/migration/progress.md`（含“做了什么/下一步/风险”简述）。
- **Implementing 每日更新**：处于 Implementing 的 RFC，按 Asia/Shanghai 自然日 **每天至少更新一次**进度（哪怕只是“无进展 + 原因”）。
- **破坏性变更同提交登记**：任何破坏性变更（接口/配置/数据/行为语义）落地时，必须在**同一提交**更新 `docs/migration/breaking-changes.md` 并引用 RFC。
- **未更新视为未完成**：未按上述规则更新进度/变更记录的工作，视为未完成，不应合并。

## 6. Git/GitHub

- 默认使用 SSH 远端（本项目）：`ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git`
- 如必须走 HTTPS 且需要代理，可按命令级别注入（示例）：`git -c http.proxy=http://127.0.0.1:10809 -c https.proxy=http://127.0.0.1:10809 <cmd>`
- 不要提交密钥/Token；`.env` 等敏感文件保持在 `.gitignore` 中。

PR 合并策略（项目强制约束）：
- **禁止直推 `main`**：所有改动在 feature 分支完成后提交 PR。
- PR 必须满足：
  - CI 全绿（`CI / governance`、`CI / pre-commit`、`CI / pytest`）
  - reviewer Approve：GitHub 不允许 PR 作者自我 Approve；单账号仓库暂不强制（0），引入第二账号/团队后改回 ≥1
  - 解决所有 review discussion 后再合并

## 7. Skills（可选）

- 本环境支持在本机 Codex skills 目录下按需加载 `SKILL.md`，并遵循其中工作流。
- 若用户点名技能，或任务明显匹配技能描述，则优先使用该技能。
