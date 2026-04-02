# Position Management Dense Layout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 PositionManagement 重构为高密度三栏交易台：左栏状态/对账对半，中栏 dense 标的总览，右栏选中标的工作区 + 最近决策。

**Architecture:** 继续复用现有 `PositionManagement`、`PositionSubjectOverviewPanel`、`PositionReconciliationPanel` 与 subject workbench controller。新增“选中标的”主从联动，只在视图层重排数据与布局，不改 API 协议。测试先锁定结构与联动，再最小实现通过。

**Tech Stack:** Vue 3 SFC、Element Plus、Node `--test`、现有 workbench primitives。

---

### Task 1: 锁定新版工作台结构测试

**Files:**
- Modify: `morningglory/fqwebui/src/views/position-management.test.mjs`
- Modify: `morningglory/fqwebui/src/views/workbenchViewportLayout.test.mjs`
- Modify: `morningglory/fqwebui/src/views/workbenchDesignSystem.test.mjs`

**Step 1: 写失败测试**

- 断言左栏与右栏都切为上下两段布局
- 断言右栏新增“选中标的工作区”
- 断言 `PositionReconciliationPanel` 不再描述为 card layout
- 断言 `PositionSubjectOverviewPanel` 使用 dense table + row selection 结构

**Step 2: 运行测试，确认失败**

Run:

```bash
node --experimental-default-type=module --test src/views/position-management.test.mjs src/views/workbenchViewportLayout.test.mjs src/views/workbenchDesignSystem.test.mjs
```

Expected: 至少 1 个与新版布局/结构断言相关的失败。

**Step 3: 保持测试最小且可读**

- 不测试视觉细节颜色
- 只测试布局骨架、联动入口与表格语义

### Task 2: 重构中栏标的总览为高密度主表

**Files:**
- Modify: `morningglory/fqwebui/src/components/position-management/PositionSubjectOverviewPanel.vue`
- Test: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`

**Step 1: 写失败测试**

- 断言配置项不再纵向渲染为多段 block/card
- 断言每个设置项进入独立列
- 断言表格支持当前选中 symbol 的单行高亮/事件发射

**Step 2: 运行测试，确认失败**

Run:

```bash
node --experimental-default-type=module --test src/views/subjectManagement.test.mjs src/views/workbenchDesignSystem.test.mjs
```

Expected: 与 dense column layout/selection 相关断言失败。

**Step 3: 最小实现**

- 增加 `selectedSymbol` / `@select` 或行点击发射
- 将配置编辑器压缩到列中
- 保留单行保存按钮
- 继续按现有排序展示，不改数据构造逻辑

**Step 4: 重跑相关测试**

Run:

```bash
node --experimental-default-type=module --test src/views/subjectManagement.test.mjs src/views/positionManagementSubjectWorkbench.test.mjs
```

Expected: PASS

### Task 3: 重构左栏对账检查为 dense ledger

**Files:**
- Modify: `morningglory/fqwebui/src/components/position-management/PositionReconciliationPanel.vue`
- Test: `morningglory/fqwebui/src/views/positionReconciliation.test.mjs`

**Step 1: 写失败测试**

- 断言“对账检查”使用 ledger/table 结构而非 audit card list
- 断言保留筛选器、状态 chip 与行级证据入口

**Step 2: 运行测试，确认失败**

Run:

```bash
node --experimental-default-type=module --test src/views/positionReconciliation.test.mjs
```

Expected: 与 dense reconciliation ledger 相关断言失败。

**Step 3: 最小实现**

- 使用表格/ledger 行承载 symbol、状态、gap、mismatch 摘要
- 证据区改为行展开的次级表格或紧凑块
- 删除旧 card grid 样式

**Step 4: 重跑测试**

Run:

```bash
node --experimental-default-type=module --test src/views/positionReconciliation.test.mjs
```

Expected: PASS

### Task 4: 完成主视图联动与右栏拆分

**Files:**
- Modify: `morningglory/fqwebui/src/views/PositionManagement.vue`
- Possibly Modify: `morningglory/fqwebui/src/views/positionManagement.mjs`
- Test: `morningglory/fqwebui/src/views/positionManagement.test.mjs`
- Test: `morningglory/fqwebui/src/views/position-management.test.mjs`

**Step 1: 写失败测试**

- 断言右栏上半区为“选中标的工作区”
- 断言右栏下半区为“最近决策与上下文”
- 断言页面默认选中排序后的首个标的
- 断言右下决策表按当前选中标的过滤

**Step 2: 运行测试，确认失败**

Run:

```bash
node --experimental-default-type=module --test src/views/positionManagement.test.mjs src/views/position-management.test.mjs
```

Expected: 与右栏拆分/选中联动相关断言失败。

**Step 3: 最小实现**

- 在 `PositionManagement.vue` 持有 `selectedSymbol`
- 中栏发射 `symbol-select`
- 右上渲染当前 symbol 的 entry 表与切片表
- 右下只显示该 symbol 的最近决策
- 左栏和右栏统一改为 `1fr 1fr`

**Step 4: 重跑测试**

Run:

```bash
node --experimental-default-type=module --test src/views/positionManagement.test.mjs src/views/position-management.test.mjs src/views/workbenchViewportLayout.test.mjs
```

Expected: PASS

### Task 5: 更新当前文档并完成回归验证

**Files:**
- Modify: `docs/current/overview.md`
- Possibly Modify: `docs/current/architecture.md`

**Step 1: 同步当前事实**

- 更新 PositionManagement 当前布局描述
- 明确中栏主表、右栏联动工作区与最近决策的关系

**Step 2: 运行回归测试**

Run:

```bash
node --experimental-default-type=module --test src/views/workbenchViewportLayout.test.mjs src/views/workbenchDesignSystem.test.mjs src/views/position-management.test.mjs src/views/positionManagement.test.mjs src/views/positionManagementSubjectWorkbench.test.mjs src/views/positionReconciliation.test.mjs src/views/subjectManagement.test.mjs
```

Expected: 全部 PASS

**Step 3: 构建检查**

Run:

```bash
npm run build
```

Expected: Vite build 成功。

**Step 4: 提交**

```bash
git add docs/plans/2026-04-02-position-management-dense-layout-design.md docs/plans/2026-04-02-position-management-dense-layout.md docs/current/overview.md docs/current/architecture.md morningglory/fqwebui/src/views/PositionManagement.vue morningglory/fqwebui/src/components/position-management/PositionSubjectOverviewPanel.vue morningglory/fqwebui/src/components/position-management/PositionReconciliationPanel.vue morningglory/fqwebui/src/views/position-management.test.mjs morningglory/fqwebui/src/views/positionManagement.test.mjs morningglory/fqwebui/src/views/positionReconciliation.test.mjs morningglory/fqwebui/src/views/workbenchViewportLayout.test.mjs morningglory/fqwebui/src/views/workbenchDesignSystem.test.mjs morningglory/fqwebui/src/views/subjectManagement.test.mjs
git commit -m "feat: densify position management workspace"
```
