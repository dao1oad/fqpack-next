# KlineSlim Legend 与中枢残影修复 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 `KlineSlim` 图表的 legend 开关缺失与中枢 `markArea` 切换残影问题，同时保持当前四周期懒加载语义。

**Architecture:** 以当前 `draw-slim.js` 为基础，恢复旧仓的周期组 legend 占位 series 与组联动，并把 `keepState=false` 贯穿到 `drawSlim()` 的结构性重绘。中枢 remap 恢复为旧仓的 `xAxis / yAxis` 点位与边界过滤，避免切换后旧图形残留。

**Tech Stack:** Vue 3 Options API, ECharts, Node `--test`

---

### Task 1: 锁定 legend 分组与结构性重绘契约

**Files:**
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`
- Test: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: Write the failing test**

在 `kline-slim-multi-period-chanlun.test.mjs` 增加断言，锁定：

- `draw-slim.js` 中存在周期组 placeholder series 语义
- `draw-slim.js` 在 `keepState=false` 时使用 `notMerge: true`
- `draw-slim.js` 使用 `xAxis / yAxis` 形式 remap 中枢

**Step 2: Run test to verify it fails**

Run:

```bash
node --test tests/kline-slim-multi-period-chanlun.test.mjs
```

Expected:

- FAIL

**Step 3: Keep only the minimal failing assertions**

将失败限制在上述三个契约，不把无关实现细节一起锁死。

**Step 4: Run test again to confirm RED**

Run:

```bash
node --test tests/kline-slim-multi-period-chanlun.test.mjs
```

Expected:

- FAIL

**Step 5: Commit**

```bash
git add morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "test: 锁定 kline slim legend 与中枢残影契约"
```

### Task 2: 恢复 legend 周期组与组联动

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/draw-slim.js`
- Test: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: Write minimal implementation**

在 `draw-slim.js` 中：

- 为每个可见周期创建 placeholder series
- 建立 `groupName -> memberNames` 映射
- 保留全局 `中枢 / 段中枢` 组
- 让 legend 点击周期组时联动成员 series

**Step 2: Run targeted test**

Run:

```bash
node --test tests/kline-slim-multi-period-chanlun.test.mjs
```

Expected:

- legend 相关断言 PASS
- 残影相关断言仍可能 FAIL

**Step 3: Commit**

```bash
git add morningglory/fqwebui/src/views/js/draw-slim.js morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "feat: 恢复 kline slim legend 周期组"
```

### Task 3: 修复中枢 remap 与结构性重绘

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/draw-slim.js`
- Test: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: Implement remap and replace behavior**

在 `draw-slim.js` 中：

- 将中枢 remap 改为 `xAxis / yAxis` 点位
- 过滤左边界外和零宽中枢
- `keepState=false` 时 `chart.clear()` + `notMerge: true`
- `replaceMerge` 扩大到旧仓结构集合

**Step 2: Run test to verify it passes**

Run:

```bash
node --test tests/kline-slim-multi-period-chanlun.test.mjs
```

Expected:

- PASS

**Step 3: Run adjacent frontend tests**

Run:

```bash
node --test tests/kline-slim-default-symbol.test.mjs tests/kline-slim-sidebar.test.mjs tests/kline-slim-chanlun-structure.test.mjs tests/kline-slim-multi-period-chanlun.test.mjs
```

Expected:

- PASS

**Step 4: Commit**

```bash
git add morningglory/fqwebui/src/views/js/draw-slim.js morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "fix: 清理 kline slim 中枢切换残影"
```

### Task 4: 完整验证

**Files:**
- Modify: none
- Test: `morningglory/fqwebui/tests/*.mjs`

**Step 1: Run frontend verification**

Run:

```bash
node --test tests/kline-slim-default-symbol.test.mjs tests/kline-slim-sidebar.test.mjs tests/kline-slim-chanlun-structure.test.mjs tests/kline-slim-multi-period-chanlun.test.mjs
```

Expected:

- PASS

**Step 2: Run whitespace / diff checks**

Run:

```bash
git diff --check
git status --short --branch
```

Expected:

- `git diff --check` clean
- working tree only contains intended changes

**Step 3: Commit final verification state**

如果前面任务已分提交，此步不新增 commit，只记录验证结果。
