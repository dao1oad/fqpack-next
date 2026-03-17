# 选择性 Docker 构建与正式环境自动部署 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现 main merge 后仅对受影响服务真正构建镜像，并在单一正式 Windows self-hosted runner 上自动完成正式部署、健康检查与 deploy state 更新。

**Architecture:** 新增镜像发布计划脚本把 4 个逻辑镜像判定为 `build` 或 `retag`，更新 `docker-images.yml` 为动态 matrix。新增正式 deploy orchestrator 和 `deploy-production.yml`，通过现有 `freshquant_deploy_plan.py`、`docker_parallel_compose.ps1`、`fqnext_host_runtime_ctl.ps1`、`freshquant_health_check.py` 与 post-deploy check 脚本自动收口正式发布。

**Tech Stack:** Python 3.12、Pytest、GitHub Actions、PowerShell、Docker Buildx、GHCR、Windows self-hosted runner

---

### Task 1: 为选择性镜像发布写失败测试

**Files:**
- Create: `freshquant/tests/test_docker_image_publish_plan.py`
- Modify: `freshquant/tests/test_deploy_build_cache_policy.py`

**Step 1: Write the failing tests**

```python
def test_rear_publish_plan_builds_when_shared_rear_inputs_change():
    plan = build_publish_plan(...)
    assert plan["rear"]["action"] == "build"


def test_web_publish_plan_retags_when_only_docs_change():
    plan = build_publish_plan(...)
    assert plan["webui"]["action"] == "retag"


def test_bootstrap_mode_builds_all_images():
    plan = build_publish_plan(...)
    assert {item["action"] for item in plan.values()} == {"build"}
```

再补一个 workflow 契约测试：

```python
def test_docker_images_workflow_uses_dynamic_publish_matrix():
    text = Path(".github/workflows/docker-images.yml").read_text(encoding="utf-8")
    assert "resolve-publish-plan" in text
    assert "fromJson(" in text
    assert "imagetools create" in text
```

**Step 2: Run tests to verify they fail**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_docker_image_publish_plan.py freshquant/tests/test_deploy_build_cache_policy.py -k "publish_plan or dynamic_publish_matrix"
```

Expected:
- 缺少 publish plan 脚本和 workflow 动态 matrix 相关断言失败

**Step 3: Commit**

```powershell
git add freshquant/tests/test_docker_image_publish_plan.py freshquant/tests/test_deploy_build_cache_policy.py
git commit -m "test: cover selective docker image publish planning"
```

### Task 2: 实现镜像发布计划脚本

**Files:**
- Create: `script/ci/resolve_docker_image_publish_plan.py`
- Test: `freshquant/tests/test_docker_image_publish_plan.py`

**Step 1: Write minimal implementation**

实现：

- `load_changed_paths(base_sha, head_sha)`
- `compute_publish_plan(changed_paths, bootstrap=False)`
- `build` / `retag` 判定
- JSON 输出，包含：
  - `images`
  - `bootstrap`
  - `head_sha`

共享 rear 输入尽量复用现有 `docker_parallel_compose.py` 中的 shared rear 输入前缀，避免重复口径漂移。

**Step 2: Run focused tests**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_docker_image_publish_plan.py
```

Expected:
- publish plan 测试通过

**Step 3: Commit**

```powershell
git add script/ci/resolve_docker_image_publish_plan.py freshquant/tests/test_docker_image_publish_plan.py
git commit -m "feat: add selective docker image publish plan"
```

### Task 3: 改造 docker-images workflow 为 build/retag 动态矩阵

**Files:**
- Modify: `.github/workflows/docker-images.yml`
- Modify: `freshquant/tests/test_deploy_build_cache_policy.py`

**Step 1: Write failing workflow contract assertions**

补断言：

```python
assert "python script/ci/resolve_docker_image_publish_plan.py" in text
assert "needs.resolve-publish-plan.outputs.matrix" in text
assert "matrix.action == 'build'" in text
assert "matrix.action == 'retag'" in text
```

**Step 2: Implement minimal workflow changes**

新增 job：

- `resolve-publish-plan`
  - 输出动态 matrix

更新 `publish` job：

