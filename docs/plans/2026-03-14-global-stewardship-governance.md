# Global Stewardship Governance Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden FreshQuant `Merging -> Global Stewardship -> Done` so deploy, health check, runtime ops check, cleanup, and closeout all follow explicit contracts and survive dirty repos, proxy pollution, compose container prefixes, and reused frontend image tags.

**Architecture:** Keep GitHub Issue / PR / merge as the only truth sources, but upgrade `Merging` handoff into a structured packet and make `Global Stewardship` re-evaluate the latest `origin/main` before each batch. Standardize deploy, health, runtime-ops, and frontend-release verification through repository scripts so the parent steward can use subagents for diagnostics while remaining the only final decision-maker.

**Tech Stack:** PowerShell 7, Python 3.12, Docker Compose, GitHub CLI, existing Symphony prompts/templates/tests, FreshQuant pytest suite.

---

### Task 1: Write The Governance Design And Plan Docs

**Files:**
- Create: `docs/plans/2026-03-14-global-stewardship-governance-design.md`
- Create: `docs/plans/2026-03-14-global-stewardship-governance.md`

**Step 1: Verify the docs folder is available**

Run: `Get-ChildItem docs -Force`
Expected: `docs` exists; `docs/plans` may be absent.

**Step 2: Add the approved design doc**

Write the approved architecture, state machine, handoff contract, subagent boundaries, script changes, docs sync, and downgrade rules to `docs/plans/2026-03-14-global-stewardship-governance-design.md`.

**Step 3: Add the implementation plan**

Write this plan to `docs/plans/2026-03-14-global-stewardship-governance.md`.

**Step 4: Verify the files exist**

Run: `Get-ChildItem docs/plans | Select-Object Name`
Expected: both new markdown files are listed.

**Step 5: Commit**

```bash
git add docs/plans/2026-03-14-global-stewardship-governance-design.md docs/plans/2026-03-14-global-stewardship-governance.md
git commit -m "docs: add stewardship governance redesign"
```

### Task 2: Harden Merging And Stewardship Prompt Contracts

**Files:**
- Modify: `runtime/symphony/prompts/merging.md`
- Modify: `runtime/symphony/prompts/global_stewardship.md`
- Modify: `runtime/symphony/templates/merge_handoff_comment.md`
- Modify: `runtime/symphony/templates/global_stewardship_progress_comment.md`
- Modify: `runtime/symphony/templates/global_stewardship_done_comment.md`
- Modify: `runtime/symphony/scripts/assert_freshquant_merging_prompt.ps1`
- Modify: `runtime/symphony/scripts/assert_freshquant_global_stewardship_prompt.ps1`
- Modify: `runtime/symphony/scripts/assert_freshquant_workflow_prompt.ps1`
- Test: `freshquant/tests/test_symphony_prompt_contract.py`

**Step 1: Write the failing prompt-contract test**

Extend `freshquant/tests/test_symphony_prompt_contract.py` so it fails unless:

- `merging.md` requires a structured handoff packet
- `global_stewardship.md` requires re-fetching latest `main` after each closed issue
- `global_stewardship.md` requires proxyless health checks
- `global_stewardship.md` treats subagents as evidence-only helpers
- templates expose fields for runtime ops, frontend probe, blocker evidence, and contract version

**Step 2: Run the targeted test and verify failure**

Run: `py -3.12 -m pytest freshquant/tests/test_symphony_prompt_contract.py -q`
Expected: FAIL because current prompt/template text is still missing one or more guards.

**Step 3: Update the prompts and templates**

Implement the minimal wording changes so the prompt contract encodes:

- `Merging` only merges and emits handoff
- `Global Stewardship` always re-checks latest `origin/main`
- command timeout triggers release-state review, not instant failure
- proxyless localhost checks are mandatory
- subagents cannot make final lifecycle decisions

Use a structured merge handoff template that includes:

```md
- Source Issue: `<GH-xxx>`
- Source PR: `<#xxx>`
- Merge Commit: `<sha>`
- PR Head SHA: `<sha>`
- Base SHA: `<sha>`
- Changed Paths: `<paths>`
- Suggested Deployment Surfaces: `<surfaces>`
- Suggested Docker Services: `<services>`
- Suggested Host Surfaces: `<surfaces>`
- Verification Hints: `<markers>`
- Cleanup Targets: `<targets>`
- Contract Version: `v2`
```

**Step 4: Re-run the targeted test**

Run: `py -3.12 -m pytest freshquant/tests/test_symphony_prompt_contract.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add runtime/symphony/prompts/merging.md runtime/symphony/prompts/global_stewardship.md runtime/symphony/templates/merge_handoff_comment.md runtime/symphony/templates/global_stewardship_progress_comment.md runtime/symphony/templates/global_stewardship_done_comment.md runtime/symphony/scripts/assert_freshquant_merging_prompt.ps1 runtime/symphony/scripts/assert_freshquant_global_stewardship_prompt.ps1 runtime/symphony/scripts/assert_freshquant_workflow_prompt.ps1 freshquant/tests/test_symphony_prompt_contract.py
git commit -m "feat: harden symphony stewardship contracts"
```

### Task 3: Upgrade Deploy Plan And Runtime Path Resolution

**Files:**
- Modify: `script/freshquant_deploy_plan.py`
- Modify: `script/docker_parallel_runtime.py`
- Test: `freshquant/tests/test_freshquant_deploy_plan.py`
- Test: `freshquant/tests/test_docker_runtime_policy.py`

**Step 1: Write the failing deploy-plan tests**

Add tests to `freshquant/tests/test_freshquant_deploy_plan.py` that require:

- `--base-sha` and `--head-sha` support
- output fields `effective_release_scope`, `health_check_mode`, `verification_markers`, `cleanup_targets`
- stable behavior when multiple merges land in one run

Add tests to `freshquant/tests/test_docker_runtime_policy.py` that require:

- explicit primary worktree resolution
- separate compose env file and runtime log dir resolution
- support for “clean worktree build + primary repo env”

**Step 2: Run tests and verify failure**

Run: `py -3.12 -m pytest freshquant/tests/test_freshquant_deploy_plan.py freshquant/tests/test_docker_runtime_policy.py -q`
Expected: FAIL because current scripts do not expose the new inputs/outputs.

**Step 3: Implement minimal script changes**

In `script/freshquant_deploy_plan.py`, add CLI arguments and output fields such as:

```python
parser.add_argument("--base-sha")
parser.add_argument("--head-sha")
parser.add_argument("--issue-number")
parser.add_argument("--merge-commit")
...
plan["health_check_mode"] = "proxyless"
plan["verification_markers"] = [...]
plan["cleanup_targets"] = {...}
```

In `script/docker_parallel_runtime.py`, add explicit resolution helpers for:

- primary worktree
- compose env file
- runtime log dir
- dirty primary repo vs clean build worktree

**Step 4: Re-run tests**

Run: `py -3.12 -m pytest freshquant/tests/test_freshquant_deploy_plan.py freshquant/tests/test_docker_runtime_policy.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add script/freshquant_deploy_plan.py script/docker_parallel_runtime.py freshquant/tests/test_freshquant_deploy_plan.py freshquant/tests/test_docker_runtime_policy.py
git commit -m "feat: harden deploy plan and runtime path resolution"
```

### Task 4: Add Proxyless Health Check As A Formal Entry Point

**Files:**
- Create: `script/freshquant_health_check.ps1`
- Create: `freshquant/tests/test_freshquant_health_check.py`
- Modify: `docs/current/deployment.md`
- Modify: `docs/current/runtime.md`
- Modify: `docs/current/troubleshooting.md`

**Step 1: Write the failing test**

Create `freshquant/tests/test_freshquant_health_check.py` to require:

- localhost checks explicitly bypass proxies
- status code assertions work
- JSON field assertions work
- output is machine-readable JSON

Use subprocess-based tests with simple local HTTP fixtures if the repo already uses them; otherwise test the argument parser and emitted command contract.

**Step 2: Run the test and verify failure**

Run: `py -3.12 -m pytest freshquant/tests/test_freshquant_health_check.py -q`
Expected: FAIL because the script does not yet exist.

**Step 3: Implement the script**

Create `script/freshquant_health_check.ps1` with parameters like:

```powershell
param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$ExpectedStatus = 200,
    [string]$ExpectJsonField,
    [string]$ExpectJsonValue,
    [string]$ExpectText,
    [string]$OutputPath
)
```

Implementation requirements:

- clear `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` for the child request
- for localhost / `127.0.0.1`, force `-NoProxy`
- emit JSON with `url`, `status_code`, `passed`, `json_assertions`, `text_assertions`

**Step 4: Re-run the targeted test**

Run: `py -3.12 -m pytest freshquant/tests/test_freshquant_health_check.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add script/freshquant_health_check.ps1 freshquant/tests/test_freshquant_health_check.py docs/current/deployment.md docs/current/runtime.md docs/current/troubleshooting.md
git commit -m "feat: add proxyless health check entrypoint"
```

### Task 5: Make Runtime Post-Deploy Verify Compose-Service Aware

**Files:**
- Modify: `runtime/symphony/scripts/check_freshquant_runtime_post_deploy.ps1`
- Test: `freshquant/tests/test_symphony_runtime_post_deploy_check.py`

**Step 1: Write the failing regression test**

Extend `freshquant/tests/test_symphony_runtime_post_deploy_check.py` so it fails unless live mode can resolve containers by compose service label when actual container names are prefixed, for example:

- service `fq_mongodb`
- container `fqnext_20260223-fq_mongodb-1`

**Step 2: Run the test and verify failure**

Run: `py -3.12 -m pytest freshquant/tests/test_symphony_runtime_post_deploy_check.py -q`
Expected: FAIL because current live mode still relies on short names.

**Step 3: Implement minimal support**

Add a helper in the PowerShell script to resolve live containers in this order:

1. `docker ps --filter label=com.docker.compose.service=<service>`
2. fall back to direct `docker inspect <short-name>`
3. fall back to `-DockerSnapshotPath`

Emit extra fields in normalized output:

- `compose_service`
- `resolved_container_name`
- `check_source`

**Step 4: Re-run the targeted test**

Run: `py -3.12 -m pytest freshquant/tests/test_symphony_runtime_post_deploy_check.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add runtime/symphony/scripts/check_freshquant_runtime_post_deploy.ps1 freshquant/tests/test_symphony_runtime_post_deploy_check.py
git commit -m "feat: resolve runtime checks by compose service"
```

### Task 6: Make Compose Deploy Emit Reviewable Release Metadata

**Files:**
- Modify: `script/docker_parallel_compose.ps1`
- Test: `freshquant/tests/test_docker_runtime_policy.py`

**Step 1: Write the failing test**

Extend `freshquant/tests/test_docker_runtime_policy.py` so it fails unless the wrapper supports:

- explicit `-PrimaryWorktree`
- explicit `-ComposeEnvFile`
- explicit `-RuntimeLogDir`
- optional metadata output path
- timeout/review-oriented metadata fields

**Step 2: Run the targeted test**

Run: `py -3.12 -m pytest freshquant/tests/test_docker_runtime_policy.py -q`
Expected: FAIL because the wrapper currently only prints resolved env vars and executes docker.

**Step 3: Implement the wrapper changes**

Add parameters and metadata output similar to:

```powershell
param(
    [string]$PrimaryWorktree,
    [string]$ComposeEnvFile,
    [string]$RuntimeLogDir,
    [string]$EmitMetadataPath
)
```

Metadata should include:

- compose file
- primary worktree
- env file
- runtime log dir
- compose args
- start / end timestamp
- exit code

**Step 4: Re-run the targeted test**

Run: `py -3.12 -m pytest freshquant/tests/test_docker_runtime_policy.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add script/docker_parallel_compose.ps1 freshquant/tests/test_docker_runtime_policy.py
git commit -m "feat: add release metadata to docker deploy wrapper"
```

### Task 7: Add Frontend Release Probe For Web Deploy Verification

**Files:**
- Create: `script/freshquant_frontend_release_probe.py`
- Create: `freshquant/tests/test_freshquant_frontend_release_probe.py`
- Modify: `docs/current/deployment.md`
- Modify: `docs/current/runtime.md`
- Modify: `docs/current/troubleshooting.md`

**Step 1: Write the failing test**

Create `freshquant/tests/test_freshquant_frontend_release_probe.py` to require:

- parsing `index.html`
- extracting actual JS bundle paths
- scanning bundle content for required markers
- emitting JSON result with `bundle_path`, `markers`, `passed`

**Step 2: Run the test and verify failure**

Run: `py -3.12 -m pytest freshquant/tests/test_freshquant_frontend_release_probe.py -q`
Expected: FAIL because the script does not yet exist.

**Step 3: Implement the probe**

Use Python standard library only. Support:

```bash
py -3.12 script/freshquant_frontend_release_probe.py \
  --base-url http://127.0.0.1:18080 \
  --marker "全局 Trace" \
  --marker "组件 Event"
