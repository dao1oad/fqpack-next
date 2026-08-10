# FreshQuant 记忆系统 v2 迁移方案（B 方案：新库并行 + 旧库冻结）

> 状态：已评审待实施（GitHub Issue 关联后作为实施依据）
> 日期：2026-08-10
> 类型：记忆层重构方案（非正式当前状态文档，仅作实施计划）

## 1. 背景与动机

### 1.1 现状审计（2026-08-10 机器事实）

当前记忆系统（`freshquant/runtime/memory/**` + MongoDB `fq_memory` + 磁盘 context-packs）自 2026-03 运行至今，经审计存在三类结构性问题：

| 问题 | 证据 |
|---|---|
| 读取端全量预载，无按需检索 | `compile_context_pack()` 把全部冷记忆全文 + 14 个模块清单拼进每个 pack；15 个 pack 重复嵌入 12KB+ 冷记忆全文；`docs/current/architecture.md` 声称 "bootstrap / archive / retrieval" 三层，代码中 archive/retrieval 模块不存在 |
| 写入端无界增长、无保留策略 | `task_events` 260 条全部为 `memory_refresh` 噪声；`LOCAL-freshquant-2026.2.23` 单标识符 166 条；无 TTL/归档；`git_status` 原样入库（ISSUE-494 单文档 140KB，其中 git_status 139,495 字符）；stale 条目残留（`clx-preholdout-handoff.md` 源文件已删） |
| 运行状态从未真正落库 | `deploy-runs` / `health-results` / `cleanup-results` / `cleanup-requests` 目录全部缺失，`deploy_runs` / `health_results` 集合 11+11 条全部为 `unavailable` 占位符 |

### 1.2 与 2026 年 Agent 记忆最佳实践的差距

调研结论（Anthropic 官方 context engineering、Claude Code 官方记忆、Codex 官方 AGENTS.md/记忆、Codex 社区 #323/#24717、SitePoint/Atlan 生产级记忆指南）：

- ✅ 已符合：AGENTS.md 为权威规则层；记忆仅作 recall 层、正式真值优先；冷记忆 git 版本化、从 origin/main 读取。
- ❌ 需重构：上下文是有限资源（context rot），应"索引前置 + 按需检索"而非全量预载；任务状态每次会话重写而非无限追加；需要过期/版本化/冲突解决与定期整合（Dreams 式合并/清理）；需要可观测性（记录注入/驱逐）。

## 2. 目标

1. 读取端：context pack 瘦身为"索引 + 快照"（≤25KB / 200 行），细节按需读取 `.codex/memory/*.md`，消除全文重复与单 pack 膨胀（ISSUE-494 166KB 同类问题不再可能发生）。
2. 写入端：`git_status` 摘要化（≤1KB）；`task_events` 有界（按 issue 保留最近 N 条）；新增保留/整合策略（旧 pack 90 天归档、删除源已不存在的 knowledge、标记过期）；新增注入可观测性。
3. 数据迁移：采用 **B 方案**——新库 `fq_memory_v2` 并行，旧库 `fq_memory` 冻结保留，验证通过后清理。
4. 修正文档-代码漂移：`docs/current/architecture.md` 对记忆层的描述与实际实现对齐。

## 3. 非目标

- 不重建交易/行情/订单/持仓等业务链路，不触碰 `freshquant` / `freshquant_order_management` / `freshquant_position_management` 等业务库。
- 不实现向量检索/知识图谱/embedding 类语义记忆（当前体量 <1MB，无需引入）。
- 不手工清理旧库内容（旧库整体冻结，新库从正式真值重新播种）。
- 不改变 AGENTS.md 的正式真值层级与 GitHub-first 工作流。
- 不迁移平台原生记忆（`~/.codex/memories`、Claude auto memory），仅收敛自建系统为治理状态机专用。

## 4. 方案设计（B 方案）

### 4.1 存储布局

- 新库：MongoDB `fq_memory_v2`（7 集合结构不变：`task_state` / `task_events` / `deploy_runs` / `health_results` / `knowledge_items` / `module_status` / `context_packs`）。
- 旧库：`fq_memory` 冻结（mongodump 归档 + 保留，不 drop）。
- 配置：`freshquant/bootstrap_config.py` 的 `memory.mongodb.db` 由 `fq_memory` 切换为 `fq_memory_v2`（环境变量 `FRESHQUANT_MEMORY__MONGODB__DB` 可覆盖，用于回滚）。

### 4.2 读取端重构（PR-A）

1. **pack 索引化**：`compile_context_pack()` 输出改为：
   - 冷记忆区：每个文件一行（标题 + 一句话摘要 + 相对路径），agent 按需读取全文；
   - 任务区：task snapshot（issue/branch/git_status 摘要/PR/cleanup）+ 最近事件指针；
   - 模块区：模块 ID + 路径清单。
2. **检索补齐**：`task_events` 支持按 issue/日期/事件类型过滤查询（新增只读查询入口），替换 pack 中硬编码"最近 5 条"。
3. **文档同步**：`docs/current/architecture.md` / `runtime.md` / `interfaces.md` / `troubleshooting.md` 中对记忆层的描述与实际实现一致（删除不存在的 archive/retrieval 表述，或按实现补正）。

### 4.3 写入端重构（PR-B）

1. **git_status 摘要化**：`refresh_memory()` 对 `git_status` 截断至 ~1KB 或仅存 M/D/A 计数摘要。
2. **task_events 有界**：同 issue 的 `memory_refresh` 事件改为 upsert 单条 latest（`event_id = {issue}:refresh:latest`），或按 issue 保留最近 N 条并清理更旧记录。
3. **保留/整合脚本**：新增 `runtime/memory/scripts/consolidate_freshquant_memory.py`：
   - 归档 90 天未更新的 context pack 目录；
   - 删除 source 已不存在的 knowledge_items（对比 origin/main 与本地冷记忆文件清单）；
   - 输出整合报告（删除/归档/保留计数）。
