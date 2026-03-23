# Formal Production Deploy Entrypoint Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 FreshQuant 正式 production deploy 收口成单一脚本入口，去掉 workflow 对 skill 和宿主机全局 `py -3.12` / `uv` 状态的隐式依赖。

**Architecture:** 新增 `script/ci/run_production_deploy.ps1` 作为正式 deploy 唯一入口，统一负责远端 `main` 真值校验、deploy mirror 同步、runner Python/uv 自愈、mirror `.venv` 同步和 formal deploy 调用。`run_formal_deploy.py` 改为使用当前解释器执行 health check，这样只要入口脚本改成 mirror `.venv\Scripts\python.exe` 启动，后续 Python 子命令也会自动落到 deploy mirror 环境。

**Tech Stack:** PowerShell 7 / Windows PowerShell, Python 3.12, `uv`, GitHub Actions, pytest

---

### Task 1: 锁定 formal deploy 解释器行为

**Files:**
- Modify: `freshquant/tests/test_formal_deploy_orchestrator.py`
- Modify: `script/ci/run_formal_deploy.py`

**Step 1: Write the failing test**

在 `freshquant/tests/test_formal_deploy_orchestrator.py` 增加一个用例，断言 orchestrator 构造 health check 命令时使用传入的 Python 可执行文件，而不是硬编码 `py -3.12`。

**Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest freshquant/tests/test_formal_deploy_orchestrator.py -q`
Expected: FAIL，提示 health check 命令仍然是 `py -3.12`

**Step 3: Write minimal implementation**

在 `script/ci/run_formal_deploy.py`：
- 给 `build_health_commands()` 增加 `python_executable` 参数
- 给 `run_formal_deploy()` 增加 `python_executable` 参数，默认使用 `sys.executable`
- `main()` 调用时显式传入 `sys.executable`

**Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest freshquant/tests/test_formal_deploy_orchestrator.py -q`
Expected: PASS

### Task 2: 为正式 deploy workflow 建立契约测试

**Files:**
- Create: `freshquant/tests/test_deploy_production_workflow.py`
- Modify: `.github/workflows/deploy-production.yml`

**Step 1: Write the failing test**

新增 workflow 契约测试，断言：
- workflow 调用 `script/ci/run_production_deploy.ps1`
- workflow 不再直接包含 `py -3.12 -m uv sync --frozen`
- workflow 不再直接包含裸 `run_formal_deploy.py`

**Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest freshquant/tests/test_deploy_production_workflow.py -q`
Expected: FAIL，因为 workflow 目前还是直接跑这些命令

**Step 3: Write minimal implementation**

先不改 workflow，只创建测试文件并锁定断言。

**Step 4: Run test to verify it fails cleanly**

Run: `.venv\Scripts\python.exe -m pytest freshquant/tests/test_deploy_production_workflow.py -q`
Expected: FAIL，且失败原因就是 workflow 还没切到单入口脚本

### Task 3: 新增正式 deploy 单入口脚本

**Files:**
- Create: `script/ci/run_production_deploy.ps1`
- Modify: `.github/workflows/deploy-production.yml`
- Test: `freshquant/tests/test_deploy_production_workflow.py`

**Step 1: Write the failing integration expectation**

沿用 Task 2 的失败测试，不再新增第二套测试。

**Step 2: Implement the PowerShell entrypoint**

在 `script/ci/run_production_deploy.ps1` 实现：
- 参数：`CanonicalRoot`、`MirrorRoot`、`MirrorBranch`、`TargetSha`、`RunUrl`、`GitHubRepository`
- 校验 `TargetSha` 是当前远端 `origin/main`
- 保证 canonical repo / mirror repo 都加入 `safe.directory`
- 调用 `script/ci/sync_local_deploy_mirror.py`
- 解析一个可用的 Python 3.12
- 若 `python -m uv` 不可用，则执行 `python -m pip install uv --break-system-packages`
- 在 mirror 下执行 `python -m uv sync --frozen`
- 使用 `mirror\.venv\Scripts\python.exe` 调 `script/ci/run_formal_deploy.py`

**Step 3: Switch workflow to the single entrypoint**

把 `.github/workflows/deploy-production.yml` 改成只保留：
- main tip freshness 校验
- 调 `script/ci/run_production_deploy.ps1`

**Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest freshquant/tests/test_deploy_production_workflow.py -q`
Expected: PASS

### Task 4: 补 runner Python/uv 自愈逻辑

**Files:**
- Modify: `script/ci/run_production_deploy.ps1`

**Step 1: Implement conservative self-heal**

在 PowerShell 入口里补函数：
- 优先尝试 `py -3.12`
- 若 launcher 指向失效路径，则回退到 `HKCU:\Software\Python\PythonCore\3.12\InstallPath` 或 `HKCU:\Software\Python\Astral\CPython3.12.*`
- 若拿到的是 per-user Python，则补写 `HKCU:\Software\Python\PythonCore\3.12\InstallPath`
- 再验证 `python -m uv --version`

**Step 2: Run focused regression tests**

Run: `.venv\Scripts\python.exe -m pytest freshquant/tests/test_formal_deploy_orchestrator.py freshquant/tests/test_deploy_production_workflow.py -q`
Expected: PASS

### Task 5: 更新当前系统文档

**Files:**
- Modify: `docs/current/deployment.md`
- Modify: `docs/current/runtime.md`

**Step 1: Update docs**

记录当前正式 deploy 真值变更：
- 正式 deploy 单入口是 `script/ci/run_production_deploy.ps1`
- workflow 不再手工展开 mirror sync / uv sync / formal deploy
- formal deploy 的 Python 子命令以 mirror `.venv` 为真值

**Step 2: Verify docs reflect implementation**

Run: `.venv\Scripts\python.exe -m pytest freshquant/tests/test_deploy_production_workflow.py -q`
Expected: PASS

### Task 6: 全量验证

**Files:**
- Verify only

**Step 1: Run targeted suite**

Run: `.venv\Scripts\python.exe -m pytest freshquant/tests/test_formal_deploy_orchestrator.py freshquant/tests/test_sync_local_deploy_mirror.py freshquant/tests/test_deploy_production_workflow.py -q`
Expected: PASS

**Step 2: Run contract check on workflow text**

Run: `.venv\Scripts\python.exe -m pytest freshquant/tests/test_ci_workflow_efficiency.py freshquant/tests/test_deploy_production_workflow.py -q`
Expected: PASS

**Step 3: Manual smoke of new entrypoint help**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File script/ci/run_production_deploy.ps1 -Help`
Expected: 显示参数帮助并成功退出

**Step 4: Commit**

```bash
git add script/ci/run_production_deploy.ps1 script/ci/run_formal_deploy.py .github/workflows/deploy-production.yml freshquant/tests/test_formal_deploy_orchestrator.py freshquant/tests/test_deploy_production_workflow.py docs/current/deployment.md docs/current/runtime.md docs/plans/2026-03-23-formal-deploy-entrypoint.md
git commit -m "feat: unify production deploy entrypoint"
```
