# KlineSlim Panel Order And Holdings Sort Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 调整 `KlineSlim` 画线编辑浮层区块顺序，并让 `持仓股` 默认按仓位金额降序且与默认标的选择一致。

**Architecture:** 模板层只交换两个价格区块的位置；持仓排序逻辑集中到前端 helper，并由 sidebar 构建和默认标的选择共享，避免同一页面出现两个不同的“默认顺序”。

**Tech Stack:** Vue SFC、原生 Node test、前端辅助模块 `kline-slim-sidebar.mjs` / `kline-slim-default-symbol.mjs`

---

### Task 1: 锁定画线编辑区块顺序

**Files:**
- Modify: `morningglory/fqwebui/src/views/klineSlim.test.mjs`
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`

**Step 1: Write the failing test**

- 在 `klineSlim.test.mjs` 增加断言：`止盈价格` 的 section title 出现在 `Guardian 倍量价格` 之前。

**Step 2: Run test to verify it fails**

Run: `node --test src/views/klineSlim.test.mjs`
Expected: 新断言失败，说明当前模板顺序仍是 Guardian 在前。

**Step 3: Write minimal implementation**

- 在 `KlineSlim.vue` 里交换两个大 section 的模板顺序。

**Step 4: Run test to verify it passes**

Run: `node --test src/views/klineSlim.test.mjs`
Expected: 通过。

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/src/views/klineSlim.test.mjs
git commit -m "fix kline slim price panel section order"
```

### Task 2: 锁定持仓降序与默认标的一致性

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim-sidebar.test.mjs`
- Create: `morningglory/fqwebui/src/views/js/kline-slim-default-symbol.test.mjs`
- Modify: `morningglory/fqwebui/src/views/js/kline-slim-sidebar.mjs`
- Modify: `morningglory/fqwebui/src/views/js/kline-slim-default-symbol.mjs`

**Step 1: Write the failing tests**

- 在 `kline-slim-sidebar.test.mjs` 增加 `holding` 分组降序排序测试。
- 新建 `kline-slim-default-symbol.test.mjs`，断言 `pickFirstHoldingSymbol()` 选择仓位最大的 symbol。

**Step 2: Run tests to verify they fail**

Run: `node --test src/views/js/kline-slim-sidebar.test.mjs src/views/js/kline-slim-default-symbol.test.mjs`
Expected: 排序相关断言失败。

**Step 3: Write minimal implementation**

- 在 `kline-slim-sidebar.mjs` 提供共享持仓排序 helper，并只在 `holding` 分组使用。
- 在 `kline-slim-default-symbol.mjs` 复用同一 helper 来选择默认 symbol。

**Step 4: Run tests to verify they pass**

Run: `node --test src/views/js/kline-slim-sidebar.test.mjs src/views/js/kline-slim-default-symbol.test.mjs`
Expected: 全部通过。

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim-sidebar.mjs morningglory/fqwebui/src/views/js/kline-slim-default-symbol.mjs morningglory/fqwebui/src/views/js/kline-slim-sidebar.test.mjs morningglory/fqwebui/src/views/js/kline-slim-default-symbol.test.mjs
git commit -m "fix kline slim holding order defaults"
```

### Task 3: 全量验证与文档同步

**Files:**
- Modify: `docs/current/modules/kline-webui.md`
- Modify: `morningglory/fqwebui/web/**`

**Step 1: Update docs**

- 在 `docs/current/modules/kline-webui.md` 记录新顺序和持仓默认降序行为。

**Step 2: Run focused verification**

Run: `node --test src/views/js/kline-slim-sidebar.test.mjs src/views/js/kline-slim-default-symbol.test.mjs src/views/klineSlim.test.mjs`
Expected: 全部通过。

**Step 3: Run broader verification**

Run: `node --test src/views/js/subject-price-guides.test.mjs src/views/js/kline-slim-price-panel.test.mjs src/views/js/kline-slim-chart-price-guides.test.mjs src/views/js/kline-slim-chart-controller.test.mjs src/views/js/kline-slim-sidebar.test.mjs src/views/js/kline-slim-default-symbol.test.mjs src/views/klineSlim.test.mjs`
Expected: 全部通过。

**Step 4: Build**

Run: `npm run build`
Expected: build 成功，更新 `morningglory/fqwebui/web/**`。

**Step 5: Commit**

```bash
git add docs/current/modules/kline-webui.md morningglory/fqwebui/web
git commit -m "docs kline slim panel order and holding sort"
```