4. **可观测性**：每次 compile 记录注入内容清单（哪些记忆文件/事件进入 pack），写入 `context_packs` 或独立审计集合。

### 4.4 现有记忆内容处理（分类）

| 内容 | 现状 | 处理 |
|---|---|---|
| `.codex/memory/*.md`（8 文件） | git 版本化真值源 | 保留，新系统继续读取同一源 |
| `knowledge_items`（9 条） | 8 条来自 origin/main 可再生；1 条 stale | 不迁移，新库重新播种后自然仅剩有效条目 |
| `module_status`（14 条） | 从 `docs/current/modules` 生成 | 不迁移，bootstrap 时重新生成 |
| `task_state`（11 条） | 会话瞬时快照；ISSUE-494 含 140KB git_status | 不保留，新系统每会话重写 |
| `task_events`（260 条） | 全部为 memory_refresh 噪声 | 不迁移，新系统有界写入 |
| `deploy_runs` / `health_results`（各 11 条） | 全部为 unavailable 占位符 | 不迁移；新系统直接读取 artifacts 真实产物 |
| 磁盘 context-packs（15 目录） | 派生产物，含 166KB 污染文件 | 归档冻结，不删除 |
| Mongo `context_packs`（11 条） | 派生索引记录 | 归档冻结 |

## 5. 迁移步骤

```
Step 0  冻结旧写入：切换入口/配置指向 fq_memory_v2（或临时暂停自动 bootstrap）
Step 1  归档旧库：mongodump fq_memory + context-packs 目录改名冻结（可回滚）
Step 2  实施 PR-A（读取端）+ PR-B（写入端），合并 main
Step 3  从正式真值重新播种：跑一次新 bootstrap 生成干净基线（fq_memory_v2）
Step 4  验证（对照第 6 节验收标准）
Step 5  观察 1-2 周；验证通过后清理归档（删除旧库与旧 pack 目录）
```

### Step 1 具体操作（归档冻结）

```powershell
# 归档 MongoDB fq_memory（容器内 mongodump，已确认 100.13.0 可用）
docker exec fqnext_20260223-fq_mongodb-1 mongodump --db fq_memory --out /dump/fq_memory-20260810
docker cp fqnext_20260223-fq_mongodb-1:/dump/fq_memory-20260810 D:\fqpack\runtime\backups\

# 归档磁盘 context-packs（改名而非删除）
Rename-Item D:\fqpack\runtime\artifacts\memory\context-packs context-packs-legacy-20260810
```

## 6. 验收标准

新系统播种后的干净基线：

- `knowledge_items`：8 条，全部 `source_ref=origin/main`，无 stale。
- `module_status`：14 条，全部来自 `docs/current/modules`。
- `task_state`：1 条当前会话，`git_status` ≤ 1KB（摘要化后）。
- `task_events`：每会话 ≤ 5 条（有界）。
- context pack：≤ 25KB / 200 行（索引 + 快照，不再嵌入冷记忆全文）。
- `deploy_runs` / `health_results`：能反映 artifacts 真实产物（若存在）；缺失时明确 `unavailable` 而非静默。
- `docs/current/**` 记忆层描述与代码一致（无 archive/retrieval 虚指）。
- 回滚验证：环境变量 `FRESHQUANT_MEMORY__MONGODB__DB=fq_memory` 可切回旧库，旧 bootstrap 可用。

## 7. 部署影响

- 影响面：仅 agent 会话上下文层（`freshquant/runtime/memory/**`、`codex_run/**`、`freshquant/bootstrap_config.py` 中 memory 段、docs 记忆层段落）。
- 不涉及：交易/行情/订单/持仓/止盈止损等运行链路，无常驻服务重启需求。
- 配置变更：Mongo 新增 `fq_memory_v2` 库；`bootstrap_config.py` memory.mongodb.db 切换。
- 入口变更：`codex_run/start_freshquant_codex.ps1` 及 AGENTS.md 自举规则随 PR 同步。
- CI：新增/更新 `freshquant/tests/test_runtime_memory.py`、`test_runtime_memory_docs.py`、`test_codex_run_entrypoints.py` 覆盖。

## 8. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 新库播种失败 | 旧库冻结保留，环境变量一键切回 |
| pack 瘦身后 agent 上下文不足 | 索引含摘要与路径，按需读取补充；对比新旧 pack 质量后再切正式入口 |
| 保留/整合误删 | 整合脚本输出报告人工复核；删除前先移动至归档目录 |
| 文档-代码不一致残留 | `test_runtime_memory_docs.py` 契约测试强制对齐 |

## 9. 参考来源

- Anthropic: [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Claude Code: [How Claude remembers your project](https://code.claude.com/docs/en/claudemd)
- Codex: [AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md) / [Memory & Project Docs](https://mintlify.wiki/openai/codex/features/memory)
- Codex 社区: [Persistent Memory strategies #323](https://github.com/openai/codex/discussions/323) / [Outdated/incorrect memories #24717](https://github.com/openai/codex/discussions/24717)
- SitePoint: [The New Reality of Agent Memory (2026)](https://www.sitepoint.com/ai-agent-memory-guide/)
- Atlan: [Agent Memory Architectures: 5 Patterns](https://atlan.com/know/agent-memory-architectures/)

## 10. 关联

- 前置审计：本方案基于 2026-08-10 记忆系统审计（MongoDB `fq_memory` 集合规模、context-packs 目录、artifacts 缺失事实）。
- 任务入口：GitHub Issue（见关联 Issue，随实施 PR 落地本文件到 `docs/plans/`）。
