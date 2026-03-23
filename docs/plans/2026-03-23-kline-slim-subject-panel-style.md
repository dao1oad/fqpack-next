# Kline Slim Subject Panel Style Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 优化 `/kline-slim` 标的设置浮层的布局密度和 buy lot 止损区可读性，避免标题竖排、过长 `buy_lot_id` 撑坏布局，并补充更有业务语义的订单摘要。

**Architecture:** 保持现有 `KlineSlim.vue + kline-slim-subject-panel.mjs + subjectManagement.mjs` 分层不变。新增 buy lot 展示摘要 helper，在 view model 中产出“中文摘要 + 次级元信息”，模板只消费归一化字段；样式层调整浮层宽度、头部布局和止损行 grid，确保更紧凑且不引入额外信息噪音。

**Tech Stack:** Vue 3, Element Plus, Stylus, Node test runner

---

### Task 1: 锁定 buy lot 摘要字段

**Files:**
- Modify: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- Modify: `morningglory/fqwebui/src/views/js/kline-slim-subject-panel.test.mjs`
- Modify: `morningglory/fqwebui/src/views/klineSlim.test.mjs`

**Step 1: Write the failing test**

为 `buildDetailViewModel()` 和 `normalizeKlineSlimSubjectPanelDetail()` 增加断言：
- `buyLots[n]` 暴露 `buyLotDisplayLabel`
- `buyLots[n]` 暴露 `buyLotMetaLabel`
- 长 `buy_lot_id` 不再作为唯一主显示文案

并为 `KlineSlim.vue` 增加结构断言：
- 标的设置头部存在独立摘要区
- stoploss row 使用新的摘要/元信息节点

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/klineSlim.test.mjs morningglory/fqwebui/src/views/js/kline-slim-subject-panel.test.mjs morningglory/fqwebui/src/views/subjectManagement.test.mjs`

Expected: FAIL，因为新增字段和模板结构尚不存在。

**Step 3: Write minimal implementation**

在 `subjectManagement.mjs` 内构造 buy lot 中文摘要与元信息，在 `kline-slim-subject-panel.mjs` 透传归一化结果，在 `KlineSlim.vue` 使用新字段替代裸 `buy_lot_id`。

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/klineSlim.test.mjs morningglory/fqwebui/src/views/js/kline-slim-subject-panel.test.mjs morningglory/fqwebui/src/views/subjectManagement.test.mjs`

Expected: PASS

### Task 2: 收紧弹窗布局

**Files:**
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`

**Step 1: Write the failing test**

为 `KlineSlim` 视图测试增加样式源码断言：
- `kline-slim-subject-panel` 宽度大于现有 `372px`
- 头部 actions 支持换行或压缩
- stoploss row 改为更稳定的 grid/stack 布局

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/klineSlim.test.mjs`

Expected: FAIL，因为当前样式仍是旧尺寸和旧 grid。

**Step 3: Write minimal implementation**

调整浮层宽度、头部布局、摘要行布局、stoploss row 卡片布局和移动端收敛规则；尽量减少垂直空白。

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/klineSlim.test.mjs`

Expected: PASS

### Task 3: 文档与构建验证

**Files:**
- Modify: `docs/current/modules/kline-webui.md`

**Step 1: Update docs**

记录标的设置浮层当前展示语义：
- 浮层头部采用紧凑摘要布局
- buy lot 止损区显示中文摘要和买入元信息，原始 `buy_lot_id` 降级为辅助信息

**Step 2: Run verification**

Run:
- `node --test morningglory/fqwebui/src/views/klineSlim.test.mjs morningglory/fqwebui/src/views/js/kline-slim-subject-panel.test.mjs morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- `npm run build`
- `py -3.12 script/ci/check_current_docs.py`

Expected:
- tests PASS
- build exit 0
- docs guard OK

### Task 4: 集成交付

**Files:**
- No new code files expected

**Step 1: Commit**

```bash
git add docs/current/modules/kline-webui.md docs/plans/2026-03-23-kline-slim-subject-panel-style.md morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/src/views/js/kline-slim-subject-panel.mjs morningglory/fqwebui/src/views/subjectManagement.mjs morningglory/fqwebui/src/views/klineSlim.test.mjs morningglory/fqwebui/src/views/js/kline-slim-subject-panel.test.mjs morningglory/fqwebui/src/views/subjectManagement.test.mjs
git commit -m "feat: tighten kline slim subject panel layout"
```

**Step 2: Merge and deploy**

创建 PR，合并远程 `main`，然后仅对 `web` 执行 formal deploy，并以 `result.json`、`runtime-verify.json`、`production-state.json` 为完成依据。
