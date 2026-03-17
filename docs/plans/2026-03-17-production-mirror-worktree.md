# Production Mirror Worktree Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把正式 deploy mirror 从开发根目录切换为独立本机 worktree，并修复 production runner 的 `safe.directory` 阻断。

**Architecture:** `deploy-production.yml` 改为使用固定 canonical repo root + 独立 mirror worktree。mirror 通过 `deploy-production-main` 本地分支 fast-forward 到 `origin/main`，同步脚本负责 `safe.directory`、remote/main 校验和 fast-forward 语义。

**Tech Stack:** GitHub Actions, PowerShell, Python 3.12, pytest, git worktree

---

### Task 1: 为独立 mirror worktree 写失败测试

**Files:**
- Modify: `freshquant/tests/test_sync_local_deploy_mirror.py`
- Modify: `freshquant/tests/test_deploy_build_cache_policy.py`
- Test: `freshquant/tests/test_check_current_docs.py`

**Step 1: 写失败测试**

- 给 mirror 同步脚本新增一个测试：
  - `remote_branch="main"`
  - `checkout_branch="deploy-production-main"`
  - 断言同步后 checkout 分支为 `deploy-production-main`
- 给 workflow 契约测试新增断言：
  - `FQ_DEPLOY_MIRROR_ROOT` 指向 `.worktrees\\main-deploy-production`
  - 出现 `FQ_DEPLOY_CANONICAL_REPO_ROOT`
  - 出现 `safe.directory`
- 给文档测试新增断言：
  - 当前部署文档提到 `.worktrees\\main-deploy-production`

**Step 2: 运行测试确认失败**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_sync_local_deploy_mirror.py freshquant/tests/test_deploy_build_cache_policy.py freshquant/tests/test_check_current_docs.py
```

Expected:

- 至少一条断言失败，证明当前实现仍写死旧 mirror 路径和旧分支语义

### Task 2: 实现 mirror 同步脚本的新分支与 safe.directory 语义

**Files:**
- Modify: `script/ci/sync_local_deploy_mirror.py`
- Modify: `freshquant/tests/test_sync_local_deploy_mirror.py`

**Step 1: 最小实现**

- 增加 `ensure_safe_directory(repo_root)`
- 增加 `checkout_branch` 参数
- `fetch` 保持对 `origin/main` 语义
- `checkout` / `merge` 改为使用 `checkout_branch`

**Step 2: 运行目标测试**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_sync_local_deploy_mirror.py
```

Expected:

- 全部通过

### Task 3: 更新正式 workflow 为 canonical repo + 独立 mirror worktree

**Files:**
- Modify: `.github/workflows/deploy-production.yml`
- Modify: `freshquant/tests/test_deploy_build_cache_policy.py`

**Step 1: 写最小变更**

- 新增：
  - `FQ_DEPLOY_CANONICAL_REPO_ROOT`
  - 新的 `FQ_DEPLOY_MIRROR_ROOT`
  - mirror 本地分支变量，例如 `FQ_DEPLOY_MIRROR_BRANCH=deploy-production-main`
- 在 sync step 中：
  - 为 canonical root 和 mirror root 添加 `safe.directory`
  - 若 mirror 不存在，执行 `git worktree add`
  - 调用 `sync_local_deploy_mirror.py` 时传 `--checkout-branch`

**Step 2: 运行 workflow 契约测试**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_deploy_build_cache_policy.py
```

Expected:

- 全部通过

### Task 4: 同步当前文档真值

**Files:**
- Modify: `docs/current/deployment.md`
- Modify: `docs/current/runtime.md`
- Modify: `freshquant/tests/test_check_current_docs.py`

**Step 1: 更新文档**

- 把正式 mirror 路径改成 `.worktrees\\main-deploy-production`
- 说明 canonical repo root 仅用于 mirror 管理
- 明确 production runner 需要 `safe.directory`

**Step 2: 运行文档测试**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_check_current_docs.py
```

Expected:

- 全部通过

### Task 5: 完整回归验证

**Files:**
- Verify only

**Step 1: 运行完整相关测试**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_freshquant_deploy_plan.py freshquant/tests/test_docker_parallel_compose.py freshquant/tests/test_deploy_build_cache_policy.py freshquant/tests/test_docker_image_publish_plan.py freshquant/tests/test_formal_deploy_orchestrator.py freshquant/tests/test_sync_local_deploy_mirror.py freshquant/tests/test_check_current_docs.py
```

Expected:

- 全部通过

**Step 2: 运行本地 pre-commit**

Run:

```powershell
py -3.12 -m uv tool run pre-commit run --show-diff-on-failure --color=always --from-ref origin/main --to-ref HEAD
```

Expected:

- 全部通过

### Task 6: 提交、PR、merge、验证 production deploy

**Files:**
- Verify GitHub state

**Step 1: 提交**

```powershell
git add .github/workflows/deploy-production.yml script/ci/sync_local_deploy_mirror.py docs/current/deployment.md docs/current/runtime.md freshquant/tests/test_sync_local_deploy_mirror.py freshquant/tests/test_deploy_build_cache_policy.py freshquant/tests/test_check_current_docs.py docs/plans/2026-03-17-production-mirror-worktree-design.md docs/plans/2026-03-17-production-mirror-worktree.md
git commit -m "fix: isolate production deploy mirror worktree"
```

**Step 2: 推送和创建 PR**

```powershell
git push -u origin codex/fix-production-deploy-mirror
gh pr create --base main --head codex/fix-production-deploy-mirror --title "修复正式 deploy mirror worktree"
```

**Step 3: 合并并验证**

- 等 CI 通过后 merge
- 检查 `Deploy Production` 是否基于新 mirror 路径启动
- 记录成功或新的失败根因

