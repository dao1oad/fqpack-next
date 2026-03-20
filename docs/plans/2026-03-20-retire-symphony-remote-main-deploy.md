# 退役 Symphony 并收紧为远程 main 正式部署 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 退役 `Symphony` 治理与运行面，并把正式部署真值收紧为“最新远程 `main` 已合并 SHA + deploy/verify 结果”。

**Architecture:** 先把 formal deploy state 与通用 runtime verify 能力从 `runtime/symphony/**` 迁到中性路径，再把 formal deploy 入口改成 remote `main` only，最后删除 Symphony surface、服务、文档和测试。整个实现遵循“先迁移真值链，再删除旧对象”的顺序，避免 deploy 后验收链断裂。

**Tech Stack:** Python 3.12, PowerShell, pytest, git worktree, Windows service / scheduled task, FreshQuant selective deploy scripts

---

### Task 1: 纳入 formal deploy orchestrator 到正式仓库

**Files:**
- Create: `script/ci/formal_deploy_state.py`
- Create: `script/ci/run_formal_deploy.py`
- Create: `freshquant/tests/test_formal_deploy_orchestrator.py`
- Reference: `.worktrees/main-deploy-production/script/ci/formal_deploy_state.py`
- Reference: `.worktrees/main-deploy-production/script/ci/run_formal_deploy.py`
- Reference: `.worktrees/main-deploy-production/freshquant/tests/test_formal_deploy_orchestrator.py`

**Step 1: 写入 failing test，先把 orchestrator 纳入 repo 真值**

```python
def test_bootstrap_without_state_deploys_all_surfaces(tmp_path, monkeypatch):
    module = load_module()
    result = module.run_formal_deploy(
        repo_root=Path("."),
        state_path=tmp_path / "production-state.json",
        runs_root=tmp_path / "runs",
        head_sha="newsha",
        run_url="https://example.invalid/runs/1",
    )
    assert result["bootstrap"] is True
```

**Step 2: 运行测试，确认当前分支缺失正式入口**

Run: `py -3.12 -m pytest freshquant/tests/test_formal_deploy_orchestrator.py -q`

Expected: FAIL，提示 `script/ci/run_formal_deploy.py` 不存在。

**Step 3: 从 deploy mirror 引入最小可运行实现**

```python
DEFAULT_STATE = {
    "last_success_sha": None,
    "last_attempt_sha": None,
    "last_attempt_at": None,
    "last_success_at": None,
    "last_deployed_surfaces": [],
    "last_run_url": None,
}
```

要求：
- 先原样引入 deploy mirror 中的 `formal_deploy_state.py`
- 先原样引入 deploy mirror 中的 `run_formal_deploy.py`
- 暂不修改 Symphony 路径，先把正式入口纳入仓库

**Step 4: 运行测试，确认引入成功**

Run: `py -3.12 -m pytest freshquant/tests/test_formal_deploy_orchestrator.py -q`

Expected: PASS。

**Step 5: Commit**

```bash
git add script/ci/formal_deploy_state.py script/ci/run_formal_deploy.py freshquant/tests/test_formal_deploy_orchestrator.py
git commit -m "feat: add formal deploy orchestrator to repo"
```

### Task 2: 迁移 runtime verify 脚本到中性路径

**Files:**
- Create: `script/check_freshquant_runtime_post_deploy.ps1`
- Create: `freshquant/tests/test_runtime_post_deploy_check.py`
- Delete: `runtime/symphony/scripts/check_freshquant_runtime_post_deploy.ps1`
- Delete: `freshquant/tests/test_symphony_runtime_post_deploy_check.py`

**Step 1: 写入 failing test，先锁定新路径与新命名**

```python
SCRIPT = REPO_ROOT / "script" / "check_freshquant_runtime_post_deploy.ps1"

def test_capture_baseline_records_runtime_state_from_snapshots(tmp_path):
    result = _run_powershell(SCRIPT, "-Mode", "CaptureBaseline", "-OutputPath", str(tmp_path / "baseline.json"))
    assert result.returncode == 0
```

**Step 2: 运行测试，确认新路径尚不存在**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_post_deploy_check.py -q`

Expected: FAIL，提示 `script/check_freshquant_runtime_post_deploy.ps1` 不存在。

**Step 3: 复制脚本并改成中性路径**

```powershell
param(
    [ValidateSet('CaptureBaseline', 'Verify')]
    [string]$Mode
)
```

要求：
- 先把原脚本复制到 `script/check_freshquant_runtime_post_deploy.ps1`
- 测试文件改名为 `test_runtime_post_deploy_check.py`
- 暂时保留旧脚本，直到调用方全部切换

**Step 4: 运行测试，确认行为等价**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_post_deploy_check.py -q`

