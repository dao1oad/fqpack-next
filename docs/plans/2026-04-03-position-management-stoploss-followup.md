# Position Management Stoploss Follow-up Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 完成 `PositionManagement` 第二轮优化：修正中栏字段口径、把最近决策改成全量时间线、让右上 entry 与切片形成主从联动，并实现 symbol 级全仓止损语义。

**Architecture:** 前端继续复用 `SubjectManagement` 读模型与控制器，但把中栏字段映射改成真实 `effective_value` 语义，并在右上引入“选中 entry”状态。后端在 TPSL 中新增 symbol 级全仓止损 batch，优先级高于 entry 级 stoploss，同时保留现有 entry 级绑定接口。

**Tech Stack:** Vue 3、Element Plus、Node test runner、Playwright、Flask、Python pytest

---

### Task 1: 建立前端字段与联动的失败测试

**Files:**
- Modify: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- Modify: `morningglory/fqwebui/src/views/positionManagement.test.mjs`
- Modify: `morningglory/fqwebui/src/views/positionManagementSubjectWorkbench.test.mjs`
- Modify: `morningglory/fqwebui/tests/workbench-overlap.browser.spec.mjs`

**Step 1: 写失败测试**

- 给 `buildDenseConfigRows()` 增加断言：
  - 不再返回 `category`
  - 返回 `full_stop_loss_price / initial_lot_amount / lot_amount / active_single_stoploss`
  - `lot_amount` 当前生效值能从默认链路回退得到
- 给 `buildRecentDecisionLedgerRows()` 增加断言：
  - 不按 symbol 过滤
  - 结果按 `evaluated_at` 倒序
- 给 `positionManagementSubjectWorkbench` 增加断言：
  - 默认选中首个 entry
  - 切换 entry 后只暴露该 entry 的切片
- 给 browser smoke 增加断言：
  - 新列头名称
  - 最近决策显示全量
  - 切换 entry 后切片明细变化

**Step 2: 跑测试确认失败**

Run: `npm run test:unit`
Expected: 新增的 `positionManagement` / `subjectManagement` / `positionManagementSubjectWorkbench` 相关断言失败

Run: `npm run test:browser-smoke`
Expected: `position-management` 相关 smoke 失败

### Task 2: 实现前端字段重命名与真实有效值口径

**Files:**
- Modify: `morningglory/fqwebui/src/views/subjectManagement.mjs`
- Modify: `morningglory/fqwebui/src/components/position-management/PositionSubjectOverviewPanel.vue`

**Step 1: 最小实现**

- `buildDenseConfigRows()` 去掉 `category`
- 把：
  - `止损价` 改成 `全仓止损价`
  - `首笔金额` 改成 `开仓数量`
  - `常规金额` 改成 `默认买入金额`
  - `活跃止损` 改成 `活跃单笔止损`
- `默认买入金额` 使用 `lot_amount.effective_value`
- `开仓数量` 使用 `initial_lot_amount.effective_value`
- 调整列头与空态文案

**Step 2: 跑测试确认通过**

Run: `npm run test:unit`
Expected: 字段映射相关 Node 测试转绿

### Task 3: 实现右上 entry 选中态与切片主从联动

**Files:**
- Modify: `morningglory/fqwebui/src/views/positionManagementSubjectWorkbench.mjs`
- Modify: `morningglory/fqwebui/src/components/position-management/PositionSubjectOverviewPanel.vue`

**Step 1: 写最小状态层**

- 为每个 symbol 维护 `selectedEntryId`
- hydrate detail 后默认选中第一条 entry
- 切换 symbol 时重置为首条 entry
- 派生 `selectedEntry` 和 `selectedEntrySlices`

**Step 2: 调整 UI**

- `聚合买入列表 / 按持仓入口止损` 改为可点击选中行
- `切片明细` 单独渲染在右上第二张表
- 不再在浮层里一次性展示所有切片

**Step 3: 跑测试确认通过**

Run: `npm run test:unit`
Expected: controller 和组件结构测试通过

Run: `npm run test:browser-smoke`
Expected: `position-management` 右上主从联动 smoke 通过

### Task 4: 取消最近决策与选中标的联动

**Files:**
- Modify: `morningglory/fqwebui/src/views/positionManagement.mjs`
- Modify: `morningglory/fqwebui/src/views/PositionManagement.vue`

**Step 1: 写最小实现**

- `buildRecentDecisionLedgerRows()` 改成全量 rows
- 按 `evaluated_at` 从近到远排序
- `PositionManagement.vue` 删除基于当前选中 symbol 的过滤依赖

**Step 2: 跑测试确认通过**

Run: `npm run test:unit`
Expected: recent decision 相关测试通过

Run: `npm run test:browser-smoke`
Expected: 最近决策全量显示的 smoke 通过

