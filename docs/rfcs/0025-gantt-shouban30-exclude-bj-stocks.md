# RFC 0025: Gantt Shouban30 排除北交所标的

- **状态**：Approved
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-09
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

`/gantt/shouban30` 已经切换到盘后 Dagster 预计算快照语义。当前快照中仍会纳入北交所标的，导致两个问题：

1. 页面语义偏离预期。该页面面向 A 股首板热门标的筛选，不希望出现北交所标的。
2. 北交所 `920xxx` 标的在当前 K 线抓取链路下容易落成 `structure_unavailable`，污染候选总数、失败数与板块统计。

因此需要在盘后快照构建期就彻底排除北交所标的，而不是在前端或读接口层隐藏。

## 2. 目标（Goals）

- 在 `/gantt/shouban30` 的盘后快照构建期彻底排除北交所标的。
- 被排除后的板块计数、候选总数、失败总数都只基于剩余 A 股候选重新统计。
- 过滤后没有剩余候选股的板块，不进入 `shouban30_plates` 快照。

## 3. 非目标（Non-Goals）

- 不扩展到底层 `get_stock_data()` 的北交所 K 线支持。
- 不修改 `/gantt/shouban30` 前端页面结构。
- 不新增新的 API 路由、查询参数或页面开关。

## 4. 范围（Scope）

**In Scope**
- `freshquant/data/gantt_readmodel.py` 中 `shouban30` 盘后快照构建逻辑。
- `freshquant/tests/test_gantt_readmodel.py` 的读模型回归测试。
- 迁移进度与破坏性变更记录更新。

**Out of Scope**
- `freshquant/KlineDataTool.py`、`freshquant/data/stock.py` 的北交所 K 线能力补齐。
- 非 `shouban30` 页面或读模型。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**
- 在 `persist_shouban30_for_date()` 中剔除北交所标的。
- 基于剔除后的 stock rows 重新生成 plate rows。
- 对 `43**** / 83**** / 87**** / 92****` 代码段执行排除。

**不负责（Must Not）**
- 不为北交所标的提供兜底缠论计算。
- 不在前端页面或读路由层追加重复过滤。

**依赖（Depends On）**
- 现有 `gantt_stock_daily`、`shouban30_stocks`、`shouban30_plates` 盘后构建链路。
- 现有 Dagster `job_gantt_postclose` / `_build_shouban30_snapshots_for_date()`。

**禁止依赖（Must Not Depend On）**
- 不依赖前端二次过滤维持正确结果。
- 不依赖运行时人工清洗数据库。

## 6. 对外接口（Public API）

- 不新增新接口。
- `/api/gantt/shouban30/plates|stocks` 路径保持不变。
- 返回语义变化：
  - 北交所标的不再出现在 `stocks` 结果中。
  - 仅由北交所标的构成的板块不再出现在 `plates` 结果中。
  - `candidate_stocks_count / stocks_count / failed_stocks_count` 将同步下降。

## 7. 数据与配置（Data / Config）

- 不新增配置项。
- 不新增集合或字段。
- 仅调整 `shouban30_*` 快照的构建输入集合。

## 8. 破坏性变更（Breaking Changes）

- `/api/gantt/shouban30/*` 的候选集语义发生变化：北交所标的不再属于快照范围。
- 历史依赖旧语义的统计、截图、文档需要更新。
- 落地时将同步更新 `docs/migration/breaking-changes.md`。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- 旧分支 `gantt_shouban30_service.py` 的页面导出/现算逻辑不再沿用。
- 本 RFC 仅作用于目标仓库现有 `gantt_readmodel.py` 的盘后快照行为。

## 10. 测试与验收（Acceptance Criteria）

- [ ] `test_gantt_readmodel.py` 覆盖北交所标的被排除。
- [ ] 过滤后无候选股的板块不会写入 `shouban30_plates`。
- [ ] 重建最新交易日 `shouban30` 后，`920xxx` 不再出现在 `shouban30_stocks`。
- [ ] `/api/gantt/shouban30/plates|stocks` 不再返回北交所标的或空板块。

## 11. 风险与回滚（Risks / Rollback）

- 风险：现有统计值会下降，可能与历史截图不一致。
- 缓解：在 `breaking-changes.md` 中明确迁移语义，并重建最新交易日四档窗口快照。
- 回滚：回退 `gantt_readmodel.py` 与相关测试，重新构建 `shouban30` 快照。

## 12. 里程碑与拆分（Milestones）

- M1：RFC 通过
- M2：读模型测试补齐并失败
- M3：实现北交所排除并测试通过
- M4：重建最新交易日快照并验证 API 结果
