# Kline Slim 运行态展示 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 `kline-slim` 的 `画线编辑` 面板中展示 Guardian 和止盈三层只读运行态，并明确 Guardian 的最近命中语义。

**Architecture:** 保持现有价格编辑与配置开关保存链路不变，只在 `kline-slim.js` 扩展区块/行级运行态计算，再由 `KlineSlim.vue` 渲染只读标签与摘要。测试先行，先让模板断言失败，再做最小实现，最后同步 `docs/current`。

**Tech Stack:** Vue 2 + Element UI 模板，纯前端计算属性，Node test，Vite build。

---

### Task 1: 建立基线与失败测试

**Files:**
- Modify: `D:/fqpack/freshquant-2026.2.23/.worktrees/kline-slim-runtime-state-20260325/morningglory/fqwebui/src/views/klineSlim.test.mjs`

**Step 1: 写失败测试**

- 断言 Guardian 头部出现 `运行态`
- 断言 Guardian 摘要出现 `最近命中价`
- 断言 Guardian 未命中时显示 `最近命中 未命中`
- 断言行内出现 `运行态 激活` / `运行态 未激活`
- 断言止盈区出现 `运行态 已布防` / `运行态 未布防`

**Step 2: 运行失败测试**

Run: `node --test src/views/klineSlim.test.mjs`

Expected: 至少一个新增断言失败，且失败原因是模板/脚本还未输出这些内容。

### Task 2: 做最小实现

**Files:**
- Modify: `D:/fqpack/freshquant-2026.2.23/.worktrees/kline-slim-runtime-state-20260325/morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `D:/fqpack/freshquant-2026.2.23/.worktrees/kline-slim-runtime-state-20260325/morningglory/fqwebui/src/views/KlineSlim.vue`

**Step 1: 扩展计算属性**

- 为 Guardian 行增加只读运行态字段和展示文本
- 为止盈行增加只读运行态字段和展示文本
- 补 Guardian / 止盈区块运行态汇总数量
- 补 Guardian 最近命中摘要文本，在未命中时返回 `未命中`

**Step 2: 渲染模板**

- Guardian 区块头部增加运行态汇总
- Guardian 摘要改为 `最近命中` / `最近命中价`
- Guardian / 止盈每行增加只读运行态 chip

**Step 3: 运行单测**

Run: `node --test src/views/klineSlim.test.mjs`

Expected: PASS

### Task 3: 同步文档与回归验证

**Files:**
- Modify: `D:/fqpack/freshquant-2026.2.23/.worktrees/kline-slim-runtime-state-20260325/docs/current/modules/kline-webui.md`

**Step 1: 更新当前文档**

- 记录 `最近命中价` 的语义
- 记录 Guardian / 止盈三层只读运行态展示

**Step 2: 跑相关测试**

Run: `node --test src/views/js/subject-price-guides.test.mjs src/views/js/kline-slim-price-panel.test.mjs src/views/js/kline-slim-chart-price-guides.test.mjs src/views/klineSlim.test.mjs`

Expected: PASS，0 fail

**Step 3: 跑构建**

Run: `npm run build`

Expected: exit 0

### Task 4: Git 收口

**Files:**
- Modify: 本次改动文件

**Step 1: 提交**

```bash
git add docs/current/modules/kline-webui.md docs/plans/2026-03-25-kline-slim-runtime-state-design.md docs/plans/2026-03-25-kline-slim-runtime-state.md morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/src/views/klineSlim.test.mjs
git commit -m "Show kline slim runtime states"
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
