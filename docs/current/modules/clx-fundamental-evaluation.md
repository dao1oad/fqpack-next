# CLX 基本面评价（fundamental-driven）

## 职责

`freshquant/clx_daily_selection/fundamental/` 是 CLX 日线选股的基本面驱动评价链：

- 以 CLX 正式批次（`content_hash` 锁定）为唯一输入，提取全部 Stock pure-buy；
- 全量确定性快排（规则化六维财务等级，行业内分位）；
- 快排前 100 只进入标准单股深析（`a-share-fundamental-analysis`，不简化），
  其余输出本期初评快照；
- 确定性排序（排序键脚本计算）、统计聚合与批次质量门；
- 发布静态产物到 `/data/clx-evaluator/runs/<date>/<run>/`，并扩展
  `latest.json / index.json`。

分析引擎只有一个：`a-share-fundamental-analysis`。`a-share-market-replay`
市场复盘已从主链移除；`market-state.v1.json / market-state.lock.json`、
`market_lane / market_theme_id / market_fit_grade` 等市场字段不再生成，
也不进入 UI。业务 `primary_group`（规则化行业分组）保留为统计的行业维度。

## 代码入口

- 管线编排：`freshquant/clx_daily_selection/fundamental/runner.py`
  （bootstrap / prepare / rank / deep-run / stats / consistency / validate / publish）
- 深析执行器：`freshquant/clx_daily_selection/fundamental/deep_executor.py`
  （有限并发、逐标的失败记录/重试、schema 校验、幂等跳过）
- 深析 agent 适配器：`freshquant/clx_daily_selection/fundamental/agent_run.py`
  （只读引用 a-share-fundamental-analysis 技能说明；提示词显式禁止
  a-share-market-replay，本链路只保留基本面分析引擎）
- 数据合同：`freshquant/clx_daily_selection/fundamental/contracts.py`
- 证据包与缓存：`freshquant/clx_daily_selection/fundamental/evidence.py`
  （静态财务按 (symbol, 报告期) 缓存复用，行情按交易日刷新）
- 确定性快排：`freshquant/clx_daily_selection/fundamental/quick_rank.py`
- 深析/快照合同与合并：`freshquant/clx_daily_selection/fundamental/deep_analysis.py`
- 统计与质量门：`freshquant/clx_daily_selection/fundamental/stats.py`
- 跨日连续入选：`freshquant/clx_daily_selection/fundamental/history.py`
- 产物校验：`freshquant/clx_daily_selection/fundamental/validate.py`
- JSON Schema：`freshquant/clx_daily_selection/fundamental/schemas/*.schema.json`
- 每日跑批入口：`script/clx_eval_daily.ps1`
- 前端工作台：`morningglory/fqwebui/src/views/DailyScreening.vue` +
  `morningglory/fqwebui/src/components/clx-workbench/`

## 每日跑批

`pwsh script/clx_eval_daily.ps1 -TradeDate <YYYY-MM-DD>` 依次执行：

1. bootstrap：按 official ready 契约拉取 CLX 正式批次（仓库内 runner
   `bootstrap` 子命令，content_hash 锁定，记录 batch_id / trade_date /
   content_hash / generation_id / publication_id / counts）；

> 2026-08-11 起 bootstrap 改为仓库内自包含：调用
> `/api/clx-daily-selection/official?trade_date=...&direction_mode=all`（official
> ready generation，ready marker 为唯一锚点），校验 status=trade_date/batch_id/
> content_hash/is_final 后保存 `clx-official-raw.json` +
> `clx-batch-identity.json`；不通过 list_batches 猜测“最近 final 批次”，不依赖
> 任何全局 skill 路径。
2. prepare：按 `classify_direction_mode(directions)==pure_buy` 且
   `asset_type=stock` 提取全量标的（与
   `/api/clx-daily-selection/official?direction_mode=pure_buy` 同口径），
   装配证据包（CNINFO 行业、THS 业务、THS 财务 as-of 安全、行情）；
