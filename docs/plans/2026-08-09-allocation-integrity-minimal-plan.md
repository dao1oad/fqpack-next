# 账本内部一致性校验（allocation_integrity）最小化方案

日期：2026-08-09
状态：已确认（用户）+ Devin 架构评审（单轮）
关联：#504/#505（将关闭）、#412（保留）、#478/#475（将关闭）

## 一、结论

1. **与 #412 不重复、不阻塞**：
   - 机器事实（已验证）：`morningglory/fqwebui/src/router/index.js` 中 `/reconciliation` 已是
     redirect 到 `/position-management`（第 94-100 行），#412 的“并入”主体早已完成；
     剩余工作仅为清理 `ReconciliationWorkbench.vue` 等遗留文件，属于独立小任务。
   - allocation_integrity 是对既有 `ledger_internal_consistency` 规则
     （`reconciliation_read_service.py:264`，entry↔slice 数量匹配，mismatch_code=
     `entry_vs_slice_quantity_mismatch`）的**逐记录级加深**：新增三表引用完整性、
     symbol 三方一致性、exit_allocations 参与。属数据能力增强，不是新入口。
   - 接入既有 summary/rules 体系，不产生第三套“对账/一致性”入口。

2. **最小化方案**（本次实施范围）见下；**本次不做**清单见第四节。

## 二、后端接入（文件级）

1. `freshquant/order_management/allocation_integrity.py`
   - 从 PR #505 提取只读纯函数 `find_exit_allocation_integrity_errors(...)`
     （约 280 行，main 上不存在）。
   - 检查对象：`om_position_entries` / `om_entry_slices` / `om_exit_allocations`。
   - 检查项：重复 ID、引用完整性、slice 归属一致、symbol 三方一致、数量有效性/不超剩余。
   - 只读、无副作用。
2. `freshquant/tests/test_allocation_integrity.py`
   - 用例：引用缺失、slice 归属错位、symbol 不一致（#504 混合 symbol 场景）、
     数量超限、正常账本零错误。
3. `freshquant/position_management/reconciliation_read_service.py`
   - `get_overview()` 顶层增加 `internal_integrity` 字段：复用既有
     `CONSISTENCY_RULES` / `_build_exact_match_check` 风格，返回
     `{ok, error_count, errors[], by_symbol{}}`。
   - 不动 rows 的五源对比结构；**routes.py 零改动、不新增端点**。

## 三、前端接入（组件级）

1. `morningglory/fqwebui/src/components/position-management/PositionReconciliationPanel.vue`
   - 摘要行新增 1 个“内部一致性” StatusChip（ERROR / OK 计数）。
   - 展开区新增规则行（复用现有 rules 行模式），展示错误清单（allocation_id、
     entry_id / entry_slice_id、期望 vs 实际 symbol / 数量）。
   - 无新抽屉、无新路由。
2. `morningglory/fqwebui/src/views/positionReconciliation.mjs`
   - 消费 `get_overview().internal_integrity`，映射到 Chip 与规则行。

## 四、CLI 与验证接入

- `script/maintenance/rebuild_order_ledger_v2.py` 与
  `script/maintenance/targeted_order_ledger_repair.py` 增加 `--verify` 后检：
  重建/修复完成后调用 allocation_integrity 校验器，非零错误即退出码非 0。
- 验收：三台机器（101/100/116）重建后账本跑校验器返回零错误，作为
  “数据层已解决”的机器事实证据。

## 五、验收口径

1. 单测：上述用例全绿（pytest）。
2. 面板：仓位管理 → 对账检查 → “内部一致性” Chip 计数正确，展开区错误清单可读。
3. CLI：`--verify` 在重建后账本上零错误；故意注入错位时非零退出。
4. CI：docs-current-guard / pre-commit / pytest 全绿；docs/current 同步。
5. 随下一次统一部署上线（当前 Deploy Production workflow 已禁用，等待统一部署）。

## 六、本次不做（防止范围膨胀）

- PR #505 其余内容：ingest/xt_reports.py、repository.py、tracking/service.py、
  reconcile/service.py、broker_match.py 的大规模重写，以及 broker_correlation.py、
  repair/targeted_ledger.py 的 #505 增强版 —— 均不引入。
- 校验结果落库 / 历史快照（保持只读巡检语义，仅页面与 CLI 消费）。
- #412 的遗留文件清理（ReconciliationWorkbench.vue 等）——独立小任务，另行处理。