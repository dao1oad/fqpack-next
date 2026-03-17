# Docker 部署全链路优化 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修正 shared rear image 的部署语义，并把 Docker 部署升级为“远端预构建镜像优先、本机构建回退”的全链路优化方案。

**Architecture:** 部署计划新增 shared image refresh / registry image 语义，`docker_parallel_compose` 负责 local cache / remote cache / build fallback 三段决策，Compose 与 Dockerfile 统一 git SHA label 和 BuildKit cache，GitHub Actions 负责在 `main` 预构建并发布镜像到 `GHCR`。

**Tech Stack:** Python 3.12、Pytest、PowerShell、Docker Compose、Docker BuildKit、GitHub Actions、GHCR

---

### Task 1: 先写 shared image 与 smart-build 的失败测试

**Files:**
- Modify: `freshquant/tests/test_freshquant_deploy_plan.py`
- Modify: `freshquant/tests/test_docker_parallel_compose.py`
- Modify: `freshquant/tests/test_deploy_build_cache_policy.py`

**Step 1: Write the failing tests**

```python
def test_shared_rear_surfaces_require_rear_build_target() -> None:
    plan = build_deploy_plan(explicit_surfaces=["dagster"])
    assert "fq_apiserver" in plan["docker_build_targets"]
    assert "fq_dagster_webserver" in plan["docker_up_services"]


def test_remote_registry_match_prefers_pull_and_no_build() -> None:
    result = compute_rewrite_result(...)
    assert result["mode"] == "remote_cached"
    assert result["compose_args"] == ["up", "-d", "--no-build", "fq_webui"]


def test_dirty_unrelated_files_do_not_disable_cached_deploy() -> None:
    result = compute_rewrite_result(...)
    assert result["skip_build"] is True
```

**Step 2: Run tests to verify they fail**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_freshquant_deploy_plan.py freshquant/tests/test_docker_parallel_compose.py freshquant/tests/test_deploy_build_cache_policy.py
```

Expected:
- 新增测试失败，提示缺少 `docker_build_targets` / `docker_up_services` / `mode` / TradingAgents label 或 dirty 路径判定。

### Task 2: 实现部署计划中的 shared image refresh 语义

**Files:**
- Modify: `script/freshquant_deploy_plan.py`
- Modify: `freshquant/tests/test_freshquant_deploy_plan.py`

**Step 1: Write minimal implementation**

```python
DOCKER_BUILD_OWNER_MAP = {
    "api": ["fq_apiserver"],
    "dagster": ["fq_apiserver"],
    "qa": ["fq_apiserver"],
}

DOCKER_UP_SERVICE_MAP = {
    "api": ["fq_apiserver"],
    "dagster": ["fq_dagster_webserver", "fq_dagster_daemon"],
    "qa": ["fq_qawebserver"],
}
```

- 让 plan 同时返回：
  - `docker_build_targets`
  - `docker_up_services`
  - `registry_images`
- 保持原有字段兼容，必要时让 `docker_services` 作为 `docker_up_services` 的兼容别名。

**Step 2: Run focused tests**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_freshquant_deploy_plan.py
```

Expected:
- shared rear image 相关测试通过

### Task 3: 扩展 docker_parallel_compose 为 remote/local/build 三态决策

**Files:**
- Modify: `script/docker_parallel_compose.py`
- Modify: `script/docker_parallel_compose.ps1`
- Modify: `freshquant/tests/test_docker_parallel_compose.py`

**Step 1: Add failing tests for remote registry preference and dirty path sensitivity**

```python
def test_remote_cached_images_prefer_pull() -> None:
    assert result["mode"] == "remote_cached"


def test_dirty_files_outside_build_inputs_keep_no_build() -> None:
    assert result["compose_args"] == ["up", "-d", "--no-build", "fq_webui"]
```

**Step 2: Implement minimal code**

```python
if remote_revision == current_revision:
    return {"mode": "remote_cached", "compose_args": no_build_args, ...}
if local_revision == current_revision:
    return {"mode": "local_cached", "compose_args": no_build_args, ...}
return {"mode": "build_required", "compose_args": original_args, ...}
```

- 新增：
  - registry image reference 生成
  - `docker manifest inspect` 或 `docker buildx imagetools inspect` 探测
  - dirty file -> build input 匹配
- `ps1` 中：
  - 若 `mode=remote_cached`，先 `docker pull`
  - 否则沿用现有 compose 调用