3. rank：全量确定性快排（六维等级 + 综合等级 + 稳定排序键），前 100 只
   `tier=deep`，其余 `tier=snapshot`；生成
   `fundamental-analysis-spec/<symbol>.md` 深析规格；若
   `fundamental-analysis/` 已有深析文档则合并（`grade_source=deep`，分区与
   排序键不变）；
4. deep-run（agent，前 100 只，自动主链闭环）：`runner.py deep-run` 按规格
   逐只执行 `a-share-fundamental-analysis` 标准单股分析（不简化），输出
   `fundamental-analysis/<symbol>.json`；有限并发（`--workers`，默认 2）、
   逐标的失败记录/重试（`--max-attempts`，默认 2，状态写入
   `fundamental-deep-run.json`）、输出 schema 校验；已存在且合格的 JSON
   幂等跳过；完成后重新 `rank` 合并深析等级；
5. stats：统计聚合 + 批次质量门；
6. validate：四个产物的 JSON Schema + 结构校验；
7. publish：写入 `D:/fqpack/runtime/artifacts/clx-evaluator/runs/<date>/<run>/`
   （webui bind mount 提供 `/data/clx-evaluator/**`），更新 `latest.json`
   与 `index.json`；跨日连续入选按已发布历史 runs 计算。

深析未齐时 publish 默认失败（fail-closed）；显式 `-AllowIncompleteDeep` 可发布
amber 批次（页面顶部琥珀提示）。

深析 agent 会话通过仓库内适配器 `agent_run.py` 启动（默认生产协议）：

```text
agent_run.py --symbol <s> --spec <spec.md> --output <symbol.json>
             [--skill-root <a-share-fundamental-analysis 技能目录>]
             [--codex-bin codex]
```

适配器只读取技能说明并构造隔离会话提示词；提示词硬性约束禁止调用/读取
`a-share-market-replay` 或任何市场复盘/主题匹配工具，本链路只保留基本面分析。
技能目录可用 `FQ_FUNDAMENTAL_SKILL_ROOT` 环境变量覆盖。

## 产物合同

发布目录 `runs/<date>/<run-id>/`：

| 产物 | 内容 |
|---|---|
| `clx-fundamental-ranking.csv/.json` | 全量行：rank / quick_rank / symbol / name / tier（deep\|snapshot）/ grade_source（quick\|deep）/ primary_group / composite_grade / 六维等级 / quick_sort_key / original_clx_rank / 关键指标 / evidence_grade / evidence_ids / risk_flags / consecutive_selection_days / analysis_href / snapshot_href / as_of / financial_report_date |
| `fundamental-analysis/<symbol>.json` | 前 100 深析完整报告（schema `fundamental-analysis.v1`） |
| `fundamental-snapshot/<symbol>.json` | 其余本期初评快照（schema `fundamental-snapshot.v1`，规则生成） |
| `fundamental-stats.json` | 统计聚合 + 质量门（schema `fundamental-stats.v1`） |

`latest.json`（schema `clx-eval-latest.v2`）扩展：

```json
{
  "schemaVersion": "clx-eval-latest.v2",
  "tradeDate": "…",
  "runId": "…",
  "fundamentalRankingHref": "/data/clx-evaluator/runs/<date>/<run>/clx-fundamental-ranking.json",
  "fundamentalRankingCsvHref": "…/clx-fundamental-ranking.csv",
  "statsHref": "…/fundamental-stats.json",
  "promotedAt": "…"
}
```

历史 runs（含旧 `clx-eval.v1.json`）保留在数据目录，前端通过 `latest.json`
字段切换，新旧产物并存可回滚。

## 排序确定性

- 排序键 = 快排综合等级 → 六维等级（字典序）→ 原 CLX 序 → 代码，脚本计算；
- LLM 只输出六维离散等级与依据，不参与排序键；
- 深析/初评分区边界固定（前 100 恒为深析）；前端切换排序维度只改行序；
- 同输入重跑产出字节级一致的 CSV（固定精度与列序）；
- 2026-08-10 真实批次（159 只）重跑验证 CSV SHA-256 字节级一致。

## 批次质量门

