# Runtime Observability Fast Locate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 `/runtime-observability` 的异常数字和组件异常摘要可直接跳转到对应异常 Trace、异常 Event 和异常步骤。

**Architecture:** 保持现有 API 与三栏布局不变，只在前端增加本地异常聚焦状态、异常步骤导航和可点击入口。Trace 层增加“按异常组件聚焦”过滤，步骤层增加“异常/慢点跳转”，并复用现有 `selectedTrace`、`selectedStep`、`selectedEvent` 同步机制。

**Tech Stack:** Vue 3 `script setup`、Element Plus、Node test、纯前端辅助函数 `runtimeObservability.mjs`

---

### Task 1: 写失败用例覆盖异常聚焦与步骤导航

**Files:**
- Modify: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`
- Test: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: 为 Trace 异常组件聚焦写失败测试**

新增测试覆盖：

- 只保留指定组件发生异常的 Trace
- 不把仅经过该组件但未在该组件异常的 Trace 算进去

**Step 2: 为步骤异常导航写失败测试**

新增测试覆盖：

- `first` 返回首个异常步骤
- `previous` / `next` 基于当前步骤跳转
- `slowest` 返回最长耗时步骤

**Step 3: 为模板入口写失败测试**

新增源码断言覆盖：

- 顶部摘要区异常按钮
- 组件卡片异常链路/异常节点按钮
- 步骤区异常导航按钮

**Step 4: 跑测试确认失败**

Run: `node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs`

Expected: 新增用例失败，提示缺少新的 helper 或模板结构。

### Task 2: 实现前端 helper 与视图交互

**Files:**
- Modify: `morningglory/fqwebui/src/views/runtimeObservability.mjs`
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`

**Step 1: 在 helper 中实现异常聚焦与导航函数**

增加：

- 指定组件异常 Trace 过滤 helper
- 异常步骤/最慢步骤选择 helper

**Step 2: 在 Vue 状态中加入 Trace 异常聚焦**

增加本地状态并接入：

- 顶部摘要点击
- 组件异常链路点击
- 清空 filter chip

**Step 3: 把异常数字改成可点击入口**

修改：

- 顶部 `异常链路`
- 顶部 `异常节点`
- 组件卡片中的异常链路/异常节点

**Step 4: 在步骤区加入导航条和自动滚动**

修改：

- `首个异常`
- `上一个异常`
- `下一个异常`
- `最慢节点`
- 选中步骤滚动入可视区

### Task 3: 重新跑测试并收口文档

**Files:**
- Modify: `docs/current/modules/runtime-observability.md`
- Test: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: 跑前端测试**

Run: `node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs`

Expected: PASS

**Step 2: 同步模块文档**

补充 `/runtime-observability` 的快速定位交互事实：

- 顶部异常摘要可直接跳转
- 组件卡片异常摘要可直接跳转
- Trace 步骤区支持异常导航

**Step 3: 再次跑测试确认**

Run: `node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs`

Expected: PASS