Expected: PASS。

**Step 5: Commit**

```bash
git add script/check_freshquant_runtime_post_deploy.ps1 freshquant/tests/test_runtime_post_deploy_check.py runtime/symphony/scripts/check_freshquant_runtime_post_deploy.ps1 freshquant/tests/test_symphony_runtime_post_deploy_check.py
git commit -m "refactor: move runtime verify script out of symphony"
```

### Task 3: 删除 Symphony deployment surface 并更新 deploy plan

**Files:**
- Modify: `script/freshquant_deploy_plan.py`
- Modify: `freshquant/tests/test_freshquant_deploy_plan.py`

**Step 1: 先写 failing test，锁定新的 deploy surface 集合**

```python
def test_runtime_symphony_paths_no_longer_emit_deploy_surface() -> None:
    module = load_module()
    plan = module.build_deploy_plan(
        changed_paths=["runtime/symphony/prompts/global_stewardship.md"]
    )
    assert plan["deployment_surfaces"] == []
    assert "http://127.0.0.1:40123/api/v1/state" not in plan["health_checks"]
```

**Step 2: 运行测试，确认当前实现仍依赖 Symphony**

Run: `py -3.12 -m pytest freshquant/tests/test_freshquant_deploy_plan.py -q`

Expected: FAIL，仍返回 `symphony` surface 与 `40123` 健康检查。

**Step 3: 最小修改 deploy plan**

```python
SURFACE_ORDER = (
    "api",
    "web",
    "dagster",
    "qa",
    "tradingagents",
    "market_data",
    "guardian",
    "position_management",
    "tpsl",
    "order_management",
)
```

要求：
- 删除 `SURFACE_ORDER` 中的 `symphony`
- 删除 `SURFACE_ALIASES` 中的 `symphony`
- 删除 `HEALTH_CHECK_MAP` 中的 `40123`
- 删除 `runtime/symphony/` path rule
- 删除 `symphony_sync_restart` pre-deploy step

**Step 4: 运行测试，确认 deploy plan 已不生成 Symphony**

Run: `py -3.12 -m pytest freshquant/tests/test_freshquant_deploy_plan.py -q`

Expected: PASS。

**Step 5: Commit**

```bash
git add script/freshquant_deploy_plan.py freshquant/tests/test_freshquant_deploy_plan.py
git commit -m "refactor: remove symphony from deploy plan surfaces"
```

### Task 4: 把 formal deploy 改成 remote main-only，并迁中性 state 路径

**Files:**
- Modify: `script/ci/run_formal_deploy.py`
- Modify: `script/ci/formal_deploy_state.py`
- Modify: `freshquant/tests/test_formal_deploy_orchestrator.py`
- Create: `script/ci/fetch_remote_main_sha.py`（仅当现有 orchestrator 不便内联时）

**Step 1: 写 failing test，锁定 remote main-only 语义**

```python
def test_formal_deploy_uses_last_success_sha_to_latest_origin_main(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "resolve_latest_remote_main_sha", lambda *_: "newsha")
    result = module.run_formal_deploy(
        repo_root=Path("."),
        state_path=tmp_path / "production-state.json",
        runs_root=tmp_path / "runs",
        run_url="https://example.invalid/runs/2",
    )
    assert result["head_sha"] == "newsha"
```

**Step 2: 运行测试，确认当前实现仍可接受本地 `HEAD` 作为正式输入**

Run: `py -3.12 -m pytest freshquant/tests/test_formal_deploy_orchestrator.py -q`

Expected: FAIL，当前测试夹具仍围绕本地 `HEAD` / `service_root=D:\\fqpack\\runtime\\symphony-service`。

**Step 3: 修改 orchestrator**

```python
DEFAULT_ARTIFACTS_ROOT = Path(r"D:\fqpack\runtime\formal-deploy")

def default_state_path(artifacts_root: Path) -> Path:
    return artifacts_root / "production-state.json"
```

要求：
- 默认 formal deploy 根目录改到中性路径
- 执行前显式 `git fetch origin main`
- 解析最新远程 `origin/main` SHA
- 统一按 `last_success_sha -> latest origin/main sha` 生成 changed paths
- 本地 worktree 未 merge 状态不得作为正式 deploy 输入
- runtime baseline / verify 调用改到 `script/check_freshquant_runtime_post_deploy.ps1`

