# Host Supervisor Deploy Mirror Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 formal deploy 命中宿主机面时自动把 `fqnext-supervisord` 配置收敛到 `main-deploy-production`，并在 runtime verify 中阻断错误 import source。

**Architecture:** 新增一个 supervisor 配置真值脚本负责渲染/检查 `supervisord.fqnext.conf`；formal deploy 在 host restart 前调用该能力并按需重载 service；runtime post-deploy verify 同步增加配置与 import source 校验。

**Tech Stack:** Python 3.12, PowerShell 5.1, pytest, supervisor XML-RPC, Windows service bridge

---

### Task 1: 写 supervisor 配置真值测试

**Files:**
- Create: `freshquant/tests/test_fqnext_supervisor_config.py`
- Reference: `deployment/examples/supervisord.fqnext.example.conf`
- Reference: `script/fqnext_host_runtime.py`

**Step 1: Write the failing test**

- 覆盖渲染后的 config 必须固定指向 `main-deploy-production`
- 覆盖 inspect/validate 必须能识别 `main-runtime` 和 `site-packages` 漂移

**Step 2: Run test to verify it fails**

Run: `python -m pytest freshquant/tests/test_fqnext_supervisor_config.py -q`

Expected: FAIL，因为脚本文件与相关函数尚不存在。

**Step 3: Write minimal implementation**

- 新建 `script/fqnext_supervisor_config.py`
- 实现 render / write / inspect 所需最小函数与 CLI

**Step 4: Run test to verify it passes**

Run: `python -m pytest freshquant/tests/test_fqnext_supervisor_config.py -q`

Expected: PASS

### Task 2: 写 runtime verify 对 supervisor config 的失败用例

**Files:**
- Modify: `freshquant/tests/test_runtime_post_deploy_check.py`
- Modify: `script/check_freshquant_runtime_post_deploy.ps1`

**Step 1: Write the failing test**

- 新增“命中 host surface 且 supervisor config 指向 `main-runtime` / `site-packages` 时 Verify 失败”的测试
- 新增“config 正确时 Verify 通过”的测试

**Step 2: Run test to verify it fails**

Run: `python -m pytest freshquant/tests/test_runtime_post_deploy_check.py -q`

Expected: FAIL，因为当前脚本还没有 supervisor config checks。

**Step 3: Write minimal implementation**

- `check_freshquant_runtime_post_deploy.ps1` 增加 config snapshot/check
- 支持测试快照输入，避免依赖真实宿主机 service

**Step 4: Run test to verify it passes**

Run: `python -m pytest freshquant/tests/test_runtime_post_deploy_check.py -q`

Expected: PASS

### Task 3: 写 formal deploy host reconcile 的失败用例

**Files:**
- Modify: `freshquant/tests/test_host_runtime_management.py`
- Modify: `freshquant/tests/test_fqnext_host_runtime.py`
- Modify: `script/fqnext_host_runtime_ctl.ps1`
- Modify: `script/ci/run_formal_deploy.py`

**Step 1: Write the failing test**

- 断言 host runtime 控制脚本暴露 `SupervisorConfigRepoRoot` 能力
- 断言 formal deploy 在执行 host command 时会传入当前 `repo_root`

**Step 2: Run test to verify it fails**

Run: `python -m pytest freshquant/tests/test_host_runtime_management.py freshquant/tests/test_fqnext_host_runtime.py -q`

Expected: FAIL，因为现在还没有 config reconcile 参数与流程。

**Step 3: Write minimal implementation**

- `fqnext_host_runtime_ctl.ps1` 增加 config 写入、mtime/service-start 检查、必要时管理员桥接重启
- `run_formal_deploy.py` 在 host command 上追加 `-SupervisorConfigRepoRoot`

**Step 4: Run test to verify it passes**

Run: `python -m pytest freshquant/tests/test_host_runtime_management.py freshquant/tests/test_fqnext_host_runtime.py -q`

Expected: PASS

### Task 4: 同步模板与当前文档

**Files:**
- Modify: `deployment/examples/supervisord.fqnext.example.conf`
- Modify: `README.md`
- Modify: `docs/current/configuration.md`
- Modify: `docs/current/deployment.md`
- Modify: `docs/current/runtime.md`
- Modify: `freshquant/tests/test_host_runtime_pythonpath.py`

**Step 1: Write the failing test**

- 更新或新增断言，要求模板与文档明确说明宿主机正式运行真值为 `main-deploy-production`

**Step 2: Run test to verify it fails**

Run: `python -m pytest freshquant/tests/test_host_runtime_pythonpath.py freshquant/tests/test_deploy_build_cache_policy.py -q`

Expected: FAIL，因为模板与文档仍保留旧口径。

**Step 3: Write minimal implementation**

- 更新 example config、README 与 `docs/current/**`

**Step 4: Run test to verify it passes**

Run: `python -m pytest freshquant/tests/test_host_runtime_pythonpath.py freshquant/tests/test_deploy_build_cache_policy.py -q`

Expected: PASS

### Task 5: 完整验证

**Files:**
- Verify only

**Step 1: Run targeted tests**

Run: `python -m pytest freshquant/tests/test_fqnext_supervisor_config.py freshquant/tests/test_runtime_post_deploy_check.py freshquant/tests/test_host_runtime_management.py freshquant/tests/test_fqnext_host_runtime.py freshquant/tests/test_host_runtime_pythonpath.py freshquant/tests/test_deploy_build_cache_policy.py -q`

Expected: PASS

**Step 2: Run broader guard where relevant**

Run: `python -m pytest freshquant/tests/test_runtime_memory_docs.py -q`

Expected: PASS

**Step 3: Commit**

```bash
git add docs/plans/2026-04-02-host-supervisor-deploy-mirror-design.md docs/plans/2026-04-02-host-supervisor-deploy-mirror.md script/fqnext_supervisor_config.py script/fqnext_host_runtime_ctl.ps1 script/check_freshquant_runtime_post_deploy.ps1 script/ci/run_formal_deploy.py deployment/examples/supervisord.fqnext.example.conf README.md docs/current/configuration.md docs/current/deployment.md docs/current/runtime.md freshquant/tests/test_fqnext_supervisor_config.py freshquant/tests/test_runtime_post_deploy_check.py freshquant/tests/test_host_runtime_management.py freshquant/tests/test_fqnext_host_runtime.py freshquant/tests/test_host_runtime_pythonpath.py
git commit -m "fix: align host supervisor runtime with deploy mirror"
```
