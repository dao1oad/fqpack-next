# KlineSlim 视口快路径优化 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 `KlineSlim` 的缩放/平移从整图重绘链路中拆出，改为只更新 `dataZoom` 的视口快路径，降低鼠标交互卡顿。

**Architecture:** 保留现有 `chartDataZoomState` 和 `drawSlim()` 的完整重绘路径，但把 `datazoom` / `mouseup` 改成“状态更新 + 局部 `dataZoom` `setOption`”。只有数据版本变化、legend 切换和结构切换才继续触发 `drawSlim()`。

**Tech Stack:** Vue 3、ECharts 6、Node test runner、Vite

---

### Task 1: 为视口快路径补失败测试

**Files:**
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`
- Reference: `morningglory/fqwebui/src/views/js/kline-slim.js`

**Step 1: 写失败测试**

在 `kline-slim-multi-period-chanlun.test.mjs` 中补文件级断言，锁定以下语义：

1. `handleSlimDataZoom()` 不再直接依赖完整 `scheduleRender(true)` 热路径。
2. `kline-slim.js` 新增专门的局部视口更新函数，例如 `applySlimViewportWindow`。
3. `handleSlimDataZoom()` 和 `handleSlimDataZoomPointerUp()` 会调用该局部视口更新函数。
4. 文件中存在内部递归保护标记，例如 `isApplyingViewportWindow`。

**Step 2: 运行测试确认失败**

Run:
```bash
node --test tests/kline-slim-multi-period-chanlun.test.mjs
```

Expected: 至少 1 个与新断言相关的失败。

**Step 3: 提交前不要修实现**

保持 RED 状态进入 Task 2。

### Task 2: 在 controller 中引入视口快路径

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/src/views/js/draw-slim.js`（仅当需要复用 helper）
- Reference: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: 在 `kline-slim.js` 中新增局部视口更新函数**

目标语义：

1. 仅使用 `chartDataZoomState` 生成 `dataZoom` 配置。
2. 对当前 `chart` 执行局部 `setOption({ dataZoom })`。
3. 不触发 `drawSlim()`。

**Step 2: 增加递归保护**

在组件实例上增加一个轻量保护标记，例如 `isApplyingViewportWindow`：

1. 局部视口更新前置为 `true`
2. 事件回流时直接 return
3. 更新完成后恢复为 `false`

**Step 3: 改写 `handleSlimDataZoom()`**

目标语义：

1. 提取窗口
2. 更新 `chartDataZoomState`
3. 调用局部视口更新函数
4. 不再进入完整 `scheduleRender(true)`

**Step 4: 改写 `handleSlimDataZoomPointerUp()`**

目标语义：

1. 继续从稳定的 `chart.getOption().dataZoom` 读取最终窗口
2. 更新 `chartDataZoomState`
3. 调用局部视口更新函数
4. 不再进入完整 `scheduleRender(true)`

**Step 5: 如有必要，在 `draw-slim.js` 中抽出复用 helper**

如果当前 `resolveDataZoomState()` 无法直接在 controller 层复用，则提取一个小的导出 helper，保持 `dataZoom` 默认值与当前 renderer 一致。

**Step 6: 运行测试确认转绿**

Run:
```bash
node --test tests/kline-slim-multi-period-chanlun.test.mjs
```

Expected: PASS

**Step 7: 提交**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/src/views/js/draw-slim.js morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "perf: add viewport fast path for kline slim"
```

### Task 3: 验证、文档更新与收口

**Files:**
- Modify: `docs/migration/progress.md`
- Possibly update: `morningglory/fqwebui/web/`

**Step 1: 跑聚焦前端测试**

Run:
```bash
node --test tests/kline-slim-default-symbol.test.mjs tests/kline-slim-sidebar.test.mjs tests/kline-slim-chanlun-structure.test.mjs tests/kline-slim-multi-period-chanlun.test.mjs
```

Expected: PASS

**Step 2: 构建前端**

Run:
```bash
npm run build
```

Expected: `vite build` 成功；如 `web/` 产物变化，纳入提交。

**Step 3: 做浏览器烟测**

目标页面：
```text
http://127.0.0.1:18080/kline-slim?symbol=sh510050&period=5m
```

验证点：

1. 连续滚轮缩放时，窗口立即变化。
2. 底部拖拽平移时，窗口立即变化。
3. 滚轮/拖拽期间不再触发完整 `drawSlim()` 重绘链路。
4. 等待一次轮询刷新后，窗口保持不变。
5. `5m` legend 仍然只隐藏 `5m` 缠论层。

**Step 4: 更新 `progress.md`**

在 RFC `0022` 下追加一条说明，记录这次“视口快路径”优化和验证结果。

**Step 5: 提交**

```bash
git add docs/migration/progress.md morningglory/fqwebui/web
git commit -m "docs: record kline slim viewport fast path optimization"
```

**Step 6: 合并前最终验证**

Run:
```bash
git diff --check origin/main...HEAD
```

Expected: 无 trailing whitespace / merge conflict marker 等问题。
