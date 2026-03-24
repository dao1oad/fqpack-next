# Kline Slim Price Panel Compact Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 精简 `/kline-slim` 的价格层级与标的设置浮层，同时把 buy lot 止损行的展示统一到当前系统 `avg_price + 仓位市值真值 + 剩余百分比` 口径。

**Architecture:** 保持现有 `subject-management detail -> subjectManagement.mjs / kline-slim-subject-panel.mjs -> KlineSlim.vue` 分层不变。后端仅为 detail 透传当前系统 `avg_price`，前端 view model 统一生成 buy lot 摘要字符串；价格层级面板只做模板裁剪，不改保存动作与接口编排。

**Tech Stack:** Python, Vue 3, Node test, pytest

---

### Task 1: 锁定后端 detail 的 `avg_price` 真值

**Files:**
- Modify: `freshquant/tests/test_subject_management_service.py`
- Modify: `freshquant/subject_management/dashboard_service.py`

**Step 1: Write the failing test**

给 `get_detail()` 补断言：当 position loader 返回 `avg_price` 时，`runtime_summary.avg_price` 会出现在 detail 中。

**Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest -q freshquant/tests/test_subject_management_service.py`

**Step 3: Write minimal implementation**

在 `SubjectManagementDashboardService.get_detail()` 和相关 summary 归一里透传 `avg_price`。

**Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest -q freshquant/tests/test_subject_management_service.py`

### Task 2: 锁定 buy lot 新摘要与价格层级精简 UI

**Files:**
- Modify: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- Modify: `morningglory/fqwebui/src/views/js/kline-slim-subject-panel.test.mjs`
- Modify: `morningglory/fqwebui/src/views/klineSlim.test.mjs`
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`
- Modify: `morningglory/fqwebui/src/views/subjectManagement.mjs`
- Modify: `morningglory/fqwebui/src/views/js/kline-slim-subject-panel.mjs`

**Step 1: Write the failing tests**

- 价格层级不再包含 `待机 / 布防 / 仅展示 / 保存 Guardian / 保存止盈 / footer 说明文案`
- `已布防` 改成 `已启用`
- 标的设置头部按钮文案改成 `保存`
- buy lot 元信息改成 `买入时间 + 均价(3 位) + 市值 + 剩余百分比(2 位)`

**Step 2: Run tests to verify they fail**

Run: `node --test src/views/klineSlim.test.mjs src/views/js/kline-slim-subject-panel.test.mjs src/views/subjectManagement.test.mjs`

**Step 3: Write minimal implementation**

更新 detail 归一和模板，保留价格输入与 `开/关` 开关，不改动作函数。

**Step 4: Run tests to verify they pass**

Run: `node --test src/views/klineSlim.test.mjs src/views/js/kline-slim-subject-panel.test.mjs src/views/subjectManagement.test.mjs`

### Task 3: 同步当前文档与完整验证

**Files:**
- Modify: `docs/current/modules/kline-webui.md`

**Step 1: Update docs**

补充价格层级头部只保留 `保存并激活`、buy lot 行展示口径改成 `avg_price + 仓位市值真值 + 剩余百分比`。

**Step 2: Run verification**

Run:
- `node --test src/views/klineSlim.test.mjs src/views/KlineSlim.layout.test.mjs src/views/js/kline-slim-subject-panel.test.mjs src/views/js/kline-slim-sidebar.test.mjs src/views/subjectManagement.test.mjs`
- `.venv\Scripts\python.exe -m pytest -q freshquant/tests/test_subject_management_service.py`
- `npm run build`
- `py -3.12 script/ci/check_current_docs.py`
- `powershell -ExecutionPolicy Bypass -File script/fq_local_preflight.ps1 -Mode Ensure`