- `strategy.matrix` 来自 `fromJson(...)`
- `build` action 继续使用 `docker/build-push-action`
- `retag` action 使用 `docker buildx imagetools create`

**Step 3: Run tests**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_deploy_build_cache_policy.py -k "docker_images_workflow or dynamic_publish_matrix"
```

Expected:
- workflow 契约通过

**Step 4: Commit**

```powershell
git add .github/workflows/docker-images.yml freshquant/tests/test_deploy_build_cache_policy.py
git commit -m "feat: publish only affected docker images"
```

### Task 4: 为正式 deploy state 与 orchestrator 写失败测试

**Files:**
- Create: `freshquant/tests/test_formal_deploy_orchestrator.py`

**Step 1: Write the failing tests**

```python
def test_bootstrap_without_state_deploys_all_surfaces(tmp_path):
    result = run_deploy_plan(...)
    assert result.bootstrap is True
    assert "api" in result.plan["surfaces"]


def test_successful_run_updates_last_success_sha(tmp_path):
    state = load_state(...)
    assert state["last_success_sha"] == "newsha"


def test_failed_health_check_does_not_advance_state(tmp_path):
    state = load_state(...)
    assert state["last_success_sha"] == "oldsha"
```

**Step 2: Run tests to verify they fail**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_formal_deploy_orchestrator.py
```

Expected:
- 缺少 orchestrator/state 实现导致失败

**Step 3: Commit**

```powershell
git add freshquant/tests/test_formal_deploy_orchestrator.py
git commit -m "test: cover formal deploy orchestration state"
```

### Task 5: 实现 deploy state 与正式 deploy orchestrator

**Files:**
- Create: `script/ci/run_formal_deploy.py`
- Create: `script/ci/formal_deploy_state.py`
- Test: `freshquant/tests/test_formal_deploy_orchestrator.py`

**Step 1: Implement state helpers**

实现：

- `load_deploy_state(path)`
- `write_deploy_state(path, payload)`
- `acquire_deploy_lock(path)`
- `release_deploy_lock(path)`

状态字段至少包含：

- `last_success_sha`
- `last_attempt_sha`
- `last_attempt_at`
- `last_success_at`
- `last_deployed_surfaces`
- `last_run_url`

**Step 2: Implement orchestrator**

最小流程：

1. 解析当前 `HEAD`
2. 读取 state
3. 决定 bootstrap 或 diff mode
4. 计算 changed paths
5. 调用 `script/freshquant_deploy_plan.py`
6. 生成部署命令清单
7. 成功时推进 state；失败时只记录 attempt

先把外部命令执行抽成可 monkeypatch 的 helper，便于测试。

**Step 3: Run focused tests**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_formal_deploy_orchestrator.py
```

Expected:
- state/orchestrator 测试通过

**Step 4: Commit**

```powershell
git add script/ci/run_formal_deploy.py script/ci/formal_deploy_state.py freshquant/tests/test_formal_deploy_orchestrator.py
git commit -m "feat: add formal deploy orchestrator and state"
```

### Task 6: 让正式 orchestrator 接上现有 deploy/health/runtime-check 入口

**Files:**
- Modify: `script/ci/run_formal_deploy.py`
- Modify: `freshquant/tests/test_formal_deploy_orchestrator.py`

**Step 1: Extend failing tests**

```python
def test_orchestrator_runs_docker_and_host_surfaces_in_order(...):
    assert commands == [...]


def test_orchestrator_runs_health_and_runtime_checks_after_deploy(...):
    assert "freshquant_health_check.py" in commands
    assert "check_freshquant_runtime_post_deploy.ps1" in commands
```

**Step 2: Implement minimal command assembly**

接入：

- Docker：`powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 ...`
- 宿主机：`powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 ...`
- Health：`py -3.12 script/freshquant_health_check.py ...`
- Runtime check：
  - `CaptureBaseline`
  - `Verify`

**Step 3: Run tests**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_formal_deploy_orchestrator.py
```

Expected:
- orchestrator 相关测试继续通过

**Step 4: Commit**

```powershell
git add script/ci/run_formal_deploy.py freshquant/tests/test_formal_deploy_orchestrator.py
git commit -m "feat: wire formal deploy workflow to current deploy commands"
```