```

The script should:

- fetch `/runtime-observability` or `/`
- identify referenced JS bundles
- download the relevant runtime-observability bundle
- confirm marker presence
- print JSON

**Step 4: Re-run the targeted test**

Run: `py -3.12 -m pytest freshquant/tests/test_freshquant_frontend_release_probe.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add script/freshquant_frontend_release_probe.py freshquant/tests/test_freshquant_frontend_release_probe.py docs/current/deployment.md docs/current/runtime.md docs/current/troubleshooting.md
git commit -m "feat: add frontend release verification probe"
```

### Task 8: Wire Docs And Contracts To The New Stewardship Flow

**Files:**
- Modify: `docs/current/deployment.md`
- Modify: `docs/current/runtime.md`
- Modify: `docs/current/troubleshooting.md`
- Modify: `runtime/symphony/prompts/global_stewardship.md`
- Modify: `runtime/symphony/templates/global_stewardship_progress_comment.md`
- Modify: `runtime/symphony/templates/global_stewardship_done_comment.md`

**Step 1: Update docs to match actual behavior**

Ensure docs explicitly describe:

- clean worktree builds with primary repo env/log paths
- proxyless localhost checks as the formal health-check contract
- compose-service-aware runtime ops verify
- frontend release probe as part of `web` deploy verification
- command-timeout-goes-to-review, not instant failure

**Step 2: Re-read the prompt/template files**

Verify docs and prompts use the same order:

`fetch latest main -> deploy plan -> baseline -> deploy -> proxyless health -> runtime ops verify -> cleanup -> close`

**Step 3: Run prompt and docs regression tests**

Run:

```bash
py -3.12 -m pytest \
  freshquant/tests/test_symphony_prompt_contract.py \
  freshquant/tests/test_freshquant_deploy_plan.py \
  freshquant/tests/test_docker_runtime_policy.py \
  freshquant/tests/test_symphony_runtime_post_deploy_check.py \
  freshquant/tests/test_freshquant_health_check.py \
  freshquant/tests/test_freshquant_frontend_release_probe.py -q
