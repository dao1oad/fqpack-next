# Daily Screening Workspace Enhancement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为每日选股页面补齐共享工作区和条件提示能力，让交集结果可以直接沉淀到共享池子并让条件口径在界面上可解释。

**Architecture:** 前端直接复用 `/gantt/shouban30` 的共享工作区接口和 tab 构造逻辑；每日选股页面只新增“当前交集结果 -> pre_pools payload”适配层和“条件 -> 提示文案”元数据层。实现顺序严格遵守 TDD，先写失败测试，再做最小实现。

**Tech Stack:** Vue 3、Element Plus、Node test、现有 HTTP API 封装

---

### Task 1: 文档落地

**Files:**
- Create: `docs/plans/2026-03-19-daily-screening-workspace-enhancement-design.md`
- Create: `docs/plans/2026-03-19-daily-screening-workspace-enhancement.md`

**Step 1: 写设计文档**

记录：
- 工作区共享口径
- 交集结果作用范围
- 条件提示展示方式

**Step 2: 写实现计划**

把前端测试、实现、文档更新、验证拆成独立任务。

**Step 3: 提交文档**

Run: `git add docs/plans/2026-03-19-daily-screening-workspace-enhancement-design.md docs/plans/2026-03-19-daily-screening-workspace-enhancement.md`

**Step 4: Commit**

```bash
git commit -m "docs: add daily screening workspace enhancement plan"
```

### Task 2: 为每日选股纯逻辑层补失败测试

**Files:**
- Modify: `morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`
- Modify: `morningglory/fqwebui/src/views/dailyScreeningPage.mjs`

**Step 1: 写失败测试**

新增测试覆盖：
- 条件目录被规范化后包含条件提示元数据
- 当前结果行能构造出追加到 `pre_pools` 的 payload
- 共享工作区响应能映射为 `pre_pools / stock_pools` tabs

**Step 2: 运行测试确认失败**

Run: `node --test morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`
Expected: FAIL，因为新 helper 和新字段尚未实现

**Step 3: 写最小实现**

在 `dailyScreeningPage.mjs` 中新增：
- 条件提示元数据映射
- 当前交集结果到 `pre_pools` payload 的构造函数
- 工作区 tab 的适配 helper

**Step 4: 运行测试确认通过**

Run: `node --test morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs morningglory/fqwebui/src/views/dailyScreeningPage.mjs
git commit -m "test: cover daily screening workspace helpers"
```

### Task 3: 为每日选股页面补工作区 UI 与交互

**Files:**
- Modify: `morningglory/fqwebui/src/views/DailyScreening.vue`
- Modify: `morningglory/fqwebui/src/api/dailyScreeningApi.js`
- Modify: `morningglory/fqwebui/src/api/ganttShouban30.js`
- Reference: `morningglory/fqwebui/src/views/shouban30PoolWorkspace.mjs`

**Step 1: 写失败测试**

在现有前端测试入口中补充对以下行为的断言：
- 页面渲染工作台总说明
- 条件旁边出现提示入口
- 交集列表头部出现 `全部加入 pre_pools`
- 页面出现 `pre_pools / stock_pools` 工作区

**Step 2: 运行测试确认失败**

Run: `node --test morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`
Expected: FAIL，因为页面还未接入新 UI 状态

**Step 3: 写最小实现**

在 `DailyScreening.vue` 中：
- 引入共享工作区接口
- 加载并展示共享工作区
- 增加当前结果批量加入 `pre_pools`
- 增加工作区 tabs 和批量/行级操作
- 在条件按钮旁渲染提示图标
- 在工作台顶部渲染总说明

**Step 4: 运行测试确认通过**

Run: `node --test morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`
Expected: PASS

**Step 5: 做一次前端构建验证**

Run: `npm run build`
Workdir: `morningglory/fqwebui`
Expected: build 成功

**Step 6: Commit**

```bash
git add morningglory/fqwebui/src/views/DailyScreening.vue morningglory/fqwebui/src/api/dailyScreeningApi.js
git commit -m "feat: add shared workspace to daily screening"
```

### Task 4: 更新当前文档

**Files:**
- Modify: `docs/current/modules/daily-screening.md`
- Modify: `docs/current/interfaces.md`

**Step 1: 写文档变更**

补充：
- 每日选股页面包含共享工作区
- 条件提示说明来源与规则
- 复用 `/gantt/shouban30` 的工作区接口

**Step 2: 检查文档与代码一致**

核对当前 API、页面行为、工作区语义。

**Step 3: Commit**

```bash
git add docs/current/modules/daily-screening.md docs/current/interfaces.md
git commit -m "docs: document daily screening workspace"
```

### Task 5: 验证与集成

**Files:**
- No file changes required

**Step 1: 运行前端逻辑测试**

Run: `node --test morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`
Expected: PASS

**Step 2: 运行相关后端回归测试**

Run: `py -3.12 -m pytest freshquant/tests/test_daily_screening_routes.py freshquant/tests/test_daily_screening_service.py -q`
Expected: PASS

**Step 3: 运行前端构建**

Run: `npm run build`
Workdir: `morningglory/fqwebui`
Expected: PASS

**Step 4: 若 Docker 可用则部署**

Run: `./script/docker_parallel_compose.ps1 up -d --build fq_webui fq_apiserver fq_dagster_webserver fq_dagster_daemon`
Expected: 受影响服务更新成功

**Step 5: 健康检查**

Run:
- `Invoke-WebRequest http://127.0.0.1:18080 -UseBasicParsing`
- `Invoke-WebRequest http://127.0.0.1:15000/api/daily-screening/scopes/latest -UseBasicParsing`

Expected: `200`

**Step 6: Git 收口**

```bash
git status --short
git push origin codex/daily-screening-opt-20260318
```

**Step 7: 通过 PR 合并到 remote main**

使用非交互 git / gh 流程创建或更新 PR，等待检查通过后合并，不直接推送 `main`。
