---
name: rfc-0004-powershell-utf8-display
description: 为 Windows PowerShell 5.1 增加 UTF-8 中文显示辅助脚本与使用说明，避免 `cat/type` 查看项目文档时乱码。
---

# RFC 0004: Windows PowerShell UTF-8 中文显示（`cat/type` 不乱码）

- **状态**：Done
- **负责人**：TBD
- **评审人**：TBD
- **创建日期**：2026-03-05
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

项目文档与大量 agent 工作流默认使用中文，但 Windows PowerShell 5.1 在默认编码下查看 UTF-8 Markdown 文件时，容易出现 `cat/type` 中文乱码，直接影响：

- AI 助手读取项目文档
- 开发者在终端中审阅 RFC、迁移记录和运行说明
- 文档优先工作流的可执行性

该问题不属于业务功能迁移，但属于当前仓库在 Windows 宿主机上的基础开发体验问题。

## 2. 目标（Goals）

- 为 Windows PowerShell 5.1 提供一个可重复执行的 UTF-8 会话初始化脚本。
- 让开发者和 AI 助手在终端中直接查看 `docs/`、`README.md`、`AGENTS.md` 等 UTF-8 文档时不乱码。
- 在核心入口文档中明确提示使用方式，降低踩坑成本。

## 3. 非目标（Non-Goals）

- 不改造 PowerShell 7 或其他终端的默认编码策略。
- 不修改业务代码、配置语义或部署方式。
- 不处理第三方程序自身的编码问题。

## 4. 范围（Scope）

**In Scope**

- 新增 `script/pwsh_utf8.ps1`
- 在 `README.md` 与 agent 入口文档中补充使用提示
- 让当前 PowerShell 会话按 UTF-8 读取文本文件

**Out of Scope**

- 修改系统级区域设置
- 修改 Windows Terminal / Console Host 全局配置
- 变更非 UTF-8 文件本身的编码

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- 提供最小、可直接 dot-source 的脚本入口
- 仅作用于当前 PowerShell 会话

**不负责（Must Not）**

- 不保证所有外部命令都按 UTF-8 输出
- 不依赖管理员权限或系统级永久改动

**依赖（Depends On）**

- Windows PowerShell 5.1

**禁止依赖（Must Not Depend On）**

- 新增 Python / Node / 第三方编码转换工具

## 6. 对外接口（Public API）

本 RFC 的接口是一个开发体验脚本：

- 命令：`. .\script\pwsh_utf8.ps1`
- 效果：当前 PowerShell 会话切换到适合 UTF-8 文档阅读的编码设置

## 7. 数据与配置（Data / Config）

- 无新增 Mongo / Redis / 文件存储 schema
- 无新增业务配置项

## 8. 破坏性变更（Breaking Changes）

无。该 RFC 仅改善开发体验。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

无旧仓业务能力迁移，属于目标仓内开发体验修复。

## 10. 测试与验收（Acceptance Criteria）

- [x] 运行 `. .\script\pwsh_utf8.ps1` 后，`cat/type` 查看 UTF-8 中文文档不乱码
- [x] `README.md` 和 `docs/agent/index.md` 明确提示该脚本的用途
- [x] 不引入新的业务依赖或部署步骤

## 11. 风险与回滚（Risks / Rollback）

- 风险点：仅对当前会话生效，用户可能忘记执行
- 缓解：在入口文档中重复提示
- 回滚：删除 `script/pwsh_utf8.ps1` 与对应文档提示即可

## 12. 里程碑与拆分（Milestones）

- M1：新增 UTF-8 会话脚本
- M2：更新 README 与 agent 文档提示
- M3：作为 `progress.md` 中 `0004` 收口
