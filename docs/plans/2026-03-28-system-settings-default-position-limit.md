# System Settings Default Position Limit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 `/system-settings -> 仓位门禁` 直接显示并编辑当前 `pm_configs.thresholds.single_symbol_position_limit`，并把页面与文档文案统一为“单标的默认持仓上限”。

**Architecture:** 继续复用现有 `/api/system-config/dashboard` 与 `/api/system-config/settings` 真值链路，不新增新的配置源或页面边界。实现只收紧后端 section 元数据、前端显示语义与测试口径，同时同步 `docs/current` 文案，保持 `/system-settings` 与 `/position-management` 读取同一系统级默认值。

**Tech Stack:** Python, pytest, Vue 3, Element Plus, node:test, Markdown

---

## 执行前提

- 必须在基于最新 `origin/main` 的干净 worktree 中执行，不要在当前脏工作区直接编码
- 继续遵守 TDD：先写失败测试，再做最小实现
- 每个任务结束后单独提交，避免把文档、前端、后端混成一个大提交

### Task 1: 锁定后端“默认持仓上限”契约

**Files:**
- Modify: `freshquant/tests/test_system_config_service.py`
- Modify: `freshquant/system_config_service.py`

**Step 1: Write the failing test**

在 `freshquant/tests/test_system_config_service.py` 里补一个精确断言，锁定 `position_management.single_symbol_position_limit` 的展示标签和现有真值。

```python
section = dashboard["settings"]["sections"][-1]
limit_item = next(
    item
    for item in section["items"]
    if item["key"] == "position_management.single_symbol_position_limit"
)

assert limit_item["label"] == "单标的默认持仓上限"
assert dashboard["settings"]["values"]["position_management"]["single_symbol_position_limit"] == 880000.0
```

**Step 2: Run test to verify it fails**

Run: `D:\\fqpack\\freshquant-2026.2.23\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_system_config_service.py -q`

Expected: FAIL，提示当前 label 仍是 `单标的实时仓位上限`

**Step 3: Write minimal implementation**

在 `freshquant/system_config_service.py` 的 `SETTINGS_SECTION_META["position_management"]["items"]` 中，把：

```python
("single_symbol_position_limit", "单标的实时仓位上限")
```

改成：

```python
("single_symbol_position_limit", "单标的默认持仓上限")
```

不要修改接口结构、字段名或保存逻辑。

**Step 4: Run test to verify it passes**

Run: `D:\\fqpack\\freshquant-2026.2.23\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_system_config_service.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/tests/test_system_config_service.py freshquant/system_config_service.py
git commit -m "fix: clarify default position limit label"
```

### Task 2: 锁定前端“当前值直接可改”显示语义

**Files:**
- Modify: `morningglory/fqwebui/src/views/systemSettings.test.mjs`
- Modify: `morningglory/fqwebui/src/views/systemSettings.mjs`
- Modify: `morningglory/fqwebui/src/views/SystemSettings.vue`

**Step 1: Write the failing test**

在 `morningglory/fqwebui/src/views/systemSettings.test.mjs` 中补一个针对仓位门禁行的测试，锁定三件事：

- 行标签为 `单标的默认持仓上限`
- 当前值来自 payload 中的 `600000`
- 编辑器仍然是 number editor

```javascript
const sections = buildSettingsLedgerSections(payload, {
  currentValues: payload.settings.values,
  baselineValues: payload.settings.values,
})
const rows = flattenLedgerRows(sections)
const limitRow = rows.find((row) => row.key === 'position_management.single_symbol_position_limit')

assert.equal(limitRow.label, '单标的默认持仓上限')
assert.equal(limitRow.value_label, '600,000')
assert.equal(limitRow.editor.type, 'number')
```

如果你打算顺手加弱提示文案，再补一个静态断言检查 `SystemSettings.vue` 中出现“未为某个标的单独设置上限时”的提示文本。

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/systemSettings.test.mjs`

Expected: FAIL，提示当前行标签仍是 `单标的实时仓位上限`

**Step 3: Write minimal implementation**

实现时只做最小改动：

- 让前端消费后端新 label
- 保持 `position_management.single_symbol_position_limit` 的 number editor 配置不变
- 保持 `SystemSettings.vue` 通过 `syncFormsFromDashboard()` 把 payload 当前值灌进 `settingsForm`

如果需要补充弱提示，只给这一行增加不影响布局的辅助文案，不改变保存入口和行结构。

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/systemSettings.test.mjs`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/systemSettings.test.mjs morningglory/fqwebui/src/views/systemSettings.mjs morningglory/fqwebui/src/views/SystemSettings.vue
git commit -m "fix: expose default position limit in system settings"
```

### Task 3: 同步当前文档口径

**Files:**
- Modify: `docs/current/configuration.md`
- Modify: `docs/current/modules/position-management.md`

**Step 1: Update the docs**

把当前文档里描述 `single_symbol_position_limit` 的位置统一成“单标的默认持仓上限”口径，并明确：

- 该值属于系统级默认值
- 在 `/system-settings -> 仓位门禁` 中直接编辑
- 标的级 override 仍然在 `/position-management` 等入口维护

建议把类似下面的文案统一替换：

```md
- 单标的实时仓位上限默认约 `800000`
```

改成：

```md
- 单标的默认持仓上限默认约 `800000`
```

**Step 2: Review doc diffs**

Run: `git diff -- docs/current/configuration.md docs/current/modules/position-management.md`

Expected: 只出现术语收敛和页面边界说明，没有引入新的配置边界

**Step 3: Commit**

```bash
git add docs/current/configuration.md docs/current/modules/position-management.md
git commit -m "docs: align default position limit wording"
```

### Task 4: 做最终回归验证并整理交付

**Files:**
- Verify only: `freshquant/tests/test_system_config_service.py`
- Verify only: `morningglory/fqwebui/src/views/systemSettings.test.mjs`
- Verify only: `morningglory/fqwebui/src/views/SystemSettings.vue`
- Verify only: `docs/current/configuration.md`
- Verify only: `docs/current/modules/position-management.md`

**Step 1: Run the backend targeted test suite**

Run: `D:\\fqpack\\freshquant-2026.2.23\\.venv\\Scripts\\python.exe -m pytest freshquant/tests/test_system_config_service.py freshquant/tests/test_system_settings.py -q`

Expected: PASS

**Step 2: Run the frontend targeted test suite**

Run: `node --test morningglory/fqwebui/src/views/systemSettings.test.mjs`

Expected: PASS

**Step 3: Run the frontend build**

Run:

```bash
cd morningglory/fqwebui
npm run build
```

Expected: build 成功；如仍有既有大 chunk warning，只记录，不作为本任务失败条件

**Step 4: Inspect the final diff**

Run: `git diff --stat origin/main...HEAD`

Expected: 只包含本任务相关的后端元数据、前端页面/测试、文档更新

**Step 5: Commit**

```bash
git status --short
git add freshquant/system_config_service.py freshquant/tests/test_system_config_service.py morningglory/fqwebui/src/views/systemSettings.test.mjs morningglory/fqwebui/src/views/systemSettings.mjs morningglory/fqwebui/src/views/SystemSettings.vue docs/current/configuration.md docs/current/modules/position-management.md
git commit -m "fix: make default position limit editable in system settings"
```