### Task 7: 新增 deploy-production workflow

**Files:**
- Create: `.github/workflows/deploy-production.yml`
- Modify: `freshquant/tests/test_deploy_build_cache_policy.py`

**Step 1: Write failing workflow contract test**

```python
def test_deploy_production_workflow_runs_on_windows_self_hosted():
    text = Path(".github/workflows/deploy-production.yml").read_text(encoding="utf-8")
    assert "workflow_run" in text
    assert "self-hosted" in text
    assert "windows" in text
    assert "production" in text
    assert "python script/ci/run_formal_deploy.py" in text
```

**Step 2: Implement minimal workflow**

要求：

- 监听 `Docker Images`
- 成功且分支为 `main` 时执行
- `concurrency: deploy-production`
- self-hosted Windows runner
- 调用 `run_formal_deploy.py`

**Step 3: Run tests**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_deploy_build_cache_policy.py -k deploy_production_workflow
```

Expected:
- workflow 契约通过

**Step 4: Commit**

```powershell
git add .github/workflows/deploy-production.yml freshquant/tests/test_deploy_build_cache_policy.py
git commit -m "feat: add production auto deploy workflow"
```

### Task 8: 更新正式文档

**Files:**
- Modify: `docs/current/deployment.md`
- Modify: `docs/current/runtime.md`
- Modify: `freshquant/tests/test_check_current_docs.py`

**Step 1: Write failing docs test**

```python
def test_current_docs_describe_selective_image_publish_and_auto_deploy():
    assert "只有改到的服务才真正 build" in deployment_text
    assert "deploy-production.yml" in deployment_text
    assert "Windows self-hosted runner" in deployment_text
```

**Step 2: Implement minimal docs updates**

部署文档新增：

- 选择性镜像发布
- GHCR retag 语义
- 自动正式部署 workflow
- `last_success_sha -> current_head` 增量发布口径
- 失败不回滚，只阻断

**Step 3: Run tests**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_check_current_docs.py
```

Expected:
- docs 契约通过

**Step 4: Commit**

```powershell
git add docs/current/deployment.md docs/current/runtime.md freshquant/tests/test_check_current_docs.py
git commit -m "docs: describe selective build and auto deploy flow"
```

### Task 9: 完整验证

**Files:**
- No code changes expected

**Step 1: Run the full relevant suite**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_freshquant_deploy_plan.py freshquant/tests/test_docker_parallel_runtime.py freshquant/tests/test_docker_runtime_policy.py freshquant/tests/test_deploy_build_cache_policy.py freshquant/tests/test_docker_parallel_compose.py freshquant/tests/test_freshquant_health_check.py freshquant/tests/test_tradingagents_runtime_policy.py freshquant/tests/test_check_current_docs.py freshquant/tests/test_docker_image_publish_plan.py freshquant/tests/test_formal_deploy_orchestrator.py
```

Expected:
- 全部通过

**Step 2: Run formatting / lint gate equivalent**

Run:

```powershell
py -3.12 -m uv tool run black --check freshquant/tests/test_deploy_build_cache_policy.py freshquant/tests/test_docker_image_publish_plan.py freshquant/tests/test_formal_deploy_orchestrator.py script/ci/resolve_docker_image_publish_plan.py script/ci/formal_deploy_state.py script/ci/run_formal_deploy.py
```

Expected:
- 无文件需要重格式化

**Step 3: Smoke the publish-plan script**

Run:

```powershell
py -3.12 script/ci/resolve_docker_image_publish_plan.py --base-sha HEAD~1 --head-sha HEAD
```

Expected:
- 返回带 `build/retag` 动作的 JSON

**Step 4: Smoke the formal deploy orchestrator in dry-run mode**

如果实现中提供 `--dry-run`：

```powershell
py -3.12 script/ci/run_formal_deploy.py --state-path .tmp/formal-deploy-state.json --artifacts-root .tmp/formal-deploy-runs --dry-run
```

Expected:
- 输出 deploy plan 和待执行命令，不修改正式状态路径

**Step 5: Final commit**

```powershell
git add .
git commit -m "feat: automate selective docker builds and production deploy"
```