**Step 4: 运行测试，覆盖 bootstrap、noop、失败不推进 state、remote compare 等场景**

Run: `py -3.12 -m pytest freshquant/tests/test_formal_deploy_orchestrator.py -q`

Expected: PASS。

**Step 5: Commit**

```bash
git add script/ci/run_formal_deploy.py script/ci/formal_deploy_state.py freshquant/tests/test_formal_deploy_orchestrator.py
git commit -m "refactor: make formal deploy remote-main only"
```

### Task 5: 去掉 Symphony 服务检查并清理 verify 语义

**Files:**
- Modify: `script/check_freshquant_runtime_post_deploy.ps1`
- Modify: `freshquant/tests/test_runtime_post_deploy_check.py`

**Step 1: 写 failing test，锁定不再检查 `fq-symphony-orchestrator`**

```python
def test_verify_does_not_require_symphony_service(tmp_path):
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert all("fq-symphony-orchestrator" not in failure for failure in payload["failures"])
```

**Step 2: 运行测试，确认当前 verify 仍依赖 Symphony service**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_post_deploy_check.py -q`

Expected: FAIL，出现 `fq-symphony-orchestrator` 相关断言。

**Step 3: 最小修改 verify 脚本和测试**

```powershell
$AllowedDeploymentSurfaces = @(
  'api','web','dagster','qa','tradingagents',
  'market_data','guardian','position_management','tpsl','order_management'
)
```

要求：
- 删除 `symphony` deployment surface
- 删除 `fq-symphony-orchestrator` service baseline / verify
- 保留 `fqnext-supervisord`
- 保留 Docker / process 恢复语义

**Step 4: 运行测试，确认 verify 通过新契约**

Run: `py -3.12 -m pytest freshquant/tests/test_runtime_post_deploy_check.py -q`

Expected: PASS。

**Step 5: Commit**

```bash
git add script/check_freshquant_runtime_post_deploy.ps1 freshquant/tests/test_runtime_post_deploy_check.py
git commit -m "refactor: remove symphony from runtime verify"
```

### Task 6: 删除 Symphony 仓库内容并改写正式文档

**Files:**
- Modify: `docs/current/deployment.md`
- Modify: `docs/current/runtime.md`
- Modify: `docs/current/overview.md`
- Modify: `docs/current/troubleshooting.md`
- Modify: `docs/index.md`
- Modify: `AGENTS.md`
- Modify: `.codex/memory/deploy-surfaces.md`
- Delete: `runtime/symphony/README.md`
- Delete: `runtime/symphony/WORKFLOW.freshquant.md`
- Delete: `runtime/symphony/prompts/global_stewardship.md`
- Delete: `runtime/symphony/prompts/in_progress.md`
- Delete: `runtime/symphony/prompts/merging.md`
- Delete: `runtime/symphony/prompts/todo.md`
- Delete: `runtime/symphony/scripts/activate_github_first_formal_service.ps1`
- Delete: `runtime/symphony/scripts/assert_freshquant_global_stewardship_prompt.ps1`
- Delete: `runtime/symphony/scripts/assert_freshquant_merging_prompt.ps1`
- Delete: `runtime/symphony/scripts/assert_freshquant_workflow_prompt.ps1`
- Delete: `runtime/symphony/scripts/freshquant_runner.exs`
- Delete: `runtime/symphony/scripts/install_freshquant_symphony_restart_task.ps1`
- Delete: `runtime/symphony/scripts/install_freshquant_symphony_service.ps1`
- Delete: `runtime/symphony/scripts/invoke_freshquant_symphony_cleanup_finalizer.ps1`
- Delete: `runtime/symphony/scripts/invoke_freshquant_symphony_restart_task.ps1`
- Delete: `runtime/symphony/scripts/reinstall_freshquant_symphony_service.ps1`
- Delete: `runtime/symphony/scripts/request_freshquant_symphony_cleanup.ps1`
- Delete: `runtime/symphony/scripts/run_freshquant_codex_session.ps1`
- Delete: `runtime/symphony/scripts/run_freshquant_symphony_restart_task.ps1`
- Delete: `runtime/symphony/scripts/smoke_test_github_first_formal_service.ps1`
- Delete: `runtime/symphony/scripts/start_freshquant_symphony.ps1`
- Delete: `runtime/symphony/scripts/sync_freshquant_symphony_service.ps1`
- Delete: `runtime/symphony/templates/deployment_comment.md`
- Delete: `runtime/symphony/templates/design_review_packet.md`
- Delete: `runtime/symphony/templates/done_summary.md`
- Delete: `runtime/symphony/templates/follow_up_issue.md`
- Delete: `runtime/symphony/templates/global_stewardship_done_comment.md`
- Delete: `runtime/symphony/templates/global_stewardship_progress_comment.md`
- Delete: `runtime/symphony/templates/human_review_comment.md`
- Delete: `runtime/symphony/templates/merge_handoff_comment.md`
- Delete: `runtime/symphony/templates/pr_completion_comment.md`
- Delete: `.github/ISSUE_TEMPLATE/symphony_task.yml`
- Delete: `freshquant/tests/test_symphony_cleanup_scripts.py`
- Delete: `freshquant/tests/test_symphony_memory_contract.py`
- Delete: `freshquant/tests/test_symphony_prompt_contract.py`
- Delete: `freshquant/tests/test_symphony_restart_task_scripts.py`

**Step 1: 写 failing docs/test assertions，锁定新正式口径**

```python
def test_deployment_docs_state_formal_deploy_is_remote_main_only():
    content = Path("docs/current/deployment.md").read_text(encoding="utf-8")
    assert "latest remote `main`" in content
    assert "http://127.0.0.1:40123/api/v1/state" not in content
