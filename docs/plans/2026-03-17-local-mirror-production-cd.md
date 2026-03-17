# Local Mirror Production CD Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把正式自动部署改为“本机 deploy mirror + 本机构建部署”，取消生产机在线下载源码归档和把 Docker Images 作为正式 deploy 前置。

**Architecture:** `deploy-production.yml` 改为 `push main` 触发，在 production runner 上先同步 `D:\fqpack\freshquant-2026.2.23` 的 `main` 分支，再在该 mirror 目录中执行 `uv sync` 和 `run_formal_deploy.py`。正式 deploy 直接使用 mirror 的 git 工作树计算增量 changed paths，并在本机完成 Docker/宿主机构建部署。

**Tech Stack:** GitHub Actions, PowerShell, Python 3.12, git, Docker Compose, pytest

---

### Task 1: 锁定新的 workflow 契约

**Files:**
- Modify: `freshquant/tests/test_deploy_build_cache_policy.py`

**Step 1: Write the failing test**

- 断言 `deploy-production.yml`：
  - 使用 `push` 监听 `main`
  - 不再包含 `workflow_run`
  - 不再包含 zipball 下载逻辑
  - 使用固定 mirror 路径 `D:\fqpack\freshquant-2026.2.23`
  - 调用新的 mirror 同步脚本

**Step 2: Run test to verify it fails**

Run:
```powershell
py -3.12 -m pytest -q freshquant/tests/test_deploy_build_cache_policy.py
```

Expected: workflow 契约测试失败。

**Step 3: Commit**

```powershell
git add freshquant/tests/test_deploy_build_cache_policy.py
git commit -m "test: lock local mirror production deploy workflow"
```

### Task 2: 实现 mirror 同步脚本

**Files:**
- Create: `script/ci/sync_local_deploy_mirror.py`
- Create: `freshquant/tests/test_sync_local_deploy_mirror.py`

**Step 1: Write the failing tests**

- clean repo + fast-forward 成功
- dirty repo 失败
- `origin/main` 不等于目标 SHA 失败
- fast-forward 失败

**Step 2: Run tests to verify they fail**

Run:
```powershell
py -3.12 -m pytest -q freshquant/tests/test_sync_local_deploy_mirror.py
```

Expected: 缺少脚本或行为不满足导致失败。

**Step 3: Write minimal implementation**

- 参数：
  - `--repo-root`
  - `--target-sha`
- 行为：
  - 校验 git repo / clean worktree
  - `git fetch origin main`
  - 校验 `origin/main` == `target-sha`
  - `git checkout main`
  - `git merge --ff-only origin/main`
  - 校验 `HEAD` == `target-sha`

**Step 4: Run tests to verify they pass**

Run:
```powershell
py -3.12 -m pytest -q freshquant/tests/test_sync_local_deploy_mirror.py
```

Expected: PASS

**Step 5: Commit**

```powershell
git add script/ci/sync_local_deploy_mirror.py freshquant/tests/test_sync_local_deploy_mirror.py
git commit -m "feat: add local deploy mirror sync script"
```

### Task 3: 改造 deploy workflow

**Files:**
- Modify: `.github/workflows/deploy-production.yml`

**Step 1: Implement workflow changes**

- `on: push` 监听 `main`
- 删除 `workflow_run` 条件判断
- 用固定 repo root：`D:\fqpack\freshquant-2026.2.23`
- 先调用 `sync_local_deploy_mirror.py`
- 再在 mirror 目录执行：
  - `py -3.12 -m uv sync --frozen`
  - `py -3.12 script/ci/run_formal_deploy.py --repo-root <mirror> --head-sha ${{ github.sha }}`

**Step 2: Run workflow contract tests**

Run:
```powershell
py -3.12 -m pytest -q freshquant/tests/test_deploy_build_cache_policy.py
```

Expected: PASS

**Step 3: Commit**

```powershell
git add .github/workflows/deploy-production.yml freshquant/tests/test_deploy_build_cache_policy.py
git commit -m "feat: switch production deploy to local mirror workflow"
```

### Task 4: 调整 orchestrator 测试与兼容逻辑

**Files:**
- Modify: `freshquant/tests/test_formal_deploy_orchestrator.py`
- Modify: `script/ci/run_formal_deploy.py`

**Step 1: Write failing tests**

- 当 `repo_root` 是本地 git repo 时，优先使用本地 git diff
- 正式 summary / result 保持不变
- 不再要求 workflow 传入 zipball/compare API 才能增量 deploy

**Step 2: Run tests to verify they fail**

Run:
```powershell
py -3.12 -m pytest -q freshquant/tests/test_formal_deploy_orchestrator.py
```

**Step 3: Apply minimal implementation if needed**

- 只保留必要兼容
- 不引入额外在线下载逻辑

**Step 4: Run tests to verify they pass**

Run:
```powershell
py -3.12 -m pytest -q freshquant/tests/test_formal_deploy_orchestrator.py
```

**Step 5: Commit**

```powershell
git add script/ci/run_formal_deploy.py freshquant/tests/test_formal_deploy_orchestrator.py
git commit -m "refactor: align formal deploy orchestrator with local mirror flow"
```

### Task 5: 更新当前文档

**Files:**
- Modify: `docs/current/deployment.md`
- Modify: `docs/current/runtime.md`
- Test: `freshquant/tests/test_check_current_docs.py`

**Step 1: Update docs**

- 正式 deploy mirror 是 `D:\fqpack\freshquant-2026.2.23`
- 正式 deploy 由 push `main` 触发
- 生产机不再下载 zipball，不再以 Docker Images 为正式前置
- 正式 deploy 在 mirror 目录本地构建和部署

**Step 2: Run docs tests**

Run:
```powershell
py -3.12 -m pytest -q freshquant/tests/test_deploy_build_cache_policy.py freshquant/tests/test_check_current_docs.py
```

Expected: PASS

**Step 3: Commit**

```powershell
git add docs/current/deployment.md docs/current/runtime.md freshquant/tests/test_check_current_docs.py freshquant/tests/test_deploy_build_cache_policy.py
git commit -m "docs: document local mirror production cd"
```

### Task 6: 全量验证

**Files:**
- Verify only

**Step 1: Run deploy-related suite**

```powershell
py -3.12 -m pytest -q freshquant/tests/test_freshquant_deploy_plan.py freshquant/tests/test_docker_parallel_compose.py freshquant/tests/test_deploy_build_cache_policy.py freshquant/tests/test_docker_image_publish_plan.py freshquant/tests/test_formal_deploy_orchestrator.py freshquant/tests/test_sync_local_deploy_mirror.py freshquant/tests/test_check_current_docs.py
```

Expected: 全绿

**Step 2: Inspect diff**

```powershell
git diff --stat HEAD~5..HEAD
git status --short --branch
```

**Step 3: Commit any final fixups**

```powershell
git add <final files>
git commit -m "chore: finalize local mirror production cd"
```

**Step 4: Push and open PR**

```powershell
git push -u origin <branch>
gh pr create --base main --head <branch> --title "切换正式环境到本机 mirror 构建部署"
```