**Step 3: Run focused tests**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_docker_parallel_compose.py
```

Expected:
- `docker_parallel_compose` 相关测试通过

### Task 4: 补齐 Compose / Dockerfile 的镜像 label 与 BuildKit cache

**Files:**
- Modify: `docker/compose.parallel.yaml`
- Modify: `docker/Dockerfile.rear`
- Modify: `docker/Dockerfile.web`
- Modify: `third_party/tradingagents-cn/Dockerfile.backend`
- Modify: `third_party/tradingagents-cn/Dockerfile.frontend`
- Modify: `freshquant/tests/test_deploy_build_cache_policy.py`

**Step 1: Write failing tests**

```python
def test_tradingagents_images_have_git_sha_build_args() -> None:
    assert "FQ_IMAGE_GIT_SHA" in compose_text
    assert 'LABEL io.freshquant.git_sha="${FQ_IMAGE_GIT_SHA}"' in backend_text


def test_dockerfiles_use_cache_mounts() -> None:
    assert "--mount=type=cache" in rear_text
    assert "--mount=type=cache" in web_text
```

**Step 2: Implement minimal changes**

- Compose:
  - `ta_backend` / `ta_frontend` 补 `build.args.FQ_IMAGE_GIT_SHA`
- Dockerfiles:
  - 补 `ARG FQ_IMAGE_GIT_SHA`
  - 补统一 label
  - 加 `RUN --mount=type=cache,...`

**Step 3: Run focused tests**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_deploy_build_cache_policy.py
```

Expected:
- cache policy / label 契约通过

### Task 5: 修正 Dagster 配置同步策略

**Files:**
- Modify: `docker/compose.parallel.yaml`
- Modify: `freshquant/tests/test_deploy_build_cache_policy.py`

**Step 1: Write the failing test**

```python
def test_dagster_config_sync_overwrites_repo_config() -> None:
    assert "cp -f" in compose_text
    assert "cp -n" not in compose_text
```

**Step 2: Implement minimal change**

- 将 Dagster webserver / daemon 启动命令中的 `cp -n` 改为 `cp -f`

**Step 3: Run focused tests**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_deploy_build_cache_policy.py
```

Expected:
- Dagster 配置同步契约通过

### Task 6: 新增 GHCR 预构建镜像 workflow

**Files:**
- Create: `.github/workflows/docker-images.yml`
- Modify: `freshquant/tests/test_deploy_build_cache_policy.py`

**Step 1: Write the failing test**

```python
def test_docker_images_workflow_publishes_to_ghcr() -> None:
    text = Path(".github/workflows/docker-images.yml").read_text(encoding="utf-8")
    assert "ghcr.io" in text
    assert "packages: write" in text
    assert "docker/build-push-action" in text
```

**Step 2: Implement minimal workflow**

- `push` 到 `main`
- `workflow_dispatch`
- 登录 GHCR
- buildx 构建四个镜像并推送 `sha` / `main` tag

**Step 3: Run focused tests**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_deploy_build_cache_policy.py
```

Expected:
- workflow 契约通过

### Task 7: 更新正式文档

**Files:**
- Modify: `docs/current/deployment.md`
- Modify: `docs/current/runtime.md`
- Modify: `freshquant/tests/test_check_current_docs.py`

**Step 1: Write the failing test**

```python
def test_current_deployment_docs_describe_registry_first_docker_entry() -> None:
    assert "GHCR" in deployment_text
    assert "优先拉取 registry 中与当前 commit 匹配的镜像" in deployment_text
```

**Step 2: Implement minimal doc updates**

- 部署文档增加：
  - registry-first / local-fallback
  - shared rear image refresh
  - TradingAgents 同步接入 smart-build
- runtime 文档增加：
  - GHCR 预构建镜像是部署提速机制，不改变运行真值

**Step 3: Run focused tests**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_check_current_docs.py
```

Expected:
- 文档契约通过

### Task 8: 构建与回归验证

**Files:**
- No code changes

**Step 1: Run the full relevant suite**

Run:

```powershell
py -3.12 -m pytest -q freshquant/tests/test_freshquant_deploy_plan.py freshquant/tests/test_docker_parallel_runtime.py freshquant/tests/test_docker_runtime_policy.py freshquant/tests/test_deploy_build_cache_policy.py freshquant/tests/test_docker_parallel_compose.py freshquant/tests/test_freshquant_health_check.py freshquant/tests/test_tradingagents_runtime_policy.py freshquant/tests/test_check_current_docs.py
```

Expected:
- 全部通过

**Step 2: Run Docker build verification**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 build fq_apiserver
powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 build fq_webui
powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 build ta_backend
powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 build ta_frontend
```

Expected:
- 四个镜像构建成功

**Step 3: Run no-build smoke**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 up -d --no-build fq_apiserver fq_webui ta_backend ta_frontend
```

Expected:
- compose 成功启动，不触发额外 build

**Step 4: Run health verification**

Run:

```powershell
py -3.12 script/freshquant_health_check.py --surface api --format summary
py -3.12 script/freshquant_health_check.py --surface web --format summary
py -3.12 script/freshquant_health_check.py --surface tradingagents --format summary
```

Expected:
- API / Web / TradingAgents health check 通过