```

**Step 2: 运行文档与契约测试，确认当前仍残留 Symphony**

Run: `py -3.12 -m pytest freshquant/tests/test_check_current_docs.py freshquant/tests/test_runtime_memory_docs.py -q`

Expected: FAIL 或需要同步更新测试，因为当前文档仍引用 Symphony。

**Step 3: 批量改写文档并删除旧目录**

```markdown
正式 deploy 只允许从最新远程 `main` 已合并 SHA 发起。
本地会话用于开发、测试与预检查，不作为正式部署真值。
```

要求：
- 文档统一改为 remote `main` only
- 删除 `40123`、`fq-symphony-orchestrator`、Symphony 治理描述
- 删除 `runtime/symphony/**` 与其测试/模板/issue template

**Step 4: 运行回归测试**

Run: `py -3.12 -m pytest freshquant/tests/test_check_current_docs.py freshquant/tests/test_runtime_memory_docs.py freshquant/tests/test_freshquant_deploy_plan.py freshquant/tests/test_formal_deploy_orchestrator.py freshquant/tests/test_runtime_post_deploy_check.py -q`

Expected: PASS。

**Step 5: Commit**

```bash
git add docs/current/deployment.md docs/current/runtime.md docs/current/overview.md docs/current/troubleshooting.md docs/index.md AGENTS.md .codex/memory/deploy-surfaces.md .github/ISSUE_TEMPLATE/symphony_task.yml runtime/symphony freshquant/tests
git commit -m "refactor: retire symphony governance and service"
```

### Task 7: 执行真实验证与系统清理

**Files:**
- Modify: `docs/current/deployment.md`（如需补充实际验证记录）
- Reference: `D:\fqpack\runtime\formal-deploy\production-state.json`

**Step 1: 在 deploy mirror 上跑一次真实 formal deploy**

Run:

```powershell
git -C D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production fetch origin main
git -C D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production reset --hard origin/main
py -3.12 D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production\script\ci\run_formal_deploy.py --repo-root D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production --format summary
```

Expected: 成功输出 remote `main` SHA、deployment surfaces、health check、runtime verify 结果。

**Step 2: 核对新 formal deploy state**

Run:

```powershell
Get-Content D:\fqpack\runtime\formal-deploy\production-state.json
```

Expected: `last_success_sha` 更新到最新远程 `main` SHA。

**Step 3: 删除系统服务和计划任务**

Run:

```powershell
Stop-Service fq-symphony-orchestrator -ErrorAction SilentlyContinue
sc.exe delete fq-symphony-orchestrator
Unregister-ScheduledTask -TaskName 'fq-symphony-orchestrator-restart' -Confirm:$false -ErrorAction SilentlyContinue
```

**Step 4: 验证系统对象已删除**

Run:

```powershell
Get-Service fq-symphony-orchestrator -ErrorAction SilentlyContinue
Get-ScheduledTask -TaskName 'fq-symphony-orchestrator-restart' -ErrorAction SilentlyContinue
```

Expected: 不再返回有效服务或任务。

**Step 5: 删除旧运行目录并提交最终文档同步**

Run:

```powershell
Remove-Item -Recurse -Force D:\fqpack\runtime\symphony-service
```

Commit:

```bash
git add docs/current/deployment.md
git commit -m "chore: remove retired symphony runtime leftovers"
```
