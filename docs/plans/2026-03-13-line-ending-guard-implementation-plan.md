# Line Ending Guard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 固化仓库换行规则，并在本地与 CI 中阻止 mixed line endings 回归。

**Architecture:** 使用 `.gitattributes` 作为换行真值，使用 `pre-commit` mixed-line-ending hook 作为自动门禁，再通过一个小型 pytest 验证关键策略存在。实现仅覆盖仓库规则与门禁，不做全仓批量重写。

**Tech Stack:** Git attributes, pre-commit, pytest

---

### Task 1: 写失败测试

**Files:**
- Create: `freshquant/tests/test_line_ending_policy.py`

**Step 1: Write the failing test**

断言 `.gitattributes` 包含关键 `eol` 规则，`.pre-commit-config.yaml` 包含 `mixed-line-ending` 且参数为 `--fix=no`。

**Step 2: Run test to verify it fails**

Run: `D:/fqpack/freshquant-2026.2.23/.venv/Scripts/python.exe -m pytest -q freshquant/tests/test_line_ending_policy.py`
Expected: FAIL

### Task 2: 补齐仓库规则

**Files:**
- Modify: `.gitattributes`
- Modify: `.pre-commit-config.yaml`

**Step 1: Add explicit line-ending rules**

为常见源码/文档类型声明 `LF`，为 `*.bat` / `*.cmd` 声明 `CRLF`。

**Step 2: Add mixed-line-ending guard**

新增：

```yaml
      - id: mixed-line-ending
        args: [--fix=no]
```

**Step 3: Run test to verify it passes**

Run: `D:/fqpack/freshquant-2026.2.23/.venv/Scripts/python.exe -m pytest -q freshquant/tests/test_line_ending_policy.py`
Expected: PASS

### Task 3: 同步当前文档

**Files:**
- Modify: `docs/current/configuration.md`

**Step 1: Add current fact**

补充仓库换行规则与 CI / pre-commit 门禁说明。

**Step 2: Verify docs**

Run: `rg -n "gitattributes|mixed-line-ending|换行" docs/current/configuration.md`
Expected: 命中新说明

### Task 4: 只验证本次变更文件

**Files:**
- Test: `.gitattributes`
- Test: `.pre-commit-config.yaml`
- Test: `docs/current/configuration.md`
- Test: `freshquant/tests/test_line_ending_policy.py`
- Test: `docs/plans/2026-03-13-line-ending-guard-design.md`
- Test: `docs/plans/2026-03-13-line-ending-guard-implementation-plan.md`

**Step 1: Run targeted pytest**

Run: `D:/fqpack/freshquant-2026.2.23/.venv/Scripts/python.exe -m pytest -q freshquant/tests/test_line_ending_policy.py`
Expected: PASS

**Step 2: Run targeted pre-commit hooks**

Run:

```bash
D:/fqpack/freshquant-2026.2.23/.venv/Scripts/python.exe -m pre_commit run mixed-line-ending --files .gitattributes .pre-commit-config.yaml docs/current/configuration.md freshquant/tests/test_line_ending_policy.py docs/plans/2026-03-13-line-ending-guard-design.md docs/plans/2026-03-13-line-ending-guard-implementation-plan.md
```

Expected: PASS

**Step 3: Commit**

```bash
git add .gitattributes .pre-commit-config.yaml docs/current/configuration.md docs/plans/2026-03-13-line-ending-guard-design.md docs/plans/2026-03-13-line-ending-guard-implementation-plan.md freshquant/tests/test_line_ending_policy.py
git commit -m "chore: guard mixed line endings in repository"
```
