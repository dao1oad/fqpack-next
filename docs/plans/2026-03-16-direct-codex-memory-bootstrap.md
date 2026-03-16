# Direct Codex Memory Bootstrap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让直接在 Codex app 中打开仓库的自由会话，在没有 `FQ_MEMORY_CONTEXT_PATH` 时也能按仓库规则自举 FreshQuant 记忆系统。

**Architecture:** 在 `freshquant.runtime.memory` 中新增可测试的 bootstrap helper，并提供一个仓库内正式脚本入口。`AGENTS.md` 与 `docs/current/**` 约束直开会话先执行该入口，再读取生成的 context pack。

**Tech Stack:** Python 3.12、Pytest、PowerShell、MongoDB、现有 `freshquant.runtime.memory` 模块

---

### Task 1: 设计直开会话 bootstrap 的失败测试

**Files:**
- Modify: `freshquant/tests/test_runtime_memory.py`
- Modify: `freshquant/tests/test_runtime_memory_docs.py`

**Step 1: Write the failing tests**

- 为 `issue_identifier` 推导规则增加测试：
  - workspace 目录名为 `GH-166` 时直接返回 `GH-166`
  - branch 名中包含 `GH-166` 时解析出 `GH-166`
  - 否则回退为 `LOCAL-<workspace-name>`
- 为 bootstrap helper 增加测试：
  - 会执行 refresh
  - 会编译 context pack
  - 返回 `context_pack_path`
- 为文档契约增加测试：
  - `AGENTS.md` 提到 bootstrap 脚本
  - `docs/current/runtime.md` / `interfaces.md` / `troubleshooting.md` 提到 bootstrap 脚本

**Step 2: Run tests to verify they fail**

Run:

```powershell
py -3.12 -m pytest freshquant/tests/test_runtime_memory.py freshquant/tests/test_runtime_memory_docs.py -q
```

Expected:
- 至少新增测试失败，提示缺少 bootstrap helper、脚本或文档约束。

### Task 2: 实现 bootstrap helper

**Files:**
- Create: `freshquant/runtime/memory/bootstrap.py`
- Modify: `freshquant/runtime/memory/__init__.py`

**Step 1: Write minimal implementation**

- 新增 `derive_issue_identifier(...)`
- 新增 `bootstrap_memory_context(...)`
- 复用现有 `refresh_memory()` 与 `compile_context_pack()`

**Step 2: Run focused tests**

Run:

```powershell
py -3.12 -m pytest freshquant/tests/test_runtime_memory.py -q
```

Expected:
- bootstrap 相关测试通过

### Task 3: 提供仓库内正式脚本入口

**Files:**
- Create: `runtime/memory/scripts/bootstrap_freshquant_memory.py`

**Step 1: Write the script**

- 支持 `--repo-root`
- 支持 `--service-root`
- 支持可选 `--issue-identifier`
- 支持可选 `--issue-state`
- 支持可选 `--role`
- 默认从 git 推导 branch / git status
- 输出 JSON

**Step 2: Add script smoke coverage**

- 在 `freshquant/tests/test_runtime_memory.py` 增加脚本 smoke test

**Step 3: Run focused tests**

Run:

```powershell
py -3.12 -m pytest freshquant/tests/test_runtime_memory.py -q
```

Expected:
- 新增脚本 smoke test 通过

### Task 4: 更新 AGENTS 与正式文档

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/current/runtime.md`
- Modify: `docs/current/interfaces.md`
- Modify: `docs/current/troubleshooting.md`

**Step 1: Update docs minimally**

- 在 `AGENTS.md` 里增加自由 Codex 会话 memory bootstrap 规则
- 在 `docs/current/runtime.md` 里增加直开会话接入说明
- 在 `docs/current/interfaces.md` 里增加 bootstrap 脚本入口
- 在 `docs/current/troubleshooting.md` 里增加直开会话排障方式

**Step 2: Run doc contract tests**

Run:

```powershell
py -3.12 -m pytest freshquant/tests/test_runtime_memory_docs.py -q
```

Expected:
- 所有文档契约测试通过

### Task 5: 做端到端 smoke 验证

**Files:**
- No code changes

**Step 1: Run bootstrap smoke**

Run:

```powershell
$serviceRoot = Join-Path $env:TEMP ('fq-direct-memory-' + [guid]::NewGuid().ToString())
py -3.12 runtime/memory/scripts/bootstrap_freshquant_memory.py --repo-root . --service-root $serviceRoot
```

Expected:
- 输出 JSON
- `context_pack_path` 存在

**Step 2: Verify generated pack**

Run:

```powershell
Get-Content <context_pack_path>
```

Expected:
- 能看到 cold memory 与 task snapshot

### Task 6: Final regression verification

**Files:**
- No code changes

**Step 1: Run final relevant suite**

Run:

```powershell
py -3.12 -m pytest freshquant/tests/test_runtime_memory.py freshquant/tests/test_runtime_memory_docs.py freshquant/tests/test_symphony_memory_contract.py -q
```

Expected:
- 全部通过
