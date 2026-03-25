# Kline Slim 平移精度与批量运行态 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `kline-slim` 增加 `Shift + 左键拖拽` 双轴平移，修复图上拖拽仍是两位小数的问题，并让批量 `全部开启 / 全部关闭` 同步配置层与运行态。

**Architecture:** 保持现有普通拖拽和画线编辑手势不变，在控制器中新增独立的 shift-pan 状态机；价格取值统一复用三位小数；批量开关沿用现有保存链路，但为 Guardian 增加状态保存调用、为止盈增加 `rearm` 调用。所有行为先由单测锁定，再做最小实现并同步 `docs/current`。

**Tech Stack:** Vue 2 + Element UI，ECharts 控制器，Node test，Vite build。

---

### Task 1: 写失败测试锁定目标行为

**Files:**
- Modify: `D:/fqpack/freshquant-2026.2.23/.worktrees/kline-slim-runtime-state-20260325/morningglory/fqwebui/src/views/js/kline-slim-chart-controller.test.mjs`
- Modify: `D:/fqpack/freshquant-2026.2.23/.worktrees/kline-slim-runtime-state-20260325/morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs`

**Step 1: 写双轴平移失败测试**

- 新增 `Shift + 左键拖拽` 用例
- 断言视口进入 `manual`
- 断言 `xRange` 与 `yRange` 都变化

**Step 2: 写三位小数拖拽失败测试**

- 新增价格线拖拽用例
- 断言拖拽回调中的 `price` 至少能落在三位小数精度

**Step 3: 写批量运行态同步失败测试**

- Guardian 批量开启/关闭时，断言除了 `saveGuardianBuyGrid` 还会调用 `saveGuardianBuyGridState`
- 止盈批量开启/关闭时，断言保存配置后会调用 `rearmTakeprofit`

**Step 4: 运行失败测试**

Run: `node --test src/views/js/kline-slim-chart-controller.test.mjs src/views/js/kline-slim-price-panel.test.mjs`

Expected: 新增断言失败，且失败原因与目标行为尚未实现一致。

### Task 2: 最小实现控制器与保存链路

**Files:**
- Modify: `D:/fqpack/freshquant-2026.2.23/.worktrees/kline-slim-runtime-state-20260325/morningglory/fqwebui/src/views/js/kline-slim-chart-controller.mjs`
- Modify: `D:/fqpack/freshquant-2026.2.23/.worktrees/kline-slim-runtime-state-20260325/morningglory/fqwebui/src/views/js/kline-slim-chart-renderer.mjs`
- Modify: `D:/fqpack/freshquant-2026.2.23/.worktrees/kline-slim-runtime-state-20260325/morningglory/fqwebui/src/views/js/kline-slim-price-panel.mjs`
- Modify: `D:/fqpack/freshquant-2026.2.23/.worktrees/kline-slim-runtime-state-20260325/morningglory/fqwebui/src/views/js/kline-slim.js`

**Step 1: 实现双轴平移**

- 在控制器中增加 `shift-pan` 起止状态
- 让 `Shift + 左键拖拽` 同步平移 `xRange` 和 `yRange`
- 确保不与价格线拖拽冲突

**Step 2: 统一三位小数**

- 把图上像素取价从两位改为三位
- 把十字准星价格显示同步到三位

**Step 3: 实现批量运行态同步**

- Guardian 批量按钮保存配置后，再保存 `buy_active`
- 止盈批量按钮保存配置后，再调用 `rearm`
- 行内单开关保持现状，不直接改运行态

**Step 4: 运行定向测试**

Run: `node --test src/views/js/kline-slim-chart-controller.test.mjs src/views/js/kline-slim-price-panel.test.mjs`

Expected: PASS

### Task 3: 同步当前文档并回归验证

**Files:**
- Modify: `D:/fqpack/freshquant-2026.2.23/.worktrees/kline-slim-runtime-state-20260325/docs/current/modules/kline-webui.md`

**Step 1: 更新当前文档**

- 记录 `Shift + 左键拖拽` 双轴平移
- 记录图上拖拽与保存统一三位小数
- 记录批量开关会同步配置层与运行态

**Step 2: 跑相关前端测试**

Run: `node --test src/views/js/subject-price-guides.test.mjs src/views/js/kline-slim-price-panel.test.mjs src/views/js/kline-slim-chart-price-guides.test.mjs src/views/js/kline-slim-chart-controller.test.mjs src/views/klineSlim.test.mjs`

Expected: PASS，0 fail

**Step 3: 跑构建**

Run: `npm run build`

Expected: exit 0

### Task 4: Git、PR、部署与 cleanup

**Files:**
- Modify: 本次改动文件

**Step 1: 提交**

```bash
git add docs/current/modules/kline-webui.md docs/plans/2026-03-25-kline-slim-pan-precision-runtime-design.md docs/plans/2026-03-25-kline-slim-pan-precision-runtime.md morningglory/fqwebui/src/views/js/kline-slim-chart-controller.mjs morningglory/fqwebui/src/views/js/kline-slim-chart-renderer.mjs morningglory/fqwebui/src/views/js/kline-slim-price-panel.mjs morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/src/views/js/kline-slim-chart-controller.test.mjs morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs
git commit -m "Refine kline slim pan and bulk activation"
```

**Step 2: 推送并合并**

- 推到远端功能分支
- 创建 PR
- 等待 CI
- 合并回远端 `main`

**Step 3: Deploy 与 cleanup**

- 正式 deploy `web`
- 做健康检查和 runtime verify
- 删除远端功能分支与本地 worktree