### Task 5: 建立 symbol 级全仓止损的失败测试

**Files:**
- Modify: `freshquant/tests/test_tpsl_service.py`
- Modify: `freshquant/tests/test_tpsl_stoploss_batch.py`
- Modify: `freshquant/tests/test_tpsl_management_service.py`

**Step 1: 写失败测试**

- `evaluate_stoploss()` 在 symbol 命中 `must_pool.stop_loss_price` 时生成 full-position batch
- 当 symbol 级全仓止损与 entry 级止损同时命中时，只返回 full-position batch
- batch 聚合全部 open entry slices
- 事件 / strategy / scope_type 区分 `symbol_full_stoploss`

**Step 2: 跑测试确认失败**

Run: `py -3.12 -m pytest freshquant/tests/test_tpsl_service.py freshquant/tests/test_tpsl_stoploss_batch.py freshquant/tests/test_tpsl_management_service.py -q`
Expected: symbol full stoploss 相关测试失败

### Task 6: 实现 symbol 级全仓止损 batch 与优先级

**Files:**
- Modify: `freshquant/tpsl/service.py`
- Modify: `freshquant/tpsl/stoploss_batch.py`
- Modify: `freshquant/subject_management/dashboard_service.py` 或相关读 helper（仅当需要读取 must_pool.stop_loss_price）
- Modify: `freshquant/rear/order/routes.py` 仅在接口契约需要扩展时修改

**Step 1: 最小实现**

- 在 stoploss 评估中先解析 symbol 级 `must_pool.stop_loss_price`
- 构建 full-position batch：
  - 聚合 symbol 全部 open entry slices
  - 受 `can_use_volume` 和一手约束限制
  - `scope_type = symbol_stoploss_batch`
  - `strategy_name = FullPositionStoploss`
- 若 full-position batch ready，则不再走 entry 级 stoploss
- stoploss 事件里补 symbol 级语义标记

**Step 2: 跑测试确认通过**

Run: `py -3.12 -m pytest freshquant/tests/test_tpsl_service.py freshquant/tests/test_tpsl_stoploss_batch.py freshquant/tests/test_tpsl_management_service.py -q`
Expected: 相关 pytest 全绿

### Task 7: 更新文档与前后端验收

**Files:**
- Modify: `docs/current/modules/position-management.md`
- Modify: `docs/current/modules/subject-management.md`
- Modify: `docs/current/modules/tpsl.md`

**Step 1: 同步当前事实**

- 文档改成“全仓止损价 + 单笔止损并存”
- 更新右上工作区与最近决策的当前布局说明

**Step 2: 跑完整前端验证**

Run: `npm run lint`
Expected: exit 0

Run: `npm run test:unit`
Expected: all green

Run: `npm run test:browser-smoke`
Expected: all green

Run: `npm run build`
Expected: exit 0

### Task 8: 部署与收尾

**Files:**
- Modify: none

**Step 1: 提交改动**

```bash
git add docs/current/modules/position-management.md docs/current/modules/subject-management.md docs/current/modules/tpsl.md docs/plans/2026-04-03-position-management-stoploss-followup-design.md docs/plans/2026-04-03-position-management-stoploss-followup.md morningglory/fqwebui/src/components/position-management/PositionSubjectOverviewPanel.vue morningglory/fqwebui/src/views/PositionManagement.vue morningglory/fqwebui/src/views/positionManagement.mjs morningglory/fqwebui/src/views/positionManagementSubjectWorkbench.mjs morningglory/fqwebui/src/views/subjectManagement.mjs morningglory/fqwebui/src/views/subjectManagement.test.mjs morningglory/fqwebui/src/views/positionManagement.test.mjs morningglory/fqwebui/src/views/positionManagementSubjectWorkbench.test.mjs morningglory/fqwebui/tests/workbench-overlap.browser.spec.mjs freshquant/tpsl/service.py freshquant/tpsl/stoploss_batch.py freshquant/tests/test_tpsl_service.py freshquant/tests/test_tpsl_stoploss_batch.py freshquant/tests/test_tpsl_management_service.py
git commit -m "feat: add full-position stoploss to position management"
```

**Step 2: 推送并合并**

```bash
git push -u origin codex/position-management-stoploss-followup
```

**Step 3: 正式部署**

Run: `powershell -ExecutionPolicy Bypass -File script/ci/run_production_deploy.ps1 -CanonicalRoot D:\\fqpack\\freshquant-2026.2.23 -MirrorRoot D:\\fqpack\\freshquant-2026.2.23\\.worktrees\\main-deploy-production -MirrorBranch deploy-production-main`
Expected: `ok: true`, `deployment_surfaces: web`，以及受影响的 API / worker runtime verify 正常

**Step 4: 健康检查**

Run: `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18080/`
Expected: `200`

Run: `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/health/summary`
Expected: `200`
