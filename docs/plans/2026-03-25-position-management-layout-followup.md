# Position Management Layout Followup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 收口 `/position-management` 的首屏空白、指标卡尺寸和右栏仓位列顺序，让页面更紧凑且表格节奏稳定。

**Architecture:** 只调整 `PositionManagement.vue` 的模板顺序和 CSS 栅格，不改后端读模型。所有变更先在 `position-management.test.mjs` 中建立失败断言，再做最小实现，最后同步 `docs/current/modules/position-management.md` 的当前事实。

**Tech Stack:** Vue 3、Element Plus、Node built-in test、Vite

---

### Task 1: 建立失败基线

**Files:**
- Modify: `morningglory/fqwebui/src/views/position-management.test.mjs`

**Step 1: 为三项需求补失败断言**

- 断言最近决策 ledger 的默认可视高度从 11 行提升到 15 行左右
- 断言“当前命中规则”不再占据独立宽列，而是进入统一小卡布局
- 断言右栏表头和行模板里，“券商仓位 / 推断仓位 / stock_fills仓位”位于“操作”列之后
- 断言三列仓位使用固定宽度列，而不是 `minmax(..., 1.1fr)` 弹性列

**Step 2: 运行测试并确认失败**

Run:

```powershell
node --test morningglory/fqwebui/src/views/position-management.test.mjs
```

Expected: 新增断言失败，且失败点对应最近决策高度、规则卡尺寸和右栏列顺序。

### Task 2: 调整页面实现

**Files:**
- Modify: `morningglory/fqwebui/src/views/PositionManagement.vue`

**Step 1: 提高最近决策默认可视行数**

- 将 `runtime-position-decision-ledger` 的 `max-height` 从当前 11 行提升到约 15 行
- 保持分页仍为 `100 / 页`

**Step 2: 收紧“当前命中规则”卡片**

- 让 `position-rule-card` 和其他 `position-metric-card` 共用同一网格尺寸
- 保留一行详情文案，但不再让它撑出单独大列

**Step 3: 调整右栏表格列顺序与宽度**

- 把三列仓位挪到“操作”列之后
- 给三列仓位设置固定宽度
- 保持单元格内部的数量/市值与来源双层展示

**Step 4: 跑单测**

Run:

```powershell
node --test morningglory/fqwebui/src/views/position-management.test.mjs
```

Expected: PASS

### Task 3: 同步当前文档

**Files:**
- Modify: `docs/current/modules/position-management.md`

**Step 1: 更新当前事实**

- 最近决策默认可视行数提高，首屏吃掉更多空白
- 当前命中规则改成与小指标卡同尺寸
- 右栏三列仓位移动到操作列后，并改成固定宽度

**Step 2: 回归验证**

Run:

```powershell
node --test morningglory/fqwebui/src/views/position-management.test.mjs
```

Run:

```powershell
cd morningglory/fqwebui
npm run build
```

Expected: 所有命令 exit 0

### Task 4: 交付

**Files:**
- Verify: `morningglory/fqwebui/src/views/PositionManagement.vue`
- Verify: `morningglory/fqwebui/src/views/position-management.test.mjs`
- Verify: `docs/current/modules/position-management.md`

**Step 1: 提交并推送分支**

Run:

```powershell
git add docs/current/modules/position-management.md docs/plans/2026-03-25-position-management-layout-followup-design.md docs/plans/2026-03-25-position-management-layout-followup.md morningglory/fqwebui/src/views/PositionManagement.vue morningglory/fqwebui/src/views/position-management.test.mjs
git commit -m "Refine position management panel layout"
git push -u origin <feature-branch>
```

**Step 2: 创建 PR，等待 CI，合并到 `main`**

Expected: `governance / pre-commit / pytest` 全绿

**Step 3: 正式部署 Web UI**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File script/ci/run_production_deploy.ps1 -CanonicalRoot D:\fqpack\freshquant-2026.2.23 -MirrorRoot D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production -MirrorBranch deploy-production-main
```

**Step 4: 健康检查与截图复核**

Expected: `http://127.0.0.1:18080/position-management` 返回 `200`，截图确认三项调整都已生效。