`fundamental-stats.json` 内置质量门，任一不通过时 `qualityGateStatus=amber`，
页面顶部琥珀提示：

- deepCompletionRate = 1.0（前 100 全部有深析，默认 fail-closed）；
- evidenceABShare >= 0.8；evidenceDCount <= 10；
- collectionCompleteness >= 0.95；
- rerunConsistency >= 0.95（研发期验收项；`runner.py consistency` 与上一运行
  同 symbol 同报告期深析对比，无上一运行可跳过，不判失败）。

## 前端工作台

`/daily-screening` 重构为三区：

- ① CLX 基本面排序（40%）：虚拟滚动列表、两级密度（紧凑/舒适）、筛选
  （行业/证据等级/风险/分区/单维等级下限/搜索/星标）、排序切换（分区固定）、
  URL 状态持久化、跨日连续入选 ×N 徽章、星标收藏（localStorage）；
- ② 标的基本面详情（38%）：首屏决策卡（快照条/一句话定位/六维评分卡/关键
  指标/风险清单/三项优势/三项问题）+ 手风琴分节（业务结构、财务趋势、成长
  质量、资产负债、行业能力、估值情景、验证节点、证据溯源）；↑↓ 键盘切换
  保持手风琴展开态；证据 D 级置灰并提示“仅初步观察，估值暂停”；初评标的
  统一标注“本期初评”；
- ③ 池子统计分析（22%）：KPI 卡、质量×估值散点、行业分布、六维等级分布
  （默认 4 图）+ 成长×盈利四象限、风险热力、证据覆盖、估值分位直方图
  （折叠 4 图）+ 全屏模式；点击行业条/散点只写入列表筛选（单向下钻，不
  覆盖已选中标的）；`fundamental-stats.json` 缺失时统计区显示不可用原因，
  列表与详情降级可用。

断点降级：<1280px 统计区移至底部；<960px 仅列表 + 详情抽屉。

三池工作区（`PoolWorkspacePanel`）已下线；其通达信同步功能审计后未发现其他
页面依赖（`/daily-screening?tab=clx` 的 CLX 18 导入路径由
`ClxSelectionPanel` 独立承载，不受影响）。

## 部署

- `freshquant/clx_daily_selection/fundamental/**` 或
  `script/clx_eval_daily.ps1` 变更：自动任务产物与管线（每日跑批脚本）；
- `morningglory/fqwebui/**` 变更：重新构建并部署 Web UI；
- 静态产物目录 `/data/clx-evaluator/runs/<date>/<run>/` 由宿主外部目录
  `D:/fqpack/runtime/artifacts/clx-evaluator/` bind mount 提供，每日 publish
  直接写入，无需 rebuild 镜像/commit。

正式部署后检查：

```powershell
pwsh script/clx_eval_daily.ps1 -TradeDate <T> -SkipBootstrap -SkipPublish
Invoke-RestMethod http://127.0.0.1:15000/api/clx-daily-selection/health
Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:18080/daily-screening'
```

## 排障

### publish 报 “deep analysis incomplete”

- 快排前 100 只深析未齐（`fundamental-analysis/` 少于 100 份或 schema 校验
  失败）；按 `fundamental-analysis-spec/<symbol>.md` 补齐后重跑
  `script/clx_eval_daily.ps1`（bootstrap 幂等跳过）；
- 确需先发布时显式 `-AllowIncompleteDeep`（页面琥珀提示，质量门未通过）。

### 排序 CSV 与上一运行不一致

- 同输入、同版本脚本重跑必须字节级一致；先核对
  `clx-fundamental-input.json` 是否变化（证据包/财务报告期）；
- 检查 `financial-cutoff` 与证据缓存：静态财务按 (symbol, 报告期) 复用，
  报告期切换会改变指标与分位，属于预期变化。

### 页面无排序数据

- 看 `latest.json` 是否含 `fundamentalRankingHref`；数据目录是否已 publish；
- 看 `runs/<date>/<run>/clx-fundamental-ranking.json` 是否存在且 schema
  版本为 `clx-fundamental-ranking.v1`。