```

Expected: PASS.

**Step 4: Run a steward-focused smoke check**

Run:

```bash
py -3.12 script/freshquant_deploy_plan.py --changed-path runtime/symphony/prompts/global_stewardship.md --format summary
powershell -ExecutionPolicy Bypass -File script/freshquant_health_check.ps1 -Url http://127.0.0.1:40123/api/v1/state -ExpectedStatus 200
```

Expected:

- deploy plan includes `symphony`
- health check returns structured success JSON

**Step 5: Commit**

```bash
git add docs/current/deployment.md docs/current/runtime.md docs/current/troubleshooting.md runtime/symphony/prompts/global_stewardship.md runtime/symphony/templates/global_stewardship_progress_comment.md runtime/symphony/templates/global_stewardship_done_comment.md
git commit -m "docs: align stewardship docs with hardened flow"
```

### Task 9: Final Verification Before Opening The Implementation PR

**Files:**
- Modify: `docs/current/deployment.md`
- Modify: `docs/current/runtime.md`
- Modify: `docs/current/troubleshooting.md`
- Modify: any files from Tasks 2-8

**Step 1: Run the full targeted suite**

Run:

```bash
py -3.12 -m pytest \
  freshquant/tests/test_symphony_prompt_contract.py \
  freshquant/tests/test_freshquant_deploy_plan.py \
  freshquant/tests/test_docker_runtime_policy.py \
  freshquant/tests/test_symphony_runtime_post_deploy_check.py \
  freshquant/tests/test_freshquant_health_check.py \
  freshquant/tests/test_freshquant_frontend_release_probe.py -q
```

Expected: all pass.

**Step 2: Run the web runtime-observability frontend tests if touched**

Run: `node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs`
Expected: PASS.

**Step 3: Inspect git diff**

Run: `git status --short`
Expected: only intended governance hardening changes remain.

**Step 4: Prepare PR summary**

Summarize:

- contract changes
- deploy/verify script hardening
- health check and frontend probe additions
- docs sync

**Step 5: Commit**

```bash
git add .
git commit -m "feat: harden global stewardship governance flow"
```
